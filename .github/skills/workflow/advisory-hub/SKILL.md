---
name: advisory-hub
description: Cross-session phase validation for multi-phase implementation plans — a long-lived "Hub" session RE-DERIVES each implementation phase's claims independently instead of trusting its self-assessment. Use when the user says "advisory hub", "validate this phase", "phase report", "hub verdict", "advisory context", "who checks the implementing session", "the plan turned out to be wrong", "hand off the hub", "re-derive don't trust", or when a long, multi-session plan with expensive-to-reverse decisions (a migration, a security change, anything touching production data correctness) needs an independent session that verifies every phase before the next one starts. NOT for a three-phase feature — it costs a full extra session's context per phase, and a skill that doesn't say so gets applied everywhere and resented.
---

# Advisory Hub — cross-session phase validation

> **THE RULE: re-derive, do not trust.**
>
> When a phase reports *"VALUE CHECK passed: endpoint returned 11,126, SQL returned 11,126,"* the Hub
> **runs the query itself.** A phase report is a self-assessment. Accepting it at face value makes the
> Hub a rubber stamp — and a Hub that reads reports and nods is *worse than no Hub*, because it
> manufactures false confidence. Everything else in this skill is scaffolding around that one rule.

## Not to be confused with

`.github/prompts/advisory-hub.prompt.md` and `.github/instructions/advisory-mode.instructions.md` use
the same name for an older, unrelated concept — a VS Code Copilot/GPT chat-mode pipeline where a
**human** orchestrates six stages (Triage → ADR → Plan → Absorb → Execute → Review) across named
Copilot agents via `pipeline-state.json`. That pipeline is Copilot-only tooling; it never ships to the
Claude Code plugin. This skill is a different mechanism entirely: an autonomous Claude Code
**cross-session** pattern where a long-lived session validates disposable implementation sessions, one
phase at a time.

## When it earns its keep

**Worth it:** long multi-session work with expensive-to-reverse decisions — a migration, a security
change, anything touching production data correctness. A fresh Hub session, reconstituted from an
`advisory-context.md` file with **zero conversation history**, has caught a real production bug that an
implementing session's own two independent cross-review passes had both missed — by refusing to trust
the report's own "CLEAN" and switching cross-review provider when the first one timed out rather than
recording "inconclusive."

**Overkill:** a three-phase feature. **The cost is real and worth saying plainly: a full extra session's
context, per phase.** Do not reach for this because it sounds rigorous — reach for it because the
decisions are expensive enough to reverse that the cost is cheap insurance by comparison.

## The five artifacts

| File | Who writes it | Committed? | What is lost without it |
|---|---|---|---|
| `<slug>.md` (the plan) | the planning session | yes | — |
| `<slug>-advisory-context.md` | the Hub | **yes** | Nothing else can carry re-derivation access, locked-decision reasons, or a disproved-claims list across a Hub crash/compaction |
| `.caddis/advisory-hub-reports/phase-NN-<slug>.md` | the implementing session | **yes** | The only evidence that a phase's claims were ever checkable, not just asserted |
| `.caddis/advisory-hub-reports/phase-NN-hub-verdict.md` | the Hub | **yes** | Without it a later reader sees a self-assessment and no evidence anyone verified it |
| `.caddis/advisory-hub-reports/README.md` | the Hub (updated per phase) | yes | An index — which phase, which verdict, when |

**Why not just use `.caddis/relay.md`?** Relay is **gitignored and overwritten by every
`/caddis:handoff`** — it is a pointer for resuming *one* session, not a durable record. The whole reason
`advisory-context.md` exists is that relay cannot hold state across the Hub's entire lifetime.

**The existence of `<slug>-advisory-context.md` beside a plan is the gate flag.** `/caddis:implement` and
`/caddis:handoff` both check for this exact file to decide whether Advisory-Hub mode is on for that plan.
No file → no behavior change, in either command, ever. This is intentional: the pattern is opt-in per
plan, never ambient.

---

## §A — the `advisory-context.md` template

Copy this in full when you (the Hub) start guarding a new plan. It is a **committed** peer of the plan,
not of `relay.md`.

````markdown
---
type: advisory-context
status: active
feature: <slug>
Original Author: <human or agent>
Creation Date: <ISO 8601 UTC>
Creating Model: <model/lane>
---

