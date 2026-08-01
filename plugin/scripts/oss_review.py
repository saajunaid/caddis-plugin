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
    --range   e.g. origin/main..HEAD   (default: the working tree, i.e. staged+unstaged)

Exit codes (fail-closed):
  0  REVIEW: CLEAN      — no blocking issues
  1  REVIEW: BLOCKING   — one or more blocking issues
  2  error              — no diff verdict parsed, git failure, or endpoint/parse failure
  3  misconfigured      — REVIEW_API_KEY missing (actionable message on stderr)

Stdlib-only (urllib) so it runs anywhere with no pip install.
"""
from __future__ import annotations

import argparse
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
    "glm":        {"base_url": "https://api.z.ai/api/coding/paas/v4", "model": "glm-4.7"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1",        "model": "deepseek/deepseek-v4-flash"},
}
DEFAULT_PROVIDER = "deepseek"


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


def resolve_config(args: argparse.Namespace, env: dict[str, str]) -> tuple[str, str, str]:
    """(base_url, api_key, model). Precedence: explicit flag > env var > provider preset.

    Never hard-fails on a model rename: a known --provider supplies sane defaults, and
    REVIEW_MODEL / REVIEW_BASE_URL override them without any code change.
    """
    provider = (args.provider or env.get("REVIEW_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    preset = PROVIDERS.get(provider, {})
    base_url = (args.base_url or env.get("REVIEW_BASE_URL") or preset.get("base_url") or "").rstrip("/")
    model = args.model or env.get("REVIEW_MODEL") or preset.get("model") or ""
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
        raise ConfigError(
            f"no API key for provider {provider!r}. Set $REVIEW_API_KEY or ${key_env}, or add\n"
            f"  {key_env}=<your-key>\n"
            f"to your keys file ({keys_path}). Override the file path with $CADDIS_KEYS_FILE."
        )
    return base_url, api_key, model


def get_diff(rng: str | None, cwd: str) -> str:
    """The unified diff for `rng` (e.g. 'origin/main..HEAD'), or the working tree when None.

    Working tree = staged + unstaged against HEAD (`git diff HEAD`). Raises on git failure so
    main() maps it to EXIT_ERROR rather than reviewing an empty diff as CLEAN.
    """
    cmd = ["git", "diff", rng] if rng else ["git", "diff", "HEAD"]
    # encoding pinned to UTF-8: git emits UTF-8, but text=True would decode with the locale
    # codepage (cp1252 on Windows) — a non-ASCII diff then kills the reader thread and
    # subprocess hands back stdout=None with returncode 0.
    out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=30)
    if out.returncode != 0:
        raise RuntimeError(f"git diff failed: {out.stderr.strip()}")
    return out.stdout


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
    scope = rng or "the working tree (staged + unstaged changes)"
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
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"unexpected response shape from endpoint: {exc}") from exc


def main(argv: list[str] | None = None, env: dict[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(description="Cross-vendor code review via an OpenAI-compatible endpoint.")
    parser.add_argument("--range", dest="range", default=None,
                        help="git range to review (e.g. origin/main..HEAD); default = working tree")
    parser.add_argument("--cwd", default=".", help="repo directory (default: cwd)")
    parser.add_argument("--provider", default=None,
                        help=f"preset: {', '.join(sorted(PROVIDERS))} (default {DEFAULT_PROVIDER}); env REVIEW_PROVIDER")
    parser.add_argument("--base-url", dest="base_url", default=None, help="override REVIEW_BASE_URL / the preset")
    parser.add_argument("--model", default=None, help="override REVIEW_MODEL / the preset")
    args = parser.parse_args(argv)

    try:
        base_url, api_key, model = resolve_config(args, env)
    except ConfigError as exc:
        sys.stderr.write(f"{exc}\n")
        return EXIT_CONFIG

    try:
        diff_text = get_diff(args.range, args.cwd)
    except Exception as exc:
        sys.stderr.write(f"could not read diff: {exc}\n")
        return EXIT_ERROR

    if not diff_text.strip():
        print("No changes to review.")
        print("REVIEW: CLEAN")
        return EXIT_CLEAN

    branch = current_branch(args.cwd)
    prompt = build_review_prompt(diff_text, branch, args.range)

    try:
        review = call_llm(base_url, api_key, model, prompt)
    except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError, ValueError, TimeoutError) as exc:
        sys.stderr.write(
            f"review request failed ({model} @ {base_url}): {exc}\n"
            "  If the model id was renamed, set REVIEW_MODEL to the current id (env overrides the preset).\n"
        )
        return EXIT_ERROR

    print(review)
    verdict = classify_verdict(review)
    if verdict is True:
        return EXIT_CLEAN
    if verdict is False:
        return EXIT_BLOCKING
    sys.stderr.write("no REVIEW: CLEAN|BLOCKING verdict line found in the model output\n")
    return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
