---
name: schema-migration
context: fork
description: Migrate an application's data access layer from one database schema to another. Use when tables are renamed, consolidated, split, or columns change — and the app's queries, mappings, and abstraction layer must be updated without data loss. Read-only against the database.
---

# Schema Migration Skill

Systematically migrate an application from a legacy database schema to a new schema with zero data loss and full functional parity.

## When to Use

- Tables are being renamed, consolidated, or split
- Columns are renamed, retyped, or moved between tables
- The DB team has restructured tables and the app must follow
- Data previously in file storage has been migrated into database tables
- Query files, column mappings, or config need updating after a schema change
- User says "migrate to new tables", "schema changed", or "tables restructured"

---

## Constraints (Read Before Starting)

1. **Read-Only** — Never execute DDL or DML (`CREATE`, `ALTER`, `INSERT`, `UPDATE`, `DELETE`) against the database. All analysis is SELECT-only.
2. **No SQL Aliases** — Proposed queries must use direct `Table.Column` notation. Aliases obscure the mapping and make future changes harder to trace.
3. **No Assumptions** — Every column mapping must be verified against the actual schema DDL. If a mapping is ambiguous or a source column has no clear target, flag it as a **GAP** rather than guessing.
4. **Scratchpad Protocol** — If context becomes large, save intermediate findings to `.github/plans/temp_migration_scratchpad.md` to preserve state across reasoning steps.

---

## Phase 1: Schema Forensics

### Objective
Build a complete picture of old and new schemas. Produce the **Schema Manifest** — the single source of truth for the migration.

### Actions

1. **Collect Legacy Schema DDL**
   - Extract `CREATE TABLE` statements for all legacy tables (from schema files, INFORMATION_SCHEMA, or DDL scripts)
   - Note all columns, data types, nullability, defaults, and foreign keys
   - Document the table-to-variable mapping (e.g., `.env` entries, config files)

2. **Collect Target Schema DDL**
   - Extract `CREATE TABLE` statements for all new/consolidated tables
   - Note structural differences: merged tables, renamed columns, new columns, removed columns, type changes

3. **Audit the Abstraction Layer**
   - Read the app's current mapping files (e.g., `column_mappings.yaml`, `.env`, config modules)
   - Read the current query files (e.g., `queries.yaml`, `.sql` files)
   - Identify every table and column the app references

4. **Produce the Mapping Manifest**

```markdown
## Schema Mapping Manifest

### Table Mapping
| Legacy Table | Target Table | Notes |
|-------------|-------------|-------|
| OldTableA   | NewTable1   | Merged with OldTableB |

### Column Mapping
| Legacy Table | Legacy Column | Type | Target Table | Target Column | Type | Transform |
|-------------|--------------|------|-------------|--------------|------|-----------|
| OldTableA   | user_name    | NVARCHAR(100) | NewTable1 | UserFullName | NVARCHAR(200) | Direct |
| OldTableA   | status_code  | INT  | NewTable1 | Status | VARCHAR(20) | Map: 1='Active', 2='Inactive' |

### Gaps (Unmapped)
| Source | Column | Issue |
|--------|--------|-------|
| OldTableC | legacy_flag | No equivalent in target schema |
| File: results/*.json | summary_json | Verify if present in CallTranscript table |
```

**Output**: Schema Mapping Manifest (table in the migration report)

---

## Phase 2: Query Translation

### Objective
Rewrite every application query against the new schema. No aliases — direct `Table.Column` references only.

### Actions

1. **Inventory Current Queries**
   - List every query from query files, repository classes, and inline SQL
   - Tag each query with its page/feature (e.g., homepage, search, analytics)

2. **Translate Each Query**
   - Apply the column mapping from Phase 1
   - Rewrite JOINs to reflect the new table structure
   - Handle type conversions inline (e.g., `CAST`, `CASE WHEN`) where the new schema uses a different data type

3. **Document Translation**

```markdown
### Query: [query_name]

**Old Query:**
```sql
SELECT col_a, col_b FROM OldTable WHERE col_c = ?
```

**New Query:**
```sql
SELECT NewTable.ColA, NewTable.ColB FROM NewTable WHERE NewTable.ColC = ?
```

**Changes:**
- `OldTable` → `NewTable`
- `col_a` → `ColA` (renamed)
- No type changes
```

4. **File Architecture Decision** (if applicable)
   - If the app uses a monolithic query file, evaluate splitting into per-page/per-feature files
   - Compare `.yaml` vs `.sql` for query storage:

| Format | Pros | Cons |
|--------|------|------|
| `.yaml` | Structured metadata (tags, descriptions), easy Python parsing | No SQL syntax highlighting, IDE support limited |
| `.sql` | Full IDE support, syntax checking, execution in DB tools | Needs a loader; metadata requires naming conventions or comments |

   - Recommend based on the project's existing patterns and tooling

