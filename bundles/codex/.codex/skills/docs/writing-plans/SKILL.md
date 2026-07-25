---
name: writing-plans
context: fork
description: Use when you have a spec or requirements for a multi-step task, before touching code
---

# Writing Plans

## Overview

Write comprehensive implementation plans assuming the engineer has zero context for our codebase and questionable taste. Document everything they need to know: which files to touch for each task, code, testing, docs they might need to check, how to test it. Give them the whole plan as bite-sized tasks. DRY. YAGNI. TDD. Frequent commits.

Assume they are a skilled developer, but know almost nothing about our toolset or problem domain. Assume they don't know good test design very well.

**Announce at start:** "I'm using the writing-plans skill to create the implementation plan."

**Context:** This should be run in a dedicated worktree (created by brainstorming skill).

**Save plans to:** `docs/plans/YYYY-MM-DD-<feature-name>.md`

**Document metadata:** Before creating or updating a plan, apply `.github/instructions/document-frontmatter.instructions.md`. The YAML frontmatter block must be the first content in the file. New plans require `Original Author`, `Creation Date`, and `Creating Model`; revised plans must preserve those fields and add or update `Last Author`, `Last Updated`, and `Last Model Used`.

## Bite-Sized Task Granularity

**Each step is one action (2-5 minutes):**
- "Write the failing test" - step
- "Run it to make sure it fails" - step
- "Implement the minimal code to make the test pass" - step
- "Run the tests and make sure they pass" - step
- "Commit" - step

## Plan Document Header

**Every plan MUST start with this header (YAML frontmatter first, then title):**

```markdown
---
chain_id: <chain_id>
type: plan
status: current
approval: pending
Original Author: <active author or agent name>
Creation Date: <YYYY-MM-DDTHH:MM:SSZ>
Creating Model: <exact runtime model identifier or display name>
---

# [Feature Name] Implementation Plan

> **For the implementing agent:** Follow this plan task-by-task, executing each step sequentially.

**Goal:** [One sentence describing what this builds]

**Architecture:** [2-3 sentences about approach]

**Tech Stack:** [Key technologies/libraries]

---
```

> ⚠️ The YAML frontmatter block (`---` delimiters) is required for Orchestrator artefact contract validation. Do NOT use blockquote-style metadata (`> **approval:** pending`) — it will not be parsed.
> Preserve the original metadata fields on later edits, and add or update `Last Author`, `Last Updated`, and `Last Model Used` when the plan is revised. Use full ISO 8601 UTC timestamps for `Creation Date` and `Last Updated`.

## Task Structure

```markdown
### Task N: [Component Name]

**Files:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py:123-145`
- Test: `tests/exact/path/to/test.py`

**Step 1: Write the failing test**

```python
def test_specific_behavior():
    result = function(input)
    assert result == expected
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/path/test.py::test_name -v`
Expected: FAIL with "function not defined"

**Step 3: Write minimal implementation**

```python
def function(input):
    return expected
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/path/test.py::test_name -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/path/test.py src/path/file.py
git commit -m "feat: add specific feature"
```
```

## Manual Execution Protocol

**Every plan MUST include a Manual Execution Protocol section** at the top (after header, before phases). This tells the user exactly how to run each phase session:

```markdown
## Manual Execution Protocol

For each phase below, follow this workflow:

1. **Open** a new chat session with the agent specified in the phase header
2. **Load skills** listed in the phase's "Skills to load" section
3. **Attach files** listed in the phase's "Files to attach" section
4. **Paste** the self-contained Phase Prompt into the chat
5. **Validate** using the phase's Validation Checklist — every item must pass
6. **Get green light** before moving to the next phase

**Drift rule:** If you find bugs introduced by Phase N, fix them in the SAME session
before starting Phase N+1. Never carry implementation debt forward between phases.

**Dependency sequencing rule:** Write phases in execution order \u2014 every phase's dependencies must appear before that phase in the plan. If Phase 3 requires output from Phase 4, reorder before writing. No forward dependencies.
```

## Phase 0 — Context & Decisions

**Every multi-phase plan MUST include a Phase 0** before the implementation phases. Phase 0 is not an implementation phase — it is a ground-truth inventory that prevents agents from making assumptions.

Phase 0 contains four mandatory tables:

### Technology Decision Table

```markdown
### Technology Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Charting library | Recharts | Tree-shakeable, React-native, typed API |
| Animation | Framer Motion | AnimatePresence for tab transitions, spring physics |
| State management | Zustand | Lightweight, no boilerplate, devtools support |
| ... | ... | ... |
```

Every technology choice that is NOT already in `project-config.md` must appear here with a rationale.

### Data Parity / Availability Matrix

```markdown
### Data Availability

