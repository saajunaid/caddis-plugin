# Layer Responsibilities

Detailed specification for each layer in the data contract pipeline. When generating code for a layer, follow these rules exactly.

---

## Layer 1 — Source Adapter

**Location**: `src/services/adapters/` or `src/services/`  
**Responsibility**: Fetch raw data from external source and return it as a Python dict or list.

### Rules

- The adapter is the ONLY layer that knows about the source (file path, API URL, DB query)
- Returns raw `dict` / `list[dict]` — no Pydantic models, no transformations
- Handles connection errors, retries, and timeouts
- Logs the fetch operation (loguru, never print)
- Uses `pathlib.Path` for file paths, never hardcoded strings
- Environment-specific config (URLs, credentials) comes from `pydantic-settings`, never hardcoded

### Template

```python
from pathlib import Path
from loguru import logger

class {{SourceName}}Adapter:
    """Fetches raw {{source_name}} data from {{source_type}}."""

    def __init__(self, source_path: Path) -> None:
        self._source_path = source_path

    def fetch(self) -> dict:
        """Load raw payload. Returns unvalidated dict."""
        logger.debug(f"Fetching {{source_name}} from {self._source_path}")
        # Source-specific fetch logic here
        ...
```

### Anti-patterns

- ❌ Adapter validates or transforms data (that's the normalizer's job)
- ❌ Adapter returns a Pydantic model (that couples adapter to schema)
- ❌ Adapter catches and silently swallows errors

---

## Layer 2 — Ingestion Model

**Location**: `src/models/ingestion/`  
**Responsibility**: Pydantic model that matches the raw source payload shape exactly (1:1).

### Rules

- Every key in the source payload MUST have a corresponding field
- Field types match the source data types (str, int, float, list, dict, None)
- Use `Optional[T]` for keys that may be null or absent in some payloads
- Use `Field(alias=...)` only if the source key name is not valid Python (e.g., contains spaces or special chars)
- Use `extra="allow"` during initial development to catch unexpected keys
- Nested objects get their own ingestion model
- This model is NOT the API response — it exists to validate raw data
- **Share a `_FLEX` config constant** across all ingest DTOs so the `extra="allow"` policy is centralized

### Template

```python
from pydantic import BaseModel, ConfigDict, Field

# Shared config for all data-ingest DTOs.  extra="allow" means unknown keys
# land in model_extra and flow through — nothing is silently dropped.
_FLEX = ConfigDict(populate_by_name=True, extra="allow")


class {{SourceName}}Payload(BaseModel):
    """1:1 representation of raw {{source_name}} payload."""
    model_config = _FLEX

    {{field_name}}: {{raw_type}}
    # ... one field per source key
```

### Anti-patterns

- ❌ Dropping fields that "aren't needed yet" (breaks contract completeness)
- ❌ Applying business logic (renaming, computing, filtering)
- ❌ Using `extra="ignore"` (hides new source fields)
- ❌ Declaring `ConfigDict(extra="allow")` inline on every model instead of sharing a `_FLEX` constant

---

## Layer 3 — Normalizer

**Location**: `src/services/normalizers/`  
**Responsibility**: Transform ingestion model into display DTO. This is where business logic lives.

### Rules

- Input: ingestion model instance. Output: display DTO instance
- Handles field renaming, unit conversion, computed fields, filtering
- Every transformation is explicit — no implicit field passing
- Pure function where possible (no side effects, no DB calls)
- If a field is intentionally dropped, document WHY with a comment

### Template

```python
from src.models.ingestion.{{source_slug}} import {{SourceName}}Payload
from src.models.responses.{{source_slug}} import {{DtoName}}

def normalize_{{source_slug}}(raw: {{SourceName}}Payload) -> {{DtoName}}:
    """Transform raw {{source_name}} payload into display DTO."""
    return {{DtoName}}(
        {{dto_field}}=raw.{{source_field}},
        # Computed fields
        {{computed_field}}=_compute_{{computed_field}}(raw),
    )
```

