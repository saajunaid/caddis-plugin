#!/usr/bin/env python3
"""Cross-vendor code review via any OpenAI-compatible chat-completions endpoint.

A different vendor's model has different blind spots, so a second model reviewing your diff
catches bugs a same-vendor reviewer misses. This tool is provider-agnostic: point it at
agy Argon (default since 2026-10-21; needs no key), DeepSeek (cheap, architecturally distinct from
Claude), GLM, OpenRouter, or any OpenAI-compatible `/chat/completions` endpoint via three env vars.

Config precedence (highest wins): explicit CLI flag  >  env var  >  provider preset.
  REVIEW_PROVIDER   preset name: agy-argon | deepseek | glm | openrouter   (default agy-argon)
                    precedence: --provider flag, process env, then REVIEW_PROVIDER in ~/.caddis/keys.env
  REVIEW_BASE_URL   base URL, no trailing /chat/completions    (overrides the preset's URL)
  REVIEW_MODEL      model id                                   (overrides the preset's model)
  REVIEW_API_KEY    bearer token                               (REQUIRED for an HTTP provider; agy-argon needs none)

Future-proofing: model ids and endpoints churn. Two layers protect against that — (1) the PROVIDERS
table below is the ONE place a renamed model/URL is edited; (2) REVIEW_MODEL / REVIEW_BASE_URL env
vars always win, so you can point at any new id without touching code. Nothing here is hard-wired.

Usage:
  python oss_review.py [--range <git range>] [--cwd <repo>] [--provider P] [--base-url U] [--model M]
                        [--allow-path GLOB ...]
    --range        e.g. origin/main..HEAD   (default: the working tree — staged, unstaged AND
                   untracked non-ignored files; a range excludes untracked by design)
    --allow-path   repeatable; re-admits a file the pre-send secret filter's deny list would
                   otherwise drop (see secret_filter.py). `.caddis/config.toml`'s
                   `[review] deny_paths` / `allow_paths` are layered on the same way.

Exit codes (fail-closed):
  0  REVIEW: CLEAN      — no blocking issues
  1  REVIEW: BLOCKING   — one or more blocking issues
  2  unused             — advisory is not a review verdict
  3  could not run      — REVIEW_API_KEY missing, OR the pre-send secret filter refused (a
                          denylisted path / possible secret; see secret_filter.py), OR every
                          provider failed with a PROVIDER failure: HTTP 429, any 5xx, a timeout, a
                          connection error, an empty reply, an agy error status, or the agy spend
                          cap refused — actionable message on stderr/stdout either way
  4  error              — no diff verdict parsed, git failure, other endpoint/parse failure, or the diff
                          exceeds REVIEW_MAX_DIFF_CHARS (see below — never silently downgraded to CLEAN)

Provider chain (owner policy, 2026-10-21; was deepseek first from 2026-10-16): agy-argon -> deepseek -> glm.
A named --provider goes first, then the rest in policy order; a provider with no key (or no agy on PATH)
is skipped. With no provider named, the chain starts at the first provider that is available. A provider failure
moves to the next provider and never splits the diff. On HTTP 429 a `Retry-After` is honoured ONCE per
provider (capped at 60 s), then the next provider is tried. A provider that failed gets no more calls in
the same run. agy runs through `caddis_spend.py run` (the EUR spend cap), in plan mode, with the diff in
the prompt (no tools needed). The secret filter runs once, before any provider, agy included. The
provider that gave each verdict is printed.

Diff-size ceiling: an oversized diff sent to a chat-completions endpoint has been observed, live, to
come back two different unsafe ways — an empty `content` field on an HTTP 200 (at least fails closed:
no verdict line ⇒ exit 4), and, worse, a `REVIEW: CLEAN` verdict with no substantive engagement (a
silent false negative — the model was overwhelmed, not actually reviewing). Rather than risk the second
case, a diff over REVIEW_MAX_DIFF_CHARS (default 60,000 chars; override via the env var or
--max-diff-chars) is SPLIT INTO BATCHES on whole-file boundaries and each batch reviewed separately;
the verdict is CLEAN only if every batch is clean (aggregation is fail-closed). Exit 4 is the
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
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# secret_filter.py ships beside this file in every export target (see
# .github/runtime-targets.json) — import it from THIS script's own folder, not the caller's
# cwd, so it resolves the same way whether this runs from the source repo or a plugin install.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import secret_filter  # noqa: E402

# ONE SCALE ACROSS caddis (see claude-harness/README.md):
#   0 clean · 1 blocked · 2 advisory note · 3 could not run · 4 malformed
# ERROR moved 2 -> 4 on 2026-09-09. It sat on 2, which caddis_gate uses for "proceed, this is
# worth saying" — the exact opposite, and in the dangerous direction: a caller treating 2 as
# advisory silently accepts a review that never ran. That is the 2026-08-10 shape, where a stale
# copy of this file returned CLEAN on a database write path nobody had reviewed.
# 2 is left FREE here. This tool has no advisory verdict; a slot that means one thing everywhere
# is worth more than a slot reused for something else.
EXIT_CLEAN = 0
EXIT_BLOCKING = 1
EXIT_CONFIG = 3     # could not run: no key, no provider, bad configuration
EXIT_ERROR = 4      # ran, produced nothing usable: no verdict line, transport failure, unsplittable file

# Provider presets — the SINGLE place a renamed model id or moved endpoint is edited. Adding a new
# provider (Qwen, a local vLLM, …) is one new row. Callers can always bypass this via env/flags.
PROVIDERS: dict[str, dict[str, str]] = {
    "deepseek":   {"base_url": "https://api.deepseek.com",            "model": "deepseek-flash"},
    "glm":        {"base_url": "https://api.z.ai/api/coding/paas/v4", "model": "glm-5.3"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1",        "model": "deepseek/deepseek-v4-flash"},
}
# The HTTP preset used when nobody names a provider but an HTTP endpoint is still needed: a custom
# endpoint (REVIEW_BASE_URL / REVIEW_MODEL) with no --provider, and resolve_config's own default. It is
# a key-lookup and label default only; it is NOT the review order (see REVIEW_ORDER).
HTTP_DEFAULT_PROVIDER = "deepseek"

# The review chain, in owner-policy order (2026-10-21): agy Argon, then DeepSeek, then GLM. A named
# provider goes first and the rest follow in this order; a custom endpoint (REVIEW_BASE_URL /
# REVIEW_MODEL) never falls back, because its owner named exactly who reviews.
#
# Why a fallback rather than just picking one vendor: the whole point of this tool is that the
# reviewer is a DIFFERENT vendor from the author, so collapsing to a single provider means an
# outage leaves you with no second opinion and — worse — no signal that you have lost one.
# Observed on serve-sight across three consecutive phases: GLM timed out every time and the
# sessions recorded "cross-review inconclusive" and moved on. A review that silently does not
# happen is the same failure class as a diff that silently is not read.
#
# Order matters: agy Argon leads since 2026-10-21 (owner decision) because DeepSeek ran out of credit,
# so every unnamed review tried DeepSeek first and failed before it reached Argon. DeepSeek stays
# second: it has actually found real bugs (a date-boundary bug two same-vendor passes missed, an
# anchor bug, an orphaned-permission-rows bug). GLM is the spare tyre, not a co-equal — an alternation
# policy that sends half the phases to a provider that times out buys variety it never actually collects.
AGY_PROVIDER = "agy-argon"
DEFAULT_PROVIDER = AGY_PROVIDER
REVIEW_ORDER: tuple[str, ...] = (AGY_PROVIDER, "deepseek", "glm")

# agy runs headless through the spend cap: plan mode (it needs no tools, the diff is in the prompt).
AGY_MODEL = "gemini-4-argon-high"
AGY_TIMEOUT_S = 15 * 60
# The prompt is one command-line argument (`--print=<prompt>`). A Windows command line holds at most
# 32,767 characters, so a larger prompt skips agy instead of failing to start.
AGY_MAX_PROMPT_CHARS = 28_000
# `caddis_spend.py run` refusal codes: 75 over the cap or no lock, 78 cap not configured. Never agy's own.
SPEND_REFUSED = (75, 78)

# On HTTP 429, wait for `Retry-After` once per provider per run, at most this long.
RETRY_AFTER_CAP_S = 60.0

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


class ProviderFailure(RuntimeError):
    """The provider could not answer: HTTP 429, a 5xx, a timeout, a connection error, an empty reply, an agy
    error status. NOT_RUN (exit 3), never a verdict, never a reason to split the diff."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class ProviderSkipped(Exception):
    """The provider is not available for this run (the spend cap refused agy, agy is missing, the prompt
    is too long for the agy command line). The chain moves on; nothing was reviewed. `for_run=False`: skip only
    this prompt (it was too long), so a smaller batch may still use the provider."""

    def __init__(self, message: str, for_run: bool = True):
        super().__init__(message)
        self.for_run = for_run


