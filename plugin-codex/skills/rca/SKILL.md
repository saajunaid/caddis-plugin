---
name: rca
description: Record a root cause in one step — .caddis/rca/<date>-<slug>.md — or close one with the fixing commit
---

# /caddis:rca — record a root cause, or close one

A root cause found mid-task gets forgotten by the next session that hits the same symptom. This
command writes one down in a single step, and closes it later with the commit that fixed it.

The request is **$ARGUMENTS**.

## Mode select

| `$ARGUMENTS` | Do this |
|---|---|
| starts with `done ` | Go to **Close mode** |
| anything else | Go to **File mode** — the text is the symptom |

---

## File mode

### Step 1 — build the slug
Lower-case the symptom text, replace each run of characters outside `a-z0-9` with one `-`, trim
`-` from both ends, cap at 60 characters (`Login fails: 401!` → `login-fails-401`). If nothing is left after cleaning, **stop and ask the user for a shorter title** — the
one question this command may ask.

### Step 2 — pick the path
`.caddis/rca/<YYYY-MM-DD>-<slug>.md`, using today's date (UTC). Create `.caddis/rca/` first if it
does not exist.

**If that exact path already exists, refuse — never overwrite it.** Print the existing path and
stop; the user can open it directly, or pick different (more specific) symptom text so the slug
comes out differently.

### Step 3 — write the file

```markdown
---
type: rca
status: open
found: <YYYY-MM-DD>
---

# <symptom, verbatim>

## Symptom
<what was observed — the exact error, command, or behaviour>

## Root cause
<why it happened, not just what happened>

## Fix
<what changed to remove the cause>

## How verified
<the command or check that proves the fix, and its result>
```

Leave a section as its one-line prompt if the answer is not known yet — `/rca done` below is where
it gets filled in for real.

### Step 4 — verify

```bash
python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.137/scripts/caddis_gate.py" docs-check --root .
```

Exit 0 means the header is valid. Do not report the item as filed until this passes.

### Step 5 — report
One line: the path. Nothing else.

---

## Close mode — `done <file>`

`<file>` is a path under `.caddis/rca/`, optionally followed by a commit SHA.

1. If the file does not exist, say so and change nothing.
2. If its header does not carry `type: rca`, say so and change nothing.
3. If its `status:` is already `done`, say so and change nothing — closing an already-closed RCA is
   a no-op, not a re-close.
4. Otherwise set `status: done` and add `commit: <short SHA>` to the header. The SHA is whatever the
   user gave after the filename in `$ARGUMENTS`; if none was given, use `git rev-parse --short HEAD`.
   It must match `^[0-9a-f]{7,40}$`; if it does not, say so and change nothing.
5. Fill in **Root cause**, **Fix**, and **How verified** only with facts from this session or the
   fixing commit. A section you do not know stays as its Step 3 prompt; never guess.
6. Run the Step 4 docs-check. If it does not exit 0, restore the file and report the error.
7. Report the path and the recorded commit. Nothing else.

## Rules
- **Never** overwrite an existing RCA file. A repeat symptom is either the same file (edit it by
  hand) or genuinely different (use different symptom text so the slug comes out different).
- This command records facts about what already happened; it does not investigate or fix anything
  itself.
