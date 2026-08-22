"""Deterministic Dream Memory capture from a Stop transcript (fann Phase 5b).

Pure, filesystem-free extraction of *high-confidence* fact candidates from a parsed transcript,
plus privacy redaction. The hook (``session_end.py``) does the I/O — read the transcript, call
:func:`extract_facts`, then consolidate via ``dream_memory`` and rewrite the store. Keeping the
logic here (dicts in → dicts out) makes it unit-testable without a tree, mirroring the engine.

Two kinds are captured (the only ones inferable *without an LLM* — the rich kinds come from the
knowledge-transfer agent in 5d):
  • **failure-mode** — a ``Bash`` tool call whose result is an error (``is_error``). One candidate
    per distinct command per session; cross-session recurrence is what reinforces it.
  • **workflow-success** — a *build/test* command that succeeded after the same command failed
    earlier in the same session (the red→green signal).

PRIVACY (hard constraint, see the design doc): a fact must be safe to print at SessionStart and
(eventually) to commit. So we (1) **skip entirely** any command that touches a secret file
(``.env``, ``**/secrets/**``, ``*.pem``/``*.key``, credential files — guard.py's secret sense),
and (2) **redact** inline secrets (``KEY=…``, ``--token …``, ``Bearer …``, URLs with credentials,
known token shapes, long high-entropy blobs) from both the command head and the error line. The
dedup key derives from the *redacted* command, so a token can never leak into the store's key.
"""

from __future__ import annotations

import hashlib
import re

from dream_memory import make_fact, normalize_key  # sibling module in scripts/

# --------------------------------------------------------------------------- #
# Limits — keep the store lean and a single Stop's append bounded.
# --------------------------------------------------------------------------- #
MAX_FACTS_PER_RUN = 15      # cap candidates emitted from one transcript
_HEAD_LEN = 80              # command head kept (we store heads, not full args)
_ERR_LEN = 120             # first error line kept
_SUMMARY_LEN = 200          # final clamp on a summary


# --------------------------------------------------------------------------- #
# Privacy — redaction + secret-path skip. Mirrors guard.py's secret sense but
# operates on inline text (value-level scrubbing), not just file-path classing.
# --------------------------------------------------------------------------- #
_URL_CRED = re.compile(r"(\w[\w+.\-]*://)[^/\s:@]+:[^/\s@]+@")
_SENSITIVE_KEY = re.compile(
    r"\b([A-Za-z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|PWD|CREDENTIAL|CREDENTIALS|AUTH|APIKEY|PRIVATE)[A-Za-z0-9_]*)"
    r"(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|\S+)",
    re.I,
)
_SENSITIVE_FLAG = re.compile(
    r"(--?(?:password|passwd|pwd|token|secret|api[-_]?key|access[-_]?key|auth)\b)(\s+|=)(\"[^\"]*\"|'[^']*'|\S+)",
    re.I,
)
# MySQL/MariaDB attached-password flag: `-pVALUE` glued to the flag (no separator).
# Scoped to mysql-family commands so `cp -pr`, `mkdir -p`, `docker -p 8080:80`,
# `ssh -p22` are never touched. Value may be quoted (`-p"my pass"`).
_MYSQL_PW = re.compile(
    r"(\b(?:mysql|mysqldump|mariadb|mysqladmin)\b[^\n]*?\s-p)(\"[^\"]*\"|'[^']*'|\S+)",
    re.I,
)
# curl basic-auth: `-u user:pass` / `--user user:pass` (value may be glued to -u).
# Scoped to curl so `python -u`, `sort -u`, `docker run -u 1000:1000` survive.
_CURL_USERPASS = re.compile(
    r"(\bcurl\b[^\n]*?\s(?:--user|-u)\s*)(\"[^\"]*\"|'[^']*'|\S+)",
    re.I,
)
# AWS credential keys given WHITESPACE-separated (e.g. `aws configure set
# aws_secret_access_key <k>`); the `=`/`:` form is already caught by _SENSITIVE_KEY.
_AWS_CRED = re.compile(
    r"\b(aws_secret_access_key|aws_access_key_id|aws_session_token)\b"
    r"(\s+|\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|\S+)",
    re.I,
)
_AUTH_HEADER = re.compile(r"\b(authorization|x-api-key)\b(\s*:\s*|\s+)(?:bearer\s+)?\S+", re.I)
_BEARER = re.compile(r"\bbearer\s+[A-Za-z0-9._\-]+", re.I)
_TOKEN_PREFIX = re.compile(
    r"\b(?:gh[posru]_[A-Za-z0-9]{6,}|sk-[A-Za-z0-9]{6,}|xox[baprs]-[A-Za-z0-9-]{6,}|AKIA[0-9A-Z]{12,})"
)
# Long high-entropy blob (a letter AND a digit, ≥40 chars). Excludes '/' so file paths survive.
_LONG_TOKEN = re.compile(r"\b(?=[A-Za-z0-9+=_\-]*[A-Za-z])(?=[A-Za-z0-9+=_\-]*[0-9])[A-Za-z0-9+=_\-]{40,}\b")

