---
name: ci-cd-pipeline
context: fork
description: CI/CD pipeline design and implementation for GitHub Actions, Azure DevOps, and general pipeline architecture. Use when creating build pipelines, deployment workflows, quality gates, environment promotion strategies, or automating release processes.
---

# CI/CD Pipeline Skill

Automate the path from commit to production. Every merge should be deployable.

## 1. When to Apply This Skill

**Trigger conditions:**
- Setting up CI/CD for a new project
- "Create a build and deploy pipeline"
- Adding quality gates to an existing pipeline
- Designing environment promotion strategy
- Troubleshooting pipeline failures or slow builds

## 2. Pipeline Architecture

### Standard Flow

```
Commit → Lint → Test → Build → [Quality Gate] → Deploy Staging → [Approval] → Deploy Production
```

### Pipeline Stages

| Stage | Purpose | Fail = Block? |
|-------|---------|--------------|
| **Lint** | Code style, formatting | Yes |
| **Type Check** | Static type errors | Yes |
| **Unit Test** | Logic correctness | Yes |
| **Integration Test** | Service interactions | Yes |
| **Build** | Compile, bundle, containerise | Yes |
| **Security Scan** | Vulnerabilities, secrets | Yes (critical), Warn (medium) |
| **Deploy Staging** | Validate in staging env | Yes |
| **Smoke Test** | Basic health check post-deploy | Yes |
| **Deploy Production** | Ship to users | Manual approval required |

## 3. GitHub Actions — Python Project

```yaml
name: CI
context: fork

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install ruff
      - run: ruff check .
      - run: ruff format --check .

  test:
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -e ".[test]"
      - run: pytest --cov=src --cov-report=xml -q
      - uses: codecov/codecov-action@v4
        with:
          file: coverage.xml

  build:
    runs-on: ubuntu-latest
    needs: test
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/build-push-action@v5
        with:
          context: .
          push: false
          tags: app:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

## 4. GitHub Actions — Node.js/TypeScript Project

```yaml
name: CI
context: fork

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: pnpm
      - run: pnpm install --frozen-lockfile
      - run: pnpm lint
      - run: pnpm typecheck
      - run: pnpm test -- --coverage
      - run: pnpm build
```

## 5. Quality Gates

Define pass/fail criteria for each stage.

```yaml
# quality-gates.yml (reference document)
gates:
  lint:
    ruff_errors: 0
    format_diff: 0
  test:
    min_coverage: 80
    max_test_duration_seconds: 120
    allowed_failures: 0
  security:
    critical_vulnerabilities: 0
    high_vulnerabilities: 0
  build:
    max_image_size_mb: 500
    max_build_time_minutes: 10
  deploy:
    smoke_test_pass: true
    health_check_pass: true
    rollback_on_error_rate: 5  # percent
```

## 6. Environment Promotion Strategy

```
Feature Branch → PR Review → Main → Staging → Production
                    │                   │           │
                    │                   │           └── Manual approval
                    │                   └── Auto-deploy on main merge
                    └── CI runs on every PR
```

| Environment | Deploy Trigger | Approval | Data |
|-------------|---------------|----------|------|
| **Dev** | Every push to branch | None | Synthetic/mock |
| **Staging** | Merge to main | Automatic | Production-like (anonymised) |
| **Production** | Tag or manual | Required (2 reviewers) | Real |

## 7. Secrets Management

```yaml
# ✅ GOOD: Use GitHub Actions secrets
env:
  DATABASE_URL: ${{ secrets.DATABASE_URL }}
  API_KEY: ${{ secrets.API_KEY }}

# ✅ GOOD: Use OIDC for cloud auth (no long-lived credentials)
- uses: aws-actions/configure-aws-credentials@v4
  with:
    role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
    aws-region: eu-west-1

# ❌ BAD: Hardcoded secrets in workflow
env:
  API_KEY: "sk-abc123"  # NEVER DO THIS
```

**Rules:**
- Never commit secrets to the repository
- Use environment-scoped secrets (staging secrets ≠ production secrets)
- Rotate secrets on a schedule (90 days max)
- Use OIDC federation over long-lived credentials where possible

## 8. Caching Strategy

```yaml
# Python pip cache
- uses: actions/setup-python@v5
  with:
    cache: pip

