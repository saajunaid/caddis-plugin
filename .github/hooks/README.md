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
- The pre-push ruff, mypy and pytest steps check the project's own scope, never the whole tree
  (`gate_scope.py`): the tool's config when it states one (mypy `files`, pytest `testpaths`),
  otherwise only git-tracked Python. An untracked scratch file can never block a push.
- To match CI exactly, state the scope: `files = ["src"]` under `[tool.mypy]`, and
  `testpaths = ["tests"]` under `[tool.pytest.ini_options]`.
- The ruff step skips `.github/hooks/`: that folder is caddis's own, linted strictly at the
  source, and a project's rule set is not something a shipped file can satisfy. Concretely:
  `gate_scope.py` ships into every consumer repo and cannot carry any `noqa` at all — a bare
  `# ruff: noqa` fails a consumer that enables `PGH004` (bare noqa banned), and a coded
  `# ruff: noqa: S603, S607` fails one that enables `RUF100` but not the `S` rules. No form
  survives every rule set a consumer might choose, and `S603`/`S607` cannot both be satisfied by
  any subprocess call in the first place (one wants a literal command, the other an absolute
  path). Use `--extend-exclude`, never `--exclude` — the latter REPLACES the consumer's own
  excludes instead of adding to them (measured with ruff 0.16.7 on scratch copies, 2026-09-11).
- Keep hooks fast. If checks exceed ~60 seconds, split heavy checks into pre-push/CI.
