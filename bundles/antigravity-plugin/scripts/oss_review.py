#!/usr/bin/env python3
"""Cross-vendor code review via any OpenAI-compatible chat-completions endpoint.

A different vendor's model has different blind spots, so a second model reviewing your diff
catches bugs a same-vendor reviewer misses. This tool is provider-agnostic: point it at
DeepSeek (default — cheapest + most architecturally distinct from Claude), GLM, OpenRouter,
or any OpenAI-compatible `/chat/completions` endpoint via three env vars.

Config precedence (highest wins): explicit CLI flag  >  env var  >  provider preset.
  REVIEW_PROVIDER   preset name: deepseek | glm | openrouter   (default deepseek)
  REVIEW_BASE_URL   base URL, no trailing /chat/completions    (overrides the preset's URL)
  REVIEW_MODEL      model id                                   (overrides the preset's model)
  REVIEW_API_KEY    bearer token                               (REQUIRED — no key ⇒ exit 3)

Future-proofing: model ids and endpoints churn. Two layers protect against that — (1) the PROVIDERS
table below is the ONE place a renamed model/URL is edited; (2) REVIEW_MODEL / REVIEW_BASE_URL env
vars always win, so you can point at any new id without touching code. Nothing here is hard-wired.

Usage:
  python oss_review.py [--range <git range>] [--cwd <repo>] [--provider P] [--base-url U] [--model M]
    --range   e.g. origin/main..HEAD   (default: the working tree — staged, unstaged AND
              untracked non-ignored files; a range excludes untracked by design)

Exit codes (fail-closed):
  0  REVIEW: CLEAN      — no blocking issues
  1  REVIEW: BLOCKING   — one or more blocking issues
  2  error              — no diff verdict parsed, git failure, endpoint/parse failure, or the diff
                          exceeds REVIEW_MAX_DIFF_CHARS (see below — never silently downgraded to CLEAN)
  3  misconfigured      — REVIEW_API_KEY missing (actionable message on stderr)

Diff-size ceiling: an oversized diff sent to a chat-completions endpoint has been observed, live, to
come back two different unsafe ways — an empty `content` field on an HTTP 200 (at least fails closed:
no verdict line ⇒ exit 2), and, worse, a `REVIEW: CLEAN` verdict with no substantive engagement (a
silent false negative — the model was overwhelmed, not actually reviewing). Rather than risk the second
case, a diff over REVIEW_MAX_DIFF_CHARS (default 60,000 chars; override via the env var or
--max-diff-chars) is SPLIT INTO BATCHES on whole-file boundaries and each batch reviewed separately;
the verdict is CLEAN only if every batch is clean (aggregation is fail-closed). Exit 2 is now the
narrower case: a SINGLE file larger than the ceiling, which cannot be split, or more batches than
MAX_REVIEW_BATCHES. Refusal was the original behaviour and is kept for those two - a silent false
CLEAN is the worst outcome this tool has - but it no longer fires on an ordinary large phase diff.

Stdlib-only (urllib) so it runs anywhere with no pip install.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

EXIT_CLEAN = 0
EXIT_BLOCKING = 1
EXIT_ERROR = 2
EXIT_CONFIG = 3

# Provider presets — the SINGLE place a renamed model id or moved endpoint is edited. Adding a new
# provider (Qwen, a local vLLM, …) is one new row. Callers can always bypass this via env/flags.
PROVIDERS: dict[str, dict[str, str]] = {
    "deepseek":   {"base_url": "https://api.deepseek.com",            "model": "deepseek-v4-flash"},
    "glm":        {"base_url": "https://api.z.ai/api/coding/paas/v4", "model": "glm-5.2"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1",        "model": "deepseek/deepseek-v4-flash"},
}
DEFAULT_PROVIDER = "deepseek"

# Tried, in order, ONLY when the primary provider fails at transport level (timeout, HTTP
# error, unparseable response) AND the user did not name a provider explicitly.
#
# Why a fallback rather than just picking one vendor: the whole point of this tool is that the
# reviewer is a DIFFERENT vendor from the author, so collapsing to a single provider means an
# outage leaves you with no second opinion and — worse — no signal that you have lost one.
# Observed on serve-sight across three consecutive phases: GLM timed out every time and the
# sessions recorded "cross-review inconclusive" and moved on. A review that silently does not
# happen is the same failure class as a diff that silently is not read.
#
# Order matters: DeepSeek leads because it has actually found real bugs (a date-boundary bug
# two same-vendor passes missed, an anchor bug, an orphaned-permission-rows bug). GLM is the
# spare tyre, not a co-equal — an alternation policy that sends half the phases to a provider
# that times out buys variety it never actually collects.
FALLBACK_PROVIDERS: tuple[str, ...] = ("glm",)

# Fail-closed diff-size ceiling (see the module docstring). Observed live: an oversized diff got back
# an empty `content` field (safe, but wasteful) on one occasion, and — separately, a bulk multi-document
# diff around 169,000 chars — a `REVIEW: CLEAN` verdict with zero substantive engagement (unsafe: a
# silent false negative). 60,000 chars is comfortably under both observed failure points while still
# covering an ordinary multi-file phase diff. REVIEW_MAX_DIFF_CHARS / --max-diff-chars override it.
DEFAULT_MAX_DIFF_CHARS = 60_000

# Every exception class that means "the request did not come back usable", so main() can route it
# to provider failover instead of letting it escape.
#
# `http.client.HTTPException` is the load-bearing entry and was MISSING. Its subclass
# `IncompleteRead` — a truncated response body, one of the two live failures behind
# `.caddis/parking-lot/006` — is NOT a ValueError despite the name suggesting a parse problem; its
# MRO is (IncompleteRead, HTTPException, Exception). So it escaped the handler entirely, Python
# exited 1, and 1 is EXIT_BLOCKING. A transport truncation was being reported to scripted callers
# as "the reviewer found blocking issues" — the same class of bug as the `content: null` crash
# documented in call_llm, in the same file, unfixed on the sibling path.
TRANSPORT_ERRORS = (
    urllib.error.URLError, urllib.error.HTTPError, http.client.HTTPException,
    RuntimeError, ValueError, TimeoutError, ConnectionError, OSError,
)

# How many times a failing chunk may be halved and retried before the run gives up. Two levels
# turns one 8-file batch into at most four 2-file requests, which is enough to clear a
# size-correlated truncation without turning a broken endpoint into sixteen doomed calls.
RETRY_SPLIT_DEPTH = 2


# A diff over the ceiling is split into batches on whole-FILE boundaries and each batch is
# reviewed separately, rather than the whole thing being refused. Refusing was correct while
# there was no alternative — a silent false CLEAN is the worst outcome this tool has — but it
# put the burden on the author, and the workaround people reached for (`git stash` to split
# the tree) mutates the working tree mid-verification and cost a hand-resolved merge conflict
# on serve-sight, 2026-08-03.
#
# Batching scales in both directions: a small change is one batch, identical in cost and
# behaviour to before; a 175k-char phase is three or four, with no judgement call about where
# to cut. Verdicts aggregate fail-closed (see `aggregate_verdicts`).
MAX_REVIEW_BATCHES = 12


class ConfigError(Exception):
    """Raised when configuration can't be resolved (unknown provider, or missing API key)."""