# Advisory Context — <Feature Name>

**Companion to `<path to the plan>`.** The plan says *what to build*. This says *why it is shaped that
way, what was measured, and what has already been disproved* — the things a reader of the plan alone
would re-litigate.

**Who this is for:** the **Advisory Hub** — the long-lived session that validates each implementation
phase. If the Hub session dies or compacts, a new one is reconstituted from: this file → the plan → the
project's own rules file (`AGENTS.md`). Nothing else is required.

---

## 1. The Hub's job, and its one rule

Implementation sessions run phases and report. The Hub **validates**.

> **THE RULE: re-derive, do not trust.** A phase report is a self-assessment; accepting it at face value
> makes the Hub a rubber stamp.

The Hub's verdict is one of:
- **ACCEPT** — re-derived numbers match; gates genuinely ran; move to the next phase.
- **ACCEPT WITH CORRECTION** — work is sound but something is wrong or missing; the Hub states the exact
  fix and it lands before the next phase.
- **REJECT** — a gate was skipped, a number does not reproduce, or a locked decision was violated. The
  phase is redone.

The Hub also protects the plan from drift (§6 below) — a deviation from a locked decision (§4) is a
*Hub* decision, never the implementer's.

---

## 2. Baseline state as of <date>

The state every validation starts from — anything that changed out-of-band, before Phase 0/1 ran, that a
fresh Hub needs to know about (environment changes, migrations already applied, services restarted).

---

## 3. The measured facts (re-derivable — do not accept a contradiction without re-measuring)

### 3a. RE-DERIVATION ACCESS

The literal, copy-pasteable command (or script, query, API call, test invocation) that reproduces this
plan's anchor numbers from this repo, and roughly how long it takes. **The Hub's one rule is unaffordable
without this** — if reproducing a number takes twenty minutes of setup, the Hub will quietly stop doing
it. Include every environment prerequisite; nothing here should require reconstruction.

### 3b. The anchor numbers

| Fact | Value |
|---|---|
| <the numbers the plan's claims will be checked against> | |

### 3c. The findings that shaped the plan most

<the 1-3 measured findings that most determined the plan's shape, and why no simpler approach works>

---

## 4. Locked decisions — an implementer may not change these unilaterally

| # | Decision | The reason that is NOT obvious from the plan |
|---|---|---|
| D1 | | |

---

## 5. Project safety conventions this Hub enforces

If this project's rules file (`AGENTS.md`/`CLAUDE.md`) or its docs declare standing correctness
conventions that a phase could silently violate, list them here with an id, a one-line statement, and
**the check that proves compliance**. The phase report carries a slot per rule; the Hub re-checks each.
**If this project declares none, write `NONE DECLARED`** — both the report section and the Hub's
re-check become `N/A`, and this costs nothing.

| Rule id | What it requires | The check that proves it | Scope (docs only, or `src/` too) |
|---|---|---|---|

*Worked example — a project that computes rates or percentages typically declares something like: every
rate-bearing field must name its population, must carry its coverage denominator, and must have a
nested-subset test that would actually fail if the denominator drifted. Other common shapes: a
date-window boundary convention; a required migration-reversibility check; a mandatory secret-scan on any
config change.* This section exists because the Hub's core distrust — re-derive, don't trust — applies to
process as much as to arithmetic; where a project has already codified that distrust as a rule, the Hub
enforces it every phase rather than hoping the implementer remembered.

---

## 6. Already disproved — do not re-raise

| Claim | Status |
|---|---|
| <a claim two reviewers independently raised, that a live check settled as false> | **FALSE** — <the evidence> |

A Hub without this memory reopens the same false blocker every phase a new reviewer raises it.

---

## 7. The phase report contract

Canonical definition: the `advisory-hub` skill's §B. This project's local additions (if any) and the
specific failures that earned them:

<none yet, or list them here as they're discovered>

---

## 8. Standing gotchas that bite every phase

<durable, non-obvious rules a fresh implementing session needs and would not discover from the code>

---

## 9. Hub techniques that actually caught something here

<which of §E's techniques (mutation testing, re-running cross-review, reading the copy) found a real
problem on this plan, and what it found>

---

## 10. Environment facts a fresh Hub will not otherwise know

| Fact | Why it matters |
|---|---|

---

## 11. Gotchas discovered while implementing (not in the plan)