### Anti-patterns

- ❌ Normalizer fetches data (that's the adapter's job)
- ❌ Normalizer returns dict instead of DTO (loses type safety)
- ❌ Implicit field dropping without documentation

---

## Layer 4 — Display DTO

**Location**: `src/models/responses/`  
**Responsibility**: Frozen Pydantic model defining the API boundary contract.

### Rules

- `frozen=True` — immutable after construction
- `populate_by_name=True` — can construct with Python names or aliases
- `extra="forbid"` — no silent data loss (use "allow" only during migration, with logging)
- `Field(alias="camelCaseName")` for every field exposed to frontend
- All fields have type annotations
- Optional fields have explicit defaults (`Field(default_factory=list)`)
- This is the API contract — changes here require frontend coordination

### Template

```python
from pydantic import BaseModel, ConfigDict, Field

class {{DtoName}}(BaseModel):
    """API response DTO for {{source_name}}."""
    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        extra="forbid",
    )

    {{field_name}}: {{python_type}} = Field(alias="{{camelCaseName}}")
```

### Anti-patterns

- ❌ `extra="ignore"` — silently drops fields, causes data loss bugs
- ❌ Mutable DTO — allows post-construction tampering
- ❌ Missing aliases — forces frontend to use snake_case
- ❌ Any field — loses type safety at the API boundary

---

## Layer 5 — API Router

**Location**: `src/api/routers/`  
**Responsibility**: FastAPI endpoint that returns typed `response_model`.

### Rules

- Always set `response_model=DtoName` on the endpoint
- Router calls service layer, never adapter or repository directly
- Returns DTO instance, not dict
- Error handling returns structured error responses, not stack traces
- Follows REST conventions for path naming

### Template

```python
from fastapi import APIRouter, Depends
from src.models.responses.{{source_slug}} import {{DtoName}}
from src.services.{{source_slug}}_service import get_{{source_slug}}

router = APIRouter(prefix="/api/{{source-slug}}", tags=["{{source_name}}"])

@router.get("/", response_model={{DtoName}})
async def get_data(
    # query params here
):
    """Get {{source_name}} data."""
    return await get_{{source_slug}}()
```

### Anti-patterns

- ❌ No `response_model` — FastAPI can't validate the response shape
- ❌ Returning raw dict — bypasses DTO validation
- ❌ Business logic in router — should be in service layer

---

## Layer 6 — Frontend Types

**Location**: `frontend/src/types/`  
**Responsibility**: TypeScript interfaces that mirror the display DTO.

### Rules

- One interface per DTO, field names match DTO aliases (camelCase)
- Use strict TypeScript types — no `any`
- Nested objects get their own interface
- Export from a barrel file (`index.ts`) for clean imports
- When DTO changes, TypeScript interface changes in the same PR

### Template

```typescript
export interface {{DtoName}} {
  {{camelCaseName}}: {{tsType}};
}
```

### Type Mapping

| Python Type | TypeScript Type |
|------------|----------------|
| `str` | `string` |
| `int`, `float` | `number` |
| `bool` | `boolean` |
| `list[T]` | `T[]` |
| `dict[str, T]` | `Record<string, T>` |
| `Optional[T]` | `T \| null` |
| `datetime` | `string` (ISO format) |
| `Decimal` | `number` |

---

## Layer 7 — Frontend Service

**Location**: `frontend/src/services/`  
**Responsibility**: Typed fetch/axios functions that call the API and return typed data.

### Rules

- Every function has a return type matching the TypeScript interface
- Base URL from environment config, never hardcoded
- Error handling with typed error responses
- Uses the project's HTTP client (axios, fetch, React Query, etc.)

### Template

```typescript
import type { {{DtoName}} } from '@/types/{{source-slug}}';
import { apiClient } from '@/lib/api-client';

export async function get{{DtoName}}(): Promise<{{DtoName}}> {
  const { data } = await apiClient.get<{{DtoName}}>('/api/{{source-slug}}');
  return data;
}
```

