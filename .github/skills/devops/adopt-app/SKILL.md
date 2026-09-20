---
name: adopt-app
description: Bring an app that was never scaffolded - a proof of concept that became real, a folder on a server, a checkout with no remote - up to the standard a generated app starts at. Inventories it without running it (local folder, network share, or a remote Windows box over WinRM), works out what stack each component is, measures it against an adoption standard with three verdicts (pass, gap, and question-only-a-person-can-answer), and writes an ordered plan whose steps cannot be done in the wrong order. Use when the user says "this app was never set up properly", "adopt this POC", "onboard this app", "it just runs from a folder on the server", "bring this up to standard", "what would it take to get this into CI", "nobody knows how this is deployed", or "it started as a prototype and now it is production".
---

# adopt-app

An app that was never scaffolded is missing things a generated app gets for free: a repository
on the team's host, CI, a declared stack, a health signal, a rollback. This skill finds out
exactly which of them are missing, what only a person can answer, and in what order to fix it.

**It never runs the app.** It reads files, file metadata, git state and what the host has
registered to start the folder. It does not execute an entry point, an installer, a build or a
migration. The app is usually the only copy of something already in production.

**It changes nothing outside its own output folder.** Every phase is read-only. The last phase
writes a plan; a different, team-specific skill performs it.

| Phase | Script | Writes |
|---|---|---|
| 1. Inventory | `Get-AppInventory.ps1` | `inventory.json` |
| 2. Stack | `Resolve-AppProfile.ps1` | `profile.json` |
| 3. Conformance | `Test-AppConformance.ps1` | `conformance.json`, `answers.json` |
| 4. Plan | `New-AdoptionPlan.ps1` | `adoption-plan.md`, `adoption.json` |

Output goes to `<outDir>/<name>/`, by default `.caddis/adopt/<name>/` under the current repo.
Scripts are PowerShell 7 (`pwsh`); the code that runs on a remote box is Windows PowerShell 5.1
compatible.

## Before you start

1. **Read the project config** if one exists: `.caddis/adopt-app.json`, or `$env:ADOPT_APP_CONFIG`.
   Six keys, every one of them read by a named script: `outDir`, `fileBudget`, `skipFolders`,
   `skipPattern`, `untrackedThresholdMB`, and `expectedRemotePattern` - the regex that says what
   "the team's host" means here. Without that pattern the skill cannot tell a team repository from
   a personal one, and it says so rather than assuming. Shape and per-key detail:
   `references/config.example.json`.
2. **Find out where the app really is.** A folder on a developer's machine may be a stale copy of
   a server folder, or the only copy in existence. Phase 1 reports which, but ask as well.
3. **Say up front that nothing will be run or changed.** People are right to be nervous about a
   tool pointed at a production folder.

## Phase 1 - inventory

```powershell
$s = '<path-to-this-skill>/scripts'
& $s/Get-AppInventory.ps1 -Path <folder> [-Name <short-name>] [-ComputerName <box>]
```

| Where the app is | How to point at it |
|---|---|
| this machine | `-Path E:\legacy-app` |
| a network share | `-Path \\fileserver\apps\legacy-app` |
| a remote Windows box | `-Path G:\apps\legacy-app -ComputerName appserver01` |

Prefer `-ComputerName` for anything on a server. A share scan works but is slow, and the host
facts - services, scheduled tasks, web sites - can only be read on the box itself.

**Read four things in the output before going on.**

- **Is the scan complete?** A budget or an access denial makes it PARTIAL: sizes become MINIMUMS,
  the script exits 1, and `-AllowPartial` is how you accept that on the record. Never treat a
  partial scan's "nothing found" as "nothing there". Raise `-FileBudget`, or use
  `-SkipFolder <name>` to spend the budget where the answer is still open. A skipped folder is
  recorded as NOT SCANNED, never as empty, and it prevents later checks from passing.
- **Neither committed nor ignored.** Folders in this state are the real hazard: one `git add -A`
  puts them in the history for ever. A filename pattern cannot find them - only git can.
- **COMMITTED versus not committed**, on every row of "what the repository must not carry". Only
  the committed rows need a history rewrite; the rest need a `.gitignore` line, or already have
  one. The distinction is per FILE, because one folder is routinely both: committed documents
  beside ignored output. Read the row's state before planning any work.
- **Possible credentials.** The heuristics are tuned to be readable rather than exhaustive: they
  skip comments, type declarations, template references and expressions. **Read every file they
  flag yourself.** A credential that was ever committed must be ROTATED, not only deleted.
