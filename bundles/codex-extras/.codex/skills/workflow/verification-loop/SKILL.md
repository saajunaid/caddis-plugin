---
name: verification-loop
context: fork
description: "Systematic code change verification — lint, test, type-check, review"
---

# Verification Loop

Systematic checklist to verify code changes before committing or opening a PR.

## When to Use

- After completing a feature or significant code change
- Before creating a commit or pull request
- After refactoring
- Periodically during long coding sessions (every 15-30 min)

## Phase 1: Build Verification

Confirm the project compiles without errors.

```bash
# Python
python -m py_compile myapp/main.py

# JavaScript/TypeScript
npm run build

# Go
go build ./...
```

**If the build fails, stop and fix before continuing.**

## Phase 2: Type Check

```bash
# Python
mypy myapp/ --ignore-missing-imports
# or: pyright myapp/

# TypeScript
npx tsc --noEmit

# Go
go vet ./...
```

Fix critical type errors. Defer warnings only if they're cosmetic.

## Phase 3: Lint Check

```bash
# Python
ruff check . --fix
ruff format . --check

# JavaScript/TypeScript
npx eslint . --fix
npx prettier --check .

# Go
golangci-lint run
```

| Category | Action |
|----------|--------|
| Errors (unused imports, undefined vars) | Fix now |
| Warnings (complexity, naming) | Fix if easy |
| Style (line length, whitespace) | Auto-fix |

## Phase 4: Test Suite

```bash
# Python
pytest --cov=myapp --cov-report=term-missing -v

# JavaScript/TypeScript
npm test -- --coverage

# Go
go test ./... -cover
```

Record: tests passed/failed, coverage %, duration. If tests fail, check whether the failure is in your changed code or pre-existing.

## Phase 5: Security Scan

```bash
# Secrets detection in staged files
git diff --cached --name-only | xargs grep -l -E \
  "(api_key|secret|password|token)\s*=\s*['\"][^'\"]+['\"]" 2>/dev/null

# Dependency audit
pip audit          # Python
npm audit          # JavaScript
govulncheck ./...  # Go

# Debug artifacts
grep -rn "breakpoint()" --include="*.py" myapp/
grep -rn "console\.log" --include="*.ts" src/
```

## Phase 5A: Dead Code & Orphan Scan

Catch unreachable, unused, and orphaned symbols before they accumulate.

```bash
# TypeScript / JavaScript — pick one tool
npx ts-prune --project tsconfig.json   # unused exports (TS)
npx knip                               # unused files, exports, deps (TS/JS)

# Python
pip install vulture
vulture myapp/ --min-confidence 80     # unused code (functions, classes, vars)

# Quick grep fallback (any language)
# Find symbols defined but never imported/called in the rest of the repo
# (adjust pattern to project conventions)
grep -rn "^export function \|^export class \|^def " --include="*.ts" --include="*.py" src/
```

**Checklist:**
- [ ] No new unused exports introduced by this change
- [ ] No orphaned files (created but never imported)
- [ ] Removed code has no remaining stale import sites

**Standing rule:** Do not commit a change that introduces new orphans or dead exports. If a symbol is intentionally exported for external consumers, add a `// @public` comment or equivalent project convention to suppress false positives.

## Phase 6: Diff Review

```bash
git diff --stat           # Summary
git diff --cached         # Staged changes
git diff --name-only HEAD # Changed files
```

For each changed file check:
- [ ] No unintended changes or debug code
- [ ] Error handling present for new code paths
- [ ] Edge cases handled (empty input, None, boundaries)
- [ ] No unaddressed TODO/FIXME for this PR

## Verification Report

```
VERIFICATION REPORT
===================
Build:     PASS
Types:     PASS (0 errors)
Lint:      PASS (2 warnings — deferred)
Tests:     PASS (42/42 passed, 84% coverage)
Security:  PASS (0 secrets, 0 vulnerabilities)
Diff:      5 files changed (+120, -45)

Status:    READY for commit/PR
```

| Status      | Meaning                                     |
|-------------|---------------------------------------------|
| READY       | All checks pass, safe to commit/PR          |
| NEEDS FIXES | Blocking issues — fix before proceeding     |
| PARTIAL     | Non-blocking warnings — document and proceed|

## Automation

### Pre-Commit Hook

```bash
#!/bin/sh
ruff check . || exit 1
mypy myapp/ || exit 1
pytest --cov=myapp --cov-fail-under=80 -q || exit 1
echo "All checks passed."
```

### CI Pipeline

```yaml
# .github/workflows/verify.yml
name: Verify
context: fork
on: [push, pull_request]
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -r requirements.txt
      - run: ruff check .
      - run: mypy myapp/
      - run: pytest --cov=myapp --cov-fail-under=80
      - run: pip audit
```

## Quick Reference

```bash
# Full verification
ruff check . && mypy myapp/ && pytest --cov=myapp -v && pip audit

# Quick check (lint + tests)
ruff check . && pytest -x -q

# Periodic checkpoint
python -m py_compile myapp/main.py && ruff check . && pytest -x -q
```
