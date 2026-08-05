#!/usr/bin/env bash
# claude-oss / claude-glm — launch a Claude Code session against an OSS provider's
# Anthropic-protocol endpoint (GLM, DeepSeek, or a custom OSS_BASE_URL/OSS_MODEL;
# OpenRouter/local models need an Anthropic-compatible gateway — see LOCAL-MODELS.md).
#
# Usage:
#   claude-oss <provider> [claude args...]     # e.g. claude-oss glm -p "say ok"
#   claude-glm [claude args...]                # convenience alias (provider = glm)
#
# The endpoint/model/key are resolved by oss_model.py (keys are never hardcoded — see
# CADDIS_KEYS_FILE). This runs as its OWN process and `exec`s claude, so the
# ANTHROPIC_* env it sets dies with it — your default `claude` is untouched.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# claude-glm is the same launcher symlinked/renamed: force provider=glm and treat every
# arg as a claude arg. Otherwise the first arg is the provider.
case "$(basename "$0")" in
  claude-glm*) provider="glm" ;;
  *)
    provider="${1:-}"
    if [ "$#" -gt 0 ]; then shift; fi
    ;;
esac

if [ -z "${provider}" ]; then
  echo "usage: claude-oss <provider> [claude args...]   (providers: deepseek, glm, openrouter)" >&2
  exit 2
fi

# claude's -p/--print means no human is watching. Say so in the env so the caddis hooks can
# act on it — the SessionStart relay injection is skipped for headless runs, because a run
# handed its task on the command line does not need a resume pointer and was observed
# EXECUTING the relay's leftover next step before its own prompt.
for _arg in "$@"; do
  case "$_arg" in
    -p|--print) export CADDIS_HEADLESS=1 ;;
  esac
done

# Prefer python3, fall back to python.
PY="python3"; command -v "$PY" >/dev/null 2>&1 || PY="python"

# Resolve endpoint/model/key. On failure the resolver prints an actionable message to
# stderr and exits non-zero — propagate that (command substitution lets us check it).
if ! _out="$("$PY" "$SCRIPT_DIR/oss_model.py" "$provider")"; then
  exit 3
fi

# Split the three lines (base_url, model, api_key) into the env WITHOUT echoing them.
{
  IFS= read -r ANTHROPIC_BASE_URL
  IFS= read -r ANTHROPIC_MODEL
  IFS= read -r ANTHROPIC_AUTH_TOKEN
} <<< "$_out"
export ANTHROPIC_BASE_URL ANTHROPIC_MODEL ANTHROPIC_AUTH_TOKEN

# Hand off to the real claude with all remaining args (exec = env dies with this process).
exec claude "$@"
