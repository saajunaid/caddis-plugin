---
description: End-of-session handoff — capture exact state so the next session resumes with zero re-discovery
---

# /handoff — stop cleanly, write the resume doc

You are ending a work session. Produce/refresh the resume doc (`.caddis/relay.md`) so the next session
(you, a future you, or another agent on any tool) can resume immediately. This is the anti-context-rot checkpoint.

## Step 1 — capture learnings FIRST (knowledge-transfer)
**Before** gathering git signals or writing relay.md, decide on `knowledge-transfer` — and the default
is to run it.

- **Trigger (default ON):** if this session's `git diff` touched any code or config, OR you debugged
  anything / proved a non-obvious behavior → you **MUST** dispatch the `knowledge-transfer` subagent first.
- **Skip ONLY if** the session was purely read-only, design/planning, or discussion — nothing was built,
  fixed, or proven. When in doubt, dispatch. "I already wrote some docs by hand" is **not** a reason to
  skip — the subagent routes/consolidates across the right files and catches what you'd miss.
- It writes durable findings (root causes, workarounds, constraints, rejected approaches) into the right
  AGENTS.md (the canonical rules file) / instructions / runbooks. Docs only — never code.
- **Record the outcome** in relay.md's `## Learnings captured` line (below). A skip must state its reason.

## Step 2 — gather verified signals (don't guess)
```
git status --short
git branch --show-current
git log --oneline -5
```
Then read the active plan in `.caddis/plans/` (falling back to legacy `.github/plans/` if present) and its tracker.

**Crash / interrupted-work check.** Cross-check the tracker against `git status` + `git log`: if a phase is
marked in-progress but has **uncommitted changes** (work left mid-flight), or a phase is marked done with
**no commit** to back it, the last session was interrupted. Say so explicitly in `## Next step` ("resume
mid-phase N — `<files>` left uncommitted; re-run its tests first") so the next session doesn't assume a
clean phase boundary and lose or double-do the work.

**Digression check.** If this session abandoned a mid-flight plan for a *different* one (relay.md or the
tracker shows plan A in progress, but the work moved to plan B), suggest the user run `/digress` to park
plan A on the workstream stack — so its exact resume point survives and `/resume` can pop it back later.

## Step 3 — write the resume doc (overwrite) with exactly these sections
> **Where to write:** solo / single active branch → `.caddis/relay.md` (default).
> **Team / parallel branches** → write `.caddis/relay/<current-branch>.md` instead, so two
> developers never merge-conflict on one shared relay doc. The SessionStart hook prefers the
> per-branch file automatically when it exists, then `.caddis/relay.md`, then the legacy
> `.claude/relay/<branch>.md` and root `relay.md` (back-compat during the migration).
>
> A repo still on the pre-rename `.claudster/` won't see this relay until it's converted —
> `/caddis:migrate-dir` does that.

```markdown
# Relay — <feature>
**Updated:** <ISO timestamp>

## Current workstream
<Active plan path + which phase. One line on the goal.>

## Done (this session / across sessions)
- <evidence-backed bullet — cite file/commit, only what's actually complete>

## Next step (exact)
<The single next action. Include the command/phase. Add a fallback if blocked.>

## Read first on resume
- `<path>` — why it matters
- `.caddis/plans/<feature>.md` — the plan + tracker

## Validation state
<Commands run this session and their result: pass / fail / not-run. Be honest.>

## Open questions / blockers
<Decisions needed, ambiguities, anything unverified. "None" if truly none.>

## Learnings captured
knowledge-transfer: <✓ ran → files written | ✗ skipped → reason>

## Resume prompt
\`\`\`
Read relay.md, then the plan it points to. Continue from <phase/step>. Next action: <exact>.
\`\`\`
```

## Rules
- **One next action, by priority ladder.** `## Next step` names exactly ONE action — not a menu. Pick it in
  order: (1) interrupted mid-phase work → finish + commit it; else (2) the active plan's next not-started
  phase; else (3) the top open question/decision. Everything else is context, not the next step.
- Only verified facts and real paths. Mark anything unconfirmed as `Unknown`.
- Update the plan's tracker rows too (status + last commit) — relay and tracker must agree.
- Don't commit unless asked. Report where `relay.md` was written and the one next action.
- **Prune the Done section — two rules, both apply:**
  1. **Merge-based:** Phases already merged to `main` (confirmed by a tag or commit) must be compressed
     to a single line: `- **RW-N**: merged to main as vYYYY.MM.DD.N (<commit>) ✅`. Only the current
     in-progress phase keeps detailed bullets.
  2. **Count-based:** The Done section must contain at most **8 bullets total** after writing. If there
     are more, collapse the oldest into one summary line:
     `- [N prior milestones — see git log for full history]`
     Keep the 8 most recent bullets below it.
  Target: relay.md stays under ~80 lines on disk. inject_relay.py caps injection at 120 lines as a
  safety net, but the file itself should never reach that ceiling.
