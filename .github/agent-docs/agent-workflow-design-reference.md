# Agent Workflow Design Reference

> _Formerly `plans/fix-ai-resources-pool.md` — promoted to permanent reference after plan completion._

> **Status**: COMPLETE (living reference — session updates appended)
> **Original Branch**: `fix/juno-ux-polish-v2`
> **Created**: 2026-02-18
> **Plan Completed**: 2026-02-19
> **Last Updated**: 2026-02-20 (Advisory Hub session updates)
> **Goal**: Make the entire `.github/` AI resources pool portable, generic, and properly wired for automated multi-agent workflows with intent preservation and artifact lifecycle management.

---

## Context & Decisions (READ THIS FIRST)

### Background

The `.github/` folder contains 22 agents, 40+ skills, 22 instructions, and 25 prompts. Currently, most files have VMIE/a customer-data app/ServeSight-specific values hardcoded (brand colors, table names, paths, API names). The goal is to make this pool fully portable — copy `.github/` to any project, run the onboard skill, and everything works.

### Key Decisions (confirmed by user)

1. **Portable package**: All paths relative, all values generic with `<PLACEHOLDER>` tokens resolved via `project-config.md`
2. **`copilot-instructions.md`**: NOT part of the portable package. Generated per-project via onboard skill. The existing one for a customer-data app is kept as-is (battle-tested).
3. **`project-config.md`**: Part of portable package as a template. Filled in per-project (or via onboard skill).
4. **`skills/vmie/` folder**: DELETE entirely. Promote unique skills to generic categories with placeholder tokens. Remove the profile-based skill fallback system (all skills become generic).
5. **`agent-docs/` folder**: New folder for inter-agent artifacts (not `docs/`). Agents write structured output here with lifecycle metadata (current/superseded/archived).
6. **Every agent gets 7 universal protocols** (see Universal Agent Protocols section below).
7. **Planner agent**: Move agent/prompt block to TOP of each phase (before implementation details).
8. **`360Customer-newchat.prompt.md`**: DELETE (100% project-specific, duplicates `copilot-instructions.md`).
9. **Onboard skill behavior**: Idempotent — create `copilot-instructions.md` if missing, merge/append if exists. NEVER overwrite or degrade existing content.
10. **Current project**: We ARE inside a customer-data app's `.github/`. After fixing the portable pool, update `project-config.md` in-place (no need to run onboard skill for this project).

### The Streamlit Chat Widget Disaster (Reference Pattern)

A user asked the `ui-ux-designer` critic agent to create a chat widget mockup for Streamlit. The agent produced beautiful HTML but never warned that Streamlit's DOM wrapping breaks `position: fixed/absolute`. 24 hours wasted. Root causes: no scope boundary in agent, no framework feasibility check, no handoff routing. This applies to ANY framework — agents must warn about feasibility constraints, not just produce output blindly.

### Automated Agentic Workflow Pipeline

The target workflow for the portable pool:

```
User input (freetext / idea / backlog item)
    │
    ├── Vague input ──► Prompt Engineer ──► Intent Document
    │                                            │
    ├── Clear requirements ──────────────────────┤
    │                                            │
    │                                     ┌──────┴──────┐
    │                                     │   GATE 1    │ User approves Intent
    │                                     └──────┬──────┘
    │                                            │
    │                                     PRD Agent ──► agent-docs/prd/
    │                                            │
    │                                     ┌──────┴──────┐
    │                                     │   GATE 2    │ User approves PRD
    │                                     └──────┬──────┘
    │                                            │
    │                                     Architect ──► agent-docs/architecture/
    │                                       │ consults: UX Designer, Security, etc.
    │                                       │ (specialists write to agent-docs/)
    │                                     ┌──┴──────────┐
    │                                     │   GATE 3    │ User approves Architecture
    │                                     └──────┬──────┘
    │                                            │
    │                                     Planner agent ──► .github/plans/
    │                                            │
    │                                     ┌──────┴──────┐
    │                                     │   GATE 4    │ User approves Plan
    │                                     └──────┬──────┘
    │                                            │
    │                                     Implementation Agents
    │                                     (follow plan phases)
    │                                            │
    │                                     Code Reviewer (chain audit)
    │                                            │
    │                                          Done
```

**Gates are mandatory checkpoints**. User can skip gates on trusted flows, but agents MUST wait if upstream artifact is `approval: pending`.

### Intent Document System

**Problem it solves**: Intent, goals, and specifics get lost when passing from one agent to another (lossy chain — experienced during the Streamlit disaster).

**Solution**: Every feature chain starts with an **Intent Document** — a short, immutable artifact that captures original intent. Every agent in the chain reads it FIRST, before any other artifacts. Each agent cross-references its work against Intent Document constraints and flags drift.

**Intent Document structure**:
```markdown
---
agent: prompt-engineer    # or "user" if written directly
created: 2026-02-18
status: current           # current | completed | amended
type: intent
chain_id: FEAT-2026-0218-chat-widget
---
# Intent: {Feature Title}

## Goal
{What the user wants to achieve}

## Success Criteria
- {Testable criterion}

## Constraints
- {Technical/business constraints}

## Out of Scope
- {What this is NOT}

## Original User Input
> {Verbatim user input preserved — no agent can claim they didn't know}
```

