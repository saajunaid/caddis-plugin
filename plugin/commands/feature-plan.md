---
description: Create a phased, TDD-structured implementation plan that acts as the durable spine for multi-session work
argument-hint: <feature description>
---

# /feature-plan — phased plan (the durable spine)

Create an implementation plan for: **$ARGUMENTS**

If `$ARGUMENTS` is empty, ask what to plan and stop.

The plan file is the **durable spine of the harness** — it must let any future session (or another
agent, on any tool) resume with zero re-discovery. Optimize for that.

## Headless mode
When the invocation contains the marker **`HEADLESS RUN RULES`** (a docket runner / non-interactive
caller spawned this session — no human is present), the scope-check questions and any interview are
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
- **Honor the caller's output path and slug** (falling back to `.claudster/plans/<feature-slug>.md`);
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
Read the relevant code first (don't guess). **Ground in the workspace scan:** if `.claudster/PROJECT-FACTS.md`
exists (setup-project-ai extracts it — run/test/build commands, env-var names, CI/deploy workflows, entry
points), read it first. It's a free, token-zero project fingerprint that anchors the plan in what actually
exists instead of assumed. If the work fits comfortably in one session, say so and offer to just do it
instead of planning. Only produce a plan for genuinely multi-phase work.

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
`docs/guide/multi-model-workflow.md`; wiring: `.claudster/plans/model-access.md`):
- **claude** (default) — this session, `/model <alias>` as above. Required for judgment-heavy,
  security-sensitive, or novel-architecture phases.
- **glm-headless** — mechanical, fully-specced phases run on GLM without touching Claude quota:
  `claude-glm -p "/caddis:implement <plan-path> — Phase N only"` (from the repo root, on the
  feature branch). The local-coder gate below exists exactly so these phases survive a weaker
  implementer — a phase may only take this lane if it passes that gate.
- **review lane (every phase that touches code)** — cross-vendor review by a vendor that did NOT
  write the code: `python .github/tools/oss_review.py --range main..HEAD --provider deepseek`
  (Claude or GLM implemented) or `--provider glm` / a Claude `code-reviewer` pass (DeepSeek-adjacent
  work). Never same-vendor.

## Step 3 — Write the plan to `.claudster/plans/<feature-slug>.md`

Create `.claudster/plans/` if it doesn't exist.

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
**Model:** <tier> (`/model <alias>`) — <one-line rationale tied to this phase's difficulty>
**Lane:** claude — this session  |  glm-headless — `claude-glm -p "/caddis:implement <this plan's path> — Phase 1 only"`
**Session:** continue | **fresh** (start a new session for this phase — note why: lane change / heavy context)
**Goal:** <one sentence>
**Touches:** `<files>`
**TDD:**
  - RED: failing test(s) — `<test file>::<case>` asserting <behavior>
  - GREEN: <minimal implementation>
  - REFACTOR: <what to clean if needed>
**Verify (subagents):** dispatch `tester` (must return passed), then `code-reviewer` (verdict: approved)
**Cross-review:** `python .github/tools/oss_review.py --range main..HEAD --provider <vendor that did NOT implement>` → REVIEW: CLEAN
**Exit gate:** <specific, testable — e.g. "GET /api/x returns 200 with {shape}", not "tests pass">
**Commit:** `<conventional commit message>`
**Then:** update the Tracker row (status + hash) → `/caddis:handoff` if ending the session here.

### Phase 2 — <name>  🔲
<same structure>

## Execution protocol (standing rules — this plan is the memory, not anyone's head)
- One phase at a time: read this plan → run the phase on its **Lane** → RED→GREEN→VERIFY→CROSS-REVIEW→
  COMMIT → update the **Tracker** row. The Tracker is the resume signal for every future session.
- **Session boundaries:** `/caddis:handoff` after any phase that ends a sitting. Start a FRESH
  session (or `/clear`) before any phase marked `Session: fresh`, before a lane change, or whenever
  context feels heavy. Resume with exactly: `read <this plan's path> and implement the next ⏳ phase`.
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
| Phase | Model | Lane | Status | Commit | Cross-review | Notes |
|---|---|---|---|---|---|---|
| 1 | mid | claude | not started | — | — | |
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

If any phase relies on the implementer *reasoning out* a gap, close the gap in the plan now.

## Step 4 — Report
Output the plan path (`.claudster/plans/<feature-slug>.md`), the phase list (one line each, with each
phase's model tier + lane), confirm the local-coder gate passed (or list the phases that need
tightening), and: *"To start: `read the plan and implement Phase 1`. To resume later: `/handoff` at
session end, then `read relay.md` next time. The plan's Execution protocol carries every command —
nothing to memorize."*

Do not start implementing — this command only produces the plan.
