#!/usr/bin/env python3
"""Shared provider + key resolver for the model-switching launchers (Track A).

`claude-oss` / `claude-glm` point a Claude Code session at an OpenAI-compatible
endpoint (GLM, DeepSeek, OpenRouter, or any custom base_url) by setting the
``ANTHROPIC_*`` env vars. This module owns the ONE place that maps a provider name
to its endpoint + default model, and resolves the API key WITHOUT ever hardcoding a
path or a secret.

Key resolution precedence (highest wins):
  1. the provider's explicit env var (GLM_API_KEY / DEEPSEEK_API_KEY / OPENROUTER_API_KEY),
     or the generic OSS_API_KEY;
  2. a keys file at CADDIS_KEYS_FILE (default ~/.caddis/keys.env), INI/KEY=VALUE style,
     comments (#) and blank lines allowed;
  3. ConfigError with an actionable message.

Endpoint/model precedence: OSS_BASE_URL / OSS_MODEL env override > the provider preset.
An unknown provider is fine as long as OSS_BASE_URL + OSS_MODEL are supplied.

The PROVIDERS table mirrors oss_review.py so a renamed model id / moved endpoint is a
one-line edit in each. (oss_review may import this later; not refactored here to keep
the diff small.)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Provider presets — the SINGLE place a renamed model id / moved endpoint is edited.
# These are the providers' ANTHROPIC-protocol endpoints: this table feeds
# ANTHROPIC_BASE_URL for Claude Code, which speaks the Anthropic Messages API — NOT the
# OpenAI /chat/completions dialect that oss_review.py uses (its table differs on purpose).
# "openrouter" has no Anthropic-protocol endpoint: it only works through an
# Anthropic-compatible gateway (e.g. LiteLLM — see claude-harness/LOCAL-MODELS.md) whose
# URL you supply via OSS_BASE_URL.
# The `[1m]` suffix on a model id is a CLAUDE CODE convention, not part of the model name.
# Claude Code strips it before calling the API; it only tells the client the real context
# window. Without it, an id Claude Code does not recognise is assumed to be 200k and
# auto-compact throws away context the model could still hold. Both providers are 1M
# (GLM-5.3: docs.z.ai; DeepSeek V4 Flash: 1,048,576 positions) — verified 2026-08-23 by
# running with and without the suffix and diffing the cap warning.
# NEVER put this suffix in the OpenAI-dialect tables (oss_review.py / oss_ask.py): those
# send the id raw to /chat/completions, which would reject it.
PROVIDERS: dict[str, dict[str, str]] = {
    "deepseek":   {"base_url": "https://api.deepseek.com/anthropic",  "model": "deepseek-v4-flash[1m]",          "key_env": "DEEPSEEK_API_KEY"},
    "glm":        {"base_url": "https://api.z.ai/api/anthropic",      "model": "glm-5.3[1m]",                    "key_env": "GLM_API_KEY"},
    "openrouter": {"base_url": "",                                    "model": "deepseek/deepseek-v4-flash", "key_env": "OPENROUTER_API_KEY"},
}
DEFAULT_PROVIDER = "deepseek"
DEFAULT_KEYS_FILE = "~/.caddis/keys.env"

# Env-var naming derives from the shared prefix constant, so a future rename is one edit there.
try:
    from claudster_config import ENV_PREFIX
except Exception:  # pragma: no cover — standalone copy
    ENV_PREFIX = "CADDIS"
KEYS_FILE_ENV = f"{ENV_PREFIX}_KEYS_FILE"


class ConfigError(Exception):
    """Configuration can't be resolved — unknown provider without an override, or no key."""


def _parse_keys_file(path: str) -> dict[str, str]:
    """Parse an INI/``KEY=VALUE`` keys file. Comments (#) and blank lines are ignored;
    surrounding quotes are stripped. A missing file yields ``{}`` (not an error — the
    key may still come from the environment)."""
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


