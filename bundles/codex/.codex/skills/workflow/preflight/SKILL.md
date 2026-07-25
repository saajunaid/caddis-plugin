---
name: preflight
context: fork
description: "Plan-vs-codebase validation — verifies API contracts, type names, field accuracy, dependencies, and paths before implementation begins"
---

# Preflight — Plan Validation Skill

Validate an implementation plan against the actual codebase before agents begin coding. Catches wrong endpoints, missing types, incorrect field names, stale assumptions, and dependency gaps that would otherwise waste entire agent sessions.

## When to Use

- Before starting implementation of any plan (pipeline gate or standalone)
- After significant plan revisions to re-validate
- Mid-implementation to check remaining phases against evolved codebase
- When onboarding agents to an existing codebase with a pre-written plan

## Who Loads This Skill

| Consumer | Context |
|----------|---------|
| `@Preflight` agent | Primary — standalone or pipeline invocation |
| `@Orchestrator` | At the `plan_validated` gate before routing to Implement |
| `@Planner` | Optional self-check before declaring plan complete |
| Any agent | Ad-hoc validation when plan accuracy is in doubt |

---

## Inputs

The skill requires two things:

1. **Plan document** — a markdown file containing implementation phases with code snippets, file paths, type references, API endpoints, and data binding tables
2. **Codebase access** — read access to the project's source files, package manifests, and data samples

Optional:

3. **Scope restriction** — e.g., "validate only phases 6-13 while assuming phases 1-5 are already implemented" (for mid-implementation re-validation)
4. **Tech stack hint** — if the plan doesn't state the stack, the agent should detect it from the codebase (look for `package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `*.csproj`, etc.)

---

## Validation Methodology — 8 Check Categories (run in 3 passes)

To reduce execution load, run categories in this order: Pass 1 (1-3), Pass 2 (4-6), Pass 3 (7-8), recording findings after each pass before continuing.

Execute all 8 categories in order. Each produces findings classified as:

| Severity | Meaning | Action |
|----------|---------|--------|
| `CRITICAL` | Plan contradicts codebase — will cause runtime failure | Must fix before implementation |
| `SIGNIFICANT` | Plan partially wrong — will cause incorrect behavior | Should fix before implementation |
| `MINOR` | Cosmetic or documentation gap — won't break functionality | Fix if convenient |
| `WARN` | Cannot verify — source of truth missing or ambiguous | Flag for human decision |

### Category 1: API Contract Validation

**What:** Verify that every API endpoint referenced in the plan (URL, HTTP method, parameter style) matches an actual backend route.

**How:**

1. **Find route definitions** — Search for route decorators/registrations in the codebase:
   - Python/FastAPI: `@router.get`, `@router.post`, `@app.get`, etc.
   - Express/Node: `router.get(`, `app.post(`, etc.
   - Go: `r.HandleFunc(`, `e.GET(`, etc.
   - .NET: `[HttpGet(`, `[Route(`, `MapGet(`, etc.

2. **Extract plan endpoints** — Find every URL pattern in the plan (look for `/api/`, `GET `, `POST `, `fetch(`, `axios.get(`, service function definitions with URL strings).

3. **Compare:**
   - Does the URL exist in the backend? (exact match or parameterized equivalent)
   - Does the HTTP method match?
   - Are parameters passed correctly? (path params vs. query params vs. request body)
   - Is the response shape assumption correct?

4. **Common failure patterns:**
   - Plan uses path params (`/resource/{id}`) but backend uses query params (`/resource?id=X`)
   - Plan uses a convenience endpoint that doesn't exist (e.g., `/latest` when only `/list` exists)
   - Plan assumes REST resource endpoints but backend uses RPC-style endpoints

### Category 2: Type Identity Validation

**What:** Verify that every type/interface/class name referenced in the plan exists in the codebase.

**How:**

1. **Extract type references from the plan** — Find all capitalized type names used in:
   - TypeScript: `interface X`, `type X`, `: X`, `X[]`, `X | Y`
   - Python: class definitions, type hints, Pydantic models
   - Import statements referencing types

2. **Search the codebase** for each type name:
   - Check the exact file the plan says it's in (if specified)
   - If not found there, search broadly — the type may exist under a different name or path

3. **Common failure patterns:**
   - Plan references a type that was renamed during development
   - Plan references a type from an old version of a spec
   - Plan invents a plausible type name that was never created (e.g., `NpsPeriodData` when actual is `NpsData`)

### Category 3: Field Accuracy Validation

