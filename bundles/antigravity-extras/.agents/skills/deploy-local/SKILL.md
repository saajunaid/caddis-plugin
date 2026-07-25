---
name: deploy-local
description: End-to-end local deployment loop for Gitea-hosted projects. Use when the user wants to commit on dev, push to remote, monitor the golden CI/build/deploy workflow, validate prod on the configured prod host, and fix lint/test/pipeline failures until deployment is healthy.
---

# Deploy Local Skill

Run reliable local-to-prod delivery for repositories hosted on a self-hosted Gitea.

## When To Use

Use this skill when requests include any of:
- "commit and deploy"
- "commit and push"
- "push and monitor pipeline"
- "watch prod deploy"
- "monitor deployment in prod"
- "fix CI failures"
- "lint/test failing in pipeline"
- "stuck in queue"

## Required Companion Skills

Load these first when they exist (your org may ship private deploy skills):
- your org's `golden-workflow` skill (CI/CD workflow contract)
- your org's `windows-deployment` skill (NSSM + reverse proxy)
- `.github/skills/devops/ci-cd-pipeline/SKILL.md`
- `.github/skills/devops/git-commit/SKILL.md`

Optional:
- `.github/skills/devops/gh-cli/SKILL.md` for issue/PR linking
- `.github/skills/workflow/verification-loop/SKILL.md` for stricter local validation loops

## Local Platform Defaults (configure per project)

Resolve these from your project config (e.g. a repo-local `config/.env.gitea`) — do not hardcode:
- Gitea UI / API base: `$env:GITEA_BASE_URL` (e.g. `http://gitea.example:8090`, API at `.../api/v1`)
- Repo org/owner: `<org>`
- Expected non-prod runner label: `dev`
- Expected prod runner label: `prod`
- Prod host: `$env:PROD_HOST`
- Prod checkout root: `<prod-checkout-root>\<repo>`

## Golden Deploy Model

The deploy-critical path is SHA-driven:
1. A push to `main` triggers the canonical `.gitea/workflows/ci.yml`.
2. `lint_and_test` and any repo-relevant frontend checks run on `dev`.
3. `deploy_prod` runs on `prod` only after gates pass.
4. Prod fetches, resets, and verifies the expected commit SHA.
5. Prod installs/builds/restarts app-owned NSSM services.
6. Prod health and version endpoints are verified.
7. `release_metadata` creates/pushes the CalVer Git tag only after deploy success.
8. A tag-triggered workflow run may occur, but deploy/release jobs must be skipped for tag refs.

CalVer is release metadata, not the deploy identity. Do not reintroduce tag-first deploy logic.

## Phase 1: Preflight

1. Confirm repo root and current branch.
2. Run `git status --short`.
3. Identify the repo's actual gates from `.gitea/workflows/ci.yml`; do not invent database or frontend gates.
4. Run local quality gates that mirror CI where feasible **before any commit**:
  - Backend repos: `ruff check .` (required), then format/tests as configured.
  - Frontend repos: lint/typecheck/build as configured.
  - Full-stack repos: run both backend and frontend gates.
  - Repo-specific data/database checks only when the repo declares that capability.
5. If a gate fails, fix source code first before changing workflow logic.

## Phase 2: Commit + Push

1. Confirm preflight quality gates are green (no failing `ruff`/lint checks).
2. Stage only intended files.
3. Commit with a conventional message.
4. Push to the target branch, normally `main` for prod deploy.
5. Capture commit SHA and remote ack.

Example:

```powershell
git status --short
git add <files>
git commit -m "fix(ci): resolve deploy health check"
git push origin main
git rev-parse HEAD
```

## Phase 3: CI and Deploy Monitoring

Before calling the Gitea API, normalize token variables from the repo-local
`config/.env.gitea` file when it exists. The shell environment can be stale even
when the repo has a valid token file.

```powershell
$envFile = Join-Path (Get-Location) "config/.env.gitea"
if (Test-Path $envFile) {
  Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#") -or $line -notmatch "=") { return }
    $key, $value = $line -split "=", 2
    if ($key -in @("GITEA_TOKEN", "REPO_API", "GITEA_BASE_URL")) {
      Set-Item -Path "Env:$($key.Trim())" -Value $value.Trim().Trim('"').Trim("'")
    }
  }
}
```

Monitor the run lifecycle in Gitea:
1. Find the latest `ci.yml@refs/heads/main` run for the pushed SHA.
2. Track jobs in order:
   - `lint_and_test`
   - `frontend_checks` when present
   - `deploy_prod`
   - `release_metadata`
   - `notify`
3. If a tag-triggered run appears after release metadata, verify `deploy_prod` and `release_metadata` are skipped.
4. If a gate fails:
   - classify as lint, format, test, build, workflow-runtime, deploy-script, prod-env, release-metadata, or infra-runner.
   - patch the smallest safe fix.
   - rerun from commit/push.

Gitea API shape:

