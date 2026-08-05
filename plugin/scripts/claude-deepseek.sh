#!/usr/bin/env bash
# claude-deepseek — convenience alias: a Claude Code session on DeepSeek (provider preset "deepseek").
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/claude-oss.sh" deepseek "$@"