**Intent amendments** (when requirements change mid-pipeline):
- Intent Document itself is NEVER edited (historical record)
- Create an Intent Amendment file linking to the original via `chain_id`
- All downstream artifacts produced BEFORE the amendment get marked `superseded`
- Pipeline re-runs from earliest affected point

**`chain_id`**: Unique identifier linking ALL artifacts in a feature chain. Every agent carries it through. Format: `FEAT-YYYY-MMDD-{slug}`

### Inter-Agent Artifact Protocol

Every agent that produces decision-making output writes a structured artifact to `agent-docs/`:

```
agent-docs/
├── ARTIFACTS.md            # Manifest — single source of truth
├── .archive/               # Janitor moves stale items here (30+ days old)
├── intents/                # Intent Documents + amendments
├── escalations/            # Agent-to-agent escalations
├── prd/                    # PRD agent
├── architecture/           # Architect agent
├── ux/                     # UX Designer
│   ├── mockups/
│   └── reviews/
├── security/               # Security Analyst
├── reviews/                # Code Reviewer
├── debug/                  # Debug agent
└── testing/                # Tester (coverage analysis)
```

**Artifact YAML header** (required for all artifacts):
```yaml
---
agent: {agent-name}
created: {date}
updated: {date}
status: current | superseded | archived | completed
superseded_by: {path or null}
approval: pending | approved | revision-requested
chain_id: {FEAT-xxx}
plan_ref: {path to plan or null}
---
<!-- AGENT-GENERATED: Created by AI agent for inter-agent communication.
     Do NOT include in project documentation without human review. -->
```

**Lifecycle rules:**
- Producing agent marks old artifact `superseded` when creating replacement
- All agents: check manifest FIRST, only read `current` artifacts
- Janitor agent: moves `superseded`/`archived` items older than 30 days to `.archive/`
- Documentation skills: NEVER read from `agent-docs/` — this is agent working space, not project docs

### Escalation Protocol

Any agent can create an escalation when they find a problem with an upstream artifact:

```markdown
---
type: escalation
chain_id: {same chain_id}
from_agent: {this agent}
to_agent: {upstream agent}
severity: blocking | warning
---
## Issue
{What the problem is}

## Suggested Resolution
{How to fix it}

## Impact
{What's blocked}
```

Written to `agent-docs/escalations/`. Escalation pauses the chain — target agent must respond before work continues.

**Conflict resolution priority hierarchy:**
1. Intent Document constraints (highest — user's stated requirements)
2. Security constraints (override architecture preferences)
3. Architecture decisions (override implementation preferences)
4. Implementation details (lowest priority)

### Universal Agent Protocols (added to ALL 22 agents)

Every agent gets these 7 protocols:

**1. Scope Boundary / "Not My Job"**
```markdown
Before accepting any task, verify it falls within your responsibilities.
If outside scope: state clearly, identify correct agent, do NOT attempt partial work.
Framework/Technology Feasibility: verify solutions are feasible in project's tech stack.
WARN about known limitations before proceeding.
```

**2. Artifact Output Protocol**
```markdown
Write decision-making output to agent-docs/{your-category}/.
Include YAML header with status, chain_id, approval fields.
Update agent-docs/ARTIFACTS.md manifest after creating/superseding artifacts.
```

**3. Chain-of-Origin (Intent Preservation)**
```markdown
Read the Intent Document FIRST — before any other agent's output.
Cross-reference your work against Intent Document Goal + Constraints.
If your output would diverge from original intent, STOP and flag drift.
Carry the same chain_id in all artifacts you produce.
```

**4. Approval Gate Awareness**
```markdown
Before starting: check if upstream artifact has approval: approved.
If upstream is pending or revision-requested, do NOT proceed.
After completing: set your artifact to approval: pending for user review.
```

**5. Escalation Protocol**
```markdown
If you find a problem with an upstream artifact: write escalation to agent-docs/escalations/.
Do NOT silently work around upstream problems.
```

**6. Bootstrap Check**
```markdown
First action: read project-config.md.
If profile is blank AND placeholder values are empty → tell user to run onboarding skill first.
```

**7. Context Priority Order (mandatory reading order)**
```markdown
1. Intent Document          ← original intent (MUST READ)
2. Plan (your phase/step)   ← what to do RIGHT NOW (MUST READ)
3. project-config.md        ← project constraints (MUST READ)
4. Previous agent's artifact ← what's been decided (SHOULD READ)
5. Your skills/instructions  ← how to do it (SHOULD READ)
6. Full PRD / Architecture   ← full context (IF ROOM)
```

---

## Phase 1 — Foundation (New Files)

> **Agent**: `@implement`
> **Estimated tasks**: 6 files to create
> **Dependencies**: None — this phase can start immediately

### Step 1.1 — Create onboard-project skill

- [ ] Create `skills/workflow/onboard-project/SKILL.md`
- **Purpose**: Entry point for the portable pool. When run on a new project, it:
  1. Asks the user about their project (tech stack, DB, branding, deploy env, etc.)
  2. Creates `copilot-instructions.md` from a template if it doesn't exist, or merges missing sections into existing file
  3. Updates `project-config.md` placeholders with user's answers
  4. Creates `agent-docs/ARTIFACTS.md` manifest if missing
- **Behavior**: Idempotent. Safe to re-run. NEVER overwrites or degrades existing content.
  - File exists → read it, compare sections vs. template, append ONLY missing sections with `<!-- Added by onboard-project -->` marker
  - File doesn't exist → create from template, populate from user Q&A
  - Conflict resolution → keep user's existing content (it's more battle-tested)
