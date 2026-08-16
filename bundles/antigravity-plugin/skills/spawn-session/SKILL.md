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

The successor is what to pick up first: **$ARGUMENTS** (if empty, derive it from the parking-lot
and the active plan).

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

### Store NO answer key

Do not write `<id>-key.md`. Two reasons, and the second is the one that matters:

1. The child can read it. Any exclusion rule is one path-glob away from failing.
2. **A stored key freezes your belief at capture time.** If you were wrong, the key is wrong, and
   the check certifies the error.

**Re-derive each answer from the repo at validation time instead.** That validates the DOCUMENT and
the READER at once — which is exactly what `.caddis/parking-lot/done/004-*` said was missing, where
a successor passed a thirteen-question check on a handover containing four factual errors.

### What the child sends back

Three lines, carried by the user:

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
| **PASS** | every answer correct, citations check out | a short go-ahead naming the first task |
| **ACCEPT WITH CORRECTIONS** | broadly right; one or two facts stale or a citation wrong | the corrections, each with the file that proves it |
| **REJECT** | a settled decision misremembered, a withdrawn figure quoted, or a hazard misunderstood | an instruction to re-read named sections and re-answer. **Do not let it start work** |

**REJECT exists because a confidently wrong successor is more dangerous than a confused one.** In
this project the failure has never been *"I don't know"* — it has been a fluent wrong answer.

The vocabulary matches `/caddis:validate-phase` on purpose: same discipline, different object.

**Two REJECTs on one spawn means the HANDOVER is at fault, not the successor. Regenerate it** rather
than coaching the child through it.

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
| PASS | a normal next item; review the outcome |
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
| Write a commit hash or test count as current state | both went stale within the hour, twice |
| Write a question whose answer is not in a committed file | it would test memory |
| Store an answer key | it freezes your belief, and the child can read it |
| Grade your own answers | you validate; the child answers |
| Proceed when the open-item count is unknown | that count is the integrity check |