DEFAULT_KEYS_FILE = "~/.caddis/keys.env"


def _parse_keys_file(path: str) -> dict[str, str]:
    """Parse an INI/``KEY=VALUE`` keys file; missing file yields ``{}``.

    Mirror of claude-harness/scripts/oss_model.py::_parse_keys_file — duplicated (15 lines)
    rather than imported so this tool stays a single stdlib-only file that runs from any repo
    the runtime resources are exported into.
    """
    p = Path(path).expanduser()
    if not p.is_file():
        return {}
    out: dict[str, str] = {}
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def resolve_config(
    args: argparse.Namespace,
    env: dict[str, str],
    provider: str | None = None,
    use_overrides: bool = True,
) -> tuple[str, str, str]:
    """(base_url, api_key, model). Precedence: explicit flag > env var > provider preset.

    Never hard-fails on a model rename: a known --provider supplies sane defaults, and
    REVIEW_MODEL / REVIEW_BASE_URL override them without any code change.

    `provider` names one explicitly (used for fallback). `use_overrides=False` then ignores
    --model/--base-url/REVIEW_MODEL/REVIEW_BASE_URL, because those were chosen for the PRIMARY
    provider: pointing DeepSeek's model id at GLM's endpoint would turn a clean fallback into
    a confusing 404.
    """
    provider = (
        provider or args.provider or env.get("REVIEW_PROVIDER") or DEFAULT_PROVIDER
    ).strip().lower()
    preset = PROVIDERS.get(provider, {})
    if use_overrides:
        base_url = (args.base_url or env.get("REVIEW_BASE_URL") or preset.get("base_url") or "").rstrip("/")
        model = args.model or env.get("REVIEW_MODEL") or preset.get("model") or ""
    else:
        base_url = (preset.get("base_url") or "").rstrip("/")
        model = preset.get("model") or ""
    if not base_url or not model:
        known = ", ".join(sorted(PROVIDERS))
        raise ConfigError(
            f"could not resolve an endpoint for provider {provider!r}. Use a known --provider "
            f"({known}) or set REVIEW_BASE_URL and REVIEW_MODEL explicitly."
        )
    # Key precedence: REVIEW_API_KEY > provider env (DEEPSEEK_API_KEY, …) > OSS_API_KEY >
    # the caddis keys file — same resolution chain as the claude-oss launcher, so wiring
    # a provider once (in ~/.caddis/keys.env) lights up both lanes.
    key_env = f"{provider.upper()}_API_KEY"
    api_key = ""
    for name in ("REVIEW_API_KEY", key_env, "OSS_API_KEY"):
        api_key = (env.get(name) or "").strip()
        if api_key:
            break
    if not api_key:
        keys_path = env.get("CADDIS_KEYS_FILE") or DEFAULT_KEYS_FILE
        file_keys = _parse_keys_file(keys_path)
        for name in (key_env, "OSS_API_KEY"):
            api_key = (file_keys.get(name) or "").strip()
            if api_key:
                break
    if not api_key:
        # Name the providers that DO have a key. When DeepSeek is unset but GLM is configured, the
        # fix is `--provider glm` — and without this line the reader goes hunting for a credential
        # they already hold, at the least convenient possible moment (a commit pending).
        keys_path = env.get("CADDIS_KEYS_FILE") or DEFAULT_KEYS_FILE
        others = [p for p in configured_providers(env) if p != provider]
        have = (f"\nProviders that DO have a key here: {', '.join(others)}. "
                f"To use one now: --provider {others[0]}." if others else "")
        raise ConfigError(
            f"no API key for provider {provider!r}. Set $REVIEW_API_KEY or ${key_env}, or add\n"
            f"  {key_env}=<your-key>\n"
            f"to your keys file ({keys_path}). Override the file path with $CADDIS_KEYS_FILE."
            + have
        )
    return base_url, api_key, model


