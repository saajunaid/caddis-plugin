---
name: cross-review
description: Cross-vendor code review — have a different vendor's model (DeepSeek/GLM/any OpenAI-compatible endpoint) review the current diff to catch bugs a same-vendor reviewer misses. Use after a phase is green and before commit/merge, or for a second opinion on a risky diff.
---

# Cross-Review — a second-vendor set of eyes on your diff

A different vendor's model has different blind spots. Claude reviewing Claude's diff shares those
blind spots; a **DeepSeek** (or GLM, or any OpenAI-compatible) reviewer catches a different class of
issue. This skill runs that second reviewer over the current changes and acts on its verdict.

## When to use
- After a phase is green, **before** you commit or merge.
- On a risky diff (auth, crypto, data-touching, concurrency) where a second opinion is cheap insurance.
- NOT a replacement for the in-repo `/caddis:code-review` — this is the *cross-vendor* complement.

## Check the key FIRST, and ask if it is missing

```bash
python "$TOOL" --check-config
```

Exit 0 prints which providers have a key. **Exit 3 means nothing is configured — stop and ask the
user before reading any diff.** Do not proceed, and do not silently skip the review.

Ask with `AskUserQuestion` which provider to set up, then write the key to `~/.caddis/keys.env` as
`DEEPSEEK_API_KEY=<key>` (or the matching variable). That file sits outside every git repo, so it
cannot be committed by accident. **Never put a key in the repo, in a command, or in a reply.**

This used to fail mid-task with a commit pending — the worst moment to go hunting for a credential.
A command that fails once at an inconvenient moment does not get retried, so the safety check is
quietly lost and nothing records the loss. The script stays non-interactive because it also runs
headless, where a stdin prompt hangs instead of asking; the asking is the agent's job.

If a key exists for a *different* provider than the one requested, the error names it and gives the
exact flag (`--provider glm`). Read the message before concluding anything is missing.

## Prerequisites (one-time)
Only the key is mandatory — the tool ships **provider presets** (default `deepseek`, the cheapest + most
architecturally distinct-from-Claude option; a review costs well under a cent):
```
REVIEW_API_KEY   = <your provider key>     # REQUIRED (exit 3 without it)
REVIEW_PROVIDER  = deepseek                 # optional: deepseek | glm | openrouter (default deepseek)
REVIEW_BASE_URL  = ...                      # optional: overrides the preset's URL
REVIEW_MODEL     = ...                      # optional: overrides the preset's model id
```
Switch provider with one flag: `--provider glm` (or `REVIEW_PROVIDER=glm`). **Future-proofing:** model ids
churn — the preset table in `oss_review.py` is the one place to edit a rename, and `REVIEW_MODEL` /
`REVIEW_BASE_URL` always win, so you can point at any new id without touching code.

## How to run
From the repo root. Resolve the tool path deterministically — check only these two exact
locations, in order, and **never search the filesystem for it** (see Rules below):
```bash
# THE PLUGIN COPY WINS. It is the one `caddis update` refreshes; a vendored copy is a snapshot
# of whatever caddis shipped the day someone copied it, and it never updates again.
if [ -f "${CLAUDE_PLUGIN_ROOT}/scripts/oss_review.py" ]; then
  TOOL="${CLAUDE_PLUGIN_ROOT}/scripts/oss_review.py"
  # A vendored copy that DIFFERS is a live hazard, not a curiosity — say so, do not stay silent.
  if [ -f ".github/tools/oss_review.py" ]      && ! diff -q ".github/tools/oss_review.py" "$TOOL" >/dev/null 2>&1; then
    echo "[cross-review] WARNING: .github/tools/oss_review.py differs from the caddis copy and is"
    echo "               being IGNORED. Delete it, or keep the local change deliberately."
  fi
elif [ -f ".github/tools/oss_review.py" ]; then
  TOOL=".github/tools/oss_review.py"   # no plugin present — the vendored copy is all there is
else
  echo "oss_review.py not found at either known location — report this and stop. Do NOT search for it."
  exit 3
fi
```

> **Why the plugin copy is first.** It used to be second. On 2026-08-10 a repo ran a stale vendored
> `oss_review.py` and got `REVIEW: CLEAN` on a database write path that was never reviewed. The bug
> had been fixed on 2026-08-01 — the fix just never reached the caller, because a file someone
> copied weeks earlier silently won. `caddis_gate.py vendor-drift` now fails on the same condition.
```
python "$TOOL"                                             # review the working tree (staged+unstaged)
python "$TOOL" --range origin/main..HEAD                   # review a branch's commits
```
Optional flags: `--cwd <repo>`, `--base-url <url>`, `--model <id>` (override the env).

**Diff-size ceiling.** A diff over `REVIEW_MAX_DIFF_CHARS` (default 60,000 chars) is **split into batches** on whole-file boundaries and each batch reviewed separately (verdict is CLEAN only if every batch is). Exit 2 now means a *single unsplittable file* over the ceiling, or too many batches — not an ordinary large diff. Previously it was refused with exit 2
*before* any LLM call — an oversized diff has been observed to come back either an empty response, or
worse, a `REVIEW: CLEAN` with zero real engagement. If you hit this, narrow `--range` or review in
smaller chunks; don't just raise `--max-diff-chars` without knowing the endpoint's real limit.

## Interpret the exit code
- **0 — REVIEW: CLEAN** → no blocking issues. Proceed.
- **1 — REVIEW: BLOCKING** → the reviewer found blocking issues. **Read the printed findings, then FIX
  each blocking item** (or, if you judge one a false positive, state explicitly why it's safe to ignore).
  Re-run until CLEAN.
- **2 — error** → no verdict parsed, a git failure, or an endpoint/parse failure. Read stderr; do not
  treat this as CLEAN — investigate.
- **3 — misconfigured** → `REVIEW_API_KEY` is unset. Set it (see Prerequisites) and re-run.

## Rules
- This is a **read-only second opinion** — the tool never edits, commits, or pushes. YOU apply fixes in
  the main thread after reading the findings.
- Treat exit 2/3 as blocking-unknown, never as approval (the tool is fail-closed by design).
- Different vendor ⇒ different style; weigh its findings on merit, don't cargo-cult them.
- **Never use `find`, `Get-ChildItem -Recurse`, or any other filesystem-wide search to locate
  `oss_review.py`.** Check only the two paths above. On Git Bash under Windows, `find /` (or any
  search rooted at `/`) walks every mounted drive, not just the repo — it can hang or take minutes.
  If neither path exists, stop and report it; don't go hunting for the file.