- **Template sections for `copilot-instructions.md`**: Project overview, Architecture, Tech stack, Data sources, Key patterns/conventions, DB access patterns, Deployment, Key commands

### Step 1.2 — Create mockup skill

- [ ] Create `skills/frontend/mockup/SKILL.md`
- **Purpose**: Framework-aware mockup creation. Born from the chat widget disaster.
- **Key features**:
  - Reads `project-config.md` for framework (Streamlit, React, etc.)
  - Framework feasibility check BEFORE creating mockup
  - If framework has constraints (e.g., Streamlit DOM wrapping), WARN and suggest alternatives
  - Output: HTML/SVG mockup file written to `agent-docs/ux/mockups/`
  - Updates `agent-docs/ARTIFACTS.md` manifest
  - Includes artifact YAML header with chain_id, status, approval fields

### Step 1.3 — Create agent-docs manifest and folder structure

- [ ] Create `agent-docs/ARTIFACTS.md` (template with header, usage instructions, empty table)
- [ ] Include instructions for agents: "Only read `current` artifacts. Ignore `superseded` and `archived`."
- [ ] Document the `chain_id` system and approval gates

### Step 1.4 — Create onboarding prompt

- [ ] Create `prompts/onboarding.prompt.md` with frontmatter — triggers the onboard-project skill

### Step 1.5 — Create intent-writer skill

- [ ] Create `skills/workflow/intent-writer/SKILL.md`
- **Purpose**: Structures freetext/ideas/backlog items into Intent Documents
- **Key features**:
  - Takes any input (freetext, idea, backlog reference, detailed requirements)
  - Structures into Intent Document format (Goal, Success Criteria, Constraints, Out of Scope, Original User Input)
  - Does framework feasibility pre-check against `project-config.md`
  - Generates unique `chain_id` (format: `FEAT-YYYY-MMDD-{slug}`)
  - Writes to `agent-docs/intents/`
  - Updates manifest
  - Supports intent amendments (links to original via `chain_id`, marks downstream artifacts superseded)

### Step 1.6 — Create new-feature prompt

- [ ] Create `prompts/new-feature.prompt.md`
- **Purpose**: Entry point for the automated pipeline. User runs this to start a new feature.
- **Behavior**: Asks user if they want Prompt Engineer to refine input (for vague ideas) or go directly to PRD (for clear requirements)

---

## Phase 2 — Fix All Agents (22 files)

> **Agent**: `@implement`
> **Estimated tasks**: 22 agent files to update
> **Dependencies**: Phase 1 must be complete (agents reference skill paths and agent-docs structure created in Phase 1)

### Universal changes (apply to ALL 22 agents)

Add all 7 Universal Agent Protocols (see Context section above):
- [ ] **Scope Boundary / "Not My Job"** — refuse out-of-scope work, identify correct agent, framework feasibility check
- [ ] **Artifact Output Protocol** — where this agent writes artifacts, YAML header format, manifest update
- [ ] **Chain-of-Origin** — read Intent Document FIRST, cross-reference against Goal + Constraints, carry `chain_id`, flag drift
- [ ] **Approval Gate Awareness** — check upstream `approval` status before starting, set own artifact to `pending`
- [ ] **Escalation Protocol** — write to `agent-docs/escalations/` when finding upstream problems, don't silently work around issues
- [ ] **Bootstrap Check** — first action: read `project-config.md`, if blank profile + empty values → tell user to run onboarding
- [ ] **Context Priority Order** — mandatory reading order: Intent Doc → Plan (your phase) → project-config → previous artifact → skills/instructions → full PRD/Architecture (if room)
- [ ] Replace any hardcoded `skills/vmie/` paths with generic paths + `project-config.md` note
- [ ] Replace any `docs/prd/`, `docs/architecture/` artifact paths with `agent-docs/prd/`, `agent-docs/architecture/`
- [ ] Ensure all agents reference `project-config.md` for project values (not hardcoded)

### Model audit (apply during agent edits)

Review and update the `model:` field in every agent's frontmatter for best fit.

**Model tier philosophy** (add as comment in each frontmatter or in project-config.md):
- **Tier 1 — Deep reasoning** (Claude Opus 4.6): Architecture, planning, security, design critique, code review, PRD, debugging — needs strong analytical and cross-referencing capability
- **Tier 2 — Coding** (GPT-5.3-Codex): Implementation, testing, SQL, frontend, data engineering — needs fast, accurate code generation
- **Tier 3 — Balanced** (Claude Sonnet 4.6): Ops, accessibility, project management, mentoring, cleanup — good at reasoning and execution, cost-efficient

**Specific model changes to apply:**

