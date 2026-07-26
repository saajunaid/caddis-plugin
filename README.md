# caddis — a Claude Code harness

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

**caddis** is a Claude Code harness — a plugin (plus a shared pool of skills, subagents,
slash-commands, and hooks) that makes a single Claude Code session dramatically more capable and much
harder to derail. It's *agent-agnostic*: the same pool is exported to other AI CLIs (Codex,
Antigravity, Copilot), and `CLAUDE.md`↔`AGENTS.md` are mirrors so every agent reads the same
conventions.

This repository is the **published marketplace mirror**: it hosts the `caddis` and `caddis-extras`
Claude Code plugins, the portable per-harness bundles under `bundles/`, and the shared pool. It is
generated and pushed by the caddis authoring repo's exporter — issues are welcome here, but code
changes land upstream and are synced in.

---

## Install (Claude Code)

```bash
# 1. Register this repo as a plugin marketplace (once)
claude plugin marketplace add saajunaid/caddis-plugin

# 2. Install the core plugin (always-on, lean context)
claude plugin install caddis@caddis

# 3. (optional) Add the long-tail skill library — cloud/data/media/etc. Disabled by default,
#    so it costs zero always-on context until you enable it.
claude plugin install caddis-extras@caddis
```

Then, in any repo:

```
/caddis:setup-project-ai     # deploy the harness into the project
```

A normal working loop looks like:

```
/feature-plan      # (or /prd first) → writes .caddis/plans/<slug>.md, the durable spine
/implement         # executes the plan phase-by-phase, TDD, commit per phase
/ship              # express lane: commit → push → CI (hotfixes); feature work: /ship-pr then /ship-merge
/handoff           # ALWAYS end a session with this — writes the resume doc
```

**The one habit that matters most: end every session with `/handoff`.** It writes
`.caddis/relay.md`, which is re-injected automatically at the next session start — you resume with
zero re-discovery instead of a cold, forgetful session.

See [USERGUIDE.md](./USERGUIDE.md) for the full command/skill/hook reference and the mental models.

---

## What you get

- **Slash-commands** — `/feature-plan`, `/prd`, `/implement`, `/tdd`, `/ship` · `/ship-pr` ·
  `/ship-merge`, `/handoff`, `/kb`, `/digress` · `/resume`, `/cross-review`, `/usage-review`,
  `/mermaid-db` · `/excalidraw-db`, `/setup-project-ai`, `/migrate-dir`.
- **Subagents** — lean, own-context helpers: `anchor` (evidence-first verification),
  `code-reviewer`, `preflight` (plan-vs-codebase validation), `tester`, `debug`, `codebase-audit`,
  `security-analyst`, `data-engineer`, `sql-expert`, `knowledge-transfer`.
- **A four-layer memory model** — session relay (`relay.md`), automatic Dream Memory
  (`memory.jsonl`), a per-repo knowledge base (`.caddis/kb/` + `DOC-MAP.md`), and cross-repo memory.
- **Hooks & safety** — a PreToolUse guard for secret/destructive writes, auto-lint on edit, and the
  SessionStart/Stop hooks behind relay + memory.
- **Tiered skills** — the core dev set ships in `caddis`; the long tail (cloud, data, media,
  productivity) lives in `caddis-extras`, off by default.

---

## Installing outside Claude Code (Codex, Antigravity, …)

The knowledge layer (skills + `AGENTS.md` conventions) works in any harness. Per-harness bundles are
published under [`bundles/`](./bundles/) and installed with `caddis-init`:

```bash
# from a checkout of this repo (the installer ships in plugin/scripts/)
python plugin/scripts/claudster_init.py --target codex        --dest /path/to/project
python plugin/scripts/claudster_init.py --target antigravity  --dest /path/to/project
```

Safe by design: a sha256 manifest tracks what the installer wrote; re-runs update only unmodified
files, and anything you edited locally is reported as a conflict, never overwritten.

---

## Repo layout

| Path | What it is |
|---|---|
| `.claude-plugin/marketplace.json` | The marketplace manifest (`caddis` + `caddis-extras`) |
| `plugin/` | The core `caddis` Claude Code plugin (agents, commands, hooks, core skills) |
| `plugin-extras/` | The `caddis-extras` skill library (disabled by default) |
| `bundles/` | Portable per-harness exports (codex, antigravity) for `caddis-init` |
| `.github/` | The shared pool: skills, agents, prompts, instructions, tools |
| `sync.ps1`, `export_runtime_resources.py`, `validate_pool.py` | The build/sync machinery |

---

## A note on names

caddis was previously published as **claudster** (and, before that, this repo hosted the **junai**
Copilot pipeline — see the pre-1.2 entries in [CHANGELOG.md](./CHANGELOG.md)). Repos set up under
the old name have a `.claudster/` artifact dir; everything reads both `.caddis/` and `.claudster/`
and **writes where the repo already lives**, so nothing breaks. Run `/caddis:migrate-dir` when you
want a repo converted. The `~/.claudster/` user scope (keys, install records) is permanent.

---

## License

[MIT](./LICENSE). The published plugin bundles (`caddis` / `caddis-extras`) carry the same license
in their manifests.