_SECRET_PATH = re.compile(
    r"(?:^|[\s=:'\"/\\])\.env(?:\.|$|[\s'\"/\\])"
    r"|[/\\]\.?secrets?[/\\]"
    r"|\b(?:id_rsa|id_dsa|id_ecdsa|id_ed25519|credentials|\.npmrc|\.pypirc|\.netrc|\.pgpass|\.htpasswd)\b"
    r"|\.(?:pem|key|p12|pfx|keystore|jks)\b",
    re.I,
)


def redact(text: str) -> str:
    """Scrub inline secrets from ``text`` so it's safe to store, surface, and commit.

    Order matters: credentialed URLs first, then whole-value header/bearer forms (these must run
    before the generic ``KEY=…`` rule, else "Authorization" matches as a key and only eats the
    word "Bearer", leaking the token), then explicit ``KEY=…`` / ``--token …`` assignments, then
    known token prefixes, then a catch-all for long high-entropy blobs. Conservative on file paths
    (the blob rule excludes ``/``) so an error line stays useful.
    """
    if not text:
        return ""
    t = str(text)
    t = _URL_CRED.sub(r"\1***:***@", t)
    t = _AUTH_HEADER.sub(r"\1: ***", t)
    t = _BEARER.sub("bearer ***", t)
    t = _SENSITIVE_KEY.sub(r"\1=***", t)
    t = _AWS_CRED.sub(r"\1 ***", t)
    t = _SENSITIVE_FLAG.sub(r"\1 ***", t)
    t = _CURL_USERPASS.sub(r"\1***", t)
    t = _MYSQL_PW.sub(r"\1***", t)
    t = _TOKEN_PREFIX.sub("***", t)
    t = _LONG_TOKEN.sub("***", t)
    return t


def touches_secret(command: str) -> bool:
    """True if ``command`` references a secret file/path — such a fact is never stored at all."""
    return bool(_SECRET_PATH.search(command or ""))


# --------------------------------------------------------------------------- #
# Text shaping
# --------------------------------------------------------------------------- #
def command_head(command: str, max_len: int = _HEAD_LEN) -> str:
    """Whitespace-collapsed, length-capped command head — we store heads, not full arg lists."""
    c = " ".join((command or "").split())
    return c[:max_len].rstrip()


def command_fp(command: str) -> str:
    """Stable dedup fingerprint of the FULL command (whitespace-collapsed, lowercased), hashed so two
    distinct commands that share a truncated 80-char head don't merge into one inflated fact. Kept
    separate from the display head on purpose. Pass the ALREADY-REDACTED command so no secret is hashed."""
    norm = " ".join((command or "").split()).lower()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def first_error_line(output: str, max_len: int = _ERR_LEN) -> str:
    """First non-empty line of tool output, length-capped — the error's gist, not the whole dump."""
    for line in (output or "").splitlines():
        s = line.strip()
        if s:
            return s[:max_len]
    return ""


