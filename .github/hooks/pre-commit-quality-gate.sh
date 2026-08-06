#!/usr/bin/env sh
set -eu

echo "[hook] pre-commit quality gate"

# ONE interpreter for the whole hook, project venv preferred.
#
# This previously probed only `.venv/bin/python` - the POSIX layout - so on Windows, where
# the venv is `.venv/Scripts/python.exe`, it fell through to PATH and used the machine-wide
# interpreter. And the tool checks below used bare `ruff`/`mypy`/`pytest` regardless, so the
# hook already knew about the venv and then declined to use it for the things that mattered.
PY=""
for cand in .venv/Scripts/python.exe .venv/bin/python venv/Scripts/python.exe venv/bin/python; do
  if [ -x "$cand" ]; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then PY=$(command -v python || command -v python3 || true); fi

# Runnable IN $PY, not merely on PATH - the question is about the environment the code
# imports from, which is not the question `command -v` answers.
py_has() { [ -n "$PY" ] && "$PY" -m "$1" --version >/dev/null 2>&1; }

if [ -f "validate_pool.py" ] && [ -n "$PY" ]; then
  echo "[hook] python validate_pool.py"
  "$PY" validate_pool.py
fi

# Doc-coverage discipline - dogfood on the caddis repo itself. set -eu means a hard failure
# (missing route / dangling doc-map link) aborts the commit. No-op if the checker is absent.
if [ -f "claude-harness/scripts/check_doc_coverage.py" ] && [ -n "$PY" ]; then
  echo "[hook] doc coverage"
  "$PY" claude-harness/scripts/check_doc_coverage.py --check
fi

# Pre-commit stays FAST and mostly advisory by design: mypy and pytest keep their `|| true`
# so a slow or noisy check never blocks a commit. pre-push is the gate that actually decides.
# Only the interpreter resolution changed here, not which checks are blocking.
if [ -f "pyproject.toml" ] || [ -f "requirements.txt" ]; then
  if py_has ruff; then
    echo "[hook] ruff check ."
    "$PY" -m ruff check .
  fi

  if py_has mypy; then
    echo "[hook] mypy (best-effort)"
    "$PY" -m mypy . || true
  fi

  if py_has pytest; then
    echo "[hook] pytest -q"
    "$PY" -m pytest -q || true
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
