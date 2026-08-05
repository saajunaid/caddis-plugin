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

## The three tiers

caddis follows **OKF-lite** (Open Knowledge Format — the frontmatter layer only; the `raw/` + `+wiki/`
restructure is deliberately skipped, see `.caddis/parking-lot/kuns-tools-and-okf.md`). As of OKF **v0.2** the
schema is layered, and only the first tier is required:

| Tier | Fields | Rule |
|---|---|---|
| **0 — OKF core** | `type` | **Required.** The only field whose absence is a defect. |
| **1 — caddis provenance** | `status`, `feature`, `creation-agent`, `Original Author`, `Creation Date`, `Creating Model` | **Expected on new documents** authored through caddis workflows (the house convention below). |
| **2 — OKF v0.2 trust signals** | `stale_after`, `verified`, `generated` | **Recommended.** Add when the document has a re-verify horizon or has been confirmed by a human/hub. |

> **Backward compatibility is load-bearing.** Every field added at v0.2 is *optional and additive*. A
> document that declares only `type` is valid. A document written before v0.2 — no `stale_after`, no
> `verified`, no `generated`, using the `creation-agent` / `Creating Model` fields — remains fully valid
> and must **never** be rewritten in bulk to adopt the new fields. Tooling treats a missing trust field
> as silence, not as an error.

## Required metadata fields

When creating a **new** document, add YAML frontmatter at the top and include:

```yaml
type: plan|prd|adr|design|runbook|handoff|analysis|review|prompt
status: draft|current|done|superseded          # or OKF: draft|stable|deprecated — see the mapping below
feature: <feature-slug or chain_id that owns this document>
creation-agent: caddis
Original Author: <active author or agent name>
Creation Date: <YYYY-MM-DDTHH:MM:SSZ>
Creating Model: <exact runtime model identifier or display name>
```

`title`, `description`, and `tags` are **recommended** on any document a reader might find by search
rather than by link (KB notes especially — see the KB note schema in `/kb` and the knowledge-transfer
agent, which both point at this file).

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

`status` is the document's lifecycle state. caddis's vocabulary and OKF v0.2's vocabulary are **both
accepted** — they describe the same axis at different granularity, and neither supersedes the other.

**caddis vocabulary (canonical for work-tracking documents — plans, PRDs, reviews):**
`draft` and `current` are **active**; `done` and `superseded` are **terminal**. Use `done` when the
work a document describes is complete; use `superseded` when a newer document replaces it.
- **`done` is the canonical terminal value.** `shipped` and `implemented` are accepted legacy
  synonyms — tooling treats them as terminal — but prefer `done` in new and updated documents.
  (`ready` is NOT terminal: it means approved-and-waiting-to-start, i.e. active.)

**OKF v0.2 vocabulary (canonical for reference documents — KB notes, runbooks, guides):**
`draft` → being written, do not rely on it yet. `stable` → trustworthy, the default reading.
`deprecated` → still present but no longer to be relied on.
- **When `status` is absent, read it as `stable`.** This is OKF's default and it is what makes the
  field safe to add: every existing document without a `status` line keeps its current meaning.

**Mapping** (use when translating between the two, e.g. reading an OKF doc into a caddis workflow):

| caddis | OKF v0.2 | Meaning |
|---|---|---|
| `draft` | `draft` | Not yet reliable. |
| `current` / `ready` | `stable` | Active and trustworthy. |
| `done` (`shipped`, `implemented`) | `stable` | Work finished; the record stands. |
| `superseded` | `deprecated` | Replaced — do not rely on it. |

Pick **one** vocabulary per document and stay in it; do not write `status: done, stable`.
- `feature` — the feature slug or chain ID that this document belongs to (e.g. `feat-2026-0609-auth-rework`). Use `standalone` if the document is not tied to a feature.
- `creation-agent` — the plugin or tool that created the document. Use `caddis` for documents produced by the caddis Claude Code plugin; use `github-copilot` for documents produced by the GitHub Copilot junai-vscode extension; use `human` for manually authored documents.

## Trust signals (OKF v0.2 — recommended, never required)

Three optional fields that record *how much a reader should trust this document, and until when*.
All three are additive: omitting them is always valid.

### `stale_after: <YYYY-MM-DD>`

