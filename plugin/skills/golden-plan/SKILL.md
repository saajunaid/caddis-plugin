---
name: golden-plan
context: fork
description: "USE THIS SKILL whenever a user asks for a comprehensive implementation plan, a full-stack build plan, a UI+backend plan, or says 'create a plan for building X' where X spans multiple phases or systems. Also activate when the user says 'plan this project', 'I need a detailed plan', 'build plan', 'implementation plan', or attaches a mockup/wireframe and asks how to build it. Produces a zero-ambiguity, evidence-gated plan with self-contained per-phase prompts, exhaustive data binding tables, per-phase validation checklists, and a global quality gate. Evidence-gated: before writing phases, verify required artefacts (mockup, data sample, API contract, scaffold inventory); if any BLOCKER is missing, ask for it and wait before proceeding. Dual-mode: generic by default, junai-pipeline only when explicitly requested. Agent-agnostic - any agent with read/search/edit tools can use this skill."
---

# Golden Plan

> **`/caddis:feature-plan` is the canonical planning entry point.** It writes to `.caddis/plans/`,
> which is what `/caddis:implement`, `/caddis:handoff`, `/caddis:digress` and `/caddis:resume`
> actually read, and it now carries this skill's evidence gate. Reach for golden-plan when you
> specifically need its heavier apparatus — the data-binding tables, the query catalog, the
> self-sweep. For ordinary multi-phase work, feature-plan is the shorter path to the same place.

## When to Use

Activate this skill when the request is for a **comprehensive implementation plan** that involves:

- 8 or more phases across a project
- Full-stack work (backend + frontend or data + UI)
- Complex data binding between a backend and a UI (JSON -> React, API -> Streamlit, etc.)
- A visual reference (HTML mockup, Figma, screenshot) that must be matched pixel-for-pixel
- Multiple agents executing different phases in sequence

Do NOT use for:
- Simple bug fixes or single-file changes (use `large-task-fidelity.instructions.md` alone)
- Exploratory plans with vague scope (use `brainstorming/SKILL.md` first to harden scope)
- Plans that only touch one system in isolation with no data binding (use `docs/writing-plans/SKILL.md`)

---

## Execution Mode (Required first step)

Before Phase 0, explicitly choose an execution mode:

- **Mode A - `generic` (default):** no junai pipeline assumptions, no orchestrator routing requirements, works with default Copilot/default agents.
- **Mode B - `junai-pipeline` (opt-in):** include orchestrator/stage-routing conventions and pipeline artefact conventions.

If the user does not explicitly request junai pipeline, use `generic`.

**Document metadata:** Every plan, status tracker, and other descriptive Markdown artefact created by this skill must follow `.github/instructions/document-frontmatter.instructions.md`. The YAML frontmatter block must be the first content in the file. New documents require `Original Author` (the human owner of the plan, not an inferred name — ASK if unknown, never guess), `Creation Date`, `Creating Model`, and `Executing Coding Agent` (the agent + model + persona that will run the plan, e.g. "Copilot coding agent (model Opus 4.8, persona @architect)"); updated documents must preserve those fields and add or update `Last Author`, `Last Updated`, and `Last Model Used`.

---

## Phase 0 - Evidence Gathering (REQUIRED before writing any plan content)

Before writing a single phase, you MUST gather and validate evidence. Do not produce plan output while any BLOCKER evidence item is unresolved.

Run through the checklist below. For each item, determine its tier:

- **BLOCKER** - Plan cannot proceed without this. Stop and ask the user for it.
- **WARNING** - Plan can proceed but the affected phases will have noted assumptions. Inform the user what you are assuming.
- **OPTIONAL** - Nice to have. Note its absence but proceed.

**Free head-start (workspace scan):** if `.caddis/PROJECT-FACTS.md` exists (setup-project-ai extracts it), read it first — it pre-fills E4 (scaffold inventory) plus the run/test/build commands, env-var names, and CI/deploy workflows at zero token cost. Also use it to ground risks rather than guess them: no test setup → regression risk; no CI workflow → local-only gate; auth/migration in scope → security/structural risk.

### Evidence Checklist

