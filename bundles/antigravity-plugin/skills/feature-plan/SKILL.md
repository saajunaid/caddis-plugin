---
name: feature-plan
description: Create a phased, TDD-structured implementation plan that acts as the durable spine for multi-session work
---

# /feature-plan — phased plan (the durable spine)

Create an implementation plan for: **$ARGUMENTS**

If `$ARGUMENTS` is empty, ask what to plan and stop.

The plan file is the **durable spine of the harness** — it must let any future session (or another
agent, on any tool) resume with zero re-discovery. Optimize for that.

## Headless mode
When the invocation contains the marker **`HEADLESS RUN RULES`**, **or `CADDIS_HEADLESS` /
`DOCKET_PLAN` / `DOCKET_BRANCH` is set in the environment** (the caddis OSS launchers export
`CADDIS_HEADLESS` on claude's `-p`/`--print`; the docket runner sets the others) — a non-interactive
caller spawned this session and no human is present, so the scope-check questions and any interview are
**suspended and forbidden**. This mode exists for one-line ideas: the card may be a short title with **no
description**, and there may be **no codebase, PROJECT-FACTS, or prior PRD** to read. That is expected —
write a complete best-effort plan anyway.

Absolute rules in this mode (they override everything below):
- **NEVER ask a question, request clarification, or end your turn with questions.** Replying with a list
  of scoping questions is a hard failure. Never use AskUserQuestion, never pause, never wait for input.
- **A bare title (or PRD path) is sufficient input.** Where information is missing, invent a reasonable,
  conventional interpretation, state it explicitly as an assumption in `## Constraints & decisions`, and
  proceed. Making an explicit assumption is ALWAYS correct; asking is ALWAYS wrong here. If you feel you
  lack information, **write an assumption and continue** — never ask.
- **Every unresolved decision becomes an `[TECH-DECISION OPEN]` note** (inline in the relevant phase) or
  a bullet under `## Constraints & decisions` — never a question to the user.
- **Honor the caller's output path and slug** (falling back to `.caddis/plans/<feature-slug>.md`);
  set `feature: <slug>` in the frontmatter to that slug.
- **Also emit a visual companion** — a self-contained, scannable HTML page at `<artifact_dir>/<slug>.html`
  presenting the plan visually (a goal card, phases as cards with their steps, an affected-files table,
  and a risks/decisions section). **Use inline `<style>` ONLY** — the visual is rendered in a *sandboxed*
  iframe with no script execution, so a `<script>`/CDN (e.g. the Tailwind browser CDN) would NOT run and
  the page would appear unstyled. Keep it fully portable — no external `<script>`/`<link>`, no local
  asset files, no `/`-rooted paths. This is the visual the human reviews in docket alongside the markdown.
  Write it after the `.md`; the runner finds it by the matching `<slug>.html` name.
- **Always write the plan file, then end with exactly one fenced `json` highlights block** — nothing
  after it:
  ```json
  {"artifact":"<artifact_dir>/<slug>.md","summary":"<=280 chars>","open_questions":<int>}
  ```

The only acceptable final output in this mode is the written plan plus its highlights block — never
questions. Everything below applies in both modes; only the interview/scope questions are skipped.

## Step 1 — Scope check
Read the relevant code first (don't guess). **Ground in the workspace scan:** if `.caddis/PROJECT-FACTS.md`
exists (setup-project-ai extracts it — run/test/build commands, env-var names, CI/deploy workflows, entry
points), read it first. It's a free, token-zero project fingerprint that anchors the plan in what actually
exists instead of assumed. If the work fits comfortably in one session, say so and offer to just do it
instead of planning. Only produce a plan for genuinely multi-phase work.

### Evidence gate — do not write plan content while a BLOCKER is unresolved
Absorbed from `golden-plan`, whose strongest idea this is, and the direct counter to the failure
mode that makes a plan dangerous: **you write the spec, so you cannot see its gaps.** A phase built
on guessed field names or an imagined API is confidently wrong, passes every completeness check,
and only fails at the exit gate — or worse, doesn't.

Before writing any phase, tier each item:
- **BLOCKER** — stop and ask the user. Do not plan around it.
- **WARNING** — proceed, but the affected phases carry a stated assumption.
- **OPTIONAL** — note its absence and continue.

| # | Evidence | Tier |
|---|---|---|
| E1 | A mockup / wireframe / screenshot of the target UI, and is it frozen? | BLOCKER for UI-heavy work, WARNING otherwise |
| E2 | A real data sample on the CURRENT schema, so field names are read not guessed | BLOCKER for any data binding, WARNING if a typed DTO/interface defines it |
| E3 | The API contract for anything you will call — real request/response shapes | BLOCKER when integrating something you did not write |
| E4 | Scaffold inventory: what already exists that these phases must fit into | WARNING — `.caddis/PROJECT-FACTS.md` fills this for free if present |

**Free head-start:** `.caddis/PROJECT-FACTS.md` pre-fills E4 plus the run/test/build commands, env-var
names and CI workflows at zero token cost — and grounds the `## Risks` table in what the scan actually
shows rather than boilerplate.

**If a PRD exists for this feature, read it FIRST.** Look for `.caddis/prd/<feature-slug>.md`.
`/caddis:prd` ends by suggesting `/feature-plan <feature>`, and until now nothing on this side ever
opened the file — so the whole chain's first handoff depended on the model happening to look. Carry
its functional requirements into phases (they are written *"so a test can verify it"*, which is
exactly what a phase's exit gate needs) and its `## Open questions` into `## Constraints & decisions`.
A headless pipeline that plans straight from a bare title while a complete PRD sits on disk is the
failure this closes.

## Step 2 — Design phases
Break the work into **independently completable** phases (~30–60 min each, clear exit gate). Each phase
follows the harness loop: **RED → GREEN → REFACTOR → VERIFY → COMMIT**. Front-load risk.

**Derive risks from the workspace scan** (PROJECT-FACTS + a quick look), not generic boilerplate: **no test
setup** → every phase carries regression risk, build its tests first; **no CI/deploy workflow** → the only
gate is local, say so; **auth / migration / secret-handling** in scope → flag security/structural risk on
those phases. Put what the scan actually shows into the plan's `## Risks` table.

Before writing the plan, consider dispatching the **preflight** subagent to validate your assumptions
(paths, symbols, APIs, primitives) against the codebase — it routinely catches wrong assumptions early.

### Assign a model tier + effort per phase (don't default everything to the priciest)
Match capability to each phase's difficulty — not one model for the whole plan. Use Claude Code's
evergreen `/model` aliases so this never rots as model names change:
- **cheap** (`/model haiku`) — mechanical, fully-specced, repeat-of-an-existing-pattern phases.
- **mid** (`/model sonnet`) — standard feature work with clear specs. **This is the default.**
- **frontier** (`/model opus`) — novel architecture, tricky algorithms, security-sensitive or
  judgment-heavy seams; also recommend a `code-reviewer` pass.
- **ultra** (`/model fable`) — RARE: long-horizon / multi-step / can't-self-verify work (large-codebase
  reasoning, scientific). ~2× opus's rate-limit burn — reserve for the few phases that truly need it.
Default to **mid**; reserve frontier/ultra for phases that earn them. Effort is a secondary knob: leave
it at your session default and note **"bump to `high`"** only on a genuinely hard phase. `max` is manual
escalation, never a planned default.

### Assign an execution LANE per phase (which harness runs it — not just which model)
A tier can be served by an OSS provider instead of Anthropic (cheat sheet:
`docs/guide/multi-model-workflow.md`; wiring: the caddis repo's `.caddis/plans/model-access.md`):
- **claude** (default) — this session, `/model <alias>` as above. Required for judgment-heavy,
  security-sensitive, or novel-architecture phases.
- **glm-headless** — mechanical, fully-specced phases run on GLM without touching Claude quota:
  `claude-glm -p "/caddis:implement <plan-path> — Phase N only"` (from the repo root, on the
  feature branch). The local-coder gate below exists exactly so these phases survive a weaker
  implementer — a phase may only take this lane if it passes that gate.
- **review lane (every phase that touches code)** — cross-vendor review by a vendor that did NOT
  write the code: `/caddis:cross-review --range main..HEAD`
  (Claude or GLM implemented) or `--provider glm` / a Claude `code-reviewer` pass (DeepSeek-adjacent
  work). Never same-vendor.

**The `Lane:` line is a routing directive read by `/caddis:implement`, not a note.** An interactive
session that is handed a phase belonging to another lane spawns that lane rather than absorbing the
work; a headless one records the deviation in the Tracker. Write the launch command out in full, per
phase — it is executed verbatim.

#### A phase may take a no-escalation lane only if its exit gate would fail on a spec error
`glm-headless` cannot escalate: it does what the phase says. So completeness is only half the test —
the other half is whether being **wrong** would be caught. Ask literally: *"if the instruction I just
wrote were wrong, would this phase's exit gate go red?"*
- **Yes** → pure logic with literal assertions: a parser, a computed value, an API shape assertion
  (*"`expected_slots` returns exactly 96 and 1440"*). Safe for a no-escalation lane.
- **No** → user-facing copy, nav/menu entries, status or badge flags, ordering, wording, config
  defaults — anything whose only proof is a human looking at it. **Not safe, however completely it
  is specified.**

This is the failure the completeness gate cannot see, because **you wrote the spec**: if you could
see the gap you would have filled it. Live case — a phase spelled out to 10 literal steps across 8
files passed every bullet of the local-coder gate, and the spec itself was wrong twice (it shipped an
internal repo path into stakeholder-facing copy, and set a `live` status flag that suppressed the
framework's own "Soon" badge). `tsc` clean, 632/632 tests green, cross-review CLEAN, exit gate
satisfied. A headless run following it literally would have committed both, entirely green.

In an Advisory-Hub plan, treat your lane as **provisional**: the Hub writes each `phase-NN.prompt.md`
before the phase runs, and that is the first time anyone but the spec's author reads it. Let that
read confirm or downgrade the lane. It costs nothing — the prompt is being written anyway.

### Group phases into MILESTONES — only when the plan is big enough
**Add milestones when the plan has ~8+ phases OR spans multiple sessions.** Below that, phases and a
Tracker are enough; a three-phase feature gains nothing from ceremony. (Same sizing instinct as the
Advisory-Hub test, deliberately — one threshold to remember, not two.)

A milestone is **a group of phases that ship together**. It answers "what lands when this is done?",
which is the question a long plan otherwise leaves the executor guessing at.

```markdown
### Milestone M2 — <name>  (phases 4-7)
**Ships:** <what actually lands — a version, a PR, a deploy>
**Gate:** <the check that must pass before it ships>
**Boundary:** handoff + fresh session before M3
```

Then give every phase a `**Milestone:** M2` line and add a `Milestone` column to the Tracker, so a
resuming session can see at a glance which group it is in and what remains before the next ship.

### Flag high-risk phases (`risk:` — a marker, not a mechanism)
Each phase may carry **`risk: normal|high`** (default `normal` — omit the line unless the phase is
`high`), meaning only "this is a phase where a wrong answer is expensive" — security/authz, a
correctness-critical algorithm, an ambiguous spec, or an irreversible change. It is **inert**: it
selects no model, spawns no agents, and implies no fan-out — it exists so the executor can decide **at
runtime** whether an extra cross-check is worth it. Do not emit orchestration, lane fan-out, or
`Workflow` scripts from this command; the runtime decision rules and the intent→model map live in one
place, the `agent-orchestration` skill's *Multi-model fan-out* section.

## Step 3 — Write the plan to `.caddis/plans/<feature-slug>.md`

Create `.caddis/plans/` if it doesn't exist.

```markdown
---
type: plan
status: draft
feature: <feature-slug>
creation-agent: caddis
Original Author: Claude Code
Creation Date: <YYYY-MM-DDTHH:MM:SSZ>
Creating Model: <model-id>
---

# <Feature> — Implementation Plan
**Created:** <ISO date>  •  **Status:** Phase 1 of N  •  **Spine for:** <one-line goal>

## Goal
<2–3 sentences: what we're building and why.>

## Current state
<What exists now that's relevant — cite real files/symbols verified against the codebase.>

## Constraints & decisions
- <key tech decision + rationale>

## Phases

### Phase 1 — <name>  ⏳
> ⚠️ **Switch model/lane BEFORE starting this phase** — the *active* model does the work, not the
> one named here. Lane `claude`: run `/model <alias>`. Lane `glm-headless`: run the exact command below.
**Milestone:** M1  *(omit on plans without milestones)*
**Model:** <tier> (`/model <alias>`) — <one-line rationale tied to this phase's difficulty>
**Lane:** claude — this session  |  glm-headless — `claude-glm -p "/caddis:implement <this plan's path> — Phase 1 only"`
**Session:** continue | **fresh** (start a new session for this phase — note why: lane change / heavy context)
**Risk:** high — token-verification seam; a wrong answer here is a silent auth bypass  *(omit this line when normal)*
**Goal:** <one sentence>
**Touches:** `<files>`
**TDD:**
  - RED: failing test(s) — `<test file>::<case>` asserting <behavior>
  - GREEN: <minimal implementation>
  - REFACTOR: <what to clean if needed>
**Verify (subagents):** dispatch `tester` (must return passed), then `code-reviewer` (verdict: approved)
**Cross-review:** `/caddis:cross-review --range main..HEAD` → REVIEW: CLEAN
**Exit gate:** <specific, testable — e.g. "GET /api/x returns 200 with {shape}", not "tests pass">
**Commit:** `<conventional commit message>`
**Then:** update the Tracker row (status + hash). If this phase ends the session, WRITE the handoff
yourself (relay + Tracker) before stopping — do not hand back "run `/caddis:handoff`" as the next action.

### Phase 2 — <name>  🔲
<same structure>

## Execution protocol (standing rules — this plan is the memory, not anyone's head)
- One phase at a time: read this plan → run the phase on its **Lane** → RED→GREEN→VERIFY→CROSS-REVIEW→
  COMMIT → update the **Tracker** row. The Tracker is the resume signal for every future session.
- **Session boundaries:** the executor WRITES the handoff (durable `relay.md` + Tracker) after any
  phase that ends a sitting — it performs the work, it does not suggest the command. Start a FRESH
  session (or `/clear`) before any phase marked `Session: fresh`, before a lane change, or whenever
  context feels heavy. Resume with exactly: `read <this plan's path> and implement the next ⏳ phase`.
- **Run to a boundary, not to a phase.** The executor implements phase after phase, committing each,
  and stops only at a marked boundary. Do not plan a stop after every phase — that is the friction
  this structure exists to remove.
- **The four halts, and nothing else:**
  1. **A milestone boundary** — its `Gate:` passed and it is ready to ship.
  2. **A phase marked `Session: fresh`** — context is heavy or the work changes shape.
  3. **After a `risk: high` phase** — *after*, never before. The phase is executed and committed
     normally; the halt stops anything being **built on top of it** before a human has looked. Blast
     radius stays one reviewable, revertable commit. Halting *beforehand* buys nothing: the phase has
     to be executed either way, and a well-specced high-risk phase is as executable as any other.
  4. **A failed or blocked phase** — tests red, exit gate unmet, or the plan turned out wrong. Stop;
     do not build on it.
- **A lane change is NOT a halt.** `/caddis:implement` spawns the assigned lane itself and verifies
  the result. It used to need a human only because the routing was inert.
- **At every halt, leave both:** the executor PERFORMS the handoff (writes `relay.md`, updates the
  Tracker) and then prints the **halt block** — the single thing the human acts on. A next action of
  "do a handoff" / "update the relay" is a DEFECT, not a handoff: it names the work instead of doing
  it, and the context needed to do it is gone the moment the session ends:
  ```
  === HALT — <one-line reason> ===
  Done:    phases 4-7 (M2) · commits <sha>, <sha>
  Blocked: <what, or "nothing">
  You:     /clear, then paste ↓
           read <plan path> and implement Phase 8
  ```
  A run that trails off without this costs a human the work of reconstructing where it got to.
- **Ship gate:** NEVER push or merge to main from a phase — phases only commit to the feature branch.
  When all phases are ✅: `/caddis:ship-pr` (stops at green CI), then STOP and wait for the human's
  explicit go before `/caddis:ship-merge`.

## Affected files
| File | Action |
|---|---|

## Risks
| Risk | Mitigation |
|---|---|

## Tracker (update as you go — this is the resume signal)
| Phase | Milestone | Model | Lane | Status | Commit | Cross-review | Notes |
|---|---|---|---|---|---|---|---|
| 1 | M1 | mid | claude | not started | — | — | |
```

## Plan quality gate — local-coder ready (MANDATORY)
The plan must be executable by a **low-capability local coder model** (the planner→coder handoff: a
strong model plans, a cheaper/local model implements). The plan carries the intelligence; the coder
only follows it. Before finishing, verify every phase against this gate — a phase that fails it is not
done:
- **Exact paths** — every file to create/edit is named in full (no "the relevant service file").
- **Exact symbols** — function/class/component names and signatures are spelled out, not described.
- **Pre-decided judgment** — no "choose an approach", "use a suitable library", or open options left to
  the coder. If there's a decision, make it here with the rationale.
- **Explicit data bindings** — exact field paths / response shapes the code must read or produce.
- **Copy-paste verification** — each phase's exit gate is a literal command to run + expected output,
  not "tests pass".
- **No abbreviation** — never "etc.", "similar to Phase 1", "and so on". Write every item in full.
- **Model tier named** — every phase names a tier (cheap/mid/frontier/ultra) + a one-line rationale; no
  phase silently defaults to the most expensive model. Default mid; frontier/ultra only where justified.
- **Lane + reviewer named** — every phase names its execution lane (`claude` or `glm-headless`, with
  the literal launch command for glm phases) and a cross-review provider that is a different vendor
  than the implementer. A glm-headless phase MUST pass every bullet of this gate — that lane has no
  slack for reasoning out gaps.
- **Launch command is spawnable** — every `glm-headless` phase's command carries **`-p`** (or
  `--print`) and ends with **`— Phase N only`**. Both are load-bearing, not style: the launchers set
  `CADDIS_HEADLESS` *only* on `-p`, and that variable is the guard that stops a spawned session
  spawning another one forever; the `Phase N only` suffix is what stops the child running to the end
  of the plan. The command is executed verbatim by a model with no slack to notice a missing flag,
  and `/caddis:implement` now refuses a command without `-p` rather than running it.
- **Gate-detectable** — if this phase's instruction were WRONG, its exit gate would go red. A phase
  whose gates pass either way (copy, nav entries, badges, ordering, wording, config defaults) must
  not take a lane that cannot escalate, no matter how completely it is specified. Every other bullet
  here checks that the spec is COMPLETE; only this one checks that a mistake would be noticed.

If any phase relies on the implementer *reasoning out* a gap, close the gap in the plan now.

## Step 3b — Does this plan need an Advisory Hub? (ask once, here)

The Advisory Hub is **opt-in per plan**, gated on a single file: `<plan-stem>-advisory-context.md`
beside the plan. `/caddis:implement`, `/caddis:handoff` and `/caddis:validate-phase` all check for it;
**no file → no behaviour change, ever.** But nothing has ever *asked* whether to create it, so the
pattern only ever gets used by someone who already knows it exists. This step closes that gap.

**Ask it here** — at the end of planning is the only moment the phase count, risk levels and session
boundaries are all known.

> **You MUST call `Skill(advisory-hub)` and read *"When it earns its keep"* before deciding.**
> Do not decide from memory, and do not decide from any summary — including one in this file.
> The test is stated in exactly one place on purpose: two copies of a rule drift on the first edit,
> and the copy that used to live here had already drifted. It compressed the REQUIRED leg to the
> phrase *"expensive-to-reverse"* and dropped the enumeration that defines it — which reads as
> *"can I `git revert` this?"*, and under that reading a plan that publishes € figures to business
> stakeholders scores "no stakes". That is the one leg that fires on reporting, analytics and
> dashboard work, i.e. most of what this fleet builds. Load the skill.

If the test passes, tell the user plainly what it costs and what it buys, and offer to scaffold the
context doc from the `advisory-hub` skill's template. **Do not create it silently** — an opt-in
pattern that switches itself on is no longer opt-in.

**In headless mode, never offer and never create.** Headless forbids asking anything, so an "offer"
is impossible there. Instead record the result as a line under `## Constraints & decisions` —
*"Advisory Hub: test passed (N phases, <criteria>) — not scaffolded, headless run; create
`<plan-stem>-advisory-context.md` to enable"* — so the decision reaches a human rather than being
silently dropped or silently taken.

If it does not pass, say nothing **to the user** — a three-phase feature should never hear about
this. But **always record the determination in the plan, pass or fail**: one line under
`## Constraints & decisions`, naming which REQUIRED trigger was or was not hit.

> `Advisory Hub: not applicable — no REQUIRED trigger (not a migration / security change /
> production data correctness / numbers published to stakeholders).`

Silent to the human, auditable in the artifact. "Say nothing" once meant *leave no trace anywhere*,
and a wrong negative was then invisible — no line in the plan, no line in the chat, nothing for
anyone to challenge. A rule whose failures leave no artifact cannot be reviewed.

## Step 4 — Report
Output the plan path (`.caddis/plans/<feature-slug>.md`), the phase list (one line each, with each
phase's model tier + lane), confirm the local-coder gate passed (or list the phases that need
tightening), and: *"To start: `read the plan and implement Phase 1`. To resume later: `/handoff` at
session end, then `read relay.md` next time. The plan's Execution protocol carries every command —
nothing to memorize."*

Do not start implementing — this command only produces the plan.
