---
name: setup-project-ai
description: "Install or refresh the agent-agnostic development harness in a project — an AGENTS.md-canonical rules hierarchy (root + per-folder) with a CLAUDE.md @import shim beside each, lean subagents, slash commands, settings.json, and the frontend/python test env. USE THIS SKILL when setting up AI resources on a new or existing project, bootstrapping the rules files (AGENTS.md/CLAUDE.md), adding subagents/commands, or when the user says 'set up the harness', 'setup-project-ai', 'generate CLAUDE.md', 'onboard this project to Claude Code / Codex / agy', or runs /setup-project-ai. Combines a deterministic generator (scripts/setup_project_ai.py) for the must-not-vary mechanics with an AI enrichment step that curates project-specific AGENTS.md content."
---

# setup-project-ai

Produce a working, TDD-first, context-rot-resistant dev harness for any project. Two layers:
**deterministic** (a Python generator — mechanics that must not vary) + **generative** (you — curating
project-specific AGENTS.md content and verifying). Proven in the Phase 0 spike.

## When to use
- New project (e.g. freshly bootstrapped from a template) needs its Claude Code harness.
- Existing project moving to Claude Code / Codex.
- Refreshing the harness after the canonical templates improved (`--force`).

## What it produces
```
AGENTS.md                 canonical root rules (identity + harness loop + laws + pointers) — every agent reads it
CLAUDE.md                 root @AGENTS.md import shim + a small Claude-native block (subagents/skills/commands)
src/AGENTS.md             backend conventions   (when a Python/FastAPI backend is detected)  + src/CLAUDE.md shim
frontend/AGENTS.md        frontend conventions  (when React/Vite is detected)                + frontend/CLAUDE.md shim
tests/AGENTS.md           test/TDD conventions  (when pytest/tests are detected)             + tests/CLAUDE.md shim
.claude/agents/*          lean subagents: tester, code-reviewer, preflight
.claude/commands/*        feature-plan, tdd, prd, handoff, setup-project-ai
.claude/settings.json     stack-tuned permissions (pipeline MCP off by default)
```
Each `CLAUDE.md` is a thin `@AGENTS.md` import shim — Claude Code inlines the sibling AGENTS.md at load,
so the rules are single-sourced. Codex and Antigravity (`agy`) read the `AGENTS.md` files directly.

## Procedure

### Step 1 — Run the deterministic generator
**Resolve `<harness-root>` first** — the generator ships in two places and finds its own templates:
- **Installed as the caddis plugin (the common case):** `<harness-root>` = `${CLAUDE_PLUGIN_ROOT}`,
  so the script is `${CLAUDE_PLUGIN_ROOT}/scripts/setup_project_ai.py`. Templates (`claude-md/`,
  `settings.template.json`, `stack-map.json`) sit at the plugin root and are auto-located.
- **harness dev checkout:** `<harness-root>` = the claudster-source repo root; the script is
  `scripts/setup_project_ai.py` with templates in the sibling `claude-harness/`.

Run a dry-run first to see stack detection and unresolved placeholders:

```
python <harness-root>/scripts/setup_project_ai.py <target-project-dir> \
    --name "<Display Name>" --desc "<one-line description>" --dry-run
```