| Agent | Current | New | Reason |
|-------|---------|-----|--------|
| `project-manager` | `Claude 4.5 Sonnet` | `Claude Sonnet 4.6` | Fix naming + upgrade to Sonnet 4.6 |
| `accessibility` | `Claude Sonnet 4.5 (copilot)` | `Claude Sonnet 4.6` | Remove `(copilot)` suffix + upgrade |
| `ui-ux-designer` | `Claude Opus 4.6 (copilot)` | `Claude Opus 4.6` | Remove inconsistent `(copilot)` suffix |
| `mentor` | `Claude Opus 4.6` | `Claude Sonnet 4.6` | Teaching/explaining is balanced-tier, not deep-reasoning |
| `janitor` | `GPT-5.3-Codex` | `Claude Sonnet 4.6` | Cleanup/formatting doesn't need coding-specialist model |
| `devops` | `Claude Sonnet 4.5` | `Claude Sonnet 4.6` | Upgrade to latest Sonnet |
| `svg-diagram` | `Claude Sonnet 4.5` | `Claude Sonnet 4.6` | Upgrade to latest Sonnet |
| `mermaid-diagram-specialist` | **MISSING** | `Claude Sonnet 4.6` | Add model field; diagram generation is balanced-tier |
| All others | Keep current | — | Tier assignments are correct |

**Add model selection guide** to `project-config.md` (Phase 6.3) so future users on different model stacks know the tier philosophy.

### Individual agent fixes

| # | Agent File | Specific Fixes | Priority |
|---|-----------|---------------|----------|
| 2.1 | `ui-ux-designer.md` | Rename to `ui-ux-designer.agent.md`, add handoffs (→Architect, →UX Designer, →Frontend Dev, →Accessibility), strip unparsed closing paragraph, add framework feasibility warnings, add scope boundary | HIGH |
| 2.2 | `ux-designer.agent.md` | Add mockup skill routing (`skills/frontend/mockup/SKILL.md`), remove Streamlit hardcoding (make framework-conditional via project-config), expand handoff list, add artifact output (writes to `agent-docs/ux/`) | HIGH |
| 2.3 | `architect.agent.md` | Remove hardcoded "VMIE Technology Context" section (lines with Python/Streamlit/SQL Server), replace with "Read project-config.md → Tech Stack", update artifact paths from `docs/architecture/` to `agent-docs/architecture/`. Add: dispatches to specialist agents (UX, Security) and reads their artifacts back. | HIGH |
| 2.4 | `plan.agent.md` | Move agent/prompt block to TOP of each phase (before implementation details) in the output template, remove Streamlit-specific hardcoded gotchas (make framework-conditional), update artifact paths. Each phase prompt must instruct the executing agent to read the Intent Document first. | HIGH |
| 2.5 | `implement.agent.md` | Remove hardcoded project structure (lines ~715-740), hardcoded commands (lines ~755-770), replace with `project-config.md` reference. Make framework gotchas conditional. Fix `skills/vmie/svg-create` → generic path. Add scope boundary. | HIGH |
| 2.6 | `mermaid-diagram-specialist.md` | Rename to `mermaid-diagram-specialist.agent.md` OR demote to `skills/docs/mermaid-diagram/SKILL.md`. Fix frontmatter schema, add model/handoffs if keeping as agent. | MEDIUM |
| 2.7 | `code-reviewer.agent.md` | Remove `render_header()` project-specific reference. Add scope boundary + artifact protocol (writes to `agent-docs/reviews/`). **NEW: Add chain audit responsibility** — before any feature is "done", verify: all artifacts carry same `chain_id`, work satisfies Intent Document success criteria, approval gates were respected, manifest is up to date. | MEDIUM |
| 2.8 | `data-engineer.agent.md` | Remove hardcoded `src/services/data_ingestion/` path. Add scope boundary. | LOW |
| 2.9 | `streamlit-developer.agent.md` | Ensure brand values come from `project-config.md`, not hardcoded. Add artifact protocol (code files are the primary output). | MEDIUM |
| 2.10 | `frontend-developer.agent.md` | Same — generic, project-config driven. Add scope boundary. | MEDIUM |
| 2.11 | `janitor.agent.md` | Add artifact hygiene responsibility: scan `agent-docs/ARTIFACTS.md`, move superseded/archived items older than 30 days to `agent-docs/.archive/`. Also clean up resolved escalations. | MEDIUM |
| 2.12 | `prd.agent.md` | Update artifact path `docs/prd/` → `agent-docs/prd/`. Add: must read Intent Document first, PRD must reference `chain_id`, set `approval: pending`. Add scope boundary. | MEDIUM |
| 2.13 | `debug.agent.md` | Add artifact protocol (writes investigation reports to `agent-docs/debug/`). Add scope boundary. Otherwise GOOD. | LOW |
| 2.14 | `tester.agent.md` | Add artifact protocol (writes coverage analysis to `agent-docs/testing/`). Add scope boundary. Otherwise GOOD. | LOW |
| 2.15 | `sql-expert.agent.md` | Add scope boundary. Otherwise GOOD. | LOW |
| 2.16 | `security-analyst.agent.md` | Add artifact protocol (writes audit reports to `agent-docs/security/`). Add scope boundary. **Architect may dispatch to this agent** — output must carry `chain_id`. | MEDIUM |
| 2.17 | `devops.agent.md` | Add scope boundary. Otherwise GOOD. | LOW |
| 2.18 | `mentor.agent.md` | Add scope boundary. Otherwise GOOD. | LOW |
| 2.19 | `prompt-engineer.agent.md` | Add scope boundary. **NEW: Add Intent Document creation** — when refining vague input, use `skills/workflow/intent-writer/SKILL.md` to produce structured Intent Document. This agent is the optional first step in the pipeline. | MEDIUM |
| 2.20 | `project-manager.agent.md` | Add scope boundary. Otherwise GOOD. | LOW |
| 2.21 | `accessibility.agent.md` | Add scope boundary. Otherwise GOOD. | LOW |
| 2.22 | `svg-diagram.agent.md` | Add scope boundary. Update skill path from vmie to generic. Otherwise GOOD. | LOW |

