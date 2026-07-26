---
description: "Document provenance frontmatter for plans, docs, READMEs, reports, handoffs, and other descriptive Markdown artifacts"
applyTo: "**/*.md"
priority: 120
---

# Document Frontmatter Instructions

Apply this rule whenever you create or update a **descriptive Markdown deliverable**. The YAML frontmatter block must be the first content in the file, before the title, blockquotes, comments, or generated status headers.

This applies to outputs produced by planning, intent, preflight, relay, ADR, README, handoff, documentation, and report workflows, including outputs from `writing-plans`, `golden-plan`, `intent-writer`, `preflight`, `relay`, `plan.prompt.md`, `adr.prompt.md`, and `create-readme.prompt.md`.

Include frontmatter for:
- planning documents
- PRDs, ADRs, design docs, architecture docs, and requirements docs
- README files, runbooks, guides, reports, analyses, and handoffs
- status trackers, implementation notes, migration notes, and other prose-first Markdown artefacts
- session-spec / driver prompts (e.g. `.caddis/prompts/*.md`) — they are generated deliverables
  with a lifecycle like any plan; use `type: prompt`

## Required metadata fields

When creating a **new** document, add YAML frontmatter at the top and include:

```yaml
type: plan|prd|adr|design|runbook|handoff|analysis|review|prompt
status: draft|current|done|superseded
feature: <feature-slug or chain_id that owns this document>
creation-agent: caddis
Original Author: <active author or agent name>
Creation Date: <YYYY-MM-DDTHH:MM:SSZ>
Creating Model: <exact runtime model identifier or display name>
```

When **updating** an existing document, preserve those original fields and add or update:

```yaml
Last Author: <active author or agent name>
Last Updated: <YYYY-MM-DDTHH:MM:SSZ>
Last Model Used: <exact runtime model identifier or display name>
```

> For newly created documents, `Last Author`, `Last Updated`, and `Last Model Used` are optional and should be omitted until the first update.

**Field notes:**
- `type` — document category; choose the closest match from the list above.
- `status` — lifecycle state; update when the document is superseded or completed.

## Status lifecycle

`draft` and `current` are **active**; `done` and `superseded` are **terminal**. Use `done` when the
work a document describes is complete; use `superseded` when a newer document replaces it.
- **`done` is the canonical terminal value.** `shipped` and `implemented` are accepted legacy
  synonyms — tooling treats them as terminal — but prefer `done` in new and updated documents.
  (`ready` is NOT terminal: it means approved-and-waiting-to-start, i.e. active.)
- `feature` — the feature slug or chain ID that this document belongs to (e.g. `feat-2026-0609-auth-rework`). Use `standalone` if the document is not tied to a feature.
- `creation-agent` — the plugin or tool that created the document. Use `caddis` for documents produced by the caddis Claude Code plugin; use `github-copilot` for documents produced by the GitHub Copilot junai-vscode extension; use `human` for manually authored documents.

## Merge rules

- Merge these fields into the existing YAML frontmatter block. Do **not** replace document-specific keys such as `description`, `type`, `status`, `chain_id`, `approval`, `tags`, `model`, `tools`, or `applyTo`.
- If the document has no YAML frontmatter, add one.
- Do **not** change `Original Author`, `Creation Date`, or `Creating Model` unless they are missing and you are backfilling a legacy document.
- If a legacy document has no recoverable original metadata, backfill with:
  - `Original Author: Unknown (legacy document)`
  - `Creation Date: Unknown`
  - `Creating Model: Unknown`
  Then add the current `Last Author`, `Last Updated`, and `Last Model Used` fields.
- Use the active author identity for author fields, for example `GitHub Copilot`, `Planner`, `Architect`, `PRD`, or the human author if explicitly provided.
- Use the exact model identifier or display name exposed by the active runtime for model fields, for example `gpt-5.4`, `gpt-5.3-codex`, or `GPT-5.5`.
- Do not record only a generic model family such as `GPT-5`, `GPT-4`, `Claude`, or `Gemini` when a more specific runtime model identifier or display name is available.
- If the runtime does not expose an exact model identifier, record the most precise deterministic runtime identity available and say that the exact ID was unavailable, for example `Codex (GPT-5-based; exact runtime model ID unavailable)`. Do not silently fall back to the family label alone.
- Use full ISO 8601 UTC timestamps for metadata values, in `YYYY-MM-DDTHH:MM:SSZ` format. Do not use local timezone offsets in these fields.
- Despite the field name `Creation Date`, the value must be a full timestamp for auditability and provenance.
- For non-Markdown descriptive deliverables that support a native metadata/header block, mirror the same fields in that format.

## Examples

### New planning document (caddis / Claude Code)

```yaml
---
type: plan
status: draft
feature: feat-2026-0609-auth-rework
creation-agent: caddis
Original Author: Claude Code
Creation Date: 2026-06-09T14:30:00Z
Creating Model: claude-sonnet-4-6
---
```

### New planning document (junai-vscode / GitHub Copilot)

```yaml
---
type: plan
status: draft
feature: FEAT-2026-0520-doc-metadata
creation-agent: github-copilot
Original Author: Planner
Creation Date: 2026-05-20T18:42:11Z
Creating Model: Claude Sonnet 4.6
---
```

### Updated existing document

```yaml
---
type: runbook
status: current
feature: standalone
creation-agent: caddis
Original Author: Claude Code
Creation Date: 2026-05-18T09:14:32Z
Creating Model: claude-sonnet-4-6
Last Author: Claude Code
Last Updated: 2026-06-09T15:00:00Z
Last Model Used: claude-sonnet-4-6
---
```
