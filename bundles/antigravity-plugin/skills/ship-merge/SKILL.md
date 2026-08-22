---
name: ship-merge
description: Merge an already-green, already-reviewed PR behind an explicit deploy-confirm, monitor the deploy, validate prod, then clean up the branch — only on green.
---

# /ship-merge — the reviewed lane, half 2: green PR → deployed → cleaned up

The deliberate second door. `/ship-pr` produced a reviewable artifact and stopped; this command
takes an **already-green, already-reviewed** PR through the one irreversible step — on these repos
**merge == deploy** — then watches the deploy, validates prod, and cleans up the branch **only
after** the deploy is confirmed green.

This command **never creates a PR** — that is `/ship-pr`'s job. A single create-and-merge shot
would recreate exactly what PRs exist to prevent: the ceremony of review with none of the pause.

Argument: **$ARGUMENTS** (PR number/URL; if empty, infer the current branch's open PR). An optional
strategy word (`squash` | `merge` | `rebase`) overrides the detected merge strategy.

## Step 0 — Detect the lane, resolve the PR

- **Gitea lane** — `.gitea/workflows/` exists: PR state + merge via the Gitea API; deploy
  monitoring via the `deploy-local` skill.
- **GitHub lane** — `.github/workflows/` (no `.gitea/`): `gh pr view/merge`, `gh run watch`
  (the `gh-cli` skill).
- **Local-only lane** — no forge, no PR concept: **refuse** and point at `/ship`. Stop.

Resolve the target PR from `$ARGUMENTS`, else the current branch's open PR. No open PR → report
that and point at `/ship-pr`. Read `AGENTS.md` + the workflow file(s) for the repo's real deploy
job names and default branch — never assume.

## Step 1 — Refuse unless green + mergeable + reviewed

All of, per the repo's own rules:
- **Required checks green** (including the scope-guard check when the repo has one).
- **Mergeable** — no merge **conflicts** against the default branch.
- **Reviewed** — if the repo configures **required** reviewers/approvals, they must be satisfied.
  On a solo repo with none configured, Step 2's explicit human confirm IS the review gate.

If anything fails: report **exactly what is missing** (which check is red, which review is absent,
whether it conflicts) and **stop**. Never merge around a red or a rule.

## Step 2 — Explicit human-confirm gate (the deploy warning)

State plainly, then wait for confirmation:

> Merging PR #N will **DEPLOY** `<head-sha>` to prod via the pipeline. Confirm to proceed.

This is the one irreversible, outward-facing step. Approval here **does not carry over** to any
future run — ask every time, even for the same PR five minutes later.

## Step 3 — Merge

Use the repo's configured **merge strategy** — read it from repo settings (Gitea repo settings API /
`gh repo view --json squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed`) and `AGENTS.md`;
an explicit argument wins. Options: **squash**, **merge-commit**, rebase-merge. **Don't assume** —
if detection is inconclusive, say so and use merge-commit (never silently squash someone's history).
Record the merge SHA.

## Step 4 — Monitor the deploy

The merge lands on the default branch and triggers the pipeline. Watch it via the lane's skill:
- Gitea: `lint_and_test` → `frontend_checks` (if present) → **`deploy_prod`** → `release_metadata`
  → `notify` (`deploy-local` skill §monitoring; classify + minimum-fix on failure).
- GitHub: `gh run watch <run-id> --exit-status` on the default branch; if the workflow has a deploy
  job, watch it through; if CI-only, note that no deploy occurs.

## Step 5 — Post-deploy validation

- Prod/target checkout **SHA matches the merge commit**.
- Services (NSSM or equivalent) **Running**; **health** endpoint green.
- Version endpoint shows the expected SHA/CalVer, when exposed.
(Same checklist as `/ship` Step 5 — reuse it.) If validation is red, report immediately; do not
attempt a silent re-deploy — and **skip cleanup** (Step 6).

## Step 6 — Branch cleanup — only after a confirmed-green deploy

**Only after** Step 5 is green:
- Delete the **remote** feature branch; delete the **local** feature branch.
- Switch to the default branch and fast-forward it to the merge commit.
- Drop the `backup/<branch>-preship` ref `/ship-pr` created.

If deploy validation failed: **skip cleanup** entirely and say so — never delete a branch whose
work may need re-work.

## Step 7 — Report

```
PR:            #<n> <title> — merged (<strategy>) as <merge-sha>
Deploy:        <job ✓ / ✗ per job>
Prod SHA:      matches merge ✓ | MISMATCH
Health:        green ✓ | red — reported, cleanup skipped
Cleanup:       remote branch ✗ deleted / local ✗ deleted / backup ref dropped | SKIPPED (<why>)
```

## Rules
- Never merge without: green required checks **and** the explicit human deploy-confirm.
- Never delete a branch before its deploy is validated green.
- Never `git add -A` without reviewing `git status`; never edit a workflow file to make a gate pass.
- Local-only lane: no PR, no merge — refuse and point at `/ship`.

## Skill reference
Gitea deploy monitoring, prod validation, failure triage: the `deploy-local` skill (ships in the optional `caddis-extras` plugin — enable it with `claude plugin enable caddis-extras`).
GitHub `gh pr merge` / `gh run` usage: the `gh-cli` skill.
