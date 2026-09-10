---
name: python-development
description: Modern Python development with Python 3.12+, Django, FastAPI, async patterns, and production best practices. Use for Python projects, APIs, data processing, or automation scripts.
source: wshobson/agents
license: MIT
---

# Python Development

## Project Setup

### Modern Python Project Structure
```
my-project/
â”œâ”€â”€ src/
â”‚   â””â”€â”€ my_project/
â”‚       â”œâ”€â”€ __init__.py
â”‚       â”œâ”€â”€ main.py
â”‚       â””â”€â”€ utils.py
â”œâ”€â”€ tests/
â”‚   â”œâ”€â”€ __init__.py
â”‚   â””â”€â”€ test_main.py
â”œâ”€â”€ pyproject.toml
â”œâ”€â”€ README.md
â””â”€â”€ .gitignore
```

### pyproject.toml
```toml
[project]
name = "my-project"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.100.0",
    "pydantic>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "ruff>=0.1.0",
    "mypy>=1.0",
]

[tool.ruff]
line-length = 88
select = ["E", "F", "I", "N", "W"]

[tool.mypy]
strict = true
```

## Type Hints

```python
from typing import TypeVar, Generic
from collections.abc import Sequence

T = TypeVar('T')

def process_items(items: Sequence[str]) -> list[str]:
    return [item.upper() for item in items]

class Repository(Generic[T]):
    def get(self, id: int) -> T | None: ...
    def save(self, item: T) -> T: ...
```

## Async Patterns

```python
import asyncio
from collections.abc import AsyncIterator

async def fetch_all(urls: list[str]) -> list[dict]:
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_one(session, url) for url in urls]
        return await asyncio.gather(*tasks)

async def stream_data() -> AsyncIterator[bytes]:
    async with aiofiles.open('large_file.txt', 'rb') as f:
        async for chunk in f:
            yield chunk
```

## FastAPI Patterns

```python
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel

app = FastAPI()

class UserCreate(BaseModel):
    email: str
    name: str

class UserResponse(BaseModel):
    id: int
    email: str
    name: str

@app.post("/users", response_model=UserResponse)
async def create_user(
    user: UserCreate,
    db: Database = Depends(get_db)
) -> UserResponse:
    result = await db.users.create(user.model_dump())
    return UserResponse(**result)
```

## Testing

```python
import pytest
from unittest.mock import AsyncMock, patch

@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.users.get.return_value = {"id": 1, "name": "Test"}
    return db

@pytest.mark.asyncio
async def test_get_user(mock_db):
    result = await get_user(1, db=mock_db)
    assert result["name"] == "Test"
    mock_db.users.get.assert_called_once_with(1)
```

## Core Principles

### Readability First
Python prioritizes readability. Code should be obvious and easy to understand.

```python
# Good: Clear and readable
def get_active_users(users: list[User]) -> list[User]:
    """Return only active users from the provided list."""
    return [user for user in users if user.is_active]

# Bad: Clever but confusing
def get_active_users(u):
    return [x for x in u if x.a]
```

### EAFP Over LBYL
Python prefers exception handling over checking conditions upfront.

```python
# Good: EAFP style (Easier to Ask Forgiveness than Permission)
def get_value(dictionary: dict, key: str, default=None):
    try:
        return dictionary[key]
    except KeyError:
        return default

# Bad: LBYL (Look Before You Leap) style
def get_value(dictionary: dict, key: str, default=None):
    if key in dictionary:
        return dictionary[key]
    return default
```

## Error Handling Patterns

### Specific Exception Handling
```python
# Good: Catch specific exceptions with chaining
def load_config(path: str) -> Config:
    try:
        with open(path) as f:
            return Config.from_json(f.read())
    except FileNotFoundError as e:
        raise ConfigError(f"Config file not found: {path}") from e
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in config: {path}") from e

# Bad: Bare except with silent failure
def load_config(path: str) -> Config:
    try:
        with open(path) as f:
            return Config.from_json(f.read())
    except:
        return None
```

