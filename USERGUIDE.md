# caddis — User Guide

**caddis is a Claude Code harness** — a plugin (plus a shared pool of skills, subagents,
slash-commands, and hooks) that makes a single Claude Code session dramatically more capable and much
harder to derail. It's *agent-agnostic*: the same pool is exported to other AI CLIs (Copilot, Codex,
and more), and `CLAUDE.md`↔`AGENTS.md` are mirrors so every agent reads the same conventions.

---

## Quickstart (5 minutes)

```bash
# 1. Register the marketplace, then install the core plugin (always-on, lean context)
claude plugin marketplace add saajunaid/caddis-plugin
claude plugin install caddis@caddis

# 2. (optional) Add the long-tail skill library — cloud/data/media/etc. Off by default.
claude plugin install caddis-extras@caddis

# 3. In any repo, deploy the harness into the project
/setup-project-ai
```

Then a normal loop looks like:

```
/feature-plan      # (or /prd first) → writes .caddis/plans/<slug>.md, the durable spine
/implement         # executes the plan phase-by-phase, TDD, commit per phase
/ship              # express lane: commit → push → CI → prod (hotfixes; auto-detects the pipeline)
                   #   feature work: /ship-pr (PR → CI green, stops) then /ship-merge (deploy + cleanup)
/handoff           # ALWAYS end a session with this — writes the resume doc
```

**The one habit that matters most: end every session with `/handoff`.** It writes
`.caddis/relay.md`, which is automatically re-injected the next time you start — so you resume with
zero re-discovery instead of a cold, forgetful session.

---

## Why it exists (the problems it solves)

- **Context rot / session resume** — long sessions lose the thread. `/handoff` captures exact state
  into `relay.md`; a SessionStart hook re-injects it next time.
- **Knowledge evaporation** — hard-won findings vanish. A layered memory system + the
  `knowledge-transfer` subagent persist them into the right long-lived docs.
- **Plan drift over multi-session work** — a plan file is the durable, machine-readable spine that
  survives restarts and drives `/implement`.
- **Destructive mistakes** — a safety guard blocks secret/catastrophic writes and asks before
  dangerous shell/CI actions.
- **Same-vendor review blind spots & quota limits** — cross-vendor review and non-Anthropic model
  lanes (`/cross-review`).

---

## Key mental models

- **`.caddis/` is your repo's harness brain.** It holds `relay.md` (resume), `memory.jsonl`
  (auto-memory), `usage-log.jsonl`, `kb/` (knowledge base), `plans/`, and `workstreams.json`. It's
  repo-scoped and mostly git-ignored. Repos set up before the rename have `.claudster/` — everything
  reads both and **writes where the repo already lives**, so nothing breaks; run
  `/caddis:migrate-dir` when you want a repo converted.
- **Relay is the anti-context-rot spine between sessions.** You write it with `/handoff`; it
  auto-injects on start. You rarely open it by hand.
- **Plans-as-spine.** `.caddis/plans/<slug>.md` with a `## Tracker` is the source of truth
  `/implement` reads and updates. The plan is the intelligence; the executor just follows it.
- **Two-plugin context tiering.** `caddis` (core) is always on; `caddis-extras` (the big skill
  library) stays *off* until you need it, because every skill description is a standing context tax.
- **Model-portable by design.** Everything is markdown interpreted by a CLI. A skill's
  `model: opus|sonnet|haiku` is a logical tier, not a hardcoded vendor.

---

## Reference

### Slash commands

