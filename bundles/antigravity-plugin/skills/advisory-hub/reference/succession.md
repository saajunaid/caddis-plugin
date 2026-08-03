# Advisory Hub — handing the role over — the mechanical audit, the self-check trap, the carried-open ledger

> **Loaded by:** `/caddis:spawn-hub` · `/caddis:handoff` Step 2b
>
> Reference for `.github/skills/workflow/advisory-hub/SKILL.md`. The core card carries the
> model; this carries the detail for one moment of use. Every rule here was earned by a
> specific failure — the failure is stated alongside it, so a later reader can tell a hard-won
> rule from an opinion.

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

