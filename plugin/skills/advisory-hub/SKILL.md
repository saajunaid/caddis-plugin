---
name: advisory-hub
description: Cross-session phase validation for multi-phase implementation plans — a long-lived "Hub" session RE-DERIVES each implementation phase's claims independently instead of trusting its self-assessment. Use when the user says "advisory hub", "validate this phase", "phase report", "hub verdict", "advisory context", "who checks the implementing session", "the plan turned out to be wrong", "hand off the hub", "re-derive don't trust", or when a long, multi-session plan with expensive-to-reverse decisions (a migration, a security change, anything touching production data correctness) needs an independent session that verifies every phase before the next one starts. NOT for a three-phase feature — it costs a full extra session's context per phase, and a skill that doesn't say so gets applied everywhere and resented.
---

# Advisory Hub — cross-session phase validation

## The whole model, in four statements

> **1. Re-derive, don't trust — and re-derive DIFFERENTLY than the implementer did.**
> **2. Two roles, four files.** The implementer writes only the report. The Hub writes everything else.
> **3. The memory IS the switch.** `<plan-stem>-advisory-context.md` turns the mode on *and* is the
>    Hub's brain. An empty file buys a rubber stamp.
> **4. Nothing is fixed until it lands in the context doc.** A correction living in a verdict or a
>    chat dies with the session that wrote it.

### 1. The rule, and the correction to it

A phase report is a **self-assessment**. When it says *"VALUE CHECK passed: endpoint 11,126 = SQL
11,126,"* the Hub **runs the query itself**. A Hub that reads reports and nods is *worse than no Hub*
— it manufactures false confidence.

**But re-running a gate *identically* is not independent verification** — it reproduces the
implementer's blind spot. That cost a failed production deploy: implementer and Hub both ran the same
suite, both green, and CI then failed on a dependency-injection bug the gitignored local env file had
been masking. **For anything touching config, a data seam, or dependency injection, deprive the
environment:** `mv <env-file> aside && <test command> && mv back`.

### 2. Two roles, four files

| File | Written by | When | What is lost without it |
|---|---|---|---|
| `<plan-stem>-advisory-context.md` | scaffolded at planning; **owned and maintained by the Hub** | before | The Hub's memory — re-derivation access, locked decisions *and their non-obvious reasons*, the disproved-claims list. Nothing else survives a Hub crash or compaction |
| `.caddis/advisory-hub-reports/phase-NN.prompt.md` | **the Hub** | **BEFORE the phase runs** | What the implementer was *told*. Without it, "the implementer deviated" and "the plan was wrong" are both unfalsifiable |
| `.caddis/advisory-hub-reports/phase-NN.report.md` | the implementing session | after | The only evidence a phase's claims were ever checkable rather than merely asserted |
| `.caddis/advisory-hub-reports/phase-NN.verdict.md` | **the Hub** | after | A later reader sees a self-assessment and no evidence anyone checked it |

**Role separation is not decoration.** An implementer that writes its own verdict has produced a
self-assessment wearing a verdict's name — worse than no verdict, because it *looks* like a check
happened. Diligence is no substitute: an implementer can re-derive its own claims honestly and still
produce a worthless verdict.

Where a `phase-NN.prompt.md` exists it is **the instruction of record** — `/caddis:implement` reads it,
and deviations are measured against it, not against the plan alone.

### 3. The switch

`<plan-stem>-advisory-context.md`, beside the plan. `/caddis:implement`, `/caddis:handoff` and
`/caddis:validate-phase` all check for it. **No file → zero behaviour change, in every command, ever.**

Do not `touch` an empty one to "turn it on". The switch and the memory are deliberately the same file:
it should be structurally impossible to enable the Hub without giving it a brain.

**The verdict gates the next phase, by machine.** In Advisory-Hub mode, before starting phase N,
`/caddis:implement` requires `phase-(N-1).verdict.md` carrying `verdict: accept` or
`accept-with-correction`. Missing, or `reject` → stop and report `blocked-pending-hub`.

### 4. Corrections land structurally

Every correction the Hub issues must be asked: *where does this live so it cannot recur?* Telling the
implementing session is worthless — that session is closing. Putting it in the next phase's prompt
works exactly once. **Put it in the context doc**, where it binds every future phase whether or not
anyone remembers it. Each verdict therefore ends with *"what is now structural."*

Corollary: **feed the generic form back to this skill's parking lot.** Project facts stay in the
project; role mechanics come back here, or the skill never improves.

---

## When it earns its keep

**The cost is a full extra session's context, per phase.** Do not reach for this because it sounds
rigorous — reach for it when a mistake is expensive enough that the cost is cheap by comparison.

> **REQUIRED: the work is expensive to reverse** — a migration, a security change, production data
> correctness, or numbers published to stakeholders. **No stakes → no Hub, whatever else is true.**
>
> **PLUS at least one of:** the plan has **≥8 phases** · it is implemented across **sessions that will
> not share context**.

A three-phase feature hits none of this. `/caddis:feature-plan` Step 3b runs this test and **offers**;
it never creates the file silently. This is the test's only home — do not restate the thresholds
elsewhere, or the copies drift.

## The Hub is a ROLE, not a conversation

It outlives any one session and hands over through **files**, never chat history. Hand over with
`/caddis:spawn-hub` — at a milestone boundary, or sooner if context is filling.

**Your instinct that the context doc is current is measured-wrong.** Asked *"can we hand off?"*, an
outgoing Hub's honest first answer was yes; a mechanical audit then found **seven gaps** — including
that the single highest-value technique then in use was written down nowhere a fresh Hub would find it.

## Where the detail lives

Each file below is loaded by a **named command step**, at the moment it is needed. This is not optional
reading — it is deferred reading.

| Load this | For | Loaded by |
|---|---|---|
| `reference/context-template.md` | scaffolding or maintaining the context doc | `feature-plan` 3b · `validate-phase` 0 · `spawn-hub` 3 |
| `reference/report-contract.md` | filing a phase report | `implement`, at report time |
| `reference/hub-handbook.md` | validating a phase — verdict template, checklist, techniques, plan drift | `validate-phase` 2 |
| `reference/succession.md` | handing the role over — audit, self-check trap, carried-open ledger | `spawn-hub` · `handoff` 2b |

Naming, frontmatter and directory rules ship as an `AGENTS.md` **inside**
`.caddis/advisory-hub-reports/`, so they bind every agent that writes there — including agents that
never loaded this skill.

## Not to be confused with

`.github/prompts/advisory-hub.prompt.md` and `.github/instructions/advisory-mode.instructions.md` use
the same name for an older, unrelated Copilot chat-mode pipeline. It never ships to the Claude Code
plugin.

## Anti-patterns

- **Rubber-stamping.** A verdict with no re-derivation is not a verdict.
- **Re-running a gate the same way and calling it independent verification.** Change the environment.
- **An implementer writing its own verdict.** The roles exist for exactly this.
- **An empty context doc.** The switch *is* the memory.
- **Applying this to a short feature.** State the cost, every time, before adopting it.
- **A correction that lives only in a verdict file.** It dies with the session that wrote it.
