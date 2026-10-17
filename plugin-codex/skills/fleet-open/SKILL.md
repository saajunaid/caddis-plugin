---
name: fleet-open
description: Restore one role from the fleet restart sheet in a new session — name check, relay, tasks, peer greeting, watchers
---

# /caddis:fleet-open — restore a role from the restart sheet

A fleet close (`/caddis:fleet-close`) wrote a restart sheet: one row per role, with the folder to
start `claude` in, a start line that names the new session, and the role's resume prompt. You are the new session
for one of those rows. This command restores that role in one go.

The argument is the role: `$ARGUMENTS`. If it is empty, list the roles of the newest sheet (Step 1)
and ask which one — do not guess.

Every fleet rule lives in `${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.140/scripts/caddis_fleet.py`; this command only calls it.
Run each step in order. A step that says "stop" ends the command: print why, and nothing else.

## Step 1 — find the newest restart sheet that holds the role

```
ls -d .caddis/relay/fleet/*/restart-sheet.md
```

The folders are named `<MMDD>-<HH>` (the coordinator's local time). Go from the newest folder to the
oldest and take the first `restart-sheet.md` with a section `### <n>. <role>`. Read the
`roster.md` beside it too: its row for the role gives the relay, the tasks file, the folder and the
mode.

- No sheet holds the role → say `No restart sheet holds <role>.` and **stop**.
- The sheet row says `no new session` (mode `keeps-running`, `nothing` or `no ack`) → say so, quote
  the row's section, and **stop**. A `no ack` row needs `/caddis:handoff` run by hand in the old
  session first.

## Step 2 — check this session's name before loading anything

Run `ListAgents`. Its header line says `This session is <name>`; that is your name. The sheet row's
Start line already names the session: `claude --name <expected> "/caddis:fleet-open <role>"`, where
`<expected>` is `new_name` of the role at the sheet's hour.

- `<name>` equals `<expected>` → go on.
- Otherwise it must at least be a name of this role:
  ```
  python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.140/scripts/caddis_fleet.py" role-of <name>
  ```
  prints `<role>` (the name is `<role>-<MMDD>-<HH>`) → go on, and note the name differs from the sheet.
- Anything else → tell the owner to run `/rename <expected>` and then `/caddis:fleet-open <role>`
  again, and **stop**. A session cannot rename itself, and a role loaded under the wrong name is a
  role its peers never reach.

Nothing is read into this session (no relay, no tasks, no watcher) until this step passes.

## Step 3 — read the relay and run its resume prompt

Read the role's relay (the roster's Relay column, `.caddis/relay/<old name>.md`), then follow the
resume prompt in the sheet section — the fenced block under `### <n>. <role>`. It is the same prompt
the old session wrote; do what it says, in order.

Load the open tasks: every row of the tasks file (roster Tasks file column,
`.caddis/relay/<old name>.tasks.md`, table `| Old # | Status | Subject |`) becomes one `TaskCreate`
with the Subject as its subject. A row with Status `in_progress` then gets
`TaskUpdate` to `in_progress`. A remote role's rows are inline on the sheet under
`Tasks (inline, remote session):` — load those the same way. Tasks file `none` → 0 tasks.
Count the tasks you created; Step 6 reports it.

## Step 4 — greet the live local peers

From the `ListAgents` output of Step 2 (run it again if more than a few minutes passed), take each
live local session whose role is in the roster (`caddis_fleet.py role-of <their name>`), other than
your own role. When a role has several names, address the newest:

```
python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.140/scripts/caddis_fleet.py" newest <their role> --names-file <file with one name per line>
```

Send each one message, exactly: `<role> is now <name>` (your role, your name). Skip offline sessions
and cloud sessions. Keep the list of names you greeted for Step 6.

## Step 5 — restart the watchers

Read the relay's `## Watchers` section. For each entry:

1. Print the entry as written (script path, start command, stop condition, after-action).
2. Check the script path exists (handoff copied it to `.caddis/relay/<old name>-files/watchers/`)
   and that the stop condition and the after-action are both in the relay. If either is missing,
   do not start it: report it as `watcher not started: <reason>` in Step 6.
3. Start it with its exact start command through Bash with `run_in_background`. Never a foreground
   `sleep` or loop.

No `## Watchers` section → 0 watchers.

## Step 6 — record the name and report

Record this session's presence (your session id is printed at session start as
`[caddis] this session's id: <id>`; never guess one):

```
python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.140/scripts/caddis_fleet.py" whoami --session-id <id> --name <name> --root .
```

Then print one line, and any `watcher not started:` lines under it:

```
[FLEET-OPEN] <role> restored: <n> tasks, <k> watchers, peers greeted: <names>
```

## Rules

- One role per session. To restore another role, start another session from the sheet.
- Never `claude --resume` the old session: the sheet exists so every role starts fresh.
- Never edit the restart sheet or the roster; they are the record of the close.
