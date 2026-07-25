---
name: context-curator
description: Compress and prioritize codebase context before handing work to reasoning agents, minimizing token waste while preserving the required decision inputs.
---

# Context Curator Skill

**Skill ID:** `workflow/context-curator`  
**Used by:** Architect, Plan, Debug, Security Analyst, Orchestrator  
**Purpose:** Compress and prioritise codebase context before feeding it to reasoning agents. Prevents context bloat and token waste on long-running projects with large codebases.

---

## When to Use This Skill

Load this skill when:
- A reasoning agent (Architect, Plan, Debug, Security) is about to start and the codebase is large (>50 files)
- The previous context window was exhausted or truncated
- Starting a new pipeline stage on an existing feature (context needs refreshing)
- A handoff has occurred and the new agent needs a clean, relevant context package

---

## The Context Bloat Problem

In long-running projects, agents accumulate unnecessary context:
- Full file contents when only function signatures are needed
- Historical artefacts superseded by newer versions
- Unrelated modules with no bearing on the current task
- Duplicate information across PRD, architecture, and plan docs

This skill provides a structured protocol to curate a **minimum sufficient context package** for any given task.

---

## Step 1 — Identify the Task Scope

Before curating context, answer these questions:
1. **What is the current pipeline stage?** (read `pipeline-state.json`)
2. **What is the feature being worked on?** (read Intent Document or `pipeline-state.json → feature`)
3. **What specific files/modules will be touched?** (read the Plan if available)
4. **What upstream artefacts are required?** (check agent's Context Priority Order)

---

## Step 2 — Build the Context Package

Collect ONLY these items, in this order:

If the context package is written as a standalone Markdown handoff or context document, apply `.github/instructions/document-frontmatter.instructions.md`. New context documents require `Original Author`, `Creation Date`, and `Creating Model`; updated context documents must preserve those fields and add or update `Last Author`, `Last Updated`, and `Last Model Used`.

### Tier 1 — Always Include (MUST READ)
| Item | Source | What to extract |
|------|--------|-----------------|
| Intent Document | `agent-docs/intents/<feature>.md` | Goal, Constraints, Success Criteria |
| Pipeline state | `.github/pipeline-state.json` | Current stage, approved gates |
| Project config | `project-config.md` | Tech stack, constraints, brand tokens |
| Current plan step | `.github/plans/<feature>.md` | Current phase/step only |

### Tier 2 — Include When Relevant (SHOULD READ)
| Item | Source | What to extract |
|------|--------|-----------------|
| Previous artefact | `stages[previous_stage].artefact` | Key decisions and output fields |
| Architecture doc | `agent-docs/architecture/<feature>.md` | Section relevant to current task |
| PRD | `agent-docs/prd/<feature>.md` | FRs and NFRs for the affected area |

### Tier 3 — Include Only If Room (READ IF NEEDED)
| Item | Source | What to extract |
|------|--------|-----------------|
| Related source files | As specified by plan step | Function signatures + docstrings only |
| Test files | `tests/` | Failing test names and error messages |
| Escalations | `agent-docs/escalations/` | Blocking items only |

---

## Step 3 — Compress Each Item

Apply these compression rules:

### For Markdown Documents
- Extract only the sections relevant to the current task
- Summarise lists longer than 5 items as: `[N items — <category>]`
- Drop historical context (superseded requirements, old decisions)
- Replace repeated boilerplate with `[standard section — omitted]`

### For Source Code Files
- Include function/class signatures and docstrings only
- Replace function bodies with `# [body — <N lines>]`
- Include full body ONLY for functions directly touched by the current task
- List imports as a single-line summary: `# imports: os, sys, sqlalchemy, ...`

### For JSON/Config Files
- Include only the keys relevant to the current task
- Replace unrelated sections with `// [N keys omitted]`

---

## Step 4 — Assemble the Context Summary

Produce a structured **Context Summary Block** to prepend to the agent's task prompt:

```markdown
## Context Package — <feature-slug> / <stage>
**Generated:** <ISO-timestamp>
**Curated for:** @<AgentName>

### Active Task
<One sentence describing what the agent must do right now>

### Key Constraints (from Intent + project-config)
- <constraint 1>
- <constraint 2>
- <constraint 3>

### Upstream Decision Summary
- **<PRD/Arch/Plan>:** <one sentence summarising the key decision>
- **Gate status:** <gate_name>: approved | pending

### Files in Scope
- `<file path>` — <what it does / why it's relevant>
- `<file path>` — <what it does / why it's relevant>

### Do NOT touch
- `<file/module>` — <reason>
```

---

## Step 5 — Validate the Package

Before handing the context package to the agent, verify:

- [ ] Total context fits comfortably within the model's context window (leave 40% headroom for the agent's output)
- [ ] No superseded artefacts included (check `agent-docs/ARTIFACTS.md` for supersession notes)
- [ ] No sensitive data (credentials, PII) included in the package
- [ ] All required Tier 1 items are present

If context still exceeds the window after compression:
1. Drop all Tier 3 items
2. Summarise Tier 2 architecture doc to section headings only
3. If still too large — split the task into smaller sub-tasks and curate one context package per sub-task

---

## Supersession Check

Before including any artefact, check `agent-docs/ARTIFACTS.md`:
- If the artefact is listed as `superseded_by: <newer-file>`, use the newer file instead
- Never include a superseded artefact in a context package

---

## Output

The Context Curator does not produce a persistent artefact. It produces an in-memory Context Summary Block that is passed to the downstream agent as the first section of their task prompt.

If the Context Curator is run by the Orchestrator, the Orchestrator prepends the Context Summary Block to the routing message sent to the next agent.