def configured_providers(env: dict[str, str]) -> list[str]:
    """Every preset provider that currently has a usable key. Never returns or logs a key value.

    Mirror of claude-harness/scripts/oss_model.py::configured_providers — duplicated for the same
    documented reason as `_parse_keys_file` above: this tool stays a single stdlib-only file that
    runs from any repo the runtime resources are exported into.

    Exists so a caller can find out BEFORE it needs a key. `/caddis:cross-review` used to discover
    a missing one mid-task with a commit pending, and a command that fails once at an inconvenient
    moment does not get retried — so the safety check it provides is quietly lost, and nothing
    records that it was lost (`.caddis/parking-lot/003`).
    """
    keys_path = env.get("CADDIS_KEYS_FILE") or DEFAULT_KEYS_FILE
    file_keys = _parse_keys_file(keys_path)
    generic = ((env.get("REVIEW_API_KEY") or env.get("OSS_API_KEY") or "").strip()
               or (file_keys.get("OSS_API_KEY") or "").strip())
    out = []
    for name in sorted(PROVIDERS):
        key_env = f"{name.upper()}_API_KEY"
        if generic or (env.get(key_env) or "").strip() or (file_keys.get(key_env) or "").strip():
            out.append(name)
    return out


def _untracked_files(cwd: str) -> list[str]:
    """New, non-ignored files git is not tracking yet. Empty list on any git failure."""
    out = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=30,
    )
    if out.returncode != 0:
        return []
    return [p for p in out.stdout.split("\0") if p]


