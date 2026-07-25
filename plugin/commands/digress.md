---
description: Park the current workstream on the stack and switch to a new task — without losing the original
argument-hint: [reason for the detour]
---

# /caddis:digress — park the current task, switch, never lose the thread

You are about to leave the current task for a related-but-different one (a design decision, a sub-feature,
or a blocker that must be fixed first). This command **records the original task on a workstream stack** so
neither you nor the user has to remember and re-state it later — `/resume` pops it back with its exact
resume point, and every SessionStart surfaces it (`⛏ Parked workstream: …`).

The reason for the detour is **$ARGUMENTS** (if empty, derive a one-line reason yourself from what the
user just asked for).

## Step 1 — identify the CURRENT workstream (the thing being parked)
Determine the active plan, in this order:
1. The `.claudster/plans/*.md` this session has been executing.
2. Else the plan named in `.claudster/relay.md`'s `## Next step`.
3. Else — and ONLY if still ambiguous — ask the user which plan to park. This is the **single permitted
   question**; do not ask anything else.

Read that plan's `## Tracker` (or its phase headings) to find the **current phase** (the in-progress or
next-not-started one).

## Step 2 — write a one-line `resumePointer`
The single next concrete action for the parked task — copy it from the plan's Tracker or from relay.md's
`## Next step`. Example: `next: wire the parser to the staging table (see plan Tracker row 2)`.

## Step 3 — push the frame onto `.claudster/workstreams.json`
The state file is a JSON object `{"version": 1, "stack": [ … ]}`; `stack` is LIFO (last element = most
recently parked). Each frame has exactly these fields:

```json
{
  "plan": ".claudster/plans/<slug>.md",
  "phase": "<current phase>",
  "resumePointer": "<the one-line next action from Step 2>",
  "reason": "<$ARGUMENTS or your derived one-liner>",
  "repo": null,
  "pushedAt": "<now, ISO-8601 UTC>"
}
```

- `repo`: `null` means "the plan lives in THIS repo". If the parked plan lives in a **different** repo, set
  `repo` to that repo's absolute path (the digression spanned repos).
- Read the file (create `{"version": 1, "stack": []}` if absent). **Idempotency guard:** if the
  top-of-stack frame's `plan` already equals the plan you are parking, UPDATE that frame in place (refresh
  `phase`, `resumePointer`, `reason`, `pushedAt`) instead of pushing a duplicate. Otherwise APPEND the new
  frame. Preserve any unknown fields already present. Write the whole file back (pretty-printed is fine).

## Step 4 — confirm, then continue
Tell the user: `Parked: <plan> @ <phase>. Now switching to: <the new task>.` Then proceed with whatever the
user asked — the digression IS the new work.

## Rules
- **Never** run a destructive or history-rewriting git action (no `git checkout`, `git reset`, `git stash`,
  branch switches). Parking is metadata-only; the working tree is untouched.
- Only real paths and verified facts in the frame. If you truly cannot determine the phase, write `"?"` —
  never invent one.
- This command records state and switches focus; it does not commit code.
