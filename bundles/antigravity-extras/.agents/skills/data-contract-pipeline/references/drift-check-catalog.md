# Drift Check Catalog

Complete reference of contract drift types, detection methods, and fix patterns.

---

## Drift Types

### D1 — Payload Key Not in Ingestion Model

**What**: A key exists in the source payload but has no corresponding field in the ingestion model — at **any nesting depth**, not just top-level.

**Risk**: New data from the source is silently ignored. If the ingestion model uses `extra="ignore"`, this is invisible.

**Detection — flat (top-level only)**:
```python
payload_keys = set(payload.keys())
model_aliases = {
    info.alias or name for name, info in IngestionModel.model_fields.items()
}
uncovered = payload_keys - model_aliases
```

**Detection — recursive (recommended)**:
```python
from contract_test_helpers import _collect_dropped_keys

dropped = _collect_dropped_keys(payload, IngestionModel)
# Returns dot-path list: ["surveys.broadband.newField", "metadata.x"]
```

The recursive variant (`_collect_dropped_keys` in the contract-test template) walks nested dicts and lists-of-dicts, comparing keys against model field aliases at every depth. It also respects the `KNOWN_EXCLUDED_KEYS` allow-list (see D12).

**Fix**: Add the missing field to the ingestion model with the correct type.

---

### D2 — Ingestion Field Not in Display DTO

**What**: The ingestion model has a field that doesn't map to any display DTO field. The normalizer silently drops it.

**Risk**: Data is fetched and validated but never reaches the API consumer. If intentional, it should be documented.

**Detection — flat (top-level only)**:
```python
ingestion_fields = set(IngestionModel.model_fields.keys())
dto_fields = set(DisplayDTO.model_fields.keys())
dropped = ingestion_fields - dto_fields  # Approximate — normalizer may rename
```

**Detection — recursive (recommended)**:
```python
from contract_test_helpers import _collect_dropped_keys

dropped = _collect_dropped_keys(payload, DisplayDTO)
# Returns dot-path list at every nesting level
```

**Fix**: Either add the field to the display DTO, or add the key to `KNOWN_EXCLUDED_KEYS` (see D12) with a ticket reference explaining why it's excluded.

---

### D3 — Display DTO Uses `extra="ignore"`

**What**: The display DTO silently drops unknown fields during validation.

**Risk**: When the source adds new keys, they pass through ingestion but vanish at the DTO layer. This causes data loss bugs that are nearly impossible to debug because no error is raised.

**Detection**:
```python
config = DisplayDTO.model_config
assert config.get("extra") != "ignore", "Display DTO must not use extra='ignore'"
```

**Fix**: Change to `extra="forbid"` (strict) or `extra="allow"` (migration period).

---

### D4 — DTO Alias Mismatch with TypeScript

**What**: A DTO field alias (the camelCase name sent over the API) doesn't match the corresponding TypeScript interface property name.

**Risk**: Frontend receives the data but accesses it with the wrong key → `undefined` values, silent display bugs.

**Detection**:
```python
# Extract DTO aliases
dto_aliases = {
    info.alias or name for name, info in DisplayDTO.model_fields.items()
}

# Extract TypeScript property names (parse the .ts file)
ts_props = extract_ts_interface_properties("frontend/src/types/source.ts")

# Compare
missing_in_ts = dto_aliases - ts_props
extra_in_ts = ts_props - dto_aliases
```

**Fix**: Update the TypeScript interface to match DTO aliases exactly.

---

### D5 — DTO Type Mismatch with TypeScript

**What**: A DTO field type doesn't correspond to the TypeScript type.

**Risk**: Runtime type errors, NaN from treating strings as numbers, etc.

**Detection**: Compare using the type mapping table:

| Python | TypeScript |
|--------|-----------|
| `str` | `string` |
| `int`, `float` | `number` |
| `bool` | `boolean` |
| `list[T]` | `T[]` |
| `dict[str, T]` | `Record<string, T>` |
| `Optional[T]` | `T \| null` |

**Fix**: Update the TypeScript type to match.

---

### D6 — API Router Missing `response_model`

**What**: FastAPI endpoint doesn't specify `response_model=DtoName`.

**Risk**: FastAPI won't validate the response shape. If the service returns a dict with wrong keys, the API sends it as-is.

**Detection**:
```python
# Check router decorators
# @router.get("/", response_model=DtoName) ← must be present
```

**Fix**: Add `response_model=DtoName` to the endpoint decorator.

---

### D7 — Mapping Doc Stale

**What**: A data mapping document (e.g., `ui-json-data-mapping.md`) claims a UI element reads from `data.foo.bar`, but the code actually reads from `data.baz.qux`.

**Risk**: Document misleads developers, causes incorrect debugging assumptions.

**Detection**: Compare doc field paths against actual code references. This is a manual review item — scripts can't reliably parse prose mapping docs.

**Fix**: Regenerate the mapping doc from the contract tests and DTO definitions.

---

### D8 — Golden Sample Missing or Stale

**What**: No `tests/fixtures/payloads/source/sample.json` exists, or it's from an old schema version.

**Risk**: Contract tests run against outdated data, pass despite real drift.

**Detection**:
```python
sample_path = Path("tests/fixtures/payloads/source/sample.json")
assert sample_path.exists(), "Golden sample missing"

# Optionally check freshness
payload = json.loads(sample_path.read_text())
# Compare key count against actual source
```

