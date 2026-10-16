---
description: Commit, push, and monitor the deploy pipeline (auto-detects Gitea, GitHub Actions, or local-only)
argument-hint: [commit message]
stage: ship
---

# /ship — commit → push → CI → prod

Ship the current working changes via this repo's actual delivery pipeline. The pipeline differs per
repo, so **detect it first**, then follow the matching lane. Preflight, staging, and commit are
identical across lanes; only monitoring and validation differ.

> **This is the express lane** — it pushes straight to the default branch with no review pause.
> Right for a hotfix. On a repo where that push deploys to production, Step 2c stops it before the
> push and the owner merges. **For feature work, use the reviewed lane instead: `/ship-pr`** (open a
> PR, monitor CI, stop at green) **→ `/ship-merge`** (merge the green PR behind a deploy-confirm,
> validate, clean up).

Optional message: **$ARGUMENTS** (if empty, derive a conventional commit message from staged changes)

## Step 0 — Detect the pipeline (do this before anything else)
Inspect the repo and pick exactly one lane:
- **Gitea lane** — `.gitea/workflows/` exists. Monitor via the Gitea API; follow the `deploy-local`
  skill (CalVer/NSSM prod deploy). This is the harness's local deploy setup.
- **GitHub lane** — `.github/workflows/` exists (and no `.gitea/`). Monitor via the `gh` CLI.
- **Local-only lane** — neither exists, or there is no push remote. Commit (and push if a remote
  exists); there is no CI to monitor — say so explicitly and stop after the push + local validation.

Read `AGENTS.md` and the detected workflow file(s) before starting so you use this repo's real gate
names, branch, and service identifiers — never assume.

## Steps 1–3 — common to every lane

**1. PREFLIGHT** — Run local quality gates that mirror CI:
- Backend: `ruff check .` (must be clean before any commit)
- Frontend: `npm run typecheck && npm run build` (if `frontend/` exists)
- Tests: run only if the user says they're needed or a gate explicitly requires them
- Fix any failures before proceeding. Do not commit broken code.

**2. STAGE + COMMIT** — Stage only the intended files (never `git add -A` blindly):
```
git status --short      # confirm what's staged
git add <specific files>
git commit -m "<type>(<scope>): <message>"
git rev-parse HEAD      # record SHA for monitoring
```
Use conventional commits: `fix:`, `feat:`, `chore:`, `refactor:`, `docs:`. Scope = affected module.

**2b. CROSS-REVIEW TRIGGER** — `ship` has no review pause at all, which is how sixteen fixes reached production unreviewed in one day.

<!-- shared:cross-review-trigger — keep byte-identical across commands; a test pins it -->
Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_gate.py" review-tier --range <base>...HEAD` and review by its tier (rule 3).
`<base>` is `origin/<default branch>` (on the default branch itself, the commit before this change). Tier 0 or 1-small: no model review. Tier 1: one `/caddis:cross-review`. Tier 2: two reviewers of two other vendors in one round. No `TIER:` line means tier 2.
<!-- /shared:cross-review-trigger -->

**3. PUSH** — to the repo's default branch (confirm the branch first; don't assume `main`):
```
git push origin <branch>
```
Confirm the push succeeded and the SHA is accepted by the remote. (Local-only lane: skip if there is
no remote, and note that nothing was pushed.)

## Step 4 — MONITOR CI (lane-specific)

**Gitea lane** — Poll the Gitea API using the token from `config/.env.gitea` (load it first):
```powershell
$envFile = Join-Path (Get-Location) "config/.env.gitea"
# ... (load the bot token from file — see deploy-local skill)
```
Track jobs in order: `lint_and_test` → `frontend_checks` (if present) → `deploy_prod` →
`release_metadata` → `notify`. Report status as each job completes. On failure, classify it and apply
the minimum fix (see `deploy-local` skill §6).

**GitHub lane** — Find the run id for the pushed SHA, then wait outside the Claude session via `ci-watch`:
```bash
gh run list --branch <branch> --limit 1                 # find the run id for the pushed SHA
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_lanes.py" ci-watch --run <run-id>
```
Exit codes: **0** pass → continue; **1** fail → read `FAILING:` and the gh output, classify, apply the minimum source fix; **3** could not tell → stop and report.
On failure, pull only the failing job logs:
```bash
gh run view <run-id> --log-failed                        # on failure, pull only the failing job logs
```
Fallback when `caddis_lanes.py` is not available: watch in-session with `gh run watch <run-id> --exit-status` (`gh-cli` skill).
Report each job's status as it resolves. On failure, classify it and apply the minimum source fix.

**Local-only lane** — no CI; skip monitoring.

## Step 5 — PROD / POST-DEPLOY VALIDATION
- **Gitea lane:** after `deploy_prod` succeeds — prod checkout SHA matches the pushed commit; NSSM
  services for this repo are Running; health endpoint green; version endpoint shows the expected
  SHA/CalVer (if exposed).
- **GitHub lane:** if the workflow deploys, validate against its target the same way (deployed SHA /
  health / version endpoint). If it's CI-only (no deploy job), confirm the run is green and stop.
- **Local-only lane:** run the app's smoke/health check locally if one exists; otherwise report that
  validation is limited to the green preflight.

## Step 6 — REPORT
```
Repo:            <name>
Pipeline:        gitea | github | local-only
Commit:          <sha> — <message>
CI jobs:         <job ✓ / ✗ per job, or "n/a (local-only)">
Prod/Target SHA: matches ✓ | n/a
Health:          green ✓ | n/a
Release tag:     <tag> → <sha> | n/a
```

## Programme triggers

Small work that does not meet a trigger skips its block.

**Trigger: Always, when the repo deploys on push.** No merge while a push run on the default branch is in progress. Check `gh run list --branch <default> --event push --status in_progress`; if a run is listed, wait for it. `python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_merge_chain.py"` does this check.

**Trigger: A peer session is known.** A relay or a SessionStart warning names another session on this repo. Before the merge, send each named peer session a message (SendMessage or the peer channel). It is a notice, never a request for permission.

**Trigger: Always, when the repo deploys on push.** After the merge, run `python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_prod_check.py" <sha>` with the repo's profile, `.caddis/prod-check.toml`. The script resolves a short SHA to the full SHA first, or refuses with exit 4. A repo with no profile gets items 1 and 2 only, and the script says so.

**Trigger: Two or more reviewed green PRs wait to merge.** Combine them into one release PR (the global rule of 2026-10-10): merge their branches into one release branch, run the gates once, open one release PR that links the components, then close the components with a link.

## Rules
- Never push before preflight gates are green.
- Never use `git add -A` without reviewing `git status` first.
- Do not edit a workflow file (`.gitea/workflows/` or `.github/workflows/`) to make a failing gate
  pass — fix the source.
- Gitea lane: tag-triggered runs after `release_metadata` are expected; verify `deploy_prod` is
  **skipped** in them.
- If health is red after deploy, report it immediately — do not attempt a silent re-deploy.

## Skill reference
Full procedures for the Gitea lane (CI monitoring, prod validation, queue triage, failure remediation)
are in the `deploy-local` skill (ships in the optional `caddis-extras` plugin — enable it with `claude plugin enable caddis-extras`). For the GitHub lane, the `gh-cli` skill covers `gh run`
usage. Load whichever matches the detected lane when a step needs more detail.