---

## Phase 3 — Fix Instructions (22 files)

> **Agent**: `@implement`
> **Estimated tasks**: 22 instruction files

### Step 3.1 — MINOR fixes (12 files): Strip "VMIE" from titles/descriptions

- [ ] `code-review.instructions.md` — Title, description, remove "VMIE-Specific Checklist" heading, replace `libs/vmie_*` with `<SHARED_LIBS>` reference
- [ ] `docker.instructions.md` — Title, description, replace `vmie-api/vmie-frontend` service names with generic
- [ ] `github-actions.instructions.md` — Title, description, replace `VMIE CI/CD Pipeline` with generic
- [ ] `gpu.instructions.md` — Title, description, replace "VMIE has on-premise GPU infrastructure" with generic
- [ ] `mcp-server.instructions.md` — Title, description, replace `vmie-tools` with generic
- [ ] `plan-mode.instructions.md` — Replace Streamlit/SQL Server scenario examples with generic or multi-framework
- [ ] `playwright.instructions.md` — Title, description, replace `VMIE Dashboard` test expectation
- [ ] `plotly-charts.instructions.md` — Title, description, replace "VMIE color palette" reference
- [ ] `portability.instructions.md` — Title, description (ironic for a portability file to say "VMIE")
- [ ] `python.instructions.md` — Title, description, replace `from vmie_ui.theme` imports with `<SHARED_LIBS>` reference, replace `VIRGIN_PRIMARY_COLOR` with `<BRAND_PRIMARY>`
- [ ] `security.instructions.md` — Title, description, replace `internal.vmie.local` and `vmie.example.com` with generic
- [ ] `testing.instructions.md` — Title, description, replace complaint-domain test examples with generic, replace `libs/vmie_data` with `<SHARED_LIBS>`

### Step 3.2 — MAJOR fixes (4 files): Deep rewrite needed

- [ ] `fastapi.instructions.md` — Replace `VMIE API`, `VMIE Complaints API`, complaint domain model examples, `libs/vmie_data.DatabaseAdapter` with placeholder-based generics
- [ ] `frontend.instructions.md` — Replace all `--vmie-*` CSS vars, Virgin Media colors, branded HTML with `project-config.md` placeholder tokens (`<BRAND_PRIMARY>`, `<BRAND_DARK>`, etc.)
- [ ] `sql.instructions.md` — Remove `src/ingestion_config/queries.yaml` path, `L7DCases`/`L30DInteractions` table names, make query externalization section configurable
- [ ] `streamlit.instructions.md` — 811 lines: Replace Virgin branding, `libs/vmie_*` imports, branded component code with `project-config.md` references

### Step 3.3 — Add agent-docs exclusion

- [ ] Add note to documentation-related instructions: "When scanning for project documentation, skip `agent-docs/`. This folder contains working artifacts for inter-agent communication."

### Step 3.4 — Update README

- [ ] `instructions/README.md` — Strip VMIE branding, update to reflect generic naming

---

## Phase 4 — Fix Prompts (25 files)

> **Agent**: `@implement`
> **Estimated tasks**: ~15 prompt files to update

### Step 4.1 — Delete project-specific prompt

- [ ] DELETE `prompts/360Customer-newchat.prompt.md`

### Step 4.2 — MINOR fixes (10 files)

- [ ] `api-documentation.prompt.md` — Replace "VMIE dashboard/system" examples, add frontmatter
- [ ] `debug-help.prompt.md` — Replace pyodbc/SQLSERVER01 examples with generic, add frontmatter
- [ ] `mcp-development.prompt.md` — Replace `vmie-database` example, add frontmatter
- [ ] `migrate-project.prompt.md` — Replace 8+ "VMIE" references with generic
- [ ] `performance-optimization.prompt.md` — Remove "VMIE-Specific Optimizations" section heading
- [ ] `project-setup.prompt.md` — Replace "VMIE scripts folder" references with generic
- [ ] `pytest-coverage.prompt.md` — Merge into `test-coverage.prompt.md` as Python-specific section, then delete
- [ ] `test-coverage.prompt.md` — Absorb pytest-coverage content
- [ ] `sync-skills-readme.md` — Rename to `sync-skills-readme.prompt.md`
- [ ] `prompts/README.md` — Strip VMIE branding, remove 360Customer-newchat reference

### Step 4.3 — Create mockup prompt

- [ ] Create `prompts/mockup.prompt.md` — Trigger prompt for the mockup skill

---

## Phase 5 — VMIE Skills Restructure

> **Agent**: `@implement`
> **Estimated tasks**: ~20 skill files to move/delete/merge

### Step 5.1 — Inventory current `skills/vmie/` contents