#### E1 - Visual Reference
- Does a mockup, wireframe, HTML prototype, or screenshot of the target UI exist?
- If yes: what file/path? Is it frozen (will not change during implementation)?
- **Tier:** BLOCKER for UI-heavy plans. WARNING for backend-only plans.

#### E2 - Live Data Sample
- Is there a real data sample (JSON file, CSV, DB query result) representative of production data?
- Does it reflect the CURRENT schema (not a stale sample)?
- Can field names be read directly from it (avoid field name guessing)?
- **Tier:** BLOCKER for plans with any data binding. WARNING if schema is defined elsewhere (Pydantic DTOs, TypeScript interfaces).

#### E3 - API / Backend Contract
- Are endpoints already defined (routes, method, request params, response shape)?
- Do typed DTOs exist (Pydantic models, TypeScript interfaces)?
- Is the serialization convention documented (camelCase vs snake_case)?
- **Tier:** BLOCKER for full-stack plans. WARNING if backend and frontend are built in the same plan (contract will be defined during planning itself - mark those sections clearly as `[DEFINED IN THIS PLAN]`).

#### E4 - Existing Scaffold Inventory
- What is already built? (List files, packages, installed dependencies.)
- What must NOT be recreated or deleted?
- What needs overhauling vs net-new creation?
- **Tier:** BLOCKER. Without this, the plan will generate conflicting or duplicate code.

#### E5 - Technology Decisions
- Is the tech stack finalised? (Charts library, state management, routing, test runner, animation, etc.)
- Are any decisions still open?
- **Tier:** BLOCKER for phases that depend on the decision. Open decisions must be flagged as `[TECH-DECISION OPEN]` in affected phases.

#### E6 - Scope Boundary
- What is explicitly in v1 vs deferred to a future release?
- Are any data fields known to be empty/missing in v1 (dispatch issues, schema gaps, etc.)?
- **Tier:** WARNING. Missing scope boundary causes unbounded implementations.

#### E7 - Agent / Skill Availability
- Which agents will execute phases? (Or default: `@Implement` for code phases, `@Tester` for test phases.)
- Which model should execute each phase? Add one explicit model recommendation per phase; do not leave this implicit.
- Are the domain skills referenced in phase prompts present on disk? (Verify paths before listing.)
- Which coding-agent HARNESS executes each phase? Distinguish: (a) **Copilot coding agent** — loads custom `.github/agents/*.agent.md` personas + auto-loads skills; pick this when the phase needs your toolset. (b) **Claude coding agent** / **Codex agent** — run their own loop, do NOT load custom personas; pick only for pure-execution phases, and point them at skill FILES by path. Note the model under the chosen harness (Copilot can run Opus/Sonnet/GPT; Claude agent runs Anthropic models; Codex runs GPT models).
- The `Original Author` (human) must be confirmed, not inferred from any name appearing in source documents or commit history. If the owner is unknown, ASK before writing frontmatter.
- **Tier:** OPTIONAL. Skill paths that do not exist should be omitted from phase prompts - do not list phantom skills.

#### E8 - Output Destination
- Where should the plan file be saved? (Default: `.caddis/plans/<feature-slug>.md`)
- Where should the associated tracker be saved? (Default: `.caddis/plans/tracker/<feature-slug>-tracker.md`)
- Is there a `chain_id` to use? (Format: `FEAT-YYYY-MMDD-{slug}`)
- **Tier:** OPTIONAL. Default path is used if not specified.

#### E9 - Phase Model Selection
- Every phase MUST include `**Agent:**`, `**Objective:**`, then `**Model:**` in that exact order.
- Every phase MUST include a `**Model:**` line immediately after `**Objective:**`.
- Recommend the best model for the phase, not the cheapest model by default.
- Use premium reasoning/coding models for foundation contracts, backend/API work, SQL/data lineage, performance-sensitive work, broad integration, and final verification.
- Use design-capable frontend models for visual systems, dashboards, animation, responsive layout, and premium UX phases.
- Use lower-cost models only for low-risk documentation, tracker, inventory, route metadata, or repetitive cleanup phases, and only when source-grounding plus validation keeps quality intact.
- Include a one-line rationale explaining the quality/risk tradeoff.
- Valid example recommendations include `GPT-5.4`, `GPT-5.3-Codex`, `Claude Sonnet 4.6`, and `GPT-5.4-Mini`; adapt to the user's available model list when they provide one.
- In the caddis harness, a phase's model may be served by an OSS execution lane: `glm-headless` (`claude-glm -p "/caddis:implement <plan> — Phase N only"`) for mechanical fully-specced phases, with cross-vendor review by a vendor that did NOT implement (`oss_review.py --provider deepseek|glm`). When lanes are used, the plan MUST carry an Execution Protocol section: per-phase handoff, fresh-session boundaries, and a never-push-main ship gate (`/ship-pr` then human go).

