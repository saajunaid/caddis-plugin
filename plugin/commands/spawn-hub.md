---
description: Hand the Advisory Hub role to a fresh session — run the mechanical audit, then generate the succession prompt with a context self-check the new Hub must pass
argument-hint: [path to .caddis/plans/<slug>-advisory-context.md, or omit to auto-detect]
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

## Step 0 — resolve the context file, and refuse cleanly when you cannot

Use `$ARGUMENTS` if given. Otherwise look for `<plan-stem>-advisory-context.md` beside every plan in
`.caddis/plans/`.

- **None found → STOP and say so.** This project is not running an Advisory Hub, so there is no role to
  hand over. Do not scaffold one here: that decision belongs to `/caddis:feature-plan` Step 3b, at
  planning time, when the phase count and risk are actually known.
- **More than one → ask which**, listing them with each plan's status. Never guess: handing over the
  wrong plan's Hub is worse than not handing over.
- **Already handed over?** Check the succession table. If the last row has no end reason, this is a
  fresh handover. **If the last row is already closed and a new one opened, STOP** — a previous run
  completed and re-running would double-close it and re-open a duplicate. Re-running this command is
  safe only when the tree still shows the outgoing Hub as current.

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
3. **Land every real gap as a durable rule** in the advisory context — its *Standing gotchas*,
   *Hub techniques*, *Environment facts* or *Succession* section. **Cite sections BY NAME, never by
   number:** numbers drift between a project's hand-grown file and the shipped template, and this
   command previously named §7/§9/§13, which matched one project and no template.
   **A correction that lives only in a verdict file dies with the session that wrote it.**
4. **Audit in BOTH directions.** As well as what is missing, look for what is now **obsolete** — a
   gotcha since promoted to `AGENTS.md`, or one a committed test now enforces, compresses to a line
   and a pointer. The context doc is append-only by design and every incoming Hub must read it end to
   end; without a diet it becomes the thing it exists to prevent.

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
ended) and open the next one.

**Then update the carried-open list — APPEND AND CLOSE, never rewrite.**

Each Hub used to *rewrite* this list, which means an open item can vanish between generations with
nothing to show it ever existed. Nobody notices, because the only evidence was the list itself.

So: every item gets a stable id and is **never deleted**.

```markdown
- **[C7] Break-glass is DB-engine-dependent** — raised Hub 4. <what, and enough to act on>
  → **CLOSED by Hub 6**: fixed in `abc1234`, verified on prod.
- **[C9] `files.py` sibling-prefix traversal** — raised Hub 4. <detail>
  → still open.
```

Closing an item requires **saying who closed it and why** — a line, not a deletion. That makes a
disappearance impossible: an item either carries a close reason or it is still open, and both are
visible. It also lets a later Hub see that something was closed *wrongly*, which a deletion hides
forever.

**ARTIFACT CONSERVATION — the same check, for the files you wrote.** The ledger check above catches
an id that *disappeared*. Nothing caught a file that *exists and is invisible*, which is the inverted
failure and just as silent:

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_gate.py" hub-artifacts --reports .caddis/advisory-hub-reports
```

Exit 1 means you wrote a phase prompt the successor will never learn about. It will find no prompt,
write a fresh one, and lose whatever reasoning yours carried — plausibly and completely. Name every
prompt you authored in this spawn doc before handing over. (Degrades open: no handover yet, or no
script, means proceed.)

**CONSERVATION CHECK — mechanical, and it fails the spawn.** Every id in the predecessor's ledger
must appear in the outgoing one as either still-open or closed-with-a-reason. An id that is simply
absent is a silent loss: **stop and restore it before handing over.** Do not ask "did anything
vanish?" — diff the ids. That is the same design move as the handoff audit, for the same reason.

**One ledger, one home.** A verdict may *raise* an item, but it is not raised until it has an id in
the context doc's ledger, in the same commit. Two uncoordinated lists drift, and the drift is
invisible.

Carry the whole list forward, closed items included. It is short, and its history is the cheapest
audit trail this pattern has.

## Step 4 — generate the prompt

**"From the files, not from memory" is an instruction you cannot follow by intending to. Run the
generator:**

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_inventory.py" --with-tests
```
(falls back to `scripts/caddis_inventory.py` in a source checkout; skip the step if absent — it
degrades open like every other machine step here.)

Paste its output into the prompt as a **Repository inventory** section, verbatim. It enumerates
plans, PRDs, prompts, handoffs, KB notes, the parking-lot backlog, open comms, every script and its
purpose, and any generated artefact committed before its generator last changed. `--with-tests`
runs the suite instead of reporting a remembered number — one handover claimed 20 tests when there
were 19, and the incoming Hub found the discrepancy before anyone else.

