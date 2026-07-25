---
description: Rebuild the KB index (.claudster/kb/DOC-MAP.md) — create it if missing, index un-indexed notes, report dangling links
---

# /kb — bring the knowledge-base index up to date

Reconcile `.claudster/kb/DOC-MAP.md` (the KB index) with the notes on disk. Use this in a repo that
has the harness but no KB yet (the KB was introduced recently), or after adding/removing KB notes.

## Step 1 — locate the checker
It ships with the harness. Try, in order:
- `scripts/check_doc_coverage.py` — a project set up via `setup-project-ai` (checker copied in).
- `claude-harness/scripts/check_doc_coverage.py` — the harness source repo itself.

## Step 2 — run the reindexer
```
python <path>/check_doc_coverage.py --reindex
```
It is **additive and safe** — never deletes your rows:
- **Missing map** → creates `.claudster/kb/DOC-MAP.md` from a scaffold, pre-linking the repo's obvious
  reference docs (README, `docs/…`) and any existing `.claudster/kb/*.md` notes.
- **Existing map** → indexes any KB note that isn't yet linked (adds a row with a placeholder description).
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
    python <path>/check_doc_coverage.py --prune
    ```
    `--prune` removes *only* index rows that link to missing files (never valid rows, never prose),
    and still indexes any orphan notes in the same run.

## Step 4 — verify clean
```
python <path>/check_doc_coverage.py --check
```
Exit `0` = the index is honest (no dangling links; every note indexed). The SessionStart hook will now
surface the `[DOC-MAP]` "read the index first" pointer for future sessions in this repo.

## KB note format (OKF-lite — mandatory for every new note)

Every new `.claudster/kb/*.md` note starts with this frontmatter block (`type` is required;
the rest recommended). `DOC-MAP.md` is the index, not a note — it stays frontmatter-free:

```yaml
---
type: note                 # note | runbook | design | reference
title: <human title>
description: <one line — keep it identical to the note's DOC-MAP row description>
tags: [topic, topic]
timestamp: 2026-01-01      # ISO date of last substantive update
---
```
