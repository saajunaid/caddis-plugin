---
name: error-handling
description: Error handling patterns for Python and TypeScript applications. Use when designing error hierarchies, implementing retry logic, building error boundaries, or establishing logging strategies. Covers custom exceptions, result types, circuit breakers, and user-facing error messages.
---

# Error Handling Skill

Errors are not exceptional — they are part of the contract. This skill defines how to classify, propagate, and recover from errors consistently.

## 1. When to Apply This Skill

**Trigger conditions:**
- Designing error handling for a new service or feature
- "How should we handle errors in this module?"
- Building retry logic or circuit breakers
- Reviewing code with bare `except:` or swallowed errors
- Establishing error handling conventions for a project

## 2. Error Classification

Every error falls into one of three categories. Handle each differently.

| Category | Retryable? | User Action? | Example |
|----------|-----------|-------------|---------|
| **Transient** | Yes | None (auto-retry) | Network timeout, DB connection dropped, rate limit |
| **Operational** | No | Inform user | Invalid input, resource not found, insufficient permissions |
| **Fatal** | No | Alert team | Corrupted state, config missing, unrecoverable assertion |

## 3. Python Exception Hierarchy

Build domain-specific exceptions. Never raise raw `Exception`.

```python
class AppError(Exception):
    """Base error for the application."""
    def __init__(self, message: str, code: str | None = None):
        self.message = message
        self.code = code or self.__class__.__name__
        super().__init__(self.message)

# Operational errors (expected, handled gracefully)
class NotFoundError(AppError):
    """Resource does not exist."""

class ValidationError(AppError):
    """Input validation failed."""

class AuthorizationError(AppError):
    """User not authorized for this action."""

# Transient errors (retry-eligible)
class TransientError(AppError):
    """Temporary failure — safe to retry."""

class ExternalServiceError(TransientError):
    """External API call failed."""

class DatabaseConnectionError(TransientError):
    """Database connection lost."""
```

### Usage Patterns

```python
# ✅ GOOD: Specific exception with context
def get_user(user_id: str) -> User:
    user = repo.find_by_id(user_id)
    if user is None:
        raise NotFoundError(f"User {user_id} not found")
    return user

# ✅ GOOD: Catch specific, re-raise as domain error
def fetch_external_data(url: str) -> dict:
    try:
        response = httpx.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except httpx.TimeoutException as e:
        raise ExternalServiceError(f"Timeout calling {url}") from e
    except httpx.HTTPStatusError as e:
        raise ExternalServiceError(f"HTTP {e.response.status_code} from {url}") from e

# ❌ BAD: Bare except swallows everything
try:
    result = process()
except:
    pass

# ❌ BAD: Catching too broadly
try:
    result = process()
except Exception:
    logger.error("Something went wrong")
    return None  # Hides the real error
```

## 4. TypeScript Error Patterns

### Result Type (for expected failures)

```typescript
type Result<T, E = Error> =
  | { ok: true; value: T }
  | { ok: false; error: E };

function parseConfig(raw: string): Result<Config, ValidationError> {
  try {
    const parsed = JSON.parse(raw);
    if (!isValidConfig(parsed)) {
      return { ok: false, error: new ValidationError("Invalid config shape") };
    }
    return { ok: true, value: parsed as Config };
  } catch {
    return { ok: false, error: new ValidationError("Invalid JSON") };
  }
}

// Usage — caller must handle both cases
const result = parseConfig(rawInput);
if (!result.ok) {
  showError(result.error.message);
  return;
}
useConfig(result.value);
```

### Error Boundaries (React)

```tsx
'use client';
import { Component, type ReactNode } from 'react';

interface Props { children: ReactNode; fallback: ReactNode; }
interface State { hasError: boolean; }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('Component error:', error, info.componentStack);
    // Report to error tracking service
  }

  render() {
    return this.state.hasError ? this.props.fallback : this.props.children;
  }
}
```

## 5. Retry with Exponential Backoff

```python
import asyncio
import random
from loguru import logger

async def retry_with_backoff(
    fn,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable_exceptions: tuple = (TransientError,),
):
    """Retry a function with exponential backoff and jitter."""
    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except retryable_exceptions as e:
            if attempt == max_retries:
                logger.error(f"All {max_retries} retries exhausted: {e}")
                raise
            delay = min(base_delay * (2 ** attempt), max_delay)
            jitter = random.uniform(0, delay * 0.1)
            logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay:.1f}s")
            await asyncio.sleep(delay + jitter)
```

## 6. FastAPI Error Handling

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from loguru import logger

app = FastAPI()

@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError):
    return JSONResponse(status_code=404, content={"error": exc.code, "message": exc.message})

@app.exception_handler(ValidationError)
async def validation_handler(request: Request, exc: ValidationError):
    return JSONResponse(status_code=422, content={"error": exc.code, "message": exc.message})

@app.exception_handler(AuthorizationError)
async def auth_handler(request: Request, exc: AuthorizationError):
    return JSONResponse(status_code=403, content={"error": exc.code, "message": exc.message})

@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled error on {request.method} {request.url}")
    # Never expose internal details to the client
    return JSONResponse(status_code=500, content={"error": "InternalError", "message": "An internal error occurred."})
```

## 7. Logging Errors Correctly

```python
from loguru import logger

# ✅ GOOD: Log with context, not just the message
logger.error(f"Failed to process order {order_id}: {e}", order_id=order_id, customer_id=customer_id)

# ✅ GOOD: Use exception() to capture stack trace
try:
    process_order(order)
except Exception as e:
    logger.exception(f"Order processing failed for {order.id}")
    raise

# ❌ BAD: Logging sensitive data
logger.error(f"Auth failed for {username} with password {password}")

# ❌ BAD: Logging without context
logger.error("Something failed")
```

## 8. Error Message Guidelines

| Audience | Include | Exclude |
|----------|---------|---------|
| **End user** | What happened, what to do next | Stack traces, internal IDs, SQL errors |
| **Developer (logs)** | Full context, request ID, stack trace | User passwords, tokens, PII |
| **API consumer** | Error code, human message, field-level detail | Server internals, file paths |

```python
# User-facing message
"Unable to load your dashboard. Please try again in a few minutes."

# API response
{"error": "ValidationError", "message": "Email format is invalid", "field": "email"}

# Log entry
"Validation failed on POST /api/users: email='not-an-email' — rejected by regex validator"
```

## 9. Anti-Patterns

| Anti-Pattern | Problem | Fix |
|---|---|---|
| Bare `except:` / `except Exception:` | Catches KeyboardInterrupt, SystemExit | Catch specific exceptions |
| `return None` on error | Caller has no idea what went wrong | Raise typed exception |
| Logging and re-raising | Double logging, noisy | Log at the boundary, not at every layer |
| String error codes | Typos, no autocomplete | Enum or class-based error codes |
| Swallowing errors in background tasks | Silent failures, data loss | Log + alert + dead-letter queue |
| Generic "Something went wrong" | User can't self-serve | Specific message + action hint |
