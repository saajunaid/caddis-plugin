---
description: Cross-vendor code review of the current diff — a second-vendor model (DeepSeek/GLM/any OpenAI-compatible endpoint) reviews your changes to catch bugs a same-vendor reviewer misses
argument-hint: [git range, e.g. origin/main..HEAD]
---

# /caddis:cross-review — a second-vendor set of eyes on your diff

Run a cross-vendor review of the current changes with a DIFFERENT model family than the one that wrote them
(default **DeepSeek** — the cheapest + most architecturally distinct-from-Claude option). Use after a phase
is green and before you commit, or for a second opinion on a risky diff. This is the *cross-vendor*
complement to `/caddis:code-review`, not a replacement.

## Step 0 — check the key BEFORE reading the diff

```bash
python "$TOOL" --check-config      # resolve $TOOL first, see "Run it" below
```

Exit 0 means ready; it prints which providers have a key. **Exit 3 means nothing is configured —
STOP and ask the user now.** Do not proceed to the review, and do not silently skip it.

Ask with `AskUserQuestion`: which provider to set up (DeepSeek, GLM, or another OpenAI-compatible
endpoint), then write the key they give you to `~/.caddis/keys.env` as `DEEPSEEK_API_KEY=<key>` (or
the matching variable) and re-run the check. **The keys file lives outside every git repo, so it
cannot be committed by accident. Never put a key in the repo, in a command, or in your reply.**

**Why asking is the fix, and why the script does not do it.** This used to fail at the point of use
— mid-task, with a commit pending, which is the worst moment to go hunting for a credential. A
command that fails once at an inconvenient moment does not get retried, so the safety check is
quietly lost and nothing records that it was lost. But `oss_review.py` also runs headless, from CI
and from `claude -p` sessions, where a prompt on stdin does not ask a question — it hangs forever.
So the script answers *"is it configured?"* and **you** do the asking.

If a key exists for a different provider than the one requested, the error names it and gives you
the exact flag (`--provider glm`). Read the message before concluding anything is missing.

**Key precedence:** `REVIEW_API_KEY` > the provider's own env var (`DEEPSEEK_API_KEY` /
`GLM_API_KEY`) > `OSS_API_KEY` > the keys file (`~/.caddis/keys.env`, overridable via
`CADDIS_KEYS_FILE`). Details: the `coding/cross-review` skill and the **Providers & keys** guide.

## Run it
Resolve the tool path deterministically — check only these two exact locations, in order, and
**never search the filesystem for it** (see Rules below):
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
