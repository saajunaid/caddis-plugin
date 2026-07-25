---
name: intent-writer
description: Structure freetext ideas, backlog items, or vague requirements into a formal Intent Document that preserves user intent across the entire agent pipeline chain.
---

# Intent Writer Skill

## Purpose

Create an **Intent Document** — a structured, immutable artifact that captures the user's original intent for a feature or task. This document is the anchor that prevents intent drift as work passes through the agent pipeline (PRD → Architect → Plan → Implement).

**Problem it solves**: In multi-agent workflows, intent, goals, and specifics get diluted with each handoff. By the time an implementing agent receives work, the original intent may be distorted or lost entirely. The Intent Document gives every agent in the chain direct access to the original intent.

---

## When to Use

- A user provides a vague idea, freetext request, or rough notes
- Before handing work to the PRD agent
- When the `@prompt-engineer` agent is refining input for the pipeline
- When pulling a backlog item into active work
- To create an Intent Amendment when requirements change mid-pipeline

---

## Steps

### Step 1: Read Project Context

1. Read `project-config.md` → identify tech stack, framework, deployment constraints
2. Scan `agent-docs/intents/` → check for existing intents on the same topic (avoid duplicates)
3. If this is an amendment, read the original Intent Document being amended

### Step 2: Extract Intent from User Input

From whatever input is provided (freetext, idea, backlog item, conversation), extract:

| Field | What to capture |
|-------|----------------|
| **Goal** | What the user wants to achieve — the "why" and "what", not the "how" |
| **Success Criteria** | Testable conditions that define "done" — concrete, measurable |
| **Constraints** | Technical limitations, business rules, framework restrictions, deployment constraints |
| **Out of Scope** | What this is specifically NOT — prevents scope creep |
| **Original User Input** | Verbatim preservation of the user's words — no agent can claim they didn't know |

### Step 3: Framework Feasibility Pre-Check

Before finalizing the Intent Document, cross-reference the goal against `project-config.md` → Tech Stack:

- Does the goal involve UI? → Check if the proposed approach is feasible in the target framework
- Does the goal involve data? → Check if the database type supports what's needed
- Does the goal involve deployment? → Check if the deployment environment allows what's needed
- Does the goal involve external services? → Check air-gapped deployment constraints

If a feasibility issue is found:
1. Add it to the **Constraints** section explicitly
2. Note it in the **Feasibility Warnings** field
3. Suggest alternatives if applicable

### Step 4: Generate chain_id

Create a unique identifier for this feature chain:
- Format: `FEAT-YYYY-MMDD-{slug}`
- Example: `FEAT-2026-0218-chat-widget`
- The slug should be 2-4 words, hyphenated, describing the feature
- Check `agent-docs/ARTIFACTS.md` to ensure the chain_id isn't already in use

### Step 5: Write the Intent Document

Create the document at `agent-docs/intents/{chain_id}.md`:

Apply `.github/instructions/document-frontmatter.instructions.md` when creating or updating the Intent Document. The YAML frontmatter block must be the first content in the file. New intent documents require `Original Author`, `Creation Date`, and `Creating Model`; revised intent documents must preserve those fields and add or update `Last Author`, `Last Updated`, and `Last Model Used`.

```markdown
---
agent: prompt-engineer
created: {YYYY-MM-DDTHH:MM:SSZ}
status: current
type: intent
chain_id: {FEAT-YYYY-MMDD-slug}
approval: pending
feasibility_warnings: {list or "none"}
Original Author: prompt-engineer
Creation Date: {YYYY-MM-DDTHH:MM:SSZ}
Creating Model: {exact runtime model identifier or display name}
---
<!-- AGENT-GENERATED: This Intent Document preserves user intent for the agent pipeline.
     Every agent in the chain MUST read this document FIRST before processing. -->

# Intent: {Feature Title}

## Goal
{Clear statement of what the user wants to achieve}

## Success Criteria
- {Testable criterion 1}
- {Testable criterion 2}
- {Testable criterion 3}

## Constraints
- {Technical constraint}
- {Business constraint}
- {Framework constraint — from feasibility check}

## Out of Scope
- {Explicitly excluded item 1}
- {Explicitly excluded item 2}

## Feasibility Notes
{Any warnings from the framework feasibility check, or "No feasibility issues identified."}

## Original User Input
> {Copy the user's original input verbatim here — preserve exact wording}
```

### Step 6: Update Manifest

Add a row to `agent-docs/ARTIFACTS.md`:

| Date | Agent | Type | Description | Path | Status | Approval | Chain ID |
|------|-------|------|-------------|------|--------|----------|----------|
| {date} | prompt-engineer | intent | {Feature title} | agent-docs/intents/{chain_id}.md | current | pending | {chain_id} |

### Step 7: Report

Tell the user:
- Intent Document created at `agent-docs/intents/{chain_id}.md`
- Summary: Goal, key constraints, feasibility warnings (if any)
- Next step: "Review and approve the Intent Document. Once approved, this can be handed to the PRD agent."
- The `chain_id` for future reference

---

## Intent Amendments

When requirements change mid-pipeline:

### When to Create an Amendment (not a new Intent)

- The original goal is the same but specifics changed
- A constraint was added or removed
- Success criteria changed
- The user said "actually, I want X instead of Y" for part of the feature

### When to Create a New Intent

- The goal itself is fundamentally different
- The user is starting a different feature entirely

### Amendment Process

1. Create an amendment document at `agent-docs/intents/{chain_id}-amendment-{N}.md`:

```markdown
---
agent: prompt-engineer
created: {YYYY-MM-DDTHH:MM:SSZ}
status: current
type: intent-amendment
chain_id: {same chain_id as original}
amends: agent-docs/intents/{chain_id}.md
amendment_number: {N}
approval: pending
Original Author: prompt-engineer
Creation Date: {YYYY-MM-DDTHH:MM:SSZ}
Creating Model: {exact runtime model identifier or display name}
---

# Intent Amendment #{N}: {Brief description of change}

## What Changed
- {Specific change 1}
- {Specific change 2}

## Why
{Reason for the change}

## Impact Assessment
- **PRD**: {Does PRD need updating? Which sections?}
- **Architecture**: {Does architecture need updating?}
- **Plan**: {Does plan need updating? Which phases?}
- **Implementation**: {Is any completed work affected?}

## Downstream Artifacts to Supersede
- {List artifact paths that are now stale due to this change}
```

2. Mark downstream artifacts (produced BEFORE the amendment) as `superseded` in the manifest
3. The pipeline re-runs from the earliest affected point

If you revise an existing intent or amendment file instead of creating a new one, preserve the original metadata fields and add or update `Last Author`, `Last Updated`, and `Last Model Used` using full ISO 8601 UTC timestamps.

---

## Important Notes

- Intent Documents are **effectively immutable** — once created, they're a historical record of what was agreed
- Changes go through the Amendment process, not by editing the original
- Every agent in the pipeline MUST read the Intent Document (and any amendments) FIRST
- The `chain_id` links all artifacts in the feature chain — always carry it through
- Original User Input is preserved verbatim — this is the ultimate source of truth
