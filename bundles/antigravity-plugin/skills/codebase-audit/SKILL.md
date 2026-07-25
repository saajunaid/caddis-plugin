---
name: codebase-audit
context: fork
description: Systematic codebase audit methodology for unfamiliar codebases before architecture or implementation work. Use for new codebase, unfamiliar codebase, pre-implementation audit, codebase review, technical due diligence, or onboarding to an existing project. Produces AUDIT-FINDINGS.md and QUESTIONS.md. Routes to Architect, Planner, or Code Reviewer agents.
---

# Codebase Audit Skill

Systematic 6-step audit for entering an unfamiliar codebase before architecture changes, major features, or refactoring. Do not guess patterns — audit first.

## 1. When to Apply This Skill

**Trigger conditions:**
- "I'm new to this codebase"
- "Audit this project before we start building"
- "I need to understand what's here before changing it"
- "Pre-implementation review"
- Any major feature in a codebase you haven't worked in this session

**Do not skip the audit** even when the task seems small — hidden coupling causes broken assumptions.

## 2. Audit Scope — 20 Areas

| # | Area | What to Look For |
|---|---|---|
| 1 | **Architecture** | Monolith/microservice/monorepo, layer separation, module boundaries |
| 2 | **Entry Points** | Main files, router setup, CLI entry, exports index |
| 3 | **Framework & Runtime** | React version, Next.js, FastAPI, Django, Node version, Python version |
| 4 | **Dependencies** | `package.json`/`pyproject.toml` — packages, versions, peer deps, outdated |
| 5 | **Code Quality** | Lint config, formatter, TypeScript strict mode, type coverage |
| 6 | **Testing** | Test runner, coverage %, which layers are tested, missing tests |
| 7 | **Security Posture** | Auth implementation, env var usage, hardcoded secrets, CORS |
| 8 | **Documentation** | README completeness, inline comments, API docs |
| 9 | **Performance Signals** | Caching, lazy loading, database indexes, N+1 queries |
| 10 | **DevOps / CI** | Build commands, CI config, deployment method, Dockerfile |
| 11 | **API Design** | REST conventions, versioning, error response format, input validation |
| 12 | **Data Layer** | ORM vs raw SQL, migration strategy, schema location |
| 13 | **State Management** | Client state (Zustand, Redux, Context), server state (React Query) |
| 14 | **Error Handling** | Global error boundary, unhandled promise rejections, logging |
| 15 | **Environment Config** | `.env.example`, `pydantic-settings`, config validation on startup |
| 16 | **Dead Code / Tech Debt** | TODOs, commented-out code, unused packages, deprecated calls |
| 17 | **Naming Conventions** | Consistent file/folder naming, component vs module patterns |
| 18 | **Shared Libraries** | Utility functions, hooks, services — shared vs duplicated |
| 19 | **Accessibility** | ARIA usage, keyboard nav, color contrast, skip-nav |
| 20 | **Observability** | Logging format, tracing, health endpoints, error reporting |

## 3. 6-Step Audit Method

### Step 1 — Map the Repository
```
actions:
  - List top-level directories and understand intent of each
  - Identify the project type (app, library, monorepo, microservice)
  - Read README.md fully — note setup instructions, known issues
  - Check for CONTRIBUTING.md, ARCHITECTURE.md, or ADR folders
```

### Step 2 — Find Entry Points
```
actions:
  - Identify main application entry (main.py, app.py, src/index.ts, src/main.ts)
  - Trace the request lifecycle from entry to response (1 complete path)
  - Identify router/controller/handler layers
  - Find test entry (jest.config.ts, vite.config.ts, pytest.ini/pyproject.toml)
  - Find build entry (package.json scripts, Makefile, Dockerfile)
```

### Step 3 — Dependencies and Versions
```
actions:
  - Read package.json / pyproject.toml — note major dependencies and versions
  - Check for deprecated or significantly outdated packages
  - Identify direct vs transitive dependency conflicts
  - Note peer dependency version mismatches
  - Check for security advisories (mental note or npm audit / pip-audit)
```