---

### Evidence Gate Decision

After running the checklist:

1. **All BLOCKERs satisfied** -> Proceed to Phase 1 (Pre-flight Scan).
2. **Any BLOCKER missing** -> Load `.github/skills/workflow/asking-questions/SKILL.md` and follow its question structure (numbered questions, multiple-choice options, fast-path `defaults` reply). Do not generate any plan content yet. Example:

   ```
   EVIDENCE GATE - BLOCKED

   Before I can write this plan, I need a few things. Reply with answers
   or `defaults` to accept my assumptions.

   1) Live data sample (E2):
      a) [path/to/sample.json] - I'll read it directly
      b) Point me to the Pydantic DTO / TypeScript interface file instead
      c) Not available yet - assume from field names in the mockup

   2) Existing scaffold location (E4):
      a) [path/to/frontend/] - I'll inventory it
      b) Not built yet - plan will be greenfield
      c) Not sure - use default (greenfield)

   Once these are answered I will produce the full plan.
   ```

3. **WARNINGs present** -> Proceed, but note each WARNING at the top of Context & Decisions with a `WARNING: ASSUMPTION:` callout.

---

## Phase 1 - Pre-flight Scan

Before writing any phase content, produce a **pre-flight summary** in this exact format:

```
## Pre-Flight Scan

Phase 0  - Context & Decisions:              reference section, depends on none
Phase 1  - [Name]:                           ~N tasks, depends on [phases or "none"]
Phase 2  - [Name]:                           ~N tasks, depends on [phases]
...
Phase N  - [Name]:                           ~N tasks, depends on [phases]
```

Commit to an expected task count per phase. Do not start writing phase content until this is complete. The pre-flight is your contract with yourself - use it to enforce equal depth across phases.

**Dependency sequencing rule:** Phases MUST be listed in execution order — all dependencies of phase N must appear before phase N. No forward dependencies. If phase 3 requires output from phase 4, restructure the order before writing any phase content. The `depends on` column is not decorative; it must reflect real execution constraints. If two phases have no dependency relationship, list the one with higher risk or longer duration first.

---

## Phase 2 - Plan Construction

Write the plan to the output file using the template below, section-by-section in order. Keep each section complete before moving to the next.

Generate the plan file and its execution tracker in the same run. A golden-plan output is incomplete if either file is missing.

---

### Plan Template

````
---
Original Author: <active author or agent name>
Creation Date: <YYYY-MM-DDTHH:MM:SSZ>
Creating Model: <exact runtime model identifier or display name>
---

# Plan: [Project Name] - [Sub-title e.g. "React UI Build" or "Backend API + Data Pipeline"]

> **Updated:** YYYY-MM-DDTHH:MM:SSZ
> **Status:** READY FOR EXECUTION
> **Execution mode:** `generic` <!-- or `junai-pipeline` -->
> **Visual reference:** [path to mockup or "N/A"]
> **Data source:** [path to canonical data sample or "See E3 - API Contract section"]
> **Output destination:** [path where plan is saved]
> **Execution tracker:** `.caddis/plans/tracker/<feature-slug>-tracker.md`
> **Execution:** Manual - one agent session per phase. See protocol below.

---

## Pre-Flight Scan

[Paste output from Phase 1 - Pre-flight Scan here]

---

## Manual Execution Protocol

Each phase runs in a **separate chat session**. After each phase, return for
validation before starting the next.

- In **`generic` mode**, use normal chat + selected agent(s) directly.
- In **`junai-pipeline` mode**, follow orchestrator routing and stage sequencing.

