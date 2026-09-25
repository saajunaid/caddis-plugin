---
name: mmr
description: Multi-Model Review & Runner (MMR) — run an ad-hoc task in an isolated multi-lane sandbox with rate-limit failover, test gates, and second-vendor review, or run a fast cross-model review on a diff
---

# /caddis:mmr — Multi-Model Review & Runner

Execute an ad-hoc task across model lanes (GLM-5.3 &rarr; Codex Sol &rarr; Claude) inside an isolated
git worktree with automated test gates and second-vendor review (DeepSeek). Destroys the worktree
immediately on completion (zero worktree leaks) and leaves the output on a clean branch with a
simple Verdict Card.

When invoked without a task prompt (or with a git range), `/mmr` runs a direct cross-model diff review.

The user typed: **$ARGUMENTS**. Route it to one of the commands below: `keep`, `drop` or `status`
as given; a git range to `review --range`; empty to `review`; anything else is the task for `run`.

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
- **Immediate Worktree Cleanup:** Stashes/commits results to `lane/adhoc-<slug>` and immediately removes the worktree. Zero open worktrees remain.
- **Verdict Card:** Prints PASS/FAIL summary with diff stats and next actions.

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
- Deletes the branch `lane/adhoc-<slug>`.
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
- Fast cross-model review of working tree or git range (e.g., `origin/main..HEAD`).

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
