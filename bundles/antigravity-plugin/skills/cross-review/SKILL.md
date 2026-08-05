---
name: cross-review
description: Cross-vendor code review of the current diff — a second-vendor model (DeepSeek/GLM/any OpenAI-compatible endpoint) reviews your changes to catch bugs a same-vendor reviewer misses
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
Optional: `--base-url <url>`, `--model <id>` (env always overrides the preset).

**A large diff is batched, not refused.** Over `REVIEW_MAX_DIFF_CHARS` (default 60,000) the tool splits
on whole-file boundaries and reviews each batch, and the verdict is CLEAN only if every batch is. Exit 2
now means the narrower case — a **single file** too big to split, or more batches than the cap. When you
see it, the fix is usually to review that one file separately, not to narrow `--range`; don't raise
`--max-diff-chars` blind.

**Do not alternate providers on a schedule.** DeepSeek is the default because it has actually found real
bugs that same-vendor passes missed; GLM is the documented fallback, used automatically when DeepSeek is
unavailable and you did not name a provider. The policy lives in `oss_review.py`'s `FALLBACK_PROVIDERS`
comment — a rota that sends half your phases to a provider observed timing out three phases running buys
variety it never actually collects, and a review that silently does not happen is the same failure class
as a diff that silently is not read. Name a provider explicitly only when you have a reason.

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
