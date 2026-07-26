---
description: Pop the most recently parked workstream off the stack and resume it at its exact resume point
---

# /caddis:resume — pop the parked task and pick it back up

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
- Pop exactly one frame per invocation (the LIFO top). Run `/resume` again to pop the next.
- Only real paths and verified facts — restate the frame as written; do not embellish the resume point.