<implementation-time surprises worth a durable rule, even though the plan didn't anticipate them>

---

## 12. Hub self-handoff — the mechanical audit is mandatory, not optional

This file exists so a fresh Hub session can take over without the conversation. That only works if it
stays current — and the outgoing Hub's instinct is always "yes, this is ready," because it's judging
against its own memory of the session, not against this document. **That instinct is wrong by default.**
Run the audit in §G before every handoff; do not skip it because the file "looks current."

---

## Changelog
- **<date>** — created.
````

**Why this file, not the plan:** a fresh session has the plan but not the *why* — and will re-litigate
settled questions. §4's *reason* column is the load-bearing part; the decision alone invites a second
reviewer to reopen it. §6 exists because on the reference implementation of this pattern, two independent
cross-review models both raised the same blocker — only a live probe closed it, and a Hub without that
memory would have reopened it every subsequent phase. §3a is kept separate from §3b because the numbers
are worthless if a future Hub can't cheaply reproduce them.

---

## §B — the phase report contract

Every implementation phase, in Advisory-Hub mode, ends by writing this block **to a file**
(`.caddis/advisory-hub-reports/phase-NN-<slug>.md`), never just to chat. **A report without re-derivable
evidence is not a report.**

```
=== PHASE REPORT FOR ADVISORY HUB ===
PLAN:          <path to the plan file>
ADVISORY CTX:  <path to <slug>-advisory-context.md>
PHASE:         <n> — <title>
MILESTONE:     <M<n>, or N/A>
MODEL/LANE:    <tier> / <lane>              (the model you ACTUALLY ran on)
DATE:          <ISO 8601 UTC>
STATUS:        COMPLETE | BLOCKED | PARTIAL

--- COMMITS ---
<sha> <subject>                             (one line per commit — including tooling,
                                              config, and non-source files)
FILES CHANGED: <n> (+<added>/-<removed>)

--- EXIT GATE: verbatim command + verbatim output ---
$ <the literal command the plan names>
<paste the real terminal output — do not summarise, retype, or tidy it>
RESULT: PASS | FAIL                          (repeat this triple per gate)

--- VALUE CHECK ---
CLAIM:                   <the number or behaviour this phase asserts>
RE-DERIVED BY:            <the exact independent query/command/script — copy-pasteable,
                          not a description of one>
RE-DERIVATION RETURNED:  <what it actually returned>
MATCH:                   YES | NO

--- PROJECT SAFETY RULES ---
RULES IN SCOPE: <rule ids from advisory-context §5, or NONE DECLARED>
RULE <id>:  APPLIES THIS PHASE: YES | NO — <why>
            EVIDENCE: <the check that was run + its output, or N/A>
            RESULT: PASS | FAIL | N/A          (repeat per rule)

--- CROSS-REVIEW ---
PROVIDER: <deepseek | glm | …>   VERDICT: CLEAN | ISSUES | NOT RUN (+ why)
ISSUES ADDRESSED: <list, or NONE>

--- DEVIATIONS FROM PLAN ---
<each deviation + why, or NONE>

--- SURPRISES / CONTRADICTIONS ---
<anything the real data or code contradicted in the plan's `## Current state`, or NONE>
<<< STOP CONDITION: if this section is non-empty, STOP after this phase.
    The Hub owns the plan correction — you do not. >>>

--- NOT DONE ---
<anything in the phase left undone + why, or NONE>