| Command | What it does |
|---|---|
| `/handoff` | End-of-session resume doc; runs `knowledge-transfer` first, writes `relay.md`, names one exact next step |
| `/feature-plan` | A phased, TDD-structured plan — the durable spine for multi-session work |
| `/prd` | Requirements discovery → a PRD (headless-safe; won't interrogate on terse input) |
| `/implement` | Headless plan executor — branch-only, TDD, commit-per-phase, updates the Tracker |
| `/tdd` | A strict red-green-refactor cycle for one unit of behavior |
| `/ship` | **Express lane**: commit → push → monitor deploy (auto-detects Gitea, GitHub Actions, or local-only). Right for hotfixes — pushes the default branch straight through |
| `/ship-pr` | **Reviewed lane ½**: push the feature branch safely (backup ref + `--force-with-lease` if rebased), open/update the PR, monitor its CI, **stop at green** with a mergeability verdict. Never merges |
| `/ship-merge [pr]` | **Reviewed lane 2/2**: merge an already-green, reviewed PR behind an explicit "this will DEPLOY" confirm, watch the deploy, validate prod, then clean up the branch — only on a green deploy |
| `/kb` | Rebuild the KB index (`.caddis/kb/DOC-MAP.md`) — create, reindex, prune, or check |
| `/usage-review [days]` | Analyze your usage log, surface prioritized harness tweaks, apply config changes |
| `/digress [reason]` · `/resume` | The **workstream stack** — park the current task on a detour, pop it back later |
| `/cross-review` | A second-vendor review of your current diff |
| `/mermaid-db [sql\|file\|object] [out]` | Turn a SQL proc/view/query/schema into a **Mermaid** diagram (git-diffable `.md`) |
| `/excalidraw-db [sql\|file\|object]` | Same, as an **Excalidraw** diagram for a design review / ARB / slide |
| `/setup-project-ai` | Install/refresh the harness into a project |
| `/migrate-dir` | Rename a pre-rename repo's `.claudster/` artifact dir to `.caddis/` — dry-run first, `git mv` so history follows. Opt-in; nothing breaks if you never run it |

**DB diagramming (`/mermaid-db`, `/excalidraw-db`).** Both take a SQL artifact — a file path, a
database object name (looked up via a DB MCP tool or read-only `sqlcmd`/`psql`), pasted SQL, or the
current file — and explain it as a diagram. The `db-diagram` skill extracts the structure
*deterministically* (via `sqlglot`) so diagrams diff cleanly and regenerate on schema change; the
model adds the business-terms explanation. Both are **read-only** (never DDL/DML) and **never guess
schema** (inferred-from-SQL-text-only elements are marked).

### Skills (the pool)

Skills are focused capability modules Claude loads on demand, grouped by category:

- **Coding** — api-design, backend-development, code-review, refactoring, security-review, sql…
- **Frontend** — frontend-design, css-architecture, react-dev, mockup, warm-editorial-ui…
- **Planning / Workflow** — brainstorming, golden-plan, writing-plans, preflight, context-curator…
- **Testing** — tdd-workflow, playwright, test-strategy, webapp-testing
- **Docs** — technical-writing, code-documentation
- **Data / DevOps / Media / Cloud** — database-design, git-commit, worktrees, mermaid, draw-io…

The core set ships in `caddis`; the long tail lives in `caddis-extras` (enable when needed).

### Subagents

Lean, own-context helpers that do a job and report back (they don't clutter your main thread):

- **anchor** — evidence-first verification for high-risk changes (read-only)
- **code-reviewer** — reviews a diff, returns a verdict + issue list
- **preflight** — validates a plan against the *actual* codebase before you build
- **tester**, **debug**, **codebase-audit**, **security-analyst**, **data-engineer**, **sql-expert**
- **knowledge-transfer** — captures durable lessons into your long-lived docs after a session

### The four-layer memory model

1. **Session relay** — `relay.md`, written by `/handoff`, injected at SessionStart/PreCompact.
2. **Dream Memory** — `memory.jsonl`, **automatic**: mines your session transcripts for
   failure-modes and red→green wins, decays over time, surfaces the top few at start. Secrets are
   redacted; it fails open.
3. **Knowledge base** — `.caddis/kb/*.md` indexed by `DOC-MAP.md`; a coverage check keeps links honest.
4. **Cross-repo memory** — durable per-repo facts under `~/.claude/projects/<slug>/memory/`.

### Hooks & safety

- **guard.py** (PreToolUse) — blocks secret/catastrophic writes, asks before destructive
  shell/CI/lockfile changes. Tunable via `.caddis/config.toml [guard]`.
- **auto_lint.py** (PostToolUse) — lints on Edit/Write.
- **inject_relay.py** / **session_end.py** — the SessionStart/Stop hooks behind relay + memory.

### Digression tracker

When a task detours into a different one, you don't lose the original:

```
/digress blocked on the auth bug     # parks the current plan+phase on a LIFO stack
...do the detour...
/resume                              # pops it back with its exact resume point
```

Parked work is surfaced at the top of every session start (`⛏ Parked workstream: …`). It's
metadata-only — it never touches your git working tree.

### Installing outside Claude Code

Per-harness bundles (Codex, Antigravity) are published under `bundles/` in this repo and installed
with `caddis-init` — see [README.md](./README.md#installing-outside-claude-code-codex-antigravity-).
