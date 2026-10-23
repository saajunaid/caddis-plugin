---
name: ship-pr
description: Open a reviewed PR for the current feature branch — rebase-safe push, PR create/update, monitor CI, STOP at green. Never merges, never deploys (that's /ship-merge).
---

# /ship-pr — the reviewed lane, half 1: branch → green PR

Land feature-branch work as a **Pull Request** so CI + a human gate run **before** the deploy, not
after. This command does the mechanics only: push safely, open (or update) the PR, watch its checks,
and **stop at green** with a mergeability verdict. It **never merges and never deploys** — on these
repos merge == deploy, so the merge stays a separate, deliberate act: `/ship-merge`.

For a quick commit and push of a feature branch, use `/ship` (the express lane). It never pushes the default branch.

Optional argument: **$ARGUMENTS** (PR title override; default = derived from the branch's
conventional-commit summary).

## Step 0 — Detect the lane (before anything else)

- **Gitea lane** — `.gitea/workflows/` exists. PR + CI monitoring via the Gitea API (token loading
  and job-polling procedure: the `deploy-local` skill).
- **GitHub lane** — `.github/workflows/` exists (and no `.gitea/`). PR + monitoring via the `gh` CLI
  (`gh pr create`, `gh pr checks` — see the `gh-cli` skill).
- **Local-only lane** — neither exists, or there is no push remote. There is no PR concept here:
  **refuse early**, tell the user to use `/ship`, and stop. Do not fabricate a PR flow.

Read `AGENTS.md` + the detected workflow file(s) first for the repo's real gate names, default
branch, and merge conventions — never assume `main`, never assume job names.

## Step 0b — Is this checkout safe to move?

<!-- checkout-safety: keep byte-identical in pr-merge, ship-pr, ship-merge and cloud-phases; a test pins it -->
Some steps below move the files of this checkout (`git rebase`, `switch`, `checkout <branch>`, `pull`, `merge`,
`stash`, `reset --hard`). Before the first of them, run:
```
python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.158/scripts/caddis_checkout_guard.py" shared --root .
```
It prints `SHARED: yes <reason>` or `SHARED: no` and exits 0. It says yes when the repo's `AGENTS.md` has a line
`Shared checkout: yes` (a dev service serves from this checkout), or when `git status` lists a change. With no
`--own-files`, every change counts as another session's. A linked worktree is never shared.

- **On `SHARED: no`,** do the steps as written, in this checkout.
- **On `SHARED: yes`,** never move this checkout. Leave its changes as they are, and report them. Instead:
  - **Rebase:** `git worktree add --detach "$(python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.158/scripts/caddis_worktree_root.py" rebase-<name> --record --purpose "rebase <name>")" <branch>`, then
    `git -C <worktree> rebase origin/<default>` and `git -C <worktree> push --force-with-lease origin HEAD:<branch>`.
  - **Pull a branch to test it:** `git fetch origin`, then
    `git worktree add --detach "$(python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.158/scripts/caddis_worktree_root.py" test-<name> --record --purpose "test <name>")" origin/<branch>` (for the default branch,
    `origin/<default>`), and run the gates there. Install dependencies fresh; never link `node_modules` or a venv.
  - **Clean up after a merge:** do not switch or pull. Run `git fetch --prune`, then
    `git fetch origin <default>:<default>`: it fast-forwards the default branch with no checkout. Git refuses when a
    checkout has the default branch out; then leave it and report it. Delete the local feature branch only when no
    checkout has it out.
  - Remove each worktree you made when its step ends: `git worktree remove <worktree>`.

`<name>` is the branch name with each `/` written as `-`. `caddis_worktree_root.py` prints the path of a new worktree:
`$CADDIS_WORKTREE_ROOT/<repo>/<short-name>`, else `<parent of the main checkout>/.worktrees/<repo>/<short-name>`. Never `%TEMP%`: Windows
cleanup can empty it. `--record --purpose "<why>"` also writes the path to this
session's created list (`caddis_created.py`), so `/handoff` can remove the worktree later. The caddis guard checks only the `Shared checkout: yes` line in
`AGENTS.md`, not a dirty tree: with that line, it asks before a tree move, and denies it in a headless session.
<!-- /checkout-safety -->

## Step 1 — Refuse on the default branch

A PR is *branch → default*. Read the default branch as a bare name: `git rev-parse --abbrev-ref
origin/HEAD` prints `origin/<default>`, so strip the `origin/` prefix before you compare.
```bash
d=$(git rev-parse --abbrev-ref origin/HEAD 2>/dev/null) && d=${d#origin/}   # prints origin/<default>: strip origin/
[ -n "$d" ] || d=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name)   # origin/HEAD not set
git branch --show-current                                                  # compare with "$d"
```
If HEAD **is** the default branch, stop: there is nothing to open a PR from. Offer to move the
uncommitted work to a feature branch (`git switch -c <branch>`), or run `/ship`, which does that and
hands back here.

## Step 2 — Preflight (local gates mirroring CI)

- Backend: `ruff check .` clean.
- Frontend: `npm run typecheck && npm run build` if `frontend/` exists.
- Fix failures first. **Never open a PR over red preflight** — a PR that arrives red wastes the
  reviewer it exists to serve.

## Step 2b — Tidy check on this PR's files (before the PR exists)

Finished plans close in the PR that finishes them (`/caddis:implement` step 4b). Check that this
PR did, on the files it touches only:

```bash
python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.158/scripts/caddis_tidy.py" --repo-root . --check --commit-range origin/<default>..HEAD
```

(`<default>` is the default branch from Step 0. Falls back to `scripts/caddis_tidy.py` from a
source checkout; skip this step if the script is missing or the repo has no `.caddis/`.)

- Exit **0** — carry on.
- Exit **1** — **stop; do not open the PR.** Show each `CHECK VIOLATION` or `ERROR` line.
  - `plan <path>: tracker done, status <s>` — run
    `caddis_tidy.py --repo-root . --apply --only <path>`, `git add` the moved plan by name,
    commit with `git commit -m "..." -- <old path> <new path>`, and run this step again.
  - `plan <path>: tracker done, but done/<name> already exists (rename one of them)` — `--apply`
    cannot fix this; it changes nothing while the name is taken. Rename the plan or the old
    `done/` copy with `git mv`, commit, and run this step again.
  - Any other violation — fix that file's frontmatter, commit, and run this step again.
  - `ERROR: uncommitted changes in files this range touched: <paths>; commit them first` — the
    check reads the committed files the PR ships, so commit (or discard) those changes first.
  - `ERROR: cannot read commit range <range>: <git error>`, or `commit range has an empty side`
    — the range is wrong, not the files. Fix the range: name both sides, and use the remote and
    default branch this repo really has (for example `upstream/master..HEAD`; check with
    `git remote` and Step 0). No violation list is printed with an `ERROR`, so nothing was
    checked yet.
- Only files this branch changed are checked, so problems already on the default branch never
  block an unrelated PR. The owner's fleet report (`caddis-fleet-tidy.ps1`) lists those.

## Step 3 — Scope-guard pre-check (before the PR exists)

- If the repo has a **named scope-guard workflow** (e.g. a Gitea `pr-scope-guard` that blocks PRs
  mixing infra `.gitea/`/`.github/` changes with product `src/`/`frontend/`/`tests/` changes): read
  the workflow's own rule and check the branch diff against exactly that rule **before** creating
  the PR. On a violation, **refuse with the specific offending files** — do not let the guard fail
  the PR after the fact.
- Without a named guard, apply the generic infra-vs-product mixed-diff heuristic as a **warning
  only** — surface it and proceed (repos without a guard allow mixed PRs by construction).

## Step 3b — Cross-review trigger (before anything is pushed)

<!-- shared:cross-review-trigger — keep byte-identical across commands; a test pins it -->
Run `python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.158/scripts/caddis_gate.py" review-tier --range <base>...HEAD` and review by its tier (rule 3).
`<base>` is `origin/<default branch>` (on the default branch itself, the commit before this change). Tier 0 or 1-small: no model review. Tier 1: one `/caddis:cross-review`. Tier 2: two reviewers of two other vendors in one round. No `TIER:` line means tier 2.
<!-- /shared:cross-review-trigger -->

> **Why this is mechanical and not "consider a review here".** a fleet app shipped four
> production releases in one day — sixteen fixes across SQL, caches, refresh jobs and React — and
> `/caddis:cross-review` ran **zero times**. Nothing was broken: the tool reported itself ready
> with two providers keyed. Nothing decided *when* to call it. Measured there: 4 of 39 plan files
> mention cross-review, and all four came from `/caddis:feature-plan`, which writes the line into
> the plan template it emits. So planned feature work got reviewed and a bug batch did not —
> **review coverage inversely correlated with urgency.** Two of that day's sixteen fixes were
> diff-visible defects, including a cache whose docstring said "cached for the instance's life"
> while a dependency rebuilt the object per request, so the cache was never once read.

## Step 4 — Rebase-safe currency

- If the branch is **behind** the default branch, offer to rebase onto it (stale branches are how
  merges rot). Only when behind — never rebase gratuitously.
- If the branch was already pushed, a rebase rewrites history. **Snapshot first, then push safely:**
  ```
  git branch backup/<branch>-preship          # recovery ref BEFORE any rewrite
  git rebase <default-branch>
  git push --force-with-lease origin <branch> # never bare --force
  ```
- In a shared checkout (Step 0b says `SHARED: yes`), never rebase here: rebase in a detached worktree, as
  Step 0b says.

## Step 5 — Push + create/update the PR

- Push the branch (plain push if no rewrite happened).
- Create the PR: title from the branch's conventional-commit summary (or `$ARGUMENTS`); body = the
  commit list + a "generated by /ship-pr" note.
- **Idempotent:** if a PR for this branch **already exists**, update its title/body and report it —
  never error, never open a duplicate.

## Step 6 — Monitor PR CI

Watch the PR's checks job-by-job (never the deploy — PRs don't deploy here), including the
scope-guard check when present:
- Gitea lane: poll the run for the PR's head SHA via the API (`deploy-local` skill procedure).
- GitHub lane: wait for PR checks outside the Claude session via `ci-watch`:
  ```bash
  python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.158/scripts/caddis_lanes.py" ci-watch --pr <pr>
  ```
  `RESULT: pass` means every check of the PR's head commit is complete and green; `HEAD:` names that commit.
  Exit codes: **0** pass → continue; **1** fail → read `FAILING:` and the gh output, classify, apply the minimum source fix, then re-push (through Step 4's safety if history must change); **3** could not tell (also: a check still unfinished, or the head's checks unreadable) → run `ci-watch` again; if it stays 3, stop and report, do not merge.
  Fallback when `caddis_lanes.py` is not available: watch in-session with `gh pr checks <pr> --watch` / `gh run watch` (`gh-cli` skill).
