#!/usr/bin/env sh
set -eu

MSG_FILE="$1"
PATTERN='^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\(.+\))?(!)?: .{1,72}$'

if ! head -1 "$MSG_FILE" | grep -qE "$PATTERN"; then
  echo "Invalid commit message format."
  echo "Expected: <type>[scope]: <subject>"
  echo "Example:  docs(readme): document new analytics route"
  exit 1
fi