def _retry_after(exc: BaseException) -> float | None:
    """Seconds from a 429's `Retry-After` header (delta-seconds form only), else None."""
    if isinstance(exc, ProviderFailure):
        return exc.retry_after
    if isinstance(exc, urllib.error.HTTPError) and exc.code == 429 and exc.headers is not None:
        try:
            value = float((exc.headers.get("Retry-After") or "").strip())
        except ValueError:
            return None
        return value if value >= 0 else None
    return None


def failure_kind(exc: BaseException) -> str:
    """'provider' (NOT_RUN: next provider, no split), 'truncation' (size signal: may split), or 'other'.

    Order matters: HTTPError is a URLError, and RemoteDisconnected is both a ConnectionError and an
    HTTPException (a dropped connection, not a truncated body)."""
    if isinstance(exc, (ProviderFailure, ProviderSkipped)):
        return "provider"
    if isinstance(exc, urllib.error.HTTPError):
        return "provider" if exc.code == 429 or exc.code >= 500 else "other"
    if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError)):
        return "provider"
    if isinstance(exc, http.client.HTTPException):
        return "truncation"
    if isinstance(exc, OSError):
        return "provider"
    return "other"


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
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # Unreadable or not UTF-8 (PowerShell writes UTF-16). agy needs no key, so this file must not
        # stop a review; a provider that needs a key then reports "no API key" as usual.
        return {}
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def named_provider(args: argparse.Namespace, env: dict[str, str]) -> str:
    """The provider the caller chose, or "". Order: --provider flag, process env REVIEW_PROVIDER,
    REVIEW_PROVIDER in the keys file (~/.caddis/keys.env), so a default is switched with one line there."""
    chosen = args.provider or env.get("REVIEW_PROVIDER")
    if not chosen:
        chosen = _parse_keys_file(env.get("CADDIS_KEYS_FILE") or DEFAULT_KEYS_FILE).get("REVIEW_PROVIDER")
    return (chosen or "").strip().lower()


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
    provider = (provider or named_provider(args, env) or HTTP_DEFAULT_PROVIDER).strip().lower()
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
        ["git", "diff", "--no-color", "--no-ext-diff", "--src-prefix=a/",
         "--dst-prefix=b/", "--no-index", "--", null, path],
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
    cmd = ["git", "diff", "--no-color", "--no-ext-diff", "--src-prefix=a/",
           "--dst-prefix=b/", rng or "HEAD"]
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