Current vmie skills (18):
1. `vmie/architecture-design/` — VMIE architecture standards → promote to `skills/workflow/architecture-design/`
2. `vmie/caching-patterns/` — Caching strategies → promote to `skills/coding/caching-patterns/`
3. `vmie/fastapi-dev/` — FastAPI patterns → promote to `skills/coding/fastapi-dev/`
4. `vmie/query-display/` — Dev-mode SQL query transparency → promote to `skills/frontend/query-display/`
5. `vmie/streamlit-dev/` — Branded duplicate of `frontend/streamlit-dev` → DELETE (generic exists)
6. `vmie/svg-create/` — SVG creation → promote to `skills/media/svg-create/` (if not already there)
7. `vmie/ui-review/` — Branded duplicate of `frontend/ui-review` → DELETE (generic exists)
8. `vmie/ux-design/` — VMIE UX guidelines → promote to `skills/frontend/ux-design/`
9. `vmie/vm-ppt/` — Presentation templates → promote to `skills/docs/presentation/` or `skills/media/presentation/`
10. `vmie/webapp-development/` — Webapp patterns → promote to `skills/coding/webapp-development/`
11-18. Any remaining skills → audit individually, promote or delete

### Step 5.2 — Promote unique skills with placeholder tokens

For each skill promoted from `vmie/` to a generic category:
- [ ] Replace hardcoded VMIE values with `<PLACEHOLDER>` tokens
- [ ] Add header: "Read project-config.md to resolve placeholder values"
- [ ] Move to appropriate generic category folder

### Step 5.3 — Delete `skills/vmie/` folder

- [ ] Confirm all unique content promoted
- [ ] Delete the entire `skills/vmie/` directory

### Step 5.4 — Update skill resolution in project-config.md

- [ ] Remove the "Skill resolution rule" section that references `skills/vmie/`
- [ ] Remove "VMIE-only skills" section
- [ ] Update the "How Agents Use This File" flowchart (remove vmie skill fallback logic)
- [ ] Keep profile system for placeholder resolution only

---

## Phase 6 — Update Supporting Files

> **Agent**: `@implement`
> **Estimated tasks**: 5 files
> **Dependencies**: Phases 2-5 must be complete (references need to exist before updating indexes)

### Step 6.1 — Update skills registry

- [ ] `skills/_registry.md` — Remove VMIE section, add new skills (mockup, onboard-project, intent-writer), update all paths from vmie/ to generic categories

### Step 6.2 — Update workflow cheatsheet

- [ ] `diagrams/AGENT_WORKFLOW_CHEATSHEET.md` — Add:
  - UI/UX decision tree
  - "Wrong agent" guardrail
  - Mockup/design workflow pattern
  - Artifact protocol documentation
  - `agent-docs/` explanation and folder structure
  - Automated pipeline diagram (PRD → Architect → Plan → Implement)
  - Intent Document system explanation
  - Approval gates documentation
  - Escalation protocol
  - Chain-of-Origin rule
  - Context Priority Order

### Step 6.3 — Update project-config.md for this project

- [ ] Update `project-config.md` to match new schema:
  - Remove "Skill resolution rule" section (vmie skill fallback)
  - Remove "VMIE-only skills" section
  - Update "How Agents Use This File" flowchart (remove vmie skill fallback, simplify to: profile set? → use profile values for placeholders)
  - Update promoted skill paths (e.g., `skills/vmie/fastapi-dev/` → `skills/coding/fastapi-dev/`)
  - Keep all VMIE profile values (colors, tech stack, data sources, project structure, conventions)

### Step 6.4 — Review copilot-instructions.md

- [ ] Check if any sections of the existing `copilot-instructions.md` reference old `skills/vmie/` paths → update to new generic paths
- [ ] Check if any onboard-template sections are missing from the existing file → merge if needed
- [ ] Ensure `copilot-instructions.md` works with the updated `project-config.md` schema

---

## Phase 7 — Verification

> **Agent**: `@implement`
> **Estimated tasks**: 4 verification passes
> **Dependencies**: All previous phases complete

### Step 7.1 — Grep for remaining hardcoding

- [ ] Search entire `.github/` for: `VMIE`, `vmie`, `Virgin`, `a customer-data app`, `ServeSight`, `Customer_FeedBack_JIT`, `IECLONDBUAT01`
- [ ] Any hits that are NOT in `project-config.md` or `copilot-instructions.md` → fix
- [ ] Allowed exceptions: `project-config.md` (profile definitions), `copilot-instructions.md` (project-specific)

### Step 7.2 — Cross-reference validation

- [ ] All agent handoff targets exist as `.agent.md` files
- [ ] All skill paths referenced in agents/instructions exist
- [ ] All prompts have valid frontmatter
- [ ] All agent artifact paths match `agent-docs/` subfolder structure
- [ ] All agents have all 7 universal protocols
- [ ] Intent writer skill exists and is referenced in prompt-engineer agent
- [ ] New-feature prompt exists and routes correctly

### Step 7.3 — Portability smoke test

- [ ] Confirm: if you delete `copilot-instructions.md` and reset `project-config.md` to blank profile, the entire pool should still parse correctly (just with unresolved `<PLACEHOLDER>` tokens)
- [ ] Confirm: `skills/vmie/` no longer exists
- [ ] Confirm: `agent-docs/ARTIFACTS.md` exists with template
- [ ] Confirm: all 7 universal protocols are present in every agent file
- [ ] Confirm: the automated pipeline workflow (new-feature prompt → intent → PRD → architect → plan → implement) has all pieces in place

### Step 7.4 — Dependency ordering verification

- [ ] Confirm no broken references exist (skills deleted in Phase 5 are no longer referenced by agents fixed in Phase 2)
- [ ] Run a final scan for any `skills/vmie/` path references anywhere in `.github/`

