#!/usr/bin/env sh
set -eu

echo "[hook] pre-push quality gate"

# Tools run in the PROJECT'S interpreter, not whatever is on PATH.
#
# The old version called bare `ruff` / `mypy` / `pytest`. On Windows that resolves to the
# machine-wide interpreter, so the gate tested the project in an environment without the
# project's dependencies - while a tool present only in the venv was reported "not
# installed" and silently skipped. It ran the checks that could not work and skipped the
# ones that would. Found by a fresh-scaffold dry run, 2026-08-06.
PY=""
for cand in .venv/Scripts/python.exe .venv/bin/python venv/Scripts/python.exe venv/bin/python; do
  if [ -x "$cand" ]; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then PY=$(command -v python || command -v python3 || true); fi

# Runnable IN $PY, not merely present on PATH: `command -v mypy` answers a question about
# PATH, and the question that matters is about the environment the code imports from.
py_has() { [ -n "$PY" ] && "$PY" -m "$1" --version >/dev/null 2>&1; }
# Does the project ASK for this tool? Being unable to run a declared tool is a broken
# environment, not a project without linting - so it fails rather than skipping.
py_wants() { grep -qi -- "$1" pyproject.toml requirements.txt requirements-dev.txt 2>/dev/null; }

# Does this project actually contain Python source? A pyproject.toml alone does not mean it
# does - a config-only or frontend repo can carry one - and mypy exits non-zero with "There
# are no .py[i] files in directory" when handed nothing. Skipping a checker that has nothing
# to check is honest; failing the push over it is not.
py_sources_exist() {
  [ -n "$(find . -name '*.py' -not -path './.venv/*' -not -path './venv/*'             -not -path './node_modules/*' -not -path './.git/*' 2>/dev/null | head -1)" ]
}

py_gate() {
  tool=$1; shift
  if py_has "$tool"; then
    echo "[hook] $tool $*"
    rc=0
    "$PY" -m "$tool" "$@" || rc=$?
    if [ "$rc" -ne 0 ]; then
  # pytest exit 5 = "no tests collected". A repo that has not written tests yet is not a
  # failing repo, and blocking it would hit exactly the fresh-scaffold case this fix exists
  # for. Every other non-zero code is a real failure.
      if [ "$tool" = "pytest" ] && [ "$rc" -eq 5 ]; then
        echo "[hook] pytest: no tests collected yet - not treated as a failure"
      else
        exit 1
      fi
    fi
  elif py_wants "$tool"; then
    echo "[hook] $tool: DECLARED by this project but not runnable in $PY - environment is broken" >&2
    echo "       fix: activate the venv, or reinstall dev deps (pip install -e '.[dev]')" >&2
    exit 1
  fi
}

if [ -f "pyproject.toml" ] || [ -f "requirements.txt" ]; then
  if [ -z "$PY" ]; then
    echo "[hook] python project, but no interpreter found (.venv or PATH) - cannot verify" >&2
    exit 1
  fi
  echo "[hook] interpreter: $PY"
  py_gate ruff check .
  if py_sources_exist; then py_gate mypy .; else echo "[skip] mypy: no Python sources"; fi
  py_gate pytest -q
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