The date by which the document should be **re-verified**. Past that date the content is not wrong —
it is *unconfirmed*. Set it when a document's accuracy depends on something that drifts (a published
version, an external API, a fleet state, a quota reset). Omit it for documents with no natural
expiry (an ADR recording a decision already made does not go stale).

```yaml
stale_after: 2026-12-31
```

> **Declaration only.** Nothing acts on `stale_after` today — there is no auto-tidy, no sweep, no gate
> that fails on an expired document. Building one is deliberate future work; the field exists now so
> that when such a tool arrives the data is already there. Do not write tooling that deletes,
> archives, or rewrites a document because its `stale_after` has passed.

### `verified: [ { by: <actor>, at: <ISO-datetime> } ]`

A list of independent confirmations. This formalises caddis's existing **"hub-validated"** pattern:
when a human or the Advisory Hub reviews a plan/review and confirms it, that confirmation is recorded
here rather than in prose.

```yaml
verified:
  - { by: human:clawnshaw, at: 2026-07-28T10:00:00Z }
  - { by: hub:advisory, at: 2026-07-28T11:30:00Z }
```

- `by` — who confirmed. Namespace the actor: `human:<handle>`, `hub:<name>`, or an agent/model id.
- `at` — full ISO 8601 UTC timestamp, `YYYY-MM-DDTHH:MM:SSZ`.
- **Append, never rewrite.** Each entry is a historical fact; a re-verification adds a row.
- **`verified` is distinct from `generated`.** `generated` records who *produced* the document;
  `verified` records who *checked* it. A document generated and "verified" by the same agent in the
  same breath carries no trust signal — do not self-verify. An entry means a second party looked.

### `generated: { by: <agent-or-model>, at: <ISO-datetime> }`

OKF's consolidation of authorship provenance. It says the same thing as caddis's
`creation-agent` + `Original Author` + `Creating Model` + `Creation Date` block, in one field.

```yaml
generated: { by: caddis/claude-opus-4-8, at: 2026-07-28T09:00:00Z }
```

- **Recommended for new documents.** Prefer `generated` going forward.
- **The legacy fields stay valid — permanently.** `creation-agent`, `Original Author`,
  `Creating Model`, and `Creation Date` are not deprecated and are not to be stripped. There is
  **no forced rewrite**: do not migrate existing documents to `generated` as a bulk change.
- Carrying both is allowed (and is what a migrated document looks like); keep them consistent.
- The same precision rules apply to `by` as to `Creating Model`: record the exact runtime model
  identifier, never a bare family name like `Claude` or `GPT-5`.

## Deliberately skipped from OKF v0.2

Two parts of the v0.2 spec are **not adopted**, and this is a decision rather than an oversight:

- **`sources:` with `usage_count` / data-catalog provenance** — the field models a concept derived
  from catalogued *data assets*, ranked by how often a warehouse table is queried. caddis documents
  describe code and process; they have no data catalog behind them and no usage counter to read, so
  the field would carry invented numbers. Ordinary Markdown links already record where a document
  came from.
- **The entire `Attested Computation` type** (`executor`, `attester`, `receipt`, `parameters`) — it
  encodes a re-runnable BigQuery job whose result an attester can re-derive and prove. caddis's
  equivalent of "prove it still holds" is the test suite and the validation gates, which are already
  executable and already run in CI. Adding a parallel attestation format would duplicate them.

Both are sound for the data-analytics/BigQuery setting OKF was written in. Neither fits a dev
harness. Revisit only if caddis documents ever start describing data assets directly.

## Merge rules

- Merge these fields into the existing YAML frontmatter block. Do **not** replace document-specific keys such as `description`, `type`, `status`, `chain_id`, `approval`, `tags`, `model`, `tools`, `stale_after`, `verified`, `generated`, or `applyTo`.
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

### New document with OKF v0.2 trust signals (recommended shape)

```yaml
---
type: plan
status: stable
feature: feat-2026-0728-okf-trust-signals
generated: { by: caddis/claude-opus-4-8, at: 2026-07-28T09:00:00Z }
verified:
  - { by: human:clawnshaw, at: 2026-07-28T10:00:00Z }
stale_after: 2027-01-31
---
```

### Legacy document — still valid, do not rewrite

```yaml
---
type: analysis
creation-agent: caddis
Creation Date: 2026-05-02
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
