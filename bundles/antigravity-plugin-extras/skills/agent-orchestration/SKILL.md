---
name: agent-orchestration
description: "End-to-end blueprint for orchestrating the full agent pipeline — from spec intake through planning, implementation, testing, and debugging — plus the multi-model fan-out rules (when a second model is worth it, the intent→model map, and the cost guardrails)"
---

# Agent Orchestration Blueprint

## Purpose

Codify the **Advisory Hub** methodology: a repeatable workflow where the human operator drives a multi-agent pipeline from raw specification to production-ready code. This skill captures the exact sequence, decision points, and artefacts that emerged from real feature delivery so any future session can follow the same playbook.

---

## When to Use

- Starting a new feature, refactor, or large bug-fix that spans multiple files and sessions
- Resuming a multi-session effort and need to recall the methodology
- Onboarding a new collaborator to the agent-driven workflow
- Auditing whether a completed feature followed the full pipeline

---

## Core Concepts

### Advisory Hub Mode

The operator (human) acts as **orchestrator**. Agents act as an **advisory board** — each specialised, none acting unilaterally. The operator:

1. **Supplies context** — spec files, codebase pointers, domain knowledge
2. **Chooses the next agent** — based on where the work stands
3. **Reviews artefacts** — plans, ADRs, prompts, code, test results
4. **Commits incrementally** — checkpoint after each verified stage

```
┌─────────────────────────────────────────────────────────┐
│                   ADVISORY HUB                          │
│                                                         │
│   Operator ◄──► PRD Agent        (requirements)        │
│   Operator ◄──► Architect Agent  (design decisions)     │
│   Operator ◄──► Planner agent       (implementation plan)  │
│   Operator ◄──► Implement Agent  (code generation)      │
│   Operator ◄──► Tester Agent     (test coverage)        │
│   Operator ◄──► Code Reviewer    (quality gate)         │
│   Operator ◄──► Debug Agent      (cross-cut polish)     │
│                                                         │
│   The operator is the thread that ties agents together. │
│   Agents never chain autonomously without review.       │
└─────────────────────────────────────────────────────────┘
```

### Key Principle: Artefact-Driven Workflow

Every stage produces a **persistent artefact** (markdown file, commit, test run) that the next stage can consume without relying on conversation memory. This is what makes multi-session execution reliable.