def _untracked_diff(path: str, cwd: str) -> str:
    """A synthetic add-hunk for one untracked file, WITHOUT touching the index.

    `git add -N` would also work and is shorter, but it WRITES to the index — unacceptable
    in a review tool that routinely runs mid-session against a tree the user is still
    working in. `--no-index` gets the same diff with no side effect.

    Note the exit code: `git diff --no-index` returns 1 when the files differ, which is the
    normal outcome here. Only >1 is a real failure.
    """
    null = "/dev/null" if os.name != "nt" else "NUL"
    out = subprocess.run(
        ["git", "diff", "--no-index", "--", null, path],
        cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=30,
    )
    return out.stdout if out.returncode <= 1 else ""


def get_diff(rng: str | None, cwd: str, include_untracked: bool = True) -> str:
    """The unified diff for `rng` (e.g. 'origin/main..HEAD'), or the working tree when None.

    Working tree = staged + unstaged against HEAD, PLUS untracked non-ignored files.

    Untracked files are included because `git diff HEAD` reports only paths git already
    tracks, so a change consisting entirely of NEW files produced an empty diff — and the
    empty-diff branch in main() prints `REVIEW: CLEAN` and exits 0 without ever calling the
    model. A brand-new module is exactly the kind of change most worth reviewing, and it was
    the kind that silently got no review at all. Found on serve-sight 2026-08-02: four
    consecutive cross-review runs over a phase of mostly-new files reported CLEAN, and the
    real findings only appeared once the author happened to run `git add -A` first.

    Untracked files are NOT included for an explicit `rng` — a commit range is a span of
    history, and files that were never committed are correctly outside it.
    """
    cmd = ["git", "diff", rng] if rng else ["git", "diff", "HEAD"]
    # encoding pinned to UTF-8: git emits UTF-8, but text=True would decode with the locale
    # codepage (cp1252 on Windows) — a non-ASCII diff then kills the reader thread and
    # subprocess hands back stdout=None with returncode 0.
    out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=30)
    if out.returncode != 0:
        raise RuntimeError(f"git diff failed: {out.stderr.strip()}")
    if rng or not include_untracked:
        return out.stdout
    extra = "".join(_untracked_diff(p, cwd) for p in _untracked_files(cwd))
    # Concatenated BEFORE returning so the caller's REVIEW_MAX_DIFF_CHARS ceiling measures
    # the true payload rather than the tracked-only fraction of it.
    return out.stdout + extra


def split_diff_by_file(diff_text: str) -> list[str]:
    """The diff cut into per-file chunks on `diff --git` boundaries.

    Splitting on file boundaries, never mid-file: half a file's hunks is worse than no
    review of it, because the model confidently reasons about code it cannot see.
    """
    if not diff_text.strip():
        return []
    parts: list[str] = []
    current: list[str] = []
    for line in diff_text.splitlines(keepends=True):
        if line.startswith("diff --git ") and current:
            parts.append("".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        parts.append("".join(current))
    return parts


def batch_diff(diff_text: str, max_chars: int) -> list[str]:
    """Pack whole files into as few batches as possible, each under `max_chars`.

    A single file larger than the ceiling gets its own batch and is sent anyway — it is
    over the limit either way, and reviewing it is strictly better than skipping it. The
    caller reports how many batches were used so an oversized single file is visible.
    """
    files = split_diff_by_file(diff_text)
    if not files:
        return []
    batches: list[str] = []
    current = ""
    for chunk in files:
        if current and len(current) + len(chunk) > max_chars:
            batches.append(current)
            current = chunk
        else:
            current += chunk
    if current:
        batches.append(current)
    return batches


def aggregate_verdicts(verdicts: list[bool | None]) -> bool | None:
    """Fail-closed roll-up: any BLOCKING wins; CLEAN only if EVERY batch was clean.

    A batch with no parseable verdict (`None`) poisons the result to `None`, which the
    caller maps to EXIT_ERROR — the same fail-closed rule as the single-batch path. An
    unreviewed batch must never be able to produce a CLEAN overall.
    """
    if not verdicts:
        return None
    if any(v is False for v in verdicts):
        return False
    if any(v is None for v in verdicts):
        return None
    return True


def current_branch(cwd: str) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10,
        )
        return out.stdout.strip() or "the current branch"
    except Exception:
        return "the current branch"


