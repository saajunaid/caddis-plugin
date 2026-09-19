---
name: port-to-github
description: Move (port) an app or repository to GitHub from ANY source - a Gitea/GitLab/any git server URL, a local folder, a network (UNC) share, or a folder on a remote Windows box reached over WinRM - with or without existing git history. Keeps every branch and tag, verifies by SHA, translates Gitea/Forgejo Actions CI, switches deploy checkouts to GitHub with automatic rollback, and retires the old host safely. Use when the user says "move this app to GitHub", "port X to GitHub", "migrate from Gitea", "put this folder on GitHub", "this app only exists on the server", "import the repo from the prod box", or "cut the deploy over to GitHub".
---

# port-to-github

Move one app to GitHub without losing history, leaking a secret, or breaking its deploy.

The work is in **six phases**. Each ends in a check that can FAIL. Do not start a phase until
the one before it passed. Scripts are in `scripts/` next to this file. They are PowerShell 7
(`pwsh`); the parts that run on a remote box are Windows PowerShell 5.1 compatible.

| Phase | Script | Changes anything outside this machine? |
|---|---|---|
| 1. Stage the source | `Get-PortSource.ps1` | No. The source is only read. |
| 2. Readiness | `Test-PortReadiness.ps1` | No. |
| 3. Publish | `Publish-PortToGitHub.ps1` | **Yes: creates a GitHub repo and pushes.** |
| 4. CI | `Convert-PortWorkflow.ps1`, `Test-PortWorkflowParses.ps1` | Yes: a feature branch and a PR. |
| 5. Cutover | `Switch-CheckoutOrigin.ps1` | **Yes: changes where a deploy host pulls from.** |
| 6. Retire the old host | manual, see `references/old-host.md` | **Yes, and can be destructive.** |

**Stop and ask the user before phases 3, 5 and 6.** Each one is outward-facing. Say exactly
what will be created or changed, on which host, and how to undo it.

Not every port needs every phase. A folder that never had CI or a deploy host ends after
phase 3. Say which phases apply and why, before you start.

## Before you start

1. **Read the project config**, if one exists: `.caddis/port-to-github.json` in the repo you are
   working from (or `$env:PORT_TO_GITHUB_CONFIG`). It sets the GitHub `owner`, `visibility`,
   staging folder, the name for the old remote, dependency hosts and their secrets, and
   `projectNotes` - pointers to the project's own rules. **Read every file `projectNotes` names
   before phase 4.** Project rules beat this skill. The shape is in `references/config.example.json`.
2. `gh auth status` must show an account that can create repos in the owner. `git` must be able
   to push to github.com (run `gh auth setup-git` once if not).
3. **Find the authoritative copy.** If a folder is a clone of a server, port from the SERVER
   URL, not the folder: the folder may lack branches the server has. Port from a folder only
   when it is the only copy, or when it holds commits the server lacks. Phase 1 reports both
   cases.

## Phase 1 - stage the source

```powershell
$s = '<path-to-this-skill>/scripts'
& $s/Get-PortSource.ps1 -Source <source> [-Name <repo-name>] [-IncludeUncommitted]
```

| Source | Example `-Source` |
|---|---|
| any git server | `https://gitea.example/org/app.git`, `git@host:org/app.git` |
| local folder | `D:\work\app` |
| network share | `\\fileserver\projects\app` |
| remote box (WinRM) | `winrm://appserver01/D:/apps/app` (or `-ComputerName appserver01 -Source D:\apps\app`) |

What it does, for every kind: builds `<staging>/<Name>/mirror.git` holding ONLY branches and
tags, removes the remote so nothing can be pushed back to the source, and writes
`manifest.json`. A folder without history becomes one import commit; `node_modules`, virtual
envs and caches are skipped, and a `.gitignore` is written if there was none.

Read the output. These need a decision, not a shrug:

- **Uncommitted changes** in a source checkout are left out unless you pass
  `-IncludeUncommitted`, which puts them on a separate branch `port/uncommitted-snapshot-*`.
  The real branches stay exactly as committed. Ask the user which they want.
- **Remote-only branches**: branches the checkout only knows as `origin/x`. If the checkout is
  the only copy, re-run with `-PromoteRemoteBranches origin`. If a server has them, port from it.
- **Likely secrets** in a plain folder or a snapshot stop the script (exit 2). Nothing has left
  the machine. Show the user the list. Re-run with `-OnSecret Exclude` only after they agree
  those files must not be published.
