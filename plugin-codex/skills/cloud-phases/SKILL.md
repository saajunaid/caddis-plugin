---
name: cloud-phases
description: Run plan phases in Claude Code cloud sessions — write one prompt per phase, push, hand out paste lines, then take the PRs back
---

# /caddis:cloud-phases — run plan phases in the cloud, then take them back

Use this when a plan has phases that can run in parallel and you want them to run in Claude Code
cloud sessions (claude.ai/code) instead of on this machine. This session stays the orchestrator:
it writes the work orders, and it reviews and merges the results. The cloud sessions only implement.

**How the code moves.** Nothing syncs between the cloud and this disk. GitHub is the only meeting
point. This session pushes the feature branch and the prompts. Each cloud session clones from
GitHub, works on its own branch, and opens a pull request (PR) into the feature branch. This session
merges each PR on GitHub, then pulls. So a cloud session sees only what is committed and pushed.

Arguments: `$ARGUMENTS`

Two modes:
- `/caddis:cloud-phases [plan] [phases]` — **dispatch**: Steps 1–6.
- `/caddis:cloud-phases intake` — **intake**: Step 7, after the owner has run the sessions.

With no plan argument, use the active plan (`python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.126/scripts/caddis_todo.py" active-plan`,
or the one `status: current` plan in `.caddis/plans/`). If there is none, or more than one, ask.

## Step 1 — check the preconditions (stop on any failure)

```
git remote get-url origin
git branch --show-current
git status --short
gh auth status
```

- `origin` must be a GitHub repository. Cloud sessions clone from GitHub; a repo with no GitHub
  remote cannot use this command. Say so and stop.
- The current branch must be the plan's feature branch, never the default branch. The cloud PRs
  target this branch, and it goes to `main` later through the normal `/caddis:ship-pr`.
- Tracked changes must be committed. A cloud session cannot see uncommitted work.
- `gh` must be signed in as an account that can push to the repository and open PRs.

## Step 2 — pick the phases for the cloud

Take the plan's not-done Tracker rows (or the phase numbers given). Keep a phase **local** when
any of these is true, and say why:
- It needs a tool the cloud does not have: Codex, agy, GLM, DeepSeek, a local database, a VPN
  host, or real data.
- It needs a gitignored file (for example `.caddis/relay/`, `.env`, keys). The cloud clone does
  not have them.
- It needs the owner's go-ahead when it runs (model evals, production), or it is orchestrator
  work (verification, measurement, release judgement).
- It depends on a phase that has not merged yet.

Then check the **Touches** lists. Two cloud phases may run at the same time only if they share no
file. When two phases touch the same file — a shared registry or manifest is the usual case — run
them one after the other, or keep that shared edit local and make it yourself after both merge.

## Step 3 — check the facts each phase depends on (rule: think before you send)

For each cloud phase, at the feature branch's current head:
- Confirm every path, function and line number the phase names. Record what you found, with
  line numbers and the short SHA.
- Write the edge cases the implementer must handle.
- Find the exact CI commands for the files it touches (read `.github/workflows/`).

A cloud session cannot ask you anything mid-run. Anything you do not write down, it will guess.

## Step 4 — write one prompt per phase

Write `.caddis/prompts/<release-or-feature>-cloud-phase-<NN>.md`. Every prompt is self-contained,
with these sections in this order:

```markdown
---
type: prompt
title: <feature> Phase <N> (cloud) — <phase goal in a few words>
created: <YYYY-MM-DD>
---

# <feature> Phase <N> — <phase title>

Suggested model: <Opus | Sonnet> (`/model <alias>`). <one line on why>

## Where you are
- Repository `<owner>/<repo>`. Start from branch `<feature branch>` at its current head.
  Create branch `<prefix>/phase-<NN>` from it. Work only on that branch.
- You run in a Claude cloud session. You have no Codex, agy, GLM or DeepSeek, and you cannot see
  gitignored files. This file and the tracked repo hold everything you need.
- Read `AGENTS.md` at the repo root first. For background only, read the "Constraints" section of
  `<plan path>`. Where it differs, this file wins.

## The phase (copied from the plan)
<Goal, Touches, Design, TDD, Exit gate, Commit message — copied, not summarised>

## Facts already checked (<date>, at <short SHA>)
- <path:line — what is there>

## Edge cases to handle
- <edge case>

## Checks to run before you open the PR (the same as CI)
- `<exact command>`
Report the literal result of each.

## Finish
1. Commit on `<prefix>/phase-<NN>` with the commit message above. Stage named files only.
2. Push the branch: `git push -u origin <prefix>/phase-<NN>`.
3. Open a PR into `<feature branch>` (never into the default branch). Put the check results in
   the PR description.
4. Do not merge. Do not touch other branches. Stop and report the PR link.
```

