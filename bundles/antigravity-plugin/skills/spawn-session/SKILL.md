---
name: spawn-session
description: Hand the WORK to a fresh session — generate the handover from the repo, then validate the successor by re-deriving its answers
---

# /caddis:spawn-session — generate the handover, then validate the successor

Use this when a session is long enough that its own recall has become the risk. It replaces
`/caddis:handoff` for that case: `/handoff` writes down what you remember, and **what you remember
is the failure mode.**

**Sibling, not duplicate, of `/caddis:spawn-hub`.** `spawn-hub` hands over a validation ROLE;
this hands over the WORK. Both run on `scripts/caddis_spawn.py`, so a fix to the machinery lands in
both.

## The failure this exists to catch

A long session does not forget. **It recalls superseded facts fluently.** Measured in one session:

- two throughput figures the agent had **itself withdrawn**, re-quoted days later
- *"E8 is blocked on F1"* repeated for three days without a re-test
- a commit hash written into a handover that went stale **within the hour**

Each was stated with conviction and was wrong. Asking that agent what it knows cannot find any of
it.

## Start the successor FIRST, then name it

**Preferred flow.** Start the child with a name you choose, then pass that same name here:

```
claude --name successor-9c2                                   # in a new terminal
/caddis:spawn-session successor-9c2 finish the harvester      # here
```

`claude -n/--name` sets the session's display name, and that is exactly the name `SendMessage`
addresses. You pick it, so nothing has to be looked up.

**Check the row before you trust the name.** Run `ListAgents` once and confirm the child is there
and reads `interactive`, not `offline` — a listing carries long-dead sessions, so presence alone
proves nothing. Names are also **not unique**: if two rows share one, `SendMessage` needs the
` [ref]` shown beside it. Pick a short distinct name and this never arises.

**Why this ordering.** With the child already running you hold its address from the start, so the
parent messages it directly and nothing has to be pasted. The older flow printed a prompt for a
human to carry, which meant the child did not exist yet and its address could not be known.

**What you give up, and how it is replaced.** In the older flow the child spoke first, so its
first message was itself proof it had read the handover. Here the parent speaks first, so that
proof is a separate step: **your opening message asks the child to reply with WHICH FILES it
opened, before it answers anything.** Ask for paths — a summary can be written without opening
anything. Record it with `--event readback`; until you do, the handshake refuses `--event answers`.

**No name given?** The command falls back to the older printed-prompt flow. That is also the only
route on agy and Codex, which have no `SendMessage`.

The successor is what to pick up first: **$ARGUMENTS** (if empty, derive it from the parking-lot
and the active plan).

---

## The capture ORDER — it is an order, not a list

**Out of sequence, you produce a handover that describes a state that never existed.**

| # | Step | Why it must be here |
|---|---|---|
| 1 | **Capture the knowledge** — KB notes for anything that generalises | FIRST, while the reasoning is still in context. Written last it becomes a summary of a summary |
| 2 | **Update the durable state** — the register, the parking lot | These are the authority. The relay quotes them, so they must be true before it does |
| 3 | **Write the TASK LIST to a file** | A task widget does not survive a `/clear`. This project has already lost one |
| 4 | **Write the relay** — what happened, who owns what, what is blocked | It CITES 1-3. Written earlier, it cites things that have since moved |
| 5 | **Derive the questions** | LAST. They must target what steps 1-4 actually say. Questions written first test **your memory**, which is the thing under suspicion |

Named, so a fresh session knows what to open with no prompt engineering:

```
.caddis/parent-relay.md            what happened, who owns what, what blocks
.caddis/parent-session-state.md    the task list
```

**`parent-` rather than overwriting `relay.md`:** the live relay belongs to the WORK and outlives
any one session. A handover is a snapshot.

> **Do not confuse `.caddis/parent-session-state.md` with `.caddis/session-state/`.** The names
> are close and the handling is opposite. The directory is written by the Stop hook every turn,
> one file per session id, and is **gitignored** — a recovery aid. The `parent-` file is written
> by you, once, deliberately, and is **committed** — a handover artefact. Reaching for the wrong
> one means either handing over an auto-generated stub, or committing conversation text.

Check the order before you issue anything:

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_spawn.py" capture-check --id <id>
```

It compares write times, which is the one property here that is mechanically knowable. It cannot
tell you a step was done *well* — nothing can — but it refuses a relay written before the task
list it cites, and questions derived before the relay they are supposed to target. It also flags
any KB note or register item that changed **after** the relay was written, because the relay
quotes those and they have since moved.

**A step that produced nothing is a note, not a failure — but you must SAY it produced nothing.**
A missing task list that the reader has to infer is worse than one declared empty.

---

## Round 0 — validate your OWN handover. No relay trip.

**Do this before writing the prompt.** It is the cheapest round and the one this whole command is
about: in the manual run, a child caught a stale hash the parent could have caught alone — a wasted
relay trip, and the relay trip is the expensive part.

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_spawn.py" preflight
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_spawn.py" fingerprint --with-tests
```
(falls back to `scripts/caddis_spawn.py` in a source checkout.)

