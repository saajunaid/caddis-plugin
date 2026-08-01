# claude-harness — canonical Claude Code / agent-agnostic harness

Source of truth for the Claude Code development harness. The `setup-project-ai` generator
(`scripts/setup_project_ai.py` + `setup-project-ai` skill) deploys and customizes these into any
project, producing a working, TDD-first, context-rot-resistant dev environment.

Proven end-to-end in the Phase 0 spike (`E:\Projects\_harness-spike`); see that repo's
`.github/agent-docs/PHASE-0-LEARNINGS.md`.

## Layout
```
claude-harness/
├── agents/            10 lean subagents (own context, report back) — deployed to .claude/agents/
│   ├── tester.md · code-reviewer.md · preflight.md          (Phase 0 trio)
│   ├── security-analyst.md · codebase-audit.md · debug.md   (Phase 2)
│   ├── anchor.md · knowledge-transfer.md                    (Phase 2)
│   └── data-engineer.md · sql-expert.md                     (Phase 2)
├── commands/          slash commands — deployed to .claude/commands/
│   ├── feature-plan.md · tdd.md · prd.md · handoff.md · setup-project-ai.md
├── claude-md/         rules fragment library — composed into the project's AGENTS.md hierarchy (+ CLAUDE.md shims)
│   ├── agents.md.tmpl     canonical root rules (identity placeholders + harness + laws) → AGENTS.md
│   ├── root.md.tmpl       root CLAUDE.md shim: `@AGENTS.md` + a small Claude-native block
│   ├── backend-python.md  → src/AGENTS.md   (when Python backend detected)  + src/CLAUDE.md shim
│   ├── backend-fastapi.md → appended to src/AGENTS.md (when FastAPI detected)
│   ├── frontend-react.md  → frontend/AGENTS.md (when React/Vite detected)   + frontend/CLAUDE.md shim
│   └── tests-pytest.md    → tests/AGENTS.md  (when pytest detected)          + tests/CLAUDE.md shim
├── settings.template.json base .claude/settings.json
├── stack-map.json         stack-detection signals → which fragments/commands/subagents apply
├── LOCAL-MODELS.md        run on local models — tier→model table + hybrid/local profiles (see below)
└── litellm.config.example.yaml  LiteLLM proxy config: maps opus/sonnet/haiku tiers → local/remote models
```

## Skills: two-plugin tiering (lean context)
Claude Code loads every enabled plugin's skill descriptions into **every** session, so a large flat
skill set is a standing context tax. caddis splits skills across two plugins in one marketplace:

- **`caddis`** (this plugin) — agents, commands, loop hooks, and a **core** set (~38) of
  high-frequency dev skills. Always enabled; modest always-on cost.
- **`caddis-extras`** — the **long tail** (cloud, data, the rest of frontend/coding, media,
  productivity). **Disabled by default**; enable only when you need it:
  ```
  claude plugin install caddis-extras@caddis   # one-time
  claude plugin enable  caddis-extras             # when you need the breadth
  claude plugin disable caddis-extras             # back to lean
  ```
  While disabled it costs **zero** always-on context. (Plugin skills must live flat at
  `skills/<name>/SKILL.md` to be discovered — the build flattens the pool's category layout.)

Office skills (`pdf`/`docx`/`pptx`/`xlsx`) are Anthropic's proprietary document-skills and are **not**
shipped here — install Anthropic's document-skills (or keep them in `~/.claude/skills/`).

## Running on local / non-Anthropic models (portability seam)
The harness is **model-portable by design** — it's markdown interpreted by a CLI, not code bound to a
provider. The one Anthropic-specific detail is each subagent's `model: opus|sonnet|haiku` frontmatter.
Treat that as a **logical tier**, resolved at the **gateway** (your LiteLLM proxy), not by any file in
this repo — so the tier is documentation of intent and the proxy config is what actually routes it.

To run under a gateway (the local-LLM fallback path):
1. Stand up a **LiteLLM** proxy in front of your models (local GPU via Ollama/vLLM, or any provider).
2. Point Claude Code at it: `ANTHROPIC_BASE_URL=<proxy>`, `ANTHROPIC_AUTH_TOKEN=<gateway/virtual key>`,
   optionally `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` to populate the model picker. (Codex uses
   the equivalent OpenAI base-URL seam.)
3. Set the tier→model mapping in your **LiteLLM proxy** config — see `litellm.config.example.yaml` for a
   ready-to-fill example and `LOCAL-MODELS.md` for the tier table + profiles. The recommended `hybrid`
   profile keeps `opus` remote for planning/verification and maps `sonnet`/`haiku` to a local coder
   (Opus plans, a local model codes); `local` runs every tier on-prem.

Caveats (don't hide them): a gateway is a server someone must run — subscription users gain nothing from
it and should leave it off (default). Claude Code sends `anthropic-beta` headers some non-Anthropic
backends reject (400). Keep the seam **optional, default-off**, same posture as the pipeline MCP.

## Design rules (learned in Phase 0)
- **Deterministic vs generative split.** Mechanical steps (placeholder substitution, venv/deps,
  frontend test harness, file deploy) are pure Python — they must not vary. AGENTS.md *curation*
  (enriching fragments with project-specific facts from STACK.md/code) is the skill's AI step.
- **Idempotent.** Re-running never destroys user edits: existing AGENTS.md/CLAUDE.md/settings are merged
  or left, harness files are refreshed only with `--force`.
- **Agent-agnostic core.** `AGENTS.md` is the canonical rules file; `CLAUDE.md` is a thin `@AGENTS.md`
  import shim. subagents/commands/skills are plain markdown Codex/agy can also read.
- **A new standalone script must be added to `.github/runtime-targets.json`'s `"claude"` target `files`
  list in the same commit that adds it.** Loose scripts (`claude-harness/scripts/*.py`,
  `.github/tools/*.py`) are enumerated one-by-one there — there is no directory-glob for them the way
  `copies` globs whole agent/skill/command directories. A script that exists on disk but is missing from
  that list is silently never bundled to any consumer install, and nothing else catches it (found
  2026-07-30: `oss_review.py`/`oss_model.py`/`oss_ask.py` shipped for weeks with `/caddis:cross-review`
  broken in every consumer repo before anyone noticed — see the runtime-targets.json inline comment at
  that files list, and `.caddis/parking-lot/future-work-register.md`).
