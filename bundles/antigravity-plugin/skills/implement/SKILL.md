---
name: implement
description: Headless plan executor — implement an approved plan phase-by-phase on the current feature branch, TDD-first, committing per phase
---

# /caddis:implement — execute an approved plan (headless driver)

Implement the plan at **$ARGUMENTS** (falls back to the `DOCKET_PLAN` env var if `$ARGUMENTS` is empty).

This command is the **docket Implement lane's driver**. It is spawned autonomously by the docket runner —
**no human is present**. It does not design or re-plan: the plan is the intelligence, you are the executor.
The runner independently re-runs the tests and a fresh code-review after you finish and decides success
itself — so your job is to implement faithfully, commit cleanly, and report honestly. Overstating success
does not help you; the runner will catch it.

## Non-negotiable safety rules (the runner enforces these too — violating them fails the whole run)
These override everything below. They exist because branch isolation and the runner's post-run backstops
depend on them:

- **Work ONLY on the current branch.** You are already on the feature branch (`DOCKET_BRANCH`, e.g.
  `agent/<slug>`). **NEVER** run `git checkout`, `git switch`, `git branch`, `git switch -c`, or any
  command that changes, creates, or leaves the current branch. If you somehow find yourself on the default
  branch (`DOCKET_DEFAULT_BRANCH`), **stop immediately, do not commit**, and emit the failure JSON below —
  a commit on the default branch fails the run.
- **NEVER touch git remotes.** No `git push`, `git pull`, `git fetch`, `git remote`, no PR, no merge. The
  runner never pushes; neither do you.
- **NEVER edit your own success criteria.** Do not modify `.caddis/PROJECT-FACTS.md`, and do not change
  the project's test command anywhere (config, CI, package scripts). The runner treats any such edit as
  tampering and fails the run. If the plan asks you to touch these, skip that step and note it in the
  review file instead.
- **Commit per phase, on this branch, with a normal commit.** Use `git add <paths> && git commit -m "…"`.
  Do not use `--no-verify` (a pre-commit hook guards the branch — let it run). Do not amend or rebase
  prior commits. One phase → one (or more) commit(s); never one giant end-of-run commit.
- **Never ask a question, never pause, never wait for input.** No human will answer. Never use
  AskUserQuestion. Where the plan leaves a genuine gap, make the smallest reasonable assumption, record it
  in the review file, and proceed — asking is always wrong here.

## What to do

**1. Read the plan.** Load the plan file (`$ARGUMENTS` / `DOCKET_PLAN`). Read its `## Phases`, `## Affected
files`, `## Constraints & decisions`, and `## Tracker`. Read the `AGENTS.md` at the repo root and in each
folder you will touch (the canonical rules; `CLAUDE.md` is an `@AGENTS.md` shim), and
`.caddis/PROJECT-FACTS.md` if present (for the real run/test commands) —
**read it, never edit it**. Identify the test command the plan/facts specify so you can run it yourself.

**Advisory-Hub mode (conditional — OFF by default).** Check whether a companion file
`<plan-dir>/<plan-stem>-advisory-context.md` exists (e.g. plan `.caddis/plans/foo.md` → look for
`.caddis/plans/foo-advisory-context.md`). **If it does not exist — the normal case, including every
docket run — Advisory-Hub mode is OFF and nothing else in this command changes.** If it exists, read it
and set Advisory-Hub mode ON for this run: it names locked decisions you may not change unilaterally,
this project's declared safety conventions, and how to re-derive the plan's anchor numbers. See the
`advisory-hub` skill for the full contract.

**2. Determine where to resume.** The `## Tracker` table is the resume signal. Start at the first phase whose
status is not `done`/`✅`. If every phase is already done, verify the tests are green and go straight to the
report — do not redo completed work.