| Feature / Tab | Data Field | Available? | Strategy |
|---------------|-----------|------------|----------|
| Executive Overview | `ceoInsight` | ✅ Full | Live API |
| Product Deep-Dive | `satisfactionScores` | ❌ Empty `{}` | Show empty state: "Coming in future release" |
| Geography | `byGeography` | ⚠️ Partial (was present May-Oct) | Show empty state with explanation |
| ... | ... | ... | ... |
```

For any data field that may be empty, partial, or absent: document the exact empty state message text.

### Existing Scaffold Audit

```markdown
### Existing Scaffold — DO NOT Recreate

| File | Purpose | Current State |
|------|---------|---------------|
| `frontend/src/api/client.ts` | API client with JWT auth | ✅ Working — build on top |
| `frontend/src/types/nps.ts` | 30+ TypeScript interfaces | ✅ Working — import, don't recreate |
| `frontend/src/components/layout/AppShell.tsx` | App shell | ⚠️ Cold zinc theme — needs warm overhaul |
| ... | ... | ... |
```

The "Current State" column tells agents what exists and whether to modify or leave it alone.

### Dependency Split

```markdown
### Dependencies

**Already installed** (DO NOT reinstall):
- react, react-dom, typescript, vite
- @tanstack/react-query, @tanstack/react-router
- tailwindcss, zustand

**Not yet installed** (install in Phase 1):
- recharts, framer-motion, leaflet, react-leaflet
- d3-force, d3-scale
```

## Enhanced Per-Phase Template

**Every implementation phase MUST use this structure.** The sections OUTSIDE the prompt block are for the user (what to prepare before opening a session). The prompt block is for the agent (what to paste into the session).

```markdown
## Phase N — {Name}

**Agent:** `@{agent-name}`
**Objective:** {One sentence describing what this phase builds}

### Skills to load

- `.github/skills/{path}/SKILL.md` — {why}
- `.github/skills/{path}/SKILL.md` — {why}

### Instructions to follow

- `.github/instructions/{name}.instructions.md`
- `.github/instructions/{name}.instructions.md`

### Files to attach

- `path/to/file.ext` — {why this file is needed}
- `path/to/file.ext` (from Phase N-1)
- `.github/plans/{this-plan}.md` (this file)

### Phase Prompt

\`\`\`
{Self-contained prompt — copy-paste ready. 30-60 lines.
References plan sections for detail. Does NOT duplicate code blocks.
Includes PRINCIPLES, SKILLS TO READ, IMPORTANT warnings, and numbered deliverable list.}
\`\`\`

### What to build

#### N.1 {Deliverable Name}

**File:** `exact/path/to/file.ext`

{Component interface / function signature}

**Data binding:**
- Uses `data.field.path` for {purpose}
- Uses `data.other.field` for {purpose}

**Behavior:**
- {Specific interactive behavior}
- {Animation spec with exact values}

**Empty state:** When `data.field` is `{}` or `[]`:
> "{Exact message text to display}"

**IMPORTANT:** {Trap-specific warning — e.g., "DO NOT recreate api/client.ts",
"field uses snake_case in BOTH API and TS types — no transformation needed"}

#### N.2 {Next Deliverable}
...

### Validation Checklist — Phase N complete when

- [ ] `npm run build` succeeds (or equivalent build command)
- [ ] {Specific behavioral criterion — e.g., "KpiFlipCard flip animation works independently on each card"}
- [ ] {Data binding criterion — e.g., "NpsSummaryTable renders 5 rows with correct data from surveys + trend"}
- [ ] {Visual criterion — e.g., "Dark mode: all components render correctly with soft dark tokens"}
- [ ] {Integration criterion — e.g., "Row click switches to Tab 2 and scrolls to chart"}
- [ ] Zero hardcoded data — all from props/hooks
- [ ] Zero hardcoded colors — all from CSS vars or constants
```

### Key rules for the "What to build" subsections

1. **Data binding is mandatory for UI components.** Every component spec must list the exact JSON field paths it consumes (e.g., `surveys.{product}.nps`, `trend.historicalNPS.byProduct.{product}`). This eliminates the #1 implementer failure mode: guessing which field to bind.

2. **Empty state specs are mandatory.** For every data field that might be empty, specify the exact message text. Do NOT say "show appropriate empty state" — write the message.

3. **IMPORTANT warnings for traps.** If a file already exists and must NOT be recreated, say so. If a field uses unexpected casing (snake_case where camelCase is expected), warn explicitly. These prevent the most common implementation errors.

4. **Complete code blocks when the component is foundational.** For theme files, config files, utility functions, and CSS — include the full source code in the plan. For application components — specify interface, behavior, and data binding; let the agent write the implementation.

