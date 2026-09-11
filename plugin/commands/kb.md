---
description: Rebuild the KB index (.caddis/kb/DOC-MAP.md) — create it if missing, index un-indexed notes, report dangling links
argument-hint: (no arguments — rebuilds .caddis/kb/DOC-MAP.md from the notes on disk)
stage: knowledge
---

# /kb — bring the knowledge-base index up to date

Reconcile `.caddis/kb/DOC-MAP.md` (the KB index) with the notes on disk. Use this in a repo that
has the harness but no KB yet (the KB was introduced recently), or after adding/removing KB notes.

## Step 1 — locate the checker
It ships with the harness. Try, in order:
- `scripts/check_doc_coverage.py` — a project set up via `setup-project-ai` (checker copied in).
- `claude-harness/scripts/check_doc_coverage.py` — the harness source repo itself.

## Step 2 — run the reindexer
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/check_doc_coverage.py" --reindex
```
It is **additive and safe** — never deletes your rows:
- **Missing map** → creates `.caddis/kb/DOC-MAP.md` from a scaffold, pre-linking the repo's obvious
  reference docs (README, `docs/…`) and any existing `.caddis/kb/*.md` notes.
- **Existing map** → indexes any KB note that isn't yet linked (adds a row with a placeholder description).
  It appends to the `## Knowledge base` table, or — in a map written by hand with no such heading —
  to the first table that already links sibling notes (`[x](x.md)`).
- **Could not index a note** (no table of notes anywhere) → says so and **exits 1**. Report it; do not
  treat the run as done.
- **Dangling links** (a linked file that's gone) → **reported, not removed** — handle them in Step 3.

## Step 3 — finish by hand
Read the `[kb]` summary it printed, then:
- For each **newly auto-indexed** note, open it and replace the placeholder description with a real
  one-line "what / when to read".
- If it reported **dangling** links (a linked file that's gone), decide per link:
  - The note was **moved/renamed** → fix the link target by hand.
  - The note is **gone for good** → remove its row. To clear all dangling rows at once, use the
    destructive opt-in — but **show the dangling list and confirm with the user first**:
    ```
    python "${CLAUDE_PLUGIN_ROOT}/scripts/check_doc_coverage.py" --prune
    ```
    `--prune` removes *only* index rows that link to missing files (never valid rows, never prose),
    and still indexes any orphan notes in the same run.

## Step 4 — verify clean
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/check_doc_coverage.py" --check
```
Exit `0` = the index is honest (no dangling links; every note indexed). The SessionStart hook will now
surface the `[DOC-MAP]` "read the index first" pointer for future sessions in this repo.

## Step 5 — was any of it the harness?

<!-- shared:harness-friction-question — keep byte-identical across commands; a test pins it -->
**One question, asked here because here is where you are already reflecting.** The observations
that reach caddis today are the ones someone happened to recall days later — so small, frequent
friction never arrives, which is exactly the friction worth fixing.

If a command was awkward, a gate fired wrongly, a doc sent you the wrong way: park it against the
harness, not this repo.

```
/caddis:park --harness <what was awkward, and what you expected>
```

Nothing to say is the normal answer. Say nothing and move on — this must not become a ritual.
<!-- /shared:harness-friction-question -->

## KB note format (OKF-lite — mandatory for every new note)

Every new `.caddis/kb/*.md` note starts with this frontmatter block. **`type` is the only required
field**; everything else is recommended. `DOC-MAP.md` is the index, not a note — it stays
frontmatter-free:

```yaml
---
type: note                 # note | runbook | design | reference
title: <human title>
description: <one line — keep it identical to the note's DOC-MAP row description>
tags: [topic, topic]
timestamp: 2026-01-01      # ISO date of last substantive update
# --- OKF v0.2 trust signals (all optional; omit rather than guess) ---
status: stable             # draft | stable | deprecated  (absent reads as stable)
stale_after: 2026-12-31    # re-verify by this date; nothing auto-acts on it
verified:                  # who CONFIRMED it (not who wrote it); append, never rewrite
  - { by: human:handle, at: 2026-07-28T10:00:00Z }
generated: { by: caddis/<model-id>, at: 2026-07-28T09:00:00Z }
---
```

The full schema, the caddis↔OKF `status` mapping, and what caddis deliberately skips from OKF v0.2
(`sources:`, `Attested Computation`) live in
`.github/instructions/document-frontmatter.instructions.md` in the caddis source repo. (Not a link: a relative path out of the plugin directory resolves nowhere once installed.)

**Backward compatible:** an existing note with no trust fields is still correct. Do not bulk-migrate
old notes — add the fields as notes are next touched.
