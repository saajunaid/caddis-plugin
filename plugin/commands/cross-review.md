---
description: Cross-vendor code review of the current diff — a second-vendor model (DeepSeek/GLM/any OpenAI-compatible endpoint) reviews your changes to catch bugs a same-vendor reviewer misses
argument-hint: [git range, e.g. origin/main..HEAD]
---

# /caddis:cross-review — a second-vendor set of eyes on your diff

Run a cross-vendor review of the current changes with a DIFFERENT model family than the one that wrote them
(default **DeepSeek** — the cheapest + most architecturally distinct-from-Claude option). Use after a phase
is green and before you commit, or for a second opinion on a risky diff. This is the *cross-vendor*
complement to `/caddis:code-review`, not a replacement.

## Prerequisite (one-time)
A provider key must be resolvable. Precedence: `REVIEW_API_KEY` > the provider's own env var
(`DEEPSEEK_API_KEY` / `GLM_API_KEY`) > `OSS_API_KEY` > the keys file (`~/.caddis/keys.env`,
overridable via `CADDIS_KEYS_FILE`). If your keys file is populated, no env setup is needed.
Details: the `coding/cross-review` skill and the **Providers & keys** guide.

## Run it
Resolve the tool path deterministically — check only these two exact locations, in order, and
**never search the filesystem for it** (see Rules below):
```bash
if [ -f ".github/tools/oss_review.py" ]; then
  TOOL=".github/tools/oss_review.py"                              # this project vendors its own copy
elif [ -f "${CLAUDE_PLUGIN_ROOT}/scripts/oss_review.py" ]; then
  TOOL="${CLAUDE_PLUGIN_ROOT}/scripts/oss_review.py"               # the plugin-bundled copy
else
  echo "oss_review.py not found at either known location — report this and stop. Do NOT search for it."
  exit 3
fi
```
```
python "$TOOL"                                           # DeepSeek eyes (default)
python "$TOOL" --provider glm                            # GLM eyes
python "$TOOL" --range $ARGUMENTS                        # review a git range, e.g. origin/main..HEAD
```
Optional: `--base-url <url>`, `--model <id>` (env always overrides the preset). If it exits 2 with a
"diff is N chars, over the review ceiling" message, the diff is too large to review safely in one
pass — narrow `--range` or review in smaller chunks; don't raise `--max-diff-chars` blind.
**Alternate the provider between reviews** (DeepSeek one diff, GLM the next) — different model
families have different blind spots, and alternation maximizes what the pair catches over time.

## Interpret the exit code
- **0 — REVIEW: CLEAN** → no blocking issues. Proceed.
- **1 — REVIEW: BLOCKING** → read the printed findings, then **FIX each blocking item** (or explicitly
  justify why one is a false positive). Re-run until CLEAN.
- **2 — error** → no verdict parsed, or a git/endpoint failure. Read stderr; do NOT treat as clean.
- **3 — misconfigured** → `REVIEW_API_KEY` is unset. Set it (see Prerequisite) and re-run.

## Rules
- Read-only second opinion — the tool never edits, commits, or pushes. YOU apply fixes in the main thread.
- Treat exit 2/3 as blocking-unknown, never as approval (the tool is fail-closed by design).
- A different vendor means a different style; weigh its findings on merit, don't cargo-cult them.
- **Never use `find`, `Get-ChildItem -Recurse`, or any other filesystem-wide search to locate
  `oss_review.py`.** Check only the two paths above. On Git Bash under Windows, `find /` (or any
  search rooted at `/`) walks every mounted drive, not just the repo — it can hang or take minutes.
  If neither path exists, stop and report it; don't go hunting for the file.