### Custom Exception Hierarchy
```python
class AppError(Exception):
    """Base exception for all application errors."""

class ValidationError(AppError):
    """Raised when input validation fails."""

class NotFoundError(AppError):
    """Raised when a requested resource is not found."""

def get_user(user_id: str) -> User:
    user = db.find_user(user_id)
    if not user:
        raise NotFoundError(f"User not found: {user_id}")
    return user
```

## Context Managers

```python
from contextlib import contextmanager

# Custom context manager for timing
@contextmanager
def timer(name: str):
    start = time.perf_counter()
    yield
    elapsed = time.perf_counter() - start
    print(f"{name} took {elapsed:.4f} seconds")

# Class-based context manager for transactions
class DatabaseTransaction:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        self.connection.begin_transaction()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.connection.commit()
        else:
            self.connection.rollback()
        return False  # Don't suppress exceptions
```

## Data Classes and Validation

```python
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class User:
    id: str
    name: str
    email: str
    created_at: datetime = field(default_factory=datetime.now)
    is_active: bool = True

    def __post_init__(self):
        if "@" not in self.email:
            raise ValueError(f"Invalid email: {self.email}")
```

## Decorators

```python
import functools

# Function decorator with wraps
def timer(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = time.perf_counter() - start
        print(f"{func.__name__} took {elapsed:.4f}s")
        return result
    return wrapper

# Parameterized decorator
def retry(max_attempts: int = 3, delay: float = 1.0):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        raise
                    time.sleep(delay * (2 ** attempt))
        return wrapper
    return decorator
```

## Comprehensions and Generators

```python
# List comprehensions for simple transforms
names = [user.name for user in users if user.is_active]

# Generator expressions for lazy evaluation (memory efficient)
total = sum(x * x for x in range(1_000_000))

# Generator functions for large data
def read_large_file(path: str) -> Iterator[str]:
    with open(path) as f:
        for line in f:
            yield line.strip()
```

## Concurrency Patterns

```python
import concurrent.futures

# Threading for I/O-bound tasks
def fetch_all_urls(urls: list[str]) -> dict[str, str]:
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_url = {executor.submit(fetch_url, url): url for url in urls}
        results = {}
        for future in concurrent.futures.as_completed(future_to_url):
            url = future_to_url[future]
            try:
                results[url] = future.result()
            except Exception as e:
                results[url] = f"Error: {e}"
    return results

# Multiprocessing for CPU-bound tasks
def process_all(datasets: list[list[int]]) -> list[int]:
    with concurrent.futures.ProcessPoolExecutor() as executor:
        return list(executor.map(process_data, datasets))
```

## Memory and Performance

```python
# Use __slots__ for memory efficiency in many-instance classes
class Point:
    __slots__ = ['x', 'y']
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y

# Use join instead of concatenation in loops
result = "".join(str(item) for item in items)  # O(n)
# NOT: result += str(item)  # O(n²)
```

## Anti-Patterns to Avoid

```python
# Bad: Mutable default arguments
def append_to(item, items=[]):  # Shared across calls!
    items.append(item)
    return items
# Good: Use None sentinel
def append_to(item, items=None):
    if items is None:
        items = []
    items.append(item)
    return items

# Bad: type(obj) == list  →  Good: isinstance(obj, list)
# Bad: value == None       →  Good: value is None
# Bad: from module import * →  Good: from module import specific_name
# Bad: bare except:         →  Good: except SpecificError as e:
```

## Python Tooling

```bash
# Formatting and linting
ruff check . && ruff format .
mypy .

# Testing with coverage
pytest --cov=mypackage --cov-report=term-missing

# Security scanning
bandit -r .
pip-audit
```

## Best Practices

- Use `ruff` for linting and formatting
- Use `mypy` with strict mode
- Prefer `pathlib.Path` over `os.path`
- Use dataclasses or Pydantic for data structures
- Use `asyncio` for I/O-bound operations
- Use `contextlib.asynccontextmanager` for async resources
- Use Protocol classes for structural subtyping (duck typing)
- Prefer generators over lists for large datasets
- Follow import order: stdlib, third-party, local (use isort)