> The pipeline below is the **sequential** axis — which agent, in what order. There is a second,
> independent axis: **how many models** work a given stage. That is deliberately rationed — see
> [Multi-model fan-out](#multi-model-fan-out-the-second-axis-how-many-models) before reaching for a
> second model.

| Stage | Artefact | Location |
|-------|----------|----------|
| Requirements | Spec / feature file | Supplied by operator (e.g. `nextprompt.md`) |
| Quick-Win Triage | Commit with passing tests | Git history |
| Architecture | ADR (Architecture Decision Record) | Inside the plan document |
| Planning | Plan document (phases, steps, files) | `.github/plans/<feature>.md` |
| Fidelity Audit | Gap table (0 gaps = pass) | Inside the plan document |
| Risk Assessment | Risk register (scored risks) | Inside the plan document |
| Implementation Prompts | Embedded copy-paste prompts | Inside the plan document |
| Implementation | Code + tests per phase | Git commits per phase |
| Code Review | Review report | Chat session or plan annotation |
| Debug / Polish | Fix-up plan (issues A–N) | `.github/plans/<feature>-fixup.md` |

---

## The Full Pipeline

### Overview

```
Spec Input
    │
    ▼
┌─────────────────┐
│ Stage 0: Triage │  ← Quick wins (H1–H3) committed immediately
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Stage 1: ADR    │  ← Architect Agent scores options, operator picks
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Stage 2: Plan   │  ← Planner agent writes phased plan + fidelity audit
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Stage 3: Absorb │  ← Mid-flight changes merged into plan (optional)
└────────┬────────┘
         │
         ▼
┌─────────────────────────────┐
│ Stage 4: Implement (×N)     │  ← One phase per session, tests pass
└────────┬────────────────────┘
         │
         ▼
┌─────────────────┐
│ Stage 5: Review │  ← Code Reviewer Agent checks each phase
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Stage 6: Debug  │  ← Cross-component polish, final commit
└─────────────────┘
```

---

### Stage 0: Triage & Quick Wins

**Agent:** Planner agent (read-only analysis) → Implement Agent (execute)

**Purpose:** Before any heavy planning, scan the spec for low-effort / high-value items that can be shipped in a single session.

**Process:**
1. Read the full spec input (e.g. `nextprompt.md`)
2. Categorise every item by effort (H = hours, D = days) and value (high / medium / low)
3. Items that are **≤ 1 hour AND high-value** become quick wins (H1, H2, H3…)
4. Implement quick wins in a single session
5. Run full test suite — all tests must pass
6. Commit: `feat: H1–H3 quick wins — <summary>`

**Decision Gate:**
- If quick wins alone satisfy the spec → **done**, no further stages needed
- If remaining work is significant → proceed to Stage 1

**Artefact:** Git commit with passing tests.

---

### Stage 1: Architecture Decision Record (ADR)

**Agent:** Architect Agent

**Purpose:** For non-trivial work, evaluate competing design approaches before committing to a plan.

**Process:**
1. Present the remaining spec items to the Architect Agent
2. Architect proposes 2–4 options with trade-off analysis
3. Each option is scored across dimensions:
   - Implementation complexity (1–5)
   - Maintainability (1–5)
   - Performance impact (1–5)
   - User experience (1–5)
   - Risk level (1–5)
4. Operator reviews, asks questions, selects the winning option
5. ADR is written into the plan document header

**Decision Gate:**
- If the spec is straightforward enough that architecture is obvious → **skip ADR**, proceed to Stage 2
- If there are genuinely competing approaches → write the ADR

**Artefact:** ADR section in the plan document with option scores and rationale.

---

### Stage 2: Plan Creation & Verification

**Agent:** Planner agent

**Purpose:** Create a comprehensive, phased implementation plan that any agent can follow without ad-hoc interpretation.

**Process:**

#### 2a. Plan Authoring
1. Read: spec, ADR (if created), existing codebase patterns
2. Break work into **phases** (each phase = 1 chat session)
3. Each phase contains **numbered steps** with:
   - File(s) to modify
   - What to change (specific enough to implement without guessing)
   - Expected test additions
   - Verification command
4. Place plan in `.github/plans/<feature-name>.md`

#### 2b. Fidelity Audit
After authoring, audit the plan against the spec:

```
┌──────────────────────────────────────────────────┐
│            FIDELITY AUDIT                        │
│                                                  │
│  For EACH requirement in the spec:               │
│    → Is it mapped to a plan step?                │
│    → Is the mapping specific (not hand-wavy)?    │
│                                                  │
│  Produce a gap table:                            │
│  | Spec Item | Plan Step | Status |              │
│  |-----------|-----------|--------|              │
│  | Feature X | Phase 2.3 | ✅     |              │
│  | Feature Y | —         | ❌ GAP |              │
│                                                  │
│  Target: 0 gaps before proceeding.               │
└──────────────────────────────────────────────────┘
```

#### 2c. Risk Assessment
Score each identified risk:

| Risk | Likelihood (1–5) | Impact (1–5) | Mitigation |
|------|-------------------|--------------|------------|
| Example risk | 3 | 4 | Mitigation strategy |

- **Showstoppers** (Likelihood × Impact ≥ 16): Must be resolved before implementation
- **Watch items** (8–15): Monitor during implementation
- **Accepted** (< 8): Proceed with awareness

**Decision Gate:**
- 0 gaps in fidelity audit → proceed
- Any gaps → update plan until 0 gaps
- Any showstopper risks → resolve before implementation

**Artefact:** Plan document with fidelity audit table, risk register, and embedded prompts.

---

### Stage 3: Mid-Flight Absorption (When Needed)

**Agent:** Planner agent (or operator + Advisory Hub)

**Purpose:** Handle changes that arrive after the plan is created but before or during implementation. This is inevitable in real projects.

**Triggers:**
- Operator makes independent code changes (e.g. adds a new model field)
- New requirements emerge from stakeholder feedback
- Testing reveals the plan assumed something incorrect
- A dependency changes

**Process:**
1. **Identify the delta** — What changed vs. what the plan assumed?
2. **Trace the impact** — Which plan steps are affected?
3. **Update the plan** — Modify affected steps, add new steps if needed
4. **Re-count** — Update phase sizes, renumber if necessary
5. **Update embedded prompts** — Regenerate any copy-paste prompts that reference changed steps
6. **Commit the plan update** — `docs: absorb <change> into plan — <N> edits`

**Example from practice:**
> Operator added `SCORE_TOOLTIPS` dict to the Pydantic model independently.
> Planner agent traced 16 affected steps, updated them to reference the new dict,
> fixed band name inconsistencies exposed by the change, and regenerated 5 prompts.

**Anti-pattern:** Implementing against a stale plan. Always check if the plan reflects current reality before starting a phase.

**Artefact:** Updated plan document + commit.

---

### Stage 4: Phased Implementation

**Agent:** Implement Agent (one phase per session)

**Purpose:** Execute the plan incrementally, with each session producing a committed, tested increment.

**Process per phase:**
1. Start a **new chat session** (clean context)
2. Provide the phase prompt:
   ```
   Read .github/plans/<feature>.md and implement Phase N.
   Run pytest after every file change. All tests must pass before commit.
   ```
3. Implement Agent reads the plan, executes numbered steps
4. After implementation: run full test suite
5. If tests pass → commit: `feat(<scope>): phase N — <summary>`
6. If tests fail → fix within the same session before committing

**Session Discipline:**
- **One phase per session** — avoids context exhaustion
- **Plan is source of truth** — agent follows the plan, doesn't freelance
- **Tests are the gate** — no commit without green tests
- **No plan edits by Implement Agent** — if a plan error is found, use Debug Agent's plan amendment protocol

**Embedded Prompts:**
The plan document should contain **copy-paste prompts** for each phase. This removes ambiguity:

```markdown
### Phase 2 Prompt (copy into new chat)

> Read `.github/plans/my-feature.md`, specifically Phase 2 (steps 5–9).
> Implement each step in order. Run `pytest tests/ -x -q` after each file edit.
> When all steps pass, commit with message:
> `feat(cards): phase 2 — insight card refactoring`
```

**Artefact:** Git commit per phase with passing tests.

---

### Stage 5: Code Review

**Agent:** Code Reviewer Agent

**Purpose:** Quality gate before declaring the implementation complete.

**Process:**
1. After all phases are implemented, start a review session
2. Code Reviewer reads the plan + all changed files
3. Review criteria:
   - Correctness: Does the code match the plan intent?
   - Style: Consistent with project conventions?
   - Performance: No regressions?
   - Security: No new vulnerabilities?
   - Test coverage: Adequate for the changes?
4. If issues found → send back to Implement Agent with specific fixes
5. If clean → proceed to Stage 6 or declare complete

**Artefact:** Review report (clean pass or list of issues).

---

### Stage 6: Cross-Component Debug & Polish

**Agent:** Debug Agent (analysis) → Implement Agent (fixes)

**Purpose:** After multi-phase implementation, cross-cutting issues often emerge that no single phase could have caught. This stage catches them.

**Triggers:**
- UI inconsistencies across components
- Duplicated data appearing in multiple cards/views
- CSS/styling divergence between independently-built components
- Data model gaps revealed by integration
- Layout issues visible only when all components render together

**Process:**
1. **Audit** — Debug Agent reviews all touched files holistically
2. **Catalogue** — Issues labelled A through N with:
   - What's wrong
   - Where it manifests (file + line range)
   - Root cause
   - Proposed fix (specific enough to implement)
   - Acceptance criteria
3. **Write fix-up plan** — Place in `.github/plans/<feature>-fixup.md`
4. **Execute** — Implement Agent works through issues sequentially
5. **Verify** — Run full test suite + visual inspection
6. **Commit** — `fix(<scope>): post-track cross-component polish`

**Example from practice:**
> After 5 implementation phases, the Debug Agent found:
> - Health Score appearing in both insight cards AND summary card (duplication)
> - Two tooltip CSS functions with different background colours (#4A4A4A vs #1F2937)
> - Card height inconsistency (one card taller due to unused metric)
> - Verbose alert text that should have been simplified
> These became 7 catalogued issues (A–G) in a fix-up plan.

**Artefact:** Fix-up plan document + final commit.

---

## Decision Framework: Which Agent When?

```
┌─────────────────────────────────────────────────────────┐
│                  AGENT SELECTION GUIDE                   │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  "I have a raw spec / feature request"                  │
│   → Planner agent (triage quick wins, then plan)           │
│                                                         │
│  "I need to choose between design approaches"           │
│   → Architect Agent (ADR with scored options)           │
│                                                         │
│  "I have a plan, need implementation"                   │
│   → Implement Agent (one phase per session)             │
│                                                         │
│  "Implementation is done, need quality check"           │
│   → Code Reviewer Agent                                │
│                                                         │
│  "Tests are failing after implementation"               │
│   → Debug Agent (root-cause, then fix)                  │
│                                                         │
│  "Multiple components don't look right together"        │
│   → Debug Agent (cross-component audit)                 │
│                                                         │
│  "I changed the model / data independently"             │
│   → Planner agent (absorb changes into plan)               │
│                                                         │
│  "I need database schema changes"                       │
│   → SQL Expert Agent                                    │
│                                                         │
│  "I need new Streamlit components"                      │
│   → Streamlit Developer Agent                           │
│                                                         │
│  "Session needs resumable context"                      │
│   → Relay Skill                                          │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## Multi-model fan-out (the second axis: how many models)

> ### ⚠️ If you are not Claude Code, treat this section as ADVISORY and execute solo.
> The `Agent` tool, its per-agent `model:` override, the `Workflow` tool, and the `/glm`,
> `/deepseek`, `/caddis:cross-review` commands described below are **Claude-Code-only**. On Codex,
> Copilot, Antigravity/agy, or any other host: take the *judgement* from this section — default solo,
> cheapest deterministic check first, don't trust a single model on a security invariant — and
> **ignore the mechanics**. Do not attempt to emulate fan-out by hand, do not tell the user to run
> tools your host does not have, and do not treat the model map below as instructions you can execute.
> Solo execution is a correct, complete outcome here.

Everything above is *sequential*: one model, one stage at a time, operator in the loop. **Fan-out** —
running two or more models on the same work and reconciling their output — is a separate axis, and it
is **expensive in three currencies at once**: provider quota, the orchestrator's own context, and the
human's attention. It earns its cost rarely. The rules below are ordered; apply them in order.

### Rule 0 — default SOLO

**One model does the work. That is the default and it is right most of the time.** Fan out only when
the work is genuinely high-risk *or* high-uncertainty:

| Fan out | Stay solo |
|---|---|
| Security-sensitive code — authn/authz, crypto, secret handling, input trust boundaries | Boilerplate, CRUD, scaffolding |
| Correctness-critical algorithms where a subtle wrong answer looks right (concurrency, money, dates/timezones, migrations, dedup/merge logic) | Mechanical refactors with a green suite either side |
| Ambiguous specs — where the risk is that *everyone* misreads the requirement the same way | Anything a test, type-checker, or linter can decide |
| Verifying a frontier model's **own** risky output — a model is the worst reviewer of its own reasoning | Work already covered by an existing review gate |
| Irreversible / wide blast radius — a drop, a flag day, a fleet-wide sweep | Work you can trivially revert |

Two failure modes, both real: **fanning out on size** (a big mechanical task is still solo — split it
across *sessions*, not models) and **fanning out for reassurance** (a second opinion you have already
decided to ignore is pure cost).

### Rule 1 — cheapest check first

**Never spend a second model on something a deterministic check can decide.** Climb this ladder and
stop at the first rung that answers the question:

1. **Tests / types / linters / the build.** If a failing test, `mypy`/`tsc`, or a lint rule confirms
   the concern, you are done — that is a *fact*, not an opinion, and it costs nothing.
2. **Read the code.** A targeted grep or a five-line read beats any model's guess about what the code
   does.
3. **A subagent on the same model** (`code-reviewer`, `security-analyst`, `anchor`, `preflight`) — a
   fresh context, not a fresh vendor. Catches most "did we miss something" cases.
4. **A different tier** — escalate one model tier for the hard part only.
5. **Cross-vendor.** The last rung, and the rationed one (see the guardrails).

If a deterministic check *can* be written but doesn't exist yet, **write the check** — it is cheaper
than the model call and it keeps paying.

### Rule 2 — name the INTENT, not the model

Talk about lanes by what they are *for*, so plans, prompts, and reviews survive model releases and the
LiteLLM cutover. **This table is the single place the intent→model mapping lives** — everything else
(plans, commands, skills) refers to the intent name and points here.

| Intent | What it's for | Current model | Claude Code mechanics | Cost |
|---|---|---|---|---|
| **deepest** | Subtle correctness, security invariants, novel architecture, judgment-heavy seams | `opus` | `/model opus`; `Agent(model: "opus")` | **High** — Anthropic plan quota |
| **broad** | Wide parallel coverage of a large but not-subtle surface; the workhorse | `sonnet` | `/model sonnet`; `Agent(model: "sonnet")` | Medium — the default; budget for several |
| **mechanical** | Fully-specced, repeat-of-a-known-pattern, no judgment required | `haiku` | `/model haiku`; `Agent(model: "haiku")` | Low |
| **cross-vendor-reviewer** | A *different vendor's* blind spots on a diff — **code review only** | `deepseek` (default), `glm` | `/caddis:cross-review`, `/glm`, `/deepseek` | **Scarce** — separate starter-tier subscription, NOT Anthropic quota. Ration it. |
| **synthesis / long-horizon** | Orchestrating many lanes, or work that can't self-verify across a large codebase | `fable` | `/model fable` | **Very high** — ~2× opus's rate-limit burn. RARE. |

**Update this table, not the callers**, when a model is added, retired, or re-tiered. A plan that says
"cross-vendor-reviewer" keeps working; a plan that says "deepseek-chat" rots.

### Hard guardrails

These are constraints, not preferences. Each exists because breaking it produced a real cost.

1. **DeepSeek and GLM are the CODE-REVIEW lane, and nothing else.** Map them to cross-vendor review of
   a diff or a concrete file set. **Never** general audit, research, planning, architecture, or
   open-ended subagent work — they are unreliable outside that lane, and an unreliable lane's output
   still costs a full synthesis pass to disprove.
2. **Ration cross-vendor to ~one consolidated pass per task.** One review of the whole change, not one
   agent per area. Alternate vendors *between* tasks (DeepSeek this diff, GLM the next) — different
   families have different blind spots and alternation maximises what the pair catches over time.
3. **Degrade to solo when a lane's quota is exhausted.** A 402/429/quota error on GLM or DeepSeek is a
   **downgrade, not a blocker**: log that the cross-vendor pass was skipped, continue with the
   same-vendor reviewer, and say so in the report. Never stall the task waiting on a rationed lane,
   and never silently drop the pass — an unrun check that reads as "reviewed" is worse than no check.
4. **Name the synthesis cost before you add a lane.** N lanes do not cost N model calls — they cost N
   calls **plus** reconciling N reports, which burns the orchestrator's frontier context (the scarcest
   thing in the session) **and** the human's attention on the write-up. So:
   - **Default cap: 3 lanes.** Above that, write the synthesis budget down first — who reconciles, on
     what model, and what the human is expected to read.
   - **Hard ceiling ~8**, and only for a one-off audit of a genuinely partitioned surface. The 8-lane
     migration audit that motivated these rules produced a 272-line report that still needed a human
     read and a main-thread re-verification of every HIGH finding. That tail is the real cost.
   - If you cannot say what you would *do differently* based on lane N's output, lane N is not worth
     running.
5. **Lanes advise; they do not write.** Fan-out agents are read-only — they return findings, the main
   thread applies them. This is the same rule as "agents never chain autonomously without review", and
   it is what keeps parallel lanes from clobbering each other.
6. **Verify high-severity findings in the main thread before acting.** A finding from a lane is a
   *claim*. Re-read the cited file/line yourself. Subagent reports are confidently wrong often enough
   that acting on an unverified HIGH is how fan-out turns into net-negative work.

### Running it — existing mechanisms only

Invent no new machinery. Everything needed already ships:

| Need | Use |
|---|---|
| Second opinion, same vendor, fresh context | `Agent` tool → `code-reviewer` / `security-analyst` / `anchor` / `preflight` |
| A different tier for one lane only | The `Agent` tool's `model:` override (per-agent; does not change the session model) |
| 2–4 lanes in parallel | Several `Agent` calls **in one message** — they run concurrently. This is enough; you do not need anything heavier. |
| Deterministic multi-stage orchestration (fan out over a discovered list, loop until dry, adversarial verify stages) | The `Workflow` tool — **only when the human explicitly asks for it**; it can spawn dozens of agents |
| Cross-vendor review of a diff | `/caddis:cross-review` (or `python .github/tools/oss_review.py --provider deepseek\|glm --range <range>`) |
| Cross-vendor opinion that needs to read the repo | `/glm <prompt>` or `/deepseek <prompt>` |
| Cross-vendor one-shot, no repo context | `/ask-glm` / `/ask-deepseek` |
| Per-phase model + lane assignment in a plan | `/caddis:feature-plan` — every phase already carries **Model**, **Lane**, and a cross-review provider |

**Reviewer rule (standing):** the reviewer is always a different vendor than whoever wrote the code.
Claude or GLM implemented → DeepSeek reviews (or swap). Never same-vendor.

Full command/billing decision table: `docs/guide/multi-model-workflow.md`.

---

## Anti-Patterns to Avoid

| ❌ Anti-Pattern | ✅ Instead |
|----------------|-----------|
| Fanning out because the task is *big* | Fan out for **risk**, not size — split a big mechanical task across sessions, not models |
| Spending a cross-vendor pass before the tests have run | Cheapest check first — deterministic gates decide it for free |
| One cross-vendor agent per area | One consolidated cross-vendor pass per task — the lane is rationed |
| Using DeepSeek/GLM for audit, research, or planning | Code-review lane only — they are unreliable outside it |
| Adding an Nth lane without budgeting the synthesis | Cap the lanes; reconciling N reports lands on you *and* the human |
| Acting on a subagent's HIGH finding as reported | Re-verify it in the main thread against the cited file/line first |
| Blocking the task when a rationed lane is out of quota | Degrade to solo, log the skipped pass, continue |
| Jumping straight to code without a plan | Triage → ADR (if needed) → Plan → Implement |
| Implementing all phases in one session | One phase per session — clean context, focused work |
| Letting agents edit the plan document | Only the Planner agent (or operator) edits plans |
| Ignoring mid-flight changes | Absorb changes into the plan before continuing |
| Skipping fidelity audit | Audit every plan — 0 gaps required |
| Committing without tests | Tests pass before every commit |
| Doing handoff chains instead of phased work | Use plan documents for large work, handoffs for emergencies |
| Building the fix-up list from memory | Debug Agent audits files systematically, catalogues issues |
| Trying to fix cross-component issues during implementation | Finish all phases first, then do a dedicated debug pass |

---

## Session Templates

### Starting a New Feature

```
Operator opens new chat:

"I have a feature spec in <file>. Let's use the Advisory Hub approach:
1. Read the spec
2. Triage quick wins (H1–H3)
3. Implement quick wins and commit
4. Then create a phased plan for remaining work

Load .github/skills/workflow/agent-orchestration/SKILL.md for the methodology."
```

### Continuing Implementation (Phase N)

```
Operator opens new chat:

"Read .github/plans/<feature>.md and implement Phase N.
Run pytest after each file change. Commit when all tests pass.
Use message: feat(<scope>): phase N — <summary>"
```

### Post-Implementation Debug

```
Operator opens new chat:

"All implementation phases for <feature> are complete.
Audit all changed files for cross-component issues.
Catalogue each issue (A–N) with root cause, fix, and acceptance criteria.
Write the fix-up plan to .github/plans/<feature>-fixup.md"
```

### Absorbing Mid-Flight Changes

```
Operator opens new chat:

"I independently added <change> to <file(s)>.
Read .github/plans/<feature>.md and update it to absorb this change.
Trace every affected step, update embedded prompts, re-verify fidelity."
```

---

## Checkpoints & Commit Discipline

Every stage that produces code changes should result in a commit:

| Stage | Commit Prefix | Example |
|-------|---------------|---------|
| Quick wins | `feat:` | `feat: H1–H3 quick wins — tooltip bands, CSS fix` |
| Plan + ADR (no code) | `docs:` | `docs: create implementation plan + ADR for <feature>` |
| Plan absorption | `docs:` | `docs: absorb SCORE_TOOLTIPS into plan — 16 edits` |
| Phase N | `feat(<scope>):` | `feat(cards): phase 2 — insight card refactoring` |
| Code review fixes | `fix:` | `fix(cards): address review feedback — null guard` |
| Debug polish | `fix:` | `fix(ui): post-track cross-component polish` |

---

## Measuring Success

A well-orchestrated session should produce:

- [ ] **Traceability** — Every spec requirement maps to a plan step, which maps to a commit
- [ ] **Green tests** — Full suite passing after every commit
- [ ] **Clean plan** — Fidelity audit: 0 gaps
- [ ] **Managed risks** — No showstoppers unresolved
- [ ] **Minimal rework** — Debug pass finds cosmetic issues, not fundamental errors
- [ ] **Session efficiency** — Clear context per session, no wasted tokens on re-discovery
- [ ] **Artefact trail** — Plan doc, ADR, prompts, commits, and fix-up plan all exist

---

## Integration with Other Skills

| Situation | Load This Skill |
|-----------|----------------|
| Session continuation context | `.github/skills/workflow/relay/SKILL.md` |
| Verifying code before committing | `.github/skills/workflow/verification-loop/SKILL.md` |
| Writing implementation plans | `.github/skills/docs/writing-plans/SKILL.md` |
| Running the cross-vendor review lane | `.github/skills/coding/cross-review/SKILL.md` |
| Creating new reusable skills | `.github/skills/workflow/skill-creator/SKILL.md` |
| Best practices reference | `.github/skills/workflow/best-practices/SKILL.md` |

---

## Reference: Real-World Example

The methodology in this document was extracted from a real multi-agent UI-polish delivery:

| Stage | Artefact | Outcome |
|-------|----------|---------|
| Triage | Commit `ad29844` | H1–H3 quick wins, 393 → 410 tests passing |
| ADR | Option B selected (score 4.1/5) | Micro-frontend hybrid for chat widget |
| Plan | 1035-line plan document | 5 phases, numbered steps, embedded prompts |
| Fidelity Audit | 0 gaps | All 470 lines of spec mapped |
| Risk Assessment | 6 risks, 0 showstoppers | All mitigated |
| Absorption | 16 plan edits | SCORE_TOOLTIPS model change integrated |
| Phases 1–5 | 5 commits | All tests passing per phase |
| Code Review | Clean pass | No issues found |
| Debug | 7 issues catalogued (A–G) | Fix-up plan created |

This end-to-end cycle took **~10 sessions** with full artefact trail and zero rework of fundamental design decisions.