`preflight` **refuses on a dirty tree** — the successor pulls, so uncommitted work is invisible to
it and it will either redo that work or build on a state that does not exist. Commit first.

### It also refuses above 95% context

**A refusal, not a warning.** Under 85% it runs normally; between 85% and 95% it runs and prints
the figure, which you must then **state in the handover** so the reader can weigh it.

Why a refusal: the thing that degrades first is the thing this command depends on. The failure is
not forgetting, it is **confident recall of superseded facts** — so a handover written from a
nearly-full context comes out fluent, cited and wrong. A warning cannot help, because the agent
that most needs to heed it is the one least able to judge that it should. The costs are not
symmetric either: refusing early costs this session's remaining headroom, while a confident wrong
handover costs the successor's whole session and everything built on the error.

**Where the number comes from.** Claude Code hands `context_window.used_percentage` to the status
line and to nothing else, so the caddis status line caches it per repo and `preflight` reads it
back. **No status line on this machine?** Pass your own reading:

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_spawn.py" preflight --context-pct 72
```

**A self-reported figure may only tighten the gate, never loosen it** — the higher of the two
always wins, so it can refuse earlier but can never talk its way through. That asymmetry is what
makes the fallback safe: the faculty being gated is the faculty doing the reporting.

With **no figure from either source, it refuses** — an unmeasurable gate that defaults to proceed
is not a gate — and the refusal names both ways out rather than leaving you stuck.

### Capture from the repo, never from recall

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_inventory.py" --with-tests
```

Then add the four things the inventory cannot derive:

| Capture | Why |
|---|---|
| **Open parking-lot count** | The integrity check. A successor that revives 13 of 15 has silently dropped two, and nothing else would show it. |
| **WITHDRAWN and SUPERSEDED facts, as an explicit list** | Highest-value content, easiest to lose. Two withdrawn figures were re-quoted by their own author. |
| **Anything learned this session that lives in no file** | A screenshot of the consuming UI changed a task's priority. It existed only in the chat. |
| **State verified, not asserted** — run the tests, the gate, `git status` | One handover said "1,066 tests"; it was 1,090 an hour later. |

**Nothing may be written from recall.** Every number comes from a command run during this capture,
or from a file quoted by path.

### Then check what you wrote

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_spawn.py" check --doc .caddis/spawn-session/<id>-prompt.md
```

It **blocks** on a commit hash or test count given as current state, and on any path that does not
exist. It only **notes** a historical hash — those are durable, and flagging them was how the first
version produced seven findings on one document and taught the reader to skim.

**A claim that cannot be re-derived does not go in the handover.**

---

## Round 1 — the questions. One relay trip.

**Up to six. Derived from what changed, never chosen.** An agent that picks its own exam picks what
it remembers, which is the thing under test.

| Slot | Source | Catches |
|---|---|---|
| 1–2 | the **oldest** settled decisions | a successor that read only the recent sections |
| 3–4 | what changed **most recently** | one that read only the summary |
| 5 | a fact that was **SUPERSEDED** | the highest-signal question — the obvious answer is the stale one |
| 6 | a live **hazard or cost** | forces a consequence, not a fact |

**At least one question's obvious answer must be WRONG.** In the manual run the discriminator was
*"which model serves chat?"* — the answer had changed **twice**, and a successor naming only the
most recent replacement had not read the history.

**Every question must be answerable from a committed file. Prove it:**

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_spawn.py" verify-question \
  --answer-in .caddis/kb/some-note.md --needle "the phrase that answers it"
```

A question whose answer is not written down tests memory — the thing being replaced. It is not a
harder question; it is the old failure wearing an exam's clothes.

### Store NO answer key — and `check` now REFUSES one

Do not write `<id>-key.md`. Two reasons, and the second is the one that matters:

1. The child can read it. Any exclusion rule is one path-glob away from failing.
2. **A stored key freezes your belief at capture time.** If you were wrong, the key is wrong, and
   the check certifies the error.

**This rule is no longer only written down.** It was written down before — in `007` §5, in these
words — and a session that had it available wrote a key anyway: into the file the successor reads,
inside a collapsed `details`/`summary` block, as though that were a lock. A model reads the whole file, so the
questionnaire tested nothing.

`caddis_spawn.py check` now **refuses** three shapes, and does not merely warn:

| Refused | Why |
|---|---|
| any collapsed `details` element | a rendering hint for a browser, not an access control |
| an answer-key heading | `ANSWER KEY`, `Expected answers`, `Correct answers`, `answers — for the …` |
| a numbered question and its answer on the same line | the questions may ship; the answers may not |