**Why a generator and not care.** Nine corrective round trips were needed to bring one Hub to a
usable state, and the user caught six of the nine: no reports listed, no documents, no KB notes, no
scripts, planned work absent, and confusion over which of two prompts actually existed. Every one of
those is a directory listing. They were missed because an outgoing agent recalls *what it did*
rather than enumerating *what exists* — and the incoming Hub cannot know what it was not told.

Then write the judgement half yourself. It must contain:

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
5. **What is carried open — INLINE THE OPEN ITEMS VERBATIM, do not link to them.** (Closed items stay
   in the context file for the audit trail; they do not belong in the prompt.) A pointer costs a file hop at
   exactly the moment the new Hub has least context, and a carried-open item that is not read is
   indistinguishable from one that was closed.
6. **The next work**, with its batching (`Session: continue` = batchable, `fresh` = not) and any
   standing constraint the new Hub would not otherwise know — a stalled upstream load, a deploy hold,
   an environment that is mid-change.
7. **The standing authorisations**: deploys are user-authorised **every time**; a previous yes does not
   carry.
8. **What comes after this, and why the order matters.** Not only what is done and what is carried
   open — **what this is building towards**, for the next two or three phases. A Hub that does not
   know what comes next can design the current phase in a way that blocks it, and it will never find
   out, because nothing it can read says so. One live handover omitted a planned model comparison
   entirely; the user caught it. A section covering only the past reads complete and is not.
9. **The deliverable.** Name the thing this workstream must eventually produce, and the step that
   produces it. One handover carried every phase faithfully and never mentioned the report that was
   the whole point of the exercise. The user caught that too.
10. **A standing instruction to maintain the tracker.** Put this in the prompt, in these words or
    close to them:

    > **Maintain the tracker.** Your in-session task list does not survive this session.
    > `.caddis/relay.md` does. Mirror your working list into it as you go, and include its current
    > state in every progress report. Anything not written there is lost.

    The succession table records **who held the role**; `relay.md` records **where the work is**. The
    table is written when a Hub *ends*, so nothing covers the hours while a Hub is *working* — which
    is the whole period this mechanism exists to protect. A real spawned Hub read `relay.md`,
    answered a thirteen-question context check correctly, found four genuine defects in its
    handover, **and created no tracker at all**, because nothing asked it to.

    Note for the incoming Hub: `relay.md` is gitignored and machine-local. Anything a successor **on
    another machine** will need belongs in the advisory context or the next spawn prompt, not only
    there.
11. **`.caddis/kb/environment-map.md`, INLINE AND VERBATIM.** Hosts, which login works, where other
    repositories actually live. It is short, it is the first thing an incoming Hub needs, and it is
    the category most often missing — one incoming Hub searched the filesystem for a repository that
    lived in Gitea, and the user had to stop it. A pointer is not enough here: this is exactly the
    file a cold session does not know to open.

**Write it to `.caddis/advisory-hub-reports/hub-NN.spawn.md`** (frontmatter `type: hub-spawn`,
`hub: NN`), then print it. Until this file existed, every succession prompt lived and died in chat —
which made two of this command's own instructions unimplementable: "rotate the trap by checking the
last spawn prompt" had nothing to check, and the ledger conservation check below had nothing to diff
against.

Print the prompt in a fenced block, ready to paste. **Say plainly that it starts a NEW session** — a
Hub spawned inside the outgoing session's context inherits exactly the staleness this whole mechanism
exists to shed.

### Check the prompt before you hand it over

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_gate.py" handover-check \
  --doc .caddis/advisory-hub-reports/hub-NN.spawn.md
```

It fails when the prompt names a file that does not exist. **Validate the DOCUMENT, not just the
reader.** The context self-check in Step 4 proves the incoming Hub read carefully; it proves nothing
about whether what it read was true. One incoming Hub passed a thirteen-question check on a handover
containing four factual errors — it found them *despite* the check, not because of it.

### The single-writer rule — state it in the prompt

**The outgoing Hub stops writing to the repository the moment the succession prompt is issued.** Say
so in the prompt itself, so both sides know which one owns the tree.

This is not tidiness. Two sessions committed to one repository concurrently and the incoming Hub's
work landed inside the outgoing Hub's commit. Only committed objects are safe from another session's
checkout; a shared working tree is process-shared state, not session-private.

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
