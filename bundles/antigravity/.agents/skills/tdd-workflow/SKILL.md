---
name: tdd-workflow
description: "Test-Driven Development workflow — red-green-refactor cycle"
---

# TDD Workflow

Test-Driven Development using the red-green-refactor cycle. Write tests first, implement minimum code to pass, then refactor with confidence.

## When to Use

- Writing new features or functionality
- Fixing bugs (write a test that reproduces it first)
- Refactoring existing code
- Adding API endpoints or service methods

## Phase 1: PLAN Tests

Map test cases before writing code. For each feature, identify:

1. **Happy path** — expected successful behavior
2. **Edge cases** — empty input, boundary values, None/null
3. **Error cases** — invalid input, missing resources, timeouts

```
Feature: Shorten URL
  - Happy: valid URL returns short code
  - Happy: same URL returns same code (idempotent)
  - Edge: very long URL (2048+ chars)
  - Error: invalid URL format
  - Error: empty string
```

## Phase 2: WRITE Failing Test (Red)

Write one test at a time. It must fail — this proves it tests something real.

```python
import pytest
from myapp.shortener import shorten_url

class TestShortenURL:
    def test_returns_short_code_for_valid_url(self):
        result = shorten_url("https://example.com/long/path")
        assert result is not None
        assert len(result) == 8

    def test_same_url_returns_same_code(self):
        code1 = shorten_url("https://example.com")
        code2 = shorten_url("https://example.com")
        assert code1 == code2

    def test_rejects_invalid_url(self):
        with pytest.raises(ValueError, match="Invalid URL"):
            shorten_url("not-a-url")

    @pytest.mark.parametrize("bad_input", ["", "ftp://wrong", None])
    def test_rejects_bad_inputs(self, bad_input):
        with pytest.raises(ValueError):
            shorten_url(bad_input)
```

Run and confirm failure:

```bash
pytest tests/test_shortener.py -v
# Expected: FAILED (module or assertions fail)
```

## Phase 3: IMPLEMENT Minimum Code (Green)

Write the simplest code that makes the failing test pass. No extras, no optimization.

```python
import hashlib, re

_store: dict[str, str] = {}

def shorten_url(url: str) -> str:
    if not url or not re.match(r"https?://\S+", url):
        raise ValueError("Invalid URL")
    code = hashlib.sha256(url.encode()).hexdigest()[:8]
    _store[code] = url
    return code
```

Run and confirm green:

```bash
pytest tests/test_shortener.py -v
# Expected: PASSED
```

## Phase 4: REFACTOR

Improve code quality while keeping all tests green.

**Production code:** extract helpers, improve naming, add type hints, remove duplication.

**Test code:** extract fixtures, use `conftest.py`:

```python
# tests/conftest.py
import pytest

@pytest.fixture(autouse=True)
def reset_store():
    from myapp.shortener import _store
    _store.clear()
```

Run after refactoring — still green:

```bash
pytest tests/test_shortener.py -v
```

## Phase 5: VERIFY Coverage

```bash
pip install pytest-cov
pytest --cov=myapp --cov-report=term-missing tests/
```

Enforce in CI:

```ini
# pyproject.toml
[tool.pytest.ini_options]
addopts = "--cov=myapp --cov-fail-under=80"
```

Look at the `Missing` column for untested lines. Common gaps: exception handlers, fallback branches, cleanup code.

## Testing Patterns

### Mocking External Dependencies

```python
from unittest.mock import patch, MagicMock

def test_fetches_remote_data():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"status": "ok"}
    mock_resp.status_code = 200
    with patch("myapp.client.requests.get", return_value=mock_resp):
        result = fetch_data("https://api.example.com/data")
        assert result == {"status": "ok"}
```

### Database Tests

```python
@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()

def test_creates_user(db_session):
    user = User(name="Alice", email="alice@test.com")
    db_session.add(user)
    db_session.commit()
    assert db_session.query(User).count() == 1
```

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Testing internal state (`obj._count`) | Test observable behavior (`obj.get_value()`) |
| Tests depend on each other | Each test sets up its own data |
| No assertions in test | Every test must assert something |
| Testing implementation details | Test what users/callers see |

## Quick Reference

```bash
pytest                                    # Run all tests
pytest tests/test_x.py -v                 # Run specific file, verbose
pytest tests/test_x.py::TestClass::test_y # Run single test
pytest --cov=myapp --cov-report=term-missing  # Coverage
pytest -x                                 # Stop at first failure
pytest --lf                               # Re-run last failures
ptw -- --cov=myapp                        # Watch mode (pytest-watch)
```