Questions on their own still pass — a check that blocked those would be switched off within a day.
The check is structural, not semantic, on purpose: judging whether prose *reveals* an answer is
wrong in both directions, and a check that cries wolf gets skimmed.

**The general class is bigger than this command.** A rule and an artefact that contradict each
other do not fail loudly. The artefact wins, silently, because the artefact is what gets read. So
put the check in the tooling, never in a document that says the tooling should have one.

**Re-derive each answer from the repo at validation time instead.** That validates the DOCUMENT and
the READER at once — which is exactly what `.caddis/parking-lot/done/004-*` said was missing, where
a successor passed a thirteen-question check on a handover containing four factual errors.

### The handshake — who sends what, and in which direction

007 routed every round trip through a human paste. Sessions can message each other now, so the
human becomes an approver rather than a transport — **where a transport exists.** Open the
handshake when you issue the prompt, not when the child replies:

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_spawn.py" handshake open --id <id>
```

It reports which route you are on. **`SendMessage` is Claude Code only** — the harness ships an
`agy/` directory and targets Codex — so detection tests `CLAUDE_CODE_MESSAGING_SOCKET`, the
transport itself, rather than the vendor. **The paste route is a supported path, not a broken
one.** On it, say so in the printed instructions, or the user watches nothing happen and concludes
the command is broken.

| Direction | When |
|---|---|
| **child → parent** | **Primary.** As soon as it has answers. It cannot message before it has them, so the message IS evidence it did the reading |
| **parent → child** | **A chase**, after the timeout, or whenever the product owner asks |
| **parent → child** | **The verdict.** Always, and always after re-deriving |
| child → parent | An acknowledgement, so the parent knows it may close |

**The parent chases, because child-initiated alone cannot see the worst failure.** A successor
that skips the gate and starts working produces silence — and silence is indistinguishable from
"still reading". Check it:

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_spawn.py" handshake status --id <id>
```

**A chase carries two FRESH questions, not just a reminder.** A reminder invites a hurried reply.
Two questions asked at chase time cannot have been pre-read in the handover, which is a stronger
test than the original set — and it costs nothing, since you are holding the context anyway.

**Write down HOW to reach the child the moment it first messages you.** `SendMessage` addresses a
peer by the name `ListAgents` shows, and you cannot know that name before the child exists — it
arrives as the `from-name` on its first message. Capture it there or you will be holding an open
handshake with no way to send the chase or the verdict:

```bash
... handshake record --id <id> --event answers --peer <from-name>
```

`handshake status` then prints the address, so a chase is a copy-paste. With no peer recorded it
says so plainly, because **that is itself the signal**: the child has not made contact. Run
`ListAgents` — and note a session started seconds ago can be missing from one listing, so a single
empty result is not proof it does not exist.

Record each step, and the parent may not finish until the child has acknowledged:

```bash
... handshake record --id <id> --event answers    # the child replied
... handshake record --id <id> --event verdict    # you replied, after re-deriving
... handshake record --id <id> --event ack        # the child confirmed
... handshake close  --id <id>                    # REFUSES unless acknowledged
```

**`close` refuses on an open handshake, and that is the point.** A handover nobody has read is not
a handover, it is a file — and grading RE-DERIVES, so it audits the document as well as the
reader. In the manual run that pass found a defect in the parent's own handover. `/clear` in your
terminal destroys the only thing that can do that.

> **You stay ALIVE. You stop WRITING.** `/caddis:spawn-hub` carries a single-writer rule — the
> outgoing session stops writing to the repository the moment the prompt is issued, because two
> sessions committed to one repo concurrently and one's work landed inside the other's commit.
> That is a different rule from this one and **both hold.** Said no other way, a reader reconciles
> them by closing the parent early, which removes the grader.

Note the handshake file lands in `.caddis/spawn-session/`, so commit it with the others before
re-running `preflight`, which refuses on a dirty tree.

### Tell the child it does not own the tree

**Say this in the prompt.** A fresh session's instinct on seeing a dirty tree is to tidy it, and
you are still in that tree.

> While both sessions are live, do **not** run `git checkout`, `switch`, `stash`, `reset`,
> `rebase` or `clean`. A branch switch is visible to every session in this working tree and
> carries or destroys the other's uncommitted work. For parallel work, add a `git worktree` off
> `origin/main` instead of checking out here. Commit early — only committed objects are safe
> from another session's checkout.

The harness prints a live-peer warning at SessionStart when it can see one, but it **under-reports
by design**: a peer that has not finished a turn has written no state yet. No warning means no
evidence of a peer, not "you are alone". `git worktree list` finds what it cannot.

See `.caddis/kb/shared-worktree-branch-switch.md` for detection and the recovery pattern.

### What the child sends back

