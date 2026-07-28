---
name: use-model
description: Explain (or apply) the model lanes — claude / claude-glm / cross-review — key resolution, and how to add a provider
---

# /caddis:use-model — switch which model backs your session

Explain the model-switching lanes so the user (or you, on their behalf) can move a session onto an
OSS provider (GLM, DeepSeek, OpenRouter, or a custom endpoint) in one command, with no hardcoded key
path. Full detail lives in the **Providers & keys** guide (`docs/guide/providers-and-keys.md`) — this
command is the quick-reference + do-it-now version.

## The lanes

| Lane | Command | Billing |
|---|---|---|
| **Primary** | `claude` | your Anthropic plan |
| **OSS lane** | `claude-oss <provider> [claude args…]` | the provider's plan/pay-per-token |
| **Convenience alias** | `claude-glm [claude args…]` | same as `claude-oss glm` |
| **Cross-vendor review** | `/caddis:cross-review` (`oss_review.py`) | the reviewer's plan |

`claude-oss` / `claude-glm` are launchers at `claude-harness/scripts/claude-oss.{sh,ps1}`. Each
resolves the endpoint/model/key, sets `ANTHROPIC_BASE_URL` / `ANTHROPIC_MODEL` / `ANTHROPIC_AUTH_TOKEN`
for **that process only**, and hands off to the real `claude` — your default session is untouched.

## Run it
```powershell
claude-oss glm -p "refactor X"        # or interactive: claude-oss glm
claude-glm -p "refactor X"            # convenience alias for provider=glm
claude-oss deepseek                   # any preset provider
```
```bash
claude-oss glm -p "refactor X"
claude-glm -p "refactor X"
```
$ARGUMENTS, if given, names the provider directly (`glm`, `deepseek`, `openrouter`, or any custom name
paired with `OSS_BASE_URL`/`OSS_MODEL`).

## Key resolution (never hardcoded)
Precedence, highest wins:
1. the provider's env var (`GLM_API_KEY` / `DEEPSEEK_API_KEY` / `OPENROUTER_API_KEY`) or generic `OSS_API_KEY`;
2. a keys file at `$CADDIS_KEYS_FILE` (default `~/.caddis/keys.env`, `KEY=VALUE` lines, `#` comments);
3. missing → the launcher exits non-zero with an actionable message naming the exact env var to set.

The resolver is `claude-harness/scripts/oss_model.py` (`resolve(provider, env)`) — the one place a
renamed model id or moved endpoint is edited (mirrors `oss_review.py`'s `PROVIDERS` table).

## Adding a provider (or overriding one)
No code change needed for a model-id bump — set env directly:
```powershell
$env:OSS_MODEL = "glm-5"              # override the preset's model
$env:OSS_BASE_URL = "https://..."     # override the preset's endpoint
```
A wholly new provider: add a row to `PROVIDERS` in `oss_model.py` (base_url, model, key_env), or just
pass an unknown provider name with `OSS_BASE_URL`+`OSS_MODEL` set — no table edit required.

## First-time install
Put `claude-harness/scripts/` (or your plugin's `scripts/` dir) on `PATH`, or add a shell profile
function. `/setup-project-ai` documents the one-liner for your platform (PowerShell profile function /
bash alias) — it does not silently edit your shell profile.

## Exit codes
`claude-oss`/`claude-glm` propagate the wrapped `claude` process's exit code, except a resolver failure
(unknown provider without an override, or no key) which exits **3** with the message on stderr.