def build_review_prompt(diff_text: str, branch: str, rng: str | None) -> str:
    """Adversarial review prompt — ported from docket runner._review_prompt (kept in sync).

    Self-contained: the criteria are inline so a real review always happens, and it ends with
    a single machine-parseable verdict line the caller maps to an exit code.
    """
    scope = rng or "the working tree (staged, unstaged and new untracked files)"
    return (
        f"Perform an adversarial code review of the changes on branch '{branch}' ({scope}). "
        "The unified diff is provided below. Judge, in priority order: (1) correctness — logic "
        "bugs, wrong results, missed edge cases; (2) tests — would a test fail without this "
        "change, and are the stated behaviors covered; (3) security — injection, auth, secret "
        "exposure, unvalidated input; (4) conventions — the repo's stated rules; (5) simplicity. "
        "Classify each issue as blocking (must fix before merge), should-fix, or nit. Be "
        "specific: cite the file and line. Do not invent issues; if the diff is clean, say so.\n\n"
        "End with EXACTLY one line and nothing after it: `REVIEW: CLEAN` (no blocking issues) or "
        "`REVIEW: BLOCKING` (one or more blocking issues).\n\n"
        "----- BEGIN DIFF -----\n"
        f"{diff_text}\n"
        "----- END DIFF -----"
    )


def classify_verdict(text: str) -> bool | None:
    """CLEAN→True, BLOCKING→False, neither→None. Fail-closed: any blocking signal wins."""
    u = text.upper()
    if "REVIEW: BLOCKING" in u:
        return False
    if "REVIEW: CLEAN" in u:
        return True
    return None


def call_llm(base_url: str, api_key: str, model: str, prompt: str, timeout: int = 180) -> str:
    """POST to {base_url}/chat/completions (OpenAI-compatible) → the assistant message text.

    Raises on transport, HTTP, or response-shape failure so main() maps it to EXIT_ERROR.
    """
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"unexpected response shape from endpoint: {exc}") from exc
    # An HTTP 200 carrying empty or null content is a REAL observed failure (see the module
    # docstring: an oversized diff came back with an empty `content` field). Returning it
    # unraised had two bad consequences, both silent:
    #   - it never reached the `except` in main(), so the provider FAILOVER never fired — the
    #     run died having never tried the spare, which is the exact case failover exists for;
    #   - `content: null` (legal in OpenAI-compatible responses) returned None, and
    #     `classify_verdict(None)` then raised AttributeError. Uncaught, Python exits 1 —
    #     which is EXIT_BLOCKING. A crash was being reported to scripted callers as "the
    #     reviewer found blocking issues."
    # Raising here routes both into the existing retry/failover path and kills the crash.
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError(
            "endpoint returned HTTP 200 with empty or absent message content "
            f"(type={type(content).__name__}) — treating as a provider failure"
        )
    return content