---

## Phase Dependency Map

```
Phase 1 (Foundation)
    │
    ▼
Phase 2 (Fix Agents) ──► references skills created in Phase 1
    │
    ├──► Phase 3 (Fix Instructions) — can run in parallel with Phase 4
    │
    ├──► Phase 4 (Fix Prompts) — can run in parallel with Phase 3
    │
    ▼
Phase 5 (VMIE Skills) ──► depends on Phases 2-4 (all vmie references updated first)
    │
    ▼
Phase 6 (Supporting Files) ──► depends on Phase 5 (registry needs final paths)
    │
    ▼
Phase 7 (Verification) ──► depends on all above
```

---

## Progress Tracker

| Phase | Status | Notes |
|-------|--------|-------|
| Phase 1 — Foundation (6 files) | COMPLETE | All 6 files created |
| Phase 2 — Fix Agents (22 files) | COMPLETE | All 22 agents: protocols added, Project Context fixed, hardcoded refs removed, model audit applied |
| Phase 3 — Fix Instructions (22 files) | COMPLETE | 16 files with VMIE refs fixed (4 MAJOR rewrites: frontend, streamlit, python, docker + 12 MINOR), 6 already clean. Verified: 0 VMIE refs in instructions/ |
| Phase 4 — Fix Prompts (~15 files) | COMPLETE | 8 prompt files fixed, 1 deleted (360Customer-newchat), 1 renamed (sync-skills-readme → .prompt.md), 1 created (mockup.prompt.md). Verified: 0 VMIE refs in prompts/ |
| Phase 5 — VMIE Skills (~20 files) | COMPLETE | 7 duplicates deleted, 8 unique skills promoted to generic categories with de-branding, 1 merged (sql), 2 kept as project-specific (query-display, vm-ppt). vmie/ reduced from 18 → 2 folders |
| Phase 6 — Supporting Files (5 files) | COMPLETE | _registry.md rebuilt, project-config.md simplified (skill fallback removed), workflow cheatsheet fixed, copilot-instructions.md stale paths updated |
| Phase 7 — Verification (4 passes) | COMPLETE | Grep scan: 0 VMIE refs in agents/, instructions/, prompts/, skills/{coding,frontend,media}/, diagrams/, handoffs/. Only intentional refs remain in project-config.md, copilot-instructions.md, _registry.md (project-specific sections) |

---

## Post-Completion: Advisory Hub Session Updates (2026-02-20)

After the 7-phase pool overhaul was completed, a follow-up Advisory Hub session extended the workflow infrastructure with the additions below. These are recorded here because this document is the canonical design reference for the entire agent workflow system.

### Update 1 — Agent Orchestration Blueprint (SKILL.md)

**Created**: `.github/skills/workflow/agent-orchestration/SKILL.md` (~350 lines)
**Registered in**: `.github/skills/_registry.md` (Workflow category)
**Wired into**: Plan, Architect, Implement, Debug agents (skill reference added to each)

Captures the **Advisory Hub methodology** — a reusable orchestration pattern for multi-agent feature development:

- **6-Stage Pipeline**: Triage → Spec/ADR → Plan → Absorb → Execute (Track phases) → Review/Debug
- **Decision Framework**: When to use Advisory Hub vs. Project Chat (single-agent)
- **Anti-Patterns**: Context fragmentation, premature implementation, skipping gates
- **Session Templates**: Fresh start, continuation, directed tasks
- **Commit Discipline**: Feature commits at each milestone, conventional commit format
- **Real-World Reference**: Juno UX Polish v2 (Track B phases 1-5, fix-up, Track A ADR)

### Update 2 — `/advisoryhub` Slash Command (Prompt)

**Created**: `.github/prompts/advisory-hub.prompt.md`
**Registered in**: `.github/prompts/README.md`

Entry point for Advisory Hub mode — auto-detects session type:
- **Fresh Start** → intake questions (what are we building? constraints? existing artifacts?)
- **Continuation** → scans `plans/`, `handoffs/`, git log → presents status dashboard
- **Directed** → routes to appropriate pipeline stage (e.g., "plan Track A" → Planner agent)

Includes: status dashboard format, pipeline stage routing table, session rules.

### Update 3 — `agent-docs/` Sub-Folder Scaffolding

**Commit**: `eeae240`

**Problem**: All 22 agents had the Artifact Output Protocol wired (writing to `agent-docs/{category}/`), but Git doesn't track empty directories. The sub-folders didn't exist on disk, so agents had no target directories.

**Fix**: Created `.gitkeep` files in all 11 sub-folders:
```
agent-docs/
├── .archive/.gitkeep
├── intents/.gitkeep
├── escalations/.gitkeep
├── prd/.gitkeep
├── architecture/.gitkeep
├── ux/.gitkeep
├── ux/mockups/.gitkeep
├── ux/reviews/.gitkeep
├── security/.gitkeep
├── reviews/.gitkeep
├── debug/.gitkeep
└── testing/.gitkeep
```

### Update 4 — ARTIFACTS.md Manifest Population

**Commit**: `13cda97`

**Problem**: `agent-docs/ARTIFACTS.md` existed as a template but had zero entries. No artefacts were ever registered despite protocols being in place.