def changed_paths(diff_text: str) -> list[str]:
    """The post-change path of every file in the diff, in diff order."""
    paths: list[str] = []
    for chunk in split_diff_by_file(diff_text):
        header = chunk.split("\n", 1)[0].rstrip("\r")
        if not header.startswith("diff --git "):
            continue
        rest = header[len("diff --git "):]
        quoted = rest.rfind(' "b/')
        if rest.endswith('"') and quoted != -1:
            paths.append(rest[quoted + 4:-1])
        elif " b/" in rest:
            paths.append(rest.rsplit(" b/", 1)[1])
    return paths


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


def build_review_prompt(diff_text: str, branch: str, rng: str | None,
                        all_paths: list[str] | None = None) -> str:
    """Adversarial review prompt.

    Self-contained: the criteria are inline so a real review always happens, and it ends with
    a single machine-parseable verdict line the caller maps to an exit code.
    """
    scope = rng or "the working tree (staged, unstaged and new untracked files)"
    part_note = ""
    if all_paths and len(all_paths) > len(changed_paths(diff_text)):
        # Without the whole list, a batch reports files it cannot see as missing.
        part_note = (
            "This diff is one part of a larger change. The whole change touches these files:\n"
            + "".join(f"- {p}\n" for p in all_paths)
            + "Review only the files in the diff below. The other files are reviewed in other "
            "batches; do not report them as missing.\n\n"
        )
    return part_note + (
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
    # Since 2026-10-19 this is a ProviderFailure: NOT_RUN and the next provider, never a split. An empty
    # reply from a throttled DeepSeek is not size-correlated, and halving it sent MORE calls to it.
    if not isinstance(content, str) or not content.strip():
        raise ProviderFailure(
            "endpoint returned HTTP 200 with empty or absent message content "
            f"(type={type(content).__name__}) — treating as a provider failure"
        )
    return content


def _spend_script() -> Path | None:
    """caddis_spend.py: beside this file in a bundle, else the source repo's scripts/ folder."""
    here = Path(__file__).resolve().parent
    for candidate in (here / "caddis_spend.py", here.parents[1] / "scripts" / "caddis_spend.py"):
        if candidate.is_file():
            return candidate
    return None


def agy_launcher() -> list[str] | None:
    """The command prefix that runs agy under the spend cap, or None when agy or caddis_spend is missing.
    Every agy call goes through `caddis_spend.py run` (owner policy: agy only through the spend cap)."""
    agy = shutil.which("agy")
    spend = _spend_script()
    if not agy or spend is None:
        return None
    return [sys.executable, str(spend), "run", "--caller", "oss-review", "--", agy]


def _kill_tree(proc) -> None:
    """Kill the child and everything it started (it runs in its own process group / session)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()


def _run_capped(argv: list[str], timeout: float) -> tuple[int, str, str]:
    """Run `argv` with stdin closed; (exit, stdout, stderr). On timeout kill the whole tree and raise
    TimeoutError: a killed caddis_spend must not leave agy running on."""
    group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})
    env = {**os.environ, "CADDIS_HEADLESS": "1"}
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", env=env, **group)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            pass
        raise TimeoutError(f"agy timed out after {int(timeout)} s; process tree killed") from None
    except BaseException:
        _kill_tree(proc)
        raise
    return proc.returncode, stdout or "", stderr or ""


def _agy_document(stdout: str) -> dict | None:
    """The last agy JSON document (keys status/response) that starts a line of `stdout`.

    Mirror of scripts/caddis_spend.py::_agy_document, duplicated so this tool stays one stdlib-only file.
    A `{` inside the model reply never starts a line of the raw output (it is inside a JSON string)."""
    decoder = json.JSONDecoder()
    text = stdout or ""
    starts = [0] if text.startswith("{") else []
    starts += [i + 1 for i, ch in enumerate(text) if ch == "\n" and text[i + 1:i + 2] == "{"]
    found = None
    for start in starts:
        try:
            obj, _end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and {"status", "response"} <= obj.keys():
            found = obj
    return found


def call_agy(launcher: list[str], prompt: str, timeout: float = AGY_TIMEOUT_S) -> str:
    """One review by agy Argon through the spend cap -> the reply text.

    ProviderSkipped: the cap refused, agy is missing, or the prompt is too long for one argument.
    ProviderFailure: a non-zero exit, a status other than SUCCESS (ERROR, RESOURCE_EXHAUSTED), no JSON
    document, or an empty reply."""
    if len(prompt) > AGY_MAX_PROMPT_CHARS:
        raise ProviderSkipped(f"prompt is {len(prompt):,} chars, over the {AGY_MAX_PROMPT_CHARS:,}-char "
                              "agy command-line limit", for_run=False)
    argv = [*launcher, "--model", AGY_MODEL, "--mode", "plan", "--output-format", "json",
            f"--print={prompt}"]
    code, stdout, stderr = _run_capped(argv, timeout)
    if code in SPEND_REFUSED:
        raise ProviderSkipped(f"the agy spend cap refused the call (caddis_spend exit {code}): "
                              f"{stderr.strip()[-300:]}")
    if code == 127:
        raise ProviderSkipped(f"agy could not start: {stderr.strip()[-300:]}")
    doc = _agy_document(stdout)
    status = str(doc.get("status")) if doc else "no JSON document"
    if code != 0 or status != "SUCCESS":
        raise ProviderFailure(f"agy exit {code}, status {status}: {(stderr or stdout).strip()[-300:]}")
    response = doc.get("response")
    if not isinstance(response, str) or not response.strip():
        raise ProviderFailure("agy returned an empty response")
    return response


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


def _config_is_changed(diff_text: str) -> bool:
    """True when either side of a changed file block names the review config."""
    target = ".caddis/config.toml"
    for block in secret_filter._split_into_file_blocks(diff_text):
        for line in block.splitlines():
            if line.startswith("@@"):
                break
            if line in (f"--- a/{target}", f"+++ b/{target}",
                        f"rename from {target}", f"rename to {target}"):
                return True
            if line.startswith("diff --git "):
                rest = line[len("diff --git "):]
                quoted = secret_filter._QUOTED_HEADER_RE.match(rest)
                if quoted:
                    sides = (secret_filter._unescape_git_quoted(part)
                             for part in quoted.groups())
                    if any(side in (f"a/{target}", f"b/{target}") for side in sides):
                        return True
                elif rest.startswith(f"a/{target} b/") or rest.endswith(f" b/{target}"):
                    return True
    return False


def main(argv: list[str] | None = None, env: dict[str, str] | None = None) -> int:
    _force_utf8_stdio()
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(description="Cross-vendor code review via an OpenAI-compatible endpoint.")
    parser.add_argument("--range", dest="range", default=None,
                        help="git range to review (e.g. origin/main..HEAD); default = working tree")
    parser.add_argument("--cwd", default=".", help="repo directory (default: cwd)")
    parser.add_argument("--provider", default=None,
                        help=f"preset: {', '.join(sorted(PROVIDERS))} or {AGY_PROVIDER} (default "
                             f"{DEFAULT_PROVIDER}, then the next available provider); env REVIEW_PROVIDER "
                             f"or REVIEW_PROVIDER in the keys file. "
                             f"A provider failure falls back in the order {' -> '.join(REVIEW_ORDER)}")
    parser.add_argument("--base-url", dest="base_url", default=None, help="override REVIEW_BASE_URL / the preset")
    parser.add_argument("--model", default=None, help="override REVIEW_MODEL / the preset")
    parser.add_argument("--max-diff-chars", type=int, default=None,
                        help=f"override REVIEW_MAX_DIFF_CHARS (default {DEFAULT_MAX_DIFF_CHARS})")
    parser.add_argument("--check-config", action="store_true",
                        help="report whether a usable reviewer exists (agy on PATH, or an API key) and "
                             "exit — no diff, no LLM call. Exit 0 = ready, 3 = nothing configured.")
    parser.add_argument("--allow-path", dest="allow_path", action="append", default=[],
                        metavar="GLOB",
                        help="re-admit a file the secret-filter deny list would otherwise drop "
                             "(repeatable)")
    args = parser.parse_args(argv)

    # --check-config is deliberately NON-INTERACTIVE. This script runs headless — from CI, from a
    # runner, from a `claude -p` session — where a prompt on stdin does not ask a question,
    # it hangs forever. The ASKING belongs in `/caddis:cross-review`, which is driven by an agent
    # that can actually talk to a human. This half just answers "is it configured?" cheaply enough
    # to call before you need it, instead of finding out mid-commit.
    if args.check_config:
        # agy Argon is the default reviewer and needs no key: agy on PATH plus caddis_spend.py is enough.
        available = ([AGY_PROVIDER] if agy_launcher() is not None else []) + configured_providers(env)
        if not available:
            sys.stderr.write(
                "no second-vendor reviewer is configured: no API key anywhere, and no agy on PATH\n"
                "  (with caddis_spend.py) for the default agy-argon reviewer.\n"
                "  Cross-review needs one — the whole point is a reviewer that does not share this\n"
                "  model's blind spots, so a same-vendor fallback would be no review at all.\n"
                f"  Add a key to {env.get('CADDIS_KEYS_FILE') or DEFAULT_KEYS_FILE}, e.g.\n"
                "    GLM_API_KEY=<your-key>\n")
            return EXIT_CONFIG
        print(f"cross-review is ready. Providers available: {', '.join(available)}")
        return EXIT_CLEAN

    try:
        diff_text = get_diff(args.range, args.cwd)
    except Exception as exc:
        sys.stderr.write(f"could not read diff: {exc}\n")
        return EXIT_ERROR

    # Pre-send secret filter — runs on the FULL diff, before it is ever split into batches and
    # before any provider is contacted, and BEFORE provider/key resolution below: a missing or
    # misconfigured REVIEW_API_KEY must never race a secret refusal and print the wrong reason.
    # A run with no key configured at all still refuses here first, on the merits, not because
    # it couldn't have called anyone anyway.
    cfg_deny, cfg_allow = secret_filter.load_config(Path(args.cwd))
    if _config_is_changed(diff_text):
        cfg_deny = list(dict.fromkeys(cfg_deny + secret_filter.load_head_deny_paths(Path(args.cwd))))
        cfg_allow = []
        print("note: .caddis/config.toml is part of this change; its allow_paths are ignored")
    filter_result = secret_filter.filter_diff(
        diff_text,
        secret_filter.DEFAULT_DENY_GLOBS + cfg_deny,
        cfg_allow + list(args.allow_path),
    )
    for warn_path, warn_line, warn_rule in filter_result.warnings:
        # Context lines are already in the repo: sending them adds no exposure. Name them anyway.
        print(f"WARN  {warn_path}:{warn_line} ({warn_rule}) — already in the repo, not refused")
    if filter_result.hits:
        print("REVIEW: REFUSED — possible secrets:")
        for hit_path, hit_line, hit_rule in filter_result.hits:
            print(f"  {hit_path}:{hit_line} ({hit_rule})")
        return EXIT_CONFIG
    if filter_result.dropped_paths:
        print(f"excluded from review: {', '.join(filter_result.dropped_paths)}")
    if not filter_result.kept_diff.strip() and filter_result.dropped_paths:
        print("REVIEW: REFUSED — every changed file is excluded")
        return EXIT_CONFIG
    diff_text = filter_result.kept_diff

    named = named_provider(args, env)
    # A custom ENDPOINT names exactly who reviews (REVIEW_BASE_URL/REVIEW_MODEL, the documented
    # future-proofing path): it never falls back. A named preset falls back on a provider failure,
    # and the switch is printed, so the reviewer is never misreported.
    custom = bool(args.base_url or env.get("REVIEW_BASE_URL") or args.model or env.get("REVIEW_MODEL"))
    # With nothing named, the default is agy Argon. A custom endpoint with no provider named is an HTTP
    # call (never agy), keyed and labelled as before.
    primary_provider = named or (HTTP_DEFAULT_PROVIDER if custom else DEFAULT_PROVIDER)
    agy_cmd = agy_launcher()

    def _http_entry(name: str, url: str, key: str, mdl: str):
        return (name, mdl, url, lambda prompt: call_llm(url, key, mdl, prompt))

    def _agy_entry(launcher: list[str]):
        return (AGY_PROVIDER, AGY_MODEL, "caddis_spend run", lambda prompt: call_agy(launcher, prompt))

    try:
        if primary_provider == AGY_PROVIDER and not custom:
            if agy_cmd is not None:
                chain = [_agy_entry(agy_cmd)]
            elif named:
                raise ConfigError(f"provider {AGY_PROVIDER!r} needs agy on PATH and caddis_spend.py "
                                  "(beside this script or in the repo's scripts/ folder).")
            else:
                # The default degrades: no agy here, so the chain starts at the next provider with a key.
                chain = []
        else:
            chain = [_http_entry(primary_provider, *resolve_config(args, env))]
        # The rest of the chain in policy order (agy Argon -> DeepSeek -> GLM). A provider with no key, or
        # agy with no agy on PATH, is skipped: not an error, just nothing to fall back to.
        if not custom:
            for name in REVIEW_ORDER:
                if chain and name == chain[0][0]:
                    continue
                if name == AGY_PROVIDER:
                    if agy_cmd is not None:
                        chain.append(_agy_entry(agy_cmd))
                    continue
                try:
                    chain.append(_http_entry(name, *resolve_config(args, env, provider=name, use_overrides=False)))
                except ConfigError:
                    continue
        if not chain:
            raise ConfigError(
                "no reviewer is available: agy is not on PATH (with caddis_spend.py) and no provider has an "
                "API key. Set $REVIEW_API_KEY, or add a key such as DEEPSEEK_API_KEY or GLM_API_KEY to "
                f"{env.get('CADDIS_KEYS_FILE') or DEFAULT_KEYS_FILE}, or install agy.")
    except ConfigError as exc:
        sys.stderr.write(f"{exc}\n")
        return EXIT_CONFIG

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

    # Per run: a provider that failed (429, 5xx, timeout, empty reply, cap refusal) gets no more calls,
    # and each provider waits for a 429 Retry-After at most once. Hammering a throttled provider with
    # more, smaller calls is the 18-19 Oct 2026 failure.
    down: set[str] = set()
    waited: set[str] = set()

    def _try_chain(prompt: str, label: str) -> tuple[str | None, list[str]]:
        """One payload against every provider still up. (review, []) or (None, the failure kinds)."""
        kinds: list[str] = []
        for idx, (name, mdl, where, call) in enumerate(chain):
            if name in down:
                continue
            while True:
                try:
                    review = call(prompt)
                except ProviderSkipped as exc:
                    sys.stderr.write(f"[cross-review] {name} skipped{label}: {exc}\n")
                    if exc.for_run:
                        down.add(name)
                    kinds.append("provider")
                    break
                except TRANSPORT_ERRORS as exc:
                    kind = failure_kind(exc)
                    retry = _retry_after(exc)
                    if kind == "provider" and retry is not None and name not in waited:
                        waited.add(name)
                        delay = min(retry, RETRY_AFTER_CAP_S)
                        sys.stderr.write(f"[cross-review] {name} is rate-limited (HTTP 429){label}; waiting "
                                         f"{delay:g} s once (Retry-After), then one retry\n")
                        time.sleep(delay)
                        continue
                    kinds.append(kind)
                    if kind == "provider":
                        down.add(name)
                    left = [n for n, *_ in chain[idx + 1:] if n not in down]
                    sys.stderr.write(
                        f"review request failed{label} ({mdl} @ {where}): {exc}\n"
                        + (f"  falling back to {left[0]}...\n" if left
                           else "  If the model id was renamed, set REVIEW_MODEL to the current id "
                                "(env overrides the preset).\n" if kind == "other"
                           else "  no provider left to try.\n")
                    )
                    break
                # Loud on purpose, every time: which vendor gave the verdict is a material fact about
                # the review, and it belongs in the transcript the phase report quotes.
                if idx:
                    print(f"[cross-review] {chain[0][0]} unavailable; reviewed by {name} ({mdl}).")
                else:
                    print(f"[cross-review] reviewed by {name} ({mdl}).")
                return review, []
        return None, kinds or ["provider"]  # nothing tried: every provider was already down

    def _review_chunk(chunk: str, label: str, depth: int = 0) -> tuple[list[str] | None, list[str]]:
        """Review `chunk`; on a size-truncation failure, halve it and retry once per level.

        WHY HALVE. The observed truncations (`http.client.IncompleteRead`, parking-lot 006) were
        SIZE-CORRELATED: a smaller payload usually gets through. Only that signal splits. A provider
        failure (429, 5xx, timeout, empty reply) does NOT: halving a throttled call sends it more calls.

        Bounded at RETRY_SPLIT_DEPTH levels and never splits a single file, so it cannot loop and
        cannot silently shrink a diff to nothing. Returns (None, kinds) when the chunk failed.
        """
        review, kinds = _try_chain(build_review_prompt(chunk, branch, args.range, whole_change), label)
        if review is not None:
            return [review], []
        files = split_diff_by_file(chunk)
        if "truncation" not in kinds or depth >= RETRY_SPLIT_DEPTH or len(files) < 2:
            return None, kinds
        half = len(files) // 2
        sys.stderr.write(
            f"[cross-review] retrying{label} as 2 smaller chunks ({half} + {len(files) - half} "
            "file(s)) — a truncated reply is size-correlated.\n")
        out: list[str] = []
        for part_no, part in enumerate(("".join(files[:half]), "".join(files[half:])), 1):
            got, sub_kinds = _review_chunk(part, f"{label} part {part_no}", depth + 1)
            if got is None:
                return None, kinds + sub_kinds
            out += got
        return out, []

    whole_change = changed_paths(diff_text)
    verdicts: list[bool | None] = []
    for batch_no, batch in enumerate(batches, 1):
        label = f" (batch {batch_no}/{len(batches)})" if len(batches) > 1 else ""
        if len(batches) > 1:
            files = len(split_diff_by_file(batch))
            print(f"\n===== batch {batch_no}/{len(batches)} — {files} file(s), "
                  f"{len(batch):,} chars =====")

        reviews, kinds = _review_chunk(batch, label)
        if reviews is None:
            # Every provider failed, and splitting did not rescue it. Do NOT continue to the next
            # batch: a partial sweep that still prints a verdict is the failure mode this whole
            # tool guards against. Only provider failures: could not run (3). Anything else: 4.
            not_run = all(k == "provider" for k in kinds)
            sys.stderr.write(f"batch {batch_no}/{len(batches)} could not be reviewed — aborting"
                             + (" (every provider failed: NOT_RUN).\n" if not_run else ".\n"))
            if any(v is False for v in verdicts):
                # An earlier batch already found a blocking issue. A later failure must not hide it behind
                # NOT_RUN (3), which reads as "nothing found, retry". Fail closed and report the finding.
                print("REVIEW: BLOCKING  (an earlier batch blocked; the remaining batches were not reviewed)")
                return EXIT_BLOCKING
            return EXIT_CONFIG if not_run else EXIT_ERROR

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