# Node.js pnpm cache
- uses: actions/setup-node@v4
  with:
    cache: pnpm

# Docker layer cache
- uses: docker/build-push-action@v5
  with:
    cache-from: type=gha
    cache-to: type=gha,mode=max

# Custom cache (e.g., test fixtures)
- uses: actions/cache@v4
  with:
    path: .test-cache
    key: test-fixtures-${{ hashFiles('tests/fixtures/**') }}
```

## 9. Pipeline Performance

Keep CI fast. Developers won't wait for slow pipelines.

| Target | Goal |
|--------|------|
| Lint + type check | < 2 minutes |
| Unit tests | < 5 minutes |
| Full pipeline (PR) | < 15 minutes |
| Deploy to staging | < 5 minutes |

**Optimisation techniques:**
- Run lint and test in parallel (separate jobs)
- Cache dependencies aggressively
- Use `concurrency` to cancel outdated runs
- Split slow test suites with `pytest -x --dist=loadgroup`
- Use Docker layer caching for builds

## 10. Rollback Strategy

| Approach | Speed | Complexity |
|----------|-------|------------|
| **Revert commit** | Fast (minutes) | Low — git revert + re-deploy |
| **Blue-green deploy** | Instant (seconds) | Medium — swap traffic target |
| **Canary rollback** | Instant | High — requires traffic splitting |
| **Database rollback** | Slow, risky | High — only if migration is reversible |

**Rule:** Always prefer forward-fix (deploy a fix) over rollback. Rollback is the escape hatch, not the default.

## 11. Anti-Patterns

| Anti-Pattern | Problem | Fix |
|---|---|---|
| No CI on PRs | Bugs merge to main | Run full pipeline on every PR |
| Deploy from local machine | "Works on my machine" | Deploy only from CI/CD |
| Single mega-job | Slow, hard to debug | Split into parallel stages |
| No caching | 10-min installs every run | Cache deps, Docker layers |
| Manual production deploy | Human error, inconsistent | Automated with approval gate |
| Secrets in code | Compromised on push | Use secrets manager + OIDC |
| No rollback plan | Broken deploy = downtime | Blue-green or revert strategy |
| Build passes but output is wrong | Config error baked into assets | Post-build output validation gate (§12) |

## 12. Frontend Build Output Validation

A successful build (exit code 0) does not guarantee correct output. Configuration errors — especially wrong asset path prefixes — produce valid bundles that break at runtime. Add a **post-build validation step** in CI:

### 12.1 Subpath Base-Path Check

When a frontend is deployed under a URL subpath (e.g. `/my-app/`), the built `index.html` must reference assets with that prefix. Vite's `base` config controls this, and it can be accidentally changed.

```yaml
# GitHub Actions / Gitea Actions example
jobs:
  frontend-checks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
      - run: npm ci
        working-directory: frontend
      # Build with production mode to activate conditional base path
      - run: npx vite build --mode production
        working-directory: frontend
      - name: Validate production base path
        working-directory: frontend
        run: |
          if ! grep -q '/my-app/assets/' dist/index.html; then
            echo "FAIL: Built index.html does not reference /my-app/assets/"
            echo "Check vite.config.ts base setting"
            exit 1
          fi
          echo 'Base-path guard passed'
```

**Key points:**
- Build with `--mode production` — without it, mode-conditional `base` stays as `"/"` and the guard always fails
- This catches the exact scenario where someone changes `base: mode === "production" ? "/my-app/" : "/"` to `base: "/"`
- The same check should also run in the deploy script as a belt-and-suspenders guard (abort before service restart)

### 12.2 General Output Validation Patterns

| Check | Command | When to use |
|-------|---------|-------------|
| Subpath prefix | `grep -q '/{subpath}/assets/' dist/index.html` | Subpath deployments |
| Non-empty dist | `test -d dist/assets && ls dist/assets/*.js` | Always |
| Bundle size budget | `du -sh dist/ \| awk '{print $1}'` | When size regressions matter |
| No source maps in prod | `! ls dist/assets/*.map 2>/dev/null` | Production builds |
