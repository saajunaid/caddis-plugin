# Pipeline Glossary

Canonical terms used across all agents, skills, and pipeline infrastructure.
When writing agent instructions, skills, or documentation, use ONLY these terms.

Two vocabularies live here and they are NOT interchangeable. **Core Terms** onward describe the
agent PIPELINE (orchestrator, stages, `pipeline-state.json`). **Toolchain Terms** describe caddis
as a distributed product (pool, mirror, export target). A word can be canonical in one and absent
from the other; where they genuinely collide, the collision is named under Flagged ambiguities
rather than resolved by fiat.

Admission test, borrowed from `last30days-skill`'s CONCEPTS.md: a term belongs here when its
project meaning is **distinct enough from its ordinary technical sense that a newcomer would
misread it**. `commit` does not belong. `pool` does.

---

## Core Terms

| Canonical Term | Definition | DO NOT USE |
|---------------|------------|------------|
| artefact | Any file produced by an agent as pipeline output. This is the correct spelling in all contexts — field names, prose, section headers. | artifact, deliverable, output file |
| stage | A pipeline-level progression step (intent, prd, architect, plan, implement, tester, review, closed) | phase (for pipeline steps), step |
| phase | A subdivision of work within a Plan (Phase 1, Phase 2…). Phases exist WITHIN the implement stage. | stage (for plan subdivisions), step |
| chain_id | Feature tracking ID format: `FEAT-YYYY-MMDD-slug`. Links all artefacts for a feature. | feature_id, tracking_id |
| handoff | Transfer of work from one agent to another via Orchestrator | routing (for the transfer act), delegation, dispatch, hand-off |
| handoff payload | The `_notes.handoff_payload` object written by Orchestrator via `update_notes` MCP tool before routing to a specialist | routing context, task context |
| evidence bundle | Anchor's structured proof-of-work document (`agent-docs/anchor-evidence-*.md`) | proof, verification report |
| gate | A supervision checkpoint requiring approval before pipeline advances (`supervision_gates.*`) | checkpoint, approval point |
| HARD STOP | Absolute refusal to proceed — security violation, out-of-scope request, or rogue state edit | halt, block, refuse |
| skill | A reusable knowledge pack in `.github/skills/{category}/{name}/SKILL.md` | SKILL (when referring to the concept, not the filename) |
| prompt | A reusable prompt file in `.github/prompts/*.prompt.md` | skill (when referring to prompt files — prompts are not skills) |
| onboarding prompt | The project bootstrap prompt at `.github/prompts/onboarding.prompt.md` | onboarding skill |

## Pipeline Modes

| Term | Definition |
|------|------------|
| supervised | All gates require manual user approval. Default mode. |
| assisted | Manual gates with AI guidance hints. Auto-routing between stages. |
| autopilot | All gates auto-satisfied except `intent_approved`. Fully hands-free after intent approval. |

## Result Statuses

### MCP `notify_orchestrator` — `result_status` parameter

| Value | Meaning | Used By |
|-------|---------|---------|
| `complete` | Standard stage completion | All agents |
| `phase_complete` | Multi-phase loop — implement stays in implement for next phase | Implement agent |
| `recovered` | Recovery after guard failure | Orchestrator (debug flow) |

### Agent-Specific Result Fields

| Agent | Field | Possible Values | Meaning |
|-------|-------|-----------------|---------|
| Tester | `tester_result.status` | `passed`, `failed` | All tests pass / any test fails |
| Code Reviewer | `Verdict` | `approved`, `revision-requested` | Code meets standards / needs changes |
| All agents (artefact YAML header) | `approval` | `approved`, `pending`, `revision-requested` | Artefact acceptance status |

### Orchestrator Artefact Validation Guards

| Guard | Checks |
|-------|--------|
| `artefact_exists` | File at `artefact_path` exists on disk |
| `artefact_approved` | YAML header `approval:` field is `approved` |
| `all_phases_done` | All implementation phases complete |

## File Naming Conventions

| Pattern | Example | Usage |
|---------|---------|-------|
| Agent file | `frontend-developer.agent.md` | Lowercase kebab-case matching `name` frontmatter field |
| Skill file | `.github/skills/{category}/{name}/SKILL.md` | Category folder + name folder + SKILL.md |
| Plan file | `.github/plans/{feature-slug}.md` | Feature slug from chain_id |
| Evidence file | `agent-docs/anchor-evidence-{feature}.md` | Per-feature evidence bundle |
| Artefact registry | `agent-docs/ARTIFACTS.md` | Single registry for all pipeline artefacts |
| Pipeline state | `.github/pipeline-state.json` | Live pipeline state — written ONLY by MCP tools |

## Pipeline State Field Ownership

All writes to `pipeline-state.json` go through MCP tools. Only `stages[*].status`, `stages[*].artefact`, `stages[*].completed_at`, and `blocked_by` may be set via `editFiles`.

| Field | Writer | Tool |
|-------|--------|------|
| `current_stage` | Pipeline runner | `notify_orchestrator` |
| `supervision_gates[*]` | Orchestrator | `satisfy_gate` |
| `pipeline_mode` | Orchestrator | `set_pipeline_mode` |
| `_notes.*` | Orchestrator / agents | `update_notes` |
| `project`, `feature`, `type` | Orchestrator | `pipeline_init` / `pipeline_reset` |

