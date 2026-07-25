---
name: data-contract-pipeline
context: fork
description: "**WORKFLOW SKILL** - Build, audit, and validate data-to-UI contracts for apps. Use whenever the user mentions data mapping, UI lineage, DB-to-UI, DisplayDTOs, source-to-screen mapping, data contracts, schema drift, typed API responses, frontend type alignment, mockup grounding, requirements-to-UI mapping, or asks whether a UI is backed by real DB/file data. Works for DBs, JSON, Markdown, CSV, XLSX, YAML, APIs, and UI mockups."
---

# Data Contract Pipeline

Build a verified path from data sources to UI fields without leaking raw database or file structure into frontend components.

```
Requirements + UI demand decide what should be displayed.
DBs / files / APIs decide what can be displayed.
Ingestion model → normalizer → DisplayDTO defines the safe contract between them.
```

If your organization has a reference scaffold for this pattern, run its tests first to understand it
before applying the pipeline below.

---

## Decision tree — choose your flow before Stage 1

```
Do you have DB schema docs, ERDs, or an existing API spec?
│
├─ YES → documented_workflow.md  (Intake → Audit → Reconcile → Generate → Validate)
│
└─ NO  → discovery_workflow.md   (cold start — introspect DB first, then same 5 stages)

Are you only checking whether an existing UI is backed by data?
└─ YES → Run Stage 2 (Audit) only; produce gap_register in .contracts/
```

---

## Operating model

1. **Inspect first, ask second.** Read the repo, DB schema, mockups, and existing DTOs before asking the user anything.
2. **Max 3 questions at once.** Prefer concrete defaults: "I will use `config/.env.api.dev` unless you say otherwise."
3. **Never print secrets.** Log variable names, not values.
4. **Bounded queries only.** `TOP N` / `OFFSET+FETCH` on LIVE tables. Never unbounded `SELECT *`.

---

## Stage 1 — Intake

Collect or infer:
- App repo path.
- Source inputs: DB/table/view names, connection config, JSON/Markdown/CSV files, or schema docs.
- Consumer inputs: requirements docs, UI mockups, existing routes or component files.
- Mode: `build` | `audit` | `drift-check` | `lineage-only`.

Search `.env*`, settings modules, Docker Compose, and deployment manifests for DB config before asking.

---

## Stage 2 — Audit

Classify every source column against the D1–D12 drift catalogue.

**D1** No fields dropped from embedded JSON/markdown blobs.
**D2** Ingestion model has `extra="allow"` (future columns are captured, not rejected).
**D3** DisplayDTO has `extra="forbid"` (normalizer bugs surface immediately).
**D4** DisplayDTO uses camelCase field aliases (serialised output matches frontend expectations).
**D5** NULL semantics are preserved, not defaulted (NULL revenue ≠ $0).
**D6** Type coercion validated: string → Decimal, string → datetime, string → bool.
**D7** Normalizer produces correct status for each null/malformed/full payload variant.
**D8** Golden sample round-trip: raw_row → normalizer → model_dump(by_alias=True) matches expected.
**D9** Schema drift: live DB columns match ingestion model field list.
**D10** API → TypeScript: DisplayDTO aliases match generated TS interface keys.
**D11** PII columns classified and not exposed unintentionally via DisplayDTO.
**D12** Bounded query: repository enforces page_size ≤ MAX_PAGE, no unbounded SELECT.

For embedded payload columns (NVARCHAR(MAX) / TEXT):
- JSON blobs → `embedded_json_adapter` → embedded payload model (extra="allow" at every depth)
- Markdown blobs → `embedded_markdown_adapter` → sections + bold_kv dict
- CSV columns → `csv_column_adapter` (RFC 4180 quoted-comma aware)
- Free text with IDs → `embedded_text_adapter` → paren_ids + lines

Produce: annotated column list; flag null semantics, embedded type, and known sub-schema.

---

## Stage 3 — Reconcile

Map each source column to a DisplayDTO field. Assign one status per field:

| Status | Meaning |
|---|---|
| `contract-backed` | Source → normalizer → DisplayDTO → FE type tested end-to-end |
| `partially-backed` | Derives from nullable payload; may degrade to `blocked` at runtime |
| `blocked` | Mandatory source column always NULL in prod — cannot populate |
| `required-unplaced` | Frontend/requirements demand it; source not yet identified |
| `source-capability-only` | Source has it; no requirement or UI demand exists yet |
| `mockup-only` | In UI mockup only — no backend data path |
| `deferred` | Explicitly out of scope for current sprint |

Use the reconcile sub-prompt: `assets/prompts/reconcile_mapping.md`.