```powershell
$headers = @{ Authorization = "token $env:GITEA_TOKEN" }
$runs = Invoke-RestMethod -Uri "$env:GITEA_BASE_URL/api/v1/repos/<org>/<repo>/actions/runs?limit=10" -Headers $headers
$run = $runs.workflow_runs |
  Where-Object { $_.head_sha -eq "<expected-sha>" -and $_.path -like "ci.yml@refs/heads/main" } |
  Select-Object -First 1
$jobs = Invoke-RestMethod -Uri "$env:GITEA_BASE_URL/api/v1/repos/<org>/<repo>/actions/runs/$($run.id)/jobs" -Headers $headers
$jobs.jobs | Select-Object name,status,conclusion,started_at,completed_at
```

## Phase 4: Prod Validation

For Windows prod flow, validate:
1. Prod checkout reached the expected SHA.
2. App-owned NSSM services are running.
3. App ports are listening and owned by the app, not another project.
4. Health endpoint returns success.
5. Version endpoint returns the expected SHA/CalVer metadata when the repo exposes it.
6. Post-deploy git dirtiness contains only allowed generated files.

Example:

```powershell
Invoke-Command -ComputerName $env:PROD_HOST -ScriptBlock {
  $root = "<prod-checkout-root>\<repo>"
  Set-Location $root
  [pscustomobject]@{
    Head = (git rev-parse HEAD)
    Branch = (git branch --show-current)
    Status = ((git status --short) -join '; ')
    Services = Get-Service -Name "app-<short>-*" -ErrorAction SilentlyContinue |
      Select-Object Name,Status,DisplayName
    ApiPort = Get-NetTCPConnection -LocalPort <api-port> -State Listen -ErrorAction SilentlyContinue |
      Select-Object LocalAddress,LocalPort,OwningProcess
    Health = Invoke-RestMethod -Uri "http://127.0.0.1:<api-port>/health" -TimeoutSec 5
    Version = Invoke-RestMethod -Uri "http://127.0.0.1:<api-port>/api/version" -TimeoutSec 5
  }
}
```

Use windows-deployment skill patterns for NSSM and reverse proxy checks.

## Phase 4.5: Release Metadata Validation

Validate release metadata after prod health is confirmed:
1. The main push run's `release_metadata` job succeeded or was intentionally skipped by policy.
2. A CalVer tag points at the deployed SHA.
3. A tag-triggered run, if created, did not redeploy.

Do not mark production unhealthy solely because a release tag failed after a successful deploy. Report it as a release metadata failure and fix it separately unless it affects service health.

```powershell
git fetch --tags --force
git tag --points-at <deployed-sha> | Where-Object { $_ -match '^v\d{4}\.\d{2}\.\d{2}\.\d+$' }
```

## Phase 5: Queue / Runner Triage

If a run is stuck waiting:
1. Verify workflow `runs-on` labels match available runners.
2. Check runner service health on the correct host.
3. Check workflow `concurrency` groups for blocking in-progress jobs.
4. Cancel stale runs only if policy allows.

Do not change runner labels or re-register runners from an app repo.

## Phase 6: Failure Auto-Remediation Rules

### Lint/Format Failures
- Fix code directly and keep style-consistent.
- Rerun local lint before push.

### Test Failures
- Fix failing code/tests according to project policy.
- Keep behavior-preserving unless feature changes are requested.

### Workflow Runtime Failures
- Fix parser/shell/exit-code handling in workflow YAML.
- Ensure native command failures are fatal in PowerShell steps.
- Preserve the golden job graph unless the repo has a justified exception.

### Build/Deploy Failures
- Fix config or script with minimal blast radius.
- Verify prod expected SHA, NSSM service state, port ownership, health, and version endpoint.
- Do not restart or relabel the shared prod runner to fix an app deploy.

### Release Metadata Failures
- Fix `release_metadata` separately after confirming prod is healthy.
- Do not make deploy depend on pre-deploy tags or workflow output plumbing.

## Exit Criteria

All must be true:
1. Local applicable lint/test/build checks pass.
2. Push succeeded and commit SHA is recorded.
3. The relevant `ci.yml@refs/heads/main` run completed.
4. Required jobs completed with expected conclusions.
5. Prod checkout matches the pushed SHA when deploy was expected.
6. Prod health endpoint is green when deploy was expected.
7. Release metadata is created or accurately reported as a separate non-health failure.
8. Notify emitted the real success/failure signal.

## Report Template

```markdown
## Deploy Local Report
- Repo:
- Branch:
- Commit:
- CI Run:
- Gate Results:
  - lint/test:
  - frontend:
  - deploy:
  - release_metadata:
  - notify:
- Prod Validation:
  - host:
  - SHA:
  - services:
  - health:
  - version:
- Fixes Applied:
- Final Status:
- Follow-ups:
```

## Anti-Patterns

- Treating stale terminal output as current truth.
- Changing workflow orchestration before fixing clear source-code lint/test failures.
- Making quality gates non-blocking to force deployment.
- Declaring queue issues fixed without verifying runner availability and label alignment.
- Reintroducing tag-first deploy logic.
- Treating tag-triggered skipped deploy jobs as failures.
- Changing shared runner services from an app repo.
