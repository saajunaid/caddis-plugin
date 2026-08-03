---
name: spawn-hub
description: Hand the Advisory Hub role to a fresh session — run the mechanical audit, then generate the succession prompt with a context self-check the new Hub must pass
---

# /caddis:spawn-hub — hand the Hub role to a fresh session

> **The Hub is a ROLE, not a conversation.** It outlives any one session and hands to the next through
> **files** — never chat history. This command is the handoff. Until it existed, every Hub was spawned
> by a hand-written prompt, which meant the pattern only worked for someone who already knew what to
> put in one.

**This command does not start the new session.** It leaves the outgoing Hub's context in a state a
fresh one can pick up, then prints the prompt to paste. The human runs it.

---

## When to spawn — do not guess, and do not wait for the crash

**The default seam is a MILESTONE BOUNDARY.** A milestone ends with a deploy, a smoke test and a
handoff; that is already the plan's own `/handoff` → `/clear` point. Carrying a Hub across a deploy is
where staleness bites — the outgoing Hub's picture of prod is exactly what just changed.

**Spawn at the next milestone boundary if ANY of these is true:**

- the current Hub has validated **≥5 phases**
- it has executed **≥2 deploys**
- it has done substantial work *outside* phase validation (fleet changes, tooling, plugin releases) —
  that consumes context far faster than validation does
- **its own context is filling** — this one overrides the milestone seam entirely

> **Observed, not theorised:** on the reference project, Hubs 1–4 each ended because context ran out,
> never because a milestone did. A Hub covers roughly **4–6 phases / 1–2 milestones** before that
> happens. So treat the milestone as the *planned* seam and context as the *real* constraint, and run
> this command at whichever arrives first.

**Do not wait until context is nearly gone.** Step 1 is a real audit that needs room to run, and the
outgoing Hub is the only session that can do it. A handoff written from a nearly-full context is the
one most likely to omit exactly what the next Hub needs.

---

## Step 1 — the mechanical audit (MANDATORY, and it is not a formality)

**Do not ask yourself "are there gaps?" — assume there are, and find them mechanically.** The outgoing
Hub's instinct is always *"yes, this is ready"*, because it is judging against its own memory of the
session rather than against the document. **That instinct is wrong by default.** On the reference
project the first answer to "can we hand off" was yes; a mechanical audit then found **seven gaps** —
including that mutation testing, by then the single highest-value technique in use, was written down
nowhere a fresh Hub would find it.

1. **List every technique, decision and correction actually used this session** — from your own
   actions, not from the context doc. Re-ran a cross-review with a second provider after a timeout?
   Mutation-tested a seam? Fixed something directly rather than only flagging it? Corrected a gate
   rather than the code? Each is a candidate line item.
2. **For each, check whether the advisory context already tells a fresh Hub to do the same thing.**
   Not "does the word appear" — whether *the instruction* is there.
3. **Land every real gap as a durable rule** in the advisory context (§7 gotchas, §8/§12 techniques,
   §9 environment facts, §13 succession) — not as a note in a verdict. **A correction that lives only
   in a verdict file dies with the session that wrote it.**

> **The caveat that will burn you: a literal-string grep over prose throws false MISSINGs.** The same
> audit that found seven real gaps also produced three false negatives — content that *was* present,
> phrased differently. `0 matches` means "not this exact string", not "not covered". Search by concept
> and read the surrounding paragraph.

## Step 2 — close the record

- Every validated phase has a **verdict file**, and its `verdict:` frontmatter is one of
  `accept` / `accept-with-correction` / `reject`.
- Every **ACCEPT-WITH-CORRECTION** either has its corrections landed, or they are in the carried-open
  list. An unlanded correction that nobody is tracking is the worst thing to hand over.
- The plan's **Tracker rows** match reality. Check them; they get silently skipped, and on the
  reference project four completed rows were reverted to "not started" by a stray staged edit and only
  caught two milestones later.
- `git status` is clean, or every uncommitted change is deliberate and named in the handoff.

## Step 3 — update the succession table

In the advisory context's succession section: close the outgoing Hub's row (what it covered, why it
ended) and open the next one. **Then write the `Carried into Hub N+1` list** — open items only, each
with enough detail to act on without archaeology. This list is the single highest-value thing you hand
over; everything else can be re-read from files.

## Step 4 — generate the prompt

Build it from the files, not from memory. It must contain:

1. **The role and the one rule** — re-derive, do not trust; validate, do not implement.
2. **The read order**: advisory context (all of it, especially the succession section and the
   carried-open list) → the plan's milestones / execution protocol / tracker → the project's
   measurement rules → the most recent 2–3 verdicts.
3. **A context self-check the new Hub must answer BEFORE touching a phase**, from the files, including:
   - re-derive **one anchor number live** (not quote it)
   - name the decisions that are **accepted but reversible**, and what would reverse them
   - state **where the next deploy gate is and how it determined that** (read the milestone table —
     never state a deploy boundary from memory)
   - name **one thing a green automated check does NOT prove**, with the example that taught it
   - **verify the tree independently** — `git fetch`, count divergence, and `git status`/diff any dirty
     file before treating it as authority
4. **At least one question whose naive answer is WRONG.** This is the load-bearing part. A Hub that
   only skimmed must fail *visibly* rather than silently.

   > **USE A DIFFERENT TRAP THAN THE PREVIOUS HUB'S.** Check the last spawn prompt in
   > `.caddis/advisory-hub-reports/` and pick a fresh one. A trap reused across generations stops
   > testing comprehension and starts testing whether the new Hub read the old prompt — which it can
   > pass while understanding nothing. Rotate it, and prefer a fact the *most recent* milestone
   > established, since that is what the incoming Hub is least likely to have absorbed.

   Good traps share a shape: a figure that looks obvious, a correct value that differs, and a reason
   rooted in the data rather than in the code. On the reference project, one generation asked why the
   funnel's `offered` is not `SUM(OfferedInd)` (naive 3,814, correct 4,783 — the raw flags do not
   nest); the next asked why an abandonment rate moved from 7.6% to 5.9% (the old figure was not a
   rate at all — 72% of its numerator sat outside its own denominator).
5. **What is carried open — INLINE IT VERBATIM, do not link to it.** A pointer costs a file hop at
   exactly the moment the new Hub has least context, and a carried-open item that is not read is
   indistinguishable from one that was closed.
6. **The next work**, with its batching (`Session: continue` = batchable, `fresh` = not) and any
   standing constraint the new Hub would not otherwise know — a stalled upstream load, a deploy hold,
   an environment that is mid-change.
7. **The standing authorisations**: deploys are user-authorised **every time**; a previous yes does not
   carry.

Print the prompt in a fenced block, ready to paste. **Say plainly that it starts a NEW session** — a
Hub spawned inside the outgoing session's context inherits exactly the staleness this whole mechanism
exists to shed.

## Step 5 — report

Output: the audit result (candidates → gaps → where each landed), the succession table update, what is
carried open, and the prompt. Then stop.

**Do not begin validating the next phase.** You are the outgoing Hub; that work belongs to the session
about to be spawned, and doing it here re-creates the context problem you just solved.

---

## Anti-patterns

- **Spawning without the audit.** The prompt will look fine and quietly omit the session's best
  technique.
- **Writing the prompt from memory.** Build it from the files; memory is what is being discarded.
- **Handing over a stale carried-open list.** An item that was closed hours ago and still appears
  teaches the new Hub to distrust the whole list.
- **Waiting until context is nearly gone.** The audit needs room. Spawn early and cheaply.
- **Continuing to work after generating the prompt.** Two Hubs holding the role is worse than one.
