---
name: golden-nuggets
description: "Extract durable tribal knowledge ('gold nuggets') from a codebase or a set of changed files and route each to its correct destination - instruction file, runbook, hub, or (in CI capture mode) a review inbox. This SKILL.md is the single source of truth for nugget categories, routing rules, write rules, inbox format, and verification gates. It is read by the knowledge-transfer agent (pipeline mode), by the /golden-nuggets prompt (independent mode), and referenced by the CI extraction script (capture mode). Use when capturing what was learned after a feature, fix, sprint, incident, or release."
mode: agent
tools: ['codebase', 'editFiles', 'search']
---

# Golden Nuggets - Knowledge Capture Core

This skill defines what counts as a durable nugget, where it belongs, and how to write it without damaging existing docs. The same extraction logic applies in all modes, but the write target changes by mode.

---

## Modes

| Mode | Invoked by | Judgement present? | Write target |
|------|------------|--------------------|--------------|
| Pipeline | `knowledge-transfer` agent at a gated stage | Yes | Live instruction files, runbooks, or the managed hub region |
| Independent | `/golden-nuggets` prompt | Yes | Live instruction files, runbooks, or the managed hub region |
| Capture (CI) | `extract_nuggets.ps1` in `release_metadata` | No | `.github/agent-docs/nuggets-inbox.md` only |

Why this split:

- Writing to a live `*.instructions.md` changes future agent behavior.
- Pipeline and independent modes include human or agent judgement, so live writes are allowed.
- CI capture mode has no judgement, so it may create candidates only. It must never write live instruction files, runbooks, or the hub.

---

## Verification Gate

In pipeline and independent modes, follow this order exactly:

1. Extract candidate nuggets.
2. Route each nugget.
3. Write each nugget to its live destination.
4. Verify each live write landed by re-reading or searching for a distinctive phrase.
5. Only after live writes are verified, write the session log.

If you are about to update the log before any live write has been verified, stop and go back.

### Completion rule

Live writes are the primary deliverable outside CI mode. The stage is complete only when one of these is true:

- At least one live instruction file, runbook, or managed hub region was updated and verified.
- No durable nugget existed, and you say so explicitly.

An empty "Live writes" section with no explicit "no durable nugget existed" justification means the stage failed.

---

## Step 1 - Detect the Tech Stack

Identify the primary language/runtime, frameworks, hosting model, database or storage layer, test framework, CI/CD pipeline, and any unusual infrastructure. Use that to decide which nugget categories are relevant.

---

## Step 2 - Extract Gold Nuggets

Before scanning, list `*.instructions.md` files in `.github/instructions/` and note their `applyTo` patterns. Extract only what is not already captured.

Categories:

- Environment: env var loading order, config precedence, dev-vs-prod differences, reverse proxy or IIS rules, auth handshakes, port/CORS behavior.
- Architecture: startup sequencing, DI registration rules, multi-process coexistence, initialization rules, caching behavior.
- UI / Embedded Frontend: iframe or postMessage contracts, lifecycle rules, z-index or positioning behavior, state rules, bug fixes that must not be reverted.
- Data and Query Patterns: query composition, ORM or adapter quirks, cross-schema access, pooling, migration rules, externalized query rules.
- Test and CI Patterns: fixture setup, mock conventions, test isolation, flaky-test causes, CI flags, E2E sequencing.
- Critical Rules: conventions enforced by practice rather than lint, naming/import patterns, DRY boundaries, logging/security rules, feature-flag wiring.
- Operational Procedures: restart sequences, deploy decision trees, incident checks, verification steps, rollback or connectivity procedures.

### Capture mode input rules

In CI capture mode, do not scan the full codebase. Work only from release-range commit metadata. Consider only `feat`, `fix`, `perf`, and `refactor` conventional-commit subjects. Ignore `chore`, `docs`, `style`, `test`, `build`, and `ci`.

Each candidate must carry enough metadata for later review:

- `fingerprint`: stable hash from the normalized commit subject
- `source`: `ci-release-capture`
- `shape`: `rule-shaped` or `project-local`
- `suggested-route`: `promote-to-pool` or `keep-local`
- `raw`: original conventional-commit subject
- `from-commits`: one or more short shas

CI produces candidates, not conclusions.

---

## Step 3 - Route Each Nugget

Route to the most specific destination before falling back to the hub.

- Instruction file: `.github/instructions/*.instructions.md` for conventions, framework rules, component rules, or scoped patterns.
- Runbook: `docs/runbooks/` or equivalent for operational procedures.
- Hub: `copilot-instructions.md`, but only inside the `<!-- junai:start -->` to `<!-- junai:end -->` region, and only for genuinely global context.

In capture mode, "route" means tagging the candidate with `proposed-target` and `suggested-route`. CI still writes only to the inbox.

### Shape tag

- `rule-shaped`: generalizable pattern that may deserve promotion to the pool later.
- `project-local`: specific to this project's wiring or infrastructure and likely to stay local.

Fallback:

- If no instruction files or runbooks directory exist, use the hub.

---

## Step 4 - Write Rules (Pipeline and Independent Modes)

Write directly when:

- The nugget is genuinely new.
- The nugget adds detail without contradicting existing docs.

Stop and ask before writing when:

- Existing docs state a rule that the code now contradicts.
- A documented rule appears to be intentionally worked around in several places.

Never:

- Delete or rewrite existing sections.
- Remove Commands, pipeline, CI, deploy, or key-files sections.
- Reduce existing detail.
- Duplicate content in both the hub and a more specific instruction file or runbook.

After every live write, verify it landed.

---

## Step 4-CI - Write Rules (Capture Mode Only)

Append each candidate to `.github/agent-docs/nuggets-inbox.md`. Do not touch live instruction files, runbooks, or the hub.

Inbox entry format:

```md
## CANDIDATE {iso-date} - {release-version}
- fingerprint: {stable fingerprint derived from normalized commit subject}
- source: ci-release-capture
- shape: rule-shaped | project-local
- category: {category}
- suggested-route: keep-local | promote-to-pool
- proposed-target: {path/to/file.instructions.md | runbook | hub}
- from-commits: {sha7}, {sha7}
- raw: {original conventional-commit subject}
- nugget: {one-paragraph durable lesson, in the agent's words}
- status: pending
```

---

## Step 5 - Write Session Log (Pipeline and Independent Modes)

Only after live writes are verified, prepend to `docs/gold-nuggets-log.md`:

```md
## Gold Nuggets Session - {date}
### Added
- {destination file} -> {section} -> {one-line summary}
### Conflicts flagged
- {what file said} vs {what code shows} - {resolution}
- None
### Skipped (nothing new)
- {category}
> Review/archive once verified.
```

The log records writes that happened. Capture mode does not write the log.

---

## Inbox Hygiene (Capture Mode)

- Cap: if pending candidates are already `>= 15`, append nothing and emit `inbox full - review pending`.
- TTL: candidates older than 14 days are discarded by the review tool, not by CI.
- Dedup: never append a candidate whose normalized subject or fingerprint already exists in the inbox. If multiple commits in the same release range normalize to the same candidate, keep one block and merge the shas into `from-commits`.

The inbox should trend toward empty rather than growing forever.

---

## Quick Reference

```text
/golden-nuggets               Full extraction, all categories, write live
/golden-nuggets chat widget   Focus one area
/golden-nuggets ops           Operational procedures / runbooks only
```