def _resolve_key(provider: str, key_env: str, env: dict[str, str]) -> str:
    """Provider key via env, then the keys file, else ConfigError. Never logged/echoed."""
    # 1. explicit env (provider-specific, then generic)
    for name in (key_env, "OSS_API_KEY"):
        val = (env.get(name) or "").strip()
        if val:
            return val
    # 2. keys file (CADDIS_KEYS_FILE if set, else ~/.caddis/keys.env)
    keys_path = env.get(KEYS_FILE_ENV) or DEFAULT_KEYS_FILE
    file_keys = _parse_keys_file(keys_path)
    for name in (key_env, "OSS_API_KEY"):
        val = (file_keys.get(name) or "").strip()
        if val:
            return val
    # 3. actionable error — name the var and the file, never a value.
    #
    # It also names the providers that DO have a key. When DeepSeek is unset but GLM is configured,
    # the fix is `--provider glm`, not "go and find a key" — and the old message sent the reader
    # hunting for a credential they already had. This fails at the moment of use, which is the
    # least convenient moment to be told to go looking (`.caddis/parking-lot/003`).
    others = [p for p in configured_providers(env) if p != provider]
    have = (f"\nProviders that DO have a key here: {', '.join(others)}. "
            f"To use one now: --provider {others[0]}." if others else "")
    raise ConfigError(
        f"no API key for provider {provider!r}. Set ${key_env} (or $OSS_API_KEY), or add\n"
        f"  {key_env}=<your-key>\n"
        f"to your keys file ({keys_path}). Override the file path with ${KEYS_FILE_ENV}."
        + have
    )


def configured_providers(env: dict[str, str]) -> list[str]:
    """Every preset provider that currently has a usable key. Never returns or logs a key value.

    Exists so a caller can find out BEFORE it needs one. `/caddis:cross-review` used to discover a
    missing key mid-task, with a commit pending — and a command that fails once at an inconvenient
    moment does not get retried, so the safety check it provides is simply lost and nobody records
    that it was lost.
    """
    keys_path = env.get(KEYS_FILE_ENV) or DEFAULT_KEYS_FILE
    file_keys = _parse_keys_file(keys_path)
    generic = (env.get("OSS_API_KEY") or file_keys.get("OSS_API_KEY") or "").strip()
    out = []
    for name, preset in sorted(PROVIDERS.items()):
        key_env = preset.get("key_env") or f"{name.upper()}_API_KEY"
        if generic or (env.get(key_env) or "").strip() or (file_keys.get(key_env) or "").strip():
            out.append(name)
    return out


def resolve(provider: str | None, env: dict[str, str]) -> dict[str, str]:
    """Resolve ``{base_url, model, api_key}`` for ``provider`` using ``env``.

    ``provider`` defaults to $OSS_PROVIDER then DEEPSEEK. An unknown provider is allowed
    only when OSS_BASE_URL + OSS_MODEL are supplied. Raises ConfigError otherwise, or
    when no API key can be resolved.
    """
    provider = (provider or env.get("OSS_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    preset = PROVIDERS.get(provider, {})
    base_url = (env.get("OSS_BASE_URL") or preset.get("base_url") or "").rstrip("/")
    model = env.get("OSS_MODEL") or preset.get("model") or ""
    if not base_url or not model:
        known = ", ".join(sorted(PROVIDERS))
        raise ConfigError(
            f"unknown provider {provider!r}: set $OSS_BASE_URL and $OSS_MODEL, "
            f"or use one of: {known}."
        )
    key_env = preset.get("key_env") or f"{provider.upper()}_API_KEY"
    api_key = _resolve_key(provider, key_env, env)
    return {"base_url": base_url, "model": model, "api_key": api_key}


def main(argv: list[str], env: dict[str, str] | None = None) -> int:
    """CLI bridge for the launchers: ``oss_model.py <provider>`` prints the resolved
    base_url, model, and api_key on three lines (in that order) to stdout — the caller
    (claude-oss.sh / .ps1) CAPTURES this output into variables and sets ANTHROPIC_*; it
    is never displayed. A ConfigError prints its message to stderr and exits 3.
    """
    env = os.environ if env is None else env
    provider = argv[0] if argv else None
    try:
        cfg = resolve(provider, env)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    print(cfg["base_url"])
    print(cfg["model"])
    print(cfg["api_key"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