- **What runs it.** If nothing on the host references the folder and the app is live, it runs
  somewhere you have not looked. Find out where before planning anything.

Junctions and symlinks are reported and never followed. A junction inside a tree that git manages
is a data-loss hazard: git's recursive remove follows it and deletes the target's contents.

## Phase 2 - what kind of app is it

```powershell
& $s/Resolve-AppProfile.ps1 -Name <short-name> [-ForceProfile <profile>]
```

A profile describes one KIND of component - how to detect it, its runtimes, build, services or
schedule, routing, config, data, CI and deploy. `profiles/` holds the starting set; the contract
is in `references/profile-contract.md`.

An app is a SET of components. The script reports **every** profile that matches each component
folder, not just the winner, because a folder can honestly be two things and picking one silently
hides a decision. Anything in `alsoMatches` is a question for the owner - leftover scaffolding
from an abandoned rewrite matches its own stack perfectly and is not part of the app.

- **No profile matched** (exit 2) means the rules do not describe this stack yet, not that the app
  has none. Copy `profiles/_template` into a new folder and fill it in. Set `status` to `draft`;
  only a stack that something has actually automated end to end may be `proven`.
- **A draft profile** is a description, not an automation. Follow it by hand and write down what
  you did, so it can earn `proven` later.

## Phase 3 - conformance

```powershell
& $s/Test-AppConformance.ps1 -Name <short-name>
```

Three verdicts, and the third is the point:

| | means |
|---|---|
| `PASS` | observed true |
| `GAP` | observed false, with the evidence named |
| `ASK` | **not observable from files.** A person must answer it. |

Who owns an app, which of 127 branches is the truth, how it is deployed today, whether the
rollback has ever been run - none of these are in the files. A tool that forces them into
pass-or-fail produces a confident wrong answer that nobody rechecks.

**An unanswered ASK on a blocking item stops the adoption exactly as a GAP does** (exit 2, versus
exit 1 for a gap). Record answers as they arrive; they persist in `answers.json`:

```powershell
& $s/Test-AppConformance.ps1 -Name app -Answer owner="Team Payments" -Answer canonical-branch=main
```

`-Waive <id>` records an accepted exception. It is stored as a waiver and never rewritten as a
pass - six months later the difference is the whole value of the record.

The standard, item by item and why each one is there: `references/standard.md`.

## Phase 4 - the plan

```powershell
& $s/New-AdoptionPlan.ps1 -Name <short-name> [-HandoverSkill <team-skill>]
```

The order is the product. Doing these in the wrong order costs real work:

- Create the repository before settling what may be in it, and removing it later means rewriting
  history other people have already cloned.
- Rotate a credential after publishing, and it was public in between.
- Wire up CI before anyone says which branch is the truth, and CI builds the wrong branch.

Each step carries why it is there, what to do, and the check that says it is done. Steps that
cannot start yet are listed as blocked, with the reason - a plan that omits what it cannot do
reads like a shorter job.

Give `adoption-plan.md` to the owner. Agree it before anything is changed.

## Handover

This skill says WHAT must be true. It does not know your hosts, ports, routing or CI, so it does
not perform the adoption. Pass the plan to the team-specific skill that does, and name that skill
with `-HandoverSkill` so the plan does not end in mid-air.

For the repository move itself, use the **port-to-github** skill: it stages the source read-only,
keeps every branch and tag, verifies by SHA, and never pushes back to the source.

Re-run phase 3 after each step. It is the same gate either way, so the work cannot quietly drift
from the standard.

## Rules that apply to every phase

- **Never run the app.** Not the installer, not the build, not a migration, not "just the health
  check". Reading is always enough to plan.
- **A partial answer must not read as a clean one.** Every script says when it did not finish, and
  reports a minimum rather than a wrong total.
- **File contents never go into an artefact.** A config file holds credentials and a report gets
  copied into tickets and chats. Paths, line numbers and key NAMES only.
- **A check that cannot fail is worse than no check**, and so is one that cannot pass. Both
  manufacture confidence. Every script here exits non-zero on the failure it exists for; do not
  pipe one to `Out-Null` or read only its last line.
- **Stage files by name.** The apps this skill is pointed at routinely hold gigabytes that are
  neither committed nor ignored, so `git add -A` in one of them is how they become permanent.
- Code that runs on a remote box runs under Windows PowerShell 5.1. There, with
  `$ErrorActionPreference='Stop'`, a native command's stderr is a terminating error even with
  `2>$null`. Use `'Continue'` and judge native commands by `$LASTEXITCODE`.