--- NEXT PHASE READY: YES | NO ---
=== END REPORT ===
```

### Non-negotiables for the report itself — each earned by a real failure

- **Verbatim means verbatim.** A phase once filed a fabricated framework stack-trace line — one that
  wasn't even valid syntax in that language — in the one section whose entire value is being trustworthy.
  Once output is reconstructed, the Hub has to re-run everything, which defeats the section's whole
  point. If output genuinely cannot be captured, **say so** — that is fine. Inventing it is not.
- **Reconcile the report against itself before filing.** One report's CROSS-REVIEW said `CLEAN` while its
  DEVIATIONS said "verdict pending" — both cannot be true. Read your own report once as a document before
  submitting it.
- **Report the model/lane you actually ran on.** One report named a first-party model for a session
  actually running on a third-party lane. The Hub uses this field to judge whether a lane is trustworthy
  for later phases; get it wrong here and the whole lane experiment is uninterpretable.
- **Report every commit**, including tooling, config, CI, and non-source files. A phase once shipped a
  deploy-pipeline change that never appeared in its own DEVIATIONS section.
- **Never edit the plan to make your own gate pass.** Run it, report the failure and why, and let the Hub
  fix the plan.
- **A re-derivation crib's numbers must match the final committed diff, not an earlier point in
  implementation.** One crib was true when written against a 6-test file, then stale by filing time
  because a late fix added 2 more tests — the same mutation against the final 8-test file gave a
  different result. The crib wasn't fabricated or self-contradictory (none of the other five rules would
  have caught it) — it was just stale. **If a late change touches what a crib measured, re-run the crib's
  own commands before filing.**

---

## §C — the Hub verdict

```
=== HUB VERDICT — PHASE <n> ===
REPORT:        .caddis/advisory-hub-reports/phase-NN-<slug>.md
VALIDATED BY:  <hub session model/lane> on <ISO 8601 UTC>
VERDICT:       ACCEPT | ACCEPT-WITH-CORRECTION | REJECT

--- RE-DERIVATION (what the HUB ran itself, not what the report said) ---
CLAIM:     <…>
HUB RAN:   <the literal command the Hub executed>
HUB GOT:   <…>
AGREES:    YES | NO | UNVERIFIABLE — <why>          (repeat per claim)

--- GATES RE-RUN ---
$ <command>
<output>
RESULT: PASS | FAIL | NOT RE-RUN — <why>

--- COMMITS AUDITED ---
$ git show --stat <sha>
MATCHES THE PHASE'S CLAIMED TOUCHES: YES | NO — <what was unexpected>

--- SAFETY-RULE RE-CHECK ---
<per rule in advisory-context §5, or N/A — none declared>

--- DEVIATIONS ADJUDICATED ---
<deviation> → touches locked decision <#>? YES | NO
           → Hub ruling: allowed | reverted | plan amended — <reason>

--- PLAN CORRECTIONS LANDED ---
<what was edited in the plan file itself, section by section — or NONE>

--- CORRECTIONS REQUIRED BEFORE THE NEXT PHASE ---
1. <exact fix, not a direction>

--- WHAT IS NOW STRUCTURAL ---            (MANDATORY — a verdict without this is incomplete)
| Correction | Where it now lives (file + section) | The failure that earned it |
|---|---|---|

NEXT PHASE MAY START: YES | NO
=== END VERDICT ===
```

**Where does a correction live so it cannot recur?**
- **Telling the implementing session** — worthless. That session ends and the lesson dies with it.
- **Putting it in the next phase's prompt** — barely better. It works once, and the Hub must remember to
  repeat it every phase. It won't, eventually.
- **Putting it in the durable artifact** (`advisory-context.md`) — correct. It binds every future phase
  whether or not anyone remembers it, and it carries the failure that earned it so a later reader knows
  why it exists rather than deleting it as noise.

**A verdict that does not end in "what is now structural" is half a verdict.** And **the Hub is not
exempt from its own contract**: if a correction traces back to advice the Hub itself gave earlier, the
verdict says so plainly rather than attributing it to the implementer.

---

## §D — Hub validation checklist

1. **Re-derive every VALUE CHECK.** Run the re-derivation yourself. Do not read the reported result.
2. **Re-run the exit gates**, at minimum the fast ones (unit tests, lint, type-check). Reported output can
   be stale even when it was honestly captured.
   **And re-run them in a DIFFERENT ENVIRONMENT from the implementer's** — see §E's
   "re-running a gate identically is not independent verification". Re-running the same way
   reproduces the blind spot instead of testing it. This is the sharpest known limit on the
   Hub's one rule, and it cost a failed production deploy to learn.
3. **`git log` / `git show --stat` the commits** — do the changes match the phase's claimed touches?
   Anything unexpected, especially tooling/config/CI files that never appeared in DEVIATIONS?
4. **Re-check every rule in advisory-context §5** — or record `N/A — none declared`.
5. **Any deviation** → is it a §4 locked decision? If so it is the Hub's call, not the implementer's.
6. **Any surprise** → does the plan's `## Current state` need correcting? Correct it **now, in the plan
   file** (§F).
7. **Deployed-environment smoke test at milestone boundaries** — against the environment the change
   actually ships to, not dev. Skip cleanly when the project has no deployed environment.

