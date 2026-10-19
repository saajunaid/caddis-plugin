---
name: roadmap
description: "Track milestones across plans in .caddis/roadmaps/<slug>/: next batch, typed blockers, rollup. Every change is a docs PR via caddis_roadmap.py."
---

# Roadmap

**Core rule:** the roadmap file on `origin/main` is the only truth; every change to it, by a tool or a human, is a
small docs PR, so it is ordered and recorded in git history. The tool's PRs are merged automatically on green checks
by `caddis_merge_chain.py --docs-only`; a repo that wants a human to review them protects its default branch.

`scripts/` below is the caddis scripts folder: `${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.146/scripts` in an installed plugin, `scripts/` in
the caddis source repo.

## The folder

`.caddis/roadmaps/<slug>/` holds:

| Path | What |
|---|---|
| `roadmap.md` | Milestones and Blockers tables (start from `assets/roadmap.template.md`) |
| `decisions.md` | decision register; a `Depends on` change cites an id from here |
| `cards/` | one **card** per unit of work handed to a lane or a reviewer: scope, files, pass criteria |
| `reports/` | what comes back from a card |
| `.local/` | machine-local: `changes.jsonl` (audit of the tool's PRs), the runner's `runner.jsonl` and `STOP` (its lock and other state are in `<git common dir>/caddis-runner/roadmap-<slug>/`) |

Plans stay in `.caddis/plans/`. Add `.caddis/roadmaps/*/.local/` to the repo's `.gitignore`. The write lock is not in
the folder: it is `<git common dir>/caddis-roadmaps/<slug>.write.lock`, so every worktree of the repo shares it.

## The format

```markdown
Runner host: <runner-host>

## Milestones
| ID | Milestone | Phases | Depends on | Exit check | Status | Owner | Target |
|---|---|---|---|---|---|---|---|
| S1 | Lines load | p-alpha#1, p-alpha#2 | - | `python scripts/check_s1.py` | todo | runner | WD3 |

## Blockers
| Milestone | Type | Reason | Check |
|---|---|---|---|
| S2 | data-condition | GPU rows not loaded | `python scripts/rows_ready.py` |
```

- **Status:** `todo`, `in-progress`, `code-done/data-pending`, `done`, `not-needed`. There is no `blocked` status: a
  milestone is blocked when it has a Blockers row.
- **Blocker types:** `owner-gate`, `external`, `shared` (a shared file, the GPU, the merge line, another session),
  `calendar`, `data-condition`. A new `calendar` blocker needs an ISO date `YYYY-MM-DD` in Check
  (`block --type calendar --check 2026-11-01`); a date is not a command, so it needs no `--by-owner`.
- **Owner:** `runner` (or empty) lets the runner take it; a session name means that session does it by hand.
- **Phase ref** `p-alpha#2` = Phase 2 in the Tracker of `.caddis/plans/p-alpha.md` or `.caddis/plans/done/p-alpha.md`.
  It is done only when its Tracker Status starts with `done` or a check mark **on origin**. Refs work inside one repo.
- **Runner host:** the one machine whose runner may run this roadmap. Write a placeholder such as `HOSTNAME` in
  shared examples.
- A `Depends on` change cites a decision id in the Milestone cell: `S9 (dep waived: TC94)`. `check` warns otherwise.
- **Strict sections.** `## Milestones` and `## Blockers` hold only blank lines, one table whose every line starts with
  `|`, and prose with no unescaped `|` set apart from the table by a blank line. Anything else is a parse error.
  A roadmap allows only headings, plain paragraphs, lists and pipe tables: no code fences, no HTML, no setext
  headings, no control or non-ASCII whitespace characters.
- **A malformed roadmap fails closed.** A row with the wrong cell count, a `|` line outside a table, a near-miss
  heading such as `## Blockers (open)`, an id that is not `[A-Za-z0-9_-]+`, an unknown Status or blocker type, or a
  phase ref to a missing plan: every command but `check` exits 4 and prints the errors. Fix the file by a PR.

## Commands

Every command runs `git fetch origin` and reads `origin/<default>`, never the working tree. Exit check and Check
commands run in a temporary worktree of `origin/<default>` (the merged code), with no stdin, killed with their whole
process tree on timeout.

```bash
python scripts/caddis_roadmap.py status  --roadmap <slug> [--json]   # "<done> of <total> done; next <id>; ..."
python scripts/caddis_roadmap.py render  --roadmap <slug> | --all [--out <html>]   # page: ~/.caddis/roadmap-pages/<repo>/<slug>.html; hub of every repo: ~/.caddis/roadmap-pages/index.html
python scripts/caddis_roadmap.py next    --roadmap <slug> [--json]   # exit 0 found, 1 nothing ready (reasons)
python scripts/caddis_roadmap.py check   --roadmap <slug>            # parse errors, unknown refs or types
python scripts/caddis_roadmap.py set     --roadmap <slug> --id S1 --col Status|Owner|Target --value <v> [--by-owner] [--reason "<r>"]
python scripts/caddis_roadmap.py block   --roadmap <slug> --id S2 --type <type> --reason "<text>" [--check "<cmd>" --by-owner]
python scripts/caddis_roadmap.py unblock --roadmap <slug> --id S2 --type <type> --reason "<text>" [--check "<cmd>"] [--by-owner]
python scripts/caddis_roadmap.py rollup  --roadmap <slug> --id S1
python scripts/caddis_roadmap.py recheck --roadmap <slug>
```

`next` picks the first milestone in table order that is `todo` or `in-progress`, whose `Depends on` are all `done` or
`not-needed`, with no Blockers row, Owner `runner` or empty, and a phase not yet merged. It returns that phase.

## Rules a runner trusts

- **Only `rollup` writes `done`.** `set --value done` exits 4. `rollup` needs every phase merged on origin, every
  `Depends on` milestone `done` or `not-needed`, and no open blocker other than `data-condition` (exit 1 names it),
  then runs the Exit check (300 s): pass -> `done`; fail with a `data-condition` blocker -> `code-done/data-pending`;
  fail otherwise -> an `external` blocker
  `exit check failing (exit <n>): <tail>` (the last 3 non-empty output lines on one line, the whole reason at most
  200 characters, masked as below). The part before `: ` is the blocker's identity: a later rollup adds no second
  row, and `unblock --reason "exit check failing (exit <n>)"` removes every row of that prefix. A check that fails
  on a missing environment (exit 9009/127/126, or output in its last 40 lines such as `No module named`,
  `Cannot find module`, `ENOENT`, `run npm run build first`) is exit 3: no blocker, no PR. Either way the last 64 KB
  of output (masked the same way) go to `.local/exit-check-<id>-<utc>.log` (the newest 10 stay), and rollup prints
  the path. A milestone with no phase refs and no Exit check is refused (exit 4).
  **Masked** in the reason and the log: the values of secret-named variables (`caddis_redact`); a whole
  `-----BEGIN ... PRIVATE KEY-----` block up to its END line (or the end of the output); AWS, GitHub, Slack and JWT
  tokens; a quoted value after a `password`/`secret`/`api_key`/`token` name, spaces included; an unquoted
  `*PASSWORD*=`/`*TOKEN*=`-style line value; URL credentials (`scheme://***@`); and absolute paths as `<path>`: a
  drive or UNC path up to the end of the line, a quote, `<`, `>` or `|`, and a `/home/`, `/Users/`, `/tmp/`, `/root/`,
  `/var/`, `/etc/` or `/opt/` path up to the end of the line or a quote. Other text is published as printed.
- **`**Exit setup:** <command>`** (optional, one per roadmap, beside `Runner host:`; no `|`) runs in the temp worktree
  before every Exit check (900 s). It must install fresh into that worktree, for example
  `python -m venv .venv && .venv\Scripts\pip install -e .[dev]` or `npm ci && npm run build`. Each command runs in a
  new shell, so the Exit check must call the venv itself: `.venv\Scripts\python -m pytest tests -q`, not
  `python -m pytest`. Never link or junction a shared venv or `node_modules`: the worktree is removed with `--force`
  after the check. A setup that fails or times out is exit 3 and writes nothing; the runner stops
  `BLOCKED rollup not run` and the owner decides (the stop names a docs PR that was opened but not merged).
- **Owner-only changes:** `set` Status `not-needed`, any `set` Owner, `unblock` of an `owner-gate`, and `block --check`
  (recheck runs that command unattended later). They need `--by-owner` and are refused headless: `CADDIS_HEADLESS`
  or `CLAUDECODE` in the environment (even empty), stdin not a terminal, or on
  Windows stdin not a console (a NUL stdin is headless).
- **`unblock` removes one blocker.** When two rows share milestone, type and reason, it exits 4 until `--check`
  names the row's Check text.
- **`recheck` clears `data-condition` blockers**, each row whose own Check passed (120 s), **and `calendar`
  blockers whose Check date has passed** (UTC; no command runs). A `calendar` row whose Check is `-` stays until
  someone runs `unblock`. Other types stay.
- **`not-needed` needs a reason.** `set --col Status --value not-needed --by-owner` also needs
  `--reason "dropped: <why>"` or `--reason .caddis/parking-lot/<file>.md` (the file must be on origin). A reason with
  `|` or a line break exits 4. The same docs PR adds `- <id> not-needed: <reason> (YYYY-MM-DD)` under `## Notes`
  (the section is added at the end when missing).
- **Old blockers are listed.** `status` (and so the runner's toast) ends with
  `old blockers: <id> <type> (<N> days), ...`, oldest first, for each blocker row older than 14 days. The age is the
  date of the newest commit on origin that added that exact row (`git log -S`): the roadmap never stores a date, and
  a row that was cleared and added again counts from the new add.
- **Commands run the merged code.** Editing a check script or a Check in the working tree changes nothing until it
  merges.

## How a write lands

`set`, `block`, `unblock`, `rollup` and `recheck` take the write lock (after 30 s, a lock whose holder is dead on
this host, or an empty or non-JSON lock older than 60 s, is taken over), branch `roadmap/<slug>-<id>-<utc>` from
`origin/<default>` in a temp worktree, commit `docs(roadmap): <slug> <id> <change>`, push, open a PR, and hand it to
`caddis_merge_chain.py --docs-only`. `gh` uses the account in `GH_TOKEN` when it is set. Git network calls time out
after 120 s, `gh` after 60 s and the merge chain after 1800 s (exit 3); none can wait on a credential prompt. `--dry-run` prints the diff
and `would run: <cmd>` lines, and runs and writes nothing. Exit codes: 0 clean, 1 blocked, 3 could not run, 4 error
(malformed roadmap, refused change, bad usage).

## The runner

`roadmap-run.ps1 -Roadmap <slug>` (a shim over `scripts/caddis_roadmap_run.py --roadmap <slug>`) runs the roadmap
unattended; `-Plan <slug>` runs one plain plan instead (the two are exclusive). It starts only on the roadmap's
`Runner host` (else exit 3). Each iteration:

1. `next`. Nothing ready: stop `BLOCKED nothing ready` (exit 1); the notification carries the `status` line. When
   the roadmap is finished (every milestone `done` or `not-needed`) the runner also removes its worktree if it is
   clean (only session relay files left), and keeps it, saying so in the stop line, if not. With the worktree gone it
   also deletes the local `caddis/roadmap/<slug>/*` branches merged into `origin/<default>` and names the others.
2. Print `next: <milestone> <plan>#<phase>` (`next` and the batch claim happen under one repo-level claim lock).
   A phase whose `**Lane:**` line does not start with this engine (`claude`, `agy`, `codex`), names a cloud session
   or the owner, or that has **no Lane line**, is not run (fail closed): the runner adds
   `block --type owner-gate --reason "phase <n> lane: <lane>"` (`lane: none` when there is no line) and goes on.
3. A `todo` milestone is set `in-progress` (a docs PR). Every session of a roadmap runs in ONE dedicated worktree,
   `%TEMP%/caddis-roadmap-<slug>-<8 hex of the repo's git common dir>`: made with `git worktree add --detach` from `origin/<default>` on the first
   session, reused on restart, recorded in the runner folder, never the `-Repo` checkout (plan mode keeps working in
   the given checkout). In that worktree the runner makes a fresh branch `caddis/roadmap/<slug>/<plan>-p<n>` from
   `origin/<default>` (it refuses a branch of that name already on origin that it did not make) and ONE session runs
   `assets/plan-resume-prompt.md` on it (if a blocked session left uncommitted work in the worktree, the runner
   stops `BLOCKED roadmap worktree has uncommitted work from <branch>` instead, and a session branch that already
   holds commits not on `origin/<default>` is never reset: `BLOCKED <branch> has unpublished commits from an earlier
   session`; the owner decides), with `{{slug}}` = the plan and
   `{{phase}}` = the phase. Every session gets its own fresh branch (also after an OWNER-GATE or BLOCKED one), so a
   blocked phase's commits never reach another PR. Sessions stay on that branch and never push.
4. Relay `STATUS: CONTINUE` with new commits on that branch: the **runner** checks that the session is still on it
   and did not touch `.caddis/roadmaps/` (else `FAILED`, nothing published), then, in this order: writes a persistent
   claim `<git common dir>/caddis-runner/claims/<plan>#<n>.json`, pushes the branch, opens a PR (`gh api`, the account
   from `GH_TOKEN`) titled `<plan> phase <n>: <phase title>`, writes the PR URL into the claim, records the wait in its
   runner folder's `waiting.json` (ref, PR, milestone, branch, claim and its hash, the roadmap hash; never in the last
   stop), and stops `BLOCKED waiting for merge <plan>#<phase> <pr url>` (exit 1). A run killed between the claim and
   `waiting.json` leaves a claim nothing names: the next start stops on it as an orphaned claim. On restart, GitHub
   must confirm the PR merged before any branch is deleted; a done Tracker row with the PR still open or closed
   unmerged stops `BLOCKED <ref> Tracker row is done but PR <url> is not merged` and keeps the branch, the claim and
   `waiting.json`. The claim keeps the phase held (`next`, other roadmaps and plan mode skip or refuse it) until the PR
   merges or closes. A run started while the PR still waits stops at once (`BLOCKED still waiting for merge of <ref>:
   <url>`) and changes nothing. Once it merges, the recheck task restarts the runner. The restart first checks that the merged
   origin roadmap is the one it published against (a hash, then the frozen tables; any difference is `FAILED roadmap
   changed`), rolls the milestone up FIRST (when every phase is merged), then removes the claim and the phase's
   branch (locally and on origin: whoever makes a branch removes it when its PR merges), and goes on with `next`.
   An own claim that neither the waiting record nor `pending-rollup.json` names (a run killed between the claim and
   the wait) stops the start `BLOCKED orphaned claim <file> from a killed run`; the owner checks the branch and its PR
   and deletes the claim.
   CONTINUE with the phase already merged on origin: `rollup` when every phase is merged, then back to 1. CONTINUE
   with no new commits and nothing merged stops FAILED. `STATUS: OWNER-GATE <r>` becomes an `owner-gate` blocker,
   `STATUS: BLOCKED <r>` an `external` one; then back to 1. `STATUS: FAILED` stops.
5. Every `**Risk:** high` phase done on the branch and not yet reviewed clean (record in the runner's own folder:
   `<git common dir>/caddis-runner/roadmap-<slug>/reviewed/<plan>.json`; another runner's record does not count) is
   reviewed BEFORE step 4 writes the claim and publishes
   (`caddis_review.py --plan --phase --runs 2`): exit 0 publishes;
   exit 1 starts one fix session, then one more review; exit 1 again stops `BLOCKED review`, exit 3, 4 or any other
   code `BLOCKED review not run` (neither restartable); the review cost counts against the USD caps.

Stops (each one notifies and releases the lock): a STOP file (`~/.caddis/STOP` or `.local/STOP`), any cap (10 h,
12 sessions, 120 min and USD 25 per session, USD 150 total; per run, in memory; the global agy spend cap of
`caddis_spend.py` still counts across runs), a lock or batch claim that cannot be written
(`BLOCKED claim not written`, before any session), the agy spend cap refusing a reservation, three sessions
with no newly merged phase, a roadmap write that fails, and the **snapshot guard**: one baseline for the whole run.
The Milestones and Blockers tables (every cell of every row, rows added, removed or moved), the `Runner host` line
and the `**Exit setup:**` line are frozen. Every origin read (each `next`, after the runner's own writes, after each session) is compared with the
previous one; the only differences allowed are the exact edits the runner itself made and recorded for that read: a
Status it set, a blocker row it added, and what a rollup's audit entry (`changes.jsonl`) says it actually wrote.
Anything else stops the run `FAILED roadmap changed`.
Each runner has its own state folder, `<git common dir>/caddis-runner/roadmap-<slug>/` (plan mode: `plan-<slug>/`):
lock, last stop, options, branches, worktree path, the saved roadmap text. `claims/` and `claim.lock` are shared at
the top level. The runner hashes its own folder (recursively) and its own claims before and after every session; a
change there stops the run `FAILED runner state changed` (not restartable). Another runner's writes never stop it. A restart checks that the claim its
waiting-for-merge stop records is still there with the same content; a missing record, claim or hash is
`FAILED own claim missing or changed` (not restartable). During the upgrade window a plan-mode lock of the base
version (`.caddis/plans/.local/<slug>/runner.lock`, read only) still holds its plan while its pid runs and the lock
file is newer than that process's start (else it is ignored). Roadmap slugs
match `^[a-z0-9][a-z0-9-]{0,62}$` everywhere (both scripts and `caddis_roadmap.py`). The launch options are kept
in memory and re-written at every stop, so a changed options file can never raise the caps.

The runner never passes `--by-owner`. Every session and every `caddis_roadmap.py` call it starts gets
`CADDIS_HEADLESS=1`. The runner lock is `<git common dir>/caddis-runner/roadmap-<slug>/runner.lock` (a plan-mode
runner: `plan-<slug>/runner.lock`), so every worktree sees it. It holds `{"host", "pid", "started_utc", "batch", "max_hours"}`. On
this host it is stale when its pid is not running, or the process now holding that pid started after `started_utc`
(pid reuse after a reboot; when the start time cannot be read, it counts as live). Another host's lock is stale when it
is older than its own `max_hours` plus 1 h. A stale lock is removed with a notification; a live lock is exit 3. A
plan-mode lock holds the whole plan (`batch` `<plan>#*`). `next` skips a phase another live lock holds, and plan mode
refuses a plan that a roadmap lock names, at start and before every session. `-DryRun` prints the chosen batch,
the session command, the worktree and any pending rollup, skips the host check, writes no files and starts nothing; it
does run `git fetch`, which updates the remote-tracking refs. `-GhAccount <login>` (recorded in the launch options,
passed on by the recheck task and in the printed task) makes every gh call of the runner and of `--last-stop` use
GH_TOKEN from `gh auth token -u <login>`; on a machine with several gh logins, give the repo's account. The sessions
never get that token, nor GH_TOKEN, GITHUB_TOKEN, GH_ENTERPRISE_TOKEN, NPM_TOKEN or NODE_AUTH_TOKEN from the
environment; with CADDIS_HEADLESS=1 the guard denies `git push`, `gh pr merge|create`, `gh release`, a write through
`gh api`, `gh workflow run` and package publishes. Only the runner publishes. A gh call that
cannot answer (gh missing, 401, 404) is an error, never "not merged": the run stops
`BLOCKED gh cannot see <repo> with account <login>`, notified and recorded.

`roadmap-recheck.ps1 -Roadmap <slug> -Repo <path>` starts `roadmap-run.ps1 -Roadmap <slug>` detached only when:
the runner's last recorded stop (next to its lock) is `BLOCKED nothing ready` or there is none, and `recheck`
cleared a blocker; or the last stop is `BLOCKED waiting for merge` and GitHub says that PR merged
(`--last-stop` asks GitHub only and fetches nothing; the restarted runner checks the Tracker row on origin under its
lock; in that tick recheck does NOT run `recheck`, because a cleared blocker would change the roadmap the restart
checks against its hash). If GitHub says merged but the Tracker row is not done, the restart
removes the claim and stops `BLOCKED <ref> merged but its Tracker row is not done` (the owner decides). A `BLOCKED nothing ready` stop also records the batches that
another runner's lock or claim held; once every one of those holders is gone, `--last-stop` says `freed:` and recheck
restarts the runner even with no blocker cleared. A plan in flight anywhere (a live lock or a claim on any of its
phases) holds the whole plan for every other roadmap and for plan mode. At the top of each run the runner rolls up
every milestone that waits only for its rollup (Status not finished, every phase merged, and the same rule as
`next`: no blocker, dependencies finished, Owner the runner); `--last-stop` says `rollup-ready:` for such a milestone,
so recheck restarts the runner. A sweep rollup that writes nothing stops `BLOCKED rollup of <id> wrote nothing`
(recorded, not restartable) and is not retried or reported until the roadmap changes. A rollup that exits 3 (its
exit check or Exit setup could not run) stops `BLOCKED rollup not run: <id> ...` (not restartable; the owner decides). The dry run lists them first. If
the owner edits the roadmap during a merge wait, the restart stops `FAILED roadmap changed ...` and names the
recovery: `roadmap-run.ps1 -Roadmap <slug> -AcceptRoadmap` (owner only, refused headless) takes the runner lock (a live
runner refuses it), prints the diff from the published baseline, asks you to type `accept` (or `--yes`), and accepts
the origin roadmap as the new baseline of the wait; the next start goes on. With `-DryRun` it prints the diff only. `--last-stop` uses `--gh-account`, else the account the run recorded
in its launch options. In all cases the lock must be absent or stale; for the agy engine `caddis_spend.py check` must exit 0 too (a
claude-engine roadmap needs no spend-cap file). A restart after a merge writes `pending-rollup.json` in its runner
folder, runs the rollup first, then removes the claim and the branch, and only then the file. Every stop records
itself: a failed rollup, a crash or a STOP file before that is not restartable (the owner decides), and the next start
finds the file and does the rollup first. A merged
branch checked out in another checkout is kept locally (HEAD never moves outside the roadmap worktree).
Any FAILED stop (the snapshot guard, a crash), a cap or a STOP file needs the owner: recheck prints why and starts
nothing; the owner's next manual run records a new last stop. A runner records the last stop `running` as soon as it
holds the lock, so a run killed without a stop (a reboot, a kill) also needs the owner; an unexpected exception
records `FAILED crash: <type>` and notifies once. Recheck restarts with the launch options the last run recorded
(engine, model, caps), each cap clamped to at most the built-in default (the options file is writable), never higher.
`roadmap-run.ps1 -Roadmap <slug> -PrintRecheckTask` prints a PowerShell block (`New-ScheduledTaskAction`,
`New-ScheduledTaskTrigger` every 2 hours, `Register-ScheduledTask`) for the owner to paste; it registers nothing. The
task runs only while you are logged on unless you add `-User` and `-Password` to `Register-ScheduledTask` (or set that
option in Task Scheduler).

## Limits

Sessions are cooperative (our own sessions): the runner guards against mistakes and runaway spend, not against a
deliberately hostile session, which runs as the same OS user and could change anything the runner can. The state
tripwire catches accidents in a runner's own state only. In particular, a session in another worktree of the repo can
delete or rewrite ANOTHER runner's claim or lock under `<git common dir>/caddis-runner/`; that is not caught while it
happens, and the victim runner fails closed only at its next restart (own claim missing or changed, orphaned claim). Caps are per run; the agy spend cap is the only limit across runs. Each roadmap has one
worktree, removed when the roadmap is finished and the worktree is clean.

Owner-only rules are enforced by this tool; a direct PR that edits `roadmap.md` bypasses them; the runner stops
when an owner-gate row disappears; repos that need more protect their default branch.
On Windows, a check's grandchild started in the instant before the job object is attached can escape the tree kill;
checks are owner-written, so this is accepted. Headless detection cannot see a process started in a fresh console with
the markers removed: anything that runs this tool unattended (the runner, scheduled tasks) must set `CADDIS_HEADLESS=1`.
