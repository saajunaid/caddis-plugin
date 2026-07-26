# {{PROJECT_NAME}} — Project Memory (canonical rules)

> **This is the canonical rules file.** Every coding agent reads it: Claude Code (via a one-line
> `@AGENTS.md` import in `CLAUDE.md`), OpenAI Codex CLI, and Antigravity (`agy`) all load `AGENTS.md`
> directly. `CLAUDE.md` is a thin shim — it imports this file and adds only Claude-native
> conveniences. **The laws and the harness are identical across agents;** only native conveniences
> differ. Keep durable project rules HERE, never in the shim.

## What this project is
{{PROJECT_DESCRIPTION}}

**Stack:** {{STACK_SUMMARY}}
{{STACK_REFERENCE_LINE}}

## The Laws (non-negotiable)
1. **TDD always.** No production code without a failing test first. Red → Green → Refactor. A behavior
   change must start with a failing test. Never write the test after the code and call it TDD.
2. **No absolute paths.** Resolve from file/project root. Portable always.
3. **No silent failures.** Specific exceptions, logged. Never swallow errors without a trace.
4. **Verify, don't assume.** Run the build/lint/test before claiming done. State what you ran.
5. **Honest status.** "Partially done, here's what remains" beats a false "done". Report failures
   with their output. If a step was skipped, say so.
6. **Stay in scope.** Do the phase's work and stop at its exit gate. Don't gold-plate.

## The Development Harness (how we work)
Every non-trivial change follows this loop. The **plan file is the durable spine** — it survives
session death, so progress is never lost to context limits.

```
1. PLAN      write a phased plan to .caddis/plans/<feature>.md
2. per phase:
   a. RED       write the failing test first   (TDD — see Law 1)
   b. GREEN     minimal code to pass
   c. REFACTOR  clean up, tests stay green
   d. VERIFY    run tests + lint; do heavy reads (audit, review, preflight) as a bounded,
                summarized step (Claude Code: dispatch a subagent that reports back)
   e. CHECKPOINT  update the plan's tracker → commit
3. END       update .caddis/relay.md so the next session resumes (read it first on resume)
```

### Context discipline (defense against context rot)
Anything that **reads a lot but writes a little** — codebase audit, review, preflight, test runs,
security scan — should run as a **bounded step whose only output is a conclusion**, not a raw dump.
Claude Code has subagents with their own context for exactly this; agents without a separate context
(Codex, agy) do the heavy read as a distinct step and summarize into the plan or a doc under
`.caddis/agent-docs/` before continuing. This is the primary defense against session overflow.

### Resuming a session
On a fresh session read in order: `.caddis/relay.md` (if present) → the active plan in
`.caddis/plans/` → its tracker. The conversation is disposable; these files are the truth.

## Always-active conventions
- **Commits**: Conventional Commits (`feat:`, `fix:`, `test:`, `chore:`). One logical change per commit.
- **Terse**: lead with the answer; results/code over prose.
- **Secrets**: never commit; keep env/config secrets git-ignored. Never print credentials.
- **Document frontmatter**: Every descriptive Markdown deliverable you write (plan, PRD, ADR, design doc,
  runbook, analysis, handoff) must open with a YAML frontmatter block:
  ```yaml
  ---
  type: plan|prd|adr|design|runbook|handoff|analysis|review
  status: draft|current|done|superseded
  feature: <feature-slug>
  creation-agent: caddis
  Original Author: <agent or human name>
  Creation Date: <YYYY-MM-DDTHH:MM:SSZ>
  Creating Model: <exact model ID>
  ---
  ```
  On update, add/refresh: `Last Author`, `Last Updated`, `Last Model Used`.
  Do NOT add frontmatter to: `relay.md`, `AGENTS.md`, `CLAUDE.md`, skill files, or agent config files.

## Where things live
| Need | Location |
|---|---|
| Reference-doc index (the meta-KB) — **read first** | `.caddis/kb/DOC-MAP.md` |
| Every UI page → endpoints → DB (frontend repos) | `UI_PAGE_GUIDE.md` |
| Active plans | `.caddis/plans/<feature>.md` |
| PRDs | `.caddis/prd/<feature-slug>.md` |
| Standing prompts / drivers / specs handed to an agent | `.caddis/prompts/` |
| Review output (code-review, cross-review) | `.caddis/reviews/` |
| ADRs, design docs, runbooks | `docs/adr/`, `docs/design/`, `docs/runbooks/` (team-facing, not tool scratch) |
| Agent-produced docs (evals, reviews, debug) | `.caddis/agent-docs/` |
| Session resume doc | `.caddis/relay.md` |
| Per-area conventions | `src/AGENTS.md`, `frontend/AGENTS.md`, `tests/AGENTS.md` (as present) |

**`.caddis/` is the default home for working artifacts.** A plan → `.caddis/plans/`, a PRD →
`.caddis/prd/`, the KB → `.caddis/kb/`, a prompt/driver/spec → `.caddis/prompts/`, a review →
`.caddis/reviews/`. Interpret an unqualified reference ("write a plan", "save this prompt")
accordingly — never scatter these to the repo root or `.github/` (the latter is often a published/
synced tree in harness-authoring repos).

> **Write where the repo lives.** Repos created before the rename use `.claudster/` instead. Both
> work — reads try `.caddis/` then `.claudster/` — but always write to whichever this repo already
> has, never both. `/caddis:migrate-dir` converts a repo when you want it converted.

### Doc discipline (the KB can't silently rot)
Read `.caddis/kb/DOC-MAP.md` first to find the right reference doc, then read it on demand. When you
add/rename/remove a route or a curated reference doc, update `UI_PAGE_GUIDE.md` / `DOC-MAP.md` in the
**same change** — `scripts/check_doc_coverage.py` runs at the pre-push gate and **blocks** on a missing
route or a dangling doc-map link.

## Conventions & resources (plain files — read whatever the agent)
- Per-area detail: `src/AGENTS.md`, `frontend/AGENTS.md`, `tests/AGENTS.md` (as present). Each folder's
  `CLAUDE.md` is a shim that imports its `AGENTS.md`.
- Reusable how-to: the caddis plugin's skills, invoked by name (e.g. `fastapi-dev`) — auto-triggered
  when a task matches; not a project file. Codex/agy read the skill markdown directly.
- Subagent briefs reusable as checklists: `.claude/agents/{tester,code-reviewer,preflight}.md`
  (if vendored under `.claude/`, else provided by the caddis plugin).
- Commands as runnable procedures: `.claude/commands/{feature-plan,tdd,prd,handoff}.md`
  (if vendored under `.claude/`, else provided by the caddis plugin).
- Commits: Conventional Commits. Terse output. Never commit secrets.