- **Dropped refs** (`refs/pull/*`, `refs/remotes/*`, notes) are expected. GitHub refuses
  `refs/pull/*`, and pull-request discussion does not move with git anyway. If the old host's
  PR and issue history matters, export it before phase 6.

## Phase 2 - readiness

```powershell
& $s/Test-PortReadiness.ps1 -Name <repo-name>
```

**Blockers (exit 1) must be fixed before phase 3:** a file over 100 MB anywhere in history,
Git LFS content, a likely live credential in the current tree, an empty `${{ }}` in a file
under `.github/workflows`. A credential found in the tree must be **rotated**, not only
deleted: history keeps it. (An empty `${{ }}` in a `.gitea/` workflow is only a warning here:
GitHub does not read that folder, so it matters in phase 4.)

**Branches that already contain `.github/workflows` run them the moment they are pushed** -
deploy jobs included. Readiness lists those branches; publish refuses them unless you pass
`-AllowWorkflowRuns`, which you do only after reading every such workflow with the user.

**Warnings are decisions.** Go through each with the user: secret-type files in past history
(the new repo will expose them), CI credentials, dependency hosts, runner labels, files that
still name the old host. The report is in `readiness.json`.

## Phase 3 - publish (ask first)

Tell the user: the repo name, owner, visibility, branch and tag counts. Then:

```powershell
& $s/Publish-PortToGitHub.ps1 -Name <repo-name> [-Owner <org>] [-Visibility private]
```

It first checks the stage still holds exactly the refs phase 1 recorded (anything else would be
pushed and then "verified" against itself), creates the repo EMPTY, pushes `refs/heads/*` and
`refs/tags/*` with an explicit refspec, sets the default branch, and compares every ref by SHA
(exit 1 on any difference). Do not run other git commands inside the stage; if you did,
rebuild it with `Get-PortSource.ps1 -Force`.

- **Never** `git push --mirror`: it tries to push hidden refs, fails AFTER pushing the rest (so
  a populated repo reports failure), and deletes anything on GitHub the stage lacks.
- **An existing repo.** If one exists with history, the script refuses. Find out whether it
  shares history with the source: for a few of its commit SHAs, `git -C mirror.git cat-file -e
  <sha>^{commit}`. If it shares nothing (for example a snapshot someone uploaded with a fresh
  "Initial commit"), pushing on top welds a fake ancestry in forever: save anything of value
  from it, delete it, and re-run. Use `-AllowExisting` only when it is a genuine older copy; the
  script then requires every GitHub branch to be an ancestor of the staged one.
- Verify with the SHA comparison, never by counting refs or by "the push said OK".

Stop here if the app has no CI and no deploy host. Otherwise continue.

## Phase 4 - CI

Work in a normal clone of the NEW repo, on a feature branch.

```powershell
git clone https://github.com/<owner>/<repo>.git; cd <repo>; git switch -c port/github-actions
& $s/Convert-PortWorkflow.ps1 -AddPermissions [-SourceRef <sha>]
```

It copies `.gitea/workflows` (or `.forgejo/workflows`) to `.github/workflows`, rewrites the
`gitea.` context to `github.`, and prints every credential line. **Leave the scripts the
workflows call where they are** - GitHub only needs the workflow file under `.github/`.

Then do by hand, one line at a time - this is the whole job, and a blanket swap breaks it:

1. **Classify every credential line.** It faces ORIGIN (checkout, fetch, reset, pushing a tag
   back to this repo) or it names a DEPENDENCY host (a package registry, a library pinned from
   another repo or server). There is no third category.
   - ORIGIN -> `${{ github.token }}`, username `x-access-token`. This includes an
     `actions/checkout` that pushes tags - it is easy to miss.
   - DEPENDENCY -> a secret valid for THAT host. `github.token` reads only the repo whose
     workflow is running, so a library in ANOTHER GitHub repo needs its own read token.
   One job can hold two credential pairs that serve different hosts. Change only the pair
   that faces origin.
2. **One Authorization header per host.** `http.<url>.extraheader` values ACCUMULATE; two for the
   same host is an HTTP 400. `actions/checkout` persists its own header, so a step that adds
   another for github.com must unset the checkout's for that command and restore it after.