---

## §E — Hub techniques that actually catch things

### Re-running a gate *identically* is not independent verification

The Hub's rule is "re-derive, don't trust". Its sharpest limit: **re-deriving the same way
reproduces the implementer's blind spot instead of testing it.**

Worked example. A Hub accepted a milestone partly on *"gates genuinely ran — I re-ran the test
suite myself, 310 passed."* The very next deploy failed on that same suite. A dependency-injected
service built a database client **before request validation ran**, so an invalid query parameter
returned 500 instead of 422 — but *only on the CI runner*, because the local env file is
gitignored and every developer machine supplied it. Implementer green. Hub green. CI red.

> **The rule:** for any phase touching config, a data-store seam, or a dependency-injection
> boundary, re-run the gate under the *deprived* environment, not just again.
> `mv <env file> aside && <test command> && mv back` is a one-step runner reproduction.

Two corollaries, both earned:
- **A regression test for this class must not depend on ambient environment.** The test that broke
  CI was structurally incapable of catching its own bug locally. Its replacement monkeypatches the
  dependency to raise, so it bites everywhere.
- **Construct nothing expensive in a dependency provider or a service `__init__`.** A validation
  error must never need a database.

### Mutate the phase's riskiest DECISION, not just its named tests

A phase ran three mutations; one — swapping two deliberately-different windows for each other —
**broke nothing**, because every fixture was single-day so the two windows coincided. The suite
looked thorough and had a hole exactly where the phase's most consequential choice lived.

> When a phase's headline claim is *"these two things are deliberately different"*, mutate them
> into being the same and check that something fails.

### Mutate the GUARDRAIL, with evasion variants — not just the obvious violation

A security phase shipped a guard asserting a visibility-only permission could never become a real
gate. The Hub mutated it three ways:

| Variant | Caught? |
|---|---|
| `require("nav.x")` — the obvious one | yes |
| `require(SOME_CONST)` — indirection | yes, by a *different* test |
| `require("""nav.x""")` — **triple-quoted** | **no — full evasion** |

The third planted a live gate on an all-roles key and the entire suite plus both lint gates stayed
green. Root cause: the guard was a regex plus a substring scan, kept "two ways on purpose" — but
**both read the source as text, so they shared a blind spot rather than covering for each other.**

> **Two checks that can be fooled by the same trick are one check.** Parse the language, don't
> pattern-match its surface syntax — the parser hands back the *resolved* value, so every quoting
> style, including ones nobody has thought of, collapses into a single comparison.

Test a guardrail the way an adversary would, not the way its author imagined. On a phase whose
whole risk is "a gate that looks real and isn't", the guard against fake gates being itself fake is
the failure that matters most.

### A test asserting the OUTCOME does not pin the INVARIANT

Same phase. A documented invariant read *"break-glass admin resolves **before any database
lookup**"*. Two tests covered it — and both created the tables first, then asserted the returned
value. Moving the short-circuit *below* the query left every test green while destroying the
invariant outright.

> If the invariant is *"X happens without Y"*, the test must **withhold Y**. Asserting the result
> in a world where Y is present proves only that the result is reachable, not that it is
> independent. Here the fix was one test that never creates the tables — the omission *is* the test.

### A render/build check proves it mounted, not that it is right

A headless render returned `OK, 0 console errors` for a bar chart drawn upside down. Read the
screenshot, not the exit code.

### Mutation testing — the highest-value check the Hub does

**A test that passes but would not fail on the bug is worthless.** Reading a test tells you almost
nothing; breaking the code and watching the test fail tells you everything.

```
1. Back up the file the test claims to prove something about.
2. Remove exactly the behaviour under test — the smallest possible break
   (delete the branch, drop the argument, invert the condition).
3. Run the project's test command for that test file.  IT MUST FAIL.
4. Restore the file.
5. Re-run.  IT MUST PASS AGAIN.
```

Do this for **every** phase that adds a test claiming to prove a behaviour. It takes about a minute, and
it is the difference between "6 passed" and "6 tests that mean something." **Always restore and re-run —
never leave a mutation in the tree.** The specific trap worth naming: dropping an argument that has a
default silently changes behaviour *without erroring* — exactly what a mutation test catches and a code
read does not.

### Re-run the cross-review yourself

