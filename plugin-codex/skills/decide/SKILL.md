---
name: decide
description: Record a decision in one step — .caddis/decisions/<date>-<slug>.md
---

# /caddis:decide — record a decision, once, before it gets re-litigated

A decision made mid-task and never written down gets re-argued the next time someone hits the same
fork. This command writes it as a single-step decision record.

The request is **$ARGUMENTS** — the decision, in a few words.

## Step 1 — build the slug
Lower-case the decision text, replace each run of characters outside `a-z0-9` with one `-`, trim
`-` from both ends, cap at 60 characters (`Use SQLite, not Postgres` → `use-sqlite-not-postgres`). If nothing is left after cleaning, **stop and ask the user for a shorter title** — the
one question this command may ask.

## Step 2 — pick the path
`.caddis/decisions/<YYYY-MM-DD>-<slug>.md`, using today's date (UTC). Create
`.caddis/decisions/` first if it does not exist.

**If that exact path already exists, refuse — never overwrite it.** Print the existing path and
stop; the user can open it directly, or pick different (more specific) decision text so the slug
comes out differently.

## Step 3 — write the file

```markdown
---
type: adr
status: current
found: <YYYY-MM-DD>
---

# <decision, verbatim>

## Context
<what forced the decision — the constraint, the conflicting options>

## Decision
<what was decided, as one plain sentence>

## Consequences
<what this makes easier, what it makes harder, what it rules out>
```

## Step 4 — verify

```bash
python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.134/scripts/caddis_gate.py" docs-check --root .
```

Exit 0 means the header is valid. Do not report the item as filed until this passes.

## Step 5 — report
One line: the path. Nothing else.

## Rules
- **Never** overwrite an existing decision file. There is no ID allocator and no revision counter —
  a changed decision is new decision text, which naturally gives it a new slug and a new file.
- This command records a decision already made; it does not itself weigh the options.