Read the output. It reports the detected stack, the AGENTS.md rules hierarchy (+ CLAUDE.md shims) it will write, the subagents/
commands it will deploy, and — critically — **unresolved `{{PLACEHOLDER}}` tokens** grouped by file
(Phase 0 friction #1: these break runtime if left, e.g. ports in `settings.py`/`vite.config.ts`).

### Step 2 — Run for real (and substitute only for fresh template copies)
**Existing project (the common case):** placeholder substitution is OFF by default — the generator
reports `{{TOKENS}}` it finds (informational; usually just example text in docs) but **never rewrites
repo files**. Just run without `--dry-run`:
```
python <harness-root>/scripts/setup_project_ai.py <target-project-dir> \
    --name "<Display Name>" --desc "<one-line description>"
```

**Fresh-from-template project only:** the copy has real `{{API_PORT_DEV}}` etc. that break runtime
(Phase 0 friction #1). Resolve them from the platform port registry / `project-config.md` and pass
`--substitute` plus each `--set`:
```
python <harness-root>/scripts/setup_project_ai.py <target-project-dir> \
    --name "<Display Name>" --desc "<one-line description>" --substitute \
    --set PROJECT_NAME=<slug> --set API_PORT_DEV=<n> --set FE_PORT_DEV=<n> --set PROJECT_SHORT=<short> ...
```
> ⚠ **Never pass `--substitute` on an existing repo** — it would rewrite docs/code containing `{{...}}`
> as literal examples (dogfood learning from a live incident on an existing project). Substitution is a
> template-bootstrap step.

Add `--force` only when intentionally overwriting an existing CLAUDE.md/AGENTS.md/harness file.
Confirm zero runtime placeholders remain: the runtime files (`settings.py`, `vite.config.ts`,
`main.py`) must compile / parse. Quick check: `python -m py_compile src/config/settings.py`.

### Step 3 — Enrich the AGENTS.md hierarchy (the AI step — this is the value-add)
The generator writes **generic** fragments and pre-extracts real facts into
`.claudster/PROJECT-FACTS.md` (run/test/build commands, env-var names, CI/deploy workflows, entry
points). **Start there** — fold each fact into the *right* `AGENTS.md` (root vs `src/` vs
`frontend/` vs `tests/`) — the **canonical** rules file, never the `CLAUDE.md` shim — then delete
`PROJECT-FACTS.md`. Then read `STACK.md` (if present), `project-config.md`, and skim the actual code to
add the project-specific truth the generic fragments can't know:
- Real shared-library import paths, the actual data-access layer, domain terms/glossary.
- The project's **actual** run/test/build commands (from `package.json`/`pyproject.toml`/scripts).
- Concrete patterns to mirror (name a real exemplar file: "follow `src/services/<x>_store.py`").
- Anything load-bearing and non-obvious (auth model, env files, DB topology).
Keep the root **lean** — push depth into the folder `AGENTS.md` files and into skills. Do not duplicate
the generic laws/harness (already in the root AGENTS.md). The goal is the best-of-best AGENTS.md per
repo. Leave every `CLAUDE.md` as the generated shim — enriching it would fork the rules for Claude only.

### Step 4 — Ensure the test environment (Phase 0 frictions #3/#4)
- **Python:** if `.venv` missing, create it and install dev deps:
  `python -m venv .venv` then `.venv/Scripts/pip install -e .[dev]` (Windows) / `.venv/bin/pip ...`.
- **Frontend:** if the generator scaffolded the Vitest/jsdom harness, run `npm install` in the frontend
  so `jsdom` + `@testing-library/jest-dom` actually install, and confirm `vite.config` has a `test`
  block (the generator emits the exact snippet to add if missing).

### Step 5 — Smoke-test the harness (verify, don't assume — Law 4)
Prove the harness is live before declaring done:
- Run the existing suite (`pytest -q`, `npm test`) — or write one trivial passing test — and show output.
- Optionally dispatch the `preflight` subagent on any existing plan to confirm subagent dispatch works.

### Step 6 — Report + relay
Summarize what was created, the detected stack, any deferred placeholders, and the smoke-test result.
If this is a multi-session effort, run `/handoff` to write `relay.md`.

## Notes
- **Idempotent.** Re-running preserves existing AGENTS.md/CLAUDE.md/settings unless `--force`; settings
  allow-lists are always merged (union). Safe to re-run.
- **Pipeline is off by default.** The lightweight loop (plan file + relay) is the default. Enable the
  optional MCP pipeline power-mode only for large multi-week features (add `mcpServers.junai` +
  `.github/pipeline-state.json`).
- **Agent-agnostic.** `AGENTS.md` is the canonical rules file; `CLAUDE.md` is a thin `@AGENTS.md` import
  shim (Claude Code inlines it). subagents/commands/skills are plain markdown Codex/agy can also read.
  The same harness serves Claude Code, Codex CLI, and Antigravity (`agy`).
- **Packaging:** the generator ships **inside the caddis plugin** (`scripts/setup_project_ai.py`
  with the templates at the plugin root), so `/setup-project-ai` runs from a plain plugin install with
  no harness checkout. The same script also runs from the harness repo for harness development.
  Resolve its path via `<harness-root>` as described in Step 1.
