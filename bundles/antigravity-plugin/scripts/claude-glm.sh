#!/usr/bin/env bash
# claude-glm — convenience alias: a Claude Code session on GLM (provider preset "glm").
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/claude-oss.sh" glm "$@"
