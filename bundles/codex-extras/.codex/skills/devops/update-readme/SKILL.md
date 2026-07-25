---
name: update-readme
description: Detect feature commits and update README sections (Features, API, Usage) with accurate repo-aware changes, then stage only README for a docs commit. Use when users add features/routes/components and want README maintained automatically.
---

# Update README Skill

Keep repository README files synchronized with delivered features using a deterministic git-first workflow.

## When To Use

Use this skill when users ask to:
- update README after feature work
- sync docs with recent commits
- document new API routes/components/usage
- create docs-only commit for README changes

## Core Guarantees

1. Only document capabilities that are evidenced in commit history and changed files.
2. Update the smallest relevant README sections:
   - **Features**
   - **API Reference**
   - **Usage**
3. Stage only README changes for a docs commit when requested.

## Workflow

### Phase 1 — Detect feature commits since last README update

1. Find last commit touching a README file:
   - `git log -n 1 --pretty=format:%H -- README.md **/README.md`
2. Collect feature commits after that point:
   - `git log <last_readme_commit>..HEAD --oneline --grep "^feat(\\(|:)"`
3. If no feature commits exist, do not fabricate updates; report "README already current".

### Phase 2 — Identify changed modules/routes/components

1. Compute changed files for feature commits:
   - `git diff --name-only <base>..HEAD`
2. Classify changes:
   - backend/API: `src/api`, `routers`, `services`, `endpoints`
   - frontend UI/routes: `frontend/src/pages`, `frontend/src/components`, `frontend/src/hooks`
   - usage/config: CLI docs, env files, setup paths
3. Extract evidence snippets from code/comments/tests where needed before writing docs.

### Phase 3 — Update only relevant README sections

1. Add concise feature bullets in **Features** with user-facing language.
2. Update **API Reference** only for changed/new endpoints and request/response behavior.
3. Update **Usage** with new flags, routes, setup steps, or examples.
4. Preserve existing README tone and formatting; avoid large rewrites unless requested.

### Phase 4 — Stage only README changes for docs commit

1. Stage README files only:
   - `git add README.md **/README.md`
2. Verify staged diff contains no non-README files.
3. Suggested conventional commit:
   - `docs(readme): document <feature summary>`

## Quality Checklist

- [ ] Every README update maps to an actual feature commit or changed file.
- [ ] No speculative/future functionality is documented.
- [ ] API examples match current code paths and payload names.
- [ ] Only README files are staged for docs-only commit.

## Anti-Patterns

- Updating README without checking commit/file evidence.
- Mixing code changes into the docs-only commit.
- Duplicating changelog text instead of task-oriented usage guidance.
- Rewriting entire README for a minor feature addition.