**What:** Verify that field names, casing, and nesting paths referenced in the plan match the actual data structures.

**How:**

1. **Extract field references from the plan** — Find data binding expressions:
   - Dot-notation paths: `data.surveys.broadband.topDetractorThemes`
   - Object destructuring: `const { themeName, currentNps } = item`
   - Table/chart data mappings: "bind X-axis to `fieldName`"

2. **Verify against source of truth** — Check each field reference against:
   - TypeScript interfaces/types (for frontend plans)
   - Pydantic models / SQLAlchemy models (for backend plans)
   - Actual JSON/API response samples (if available)
   - Database schema (if referenced)

3. **Check casing consistency:**
   - Does the plan assume camelCase but the source returns snake_case?
   - Does the plan instruct a blanket case transform, but the API already handles it via serialization aliases?
   - Are there mixed-case situations? (e.g., top-level fields are camelCase via aliases, but nested objects are snake_case)

4. **Common failure patterns:**
   - Plan says `topDetractorThemes` but actual field is `detractorThemes`
   - Plan says `currentNps` but actual is `currentNPS` (capitalization difference)
   - Plan says `target` and `minimum` but actual is `short_term` and `medium_term`
   - Plan instructs `transformKeys(snakeToCamel)` but API already returns camelCase — transform would double-convert

### Category 4: Dependency Availability Validation

**What:** Verify that every external package/library referenced in the plan is installed or listed in the project's dependency manifest.

**How:**

1. **Extract dependency references from the plan** — Find:
   - Import statements: `import X from 'Y'`, `from X import Y`
   - Package references: "install recharts", "add framer-motion"
   - Version-specific references: "requires React 18+"

2. **Check against manifests:**
   - `package.json` (dependencies + devDependencies) for JS/TS
   - `pyproject.toml` / `requirements.txt` for Python
   - `go.mod` for Go
   - `Cargo.toml` for Rust

3. **Classify:**
   - Listed in manifest → `PASS`
   - Not listed but plan says "install in Phase N" → `PASS` (with note)
   - Not listed and plan doesn't mention installation → `SIGNIFICANT` (will fail on import)

### Category 5: Path Existence Validation

**What:** Verify that every file/directory path referenced in the plan exists or is explicitly marked for creation.

**How:**

1. **Extract path references from the plan** — Find:
   - `CREATE file: src/components/Dashboard.tsx`
   - `UPDATE file: src/api/client.ts`
   - Import paths: `from '../services/nps'`
   - Config references: `tailwind.config.js`, `.env`

2. **Classify each path:**
   - `CREATE` + path doesn't exist → `PASS` (expected)
   - `CREATE` + path already exists → `WARN` (will overwrite — intentional?)
   - `UPDATE` + path exists → `PASS`
   - `UPDATE` + path doesn't exist → `CRITICAL` (can't update what doesn't exist)
   - Referenced in imports but neither CREATE nor UPDATE → check existence

3. **Verify directory structure matches plan assumptions:**
   - Does `src/components/ui/` exist if the plan puts files there?
   - Does the plan's assumed project structure match reality?

### Category 6: Data Shape Validation

**What:** Verify that the plan's assumptions about API response shapes (nesting, array vs. object, optional vs. required) match the actual response structure.

**How:**

1. **Find data shape assumptions in the plan** — Look for:
   - Response type annotations: `Promise<NpsData>`
   - Data access patterns: `response.data.surveys.broadband.nps`
   - Conditional checks: `if (data.periodType === 'monthly')`
   - Mapping operations: `data.themes.map(t => t.name)`

2. **Verify against the actual response:**
   - Read serialization models (Pydantic, Zod, JSON Schema)
   - If available, read sample response data (JSON files, test fixtures)
   - Check: Is the field always present or sometimes missing?
   - Check: Is it an array or an object? Does the plan treat it correctly?

3. **Common failure patterns:**
   - Plan assumes a field exists that is only present conditionally
   - Plan assumes an array but actual is an object (or vice versa)
   - Plan references `data.combined.trend` but combined has no trend data
   - Plan assumes a flattened structure but actual is nested

### Category 7: Transform Correctness Validation

**What:** Verify that any data transformation instructions in the plan (case conversion, normalization, derived calculations) are actually needed and correctly specified.

**How:**

1. **Find transform instructions in the plan** — Look for:
   - "Apply camelCase transform to API responses"
   - "Normalize snake_case fields"
   - "Calculate combined NPS as weighted average of products"
   - "Derive percentage from raw counts"

