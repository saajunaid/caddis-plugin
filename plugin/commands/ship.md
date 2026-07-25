---
description: Commit, push, and monitor the deploy pipeline (auto-detects Gitea, GitHub Actions, or local-only)
argument-hint: "[commit message]"
---

# /ship — commit → push → CI → prod

Ship the current working changes via this repo's actual delivery pipeline. The pipeline differs per
repo, so **detect it first**, then follow the matching lane. Preflight, staging, and commit are
identical across lanes; only monitoring and validation differ.

> **This is the express lane** — on repos where a push to the default branch deploys, `/ship` sends
> work straight to prod with no review pause. Right for a hotfix. **For feature work, use the
> reviewed lane instead: `/ship-pr`** (open a PR, monitor CI, stop at green) **→ `/ship-merge`**
> (merge the green PR behind a deploy-confirm, validate, clean up).

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

**GitHub lane** — Watch the run the push triggered via the `gh` CLI:
```
gh run list --branch <branch> --limit 1                 # find the run id for the pushed SHA
gh run watch <run-id> --exit-status                      # stream until done; non-zero on failure
gh run view <run-id> --log-failed                        # on failure, pull only the failing job logs
```
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
are in `skills/devops/deploy-local/SKILL.md`. For the GitHub lane, the `gh-cli` skill covers `gh run`
usage. Load whichever matches the detected lane when a step needs more detail.