On a red check, classify the failure and apply the minimum **source** fix, then re-push (through
Step 4's safety if history must change).

## Step 7 — STOP at green, report

```
PR:          <url>
Branch:      <branch> → <default-branch>  (rebased: yes/no, backup ref: backup/<branch>-preship | n/a)
Checks:      <check ✓ / ✗ per check>
Scope-guard: pass | warn (<files>) | n/a
Mergeable:   YES — run /ship-merge <pr> when reviewed   |   BLOCKED by <exact reason>
```
This command's job ends here. **Never merge.** The merge is `/ship-merge`'s deliberately separate,
human-confirmed door.

## Rules
- **Never merges, never deploys** — no merge action exists in this command, by design.
- Never `git add -A`, `git add .` or `git add <dir>`, even after reading `git status`: stage named files only (the guard denies all three, and `git add -u` and `git commit -a`). Commit with `git commit -m "..." -- <files>`, after `git diff --cached --name-only` shows only those files.
- Never force-push without a `backup/*-preship` recovery ref; force pushes are `--force-with-lease` only.
- Never edit a workflow file (`.gitea/workflows/`, `.github/workflows/`) to make a gate pass — fix the source.
- Local-only lane: refuse + point at `/ship`. On the default branch: stop + point at `/ship`.

## Skill reference
Gitea API monitoring + failure triage: the `deploy-local` skill (ships in the optional `caddis-extras` plugin — enable it with `claude plugin enable caddis-extras`). GitHub `gh pr` / `gh run`
usage: the `gh-cli` skill. Load whichever matches the detected lane.