**Per-phase workflow:**
1. Open a new chat session with the agent named in the phase header
2. Load the skills listed under **Skills to load** - tell the agent:
   "Read these SKILL.md files before starting: [paths]"
3. Attach the files listed under **Files to attach**
4. Also attach this plan file and the associated execution tracker
5. Paste the **Phase Prompt** exactly as written - it is self-contained
6. When the agent finishes, validate the phase implementation by running every item in the **Validation Checklist**
7. After validation passes, create the phase implementation commit with the phase-scoped commit message
8. Capture the phase implementation commit hash with `git rev-parse HEAD`
9. Update the associated execution tracker row as complete with status, gate, validation evidence, changed files, commit hash, push state, and useful comments
10. Commit the tracker update or amend it into the phase commit according to the repository commit policy
11. Do not consider the phase complete until Step 10 is finished and the tracker row reflects the validated commit hash and comments
12. Return to advisory chat, share checklist results + errors. Get a green light before proceeding

**Drift rule:** If a bug or gap is found after Phase N, fix it in the same session before
starting Phase N+1. Never carry debt forward.

**Large-task fidelity:** Agents implementing large phases must follow
`.github/instructions/large-task-fidelity.instructions.md`.

**Tracker rule:** A phase is not complete until implementation is validated, the phase implementation commit exists, and the associated execution tracker row is marked complete with that commit hash. The row must record status, gate, validation evidence, changed files, commit hash, push state, and comments. Comments should capture useful implementation notes, unresolved follow-ups, known limitations, or handoff context that does not belong in code.

---

## 0. Context & Decisions

### What this plan builds
[2-4 sentences - what the user will have when all phases are complete]

### WARNING Assumptions
[List any E-tier WARNINGs from evidence gathering here. If none, write "None - all evidence verified."]

### Technology decisions

| Concern | Decision | Rationale |
|---------|----------|-----------|
| [e.g. Charts library] | [decision] | [one-line reason] |
| ... | ... | ... |

### Data parity assumptions

List every data domain and its v1 availability:

| Domain / Tab | Data availability | Strategy |
|---|---|---|
| [e.g. Executive Overview] | Available real data | Live API |
| [e.g. Geography] | Partially available; array is always `[]` in v1 | Live API + empty state with explanation |
| [e.g. Modem platform] | Unavailable; 0% populated | Full empty state (do not build chart) |

### Existing scaffold (do NOT recreate)

| Path | Purpose | Status |
|------|---------|--------|
| [path] | [what it is] | [keep / overhaul / extend] |

### Files to modify (not create)

| File | What changes | Risk of regression |
|------|-------------|-------------------|
| [path] | [description of change] | [low / medium / high - and why] |

### API contract

Only include if the backend exists or is being defined in this plan:

| Endpoint | Method | Params | Response type | Notes |
|----------|--------|--------|---------------|-------|
| `/api/v1/[resource]` | GET | `period: string` | `[TypeName]` | [serialization notes, e.g. camelCase] |
| ... | ... | ... | ... | ... |

---

[Then repeat the following block for EACH PHASE]

## Phase N - [Name]

**Agent:** `@[AgentName]`
**Objective:** [One sentence - what this phase produces. No implementation detail here.]
**Model:** `[GPT-5.4 | GPT-5.3-Codex | Claude Sonnet 4.6 | GPT-5.4-Mini | other available model]` - [one-line rationale that explains why this model is sufficient for the phase without compromising implementation quality]

### Skills to load

Tell the agent to read these SKILL.md files before starting:
[Only list skills whose paths you have VERIFIED exist on disk]
- `.github/skills/[category]/[name]/SKILL.md` - [one-line description]

### Instructions to follow

- `.github/instructions/[name].instructions.md`

### Files to attach

[All files the agent needs as context to execute this phase]
- `[path]`

### Phase Prompt

[SELF-CONTAINED, COPY-PASTE PROMPT - includes all context needed to execute the phase
without reading any other document. Structure:]

**Fence rule:** Every generated `### Phase Prompt` must be wrapped in a bare fenced code block. The opening fence must be exactly three backticks with no language label. Do not use labelled fences such as `text`, `markdown`, `bash`, or any other language for phase prompts.

