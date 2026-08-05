---
name: prd
description: Capture requirements through structured discovery and write a PRD
---

# /prd — requirements discovery

Produce a Product Requirements Document for: **$ARGUMENTS**

If empty, ask what the feature/problem is and stop. Goal: turn a fuzzy idea into a crisp, testable spec
that `/feature-plan` can consume.

## Discovery (ask, don't assume)
Interview the user to fill gaps. Ask only what you can't infer from the codebase / `STACK.md`. Cover:
- **Problem & users** — what hurts, for whom, why now.
- **Outcome** — what "done" looks like in user terms; how we'd measure it.
- **Scope** — must-have vs nice-to-have vs explicitly out.
- **Data & constraints** — sources, fields, perf/security/compliance limits.
- **Edge cases & failure modes** — empty/error states, permissions.

Ask in small batches; stop interviewing once the spec is testable.

## Headless mode
When the invocation contains the marker **`HEADLESS RUN RULES`**, **or `CADDIS_HEADLESS` /
`DOCKET_PLAN` / `DOCKET_BRANCH` is set in the environment** (the caddis OSS launchers export
`CADDIS_HEADLESS` on claude's `-p`/`--print`; the docket runner sets the others) — a non-interactive
caller spawned this session and no human is present, so the Discovery interview above is **suspended and
forbidden**. This mode exists for one-line ideas: the card may be nothing more than a short title with
**no description**, and there may be **no codebase or `STACK.md`** to draw on. That is expected and still
fully actionable — a terse title is enough to write a complete draft PRD.

Absolute rules in this mode (they override everything above):
- **NEVER ask a question. NEVER request clarification. NEVER end your turn with questions.** Replying with
  something like *"a few questions to scope this before I write the PRD"* is a hard failure. Never use
  AskUserQuestion, never pause for approval, never wait for input.
- **A bare title is sufficient input.** Even with only a few words and nothing else, you MUST write the
  full PRD. Where information is missing, **invent a reasonable, conventional interpretation**, state it
  explicitly as an assumption, and proceed. Making an explicit assumption is ALWAYS correct; asking is
  ALWAYS wrong here. If you ever feel you lack enough information, that is the signal to **write an
  assumption and continue** — never to ask.
- **Every gap becomes an `## Open questions` bullet** (or `[TECH-DECISION OPEN]` inline). This section
  may be long — that is good, not a problem. It is where all the things you would have asked go.
- **Honor the caller's output path and slug.** Write to the `artifact_dir`/`feature` slug the caller
  specifies (falling back to `.caddis/prd/<feature-slug>.md`); set `feature: <slug>` in the
  frontmatter to that same slug. The frontmatter shape is unchanged from the interactive flow.
- **Also emit a visual companion** — a self-contained, scannable HTML page at `<artifact_dir>/<slug>.html`
  presenting the PRD visually (a goal/success card, an FR/NFR table, edge cases, and open questions as
  distinct sections). **Use inline `<style>` ONLY** — the visual is rendered in a *sandboxed* iframe with
  no script execution, so a `<script>`/CDN (e.g. the Tailwind browser CDN) would NOT run and the page
  would appear unstyled. Keep it fully portable — no external `<script>`/`<link>`, no local asset files,
  no `/`-rooted paths. This is the visual the human reviews in docket alongside the markdown. Write it
  after the `.md`; the runner finds it by the matching `<slug>.html` name.
- **Always write the artifact file, then end with exactly one fenced `json` highlights block** as the
  final output — nothing after it. Keep `summary` ≤ 280 chars; `open_questions` = the count of bullets
  under `## Open questions`:
  ```json
  {"artifact":"<artifact_dir>/<slug>.md","summary":"<=280 chars>","open_questions":<int>}
  ```

The only acceptable final output in this mode is the written artifact plus its highlights block — never
questions. Everything else — the PRD template, frontmatter, and section structure below — is identical in
both modes; only the interview is skipped.

## Write to `.caddis/prd/<feature-slug>.md`
```markdown
---
type: prd
status: draft
feature: <feature-slug>
creation-agent: caddis
Original Author: Claude Code
Creation Date: <YYYY-MM-DDTHH:MM:SSZ>
Creating Model: <model-id>
---

# PRD — <feature>
**Created:** <ISO date>  •  **Status:** draft

## Problem
<who, what, why.>

## Goal & success criteria
- <measurable outcome>

## Functional requirements
- FR-1: <requirement — phrased so a test can verify it>

## Non-functional requirements
- NFR-1: <perf/security/a11y/...>

## Out of scope
- <explicitly excluded>

## Data
| Field / source | Shape | Notes |
|---|---|---|

## Edge cases & failure modes
- <empty / error / permission / boundary>

## Open questions
- <unresolved — needs a decision before planning>
```

## Report
Output the PRD path and the FR list. Suggest: *"Next: `/feature-plan <feature>`."* Don't design the
implementation here — PRD is the *what*, the plan is the *how*.

Create `.caddis/prd/` if it doesn't exist.