def _force_utf8_stdio() -> None:
    """Make stdout/stderr survive a review written by a model, on any console.

    A review is prose, and prose from a model contains →, —, ’, … or ≥ sooner or later. A
    Windows console defaults to cp1252, where `print(review)` raises UnicodeEncodeError —
    AFTER the provider round-trip has already been paid for (~8 minutes, observed) and, because
    the print sits inside the per-batch loop, killing every remaining batch with it. Worse, the
    caller sees a traceback and a non-zero exit, which is indistinguishable from a provider
    timeout: the documented response is "switch vendor and retry", so the next move burns
    another full review on the other provider and hits the identical crash, because the cause is
    local stdout encoding, not the provider.

    `errors="replace"` is the load-bearing part: a mangled arrow is a far better outcome than a
    discarded review. Guarded because stdout may already have been swapped for something without
    `.reconfigure` (pytest's capture, a pipe wrapper) — in which case there is nothing to fix.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # pragma: no cover — defensive; never lose a review to this
            pass


def main(argv: list[str] | None = None, env: dict[str, str] | None = None) -> int:
    _force_utf8_stdio()
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(description="Cross-vendor code review via an OpenAI-compatible endpoint.")
    parser.add_argument("--range", dest="range", default=None,
                        help="git range to review (e.g. origin/main..HEAD); default = working tree")
    parser.add_argument("--cwd", default=".", help="repo directory (default: cwd)")
    parser.add_argument("--provider", default=None,
                        help=f"preset: {', '.join(sorted(PROVIDERS))} (default {DEFAULT_PROVIDER}); env REVIEW_PROVIDER")
    parser.add_argument("--base-url", dest="base_url", default=None, help="override REVIEW_BASE_URL / the preset")
    parser.add_argument("--model", default=None, help="override REVIEW_MODEL / the preset")
    parser.add_argument("--max-diff-chars", type=int, default=None,
                        help=f"override REVIEW_MAX_DIFF_CHARS (default {DEFAULT_MAX_DIFF_CHARS})")
    parser.add_argument("--check-config", action="store_true",
                        help="report whether a usable key exists and exit — no diff, no LLM call. "
                             "Exit 0 = ready, 3 = nothing configured.")
    args = parser.parse_args(argv)

    # --check-config is deliberately NON-INTERACTIVE. This script runs headless — from CI, from a
    # docket runner, from a `claude -p` session — where a prompt on stdin does not ask a question,
    # it hangs forever. The ASKING belongs in `/caddis:cross-review`, which is driven by an agent
    # that can actually talk to a human. This half just answers "is it configured?" cheaply enough
    # to call before you need it, instead of finding out mid-commit.
    if args.check_config:
        available = configured_providers(env)
        if not available:
            sys.stderr.write(
                "no second-vendor API key is configured anywhere.\n"
                "  Cross-review needs one — the whole point is a reviewer that does not share this\n"
                "  model's blind spots, so a same-vendor fallback would be no review at all.\n"
                f"  Add a key to {env.get('CADDIS_KEYS_FILE') or DEFAULT_KEYS_FILE}, e.g.\n"
                "    DEEPSEEK_API_KEY=<your-key>\n")
            return EXIT_CONFIG
        print(f"cross-review is ready. Providers with a key: {', '.join(available)}")
        return EXIT_CLEAN

    try:
        base_url, api_key, model = resolve_config(args, env)
        primary_provider = (
            args.provider or env.get("REVIEW_PROVIDER") or DEFAULT_PROVIDER
        ).strip().lower()
    except ConfigError as exc:
        sys.stderr.write(f"{exc}\n")
        return EXIT_CONFIG

    try:
        diff_text = get_diff(args.range, args.cwd)
    except Exception as exc:
        sys.stderr.write(f"could not read diff: {exc}\n")
        return EXIT_ERROR

    if not diff_text.strip():
        # Says what was scanned, not just that nothing was found. This branch used to fire
        # on a tree full of NEW files (they are invisible to `git diff HEAD`) and report
        # CLEAN without calling the model — a silent false negative that reads identically
        # to a real pass. Untracked files are in scope now; naming the scope keeps the
        # message honest if that ever regresses.
        print(f"No changes to review in {args.range or 'the working tree (incl. untracked)'}.")
        print("REVIEW: CLEAN")
        return EXIT_CLEAN

    max_diff_chars = args.max_diff_chars
    if max_diff_chars is None:
        env_val = (env.get("REVIEW_MAX_DIFF_CHARS") or "").strip()
        max_diff_chars = int(env_val) if env_val.isdigit() else DEFAULT_MAX_DIFF_CHARS
    batches = batch_diff(diff_text, max_diff_chars) or [diff_text]
    # Batching only helps when the diff HAS file boundaries to cut on. A single file (or a
    # blob with no `diff --git` headers) larger than the ceiling cannot be split, and sending
    # it anyway would reintroduce exactly the silent false-CLEAN the ceiling exists to stop.
    # Refuse, as before — the guarantee is absolute: no prompt over the ceiling is ever sent.
    if any(len(b) > max_diff_chars for b in batches):
        biggest = max(batches, key=len)
        first_line = biggest.splitlines()[0][:120] if biggest.strip() else "(no file header)"
        sys.stderr.write(
            f"diff is {len(diff_text):,} chars and contains a single chunk of {len(biggest):,}, "
            f"over the {max_diff_chars:,}-char review ceiling — refusing rather than risk an "
            "unreviewable prompt silently coming back CLEAN.\n"
            f"  Largest chunk starts: {first_line}\n"
            + (
                # The working tree includes untracked files by design (that fix stopped a
                # false-CLEAN on all-new-file phases), which means an agent's own uncommitted
                # plans/PRDs are counted as "the diff". Observed live: 77k of untracked
                # .caddis/ markdown pushed a real phase over the ceiling. Reviewing the phase's
                # commit range is both the workaround AND the more accurate scope, so name it
                # as a literal command instead of leaving each caller to rediscover it.
                "  You are reviewing the WORKING TREE, which includes untracked files — "
                "uncommitted docs/plans count toward this total.\n"
                "  If the phase is already committed, review its commits instead (usually the "
                "scope you actually want):\n"
                "      --range HEAD~1..HEAD\n"
                if args.range is None
                else "  Narrow --range to a smaller commit span, or review file-by-file.\n"
            )
            + "  Override (not recommended without knowing your endpoint's real limit): "
            "--max-diff-chars <n> or $REVIEW_MAX_DIFF_CHARS.\n"
        )
        return EXIT_ERROR
    if len(batches) > MAX_REVIEW_BATCHES:
        # Loud, never a silent truncation: a capped review that reads like a complete one is
        # the same class of lie as an oversized prompt coming back CLEAN.
        sys.stderr.write(
            f"diff is {len(diff_text):,} chars — {len(batches)} batches, over the "
            f"{MAX_REVIEW_BATCHES}-batch cap. Refusing rather than reviewing part of it and "
            "reporting a verdict that looks whole.\n"
            "  Narrow --range to a smaller commit span, or raise --max-diff-chars if you know "
            "your endpoint's real limit.\n"
        )
        return EXIT_ERROR
    if len(batches) > 1:
        print(
            f"[cross-review] diff is {len(diff_text):,} chars, over the {max_diff_chars:,} "
            f"ceiling — reviewing in {len(batches)} batches split on file boundaries. "
            "Verdict is CLEAN only if every batch is clean."
        )

    branch = current_branch(args.cwd)

    # Fall back to another vendor only when the user did NOT name one. If they asked for a
    # specific provider, silently reviewing with a different one would misreport who checked
    # the code — the single fact this tool exists to establish.
    # "Explicit" must include a custom ENDPOINT, not just a named preset. Someone who set
    # REVIEW_BASE_URL/REVIEW_MODEL (the documented future-proofing path) has named exactly who
    # should review their code; falling back to the GLM preset would misreport the reviewer —
    # the one fact this tool exists to establish.
    explicit = bool(
        args.provider or env.get("REVIEW_PROVIDER")
        or args.base_url or env.get("REVIEW_BASE_URL")
        or args.model or env.get("REVIEW_MODEL")
    )
    chain: list[tuple[str, str, str, str]] = [(primary_provider, base_url, api_key, model)]
    if not explicit:
        for name in FALLBACK_PROVIDERS:
            if name == primary_provider:
                continue
            try:
                fb_url, fb_key, fb_model = resolve_config(args, env, provider=name, use_overrides=False)
            except ConfigError:
                continue  # no key for the spare — not an error, just nothing to fall back to
            chain.append((name, fb_url, fb_key, fb_model))

    def _try_chain(prompt: str, label: str) -> str | None:
        """One payload against every provider in the chain. None when all of them failed."""
        for idx, (name, url, key, mdl) in enumerate(chain):
            try:
                review = call_llm(url, key, mdl, prompt)
            except TRANSPORT_ERRORS as exc:
                remaining = len(chain) - idx - 1
                sys.stderr.write(
                    f"review request failed{label} ({mdl} @ {url}): {exc}\n"
                    + (
                        f"  falling back to {chain[idx + 1][0]}...\n"
                        if remaining
                        else "  If the model id was renamed, set REVIEW_MODEL to the current id "
                             "(env overrides the preset).\n"
                    )
                )
                continue
            if idx:
                # Loud on purpose. A verdict from a different vendor than the one requested is
                # a material fact about the review, not an implementation detail — it belongs
                # in the transcript the phase report quotes.
                print(f"[cross-review] {chain[0][0]} unavailable; reviewed by {name} ({mdl}).")
            return review
        return None

    def _review_chunk(chunk: str, label: str, depth: int = 0) -> list[str] | None:
        """Review `chunk`, halving it and retrying once per level if every provider failed.

        WHY HALVE RATHER THAN JUST FAIL. Both observed failures were transport truncation on a
        long reply — an `http.client.IncompleteRead` on one provider and an empty HTTP 200 body on
        another — and both were SIZE-CORRELATED. Retrying the same payload against the same
        endpoint reproduces the same overflow; retrying a smaller one usually does not. The whole
        run used to abort here, which is safe but throws away a review the user has already
        waited minutes for.

        Bounded at RETRY_SPLIT_DEPTH levels and never splits a single file, so it cannot loop and
        cannot silently shrink a diff to nothing. Returns None when a chunk that cannot be split
        any further still fails — the abort path stays reachable.
        """
        review = _try_chain(build_review_prompt(chunk, branch, args.range), label)
        if review is not None:
            return [review]
        files = split_diff_by_file(chunk)
        if depth >= RETRY_SPLIT_DEPTH or len(files) < 2:
            return None
        half = len(files) // 2
        sys.stderr.write(
            f"[cross-review] retrying{label} as 2 smaller chunks ({half} + {len(files) - half} "
            "file(s)) — both observed failures were size-correlated truncation.\n")
        out: list[str] = []
        for part_no, part in enumerate(("".join(files[:half]), "".join(files[half:])), 1):
            got = _review_chunk(part, f"{label} part {part_no}", depth + 1)
            if got is None:
                return None
            out += got
        return out

    verdicts: list[bool | None] = []
    for batch_no, batch in enumerate(batches, 1):
        label = f" (batch {batch_no}/{len(batches)})" if len(batches) > 1 else ""
        if len(batches) > 1:
            files = len(split_diff_by_file(batch))
            print(f"\n===== batch {batch_no}/{len(batches)} — {files} file(s), "
                  f"{len(batch):,} chars =====")

        reviews = _review_chunk(batch, label)
        if reviews is None:
            # Every provider failed, and splitting did not rescue it. Do NOT continue to the next
            # batch: a partial sweep that still prints a verdict is the failure mode this whole
            # tool guards against.
            sys.stderr.write(f"batch {batch_no}/{len(batches)} could not be reviewed — aborting.\n")
            return EXIT_ERROR

        for review in reviews:
            print(review)
            verdicts.append(classify_verdict(review))

    verdict = aggregate_verdicts(verdicts)
    if len(batches) > 1:
        # A LEDGER, not a summary. The live report behind `.caddis/parking-lot/006` said the
        # reader's only defence was "count the REVIEW: lines against the announced batch count" —
        # so print that arithmetic instead of making a human do it. `reviewed` can exceed
        # `announced` when a batch was split and retried, and that is worth seeing.
        clean = sum(1 for v in verdicts if v is True)
        blocking = sum(1 for v in verdicts if v is False)
        unparsed = sum(1 for v in verdicts if v is None)
        print(f"\n[cross-review] announced {len(batches)} batches · reviewed {len(verdicts)} · "
              f"clean {clean} · blocking {blocking} · no parseable verdict {unparsed}")
        if unparsed:
            print("[cross-review] a chunk with no verdict is NOT a pass — the overall result "
                  "below is fail-closed.")
    if verdict is True:
        return EXIT_CLEAN
    if verdict is False:
        return EXIT_BLOCKING
    sys.stderr.write("no REVIEW: CLEAN|BLOCKING verdict line found in the model output\n")
    return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