A report's own internal contradiction (CLEAN in one section, "pending" in another) is settled in one
command by just running it directly. **If a cross-review provider times out, try the other configured
provider before recording "inconclusive."** A single provider's outage is not grounds for skipping
independent review — on the reference run, the second provider found the real bug the first had missed.

### Read the copy, don't trust "verbatim copy"

When a phase claims to have copied a function/config/pattern verbatim, read it line by line against the
original. The easiest thing to drop silently is an argument with a default — dropping it changes
behaviour without erroring.

### Check the report against itself

Read the report once as a *document* before validating a single claim. Internal contradictions — a
verdict field disagreeing with a details field, a model name that doesn't match the claimed lane — have
found real problems as often as checking the code has.

---

## §F — Plan drift is the Hub's job

Nothing else in caddis owns *"the plan turned out to be wrong, correct it mid-flight."* The Hub is the
natural owner, and it is the step most likely to be skipped. Any SURPRISE that contradicts the plan's own
`## Current state` gets corrected **in the plan file, now** — not noted in the verdict for later, not
left for the next reader to reconcile.

---

## §G — The mechanical handoff audit

**A context doc is written BEFORE the work happens, so it is ALWAYS stale by the time it is needed.** The
outgoing Hub's honest first instinct, asked "can we hand off," is always *"yes, the context doc is
designed for exactly this"* — and that instinct has been measured and found wrong: a real audit found
seven gaps in a context file the outgoing Hub believed was current, including the single highest-value
technique the Hub had developed by then.

**Do not ask "are there gaps?" Assume there are, and find them mechanically:**

1. **List every technique, decision, and correction you actually used this session** — from your own
   actions in this transcript, not from re-reading the context doc. Candidates: did you re-run something
   with a second provider after a timeout? mutation-test a seam? apply a fix instead of only flagging it?
   adjudicate a deviation against a locked decision? correct the plan? fix an index/README in passing?
2. **For each, check whether the context doc's *instruction itself* already covers it** — not whether the
   word merely appears somewhere. Would a fresh Hub, reading only that file, be told to do the same
   thing?
3. **The caveat that will burn you:** a literal-string grep over prose produces **false MISSINGs**. A
   `0 matches` result means "this exact string isn't here," **not** "this isn't covered" — real content is
   often phrased differently than the search term. **Read the section before trusting a grep's absence.**
   Search by concept, read the surrounding paragraph, don't stop at the first non-match.
4. **Land every real gap as a durable rule** in the right section of the advisory-context, carrying the
   specific failure that earned it. A note left "for later" is not a fix.

`/caddis:handoff` runs this audit as its Step 2b, whenever the active plan has a companion
`advisory-context.md` — see that command for the wiring.

---

## §H — The reports directory

`.caddis/advisory-hub-reports/` — zero-pad the phase number (`phase-00-`, `phase-01-`, …) so the
directory sorts in execution order. Keep a `README.md` index inside it:

| Phase | Report | Verdict | Outcome | Date |
|---|---|---|---|---|

The verdict file matters as much as the report: without it, a later reader sees only the phase's own
self-assessment and no evidence anyone checked it.

---

## §I — Hub succession: the Hub is a ROLE, not a conversation

A long plan outlives any one session. The Hub runs as a **numbered series**, each handing to the
next through *files* — never chat history. **Write this convention down at the start, not when
someone asks.** On the reference project three Hubs had already run on hand-written prompts before
anyone noticed there was no convention; it was written only when the user asked "what were the
rules for spawning a new Hub?" and the answer was *there aren't any*.

Keep a table in `advisory-context.md`:

| Hub | Covered | Ended because |
|---|---|---|
| 1 | pre-Phase-0 setup | context |
| 2 | Phases 0–1 | context |
| 3 | Phases 2–6, two deploys | context |
| 4 | Phases 7+ | — |

### What a new Hub does before validating anything

1. **Read, in order:** `advisory-context.md` (all of it) → the plan's milestones, execution protocol
   and tracker → the project's rate/measurement rules → the most recent 2–3 verdicts.
2. **Prove the context landed** by answering a self-check *before* touching a phase (§J).
3. **Verify the tree independently.** `git fetch`, then count divergence yourself — never trust a
   relay file's number. Also **`git status` and diff any dirty file before treating it as
   authority**: a plan's working copy was once found carrying an *uncommitted revert* that deleted
   the rules a Hub was about to read, behind a clean-looking `git log`. A committed rule is only as
   durable as the working copy the next session opens.