Output: `.contracts/feature.contract.json`.

---

## Stage 4 — Generate

Produce layers in this order:
1. Ingestion model (`extra="allow"`, raw payload columns as `str | None`)
2. Embedded payload model (each sub-model also `extra="allow"`)
3. Adapters (scalar, csv, json, markdown, text)
4. Normalizer (row → DisplayDTO, status classification logic)
5. DisplayDTO (`frozen=True`, `extra="forbid"`, camelCase aliases)
6. Repository (SQLAlchemy `text()` with named params, schema-qualified, bounded)
7. Service (orchestrate repo → ingestion model → normalizer)
8. FastAPI router (`response_model=` on every route, Query bounds with ge/le)
9. **Query catalog** — `.contracts/query_catalog.md` (see below)
10. Frontend types — regenerate from `/openapi.json` via `npx openapi-typescript`
11. Golden fixtures + D1–D12 contract tests

`_FLEX = ConfigDict(populate_by_name=True, extra="allow")` on ingestion models.
`_FROZEN = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)` on DisplayDTOs.

---

## Stage 5 — Validate

```bash
pytest tests/unit/ -v   # all D1-D12 checks must pass
```

For `mockup-only` or `required-unplaced` fields: generate `ui_gap_brief.md` and ask the
user to place, promote, or defer — do not silently add to a random screen.

CI rule: frozen contracts fail on unmapped DisplayDTO fields, DTO/type drift, and missing PII classification.

---

## Query Catalog

For every DB-backed UI field, produce `.contracts/query_catalog.md`.

This document must be **executable** — every SQL block should run as-is against the target DB (substitute
`{schema}` with the real schema name, e.g. `dbo`). Its purpose is to make explicit, during data analysis
or debugging, exactly which SQL query populates which UI element.

### Format

````markdown
# Query Catalog — {Feature Name}
# Generated: {date}
# Target: {DB server / environment}

---

## {EntityName} — {repository function name}

**UI fields populated:** `fieldA`, `fieldB`, `fieldC`
**Called by:** `{ServiceClass}.{method}` → `{NormalizerFunction}` → `{DisplayDTO}`
**Paging:** TOP {MAX_PAGE} / OFFSET+FETCH

```sql
-- Fetch {EntityName} rows, paged
-- Parameters: :customer_id (optional filter), :offset (int), :page_size (int)
SELECT
    t.column_a        AS field_a,
    t.column_b        AS field_b,
    t.payload_column  AS payload_column   -- NVARCHAR(MAX): parsed by embedded_json_adapter
FROM {schema}.TableName AS t
WHERE (:customer_id IS NULL OR t.customer_id = :customer_id)
ORDER BY t.created_at DESC
OFFSET :offset ROWS FETCH NEXT :page_size ROWS ONLY;
```

**Derived fields from payload_column (not in SQL — extracted by normalizer):**
| UI field | Source path | Adapter |
|---|---|---|
| `summaryStatus` | Derived from NULL check on `payload_column` | n/a |
| `keyIssueCount` | `payload_column → key_issues[].length` | `embedded_json_adapter` |
| `dashboardMetrics` | `payload_column → dashboard_metrics{}` | `embedded_json_adapter` |
````

### Rules

- One `##` section per repository function (one query per section).
- List every UI field the query feeds — both scalar columns AND fields derived from embedded payloads.
- For embedded payload columns, add the **Derived fields** table beneath the SQL block showing the JSON path, markdown section, or CSV token that maps to each UI field.
- Queries must use **named bind parameters** (`:param`), not f-string interpolation.
- Include the `OFFSET+FETCH` or `TOP N` bound in every query — never unbounded.
- If a query is schema-qualified, use `{schema}.TableName` with a comment showing the default (e.g. `-- default: dbo`).
- After generating, verify each query runs without error against the SQLite fixture: `python fixture/seed_sqlite_fixture.py && sqlite3 fixture/sample_source.db < .contracts/query_catalog_sqlite.sql`.

---

## Landmines

- **Secret leakage** — mask passwords and full connection strings
- **Unbounded queries** — no `SELECT *` on large LIVE tables; always bound
- **PII exposure** — classify MSISDN, email, customer IDs, names, account IDs before exposing
- **Mockup hallucination** — demo data constants are not a production contract
- **Null semantics** — distinguish zero / null / missing / unavailable / not-applicable
- **Metric ambiguity** — block until formula, grain, timezone, unit, and freshness are confirmed
- **Schema doc drift** — live schema wins over stale docs
- **MCP security** — every tool/resource needs auth, PII flag, rate limit, read/write scope