## Common Conflations to Avoid

| Wrong | Correct | Why |
|-------|---------|-----|
| "Phase 3 of the pipeline" | "The implement stage" | Phases are within a Plan; stages are pipeline-level |
| "The artifact registry" | "The artefact registry" | British spelling is canonical (matches all field names) |
| "Run the onboarding skill" | "Run the onboarding prompt" | `.prompt.md` files are prompts, not skills |
| "Route to the agent" | "Hand off to the agent" | Routing is Orchestrator's internal logic; handoff is the transfer act |
| `[Stage/Phase N]` | `[Phase N]` (within Plan) or `[Stage: implement]` (pipeline-level) | Don't conflate the two with a slash |

---

## Toolchain Terms

caddis-the-product, as opposed to the agent pipeline above. These are the words caddis invented
out of ordinary English, which is exactly why they need defining: a reader who guesses from the
plain word gets them wrong. Usage counts were measured across 444 markdown files on 2026-08-29.

| Canonical Term | Definition | DO NOT USE |
|---|---|---|
| pool | The single source of every shipped resource, living in `.github/` (skills, agents, commands, prompts). Everything a user installs is EXPORTED from the pool; nothing is authored in a bundle. Versioned independently of the CLI, and bumped only by `caddis-push` — never by hand. *(222 uses)* | bundle (for the source), library |
| bundle | One EXPORTED copy of the pool, shaped for a single target — `dist/runtime-resources/<target>/`. A bundle is generated output; editing one is always a mistake. | pool (for a built copy) |
| export target | A named consumer in `.github/runtime-targets.json` — claude, antigravity, antigravity-plugin, codex, copilot, plus `-extras` variants. Each takes a different subset and layout from the same pool. | platform, host (for a target) |
| mirror | The public repo `saajunaid/caddis-plugin`, refreshed by `caddis-push`. The SOURCE repo is private, so the mirror is what any other machine can actually reach. | upstream, remote |
| relay | `.caddis/relay.md` — the durable resume doc, rewritten by `/caddis:handoff` and injected at SessionStart. Machine-local and gitignored. Only changes when someone runs a handoff, so it is stale between them by design. *(168 uses)* | handoff doc, session notes |
| session state | `.caddis/session-state.md` — auto-captured by the `Stop` hook at the end of EVERY turn. Distinct from the relay: current without anyone deciding to make it current, and it holds no agreed next step. | relay (they are different files with different guarantees) |
| drift | A gap between what a consumer HAS installed and what the pool currently ships. `caddis status` reports it per agent. Not code drift, not schema drift. *(160 uses)* | staleness, lag |
| live-fire | Driving a real binary end to end rather than asserting against a manifest. Coined because three defects in one month passed every test and still gave a human a broken install: the tests asked "does the export match the manifest", never "would this work". An export target is not trusted until it has been live-fired once. | smoke test, integration test, manual test |
| parking-lot | `.caddis/parking-lot/` — the ONE register of future work. It exists because future work previously scattered to nine places and no session could answer "what is left". Items carry `severity` and `status`; the backlog IS the plan when no plan is active. *(41 uses)* | backlog file, TODO list, icebox |
| model lane | A named provider route reached by its own binary — `claude-oss`, `claude-glm`, `claude-deepseek` — all speaking the Anthropic protocol. A lane is a route, not a model. | provider, backend, endpoint |
| core / extras | The two shipping tiers. Core is an EXPLICIT allowlist in `.github/runtime-targets.json`; anything not named there lands in extras. A skill defaults to extras, so placement is a decision, never an accident. | tier 1 / tier 2, full / lite |
| harness | The agent runtime that loads caddis — Claude Code, agy, Codex, Copilot. caddis is agent-agnostic; "the harness" without a name means whichever one is running. *(135 uses)* | client, IDE, platform |

## Flagged ambiguities

Named rather than resolved. Pretending the vocabulary is clean is how a glossary starts lying.

- **`gate` is overloaded, badly.** Core Terms defines it as a supervision checkpoint requiring
  approval. That is one of at least twelve senses in live use: *exit gate* (20), *quality gate*
  (9), *evidence gate* (5), *decision gate* (3), plus pre-publish, handover and privacy gates —
  none of which involve pipeline supervision. The word appears 1019 times across 168 files.
  **Prefer the full two-word term everywhere**; a bare "gate" is ambiguous and the reader cannot
  tell which one you meant.

- **`artefact` vs `artifact`.** Core Terms makes `artefact` canonical, and for pipeline outputs it
  is. But the toolchain's own code says `artifact_root` and "artifact dir" (17 uses in
  `scripts/setup_project_ai.py` alone), and those are API names that cannot be respelled without
  a breaking change. So: **artefact** in pipeline prose and field names; **artifact dir /
  `artifact_root`** when naming the `.caddis/` directory mechanism. Do not "fix" one into the other.

- **`skill` means two things across harnesses.** In the pool it is
  `.github/skills/<category>/<name>/SKILL.md`. But agy CONVERTS commands into skills at install
  time, so `/caddis:catchup` ships as a command and arrives as an agy skill. A skill count that
  disagrees between two agents is usually this, not a bug.
