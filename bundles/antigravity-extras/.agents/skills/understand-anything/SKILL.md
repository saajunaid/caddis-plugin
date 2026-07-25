---
name: understand-anything
description: >
  Analyze any codebase or knowledge base and produce a searchable interactive knowledge graph.
  Use this skill whenever the user asks to understand a codebase, analyze project architecture,
  map a repo, generate an architecture diagram, create onboarding docs, explain a specific file
  or function, analyze the impact of a PR or diff, chat about code, or run any /understand command.
  Also triggers on phrases like "how does this project work", "map out the codebase", "what changed
  in this PR", "explain this file", "onboard me to this project", "what does X depend on",
  "analyze this repo", "generate a knowledge graph", or "what is the architecture of this project".
  Always use this skill for /understand, /understand-chat, /understand-dashboard, /understand-diff,
  /understand-domain, /understand-explain, /understand-knowledge, and /understand-onboard commands.
---

# Understand Anything

Multi-agent pipeline that scans a project, extracts files/functions/classes/dependencies, and
builds an interactive knowledge graph saved to `.understand-anything/knowledge-graph.json`.

## Commands

| Command | When to use | Reference |
|---|---|---|
| `/understand [path] [opts]` | Build (or rebuild) the knowledge graph | `references/pipeline.md` |
| `/understand-chat <query>` | Q&A about codebase using existing graph | `references/commands.md#chat` |
| `/understand-dashboard [path]` | Launch interactive web dashboard | `references/commands.md#dashboard` |
| `/understand-diff` | Analyze git diff / PR impact against graph | `references/commands.md#diff` |
| `/understand-domain [--full]` | Extract business domain flows | `references/commands.md#domain` |
| `/understand-explain <file>` | Deep-dive explanation of a file/function | `references/commands.md#explain` |
| `/understand-knowledge [dir]` | Analyze Karpathy-pattern LLM wiki | `references/commands.md#knowledge` |
| `/understand-onboard` | Generate onboarding guide for new team members | `references/commands.md#onboard` |

## Decision Tree

**No graph exists yet** (no `.understand-anything/knowledge-graph.json`) → `/understand`
→ read `references/pipeline.md` in full before proceeding.

**Graph already exists:**
- Question about how the codebase works → `/understand-chat`
- Explain a specific file or function → `/understand-explain`
- What a PR or set of changes touches → `/understand-diff`
- Business flows and domain model → `/understand-domain`
- Onboarding guide for new devs → `/understand-onboard`
- Launch visual dashboard → `/understand-dashboard`
- Input is a Karpathy LLM wiki (has `index.md` + `[[wikilinks]]`) → `/understand-knowledge`

For all commands except `/understand`: read `references/commands.md` for full instructions.

## Plugin Detection (Required Before Running /understand)

The pipeline uses bundled Node.js + Python scripts. Resolve the plugin root first:

```bash
PLUGIN_ROOT=""
for candidate in \
  "${CLAUDE_PLUGIN_ROOT:-}" \
  "$HOME/.understand-anything-plugin" \
  "$HOME/.understand-anything/repo/understand-anything-plugin" \
  "$HOME/.copilot/skills/../../../understand-anything/understand-anything-plugin" \
  "$HOME/understand-anything/understand-anything-plugin"; do
  if [ -n "$candidate" ] && [ -f "$candidate/package.json" ] && \
     [ -f "$candidate/pnpm-workspace.yaml" ]; then
    PLUGIN_ROOT="$candidate"; break
  fi
done
```

**Plugin found + `packages/core/dist/index.js` exists** → **Scripted mode** (fast, reliable). Skip LLM fallbacks.

**Plugin found but not built** → Build once:
```bash
cd "$PLUGIN_ROOT" && (pnpm install --frozen-lockfile 2>/dev/null || pnpm install) && \
  pnpm --filter @understand-anything/core build
```
Requires Node.js ≥ 22 and pnpm ≥ 10. If missing, tell the user and stop.

**Plugin not found** → **LLM-native mode**. All phases run as pure LLM analysis without bundled scripts.
Phases 1.5 (batch computation) and 7 (fingerprints) are skipped in LLM-native mode.

## /understand Options

| Flag | Effect |
|---|---|
| `--full` | Force full rebuild, ignoring existing graph |
| `--review` | Run LLM graph reviewer (Phase 6) instead of inline deterministic validation |
| `--auto-update` | Write `autoUpdate: true` to config (enables post-commit incremental updates) |
| `--no-auto-update` | Write `autoUpdate: false` to config |
| `--language <code>` | Output language for all text content: `en`, `zh`, `zh-TW`, `ja`, `ko`, `es`, `fr`, `de`, `ru`, `pt`, `ar` |
| `<dir-path>` | Analyze given directory instead of current working directory |

## Pipeline Phases Summary

Read `references/pipeline.md` for full phase specifications.

| # | Phase | Key Output |
|---|---|---|
| 0 | Pre-flight | Resolve `PROJECT_ROOT`, check for existing graph, incremental vs full decision |
| 0.5 | Ignore config | Generate `.understandignore`, **wait for user confirmation** before proceeding |
| 1 | Scan | File inventory, language/framework detection, import map |
| 1.5 | Batch | Semantic batches for concurrent file analysis *(scripted mode only)* |
| 2 | Analyze | Dispatch file-analyzer subagents (≤5 concurrent), merge results |
| 3 | Assemble Review | Validate graph, fix dangling edges |
| 4 | Architecture | Assign nodes to architectural layers (API, Service, Data, UI, Utility) |
| 5 | Tour | Build dependency-ordered guided learning tour |
| 6 | Review | Inline deterministic validation (default) or full LLM review (`--review`) |
| 7 | Save | Write `knowledge-graph.json`, fingerprints, `meta.json`, clean intermediate |

## Output Structure

```
.understand-anything/
├── knowledge-graph.json      ← commit this
├── meta.json                 ← commit this
├── config.json               ← commit this
├── .understandignore         ← commit this
├── intermediate/             ← DO NOT commit (scratch)
└── diff-overlay.json         ← DO NOT commit (local only)
```

## Graph Structure (Quick Reference)

```
knowledge-graph.json
├── project: { name, description, languages[], frameworks[], analyzedAt, gitCommitHash }
├── nodes[]: { id, type, name, filePath?, summary, tags[], complexity, languageNotes? }
├── edges[]: { source, target, type, direction, weight }
├── layers[]: { id, name, description, nodeIds[] }
└── tour[]: { order, title, description, nodeIds[] }
```

Node ID convention: `<type>:<relative-path>[:<name>]` — e.g., `file:src/App.tsx`, `function:src/auth.ts:login`

For full node types (13), edge types (26), and weight conventions → `references/graph-schema.md`

## Error Handling (All Commands)

- Retry failed subagent dispatches **once** with additional context about the failure
- Always save partial results — a partial graph is better than no graph
- Report all skipped phases and errors in the final summary; never drop failures silently
- Track warnings in `$PHASE_WARNINGS` throughout and surface them in Phase 7 report