# Commands whose non-zero exit is routine control flow / a search miss — not a durable lesson.
_NOISE_FIRST_TOKEN = frozenset({
    "grep", "rg", "test", "[", "find", "ls", "cat", "which", "type", "head", "tail", "diff",
})

# Build/test commands — only these qualify for the red→green workflow-success signal.
_BUILD_TEST = re.compile(
    r"\b(?:pytest|tox|nox|unittest|jest|vitest|mocha|"
    r"npm\s+(?:run\s+\S+|test|ci)|yarn\s+\S+|pnpm\s+\S+|"
    r"vite(?:\s+build)?|tsc\b|go\s+(?:test|build)|cargo\s+(?:test|build)|"
    r"make\b|gradle\b|mvn\b|dotnet\s+(?:test|build)|rspec|phpunit)\b",
    re.I,
)


def _is_noise_failure(command: str) -> bool:
    toks = (command or "").strip().split()
    return bool(toks) and toks[0] in _NOISE_FIRST_TOKEN


# --------------------------------------------------------------------------- #
# Transcript walking
# --------------------------------------------------------------------------- #
def _content_blocks(record: dict) -> list[dict]:
    """The list of content blocks in a transcript record (handles the nested ``message`` shape)."""
    if not isinstance(record, dict):
        return []
    msg = record.get("message") if isinstance(record.get("message"), dict) else record
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def _result_text(block: dict) -> str:
    """Flatten a tool_result's content (string or list-of-{text}) to plain text."""
    c = block.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = [item["text"] for item in c if isinstance(item, dict) and isinstance(item.get("text"), str)]
        return "\n".join(parts)
    return ""


def extract_facts(records: list[dict], observed_at: str) -> list[dict]:
    """Mine deterministic fact candidates from parsed transcript ``records`` (in order).

    Returns at most :data:`MAX_FACTS_PER_RUN` ``make_fact`` dicts. Pure: no I/O, no mutation of
    inputs. Secret-touching commands are skipped wholesale; all stored text is redacted.
    """
    # Pass 1: map Bash tool_use id → command.
    uses: dict[str, str] = {}
    for rec in records:
        for b in _content_blocks(rec):
            if b.get("type") == "tool_use" and b.get("name") == "Bash":
                tid = b.get("id")
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                cmd = inp.get("command")
                if tid and isinstance(cmd, str) and cmd.strip():
                    uses[tid] = cmd

    # Pass 2: walk results in order — failures first feed the red→green check for later successes.
    facts: list[dict] = []
    failed_keys: set[str] = set()
    emitted: set[str] = set()

    for rec in records:
        for b in _content_blocks(rec):
            if b.get("type") != "tool_result":
                continue
            cmd = uses.get(b.get("tool_use_id"))
            if not cmd or touches_secret(cmd):
                continue  # unknown tool, or a secret-touching command we refuse to record

            red = redact(cmd)
            head = command_head(red)
            key = normalize_key(head)
            if not key:
                continue
            fp = command_fp(red)  # full-command dedup identity (the display key stays the 80-char head)

            if bool(b.get("is_error")):
                if _is_noise_failure(cmd):
                    continue
                failed_keys.add(fp)
                if fp in emitted:
                    continue  # one failure candidate per distinct command per session
                emitted.add(fp)
                errline = redact(first_error_line(_result_text(b)))
                summary = (f"`{head}` failed: {errline}" if errline else f"`{head}` failed")[:_SUMMARY_LEN]
                facts.append(make_fact("failure-mode", key, summary, observed_at, source="auto", fp=fp))
            else:
                # Success → only a fact if a build/test command recovered from an earlier failure.
                ok_key = "ok:" + fp
                if _BUILD_TEST.search(cmd) and fp in failed_keys and ok_key not in emitted:
                    emitted.add(ok_key)
                    summary = (f"`{head}` passes now — was failing earlier this session")[:_SUMMARY_LEN]
                    facts.append(make_fact("workflow-success", key, summary, observed_at, source="auto", fp=fp))

            if len(facts) >= MAX_FACTS_PER_RUN:
                return facts

    return facts
