#!/usr/bin/env sh
set -eu

echo "[hook] pre-commit quality gate"

if [ -f "validate_pool.py" ]; then
  if [ -x ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    PYTHON_BIN=""
  fi

  if [ -n "$PYTHON_BIN" ]; then
    echo "[hook] python validate_pool.py"
    "$PYTHON_BIN" validate_pool.py
  fi
fi

# Doc-coverage discipline — dogfood on the caddis repo itself. set -eu means a hard failure
# (missing route / dangling doc-map link) aborts the commit. No-op if the checker is absent.
if [ -f "claude-harness/scripts/check_doc_coverage.py" ]; then
  DOC_PY=$(command -v python || command -v python3 || true)
  if [ -n "$DOC_PY" ]; then
    echo "[hook] doc coverage"
    "$DOC_PY" claude-harness/scripts/check_doc_coverage.py --check
  fi
fi

if [ -f "pyproject.toml" ] || [ -f "requirements.txt" ]; then
  if command -v ruff >/dev/null 2>&1; then
    echo "[hook] ruff check ."
    ruff check .
  fi

  if command -v mypy >/dev/null 2>&1; then
    echo "[hook] mypy (best-effort)"
    mypy . || true
  fi

  if command -v pytest >/dev/null 2>&1; then
    echo "[hook] pytest -q"
    pytest -q || true
  fi
fi

if [ -f "package.json" ]; then
  if command -v npm >/dev/null 2>&1; then
    if npm run | grep -q " lint"; then
      echo "[hook] npm run lint"
      npm run lint
    fi
    if npm run | grep -q " typecheck"; then
      echo "[hook] npm run typecheck"
      npm run typecheck
    fi
  fi
fi

echo "[hook] quality gate completed"
