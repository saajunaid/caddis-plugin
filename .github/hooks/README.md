# Hooks Pack

Reusable git hooks for local quality gates before code reaches CI.

## Included Hooks

- `pre-commit-quality-gate.ps1` — Windows pre-commit checks
- `pre-commit-quality-gate.sh` — POSIX pre-commit checks
- `pre-push-quality-gate.ps1` — Windows pre-push checks (stricter gate)
- `pre-push-quality-gate.sh` — POSIX pre-push checks (stricter gate)
- `commit-msg-conventional.sh` — conventional commit format validator
- `install-hooks.ps1` — one-command installer for Git hooks (Windows/PowerShell)
- `install-hooks.sh` — one-command installer for Git hooks (POSIX)

## Adapted From Pool Assets

- `python.instructions.md` → Python lint/type/test expectations (`ruff`, `mypy`, `pytest`)
- `testing.instructions.md` → TDD + fail-fast verification behavior
- `prompts/conventional-commit.prompt.md` → commit message pattern enforcement
- `skills/workflow/verification-loop/SKILL.md` → pre-commit verification sequence

## Install (Windows)

Run:

```powershell
pwsh .github/hooks/install-hooks.ps1
```

This writes:
- `.git/hooks/pre-commit` (wrapper calling PowerShell quality gate when available, else `.sh`)
- `.git/hooks/commit-msg` (wrapper enforcing conventional commits)
- `.git/hooks/pre-push` (wrapper running stricter pre-push quality gate)

## Install (POSIX)

```bash
sh .github/hooks/install-hooks.sh
```

## Notes

- Hooks are local developer safety rails; CI remains the source of truth.
- Keep hooks fast. If checks exceed ~60 seconds, split heavy checks into pre-push/CI.