2. **Check if the transform is necessary:**
   - Does the API already apply the transform via serialization (Pydantic aliases, Jackson annotations)?
   - Does the ORM already handle the conversion?
   - Would the transform break other data that's already in the correct format?

3. **Check if the transform is correct:**
   - Is the formula right? (e.g., weighted average vs. simple average)
   - Are required source fields available?
   - Does the transform handle edge cases? (division by zero, null values)

### Category 8: Output Decay Detection

**What:** Detect structural shortcuts, abbreviation patterns, and placeholder content that indicate the plan-generating agent suffered output decay (attention fatigue in later sections).

**How:**

1. **Scan the plan for decay signals** — Search for these patterns, especially in the last 40% of the document:

   | Signal | Regex pattern | Example |
   |--------|--------------|---------|
   | Ellipsis placeholders | `\.{3,}` | `// ... similar tests for each function` |
   | Same-pattern shortcuts | `same pattern` | `same pattern × 3 rows` |
   | As-above references | `as above` | `as above for remaining endpoints` |
   | Etc. in task lines | `\betc\b\.?` | `deriveDeltas, deriveYtd, etc.` |
   | Pseudo-code bodies | `\{ ?\.\.\. ?\}` | `expect(result).toBe({ ... })` |
   | Phase cross-references | `similar to (Phase\|Step\|Section)` | `similar to Phase 2` |
   | Collapsed lists | `and \d+ more\|and others\|and the rest` | `and 3 more` |
   | Implied continuation | `repeat for\|do the same for` | `repeat for remaining products` |
   | Compressed enumerations | listing 2-3 items then trailing with `, ...` or `etc.` instead of the full list | `deriveDeltas, deriveYtd, etc.` (when there are 9 items) |

2. **Measure depth uniformity:**
   - Count task lines per phase across the entire plan
   - If the last 3 phases average < 50% of the first 3 phases' task-line count, flag as `SIGNIFICANT` depth decay
   - If any single phase has ≤ 2 task lines when comparable phases have 10+, flag as `CRITICAL` depth decay

3. **Check for incomplete examples:**
   - Does the plan show one fully specified example (e.g., for "Broadband") and then shortcut the remaining items (e.g., "Mobile", "TV", "Bundle")?
   - Are test bodies fully written or do they contain `{ ... }` pseudo-code?
   - Are ID/attribute lists complete or do they trail off with "etc."?

4. **Common failure patterns:**
   - Plan writes full component spec for first product, then says "same pattern × 3 rows" for the rest
   - Test descriptions list one test fully, then say "similar tests for each function"
   - Data binding tables show one row completely, then reference "id=X etc." for remaining
   - Lists that should enumerate all items (function names, field names, route paths) stop after 2-3 with ", etc."

5. **Classification:**
   - Any unexpanded shortcut that hides specific details (names, paths, logic) → `SIGNIFICANT` with type `MECHANICAL` (the full content must be written out)
   - Depth decay across phases → `SIGNIFICANT` with type `MECHANICAL` (later phases must be expanded to match earlier phases)
   - Ambiguous abbreviation where the intended expansion is unclear → `CRITICAL` with type `DECISION_REQUIRED`

---

## Execution Protocol

### Step 1: Plan Ingestion

Read the plan document end-to-end. Extract:
- Total number of phases
- Technology stack references
- All technical claims (endpoints, types, fields, paths, transforms)

### Step 2: Codebase Discovery

Identify the sources of truth in the codebase:
- Backend route files (for API contract)
- Type definition files (for type identity)
- Serialization/DTO models (for field accuracy and transforms)
- Package manifests (for dependencies)
- Sample data or test fixtures (for data shapes)

### Step 3: Systematic Cross-Reference

Run all 8 check categories against the plan. For each finding:
- Record the **plan location** (phase number, section, line context)
- Record the **codebase evidence** (file path, line number, actual value)
- Classify severity
- For `CRITICAL` and `SIGNIFICANT`: determine if this is a **mechanical fix** (one correct answer) or a **decision required** (multiple valid options)

### Step 4: Decision Surfacing

For findings classified as **decision required**:
- Present numbered options (A, B, C) with pros/cons
- Wait for user input (in standalone mode) or flag as blockers (in autopilot)
- Record the chosen resolution alongside the finding

### Step 5: Report Generation

Produce a structured report (see Output Format below).

---

## Output Format

The report is written to the path specified by the invoking agent. Default: `.github/agent-docs/preflight-report.md`

