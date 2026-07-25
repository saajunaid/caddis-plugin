---
name: relay
description: Create or update a root relay.md session-continuation document for any repository. Use this skill whenever the user asks to preserve project context, resume later, hand work to a future session, create a session relay, summarize current implementation state, or generate a reusable continuation prompt. The workflow is generic and must discover project structure at runtime.
---

# Relay Skill

## Purpose

Create or update `relay.md` at the target repository root with enough verified context for a future agent or developer to resume work without re-discovering the project from scratch.

This skill is generic. Do not include project-specific assumptions, fixed folder names, fixed frameworks, or domain-specific terminology unless those facts are discovered in the target repository.

## Core Rules

- Write `relay.md` at the repository root by default.
- Preserve only verified facts and verified file paths.
- Do not invent plan names, phases, commands, architecture, owners, or completion state.
- Do not assume `.github/plans`, `docs`, `src`, `tests`, package managers, branch models, or CI systems exist.
- If evidence conflicts, describe the conflict and identify the files that disagree.
- If a fact cannot be verified, mark it as `Unknown` or place it under open questions.
- Do not commit changes unless the user explicitly asks.

## When To Use

Use this skill when the user asks for:

- `/relay`
- a session-continuation file
- a context document for returning later
- a resume prompt for a future agent
- a summary of current project state and next steps
- a clean handover between sessions

## Discovery Workflow

### 1. Establish Repository Root

Identify the target repository root from the current workspace. If there are multiple candidate roots, choose the one containing the active user request or ask a concise clarifying question only if choosing would be risky.

### 2. Gather Verified Signals

Use lightweight scans first:

```bash
git status --short
git branch --show-current
git log --oneline -5
```

If git is unavailable, note that in `Validation State`.

Read high-signal files only when they exist:

- root overview files such as `README.md`, `CHANGELOG.md`, `STACK.md`, or equivalent
- package, build, task, or CI configuration files
- active plan, roadmap, TODO, or issue documents discovered by search
- architecture or design documents that are referenced by active plans or recent work

Search for likely workstream signals without assuming exact locations:

```bash
rg -n "TODO|Next Step|Phase|Status|In Progress|Current Plan|Roadmap|Backlog|Validation|Acceptance" .
```

Keep searches scoped enough to avoid generated folders, dependency folders, build output, and archives unless the archive is directly relevant.

### 3. Infer Current Workstream

Determine the current plan or workstream using evidence in this order:

1. The user's latest instruction.
2. Current conversation context.
3. Recent file modifications or git status.
4. Plan or roadmap files with active status markers.
5. Recent commits.
6. Root documentation.

If several candidates remain plausible, list them and state which one appears most likely.

### 4. Identify Validation Commands

Discover validation commands from:

- documented setup or test instructions
- package scripts
- make/task files
- CI workflow files
- test configuration files
- commands already run in the current session

Do not claim validation passed unless it was actually run or documented as already passing. If not run, say `Not run in this session`.

## `relay.md` Format

Use this exact filename at the repository root: `relay.md`.

### Metadata Source Rules

- Use full ISO 8601 UTC timestamps for `Creation Date` and `Last Updated`, for example `2026-05-21T13:30:00Z`.
- Use the exact current model identifier or display name from the chat/runtime model selector or session metadata for `Creating Model` and `Last Model Used`, for example `gpt-5.4`, `gpt-5.3-codex`, or `GPT-5.5`.
- Do not infer the model from the agent name, product name, or broad family. Generic agent, product, or family labels are not acceptable when the runtime exposes a precise model name.
- If the runtime does not expose an exact model identifier, record the most precise deterministic runtime identity available and say the exact ID was unavailable, for example `Codex (GPT-5-based; exact runtime model ID unavailable)`.

### New File Frontmatter

When creating a new file:

```yaml
---
Original Author: <agent/user>
Creation Date: YYYY-MM-DDTHH:MM:SSZ
Creating Model: <exact runtime model identifier or display name>
---
```

### Existing File Frontmatter

When updating an existing file:

1. Preserve the original `Original Author`, `Creation Date`, and `Creating Model` values.
2. Add or update the last-update fields above the original fields.
3. Use this order:

```yaml
---
Last Author: <agent/user>
Last Updated: YYYY-MM-DDTHH:MM:SSZ
Last Model Used: <exact runtime model identifier or display name>
Original Author: <preserved>
Creation Date: <preserved>
Creating Model: <preserved>
---
```

If an original field is missing and cannot be recovered, use `unknown` for that field rather than inventing a value.

### Required Body Sections

Use exactly these top-level headings:

```
# Relay

## Purpose

## Current Project Context

## What Has Been Completed

## Current Plan Or Workstream

## Next Step

## Important Files To Read First

## Validation State

## Open Questions Or Blockers

## Resume Prompt
```

## Body Guidance

### Purpose

State that `relay.md` is the current session-continuation document and should be read first when resuming work.

### Current Project Context

Summarize the repository's goal and the current development direction. Cite only verified project facts.

### What Has Been Completed

List completed work visible from plans, documentation, git history, tests, or changed files. Prefer evidence-backed bullets:

```
- Completed <work> based on `<verified/path.md>`.
```

### Current Plan Or Workstream

Name the active plan, phase, issue, branch, or workstream. If the plan is unclear, describe the ambiguity and likely candidates.

### Next Step

Provide one exact next action. Include a fallback action if the first next step is blocked.

### Important Files To Read First

List verified paths only:

```
- `<path>` - why it matters.
```

Do not list files that were not found.

### Validation State

Include:

- commands discovered
- commands run in the current session
- pass/fail/not-run state
- known failing checks or missing validation

### Open Questions Or Blockers

Capture decisions needed, missing access, conflicting docs, ambiguous plan state, or unverified assumptions.

### Resume Prompt

Provide a ready-to-paste prompt inside a bare fenced code block. The opening fence must be exactly three backticks with no language label.

```
Read `relay.md` first, then read the important files listed there. Continue from <current workstream>. The next step is <exact action>. Preserve unrelated user changes and run <validation command> when appropriate.
```

Keep the prompt short, specific, and free of unsupported claims.

## Verification Checklist

Before finishing:

- [ ] `relay.md` exists at the repository root.
- [ ] Required frontmatter fields are present.
- [ ] `Creation Date` and `Last Updated` use full ISO 8601 UTC timestamps ending in `Z`.
- [ ] `Creating Model` and `Last Model Used` use the exact runtime model identifier or display name when available, not only a generic model family.
- [ ] Original metadata is preserved when updating an existing file.
- [ ] All required body sections are present.
- [ ] Every listed file path was verified.
- [ ] Validation state distinguishes run, not run, pass, and fail.
- [ ] The resume prompt names the next action and is wrapped in a bare fenced code block with no language label.
- [ ] No project-specific terminology appears unless discovered in the target repository.

## Final Response

Tell the user:

- where `relay.md` was written
- the inferred current workstream
- the next step
- validation commands found or run
- any remaining ambiguity
