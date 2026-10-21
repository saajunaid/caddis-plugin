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
When the invocation contains the marker **`HEADLESS RUN RULES`**, **or `CADDIS_HEADLESS` is set in
the environment** (the caddis OSS launchers export it on claude's `-p`/`--print`) — a non-interactive
caller spawned this session and no human is present, so the scope-check questions and any interview are
**suspended and forbidden**. This mode exists for one-line ideas: the card may be a short title with **no
description**, and there may be **no codebase, PROJECT-FACTS, or prior PRD** to read. That is expected —
write a complete best-effort plan anyway.

Absolute rules in this mode (they override everything below):

> **The same policy exists in `/caddis:prd`, and the two are deliberately NOT identical.**
> Each is specialised to the artefact its command writes — where the output goes, and
> where an unresolved decision is recorded. **Do not merge them, and do not replace
> either with a pointer:** headless mode is precisely when no human is present and the
> session will not go and read another command to find its own rules.

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

**Check upstream first when the plan builds on Claude Code behaviour** (hooks, headless `claude -p`, permission
modes, subagents, worktrees, plugins and skills, Remote Control, background sessions). Read
`.caddis/kb/claude-code-upstream-watch.md` if the repo has it, and the latest Claude Code changelog for that area
(Improvements, Bug fixes, In development). Do not plan a fix or a workaround for something Claude Code has already
changed, fixed or announced; cite the release in **Constraints & decisions** instead.

### Evidence gate — do not write plan content while a BLOCKER is unresolved
This is the direct counter to the failure
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
`docs/guide/multi-model-workflow.md` (in the caddis **source** repo — `docs/` is not shipped inside the installed plugin); wiring: the caddis repo's `.caddis/plans/model-access.md`):
- **claude** (default) — this session, `/model <alias>` as above. Required for judgment-heavy,
  security-sensitive, or novel-architecture phases.
- **glm-headless** — mechanical, fully-specced phases run on GLM without touching Claude quota:
  `claude-glm -p "/caddis:implement <plan-path> — Phase N only"` (from the repo root, on the
  feature branch). The local-coder gate below exists exactly so these phases survive a weaker
  implementer — a phase may only take this lane if it passes that gate.
- **codex-sol / codex-astra / agy / glm (via caddis_lanes)** — select one of these five task types
  and its default chain:
  - `backend`: `glm`, `codex-sol`, `claude`
  - `hard`: `claude`, `codex-astra`
  - `ui`: `claude`, `codex-astra`
  - `tests`: `codex-sol`, `glm`, `claude`
  - `docs`: `agy`, `glm`, `claude`
  Use `python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.151/scripts/caddis_lanes.py" run --plan <plan-path> --phase N
  --type <type>` as the launch command. The chains are defaults, not limits on Claude: while Claude
  has budget, give any phase the `claude` lane. Override chains and model pins per project in
  `.caddis/config.toml` `[lanes.chains]` and `[lanes.models]`.

**Evidence standard — never plan a load test on a shared host.** Prove timing robustness with
event-driven fakes, ordering assertions and an A/B check that fails against the racy version. A phase
must never ask for CPU burners, stress tests, load tests or "every core". `caddis_lanes.py` refuses
this wording. The host guard kills runaway agent processes. On 2026-09-13, 32 all-core busy loops
froze CI on the dev box.

- **review lane (every phase that touches code)** — cross-vendor review by a vendor that did NOT
  write the code: `/caddis:cross-review --range main..HEAD`
  (Claude or GLM implemented) or `--provider glm` / a Claude `code-reviewer` pass (DeepSeek-adjacent
  work). Never same-vendor.

**The `Lane:` line is a routing directive read by `/caddis:implement`, not a note.** An interactive
session that is handed a phase belonging to another lane spawns that lane rather than absorbing the
work; a headless one records the deviation in the Tracker. Write the launch command out in full, per
phase — it is executed verbatim.

**Choose each phase's Lane from the routing table.** Run
`python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.151/scripts/caddis_routing.py" show --json`. A phase the orchestrator
does itself (verification, measurement, release judgement) uses the `critical` role. A phase whose
Implementer line says "light" uses `light`. Every other phase uses `coding`. Take the first model
of that role and write its Lane line as follows:

- `opus`: `claude — /model opus`
- `sonnet`: `claude — /model sonnet`
- `claude`: `claude — this session`
- `codex`: codex — `codex exec --ephemeral --sandbox workspace-write "HEADLESS RUN RULES. Read <plan path> and its Constraints. Implement Phase N only in the current checkout. Do not switch or create branches, commit, push, or edit files outside this phase. Run its exit gate and report the literal result."`
- `agy`: agy — `python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.151/scripts/caddis_spend.py" run --caller lane-pN -- agy --mode accept-edits --dangerously-skip-permissions --add-dir . --print-timeout 20m --output-format json -p "HEADLESS RUN RULES. Read <plan path> and its Constraints. Implement Phase N only in the current checkout. Do not switch or create branches, commit, push, or edit files outside this phase. Run its exit gate and report the literal result."`

Replace `<plan path>` and `N` (also in `lane-pN`) with this plan's path and phase number. The agy line
always starts with `caddis_spend.py run`: it books the call against the global EUR spend cap, and
`caddis_gate.py lane-check` refuses a bare `agy` Lane line. If the routing command fails
or exits 3, use `claude — this session` and state the reason in that phase.

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

### Group phases into MILESTONES — only when the plan is big enough
**Add milestones when the plan has ~8+ phases OR spans multiple sessions.** Below that, phases and a
Tracker are enough; a three-phase feature gains nothing from ceremony.

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
correctness-critical algorithm, an ambiguous spec, or an irreversible change. It selects no model and
implies no fan-out. It has one effect: the roadmap/plan runner reviews a finished `risk: high` phase
twice (`caddis_review.py --plan --phase --runs 2`), gives it one fix session on blocking
findings, and stops `BLOCKED review` when findings remain. Roadmap mode reviews before it publishes the PR. Do not emit orchestration, lane fan-out, or
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
**Type:** backend | hard | ui | tests | docs  *(required when the Lane runs through caddis_lanes.py)*
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
Three rules: one attempt, one review.
1. **Think before you send.** Before a task goes to any coder, write its edge cases and check the facts it depends on (one query or one file read).
2. **Run it before review.** The coder runs only the tests of the files it touched, in the foreground, each command under 10 minutes (split into parts if needed). Name the exact commands in the task. Never start the full suite in the background and never wait on a monitor for it: CI runs the full suite on every PR. Then run the change once on real data.
3. **Review by tier.** Run `python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.151/scripts/caddis_gate.py" review-tier --range <base>...HEAD` (add `--plan <plan> --phase <N>` inside a plan; no `TIER:` line means tier 2).
   Tier 0: gates only. Tier 1-small: your self-check only. Tier 1: one review by another vendor; stop at
   the first CLEAN. Tier 2: two reviewers of two other vendors, in one round. Fix blocking findings only;
   park the rest. Re-review only the fix diff, and only when the fix changed logic. After 3 rounds, ask the owner.

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
     One exception: when the session prompt says the runner reviews `risk: high` phases (the
     runner's `plan-resume-prompt.md` says so), the runner's review gate replaces this halt: the
     session ends `STATUS: CONTINUE`, and the runner reviews the phase twice before anything builds
     on it. A headless marker (`CADDIS_HEADLESS=1`) alone does not lift the halt.
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
- **Finish:** after the last phase, run `caddis_lanes.py finish --plan <plan>`; the plan is not done
  until it prints `LEFTOVERS: 0` (merged lane worktrees and branches removed, unmerged or dirty ones
  reported, feature branch pushed; merging to main stays with `/caddis:ship-merge`).
- **No load wording** — no phase asks for a CPU burner, stress test, load test or "every core"; prove
  timing by design.

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
- **Lane + reviewer named** — every phase names its execution lane (`claude`, `glm-headless`, or a
  `caddis_lanes.py` lane with its `**Type:**`, with the literal launch command for every non-claude
  phase) and a cross-review provider that is a different vendor than the implementer. A glm-headless
  phase MUST pass every bullet of this gate — that lane has no slack for reasoning out gaps.
- **Launch command is spawnable** — every `glm-headless` phase's command carries **`-p`** (or
  `--print`) and ends with **`— Phase N only`**. Both are load-bearing, not style: the launchers set
  `CADDIS_HEADLESS` *only* on `-p`, and that variable is the guard that stops a spawned session
  spawning another one forever; the `Phase N only` suffix is what stops the child running to the end
  of the plan. The command is executed verbatim by a model with no slack to notice a missing flag,
  and `/caddis:implement` now refuses a command without `-p` rather than running it.
- **caddis_lanes command carries --phase** — a `caddis_lanes.py` launch command must name `--phase N`
  and `--type`; lane-check refuses one without `--phase`.
- **Gate-detectable** — if this phase's instruction were WRONG, its exit gate would go red. A phase
  whose gates pass either way (copy, nav entries, badges, ordering, wording, config defaults) must
  not take a lane that cannot escalate, no matter how completely it is specified. Every other bullet
  here checks that the spec is COMPLETE; only this one checks that a mistake would be noticed.

If any phase relies on the implementer *reasoning out* a gap, close the gap in the plan now.

A `risk: high` phase gets two independent review runs: run by the roadmap/plan runner automatically (from caddis-next Phase 11), and by hand in an interactive `/caddis:implement` run (`caddis_review.py --plan <plan> --phase <n> --runs 2`, from Phase 10). Only a `blocking` finding fails that review (exit 1); `should-fix` and `nit` findings go on a follow-up list and do not stop the merge. A phase gets 3 completed review rounds (a run that did not complete uses none); the 4th ends with exit 5, "stop, the owner decides". The advisory hub is retired; do not plan a separate validation session.

## Programme triggers

Small work that does not meet a trigger skips its block.

**Trigger: Always.** Add one open-work row for the plan in `.caddis/open-work.md`. Set its cells with `python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.151/scripts/caddis_rows.py" set --file <open-work.md> --id <row id> --col Status=todo`, never with a regex edit.

**Trigger: The plan records a decision.** Record it with `/caddis:decide`.

## Step 4 — Report
Output the plan path (`.caddis/plans/<feature-slug>.md`), the phase list (one line each, with each
phase's model tier + lane), confirm the local-coder gate passed (or list the phases that need
tightening), and: *"To start: `read the plan and implement Phase 1`. To resume later: `/handoff` at
session end, then `read relay.md` next time. The plan's Execution protocol carries every command —
nothing to memorize."*

Do not start implementing — this command only produces the plan.