## Remember
- Exact file paths always
- Complete code in plan (not "add validation")
- Exact commands with expected output
- Reference relevant skills with @ syntax
- DRY, YAGNI, TDD, frequent commits
- **Every phase MUST end with a numbered exit gate task** (e.g., "Task N.X: Exit Gate") that includes pass/fail checks, commit message format, and an explicit "STOP — do not proceed to next phase" instruction
- **Every phase/step must specify the executing agent and include a ready-to-use prompt with `═══ PROMPT START` / `═══ PROMPT END` markers**
- **Use 4-backtick fences (`` ```` ``) for the outer prompt block** so nested code blocks render correctly
- **After writing all phases, run the Cross-Reference Audit against ALL source documents**
- **Every plan MUST include a Manual Execution Protocol and Phase 0 — Context & Decisions**
- **Every UI phase MUST include data binding specs (exact JSON paths) per component**
- **Every data field that might be empty MUST have an explicit empty state message**
- **Drift rule: fix bugs from Phase N before starting Phase N+1**

## Cross-Reference Audit

**Run this AFTER all phases are written, BEFORE finalizing the plan.**

Walk through every FR, NFR, risk, and design decision from ALL input documents. For each, verify it maps to a specific, actionable plan step. Output a traceability matrix:

```markdown
## Source Document Traceability

| Requirement | Source | Plan Phase/Step | Status |
|-------------|--------|-----------------|--------|
| FR-101 | PRD §3.1 | Phase 1, Step 2 | ✅ Covered |
| NFR-208 | PRD §4.2 | Phase 5, Step 1 | ✅ Covered |
| Risk-003 | Arch §9 | Phase 3, Step 3 | ✅ Covered |
| ALT-002 | Arch §7.4 | N/A | ⚠️ Out of Scope — rationale: deferred to v2 |
```

**Rules:**
- A requirement without a plan step → add a step or mark "Out of Scope" with rationale
- A cited section reference (§N) → verify the section number matches the actual document
- Zero-tolerance: no unmapped requirements in a finalized plan

## Agent & Prompt Assignment

**Every phase/step MUST include a ready-to-use prompt block.** This is non-negotiable because plans are executed across multiple sessions by different agents.

### Prompt Block Template

> **CRITICAL**: Use 4-backtick fences (` ```` `) for the outer prompt block so nested code blocks (yaml, python, etc.) inside the prompt render correctly. Add `═══ PROMPT START` and `═══ PROMPT END` markers so users can clearly see where to copy from/to.

```markdown
### Ready-to-Use Prompt (Phase N — Step M)

> **How to use:** Copy the prompt block below (between ═══ START and ═══ END markers) into a new chat session. **Include all code blocks** — they're context for the agent, not for you to apply manually.
> **Agent:** `@{agent-name}` (see `.github/agents/{agent-name}.agent.md`)
> **Skills to load:** `.github/skills/{skill-path}/SKILL.md`
> **Instructions (auto-applied):** `{instruction1}.instructions.md`, `{instruction2}.instructions.md`
> **Project config:** `.github/project-config.md` (profile: `{profile}`)

> ═══ PROMPT START — Copy everything between START and END into a new chat ═══

\`\`\`\`
{One-sentence task description}

**Agent context:** You are the `@{agent-name}` agent. Load `.github/project-config.md` before starting.

**Read these files FIRST (in order):**
1. `.github/plans/{plan-file}.md` — **THIS PLAN** — read "Phase N — Step M"
2. {Architecture/PRD doc} — {specific sections}
3. {Target file(s)} — current state

**What to do:**
- {Actionable instruction 1}
- {Actionable instruction 2}

**Acceptance criteria:**
- {Testable criterion 1}
- {Testable criterion 2}

**Scope boundary:**
- Exit gate: Task N.X (the last task in this phase)
- Do NOT proceed to Phase N+1 after the exit gate passes
- Do NOT offer additional work beyond the exit gate tasks
- Commit with: `feat({feature}): Phase N — {description}` and STOP
\`\`\`\`

> ═══ PROMPT END ═══════════════════════════════════════════════════════════
```

### Agent Selection Guide

| Task Type | Agent | Agent File |
|-----------|-------|------------|
| Models, services, logic | `@implement` | `implement.agent.md` |
| Streamlit UI, components | `@streamlit-developer` | `streamlit-developer.agent.md` |
| Tests, fixtures | `@tester` | `tester.agent.md` |
| SQL queries, schema | `@sql-expert` | `sql-expert.agent.md` |
| Docs, README | `@docs` | `docs.agent.md` |
| Code review | `@code-review` | `code-review.agent.md` |

## Execution Handoff

After saving the plan, offer execution choice:

**"Plan complete and saved to `.github/plans/<filename>.md`. Two execution options:**

**1. This session** — I implement each task sequentially, reviewing between tasks

**2. Separate session** — Open a new session with the `@implement` agent and provide the plan path

**Which approach?"**

**If separate session chosen:**
- Guide them to open new session
- Reference the `@implement` agent (`.github/agents/implement.agent.md`)
- Provide the plan file path for the implementing agent to read