**Fix**: Copy a real payload from the source, sanitize PII, save as golden sample.

---

### D9 — Frontend Service Return Type Wrong

**What**: The frontend service function's return type doesn't match the TypeScript interface.

**Risk**: TypeScript compiler may not catch it if the return type is `any` or a superset.

**Detection**:
```typescript
// Check that the service function's return type matches the interface
export async function getData(): Promise<CorrectType> { ... }
//                                       ^^^^^^^^^^^^ must match
```

**Fix**: Update the return type annotation.

---

### D10 — Normalizer Produces Wrong Shape

**What**: The normalizer function's output doesn't match the display DTO fields.

**Risk**: Runtime `ValidationError` when the DTO tries to validate the normalizer output.

**Detection**: Unit test — pass a valid ingestion model through the normalizer and validate the result against the DTO.

**Fix**: Update the normalizer to produce all required DTO fields.

---

### D11 — Drift Test Mode Mismatch

**What**: The drift test uses hard assertions (`assert dropped == []`) while the upstream schema is still evolving, OR uses soft warnings (`warnings.warn`) after the schema has been frozen.

**Risk**:
- Hard asserts during evolution: CI breaks on every upstream change → drift tests get skipped or deleted.
- Soft warnings after freeze: Regressions slip through because CI never fails.

**Detection**:
```python
# Check freeze resolution precedence in the contract test file:
# 1) CONTRACT_SCHEMA_FROZEN env var
# 2) _contract_state.json marker
# 3) CI fallback (CI=true + sample exists)
import os
schema_frozen = resolve_schema_frozen()

# If the upstream schema is frozen, SCHEMA_FROZEN should be True
# If the upstream schema is still evolving, SCHEMA_FROZEN should be False
```

**Modes**:

| Schema state | `SCHEMA_FROZEN` | Drift detection behaviour |
|---|---|---|
| Evolving daily | `False` | `warnings.warn()` — CI passes, drift is visible in test output |
| Stabilised / frozen | `True` | `assert` — CI blocks, any untyped key is a failure |

**Fix**: Prefer explicit CI override (`CONTRACT_SCHEMA_FROZEN=1`) once the upstream schema is stable. If explicit env is missing, maintain `_contract_state.json` (`{"schema_frozen": true}`) to avoid ambiguous mode selection.

---

### D12 — Missing Exclusion Allow-List Entry

**What**: A JSON key is intentionally NOT typed in the DTO (deprecated, experimental, frontend-only metadata) but has no entry in `KNOWN_EXCLUDED_KEYS`, so it triggers noisy drift warnings.

**Risk**: Drift reports become cluttered with known intentional gaps. Teams learn to ignore warnings, defeating the purpose of drift detection.

**Detection**:
```python
from fnmatch import fnmatch

# KNOWN_EXCLUDED_KEYS uses dot-path globs (fnmatch syntax)
KNOWN_EXCLUDED_KEYS: dict[str, set[str]] = {
    "root.section.*": {"experimental_field"},  # TICKET-123
}

# A key is excluded if its full dot-path matches a pattern AND
# the leaf key name is in the exclusion set for that pattern.
is_excluded = any(
    fnmatch(full_path, pattern) and key in excl
    for pattern, excl in KNOWN_EXCLUDED_KEYS.items()
)
```

**Rules**:
- Every entry MUST have a ticket reference or justification comment
- Review the list periodically — remove entries once the key is typed or removed upstream
- Use dot-path + fnmatch globs: `"surveys.*"` matches `surveys.broadband`, `surveys.mobile`, etc.
- If a key appears in many paths, use a broad glob; if it's specific, use the exact path

**Fix**: Add the intentionally excluded key to `KNOWN_EXCLUDED_KEYS` in the contract test file with a justification.

---

## Drift Check Execution Order

Run checks in this order for the most useful output:

1. **D8** — Golden sample exists?
2. **D1** — Payload keys covered by ingestion model? (recursive)
3. **D3** — DTO `extra` config safe?
4. **D2** — Ingestion fields mapped to DTO? (recursive)
5. **D10** — Normalizer produces valid DTO?
6. **D11** — Schema frozen flag matches upstream state?
7. **D12** — Exclusion allow-list entries all have justifications?
8. **D4** — DTO aliases match TypeScript?
9. **D5** — DTO types match TypeScript?
10. **D6** — Router has `response_model`?
11. **D9** — Frontend service return type correct?
12. **D7** — Mapping doc current?

---

## Drift Report Format

When reporting drift, use this format:

```markdown
## Drift Report — {{source_name}}

| Check | Status | Details |
|-------|--------|---------|
| D1 — Payload Coverage | ✅ PASS | 42/42 keys covered |
| D2 — DTO Coverage | ❌ FAIL | `byPlay` in ingestion, not in DTO |
| D3 — DTO Extra Config | ✅ PASS | `extra="forbid"` |
| D4 — TS Alias Match | ❌ FAIL | DTO alias `npsDeltas`, TS has `nps_deltas` |
| ... | ... | ... |

### Fixes Required

1. **D2 — `byPlay` not in DTO**: Add `by_play: dict = Field(alias="byPlay")` to `NpsMonthlyResponse`
2. **D4 — `npsDeltas` alias**: Rename TS property from `nps_deltas` to `npsDeltas`
```