### Step 4 — Audit by Severity
```
For each area in §2, assign:
  🔴 CRITICAL — Security vulnerability, data loss risk, broken functionality
  🟡 WARNING  — Performance issue, tech debt, missing validation
  🟢 NOTE     — Style inconsistency, minor improvement opportunity
  ⚪ OK       — Meets expectations, no action needed
```

### Step 5 — Compile Questions
```
For every assumption or ambiguity discovered:
  - Business context: "Why does X exist? Is it still needed?"
  - Architecture: "Is this pattern intentional or historical?"
  - Implementation: "Is there a newer pattern preferred for this?"
  - Scope: "Which areas are off-limits for this change?"
```

### Step 6 — Write Deliverables
Write two files in the project root (or `docs/` if it exists):
- `AUDIT-FINDINGS.md`
- `QUESTIONS.md`

## 4. Output Templates

### `AUDIT-FINDINGS.md`
```markdown
# Codebase Audit Findings

**Project**: [name]
**Audited**: [date]
**Scope**: [what was covered]

## Summary
[2–3 sentence high-level assessment]

## Critical Findings 🔴

### CRIT-001: [Title]
**File**: `path/to/file.ts` (line N)
**Issue**: [What is wrong and why]
**Risk**: [What can go wrong]
**Recommendation**: [Specific fix]

## Warnings 🟡

### WARN-001: [Title]
**File**: `path/to/file.py`
**Issue**: [What needs attention]
**Recommendation**: [Specific improvement]

## Notes 🟢

- [Minor observations, style, preferences]

## Architecture Overview
[Brief description of what was found — layers, patterns, notable design decisions]

## Scope for Current Task
Based on the requested change, these areas are in scope: …
These areas should NOT be touched: …
```

### `QUESTIONS.md`
```markdown
# Pre-Implementation Questions

**For**: [next agent or human reviewer]
**Context**: [what we're about to build]

## Blocking Questions (must answer before code changes)

### Q1: [Question]
**Context**: [why this matters]
**Impact if wrong**: [what breaks]

### Q2: [Question]

## Advisory Questions (inform decisions but don't block)

### Q3: [Question]

## Assumptions Made
If we proceed without answers, these assumptions apply:
- [assumption 1]
- [assumption 2]
```

## 5. Severity Tags

| Tag | Code | Meaning |
|---|---|---|
| 🔴 Critical | `CRIT-NNN` | Fix before any changes proceed |
| 🟡 Warning | `WARN-NNN` | Address in current or next sprint |
| 🟢 Note | `NOTE-NNN` | Backlog item or stylistic observation |
| ⚪ OK | — | No action needed |

## 6. Handoff Guidance

After completing the audit:

| Finding Type | Route To |
|---|---|
| Architecture redesign needed | `@Architect` — provide `AUDIT-FINDINGS.md` |
| Implementation can proceed with caution | `@Planner` — provide findings + questions |
| Major quality/security issues | `@Code-Reviewer` + `@Security-Analyst` |
| Only minor notes, clear path | Proceed directly with `@Implement` or `@Anchor` |

### Prompt template for handoff:
```
@[Agent]: I've completed a codebase audit. 
Findings: [link or inline AUDIT-FINDINGS.md]
Blocking questions: [key Q from QUESTIONS.md]
The task is: [original task description]
Please [design solution / create plan / review / implement] with these findings in mind.
```

## 7. Checklist

- [ ] README.md read fully
- [ ] Entry point traced end-to-end (one complete request/render cycle)
- [ ] All 20 audit areas assessed (even if just ⚪ OK)
- [ ] Critical findings have file + line citation
- [ ] `AUDIT-FINDINGS.md` written to disk
- [ ] `QUESTIONS.md` written to disk
- [ ] Blocking questions identified separately
- [ ] Agent handoff prompt prepared
