# Sub-prompt: Reconcile Mapping

Use this prompt to map source columns → normalizer transforms → DisplayDTO fields.
Provide the source column list and requirements list, then run this prompt.

---

You are reconciling data source capabilities against product requirements and UI demand.

## Inputs

You will receive:
1. `SOURCE_COLUMNS` — columns from the ingestion model or DB schema
2. `REQUIREMENTS` — field requirements extracted from docs or tickets
3. `UI_DEMAND` — fields extracted from frontend components
4. `EXISTING_CONTRACT` — existing `.contracts/*.contract.json` (if any)

## Task

For each DisplayDTO field that should exist (derived from requirements + UI demand):

1. Find the best matching source column(s).
2. Determine what adapter and normalizer transform is needed.
3. Assign a status:

| Status | Assign when |
|---|---|
| `contract-backed` | Source column maps cleanly; transform is deterministic; test exists |
| `partially-backed` | Derives from nullable embedded payload; may degrade to blocked at runtime |
| `blocked` | Required column is always NULL in prod, or formula is undefined |
| `required-unplaced` | Frontend/requirements demand it; no source column found |
| `source-capability-only` | Source has it; no requirement or UI demand |
| `mockup-only` | In UI mockup only; no backend path |
| `deferred` | Explicitly out of scope |

4. Output one JSON entry per DisplayDTO field:

```json
{
  "field_key": "camelCase DTO key",
  "source_column": "column_name (or null if required-unplaced)",
  "adapter": "scalar | csv | embedded_json | embedded_markdown | embedded_text | none",
  "transform": "Description of normalizer logic (e.g. 'split CSV, preserve quoted commas')",
  "status": "contract-backed | partially-backed | ...",
  "null_handling": "What the normalizer returns when source is NULL",
  "type": "Python type annotation for DisplayDTO",
  "fe_type": "TypeScript type for frontend",
  "notes": "Any caveats, edge cases, or open questions"
}
```

## Output format

1. JSON array of mapping entries (one per DisplayDTO field).
2. `## Gaps` — fields that are `required-unplaced` or `blocked`, with recommended next action.
3. `## Orphans` — source columns that are `source-capability-only`, listed for product review.

---

SOURCE_COLUMNS:

REQUIREMENTS:

UI_DEMAND:

EXISTING_CONTRACT:
