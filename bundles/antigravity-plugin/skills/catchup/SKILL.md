---
name: catchup
description: Where were we? A quick list of what this session was doing and what is still open
---

# /catchup — where are we?

If $ARGUMENTS is empty, follow the catchup procedure below. If a name is given, follow
the pop-and-resume procedure at the end of this file. The name selects this mode; the
procedure still pops the last parked frame.

Answer one question: **what were we doing, and what is still open?**

Not named `/recap` on purpose — Claude Code has a built-in `/recap` that produces a one-line
session summary. This is the list version, and two commands whose names differ by nothing would
be a coin toss every time.

## Read these, in this order, and stop as soon as you can answer

1. **`.caddis/session-state/<session-id>.md`** — the primary source; read the NEWEST. The `Stop`
   hook rewrites one per session at the end of every turn, so it is current even when the session
   ended abruptly and nobody ran `/handoff`. It holds the last real request, the task list with
   statuses, and the files touched. Repos that have not stopped a session since 2026-09-08 have a
   single `.caddis/session-state.md` instead; read that when the directory is absent.
   **Check the `Session:` id in the header.** Sessions share working trees here, so the newest file
   can belong to a live PEER rather than to the session you are catching up on — if the id is not
   the one you are resuming, say so instead of reporting its work as yours.
2. **`.caddis/relay.md`** — only refreshed by `/handoff`, so it may be days behind, but it carries
   what the state file cannot: the agreed **next step** and the open blockers.
3. **The current turn's own context**, if this session has already done work. What you have done
   since the last Stop is newer than both files, and neither knows about it.

Compare the timestamps rather than assuming. If `relay.md` is newer, a handoff ran and its "Next
step" is the authority. If `session-state.md` is newer, work happened after the last handoff and
the relay's next step may already be done.

**A missing file is not an error.** A repo with neither has simply not run a caddis session yet —
say that in one line and stop.

## What to report

Keep it short enough to read at a glance. Roughly:

- **One line on where we are** — the workstream, and whether it is mid-flight or at a clean stop.
- **In-progress and pending items**, as a short list. Mark anything blocked, and on what.
- **The next step**, if one is recorded. Say which file it came from.
- **Uncommitted work**, if `git status` is dirty — this is the thing most likely to be lost, and
  the state file does not track it. Check it; do not assume clean.

Leave out anything already done unless the user asks. "What is finished" is a different question
from "where are we", and the completed list is usually the longest part of both files.

## Say plainly when the answer is thin

If the state file has no tasks and no last request, the honest answer is "the last session did not
record anything specific" — not a paragraph assembled from file names. A recap the user cannot act
on is worse than one sentence admitting there is nothing to recap.

## When the user wants more than a list

- To **reopen** the actual conversation rather than read about it: `claude --continue` in this
  folder, or `claude --resume` to pick an older session. Mention this only if the recap is thin,
  or if they ask for detail the files do not hold.
- To **write** a durable resume doc rather than read one: `/caddis:handoff`.
- To **pop a parked workstream** off the digress stack: `/caddis:catchup [name]`. This restores work deliberately set aside.

# /caddis:catchup [name] — pop the parked task and pick it back up

A digression is finished; return to the task you parked with `/digress`. This pops the top frame off the
workstream stack, restates where you were, realigns `relay.md`, and immediately continues the work — the
user should not have to remember or re-state anything.

## Step 1 — read the stack
Read `.caddis/workstreams.json`. If it is **absent, unparseable, `version != 1`, or `stack` is empty**,
say exactly `Nothing is parked.` and stop. Do nothing else.

## Step 2 — pop the top frame
The top of stack is the **last** element of `stack` (LIFO — most recently parked). Remove it and write the
rest of the file back (preserve `version` and any other frames + unknown fields). This is the one write
this command makes to the state file.

## Step 3 — restate + realign relay.md
Restate the popped frame to the user: its `plan`, `phase`, and `resumePointer` (and `repo` if set — the
parked task lives in another repo, so say which). Then edit `.caddis/relay.md`'s `## Next step` section
**in place** so it matches the popped frame's `resumePointer` — preserve every other section of relay.md
untouched. (If relay.md or that section is absent, skip this edit silently; the restatement above is enough.)

## Step 4 — resume the work
Begin executing the `resumePointer` immediately. Ask nothing — the frame already carries the next action.
If the parked plan lives in another `repo`, note that the user may need to open that repo first, then
proceed there.

## Rules
- **Never** run a destructive or history-rewriting git action (no `git checkout`, `git reset`, `git stash`,
  branch switches). Resuming is metadata-only.
- Pop exactly one frame per invocation (the LIFO top). Run `/caddis:catchup [name]` again to pop the next.
- Only real paths and verified facts — restate the frame as written; do not embellish the resume point.
