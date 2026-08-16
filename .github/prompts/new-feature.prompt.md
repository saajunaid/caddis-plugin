---
description: "Start a new feature — creates an Intent Document and begins the agent pipeline"
mode: agent
tools: ['codebase', 'editFiles']
---

# /new-feature — Start a New Feature

Begin the automated agent pipeline for a new feature or task.

## Input

User's request: `{{input}}`

If `{{input}}` is empty, ask: "What feature or task do you want to build? You can provide a detailed description, a rough idea, or reference a backlog item."

---

## Step 1: Assess Input Quality

Evaluate the user's input:

| Input Quality | Indicators | Action |
|--------------|------------|--------|
| **Vague idea** | No specifics, just a concept ("I want search to be better") | → Go to Step 2A (refine with Prompt Engineer) |
| **Rough requirements** | Some specifics but missing constraints, success criteria | → Go to Step 2A (refine with Prompt Engineer) |
| **Clear requirements** | Has goal, specifics, and some constraints | → Go to Step 2B (create Intent Document directly) |
| **Backlog reference** | Points to a file in `.caddis/parking-lot/` | → Read the parked item, then go to Step 2B |

---

## Step 2A: Refine with Prompt Engineer

The input needs refinement before entering the pipeline.

Intent Documents created or updated in this flow must follow `.github/instructions/document-frontmatter.instructions.md`.

1. Read `skills/workflow/intent-writer/SKILL.md`
2. Follow the skill to structure the input into an Intent Document
3. Ask clarifying questions to fill gaps (goal, success criteria, constraints, out of scope)
4. Run the framework feasibility pre-check
5. Write the Intent Document to `.github/agent-docs/intents/`
6. Update `.github/agent-docs/ARTIFACTS.md`
7. Present the Intent Document to the user for approval

---

## Step 2B: Create Intent Document Directly

The input is clear enough — structure it without extensive Q&A.

Intent Documents created or updated in this flow must follow `.github/instructions/document-frontmatter.instructions.md`.

1. Read `skills/workflow/intent-writer/SKILL.md`
2. Follow the skill to create the Intent Document
3. Run the framework feasibility pre-check
4. Write the Intent Document to `.github/agent-docs/intents/`
5. Update `.github/agent-docs/ARTIFACTS.md`
6. Present the Intent Document to the user for approval

---

## Step 3: Approval Gate

Present the Intent Document summary to the user:

```
Intent Document created: .github/agent-docs/intents/{chain_id}.md

Goal: {goal summary}
Constraints: {key constraints}
Feasibility warnings: {any warnings, or "none"}

Please review and confirm:
- Approve → I'll hand this to the PRD agent to create formal requirements
- Revise → Tell me what to change and I'll update the Intent Document
```

**Do NOT proceed to PRD until the user approves the Intent Document.**

---

## Step 4: Hand Off to PRD

Once approved, update the Intent Document's `approval` field to `approved` and instruct the user:

```
Intent Document approved. Next step:

Open a new chat and use the @prd agent with this prompt:

"Read the Intent Document at .github/agent-docs/intents/{chain_id}.md and create 
a Product Requirements Document. The chain_id is {chain_id}."
```

---

## Pipeline Overview (for user reference)

```
You are here
    ↓
[✅ Intent Document] → created and approved
    ↓
[@prd] → creates PRD from intent → user approves
    ↓
[@architect] → creates architecture from PRD + intent → user approves
    ↓
[@planner] → creates phased plan → user approves
    ↓
[Implementation agents] → execute plan phases
    ↓
[@code-reviewer] → chain audit (verifies work matches intent)
```

Each arrow is an approval gate. You stay in control at every step.
