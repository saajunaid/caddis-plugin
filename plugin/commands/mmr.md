---
description: Multi-Model Review & Runner (MMR) — run an ad-hoc task in an isolated multi-lane sandbox with rate-limit failover, test gates, and second-vendor review, or run a fast cross-model review on a diff
argument-hint: ["task description" | keep | drop | status | git-range]
stage: review
---

# /caddis:mmr — Multi-Model Review & Runner

Execute an ad-hoc task across model lanes (GLM-5.3 &rarr; Codex Sol &rarr; Claude) inside an isolated
git worktree with automated test gates and second-vendor review (DeepSeek). A full PASS commits
code changes and removes the worktree. A FAIL or PENDING keeps the worktree for inspection or
Claude-lane work. The result appears in a Verdict Card.

When invoked without a task prompt (or with a git range), `/mmr` runs a direct cross-model diff review.

The user typed: **$ARGUMENTS**. Route it to one of the commands below: `keep`, `drop` or `status`
as given; a git range such as `origin/main..HEAD` to `review --range`; empty to `review`;
anything else is the task for `run`. Pass supported run flags such as `--type` with the task.
An unknown flag returns a usage error.

The exit codes follow `caddis_exit.py`: 0 clean, 1 blocked, 2 advisory, 3 could not run,
4 error or bad usage, 5 round limit (`caddis_review.py --plan` only: stop, the owner decides). In particular, `caddis_adhoc.py` returns 4 for bad usage.

## Three rules: one attempt, one review
1. **Think before you send.** Before a task goes to any coder, write its edge cases and check the facts it depends on (one query or one file read).
2. **Run it before review.** The coder runs only the tests of the files it touched, in the foreground, each command under 10 minutes (split into parts if needed). Name the exact commands in the task. Never start the full suite in the background and never wait on a monitor for it: CI runs the full suite on every PR. Then run the change once on real data.
3. **Review by tier.** Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_gate.py" review-tier --range <base>...HEAD` (add `--plan <plan> --phase <N>` inside a plan; no `TIER:` line means tier 2).
   Tier 0: gates only. Tier 1-small: your self-check only. Tier 1: one review by another vendor; stop at
   the first CLEAN. Tier 2: one review by another vendor (two only when the owner asks). Fix blocking findings only;
   park the rest. Re-review only the fix diff, and only when the fix changed logic. After 3 rounds, ask the owner.

`/mmr` is for handing a task to another model, not for normal reviews. For a normal review, use
`/cross-review`.

## Natural Language Triggers
You can trigger MMR naturally without typing the full slash command:
- *"Run this on another lane: &lt;task&gt;"* &rarr; `/mmr "<task>"`
- *"Try this with multilane: &lt;task&gt;"* &rarr; `/mmr "<task>"`
- *"Keep it"* / *"Keep the changes"* &rarr; `/mmr keep`
- *"Drop it"* / *"Discard the attempt"* &rarr; `/mmr drop`
- *"Check mmr status"* / *"Which lanes are ready?"* &rarr; `/mmr status`
- *"Review this diff with mmr"* &rarr; `/mmr`

---

## Commands

### 1. Run an Ad-Hoc Task
```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_adhoc.py" run "<task description>" [--type backend|tests|docs|ui|hard]
# Shorthand:
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_adhoc.py" "<task description>"
```
- **Sandbox Isolation:** Creates an ephemeral 1-phase plan at `.caddis/orchestrator/adhoc/<slug>.md`.
- **Pre-flight Checks:** Verifies dirty tree and API keys. Warns if local edits exist.
- **Failover Cascade:** Automatically cascades from GLM to Codex to Claude if a lane is out of budget.
- **Local Test Gates:** Runs project test gates before review.
- **Cross-Vendor Review:** DeepSeek or GLM reviews the diff.
- **Worktree result:** PASS commits code changes to `lane/adhoc-<slug>` and removes the worktree. FAIL keeps it. A Claude-lane `PENDING` keeps it and prints the `NEXT:` step. Gates that never ran show `Gates: not run`.
- **No-op and gate failures:** A run with no code changes fails and keeps its worktree. A pytest gate that collects no tests also fails.
- **Verdict Card:** Prints PASS, FAIL, or PENDING with diff stats and next actions.
- **State per session:** The active task is saved in `.caddis/orchestrator/adhoc/latest-<session-id>.json` (session id from `CADDIS_SESSION_ID`, `CLAUDE_SESSION_ID` or `CLAUDE_CODE_SESSION_ID`). `keep`, `drop` and `status` use only your own session's task. An old un-keyed `latest.json` is adopted once by the first session that reads it.
- **Unique slug:** The `<slug>` ends in a random 6-character suffix, so two runs on the same day and topic never share a branch or plan.
- **No branch overwrite:** If `lane/adhoc-<slug>` already exists with commits not merged into the base (and is not this session's own recorded branch), the run fails, keeps its worktree and prints why.

### 2. Keep the Result
```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_adhoc.py" keep
```
- Keeps the output branch `lane/adhoc-<slug>`.
- **Main Branch Protection:** If you are on `main` or `master`, direct merge is disabled to protect trunk. Recommends running `/ship-pr`.
- If on a feature branch and the working tree is clean, provides squash-merge instructions.

### 3. Drop the Result
```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_adhoc.py" drop
```
- Removes a kept worktree, prunes its registration, and deletes the task branch.
- Deletes the ephemeral plan file and run logs.
- Workspace remains clean and untouched.

### 4. Check Status
```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_adhoc.py" status
```
- Displays API key readiness for all lanes (`Anthropic`, `DeepSeek`, `GLM`, `OpenAI`).
- Shows the latest task status, model used, and gates/review verdicts.
- Lists any unmerged `lane/adhoc-*` branches.

### 5. Review Diff Only
```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_adhoc.py" review [--range <range>]
# Shorthand (no args):
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_adhoc.py"
```
- Fast cross-model review of working tree or git range (e.g., `origin/main..HEAD`). A range can also be passed directly as the first argument.

---

## Tool Resolution
Resolve `caddis_adhoc.py` deterministically:
```bash
if [ -f "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_adhoc.py" ]; then
  TOOL="${CLAUDE_PLUGIN_ROOT}/scripts/caddis_adhoc.py"
elif [ -f "scripts/caddis_adhoc.py" ]; then
  TOOL="scripts/caddis_adhoc.py"
else
  echo "caddis_adhoc.py not found — report this and stop."
  exit 3
fi
```