Three lines — messaged directly, or carried by the user on the paste route:

```
SPAWN <id> | head <sha> | <n> tests | answers in .caddis/spawn-session/<id>-answers.md
Q1-Q6 answered with citations. <n> commands run. <n> facts I could not find in a file.
<one line: the single most important thing I believe about the current state>
```

The fingerprint lets you detect a stale or mismatched paste **before grading anything**.

**The third line is the real test.** A successor that understood the work states the current state
in one sentence. One that merely parsed the files produces a generic line, and that is visible
immediately.

---

## The verdict — three, not two

| Verdict | Condition | You write |
|---|---|---|
| **ACCEPT** | every answer correct, citations check out | a short go-ahead naming the first task |
| **ACCEPT WITH CORRECTIONS** | broadly right; one or two facts stale or a citation wrong | the corrections, each with the file that proves it |
| **REJECT** | a settled decision misremembered, a withdrawn figure quoted, or a hazard misunderstood | an instruction to re-read named sections and re-answer. **Do not let it start work** |

**REJECT exists because a confidently wrong successor is more dangerous than a confused one.** In
this project the failure has never been *"I don't know"* — it has been a fluent wrong answer.

The vocabulary matches `/caddis:validate-phase` on purpose: same discipline, different object.

**Two REJECTs on one spawn means the HANDOVER is at fault, not the successor. Regenerate it** rather
than coaching the child through it.

**Record the verdict — the machine enforces both of those rules only if you tell it which one:**

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_spawn.py" handshake record --id <id> --event verdict --verdict REJECT
```

A REJECT returns the handshake to `awaiting-answers`, so `record --event answers` is legal again
and the child re-answers. The **second** REJECT is refused: it tells you to regenerate the handover,
and the only way forward is then ACCEPT or abandoning the handshake.

Until 2026-09-10 `--verdict` did not exist. The states were strictly linear, so after `verdict-sent`
the only legal event was `ack`, and nothing recorded WHICH verdict was sent — ACCEPT and REJECT were
indistinguishable in the state file. So "re-read and re-answer" was impossible and "two REJECTs
means regenerate" was unenforceable, because nothing counted them.

### When the fault is yours, fix the class

If validation finds an error that came from your handover, **fix the source document in the same
turn** — and fix the class, not the instance. In the manual run a successor found a stale commit
hash; the fix was not a fresher hash, it was to **remove hashes from both documents** and write the
command instead. A handover patched per-instance goes stale again on the next commit.

---

## Round 2 — the first task, scoped small, reviewed. One relay trip.

**Not more questions.** Two rounds of questions would be overkill; two rounds of the right things
are not.

**The questions validate RECALL. The first task validates JUDGEMENT** — and a successor can answer
six questions perfectly and still build the wrong thing. In the manual run round 2 caught a wrong
instruction from the parent, a wrong fact left by a predecessor, and a better design than the parent
had specified.

Round 1's verdict sets round 2's size:

| Round 1 | Round 2 task |
|---|---|
| ACCEPT | a normal next item; review the outcome |
| ACCEPT WITH CORRECTIONS | a **small, reversible** item that writes nothing permanent; review closely |
| REJECT | no task — re-read and re-answer |

Review the result **by re-deriving it**, exactly as you reviewed the answers — not by reading the
successor's account of it.

### Then stop gating

**After round 2 passes, stop.** A successor that answered six questions with citations and then did
one real task correctly has demonstrated as much as a gate can. Continuing to review every item
turns you into a bottleneck and the successor into a relay — which is the cost this command exists
to remove.

---

## Files — all three committed

```
.caddis/spawn-session/
    <id>-prompt.md     generated by you. The user pastes its "For the successor" section
    <id>-answers.md    written by the CHILD
    <id>-verdict.md    written by you, after re-deriving
```

`<id>` is short, unique and sortable — `2026-08-16-a`. Two spawns on one day must not collide.

They are committed for the same reason the register is a file: **a validation that happened only in
chat cannot be reviewed**, and cannot be re-read when the next handover asks what good looked like.

## Refuse to

| Refusal | Why |
|---|---|
| Run with a dirty tree | uncommitted work is invisible to the successor |
| Run above 95% context | the handover would be written by the faculty that is failing — fluently, with citations, and wrong |
| Run with no context figure at all | a gate that defaults to proceed is not a gate |
| Write a commit hash or test count as current state | both went stale within the hour, twice |
| Write a question whose answer is not in a committed file | it would test memory |
| Store an answer key | it freezes your belief, and the child can read it. **`check` enforces this** — see round 1 |
| Grade your own answers | you validate; the child answers |
| Close on an unanswered handshake | it is the same as never running one. `handshake close` refuses |
| Read silence as success | a child that skipped the gate looks exactly like one still reading |
| Proceed when the open-item count is unknown | that count is the integrity check |