**Output**: Translated Query Library + File Architecture Recommendation

---

## Phase 3: Parity Testing

### Objective
Prove that the new queries return the same data as the old queries. Evidence-based — not theoretical.

### Actions

1. **Run Old Queries** — Execute each legacy query and capture:
   - Row count
   - Column names and types
   - Sample rows (5–10 representative rows)
   - Aggregates where applicable (SUM, COUNT, DISTINCT)

2. **Run New Queries** — Execute each translated query against the new schema and capture the same metrics

3. **Compare Results**

```markdown
### Parity Report: [query_name]

| Metric | Old Query | New Query | Match |
|--------|-----------|-----------|-------|
| Row count | 1,247 | 1,247 | ✅ |
| Columns | 8 | 8 | ✅ |
| Sample hash | abc123 | abc123 | ✅ |

**Data Type Check:**
| Column | Old Type | New Type | Compatible |
|--------|---------|---------|------------|
| created_at | DATETIME | DATETIMEOFFSET | ⚠️ App must handle offset |
```

4. **Flag Discrepancies**
   - Row count mismatch → possible fan-out from JOINs or missing WHERE filters
   - Type mismatch → document required CAST/conversion in the app layer
   - NULL differences → document new nullable columns or default changes
   - Missing data → flag as GAP with severity

**Output**: Parity Report per query (pass/fail with evidence)

---

## Phase 4: Abstraction Layer Update

### Objective
Update the application's configuration and mapping layer to reflect the new schema.

### Actions

1. **Update Column Mappings** — Produce the new version of `column_mappings.yaml` (or equivalent) reflecting target table/column names

2. **Update Environment Config** — Produce the new `.env` variable values (table names, schema names)

3. **Update Query Files** — Produce the new query file(s) using the translated queries from Phase 2

4. **Trace Application Code Impact**
   - Identify every file that reads from the mapping/config layer
   - List files that will need code changes (e.g., new column names in data models, display logic, filters)
   - Categorize impact: `no change needed` | `config-only change` | `code change required`

```markdown
### Impact Analysis

| File | Current Reference | Change Type | Details |
|------|------------------|-------------|---------|
| services/data_loader.py | OldTable via .env | Config-only | Update .env mapping |
| pages/home.py | col_a in display | Code change | Rename to ColA |
| models/complaint.py | OldTable.status_code (INT) | Code change | Now VARCHAR, update parsing |
```

**Output**: Updated config files + application impact matrix

---

## Phase 5: Migration Report

### Objective
Produce a single, comprehensive document suitable for use as an **Implementation Plan**. This document must be complete enough that a developer can execute the migration with zero ambiguity.

### Report Structure

```markdown
# Schema Migration Report

## Executive Summary
- Source: [N] legacy tables → Target: [M] consolidated tables
- Total queries migrated: [count]
- Parity status: [all pass / N failures]
- Gaps identified: [count]

## 1. Schema Mapping Manifest
[From Phase 1]

## 2. Translated Query Library
[From Phase 2, grouped by page/feature]

## 3. Parity Test Results
[From Phase 3, pass/fail per query with evidence]

## 4. Abstraction Layer Changes
[From Phase 4 — updated YAML, .env, config diffs]

## 5. Application Impact Matrix
[From Phase 4 — file-by-file change list]

## 6. File Architecture Recommendation
[From Phase 2 — split strategy and format decision]

## 7. Edge-Case Registry
[Every risk identified during analysis]

| # | Risk | Severity | Mitigation |
|---|------|----------|------------|
| 1 | DATETIME → DATETIMEOFFSET | Medium | Add .replace(tzinfo=None) in Python |
| 2 | Nullable column X now NOT NULL | High | Add default value in query |

## 8. Migration Execution Checklist
- [ ] Column mappings updated
- [ ] Environment config updated
- [ ] Query files updated and tested
- [ ] Application code changes identified and assigned
- [ ] All parity tests passing
- [ ] Edge cases mitigated
- [ ] Rollback plan documented
```

### Output Location
Place the final report at the path specified by the user (default: `.github/plans/backlog/migration_report.md`).

---

## Checklist

- [ ] Legacy schema DDL collected (all tables)
- [ ] Target schema DDL collected (all tables)
- [ ] Every legacy column mapped to target (or flagged as GAP)
- [ ] Every app query translated to new schema
- [ ] Parity tests executed (old vs new query results compared)
- [ ] No row count mismatches unexplained
- [ ] Data type changes documented with app-level mitigation
- [ ] Abstraction layer (mappings, config) updated
- [ ] Application code impact traced (file-by-file)
- [ ] Edge-case registry complete (no known risks undocumented)
- [ ] File architecture decision documented (split strategy, format)
- [ ] Report placed at specified output path
