---
description: Cross-vendor code review of the current diff — a second-vendor model (agy Argon by default; DeepSeek, GLM or any OpenAI-compatible endpoint) reviews your changes to catch bugs a same-vendor reviewer misses
argument-hint: [git range, e.g. origin/main..HEAD]
stage: review
---

# /caddis:cross-review — a second-vendor set of eyes on your diff

Run a cross-vendor review of the current changes with a DIFFERENT model family than the one that wrote them
(default **agy Argon** since 2026-10-21 — it needs no key; DeepSeek and GLM are fallbacks). Use after a phase
is green and before you commit, or for a second opinion on a risky diff. This is the *cross-vendor*
complement to `/caddis:code-review`, not a replacement.

## Step 0 — check the key BEFORE reading the diff

```bash
python "$TOOL" --check-config      # resolve $TOOL first, see "Run it" below
```

Exit 0 means ready; it prints which providers are available (agy-argon needs no key, only agy on PATH and caddis_spend.py). **Exit 3 means nothing is configured —
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
python "$TOOL" $ARGUMENTS                                # pass the user's flags THROUGH, raw
python "$TOOL"                                           # no arguments: agy Argon eyes on the working tree
```

**`$ARGUMENTS` goes through raw, and must not be re-prefixed.** Callers are told to type the flag
themselves — `feature-plan.md` emits `/caddis:cross-review --range main..HEAD` into every plan it
writes. This line used to prefix the flag itself, which turned that into a doubled
`--range --range main..HEAD` and made every plan-emitted call fail. Whatever the user typed is already a complete flag list:

```
/caddis:cross-review                          -> the working tree, agy Argon
/caddis:cross-review --range main..HEAD       -> that range
/caddis:cross-review --provider glm           -> GLM eyes
```
Optional: `--base-url <url>`, `--model <id>` (env always overrides the preset).

**A large diff is batched, not refused.** Over `REVIEW_MAX_DIFF_CHARS` (default 60,000) the tool splits
on whole-file boundaries and reviews each batch, and the verdict is CLEAN only if every batch is. When agy
Argon is anywhere in the provider chain, each batch is also kept small enough that its **whole prompt** fits
the agy command line (28,000 chars once quoted, so under about 27,000 diff chars, fewer when the diff has many `"`). A **single file** too
big for agy gets its own batch: agy skips it and the next provider reviews it. With no other provider (no
DeepSeek or GLM key), that file gives exit **3**. Exit **4** means a **single file** over the 60,000 ceiling,
or more batches than the cap. When you see either, review that one file separately (or add a key for an
HTTP provider), not a narrower `--range`; don't raise `--max-diff-chars` blind.

**The verdict is the last line.** Only the last non-empty line of the reply counts, and it must be
exactly `REVIEW: CLEAN` or `REVIEW: BLOCKING`. A reply that quotes the marker earlier and ends some other
way has no verdict (exit 4). An explicit `--range` with no changes is exit **3** (a review of nothing is not
CLEAN); the working tree with no changes is still CLEAN. When the secret filter drops some files, the
output ends with `REVIEW-SCOPE: PARTIAL (<n> file(s) excluded by the secret filter: <names>)` and then the
overall `REVIEW:` line. The exit code does not change, but the excluded files were **not reviewed**: say so,
and never report the result as a full CLEAN.

**Do not alternate providers on a schedule.** The order is the owner policy (21 Oct 2026): **agy Argon,
then DeepSeek, then GLM** (`REVIEW_ORDER` in `oss_review.py`). A named `--provider` goes first; on a provider failure
(HTTP 429, any 5xx, a timeout, a connection error, an empty reply) the tool moves to the next one in
that order and prints which provider gave the verdict. A provider with no key is skipped. agy runs
through `caddis_spend.py run` (usage log, time limit, depth guard; no spend cap); if it refuses (exit 75), agy is skipped. On a 429 the tool
waits for `Retry-After` once (at most 60 s); it never splits the diff because of a 429 or an empty
reply. A custom endpoint (`--base-url`/`--model`) never falls back. Name a provider only when you have
a reason.

**Change the default.** The first provider comes from `--provider`, then the process env `REVIEW_PROVIDER`, then
`REVIEW_PROVIDER` in `~/.caddis/keys.env`, then agy Argon. The others follow in `REVIEW_ORDER`. To make DeepSeek the default again, add `REVIEW_PROVIDER=deepseek` to ~/.caddis/keys.env.

## Interpret the exit code
- **0 — REVIEW: CLEAN** → no blocking issues. Proceed.
- **1 — REVIEW: BLOCKING** → read the printed findings, then **FIX each blocking item** (or explicitly
  justify why one is a false positive). Fix it, then re-review only the fix diff. After 3 rounds, ask the owner (rule 3).
- **4 — error** → no verdict parsed, or a git/endpoint failure. Read stderr; do NOT treat as clean.
- **3 — could not run** → no key (see Prerequisite), the secret filter refused, an explicit `--range` has
  no changes, or every provider
  failed (429, 5xx, timeout, empty reply). Read stderr. A provider failure is not a verdict: re-run later.

## Three rules: one attempt, one review
1. **Think before you send.** Before a task goes to any coder, write its edge cases and check the facts it depends on (one query or one file read).
2. **Run it before review.** The coder runs only the tests of the files it touched, in the foreground, each command under 10 minutes (split into parts if needed). Name the exact commands in the task. Never start the full suite in the background and never wait on a monitor for it: CI runs the full suite on every PR. Then run the change once on real data.
3. **Review by tier.** Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_gate.py" review-tier --range <base>...HEAD` (add `--plan <plan> --phase <N>` inside a plan; no `TIER:` line means tier 2).
   Tier 0: gates only. Tier 1-small: your self-check only. Tier 1: one review by another vendor; stop at
   the first CLEAN. Tier 2: one review by another vendor (two only when the owner asks). Fix blocking findings only;
   park the rest. Re-review only the fix diff, and only when the fix changed logic. After 3 rounds, ask the owner.

A diff over the batch ceiling is split into batches. Each batch prompt lists every file in the
change, so a batch does not report the others as missing.

## Rules
- Read-only second opinion — the tool never edits, commits, or pushes. YOU apply fixes in the main thread.
- Treat exit **3 or 4** as blocking-unknown, never as approval (the tool is fail-closed by
  design). 3 = could not run, 4 = ran and produced nothing usable. **Exit 2 is not
  emitted by this tool** — across caddis 2 always means an advisory note, and a review
  has no advisory verdict.
- A different vendor means a different style; weigh its findings on merit, don't cargo-cult them.
- Save review notes in `.caddis/reviews/`, never in `.caddis/parking-lot/`: that folder holds only items to do later, one item per file, `type: parking-lot` (`/caddis:park`).
- **Never use `find`, `Get-ChildItem -Recurse`, or any other filesystem-wide search to locate
  `oss_review.py`.** Check only the two paths above. On Git Bash under Windows, `find /` (or any
  search rooted at `/`) walks every mounted drive, not just the repo — it can hang or take minutes.
  If neither path exists, stop and report it; don't go hunting for the file.
