#!/usr/bin/env sh
set -eu

echo "[hook] pre-push quality gate"

if [ -f "pyproject.toml" ] || [ -f "requirements.txt" ]; then
  if command -v ruff >/dev/null 2>&1; then
    echo "[hook] ruff check ."
    ruff check .
  fi

  if command -v mypy >/dev/null 2>&1; then
    echo "[hook] mypy ."
    mypy .
  fi

  if command -v pytest >/dev/null 2>&1; then
    echo "[hook] pytest -q"
    pytest -q
  fi
fi

if [ -f "package.json" ] && command -v npm >/dev/null 2>&1; then
  if npm run | grep -q " lint"; then
    echo "[hook] npm run lint"
    npm run lint
  fi
  if npm run | grep -q " typecheck"; then
    echo "[hook] npm run typecheck"
    npm run typecheck
  fi
  if npm run | grep -q " test"; then
    echo "[hook] npm test -- --runInBand"
    npm test -- --runInBand
  fi
fi

echo "[hook] pre-push quality gate completed"
