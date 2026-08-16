---
description: File a future-work item in the one backlog — .caddis/parking-lot/ — or list what is open
argument-hint: [what to park] | list | done <slug>
---

# /caddis:park — put future work in the ONE place it belongs

Everything we will do later lives in `.caddis/parking-lot/`, one item per file. This command is the
only sanctioned way to add to it. Use it whenever work is identified but deliberately not done now:
a defect you are not fixing, a proposal, a plan you are parking, an idea worth keeping.

**Why a command and not just a convention.** Parking-lot item `002` records an agent that hand-wrote
a hub artifact into the wrong directory while the correct path sat unread on line 188 of the command
it never invoked. A documented convention that nothing enforces gets bypassed by the next agent in a
hurry. This command plus the `caddis_gate.py parking-lot` gate is the fix.

The request is **$ARGUMENTS**.

## Mode select

| `$ARGUMENTS` | Do this |
|---|---|
| empty or `list` | Go to **List mode** |
| `done <slug>` or `drop <slug>` | Go to **Close mode** |
| anything else | Go to **File mode** — the text is what to park |

---

## File mode

### Step 1 — check it belongs here

Park it only if it is work **we** will do later. Redirect these instead, and say which you chose:

| If it is | Send it to |
|---|---|
| Being worked on right now | `.caddis/plans/<feature>.md` |
| An interrupted task you will come back to this session | `/caddis:digress` |
| Blocked on a person outside this repo | `.caddis/comms/` + its `register.md` |
| A card on the docket board | the board. **Never hand-edit `.caddis/backlog/`** — docket writes it |
| A fact about the environment, not a task | the KB (`/caddis:kb`) |

### Step 2 — do not duplicate

List `.caddis/parking-lot/*.md` and read the title line of each. If this item already exists, **update
that file** — add the new evidence and refresh `Last Updated` — and stop. Say which file you updated.

### Step 3 — write the file

Path: `.caddis/parking-lot/<short-slug>.md`. Slug only, **no number prefix**: two sessions filing at
the same time would both pick the same number.

```markdown
---
type: parking-lot
status: open
future: <yes if we have committed to it; omit or `no` if it is a candidate>
severity: <high | medium | low>
found: <YYYY-MM-DD>
found-by: <repo / session / who reported it>
Creating Model: <your exact model id>
---

# <One line that states the problem, not the solution>

## What happened
The evidence. What was observed, where, with the actual output, path, or number.

## What it costs
Who or what is affected, and what goes wrong if this is never done. An item with no cost
stated is an item nobody will ever prioritise.

## Suggested fix
The smallest change that would remove the cause. Say if it is uncertain.
```

Rules the gate enforces — get them right the first time:

- `type:` is always `parking-lot`, whatever the item started life as.
- `status:` is one of `open`, `doing`, `done`, `dropped`. Nothing else. Not `wip`, not `todo`.
- `future:` if present is exactly `yes` or `no`. It is a **separate axis** from `status`: an item can
  be `status: open` and `future: yes`, meaning agreed but not started.
- Keep the file under **20 KB**. Over that it is a register, not an item, and the gate fails it.
- Set `severity` to something an outsider could check, not to how annoying it was.

### Step 4 — verify

Run the gate and show the result:

```bash
python scripts/caddis_gate.py parking-lot --repo-root .
```

Exit 0 means it conforms. Exit 1 means fix what it printed, then re-run. Do not report the item as
filed until this passes.

### Step 5 — report

One line: the path, the severity, and whether `future: yes` was set. Nothing else.

---

## List mode

Read every `.caddis/parking-lot/*.md` (skip `README.md` and `done/`). Print one table, sorted by
`future: yes` first, then severity high → low:

| Item | Severity | Future | Status | One-line summary |
|---|---|---|---|---|

Below the table, print the counts: how many open, how many committed (`future: yes`). Then run
`python scripts/caddis_gate.py parking-lot --repo-root .` and report any violation it prints.

If the directory is empty, say so in one line. Do not invent items.

---

## Close mode

1. Find `.caddis/parking-lot/<slug>.md`. If there is no exact match, list the near matches and stop.
2. Set `status: done` (finished) or `status: dropped` (deliberately abandoned).
3. **For `dropped`, append a `## Why dropped` section.** This is not optional. An item deleted with
   no reason gets re-raised by the next session that has the same idea; an item kept with "no,
   because ..." does not.
4. Run `python scripts/caddis_tidy.py --apply`, which moves it into `.caddis/parking-lot/done/`.
5. Report the file's new path in one line.
