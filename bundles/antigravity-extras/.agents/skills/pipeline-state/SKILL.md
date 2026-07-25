---
name: pipeline-state
description: Read and write `.github/pipeline-state.json` to track stage progress, artefacts, supervision gates, and handoff payloads in the agent pipeline.
---

# Pipeline State Skill

**Skill ID:** `workflow/pipeline-state`  
**Used by:** Orchestrator, Plan, Implement, Tester, Code Reviewer  
**Purpose:** Read and write `.github/pipeline-state.json` to track pipeline position, stage status, and supervision gates.

---

## When to Use This Skill

Load this skill when:
- Starting the Orchestrator agent on a new or resuming pipeline
- An agent completes its stage and needs to mark it done
- Checking if upstream gates are approved before proceeding
- Setting `blocked_by` when a validation failure is detected

---

## Pipeline State File Location

```
.github/pipeline-state.json
```

This file is **project-specific** — it lives in the project repo, NOT in junai. Use `.github/pipeline-state.template.json` from junai as the blank starting template.

---

## Schema Reference

```json
{
  "project": "<project-name>",
  "feature": "<feature-slug>",
  "pipeline_version": "1.0",
  "current_stage": "<stage-name>",
  "stages": {
    "intent":    { "status": "not_started | in_progress | complete | blocked", "artefact": "<path-or-null>", "completed_at": "<ISO-timestamp-or-null>" },
    "prd":       { "status": "...", "artefact": "...", "completed_at": "..." },
    "architect": { "status": "...", "artefact": "...", "completed_at": "..." },
    "plan":      { "status": "...", "artefact": "...", "completed_at": "..." },
    "implement": { "status": "...", "artefact": "...", "completed_at": "..." },
    "tester":    { "status": "...", "artefact": "...", "completed_at": "..." },
    "review":    { "status": "...", "artefact": "...", "completed_at": "..." }
  },
  "supervision_gates": {
    "intent_approved": false,
    "adr_approved": false,
    "plan_approved": false,
    "review_approved": false
  },
  "blocked_by": null,
  "last_updated": "<ISO-timestamp>"
}
```

### Stage Status Values
| Value | Meaning |
|-------|---------|
| `not_started` | Stage not yet begun |
| `in_progress` | Agent is actively working on this stage |
| `complete` | Artefact produced and `approval: approved` confirmed |
| `blocked` | Cannot proceed — see `blocked_by` field |

---

## Read Operations

### Check current stage
```
Read: .github/pipeline-state.json → .current_stage
```

### Check if a gate is approved
```
Read: .github/pipeline-state.json → .supervision_gates.<gate_name>
Returns: true | false
```

### Check upstream artefact approval
```
Read: <artefact_path from previous stage> → YAML header → approval field
Expected value: "approved"
```

### Check for blocking escalations
```
List files in: agent-docs/escalations/
If any file contains severity: "blocking" → surface to user, do NOT proceed
```

---

## Write Operations

### Mark stage as in_progress
```json
{
  "current_stage": "<new-stage>",
  "stages": {
    "<new-stage>": { "status": "in_progress" }
  },
  "last_updated": "<current-ISO-timestamp>"
}
```

### Mark stage as complete
```json
{
  "stages": {
    "<completed-stage>": {
      "status": "complete",
      "artefact": "<path-to-artefact>",
      "completed_at": "<current-ISO-timestamp>"
    }
  },
  "last_updated": "<current-ISO-timestamp>"
}
```

### Set blocked state
```json
{
  "stages": {
    "<stage>": { "status": "blocked" }
  },
  "blocked_by": "<reason: e.g., 'artefact missing approval field'>",
  "last_updated": "<current-ISO-timestamp>"
}
```

### Approve a supervision gate
```json
{
  "supervision_gates": {
    "<gate_name>": true
  },
  "last_updated": "<current-ISO-timestamp>"
}
```

### Clear a blocked state
```json
{
  "blocked_by": null,
  "stages": {
    "<stage>": { "status": "in_progress" }
  },
  "last_updated": "<current-ISO-timestamp>"
}
```

### Write handoff payload before routing (GAP-H6 + GAP-I1)

Before routing to `plan`, `implement`, `tester`, or `code-reviewer`, the Orchestrator writes to `_notes.handoff_payload`:

```json
{
  "_notes": {
    "handoff_payload": {
      "target_agent": "<implement|tester|code-reviewer|plan>",
      "scope": "<one-line description of what the agent must do>",
      "summary": "<brief context from upstream stage>",
      "required_tests": ["<test 1>", "<test 2>"],
      "exit_criteria": "<what done looks like>",
      "upstream_artefact": "<path to artefact produced by the current/previous stage>",
      "coverage_requirements": [
        "<component or requirement the receiving agent MUST cover>",
        "<e.g.: component: Search API integration>",
        "<e.g.: NFR: WCAG 2.1 AA compliance>"
      ]
    }
  }
}
```

> **`coverage_requirements[]` rule (GAP-I1):** Must be non-empty whenever an upstream artefact exists (architecture doc → plan, plan → implement, implement → tester, etc.). The receiving agent maps every item to its output and flags `COVERAGE_GAP: <item>` for any item not covered before starting work.
>
> **`pipeline_mode` field:** Set `"pipeline_mode": "supervised"` (default) or `"auto"` in the root of `pipeline-state.json`. Orchestrator §1 reads this to determine whether to HARD STOP after presenting the handoff button (`supervised`) or call `notify_orchestrator()` MCP tool and continue (`auto`). Always default to `supervised` on new pipelines — `auto` is an explicit opt-in.

---

## Initialisation

When `.github/pipeline-state.json` does not exist:
1. Copy from `.github/pipeline-state.template.json` (available in the junai pool)
2. Replace `<project-name>` with the value from `project-config.md → profile → project_name`
3. Replace `<feature-slug>` with the kebab-case feature name from the Intent Document or user input
4. Set `current_stage` to `"intent"` or the appropriate starting stage
5. Set `last_updated` to current ISO timestamp

---

## Validation Rules

Before routing to any agent, the Orchestrator MUST verify:

1. **Artefact exists** — the file at `stages[previous_stage].artefact` exists on disk
2. **Artefact approved** — the YAML header of that artefact contains `approval: approved`
3. **No blocking escalations** — `agent-docs/escalations/` has no files with `severity: blocking`
4. **Gate check** — if the transition requires a supervision gate, that gate is `true` in `supervision_gates`

If ANY check fails → set `blocked_by`, report to user, do NOT proceed.