4. **Run the mechanical handoff audit (§G) early**, while context is still thick — not at the end.

### A Hub may amend its predecessor's verdict — that is the mechanism working

Amend **in place, in the verdict file, with an attributed block**, so the record shows both the
original judgement and why it moved. On the reference project a fresh Hub — working only from files,
with no shared history — downgraded its predecessor's ACCEPT to ACCEPT-WITH-CORRECTION *and* caught
a deploy-blocking bug that the implementer, two cross-review passes and the prior Hub had all
missed. **That is the single strongest argument for this pattern.**

---

## §J — The context self-check, with a deliberate trap

The handoff prompt must force an incoming Hub to *prove* the context landed. Ask it to:

- **re-derive one anchor number live** (not quote it);
- name the decisions that are **accepted but reversible**, and what would reverse them;
- state where the next deploy gate is **and how it determined that**;
- say what it must do before its own handoff;
- name one thing a green automated check does **not** prove.

**Include at least one question whose naive answer is wrong.** The reference project's is *"what is
the funnel's `offered` count, and why is it NOT `SUM(OfferedInd)`?"* — the naive read gives 3,814,
the correct one 4,783, because the raw flags do not nest. A Hub that only skimmed **fails visibly
instead of silently**, which is the entire point.

---

## §K — Session batching belongs in the plan, as a contract

Annotate every phase `Session: continue` (may share a session) or `Session: fresh` (may not). On the
reference project every `fresh` coincided with either `Risk: high` or a model change — turning 20
phases into **11 implementer sessions with no loosened risk boundary**.

When batching: **one commit per phase** (never one combined commit), **one combined report** with a
clearly separated section per phase, and record that the batch **inherits the first phase's model**
— a phase specified as mid-tier ran on a frontier model for exactly this reason, and the report must
say so or the lane experiment is uninterpretable.

Two process rules earned by real misses:
- **Never state a deploy boundary from memory — read the plan's milestone table.** A Hub asserted a
  gate was after Phase 4; it was after Phase 3. The user caught it.
- **The plan's tracker row is not optional.** It was silently skipped for four consecutive phases
  and had to be Hub-backfilled. A Hub validating a phase should check the row was written.

---

## §L — Feed the learning back to THIS skill, not just to the project

Long plans spawn many Hub sessions, and each discovers something this skill did not anticipate.
Without a return path those learnings die in one project's context doc and the skill never improves.

> **Whenever a Hub is spawned, hands off, or lands a structural correction, append the *generic*
> form of that learning to the plugin's parking lot** — not only to the project's
> `advisory-context.md`.

**The split matters.** Project-specific facts (anchor numbers, schema quirks, local rate rules) stay
in the project's context doc. Only the **role mechanics** — techniques, failure modes, conventions —
come back here. Each entry carries the concrete failure that earned it, so a later reader can see
why it exists rather than pruning it as noise.

This is what makes the skill self-improving across Hub generations, and it is the natural extension
of "each Hub leaves the artifact better than it found it" — pointed at the *tool* rather than only
at the project. Every technique in §E arrived this way.

---

## Anti-patterns

- **Rubber-stamping.** A verdict with no re-derivation is not a verdict.
- **Applying this to a short feature.** State the cost, every time, before adopting the pattern.
- **Landing a correction only in the verdict file.** It must reach `advisory-context.md`, or it dies with
  the session that wrote the verdict.
- **Trusting a 0-match grep during the handoff audit.** Read the section; don't take the grep's word for
  it.
- **Telling the implementing session the fix instead of writing it down structurally.** That session is
  already closing.
- **Re-running a gate the same way the implementer did and calling it independent verification.**
  It reproduces the blind spot. Change the environment (§E).
- **Two guardrails that share a detection mechanism.** A regex plus a substring scan over the same
  text is one check wearing two hats — mutate with *evasion* variants to find out.
- **Asserting an invariant's outcome instead of withholding what it claims independence from.**
- **Treating a green cross-review as proof the reviewer saw everything.** Confirm the diff the tool
  actually sent was not empty — a change of all-new files reviewed as CLEAN without a model call.
- **Letting the learning die in one project's context doc.** Feed the generic form back (§L).
