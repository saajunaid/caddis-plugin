---
name: runner-move
description: >-
  Move GitHub Actions jobs from self-hosted runners to GitHub-hosted runners, one repo at a time,
  with a cost check and a pilot PR. Use when the user says "move CI to GitHub-hosted runners",
  "stop using self-hosted runners", "runner migration", "move jobs off the runner box", or "run
  CI on windows-latest or ubuntu-latest".
---

# runner-move

Move the safe jobs of one repository from self-hosted runners to GitHub-hosted runners. Prove it
with one pilot PR. Then roll out repo by repo.

This skill is generic. It names no repository, host, path or organisation. The pilot at the end is
a labelled worked example only.

## The rule

Move a job only if it needs nothing that exists on the runner machine alone. When in doubt, the job
stays. A wrong move fails in CI. A wrong deploy move can break production.

## Step 1 - classify each job

Read the workflow file. For each job, read every `run:` step. Then read every script that the step
calls.

**Can move.** The job does only these things:

- checkout
- install dependencies
- lint and type-check
- unit and integration tests that use data in the repository
- builds

**Must stay.** The job does any of these things:

- writes to a server (deploy)
- restarts a service
- reads an internal host (a database, an internal git server, a file share, `localhost` of a server)
- uses a path that exists only on the runner (a drive path such as `C:\...` or `G:\...`, or a shared
  cache folder)
- needs a licensed tool that is installed only on the runner

Search the workflow and the scripts it calls for these signs:

```powershell
git grep -n -i -E '[A-Z]:\\|localhost|127\.0\.0\.1|nssm|Restart-Service|Stop-Service|\\\\[a-z]' -- .github scripts
git grep -n -E 'secrets\.' -- .github/workflows
```

Check each secret name. A secret that holds an internal host name or an internal URL means the job
reads that host.

Workflow-level `env:` that only the deploy jobs read does not block the check jobs. Look at which
job reads each variable.

Write the result as a table: job, current `runs-on`, move or stay, and the evidence line.

If no job can move, stop here and say so.

## Step 2 - cost

Do this before you edit. Hosted minutes can cost money.

```powershell
gh api orgs/<org> --jq .plan.name
gh api "organizations/<org>/settings/billing/usage?year=<Y>&month=<M>"   # group the items by sku
```

The old `/settings/billing/actions` endpoint returns HTTP 410. Do not use it.

Measure the minutes per run from recent runs:

```powershell
gh run list --workflow <file> --limit 50 --json databaseId,createdAt,conclusion
gh run view <id> --json jobs      # startedAt and completedAt for each job
```

Count the runs per month. Then compute: minutes per run, times runs per month, for each job you
will move.

Remember these facts:

- Windows minutes cost more than Linux minutes: about 1.7 times in the October 2026 usage data
  (USD 0.010 against USD 0.006 a minute). Read the real rates from the usage call above.
- A private repository is billed after the included minutes of the plan.
- A public repository does not pay for hosted minutes.

**A change that adds cost needs owner approval.** Give the owner the numbers and wait for a yes.

## Step 3 - edit

Change `runs-on` only for the jobs that can move.

| The job's scripts are | Use |
|---|---|
| Windows scripts (PowerShell, batch) | `windows-latest` |
| Clean on Linux (no Windows-only tool) | `ubuntu-latest` |

Then fix these three things.

**1. Tool paths.** A runner-only path to Python or Node does not exist on a hosted runner. Install
the tool in the job. Pin the version that production and the old runner use.

```yaml
- uses: actions/setup-python@v5
  id: py
  with:
    python-version: "<version of prod>"
- uses: actions/setup-node@v4
  with:
    node-version: "<version of prod>"
```

If a script reads an interpreter path from an environment variable, set that variable to the new
path:

```yaml
env:
  PYTHON_EXE: ${{ steps.py.outputs.python-path }}
```

**2. The default shell.** Look at `defaults: run: shell:` in the workflow first. On `windows-latest`
the default shell is `pwsh` (PowerShell 7). The old runner often used Windows PowerShell 5.1. If the
workflow sets no default and the steps were written for 5.1, add this to the moved jobs:

```yaml
defaults:
  run:
    shell: powershell
```

If the workflow already sets `shell: powershell`, add nothing. Say in the PR that you checked.

**3. Shared-cache scripts.** A dependency script may read packages from a cache folder on the
runner. Read the script. It must fall back to a normal install when the folder is missing. If it
does not, the job must stay, or a separate PR must fix the script first (see "Do not").

Also:

- Leave `clean: false` on checkout. It does no harm on a fresh hosted VM.
- Do not add caching in the same change. A change in speed must not hide a change in behaviour.
  Add caching in a later PR.

## Step 4 - pilot PR

Use one repository and one PR. A PR does not deploy, so it is a safe test.

**Exit gate.** Both of these must be true:

1. CI is green on the hosted runners.
2. The test counts equal the last self-hosted run. Compare the test summary lines of the old run
   and the new run, line by line. Do this even for a suite that is allowed to fail. A suite that
   "passes" with fewer tests ran less.

Then compare the job times with the last self-hosted run. Put both sets of numbers in the PR
description. The numbers decide whether the move is worth it.

If the counts differ, stop. Find the cause. A missing tool, a missing data folder, or a different
shell is the usual cause.

## Step 5 - monitoring impact

Do this before you merge. Look at every tool that watches CI or runners: dashboards, alerts and
reports. Ask these questions:

- Does the tool derive the job kind or group from the runner labels? Hosted jobs may fall into an
  "other" group.
- Does the queue depth count jobs that wait for a hosted VM? That number now means something
  different.
- Does any text say that every runner is self-hosted?
- Do runner-offline alerts still work? They are not affected. Hosted runners are not listed in
  `/orgs/<org>/actions/runners`.

Write down each effect. Fix them in that tool's own PR. Do not fix them in the pilot PR.

## Step 6 - merge, watch, roll out

1. Merge the pilot PR.
2. Watch the first run on the default branch, **including the deploy job**. The deploy job stays on
   the self-hosted runner. Check that it still starts and still works.

   ```powershell
   python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_lanes.py" ci-watch --run <run-id> --repo <owner/name>
   ```
3. Only after this run is green, take the next repository. Repeat steps 1 to 6 for each one. Never
   do all repositories at once.

## Do not

- Do not move deploy jobs.
- Do not move a job that reads an internal host.
- Do not change shared scripts in the same PR. Change them in an earlier PR, and merge it first.
- Do not roll out to all repositories before one pilot has passed.
- Do not add caching in the move PR.
- Do not delete the self-hosted runner. Other jobs and repositories may still use it.

## Worked example (labelled: one real pilot)

One pilot repository (a Python and React app), 2026-10-15, PR #30, merge `432d385`. The numbers
here are an example, not a default. The repository name is left out on purpose.

- Step 1: the check jobs (change detection, lint and test, frontend checks) could move. The deploy
  job wrote to a server, so it stayed.
- Step 3: the workflow already had `shell: powershell`, so no shell change was needed. A runner-only
  Python path became `actions/setup-python` and `actions/setup-node`.
- Step 4: the Python suite is non-blocking. The summary was `31 failed, 33 passed, 27 skipped` on
  the self-hosted run and on the hosted run. The counts matched.
- Job times, self-hosted to hosted: change detection 132 s to 17 s, lint and test 85 s to 99 s,
  frontend checks 482 s to 402 s.
- Step 5: the monitoring tool grouped jobs by runner label, so hosted jobs fell into "other". Its
  queue count also included jobs that waited for a hosted VM. Nothing broke and no alert fired. The
  team noted the fix for that tool's own PR.