### Anti-patterns

- ❌ `any` return type — loses type safety
- ❌ Raw `fetch()` without error handling
- ❌ Hardcoded API URL

---

## Layer 8 — Contract Tests

**Location**: `tests/unit/test_contract_*.py`  
**Responsibility**: Validate alignment between layers using golden sample payloads.

### Rules

- At minimum: payload → DTO validation, uncovered keys check
- Tests run fast (no network, no database)
- Tests use golden sample from `tests/fixtures/payloads/`
- Each data source gets its own test file
- Test names describe what contract they validate

### Test Categories

1. **Structural**: Does the payload parse into the DTO?
2. **Coverage**: Does the DTO cover all payload keys?
3. **Alias**: Do aliases match the camelCase keys the frontend expects?
4. **Optional**: Do fields with defaults handle absent keys?
5. **Cross-layer**: Do TypeScript interface properties match DTO aliases?

See [drift-check-catalog.md](./drift-check-catalog.md) for the complete check list.

---

## Schema Evolution Lifecycle

Data pipelines rarely start with a frozen schema. This lifecycle describes how the three-layer defence adapts as the upstream schema matures.

### Three-Layer Defence Summary

| Layer | Mechanism | Purpose |
|-------|-----------|----------|
| **1 — Passthrough** | `extra="allow"` on all ingest DTOs (`_FLEX`) | Unknown keys flow through `model_extra` instead of being silently dropped |
| **2 — Drift detection** | Recursive `_collect_dropped_keys()` in contract tests | Compares raw JSON keys vs DTO field aliases at every nesting depth |
| **3 — Exclusion allow-list** | `KNOWN_EXCLUDED_KEYS` dict with fnmatch globs | Intentionally untyped keys don't pollute drift reports |

### Workflow by Schema State

| Pipeline state | `extra=` config | Drift test mode | Action |
|---|---|---|---|
| **Schema evolving daily** | `extra="allow"` (`_FLEX`) | Soft warning — `warnings.warn()`, CI passes | New keys flow through `model_extra`; drift reports show untyped keys as non-blocking warnings |
| **Schema stabilised / frozen** | `extra="forbid"` on display DTO; `extra="allow"` on ingest if you want to catch new keys | Hard assert — `assert dropped == []`, CI blocks | Type all remaining `model_extra` keys; set `CONTRACT_SCHEMA_FROZEN=1` (preferred), or `_contract_state.json` (`{"schema_frozen": true}`), or rely on CI fallback |
| **Key intentionally untyped** | n/a | Both modes | Add to `KNOWN_EXCLUDED_KEYS` with fnmatch glob + ticket ref; key is silently excluded from drift detection |

### Decision Checklist for New JSON Keys

1. **Is the key in every payload?** → Add typed field to the DTO now.
2. **Is it experimental / may be removed?** → Leave untyped; `extra="allow"` forwards it. Add to `KNOWN_EXCLUDED_KEYS` if the warning is noisy.
3. **Is it deprecated upstream?** → Add to `KNOWN_EXCLUDED_KEYS` permanently with ticket ref.
4. **Is the schema frozen?** → Switch drift test to hard assert via precedence: `CONTRACT_SCHEMA_FROZEN=1` (preferred), then `_contract_state.json`, then CI fallback. Any new untyped key is a CI failure.

### Anti-Patterns

| Anti-pattern | Why it fails | Correct approach |
|---|---|---|
| `extra='ignore'` on ingest DTOs | Silently drops evolving fields | `extra='allow'` — data flows through |
| Shape-only tests (`len(surveys) == 3`) | Pass even when half the fields are dropped | Recursive key-vs-field comparison |
| Hardcoded expected-key lists in tests | Stale within a week | Read actual JSON files, compare dynamically |
| One giant DTO with all fields optional | No validation, no IDE support | Nested models with required + optional typed fields |
| `model_dump(exclude_unset=True)` to hide extras | Hides the problem, doesn’t fix it | Let `model_extra` flow through; type when ready |
