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
Locate the tool (stdlib-only, no install), in order:
- `.github/tools/oss_review.py` — this project vendors its own copy.
- `${CLAUDE_PLUGIN_ROOT}/scripts/oss_review.py` — the plugin-bundled copy (every install has this;
  use it whenever the project has no local copy).
```
python <resolved-path>/oss_review.py                     # DeepSeek eyes (default)
python <resolved-path>/oss_review.py --provider glm      # GLM eyes
python <resolved-path>/oss_review.py --range $ARGUMENTS  # review a git range, e.g. origin/main..HEAD
```
Optional: `--base-url <url>`, `--model <id>` (env always overrides the preset).
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
