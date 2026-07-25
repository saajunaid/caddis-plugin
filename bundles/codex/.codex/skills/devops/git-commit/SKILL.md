---
name: git-commit
description: Create well-structured conventional commit messages following Conventional Commits standard. Use when committing changes, preparing PRs, or generating changelogs.
---

# Git Commit Skill

Create meaningful, conventional commit messages that follow team standards.

## Trigger

Activate when:
- User asks to commit changes
- User needs help writing a commit message
- User asks "what should I commit this as?"

---

## Conventional Commit Format

```
<type>(<scope>): <subject>

[optional body]

[optional footer]
```

### Types

| Type | Description | Example |
|------|-------------|---------|
| `feat` | New feature | `feat(complaints): add priority filtering` |
| `fix` | Bug fix | `fix(auth): resolve session timeout issue` |
| `docs` | Documentation | `docs: update API documentation` |
| `style` | Formatting (no code change) | `style: fix indentation in models` |
| `refactor` | Code restructuring | `refactor(db): extract query builder` |
| `perf` | Performance improvement | `perf: add caching to dashboard` |
| `test` | Adding/fixing tests | `test: add complaint service tests` |
| `chore` | Maintenance | `chore: update dependencies` |
| `ci` | CI/CD changes | `ci: add pytest to GitHub Actions` |
| `build` | Build system/dependencies | `build: update webpack to v5` |
| `revert` | Revert a previous commit | `revert: revert feat(api) endpoint` |

### Scope

Optional area of change:
- `api` - Backend API changes
- `ui` - Frontend/Streamlit changes
- `db` - Database changes
- `auth` - Authentication
- `complaints` - Complaints feature
- `analytics` - Analytics feature

---

## Phase 1: Analyze Changes

### Actions

0. **Run a pre-commit quality gate (blocking)**
   ```bash
   # Python repos
   ruff check .

   # TypeScript/React repos
   npm run lint

   # If both stacks exist, run both.
   ```

   If lint fails, do not proceed to commit generation until fixed.

1. **Review staged changes**
   ```bash
   # If files are staged, use staged diff
   git diff --staged --stat
   git diff --staged

   # If nothing staged, check working tree
   git diff
   git status --porcelain
   ```

2. **Stage files if needed**
   ```bash
   # Stage specific files
   git add path/to/file1 path/to/file2

   # Stage by pattern
   git add *.test.*
   git add src/components/*
   ```

   **Never stage secrets** (`.env`, `credentials.json`, private keys).

3. **Categorize the changes**
   - What files were modified?
   - What was the primary purpose?
   - Are there multiple logical changes?

3. **Identify the commit type**
   - New functionality â†’ `feat`
   - Bug fix â†’ `fix`
   - Code improvement without behavior change â†’ `refactor`
   - Tests â†’ `test`
   - Documentation â†’ `docs`

---

## Phase 2: Craft the Message

### Subject Line Rules

1. **Use imperative mood**: "add" not "added" or "adds"
2. **No period** at the end
3. **50 characters or less** (hard limit: 72)
4. **Lowercase** after the colon

```
# âœ… Good
feat(complaints): add priority filter to dashboard
fix(api): handle null customer_id in query
refactor(db): extract database adapter class

# âŒ Bad
feat(complaints): Added priority filter to dashboard.  # Past tense, period
FEAT: ADD PRIORITY FILTER  # Uppercase, no scope
fix: various bug fixes  # Too vague
```

### Body (When Needed)

Include body when:
- Change needs explanation
- There's context that isn't obvious
- Breaking changes exist

```
feat(api): add complaint analytics endpoint

Add new endpoint for retrieving complaint statistics
including resolution times, category distribution, and
trend analysis.

This endpoint powers the new analytics dashboard.
```

### Footer (When Needed)

```
# Breaking change
feat(api)!: change complaint response format

BREAKING CHANGE: complaint.created_at now returns ISO format

# Issue reference
fix(ui): resolve dashboard loading error

Fixes #123
```

---

## Phase 3: Generate Message

### Template

Based on the changes, generate:

```markdown
## Suggested Commit Message

```
<type>(<scope>): <subject>

<body if needed>
```

### Reasoning
- Type: [Why this type was chosen]
- Scope: [Area of the codebase affected]
- Subject: [What the change does]
```

---

## Examples

### Simple Feature

**Changes**: Added a new filter dropdown to the complaints dashboard

```
feat(ui): add status filter to complaints dashboard
```

### Bug Fix with Context

**Changes**: Fixed issue where queries with special characters caused errors

```
fix(db): escape special characters in search queries

The search function was failing when users entered characters
like quotes or semicolons. Added proper escaping using
parameterized queries.

Fixes #42
```

### Refactoring

**Changes**: Moved database logic from routes to repository classes

```
refactor(api): extract database operations to repository layer

Move direct database calls from route handlers to dedicated
repository classes. This improves testability and follows
the separation of concerns principle.
```

### Multiple Files, Single Purpose

**Changes**: Updated multiple files to add logging

```
feat: add structured logging throughout application

- Add loguru configuration in config.py
- Replace print statements with logger calls
- Add request logging middleware
```

### Breaking Change

**Changes**: Changed API response format

```
feat(api)!: standardize API response envelope

BREAKING CHANGE: All API responses now wrapped in
{ "data": ..., "meta": { "timestamp": ... } } format.

Clients need to update response parsing logic.
```

---

## Quick Reference

When in doubt, ask yourself:

1. **What type of change is this?** â†’ Choose type
2. **What area does it affect?** â†’ Choose scope
3. **What does it do?** (in imperative) â†’ Write subject
4. **Why was this done?** â†’ Write body if needed
5. **Does it break anything?** â†’ Add BREAKING CHANGE if yes

---

## Git Safety Protocol

- NEVER update git config
- NEVER run destructive commands (`--force`, hard reset) without explicit user request
- NEVER skip hooks (`--no-verify`) unless user asks
- NEVER force push to main/master
- ALWAYS verify lint gate status before creating a commit message
- If a commit fails due to pre-commit hooks, fix the issue and create a NEW commit (don't amend the failed one)
- One logical change per commit
- Reference issues in footers: `Closes #123`, `Refs #456`

---

## Commit Message Checklist

- [ ] Type is appropriate for the change
- [ ] Scope identifies the affected area
- [ ] Subject uses imperative mood
- [ ] Subject is under 50 characters
- [ ] Body explains "why" if not obvious
- [ ] Breaking changes are marked with `!` and footer
- [ ] Related issues are referenced
- [ ] No secrets or credentials in staged files