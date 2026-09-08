---
description: Review someone else's OPEN pull request end to end — what changed, what CI says, what is risky — then approve or request changes. Never approves on its own.
argument-hint: "<pr-number> [owner/repo]"
---

# /caddis:review — review an open PR, then decide

Review pull request **$ARGUMENTS** and walk the operator to an approve-or-not decision.

> **This is the only caddis review surface aimed at a PULL REQUEST.** The others review a local
> diff: `/caddis:gate-review` (adversarial, same vendor), `/caddis:cross-review` (a different
> vendor's model). `/caddis:ship-pr` and `/caddis:ship-merge` create and merge PRs. This one is for
> the case none of those covers — somebody else has opened a PR and you have to decide about it.
>
> Do not reimplement the review itself. Gather the context, then hand the diff to
> `/caddis:gate-review` (or Claude Code's native `/code-review`, which is better where it exists).

## Absolute rule

**Never approve, request changes, merge, or close on the operator's behalf.** Present the evidence
and the exact command; the human runs it. An approval is the one human judgement in the pipeline —
a review tool that also approves has removed the thing it was built to protect.

## 1. Resolve the PR

`$ARGUMENTS` is a PR number, optionally followed by `owner/repo`. With no repo, use the current
directory's `origin`. If the number is missing, list the open PRs and stop.

```bash
gh pr view <n> --repo <owner/repo> --json number,title,author,state,isDraft,mergeStateStatus,reviewDecision,baseRefName,headRefName,additions,deletions,changedFiles,url
```

**Stop and say so, before reviewing anything**, if:
- the PR is **merged or closed** — there is nothing to decide;
- it is a **draft** — say so and ask whether to continue;
- **the operator is the author.** GitHub does not allow approving your own PR. Say it plainly, and
  say the alternatives: have someone else approve it, or merge with an admin bypass
  (`gh pr merge <n> --squash --admin`). Do not silently produce a review they cannot submit.

## 2. Gather what the decision needs

Four things, and report them even when they are boring — "CI is green" is information:

```bash
gh pr checks <n> --repo <owner/repo>            # every check and its state
gh pr diff  <n> --repo <owner/repo>             # the change itself
gh pr view  <n> --repo <owner/repo> --comments  # review comments, and any bot review
```

If an automated review has already commented, **read it and say whether you agree**. Two reviews
that disagree is a finding; two that agree is worth stating once, not twice.

`mergeStateStatus` explains a blocked PR without guessing: `BLOCKED` (needs a review),
`BEHIND` (needs *Update branch*), `UNSTABLE` (a check failed), `DIRTY` (conflicts).

## 3. Review the diff

Hand it to `/caddis:gate-review` — or the native `/code-review` on Claude Code. Then, on top of its
verdict, check the things that have actually cost this fleet time, because a generic reviewer will
not know to look:

- **A gate that cannot fail.** A check whose failure path cannot execute — piped to `Out-Null`,
  wrapped in a `catch{}` a native non-zero exit can never trigger, or asserting something too broad
  to attribute. It manufactures confidence. Worse than no check.
- **A wall-clock assertion.** A timing threshold on a shared runner measures load, not the code.
  Assert ordering instead.
- **Staged directories.** `git add -A` / `git add .` sweeps in files nobody reviewed.
- **CI shell assumptions.** The runner may be Windows PowerShell 5.1, where a native command's
  stderr becomes a terminating error under `$ErrorActionPreference='Stop'`, and where `Should -Be`
  (Pester 4 syntax) fails on a Pester 3 runner.
- **Deploy-script changes.** If the pipeline runs the deploy script from a checkout it also updates,
  the change does not take effect on the deploy that delivers it. Budget two deploys.
- **Verification by proxy.** An HTTP 200 or a version string is not proof a page renders.
- **Credentials.** A token scoped to the wrong host; a permission raised to make a test pass; a
  secret in a URL where git will echo it into a log.
- **A doc the change makes untrue.** Comments and runbooks that were accurate until this diff.

## 4. Report, then hand over

Lead with the verdict. Keep it short enough to read before deciding:

- **What this PR does** — one or two sentences, not a file list.
- **Blocking issues** — each with file, line, and why it matters. None is a valid answer, and say it.
- **Should-fix / nits** — grouped, brief.
- **CI** — green, red, or still running. Name the failing check.
- **Merge state** — and what would clear it.

Then print the exact commands, and stop:

```bash
# approve
gh pr review <n> --repo <owner/repo> --approve
gh pr merge  <n> --repo <owner/repo> --squash --delete-branch

# or ask for changes
gh pr review <n> --repo <owner/repo> --request-changes --body "..."
```

**If you found a blocking issue, say so in the verdict line** rather than burying it under the
summary. The operator should be able to read the first line and know whether to keep reading.