3. **npm and GitHub dependencies:** npm fetches a GitHub dependency over SSH even when
   `package.json` says `https`. Set `url.https://github.com/.insteadOf=ssh://git@github.com/`
   and `GIT_TERMINAL_PROMPT=0` so a missing credential fails in seconds instead of hanging.
4. **Runner labels** must exist on GitHub (`runs-on:`). Self-hosted runners must be registered
   to the org or repo, not only to the old host.
5. **Never write `${{ }}` in any text in a workflow**, including comments inside `run:` blocks.
6. **If a workflow was frozen** on the old host (triggers reduced to `workflow_dispatch`), pass
   `-SourceRef` with the last commit before the freeze. A workflow built from a frozen copy
   fires on nothing, which looks like "still queued", not like a fault.

Details and the credential patterns: `references/ci-and-credentials.md`.

**Validate before anything reaches `main`.** Commit the workflow files BY NAME, push the branch,
then:

```powershell
& $s/Test-PortWorkflowParses.ps1 -Owner <owner> -Repo <repo> -Branch port/github-actions
```

An unparseable workflow produces a failed run with zero jobs even on a branch its triggers
ignore; a valid one produces no run (or a normal run). A broken workflow on `main` leaves the
app with no deploy path, so this check is not optional. Then open a PR and let the real jobs
run; merging follows the repo's normal rules.

## Phase 5 - cutover (ask first)

Only for apps with a deploy host whose checkout pulls from the old origin. Order matters:

1. `Switch-CheckoutOrigin.ps1 -Mode Inspect` on each host. Record what it prints.
2. **Tell the user** the host, path, old and new URL, and the rollback command.
3. Switch:
   ```powershell
   & $s/Switch-CheckoutOrigin.ps1 -Path D:\apps\app [-ComputerName appserver01] -Mode Switch `
       -NewUrl https://github.com/<owner>/<repo>.git -VerifyWithGhToken
   ```
   It records the old URL first, keeps it as a second remote, fetches, and requires the
   checkout's HEAD to be on a GitHub branch. On failure it restores the old origin itself.
   `-VerifyWithGhToken` lends your gh token to that one fetch, in memory only, because a deploy
   host normally has no GitHub credential of its own (CI supplies one per run).
4. **Stop the old host from deploying** (disable its deploy job) only AFTER the first GitHub
   deploy is green. Two schedulers on one checkout have no lock between them.
5. **Verify the deploy by an artefact changing** - a built bundle's hash or file time - never by
   an HTTP 200 or a version endpoint alone. Both pass when a new backend serves an old frontend.

Rollback, at any point before phase 6:

```powershell
& $s/Switch-CheckoutOrigin.ps1 -Path D:\apps\app [-ComputerName appserver01] -Mode Rollback
```

Also repoint developer checkouts the same way (`-Mode Switch` without `-VerifyWithGhToken`), so
`git push` goes to GitHub. Keep the old remote; it is the local rollback.

## Phase 6 - retire the old host (ask first)

Read `references/old-host.md`. The short version:

- Prove nothing is lost first:
  `& $s/Compare-PortRefs.ps1 -Left <old-url> -Right <github-url> -Mode LeftInRight` must exit 0.
  Push any ref that exists only on the old host before you continue.
- Prefer a **read-only pull mirror** of GitHub on the old host (Actions off) over deleting it:
  anything still pinned to the old URL keeps working. Never a push mirror from CI.
- Anything that still pins a dependency from the old host keeps the old host alive. Find those
  pins before retiring it.

## Report

End with a short table per app: source kind, branches and tags ported (SHA-verified yes/no),
warnings accepted and by whom, CI state, cutover state and rollback command, what is left.
Say which phases were skipped and why.

## Rules that apply to every phase

- Stage files BY NAME. The only `git add -A` is inside the scripts, on fresh throwaway trees.
- A check that cannot fail is not a check. Every script here exits non-zero on the failure it
  exists for; do not pipe it to `Out-Null` or read only its last line.
- Audit the default branch on the SERVER (`origin/main`), never a working tree that may sit on
  an old feature branch.
- Code that runs on a remote box runs under Windows PowerShell 5.1. There, with
  `$ErrorActionPreference='Stop'`, a native command's stderr is a terminating error even with
  `2>$null`. Use `'Continue'` and judge native commands by `$LASTEXITCODE`.
- One variable at a time. When a whole batch fails the same way, change one thing and retry
  one item before re-reading the request.