```
You are implementing Phase N ([Name]) of the [project name].
Read `[plan file path]` Phase N section in full before making any changes.

PRINCIPLES: [TDD / KISS / YAGNI / DRY / Readability - adjust per phase]

SKILLS TO READ FIRST (load these SKILL.md files):
- [paths]

INSTRUCTIONS TO FOLLOW:
- [paths]

[CRITICAL context the agent needs to NOT make common mistakes - e.g.
"The API already returns camelCase. Do NOT add a key transformation layer."
"client.ts already exists - do NOT recreate it."
"types/nps.ts has all interfaces - import from there, do not re-declare."]

Deliverables (in order):
1. [Specific deliverable - file path + what it exports]
2. [Specific deliverable]
...

When done, run every item in the Validation Checklist and report each result explicitly.
Do not mark done unless all items pass. If any fail, fix and re-verify.

After all items pass:
1. Create the phase implementation commit: `git add -A && git commit -m "phase(N): [Name] complete"`.
2. Capture the phase implementation commit hash with `git rev-parse HEAD`.
3. Update the associated execution tracker declared in the plan header: `.caddis/plans/tracker/<feature-slug>-tracker.md`.
4. Mark Phase N complete in the tracker row with status, gate, completed date, executor/model, changed files, validation evidence, commit hash, push state, and comments.
5. Commit the tracker update or amend it into the phase commit according to the repository's commit policy.
6. Do not consider the phase complete until the tracker row is updated after validation and commit, and the row includes the commit hash and comments.
```

### What to build

[For EACH deliverable: write the complete spec with full code/config/values.
NO "similar to above". NO "same as Phase N". NO "...". EVERY deliverable fully spelled out.]

#### N.1 [Deliverable name]

**File:** `[exact path]`

[Full interface/type definitions, implementation spec, code where exact values matter.
If the code is the spec - write the code. Do not describe code, write it.]

#### N.2 [Deliverable name]
[...]

### Validation Checklist - Phase N complete when

[SPECIFIC, VERIFIABLE assertions - not "does it work?" but exact checks:]
- [ ] `npm run build` succeeds (or `python -m pytest` depending on stack)
- [ ] [Specific file] exists and exports [specific symbol]
- [ ] [Specific behavior] renders/returns [specific value]
- [ ] [Known empty state] returns graceful message, no crash
- [ ] Dark mode: [specific component] renders correctly
- [ ] Zero [hardcoded colors / any types / console.log / etc.]
- [ ] Phase implementation is validated, committed, `git rev-parse HEAD` was captured, and the associated execution tracker row is marked complete with status, gate, changed files, validation evidence, commit hash, push state, and useful comments.

### Phase Gate - run after all checklist items pass

```bash
# 1. Commit validated phase implementation
git add -A
git commit -m "phase(N): [Name] complete"

# 2. Capture phase implementation commit hash
git rev-parse HEAD

# 3. Update tracker
#    Use .caddis/plans/tracker/<feature-slug>-tracker.md and mark Phase N complete with:
#    status, gate, completed date, executor/model, changed files,
#    validation evidence, commit hash, push state, and comments.
```

---

[After all phases, include these three mandatory reference sections:]

## Data Binding Reference

Maps every UI component to its exact data source path. All implementing agents must
consult this before wiring any component to data.

### DB-[SECTION] - [Section Name e.g. "App Shell", "Tab 1 - Overview"]

| UI Element / Component | Data path | Type | Notes |
|-----------------------|-----------|------|-------|
| [component] | `[json.field.path]` | `type` | [e.g. camelCase, derived, always [] in v1] |

[Repeat DB-[SECTION] for each logical section / tab / page]

---

## Query Catalog

Every DB-backed UI field must trace to a specific executable SQL query.
This section is the authoritative reference for data analysis - it answers
"what query fetches what for the UI?"

Include one block per repository function. Queries must use **named bind parameters**
(`:param`), be schema-qualified (`{schema}.TableName`, default `dbo`), and include an
`OFFSET+FETCH` or `TOP N` bound - never unbounded.