The repository may be public. A prompt is committed and pushed, so it must hold no secrets, no
internal host names, no machine paths and no credentials.

## Step 5 — commit and push, then prove GitHub has it

```
git add <each prompt file by name>
git commit -m "docs(prompts): cloud prompts for <feature> phases <N, M>"
git push -u origin <feature branch>
git rev-parse HEAD
git ls-remote origin refs/heads/<feature branch>
```

The two SHAs must match. If they do not, the cloud sessions will start from old code — stop and fix
the push first.

## Step 6 — hand the owner the paste table, then stop

Print one row per cloud phase:

| Phase | Model | Branch to pick | Paste this |
|---|---|---|---|
| <N> | <Sonnet> | `<feature branch>` | `Read .caddis/prompts/<file> and follow it exactly.` |

Tell the owner, in these words: open https://claude.ai/code, choose repository `<owner>/<repo>`,
choose branch `<feature branch>`, paste the line, and start. Phases in the table share no file, so
they can run at the same time. Then **stop**. Record "dispatched to cloud, PR pending" in each
phase's Tracker row. When the PRs exist, the owner runs `/caddis:cloud-phases intake`.

Do not use the Agent tool with `isolation: "remote"` for this. It has run locally instead of in the
cloud, which uses no cloud credit and leaves a worktree behind.

## Step 7 — intake: review and merge each PR, then pull

```
gh pr list --base <feature branch> --state open --json number,title,headRefName,headRefOid
```

For each PR from a `<prefix>/phase-<NN>` branch, one at a time:
1. Read the whole diff (`gh pr diff <N>`). Check it against the phase's Design and Touches. A file
   outside Touches is a finding.
2. Wait for CI: `gh pr checks <N> --watch` (or the ci-watch lane, if this caddis has it).
3. Review under the three rules: one review, stop at the first CLEAN; after two blocking reviews,
   ask the owner. A fix goes back to the same cloud session or is made locally on the PR branch.
4. Just before merging, re-read `gh pr view <N> --json headRefOid,mergeStateStatus`. Merge only if
   the head SHA is the one you reviewed and CI passed on it:
   `gh pr merge <N> --squash --delete-branch`.
5. Pull: `git pull --ff-only origin <feature branch>`.
6. Run the phase's exit gate locally, and after the last PR, the full test suite.
7. Update the phase's Tracker row: status, PR number, merge commit, review result. Set the prompt's
   frontmatter `status: done` so `/caddis:handoff` tidies it.

Merge in dependency order. If a later PR conflicts after an earlier merge, ask its session to
rebase on the feature branch, or resolve it locally on that PR branch — never on the feature branch
directly.

## Running the orchestrator in the cloud too
The orchestrator can itself be a cloud session. Nothing above needs this machine, because every
step goes through GitHub. What changes:
- The owner still opens each worker session by hand at claude.ai/code. An orchestrator cannot
  start cloud sessions itself.
- The cloud orchestrator has no Codex, agy, GLM or DeepSeek. Phases on those lanes, and
  second-vendor reviews, stay for a local session.
- It cannot see gitignored files, so there is no relay: `/caddis:handoff` state does not carry to
  the next session. Put the resume state in the plan's Tracker and push it.
- Its container ends with the session. Push before you stop, every time.

## Rules
- This command never merges into the default branch. The feature branch goes there later through
  `/caddis:ship-pr`.
- One phase, one prompt, one branch, one PR.
- The orchestrator reads every diff. A green CI run proves only that the tests pass, not that the
  phase did what its Design says.
