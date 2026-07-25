# Tests (`tests/`) — conventions

Scope: pytest backend suite. This folder is where **Law 1 (TDD) is enforced**. Inherits root laws.

## TDD is the default, not a phase
For any behavior change, the failing test is written and run **before** the implementation.
Red (fails for the right reason) → Green (minimal code) → Refactor (tests stay green). A test added
*after* the code is not TDD — call it what it is.

## Layout & naming
```
tests/conftest.py          shared fixtures (import the app lazily inside fixtures, not at module top)
tests/unit/                fast, isolated; mock external deps (DB, HTTP, services)
tests/integration/         TestClient / real wiring, dependency_overrides
tests/fixtures/            sample payloads / golden data
```
- Files: `test_<module>.py`. Functions: `test_<action>_<scenario>_<expected>`. Classes: `Test<Name>`.
- Arrange–Act–Assert. One behavior per test. Every test asserts something.

## Patterns
- **Async tests:** configure `asyncio_mode` (e.g. `auto` in `pyproject.toml`) so no per-test decorator
  is needed; otherwise mark them.
- **API tests:** use the framework TestClient; override deps with `app.dependency_overrides[dep]`; clear
  in teardown. Keep the suite free of real external services — mock or use in-memory/SQLite.
- **Edge cases mandatory:** empty, None, boundary, invalid type. Use parametrization.
- **Don't hard-import a heavy app at collection time** — import it lazily inside the fixture that needs
  it, so isolated tests stay cheap (Phase 0 learning).

## Commands
```
pytest tests/ -q
pytest tests/ --cov=<pkg> --cov-report=term-missing   # target ≥80% new code
pytest -x --lf
```

## Frontend tests
If a frontend exists, its unit/component tests (e.g. Vitest + Testing Library) live under `frontend/`
with the same TDD discipline. Ensure a DOM environment (jsdom/happy-dom) and a setup file are wired
before writing component tests.

Skills (caddis plugin, by name): `tdd-workflow`, `test-strategy`, `webapp-testing`.
