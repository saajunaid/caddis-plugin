# <slug> roadmap

Runner host: HOSTNAME

The roadmap file on `origin/main` is the only truth. Change it with `scripts/caddis_roadmap.py` (each change is a small
docs PR), never by a direct push. Only `rollup` sets a milestone `done`.

## Milestones
| ID | Milestone | Phases | Depends on | Exit check | Status | Owner | Target |
|---|---|---|---|---|---|---|---|
| S1 | <what is true when it is done> | <plan>#1, <plan>#2 | - | `<command that exits 0 when S1 holds>` | todo | runner | <date> |

## Blockers
| Milestone | Type | Reason | Check |
|---|---|---|---|

## Notes

- Status: todo, in-progress, code-done/data-pending, done or not-needed (blocked = has a Blockers row).
- Blocker types: owner-gate, external, shared, calendar or data-condition (Check: a command, added by the owner
  only; recheck runs it in a worktree of origin/main and clears that row on exit 0). A calendar blocker's Check is
  an ISO date YYYY-MM-DD; recheck clears the row once that date has passed.
- Status not-needed needs --reason "dropped: why" or --reason .caddis/parking-lot/file.md; the reason is added
  below as "- id not-needed: reason (date)".
- status lists each blocker row older than 14 days as "old blockers: id type (N days)"; the age comes from git.
- A malformed section (wrong cell count, a row without a leading pipe, a line right after the table, a pipe in
  prose, a second table, a renamed heading) stops every command: fix it by a PR. Escape a pipe in prose as \|.
- This file allows only headings, plain paragraphs, lists and pipe tables: no code fences, no HTML, no setext
  headings, no control or non-ASCII whitespace characters. GitHub would hide or move lines the parser reads, so
  each one is a parse error.
- Owner: runner (or empty) = the runner may take it; a session name = that session does it by hand.
- A Depends on change cites a decision id from decisions.md in the Milestone cell: `S9 (dep waived: D4)`.
