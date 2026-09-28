---
name: digress
description: Park the current workstream on the stack and switch to a new task — without losing the original
---

# /caddis:digress — park the current task, switch, never lose the thread

You are about to leave the current task for a related-but-different one (a design decision, a sub-feature,
or a blocker that must be fixed first). This command **saves the original task as a workstream relay** (`.caddis/relay/<name>.md`) so
neither you nor the user has to remember and re-state it later — `/catchup <name>` loads it back with its exact
resume point, and every SessionStart lists it in the workstream index. Loading never removes it.

The reason for the detour is **$ARGUMENTS** (if empty, derive a one-line reason yourself from what the
user just asked for).

## Step 1 — identify the CURRENT workstream (the thing being parked)
Determine the active plan, in this order:
1. The `.caddis/plans/*.md` this session has been executing.
2. Else the plan named in `.caddis/relay.md`'s `## Next step`.
3. Else — and ONLY if still ambiguous — ask the user which plan to park. This is the **single permitted
   question**; do not ask anything else.

Read that plan's `## Tracker` (or its phase headings) to find the **current phase** (the in-progress or
next-not-started one).

## Step 2 — write a one-line `resumePointer`
The single next concrete action for the parked task — copy it from the plan's Tracker or from relay.md's
`## Next step`. Example: `next: wire the parser to the staging table (see plan Tracker row 2)`.

## Step 3 — write the workstream relay to `.caddis/relay/<name>.md`
Write it through the locked script, never with a plain file edit (that would skip the conflict
check another session relies on). Scripts are in `${CLAUDE_PLUGIN_ROOT}/scripts/` (source
checkout: `scripts/`).

Your session id is printed at session start as `[caddis] this session's id: <id>`; use it for
`session_id` and `--session-id`, never a guess.

1. `caddis_workstreams.py hash <name>` — note the printed hash (`none` for a new workstream).
2. Put the relay below in a temp file, then
   `caddis_workstreams.py write <name> <temp-file> --expected-hash <hash>`. Exit 1 prints the diff
   against what another session saved and writes nothing: show it, merge, retry with the new hash.
3. `caddis_workstreams.py render-index --session-id <id> --branch <branch>` refreshes `.caddis/relay.md`.
   If it refuses a legacy `.caddis/relay.md`, or an old `.caddis/workstreams.json` stack exists, run
   `caddis_workstreams.py migrate-legacy` once (it backs up both), then retry.

Relay content, with the standard frontmatter:

```markdown
---
type: relay
workstream: <name>
branch: <branch>
session_id: <session_id>
plan: <plan>
generated:
  at: <now, ISO-8601 UTC>
---

# Relay — <name>

## Current workstream
<Active plan path + phase>

## Next step (exact)
<the one-line next action from Step 2>
```

- **Idempotency:** parking the same workstream again replaces its relay through the same hash-checked write; it never duplicates it.

## Step 4 — confirm, then continue
Tell the user: `Parked workstream: <name>. Saved to .caddis/relay/<name>.md. Now switching to: <the new task>.` Then proceed with whatever the
user asked — the digression IS the new work.

## Rules
- **Never** run a destructive or history-rewriting git action (no `git checkout`, `git reset`, `git stash`,
  branch switches). Parking is metadata-only; the working tree is untouched.
- Only real paths and verified facts in the frame. If you truly cannot determine the phase, write `"?"` —
  never invent one.
- This command records state and switches focus; it does not commit code.
