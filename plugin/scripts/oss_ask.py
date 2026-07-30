#!/usr/bin/env python3
"""One-shot question to an OSS provider (DeepSeek/GLM/OpenRouter) — plain chat, no tools.

Backs the /ask-glm and /ask-deepseek commands: a fast second-opinion answer from a
different model family, without spinning up a full Claude Code session. Speaks the
providers' OpenAI-compatible ``/chat/completions`` dialect (NOT the Anthropic endpoints
oss_model.py hands to Claude Code), and reuses oss_model's key resolution so one entry
in ~/.caddis/keys.env lights up every lane.

Usage:
  python oss_ask.py <provider> <prompt...>  [--model M] [--base-url U] [--system S]

Exit codes: 0 answer printed; 2 endpoint/parse error; 3 config error (message on stderr).
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oss_model  # noqa: E402  (same-directory import: shared key resolution)

# OpenAI-compatible chat endpoints — intentionally different from oss_model.PROVIDERS,
# which holds the Anthropic-protocol endpoints for Claude Code.
CHAT_PROVIDERS: dict[str, dict[str, str]] = {
    "deepseek":   {"base_url": "https://api.deepseek.com",            "model": "deepseek-v4-flash",          "key_env": "DEEPSEEK_API_KEY"},
    "glm":        {"base_url": "https://api.z.ai/api/coding/paas/v4", "model": "glm-5.2",                    "key_env": "GLM_API_KEY"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1",        "model": "deepseek/deepseek-v4-flash", "key_env": "OPENROUTER_API_KEY"},
}

EXIT_OK = 0
EXIT_ERROR = 2
EXIT_CONFIG = 3


def resolve_chat_config(provider: str, env: dict[str, str],
                        model: str | None = None, base_url: str | None = None) -> dict[str, str]:
    """{base_url, model, api_key} for the chat lane. Flag > preset; key via oss_model."""
    preset = CHAT_PROVIDERS.get(provider.strip().lower(), {})
    resolved_base = (base_url or preset.get("base_url") or "").rstrip("/")
    resolved_model = model or preset.get("model") or ""
    if not resolved_base or not resolved_model:
        known = ", ".join(sorted(CHAT_PROVIDERS))
        raise oss_model.ConfigError(
            f"unknown provider {provider!r}: pass --base-url and --model, or use one of: {known}."
        )
    key_env = preset.get("key_env") or f"{provider.upper()}_API_KEY"
    api_key = oss_model._resolve_key(provider, key_env, env)
    return {"base_url": resolved_base, "model": resolved_model, "api_key": api_key}


def ask(cfg: dict[str, str], prompt: str, system: str | None = None, timeout: int = 120) -> str:
    """POST the prompt to {base_url}/chat/completions and return the reply text."""
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    body = json.dumps({"model": cfg["model"], "messages": messages}).encode("utf-8")
    req = urllib.request.Request(
        f"{cfg['base_url']}/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload["choices"][0]["message"]["content"]


def main(argv: list[str], env: dict[str, str] | None = None) -> int:
    env = dict(oss_model.os.environ) if env is None else env
    ap = argparse.ArgumentParser(description="One-shot question to an OSS provider (no tools).")
    ap.add_argument("provider", help="deepseek | glm | openrouter (or custom with --base-url/--model)")
    ap.add_argument("prompt", nargs="+", help="the question")
    ap.add_argument("--model", default=None)
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--system", default=None)
    args = ap.parse_args(argv)
    try:
        cfg = resolve_chat_config(args.provider, env, model=args.model, base_url=args.base_url)
    except oss_model.ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_CONFIG
    try:
        print(ask(cfg, " ".join(args.prompt), system=args.system))
    except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError, TimeoutError) as exc:
        print(f"oss_ask: endpoint/parse failure: {exc}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