**Fix**: Added 4 initial artefact entries + a traceability note explaining the two-tier placement system:

| Artefact | Location | Status | chain_id |
|----------|----------|--------|----------|
| Track B plan (Juno UX Polish) | `plans/track-b-juno-ux-polish-v2.md` | completed | FEAT-2026-0218-juno-ux-polish-v2 |
| Track B fix-up plan | `plans/track-b-fixup-post-review.md` | completed | FEAT-2026-0218-juno-ux-polish-v2 |
| Track A ADR (Chat Widget) | `docs/architecture/agentic-adr/ADR-chat-widget-architecture.md` | current/approved | FEAT-2026-0219-chat-widget-extraction |
| Track A plan (Chat Widget) | `plans/track-a-chat-widget-microfrontend.md` | current/approved | FEAT-2026-0219-chat-widget-extraction |

**Traceability note added**: Clarifies the three-tier placement system:
- `plans/` → Operational plans (living docs during execution, archived when complete)
- `docs/` → Finalized project documentation (ADRs, API docs, user guides)
- `agent-docs/` → In-transit drafts and inter-agent working artifacts

### Update 5 — Artefact Placement Rules

Documented (in ARTIFACTS.md and here) the clear separation of concerns:

| Tier | Folder | Contents | Lifecycle |
|------|--------|----------|-----------|
| **Operational** | `.github/plans/` | Execution plans, phase trackers | Live during work → archived |
| **Project Docs** | `docs/` | ADRs, API docs, user guides | Permanent project record |
| **Agent Working Space** | `agent-docs/` | Drafts, escalations, reviews | Inter-agent transit → archive after 30 days |

All artefacts registered in `agent-docs/ARTIFACTS.md` regardless of final location — the manifest is the single source of truth for traceability.

---

## Agent Workflow Knowledge Base Map

All documents that together form the complete agent workflow reference:

### Tier 1 — Design Bible (This Document)
| Document | Location | Purpose |
|----------|----------|---------|
| **Agent Workflow Design Reference** | `diagrams/agent-workflow-design-reference.md` | Foundational design: 10 key decisions, pipeline architecture, intent system, artifact protocol, universal protocols, escalation, all implementation phases |

### Tier 2 — Quick Reference (Diagrams Folder)
| Document | Location | Purpose |
|----------|----------|---------|
| **Agent Workflow Cheatsheet** | `diagrams/AGENT_WORKFLOW_CHEATSHEET.md` | Wall-poster reference: agent types, decision tree, workflow patterns, context rules, invocation guide |
| **Agent Reference Card** | `diagrams/agent-reference-card.md` | 22 agents: model tiers, handoffs, skills, instructions, pipeline flow, 7 universal protocols |
| **Skills Reference Card** | `diagrams/skills-reference-card.md` | 88 skills: categories, paths, descriptions, which agents use them |
| **Agent Pipeline Poster** | `diagrams/agent-pipeline-poster.svg` | Visual SVG poster of the agent pipeline |
| **Debug Amendment Workflow** | `diagrams/debug-plan-amendment-workflow.svg` | Visual SVG of Debug → Plan amendment flow |

### Tier 3 — Operational (Skills & Prompts)
| Document | Location | Purpose |
|----------|----------|---------|
| **Agent Orchestration SKILL** | `skills/workflow/agent-orchestration/SKILL.md` | Reusable Advisory Hub methodology — agents load this for multi-agent coordination |
| **Advisory Hub Prompt** | `prompts/advisory-hub.prompt.md` | `/advisoryhub` entry point — auto-detect, status dashboard, pipeline routing |
| **Skills Registry** | `skills/_registry.md` | Master index of all 88 skills with categories and paths |

### Tier 4 — Artefact Tracking
| Document | Location | Purpose |
|----------|----------|---------|
| **ARTIFACTS.md Manifest** | `agent-docs/ARTIFACTS.md` | Single source of truth: all artefacts, chain_ids, statuses, approval gates |

### Tier 5 — Per-Agent (22 Agent Files)
Each agent file in `agents/*.agent.md` contains the 7 Universal Agent Protocols wired in, defining how that specific agent participates in the workflow.

---

## Continuation Protocol

If context window runs out mid-session:

1. Open this reference: `.github/diagrams/agent-workflow-design-reference.md`
2. Read the **Context & Decisions** section — all design decisions, protocol definitions, pipeline architecture
3. Read the **Advisory Hub Session Updates** section — post-completion enhancements
4. Read the **Agent Workflow Knowledge Base Map** — understand which docs exist and what they cover
5. Check `agent-docs/ARTIFACTS.md` for current artefact statuses
6. Read `project-config.md` for project-specific values

**Key files to re-read on resume:**
- This reference: `.github/diagrams/agent-workflow-design-reference.md`
- Project config: `.github/project-config.md`
- Existing copilot-instructions: `.github/copilot-instructions.md`
- Artefact manifest: `.github/agent-docs/ARTIFACTS.md`

**Important context for resuming agent**:
- All agent edits follow the 7 Universal Agent Protocols defined in the Context section
- The artifact system uses `agent-docs/` (NOT `docs/`) — `docs/` is for project documentation
- The Intent Document system preserves user intent across the entire pipeline chain
- The `chain_id` links all artifacts in a feature chain
- Approval gates prevent runaway pipeline execution
- Escalations are the formal feedback loop from downstream to upstream agents
