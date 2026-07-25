# Consumer-Driven Contracts

Reference summary of the Consumer-Driven Contracts pattern for data pipeline alignment.

---

## Origin

**Consumer-Driven Contracts** (Ian Robinson, Martin Fowler — 2006) is a pattern for managing service integration where the **consumer** declares what it needs from a provider, and the provider validates that it satisfies all consumer expectations.

---

## Core Principles

### 1. Contracts Are Code, Not Docs

Documentation drifts. Contract **tests** are the source of truth.

```
❌ "The API returns these fields" (in a wiki page)
✅ test_api_returns_expected_fields() (in the test suite)
```

### 2. Consumer Declares Needs

The frontend (consumer) declares which fields it needs. The backend (provider) validates it serves them. This inverts the usual direction — instead of the backend dictating "here's what I send", the frontend says "here's what I need."

In practice: TypeScript interfaces define the contract. Python DTOs validate they provide those fields.

### 3. Additive Evolution

Schema changes are additive — add optional fields with defaults. Never remove or rename a field without coordinating with all consumers.

```python
# ✅ Safe evolution: new optional field with default
class MetricsResponse(BaseModel):
    nps: float
    responses: int
    # New field — existing consumers ignore it, new consumers use it
    trend_direction: str = Field(default="stable", alias="trendDirection")
```

### 4. Just Enough Validation

Validate what matters at each layer:

| Layer | Validates |
|-------|-----------|
| Ingestion Model | "Does the raw data have the expected shape?" |
| Display DTO | "Does the API output have the exact contracted shape?" |
| Contract Test | "Do all layers agree on the same shape?" |

Don't over-validate at every layer. The ingestion model can be lenient (`extra="allow"`). The display DTO must be strict (`extra="forbid"`).

### 5. Fail Fast, Fail Loud

When a contract violation is detected, it should be an error — not a warning, not a log line.

```python
# ❌ Silent handling
try:
    dto = MyDTO.model_validate(data)
except ValidationError:
    return {}  # Silent failure — consumer gets empty data

# ✅ Fail loud
dto = MyDTO.model_validate(data)  # Raises ValidationError with details
```

---

## How This Maps to Our Pipeline

| CDC Concept | Our Implementation |
|-------------|-------------------|
| Consumer | Frontend TypeScript types + service functions |
| Provider | Backend display DTO + API router |
| Contract | Contract tests in `tests/unit/test_contract_*.py` |
| Contract verification | `pytest` (local) → CI pipeline (when available) |
| Golden sample | `tests/fixtures/payloads/{source}/sample.json` |
| Schema evolution | Additive fields with defaults, never `extra="ignore"` |

---

## Golden Sample Pattern

A **golden sample** is a curated, representative payload from the source that serves as the reference for all contract tests.

### Properties of a Good Golden Sample

1. **Complete**: Contains all known keys, including optional ones
2. **Representative**: Values are realistic (not all null or placeholder)
3. **Sanitized**: No PII, credentials, or sensitive data
4. **Versioned**: Old samples renamed (not deleted) when schema changes
5. **Committed**: Checked into version control, not generated at test time

### How to Create One

1. Copy a real payload from the source (API response, JSON file, DB query result)
2. Sanitize: replace real names, emails, IDs with realistic fakes
3. Save to `tests/fixtures/payloads/{source_name}/sample.json`
4. Commit with a descriptive message: `test: add golden sample for {source_name}`

---

## Postel's Law and Its Limits

> "Be conservative in what you send, liberal in what you accept."
> — *Jon Postel, RFC 761 (1980)*

This works for **ingestion models** (accept broad input to avoid brittle failures on new keys).

It does NOT work for **display DTOs** at the API boundary. Display DTOs must be explicit:

- **Conservative in what you send**: Only send fields the consumer declared it needs
- **Explicit about what you accept**: `extra="forbid"` — don't silently drop or add fields

The failure mode of Postel's Law at API boundaries: the backend silently drops a field (`extra="ignore"`), the frontend silently renders `undefined`, and nobody notices until a stakeholder asks "why is this blank?"

---

## When to Use CDC vs. Other Patterns

| Pattern | Best For |
|---------|----------|
| Consumer-Driven Contracts | Frontend ↔ Backend in same team/repo |
| Provider Contracts (Pact) | Microservices across teams |
| Schema Registry (Avro/Protobuf) | Event streaming (Kafka, EventBridge) |
| OpenAPI / Swagger | Public APIs with external consumers |

For most internal dashboards and applications, Consumer-Driven Contracts with golden sample tests is the right level of formality.
