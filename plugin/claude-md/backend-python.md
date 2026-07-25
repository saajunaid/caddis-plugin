# Backend (`src/`) — conventions

Scope: Python backend. Inherits all root laws (TDD, no absolute paths, no silent failures).

## Rules
- **Full type hints** on functions; keep functions small and single-purpose.
- **Config via a settings object** (e.g. pydantic-settings), loaded from env/config files — not
  `os.getenv` scattered through the code.
- **Logging, not print.** Structured logger; log on error paths (Law 3 — no silent swallow).
- **Errors:** raise specific exceptions; never bare `except: pass`. Catch narrowly, log, re-raise or
  map to a typed/HTTP error.
- **Data access is isolated** (a repository/store layer) — business logic and queries don't live in
  entrypoints/handlers.
- **Parameterized queries only.** Never string-interpolate user input into SQL.
- Lint/format with the project's tool (e.g. `ruff`); respect its line length.

## Adding functionality (the path)
1. Failing test first in `tests/` (see `tests/CLAUDE.md`).
2. Types/DTOs for the boundary.
3. Logic in the service/repository layer.
4. Wire the entrypoint.
5. Run the suite → green. Run the linter.

Skills (caddis plugin, by name): `python`, `error-handling`, `refactoring`.
