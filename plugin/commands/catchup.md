---
description: Where were we? A quick list of what this session was doing and what is still open
---

# /catchup — where are we?

Answer one question: **what were we doing, and what is still open?**

Not named `/recap` on purpose — Claude Code has a built-in `/recap` that produces a one-line
session summary. This is the list version, and two commands whose names differ by nothing would
be a coin toss every time.

## Read these, in this order, and stop as soon as you can answer

1. **`.caddis/session-state.md`** — the primary source. The `Stop` hook rewrites it at the end of
   every turn, so it is current even when the session ended abruptly and nobody ran `/handoff`.
   It holds the last real request, the task list with statuses, and the files touched.
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
- To **pop a parked workstream** off the digress stack: `/caddis:resume`. That is a different
  mechanism — it restores work deliberately set aside, not the last session's state.