Apply `.github/instructions/document-frontmatter.instructions.md` when creating or updating the report. The YAML frontmatter block must be the first content in the file. New reports require `Original Author`, `Creation Date`, and `Creating Model`; revised reports must preserve those fields and add or update `Last Author`, `Last Updated`, and `Last Model Used`.

```markdown
---
type: preflight-report
plan: <path-to-plan-file>
scope: <"full" or "phases N-M">
timestamp: <ISO-8601>
result: <PASS | FAIL>
counts:
  critical: <N>
  significant: <N>
  minor: <N>
  warn: <N>
decisions_pending: <N>
Original Author: <active author or agent name>
Creation Date: <YYYY-MM-DDTHH:MM:SSZ>
Creating Model: <exact runtime model identifier or display name>
---

# Preflight Validation Report

**Plan:** `<path>`
**Validated against:** `<project-name>` codebase
**Scope:** <full | phases N-M>
**Result:** <PASS ✅ | FAIL ❌>

## Summary

| Category | Checks | Pass | Fail | Warn |
|----------|--------|------|------|------|
| API Contract | N | N | N | N |
| Type Identity | N | N | N | N |
| Field Accuracy | N | N | N | N |
| Dependencies | N | N | N | N |
| Path Existence | N | N | N | N |
| Data Shape | N | N | N | N |
| Transform Correctness | N | N | N | N |
| Output Decay | N | N | N | N |
| **Total** | **N** | **N** | **N** | **N** |

## Critical Findings

### C1: <title>
- **Category:** <which of the 8>
- **Plan says:** <what the plan claims> (Phase N, section X)
- **Codebase says:** <what actually exists> (`path/to/file:line`)
- **Type:** Mechanical fix
- **Fix:** <exact correction>

### C2: <title>
- **Category:** <which of the 8>
- **Plan says:** <what the plan claims>
- **Codebase says:** <what actually exists>
- **Type:** Decision required
- **Options:**
  - A: <option and consequence>
  - B: <option and consequence>
  - C: <option and consequence>
- **Resolution:** <PENDING | chosen option with rationale>

## Significant Findings
<same structure as critical>

## Minor Findings
<same structure>

## Warnings
<same structure>

## Decisions

| ID | Finding | Options | Resolution |
|----|---------|---------|------------|
| D1 | <finding ref> | A / B / C | <PENDING or chosen> |
| D2 | ... | ... | ... |
```

If you revise an existing report file, preserve the original metadata fields and add or update `Last Author`, `Last Updated`, and `Last Model Used` using full ISO 8601 UTC timestamps.

---

## Pass / Fail Criteria

| Result | Condition |
|--------|-----------|
| `PASS` | Zero CRITICAL findings AND zero pending decisions |
| `FAIL` | Any CRITICAL finding exists OR any decision is PENDING |

`SIGNIFICANT` and `MINOR` findings do not block a PASS — they are advisory. However, they should be included in the report for the Planner to address.

---

## Scope Restriction (Partial Validation)

When invoked with a scope like "validate phases 6-13 only":

1. Only extract technical claims from phases 6-13 of the plan
2. Validate against the **current** codebase (which includes work from phases 1-5)
3. Report findings only for the scoped phases
4. Note in the report header: `Scope: phases 6-13 (phases 1-5 assumed implemented)`

This is useful for mid-implementation re-validation where the codebase has evolved beyond what the plan originally assumed.

---

## Project-Agnostic Design

This skill does not assume any specific technology stack. The 7 check categories are universal — they apply to:

- Python + FastAPI + React (current validated use case)
- Node.js + Express + Vue/Angular
- Go + gRPC + React
- .NET + Blazor/React
- Any backend + any frontend combination

The agent loading this skill must adapt the "how to find routes" and "how to find types" steps to the actual stack detected in the project. The methodology (what to check and how to classify findings) is stack-agnostic.

---

## Anti-Patterns to Avoid

| Anti-Pattern | Why It's Wrong | Correct Approach |
|---|---|---|
| Validate only Phase 1 | Later phases have higher drift risk | Validate all phases with equal depth |
| Trust plan's stated types without searching | Types get renamed during development | Search codebase for each type name |
| Assume blanket transforms are correct | APIs often handle serialization already | Check serialization layer before recommending transforms |
| Skip data shape validation | "The types look right" ≠ "the data matches" | Read actual response samples or DTO definitions |
| Auto-resolve decisions | Product choices need human input | Surface options and wait |
| Report only failures | Context of what passed builds confidence | Include summary table with pass counts |
