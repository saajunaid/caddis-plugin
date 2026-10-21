---
name: fleet-close
description: Close a fleet of sessions — every session writes its handoff and acks, then print one restart sheet for the owner
---

# /caddis:fleet-close — close every session, collect acks, print the restart sheet

Use this when **several** sessions must stop together (a machine restart, a long break, a context
reset for the whole fleet). For one session, run `/caddis:handoff` instead. This session is the
**coordinator**: it asks every other session to write its own handoff, collects one ack from each,
writes its own handoff last, and prints a restart sheet. The owner starts each new session from that
sheet, and each new session runs `/caddis:fleet-open <role>`.

Every fleet rule (names, ack format, order, checks) lives in
`${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.155/scripts/caddis_fleet.py`; this command only calls it. Run the steps in order.

**Safety rules for the whole command** (a wrong close loses another session's relay or tasks):
- Never write, edit or move another session's relay, tasks file or watcher files. Each session writes
  its own; you only collect acks.
- Never stop, end or kill another session, and never tell one to exit. The owner closes terminals
  after reading the sheet.
- Never wait with a foreground `sleep`. Every wait is a background timer (`run_in_background`).
- A session that does not ack is never guessed: its row says `no ack`, and the owner runs
  `/caddis:handoff` in it by hand.

The ack format (one line in a fenced block, then the session's full resume prompt):

```
FLEET-ACK name=<n> role=<r> machine=<m> folder=<abs> relay=<path> tasks=<path|none> mode=<new|keeps-running|restore-on:<machine>|nothing> owns-watchers=<yes|no> worktrees=<abs;abs|none>
```

## Step 1 — list the fleet

Run `ListAgents`. Your own name is in its header line (`This session is <name>`): you are the
coordinator. Candidates:
- every local interactive or background session, and every Remote Control session that is not
  `offline`: each gets the close message in Step 3;
- every cloud session: it is listed as `keeps-running` and gets **no** message (it keeps running in
  the cloud). In Step 4 you save its ack yourself:
  `FLEET-ACK name=<n> role=<role-of n> machine=cloud folder=- relay=- tasks=none mode=keeps-running owns-watchers=no worktrees=none`,
  then the prompt line `Cloud session: keeps running; nothing to restore.`;
- `offline` rows and your own row are not candidates.

For each candidate, and for yourself, get the role:
`python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.155/scripts/caddis_fleet.py" role-of <name>`. **Two sessions with the same role**
would get one start line and one new name, and one of them would be lost. So when roles repeat, keep the
role for the first name (sorted), and give each other one a distinct role `<role>-b`, `<role>-c`, ...; tell
that session its role in Step 3 (rule 5).

Print the candidate list (name, kind, machine, role) before you send anything. If there are no candidates,
say so, run `/caddis:handoff` for this session only, and **stop**.

## Step 2 — make the fleet dir

The fleet dir is `.caddis/relay/fleet/<MMDD>-<HH>/` in this repo, at the coordinator's local time:

```
python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.155/scripts/caddis_fleet.py" new-name fleet
```

prints `fleet-<MMDD>-<HH>`; the dir name is the `<MMDD>-<HH>` part. Create it. It is local and
gitignored (it holds machine paths). Use the same dir for every later step, even if the hour changes.

## Step 3 — send the close message

Send each candidate (from Step 1) one `SendMessage`. The first line must be exactly:

```
FLEET CLOSE from <coordinator>: write your handoff and ack.
```

Then these close rules, in the message:
1. Run `/caddis:handoff` for **your own** relay only. Never touch another session's files. Skip its
   Step 7 (the `Push this note for another machine?` question): the restart sheet carries your prompt,
   and a question nobody answers would stop you before you ack. Run the handoff's Step 9 as
   `resume-block ... --fleet`: it prints your Session, Workstream and prompt, and
   `Start line: from the restart sheet`. The restart sheet holds the only start line. The ack stays a
   separate reply (rule 5).
2. In a shared checkout (its `AGENTS.md` says `Shared checkout: yes`, or `git status` shows changes you
   did not make), skip the steps the handoff checklist skips there.
3. If you run watchers: copy each watcher script to `.caddis/relay/<your name>-files/watchers/`, and fill
   the relay's `## Watchers` section (per watcher: script path, exact start command, stop condition,
   the action after the stop).
4. Your resume prompt must load your tasks file, greet peers with `<role> is now <your new name>`, and,
   in a shared checkout, say: "read code facts from origin/main; a worktree needs its own fresh
   dependencies".
5. Reply to `<coordinator>` with this block (one line, every field filled), then your full resume prompt:
   ```
   FLEET-ACK name=<n> role=<r> machine=<m> folder=<abs> relay=<path> tasks=<path|none> mode=<new|keeps-running|restore-on:<machine>|nothing> owns-watchers=<yes|no> worktrees=<abs;abs|none>
   ```
   Use `name=<your current name>` exactly as `ListAgents` shows it, and `role=<role>` as given in this
   message (a role that repeats in the fleet gets `<role>-b`, ...). `mode=new` if your work continues
   in a new session; `mode=nothing` if it needs no new session (for example a finished read-only review).
6. Remote sessions (another machine): also put your open task rows inline after the prompt, as a table
   with exactly this header line (other headers are not read):
   ```
   | Old # | Status | Subject |
   |---|---|---|
   ```
   and say whether your machine restarts (`mode=restore-on:<machine>`) or not (`mode=keeps-running`).
7. Do not exit or stop after the ack; the owner closes sessions.

## Step 4 — collect acks (first wait: 10 minutes)

Start a background timer, never a foreground wait:

```
sleep 600
```

with `run_in_background`. Each ack arrives as a cross-session message. For each one:
1. Write the message text (from the `FLEET-ACK` line to the end) to a temp file in your scratchpad.
2. Save it:
   ```
   python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.155/scripts/caddis_fleet.py" ack add --dir <fleet dir> --text-file <temp file>
   ```
3. Exit 0 → acked. An error names the missing or bad field: send that session **one** reply that
   quotes the error and asks for a corrected ack. Do not fix the ack yourself.
4. The ack's `name=` must be the name of the candidate that sent it, and its `role=` the role you gave
   it. If not, send **one** reply asking for a corrected ack (a wrong name makes a phantom row and marks
   the real session `no ack`). A second ack from the same session replaces the first (`ack add` saves by
   name).

Also save the cloud-session acks from Step 1 here, the same way.

## Step 5 — remind once (second wait: 20 minutes)

When the 10-minute timer ends, send each silent candidate **one** reminder:
`FLEET CLOSE reminder from <coordinator>: your ack is still missing.` Start a 20-minute background
timer (`sleep 1200`, `run_in_background`) and keep saving acks as in Step 4. When it ends (or every
candidate has acked), stop waiting. Each session still silent is a `no ack` row (Step 7).

**A late ack is never dropped.** Until Step 8 ends, keep saving every ack that arrives, as in Step 4, and
remove that session from the `--no-ack` list before the next `write`.

## Step 6 — your own handoff and ack

Run `/caddis:handoff` for this session (the coordinator's own relay), with Step 9 as `resume-block ... --fleet`. Then write your own ack (the
`FLEET-ACK` block with your fields and your resume prompt) to a temp file and save it with
`ack add`, as in Step 4. The coordinator's ack is never skipped. Then record this session's presence
(your session id is printed at session start as `[caddis] this session's id: <id>`; never guess one):

```
python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.155/scripts/caddis_fleet.py" whoami --session-id <id> --name <your name> --root .
```

## Step 7 — write and check the sheet

```
python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.155/scripts/caddis_fleet.py" write --dir <fleet dir> --coordinator <your name> --no-ack <name> [--no-ack <name> ...]
python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.155/scripts/caddis_fleet.py" check --dir <fleet dir>
```

Pass `--no-ack <name>` once for each silent session from Step 5, **on every `write`**, and leave it out
when every session acked (a placeholder would become a fake row) (the no-ack rows are not
saved between runs). `write` saves `roster.md` and `restart-sheet.md` in the fleet dir.

- `check` exit 0 → go to Step 8.
- `check` exit 1 → send each named session **one** message that quotes its error and asks for a
  corrected ack. Start one 5-minute background timer (`sleep 300`, `run_in_background`) and save the
  corrected acks that arrive. Then run `write` (same `--no-ack` flags) and `check` once more. Errors that
  remain go at the end of `restart-sheet.md` under a heading `## Needs the owner:`, one line each,
  quoted exactly.
- `write` or `check` exit 3 (no acks, or a file it cannot read) → do not print a sheet. Report the exact
  error, list every ack file in `<fleet dir>/acks/`, and **stop**: the owner decides.

## Step 8 — final reply

Reply with the whole text of `restart-sheet.md`, then its absolute path, and nothing else. The
restart closes this session too, so the sheet must be on screen and on disk.
