# Advisory Hub — the `advisory-context.md` template — the Hub's memory AND its on/off switch

> **Loaded by:** `/caddis:feature-plan` Step 3b (scaffold) · `/caddis:validate-phase` Step 0 (bootstrap) · `/caddis:spawn-hub` Step 3
>
> Reference for `.github/skills/workflow/advisory-hub/SKILL.md`. The core card carries the
> model; this carries the detail for one moment of use. Every rule here was earned by a
> specific failure — the failure is stated alongside it, so a later reader can tell a hard-won
> rule from an opinion.

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

## Succession — the Hub is a role, not a conversation

| Hub | Covered | Ended because |
|---|---|---|
| 1 | <phases> | <context / milestone / handover> |

## Carried open — APPEND AND CLOSE, never rewrite

Every item keeps a stable id and is **never deleted**. Closing one requires saying who closed it and
why — a line, not a deletion. That makes a disappearance impossible: an item either carries a close
reason or is still open, and both are visible. It also lets a later Hub see something was closed
*wrongly*, which a deletion hides forever.

`/caddis:spawn-hub` runs a **conservation check** against this table at every handover: an id present
in the predecessor's ledger and absent here fails the spawn.

| id | raised by | item | status |
|---|---|---|---|
| C1 | Hub 1 | <enough detail to act on without archaeology> | open |
| C2 | Hub 1 | <…> | **closed by Hub 3** — <why> |

A verdict may *raise* an item, but it is not raised until it has an id here, in the same commit.
Closed rows compress to one line; they leave for the changelog only when the plan ships.

## Lane trust — what each execution lane has actually earned

Phase reports carry `MODEL/LANE` so the Hub can judge whether a lane is trustworthy for later phases.
Nothing accumulated that judgement, so each Hub re-formed it from scratch or lost it.

| lane | phases run | notable |
|---|---|---|
| claude | | |
| glm-headless | | |
