---
description: Review local caddis usage over a window, surface prioritised recommendations, and apply config changes in one step
argument-hint: "[days]"
---

# /usage-review — harness self-tuning

Review your actual local usage patterns, surface caddis-specific improvements, and optionally
apply config changes in one step. Data stays on-machine — no telemetry, no server.

## Step 1 — run the analysis script

Resolve the script path:
- Plugin install: `${CLAUDE_PLUGIN_ROOT}/scripts/usage_review.py`
- harness (caddis) checkout: `scripts/usage_review.py`

Run it:
```
python "<resolved-path>" [--days $ARGUMENTS]
```

- Default window is **7 days**. If the user passed a number (e.g. `/usage-review 14`), use it.
- Run from the project root so `.claude/usage-log.jsonl` is found correctly.
- If the script exits with "No sessions found", tell the user and stop — no further steps.
- The script prints a markdown report to stdout and writes `.claude/usage-review.html`.

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

## Step 5 — offer to schedule a recurring review (optional)

After reporting the outcome, ask once:

> "Want me to schedule this to run automatically every Wednesday? I can set it up with `/schedule`."

If the user says yes, use the `schedule` skill to create a weekly routine:

```
Schedule a recurring cloud routine: every Wednesday, run /usage-review
```

The routine should fire mid-week so findings are fresh for the next work sprint. If the user
declines, skip silently — the SessionStart nudge in `inject_relay.py` already covers the
"you haven't reviewed in 7 days" case.

## Notes

- HTML dashboard written to `.claudster/reviews/usage-review.html`. Override the directory with
  `--output-dir <dir>` if needed. The usage log is read from `.claudster/usage-log.jsonl`, falling
  back to the legacy `.claude/usage-log.jsonl` during the migration.
- `.claudster/.last-usage-review` is updated on each run — the SessionStart hook uses it to nudge
  users who haven't reviewed in 7+ days.
- `est_cost_usd` is an estimate from token counts, not actual billing. The Max plan is rate-limited,
  not charged per token — treat it as a relative signal, not an invoice.
