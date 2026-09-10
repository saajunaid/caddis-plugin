---
name: usage-review
description: Review local caddis usage over a window, surface prioritised recommendations, and apply config changes in one step
---

# /usage-review — harness self-tuning

Review your actual local usage patterns, surface caddis-specific improvements, and optionally
apply config changes in one step. Data stays on-machine — no telemetry, no server.

## Step 1 — run the analysis script

Resolve the script path:
- Plugin install: `${CADDIS_PLUGIN_ROOT}/scripts/usage_review.py`
- harness (caddis) checkout: `scripts/usage_review.py`

Run it:
```
python "<resolved-path>" [--days $ARGUMENTS]
```

- Default window is **7 days**. If the user passed a number (e.g. `/usage-review 14`), use it.
- Run from the project root so `.caddis/usage-log.jsonl` is found correctly. (The legacy
  the legacy `.claude/usage-log.jsonl` is still read as a fallback during the migration.)
- If the script exits with "No sessions found", tell the user and stop — no further steps.
- The script prints a markdown report to stdout and writes
  `.caddis/reviews/usage-review.html` (override with `--output-dir`).

## Step 2 — present the report

Display the markdown output. Then add a single interpretive sentence identifying the **one most
impactful finding** — the one most likely to reduce rate-limit consumption or right-size the harness.

Do NOT paraphrase every finding in prose — the report is already the output.

## Step 3 — offer to apply

For each finding marked **[apply]** in the report, ask the user whether to apply it.
Show the diff before making the change. Never apply silently.

Two paths:
- **"Apply [R1]"** (or whichever ID) — apply that single finding.
- **"Apply all safe ones"** — apply every finding whose `apply_target.type` is `agent_frontmatter`
  (config-only, reversible). Show the full change list first, confirm, then apply.

For `agent_frontmatter` apply targets: find the `model:` line in the frontmatter block (between
the two `---` delimiters) of the named agent file and change its value. Show a diff-style preview
(`- model: old` / `+ model: new`) before writing.

## Step 4 — report outcome

After any applies, tell the user which files changed and suggest:
"Run `/usage-review` again after a few sessions to see the effect."

## Step 5 — do NOT offer to schedule this as a cloud routine

**This command cannot run as a cloud routine, and offering one produces a routine that fails.**

`/schedule` creates a **cloud** agent. This command reads `.caddis/usage-log.jsonl`, which the
local `Stop` hook writes on THIS machine and which is **gitignored** — so it is neither on the
cloud runner's filesystem nor in the clone it makes. The routine would fire on time and find
nothing.

That also settles a contradiction this file used to carry: the description says "Data stays
on-machine — no telemetry, no server", and the old Step 5 offered a cloud routine two screens
later. The description is the correct half.

**The recurring nudge already exists and is local.** Each run updates
`.caddis/.last-usage-review`, and the SessionStart hook reads it to remind you when a review is
overdue. Nothing to schedule.

## Notes

- HTML dashboard written to `.caddis/reviews/usage-review.html`. Override the directory with
  `--output-dir <dir>` if needed. The usage log is read from `.caddis/usage-log.jsonl`, falling
  back to the legacy `.claude/usage-log.jsonl` during the migration.
- `.caddis/.last-usage-review` is updated on each run — the SessionStart hook uses it to nudge
  users who haven't reviewed in 7+ days.
- `est_cost_usd` is an estimate from token counts, not actual billing. The Max plan is rate-limited,
  not charged per token — treat it as a relative signal, not an invoice.