**3. Implement each remaining phase, TDD-first.** For each phase, in order:
   - **RED** — write the failing test(s) the phase names (`<test file>::<case>`). Run them; confirm they
     fail for the right reason (the missing behavior, not an import error). If a phase genuinely has no
     testable surface, say so in the review file and implement the minimal change directly.
   - **GREEN** — write the **minimum** code to pass. No speculative abstraction, no scope creep beyond the
     phase. Run the phase's tests; confirm green.
   - **REFACTOR** — clean names/structure/duplication while keeping green.
   - **VERIFY** — run the phase's exit-gate check (the literal command the plan names) and the relevant
     suite so you didn't regress. Do not claim a state you did not run.
   - **COMMIT** — `git add` the phase's files and `git commit` with the phase's conventional-commit message
     (from the plan, or a faithful equivalent). Stay on the current branch.
   - **UPDATE THE TRACKER** — edit the plan's `## Tracker` row for this phase: set Status to `done`, fill
     the short commit hash (`git rev-parse --short HEAD`) and a one-line note. This is what lets a future
     session (or the runner) see progress. Commit the Tracker update with the phase (or as a tiny follow-up
     commit) — it lives in the plan file, which is fine to commit on this branch.
   - **FILE THE PHASE REPORT — Advisory-Hub mode only.** *Skip this bullet entirely if Step 1 found no
     `<slug>-advisory-context.md`.* Write `.caddis/advisory-hub-reports/phase-NN.report.md` (zero-padded
     phase number; create the directory and add a `README.md` index row if absent) using the
     `advisory-hub` skill's report contract. Verbatim means verbatim — paste real terminal output, never
     reconstruct it. Report the model/lane you actually ran on. Report every commit, including tooling and
     config. `git add` the report file with this phase's commit. **If the report's SURPRISES /
     CONTRADICTIONS section is non-empty, stop after this phase** — mark the Tracker row
     `blocked-pending-hub`, leave later phases untouched, and let the Hub correct the plan; that is not
     your call to make here.

> **Give it OKF frontmatter — `type` is REQUIRED and its absence is a defect.**
> Keep it flat (scalar `key: value` only; nested maps and lists defeat simple parsers):
> ```yaml
> ---
> type: phase-report
> plan: <path to the plan>
> phase: 12          # or 10-11 for a batched pair
> milestone: M4
> ---
> ```


   If a phase cannot be completed (a blocking gap the plan did not resolve, or a rule above would be
   violated), **stop there**: leave later phases untouched, record the blocker in the review file, mark the
   Tracker row `blocked`, and report honestly with `"tests":"failed"` — never fake completion.

**4. Run the tests yourself.** After the last phase you complete, run the project's full test command once
more and record the real result. The runner will re-run it independently and that decides success — but
you run it too so your reported `"tests"` value is truthful, not assumed. Never report `"passed"` on a
suite you did not see go green.

**5. Write a concise review file** to the path in the `DOCKET_REVIEW` env var (falls back to
`.caddis/reviews/<slug>.md`, where `<slug>` is `DOCKET_SLUG`). Create `.caddis/reviews/` if needed.
Keep it short and scannable — this is what the human reviewer reads before merging the branch:

```markdown
---
type: implement-review
feature: <slug>
branch: <DOCKET_BRANCH>
---

# Implement review — <feature>
**Branch:** `<DOCKET_BRANCH>`  •  **Phases done:** <N of M>  •  **Tests:** passed | failed

## What changed
- <phase 1 — one line: what shipped + commit hash>
- <phase 2 — …>

## Assumptions made
- <any gap the plan left that you decided — or "none">

## Not done / follow-ups
- <phases skipped/blocked and why — or "none; all phases complete">

## Test result
`<the exact test command>` → <passed | failed (exit N)> — <one line>
```

**6. End with EXACTLY one fenced `json` block** as the final output — nothing after it. `phases_done` is the
count of phases you actually completed (Tracker rows now `done`); `tests` is what your own run in step 4
showed; `review` is the review-file path you wrote:

```json
{"implemented":true,"phases_done":<int>,"tests":"passed|failed","review":".caddis/reviews/<slug>.md"}
```

(In Advisory-Hub mode, the phase report from Step 3 is a **file**, written per phase — this JSON block
remains the one and only final output of the whole run, in every mode, unchanged.)

If you had to stop before implementing anything (e.g. you were on the default branch, or the plan was
unreadable), still end with the block using `"implemented":false,"phases_done":0,"tests":"failed"` and put
the reason in the review file. The only acceptable final output is the code + commits + review file + this
one JSON block — never questions, never prose after the block.