```sql
-- [EntityName] - [repository_module].[function_name]
-- UI fields populated: fieldA, fieldB, embeddedStatus, derivedFromBlob
-- Parameters: :filter_val (optional), :offset (int), :page_size (int)
SELECT
    t.column_a         AS field_a,
    t.column_b         AS field_b,
    t.payload_col      AS payload_col   -- NVARCHAR(MAX): parsed by [adapter_name]
FROM {schema}.[SourceTable] AS t
WHERE (:filter_val IS NULL OR t.filter_col = :filter_val)
ORDER BY t.created_at DESC
OFFSET :offset ROWS FETCH NEXT :page_size ROWS ONLY;
```

**Derived fields from `payload_col` (extracted by normalizer - not in SQL):**

| UI field | Payload path / section | Adapter |
|---|---|---|
| `embeddedStatus` | NULL check on `payload_col` | n/a |
| `derivedField1` | `payload_col -> json_key` | `embedded_json_adapter` |
| `derivedField2` | `payload_col -> ## Section Header` | `embedded_markdown_adapter` |

[Repeat one block per repository function - single-row lookups, filters, aggregates, etc.]

---

## Derived Values Reference

Values computed client-side. NOT present in the raw data. All implementing agents must
derive these - never fetch them as separate API calls.

| Value name | Formula | Used by |
|-----------|---------|---------|
| [e.g. MoM delta] | `currentValue - previousValue` | [component list] |
| [e.g. YTD avg] | `mean(all non-null values in series)` | [component list] |

---

## Quality Gates

Every component across all phases must pass these gates before the plan is considered done:

- [ ] Zero hardcoded colours - always CSS variable tokens or named constants
- [ ] Zero hardcoded data inside components - all data flows from props or hooks
- [ ] TypeScript strict mode - no `any` type anywhere (or Python typing - no untyped params)
- [ ] All empty states render without errors when arrays are `[]` or data is `null`
- [ ] Dark mode: all components render correctly (if applicable)
- [ ] No `console.log` statements in production code
- [ ] No unused imports
- [ ] `npm run build` (or equivalent) produces zero warnings
- [ ] All tests pass
[Add project-specific gate items here]
````

---

## Phase 3 - Self-Sweep (Mandatory Final Step)

After completing the plan document, re-read the **last 40% of the output** before delivering it.

Search for these decay signals:

| Pattern | Example |
|---------|---------|
| `\.{3,}` (ellipsis) | `// ... same for other tabs` |
| `same pattern` | `same pattern as Phase 2` |
| `as above` | `as above for remaining endpoints` |
| `\betc\b\.?` | `deriveYtd, deriveMoM, etc.` |
| `{ ?\.\.\. ?}` | `expect(result).toBe({ ... })` |
| `similar to (Phase|Step|Section)` | `similar to Phase 4` |
| `and \d+ more|and others` | `and 3 more endpoints` |
| `repeat for|do the same for` | `repeat for remaining products` |

**If any match is found:** Expand it in-place - write the full content that was compressed.
**Do not deliver the plan until zero decay signals remain in the last 40%.**

---

## Mid-Plan Insertion Protocol

When a new phase must be inserted into an **existing plan** (discovered mid-project):

1. **Do NOT renumber** existing phases - renumbering breaks agent prompts that reference phase numbers.
2. **Use a suffix** for inserted phases: Phase 9 -> Phase 9A, then 9B if another is added later.
3. **Update the Pre-flight Scan** at the top to include the new phase.
4. **Add a `## Phase 9A` block** with the full structure (Prompt, What to build, Validation Checklist).
5. **Update the Output Destination header** to reflect the new `Updated:` date and status.
6. **Do NOT modify completed phase sections** - treat them as immutable history.
7. **Update frontmatter metadata** - preserve the original fields and add or update `Last Author`, `Last Updated`, and `Last Model Used`.

---

## Output Destination

Every generated plan MUST have an associated execution tracker. Put the tracker path in the plan header as `> **Execution tracker:** .caddis/plans/tracker/<feature-slug>-tracker.md`.

Golden-plan must create both files together. Never emit the plan without creating its associated tracker in the same run.

Save the completed plan to:

- `.caddis/plans/<feature-slug>.md` - default for both modes
- **Not ready to execute?** It is not a plan yet — file it as one future-work item at
  `.caddis/parking-lot/<feature-slug>.md` (`type: parking-lot`, `status: open`), or run
  `/caddis:park`. `.caddis/plans/backlog/` is retired: a second backlog location meant no session
  could answer "what is left to do?" without knowing both.

If mode is **`junai-pipeline`**, additionally register the artefact in `.github/agent-docs/ARTIFACTS.md` with `status: current`.

When revising an existing plan file, preserve `Original Author`, `Creation Date`, and `Creating Model`, then add or update `Last Author`, `Last Updated`, and `Last Model Used`. Use full ISO 8601 UTC timestamps for the date fields.

### Plan Status Tracker

Alongside the plan file, **always** create `.caddis/plans/tracker/<feature-slug>-tracker.md` using
this template (one row per phase, populated from the Pre-Flight Scan). The plan header must reference this exact tracker path:

```
---
Original Author: <active author or agent name>
Creation Date: <YYYY-MM-DDTHH:MM:SSZ>
Creating Model: <exact runtime model identifier or display name>
---

# Plan Status - [Project Name]

> Plan: `.caddis/plans/<feature-slug>.md`
> Tracker: `.caddis/plans/tracker/<feature-slug>-tracker.md`
> Started: YYYY-MM-DDTHH:MM:SSZ
> Last updated: YYYY-MM-DDTHH:MM:SSZ

| Phase | Name | Agent | Model | Status | Gate | Completed | Changed files | Validation evidence | Commit | Push | Comments |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | Context & Decisions | - | - | Complete | passed | YYYY-MM-DDTHH:MM:SSZ | `.caddis/plans/<feature-slug>.md` | Evidence gate complete | - | not_required | Plan authored |
| 1 | [Name] | @[Agent] | [model] | Pending | not_run | - | | | | unknown | |
| 2 | [Name] | @[Agent] | [model] | Pending | not_run | - | | | | unknown | |
| N | [Name] | @[Agent] | [model] | Pending | not_run | - | | | | unknown | |

## Status key
- Pending - not started
- In Progress - agent session open
- Complete - gate passed, committed
- Blocked - gate failed, needs fix
- Skipped - explicitly deferred
```

**Gate rule:** The executing agent validates the phase, creates the phase implementation commit, captures that commit hash, then marks the tracker row complete with the hash and comments. Never mark a phase complete before all validation checklist items pass and the phase implementation commit exists.

**Comments rule:** The `Comments` column is required for completed, blocked, or skipped phases. Use it for concise handoff notes, blockers, decisions, caveats, known limitations, or follow-up context discovered during the phase.

**Plan Completion Protocol:** When every tracker row has `status: Complete`, the plan is done. The executing agent (or the Janitor backstop) MUST:
1. Filesystem-move the plan file from `.caddis/plans/<feature-slug>.md` to `.caddis/plans/done/<feature-slug>.md` using `Move-Item`/`mv`/`run_command` — NOT `git mv` (the `done/` folder is gitignored in project repos).
2. Update the plan frontmatter: set `status: done` and add `Archived: <YYYY-MM-DD>`.
3. Log the move in the tracker `Comments` field of the last completed phase row.
4. Never delete plan files — only move to `done/`.

**Next step after saving:** Load `.github/skills/workflow/preflight/SKILL.md` and run it against the completed plan before any agent begins implementation. Preflight catches wrong endpoints, stale type names, missing dependencies, and field name mismatches that slipped past plan authorship - far cheaper to fix in the plan than mid-implementation.

---

## Relationship to Other Skills

| Skill | When to use instead |
|-------|-------------------|
| `docs/writing-plans/SKILL.md` | Smaller plans (< 8 phases), TDD micro-task granularity, single developer session |
| `workflow/brainstorming/SKILL.md` | Scope is still vague - use to harden requirements before this skill |
| `workflow/preflight/SKILL.md` | After the plan is written - validates it against the actual codebase before agents start |
| `large-task-fidelity.instructions.md` | Always apply in addition to this skill during plan OUTPUT - not a substitute |
