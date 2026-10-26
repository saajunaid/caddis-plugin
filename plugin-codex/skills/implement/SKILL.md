---
name: implement
description: Headless plan executor — implement an approved plan phase-by-phase on the current feature branch, TDD-first, committing per phase
---

# /caddis:implement — execute an approved plan (headless driver)

Implement the plan at **$ARGUMENTS**.

**Which plan.** An explicit plan always wins: the plan path comes only from `$ARGUMENTS`. Only when
it is empty, find the active plan:

```bash
python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.167/scripts/caddis_todo.py" active-plan
```

- **Exit 0** → stdout is the plan path. Say which plan you picked ("No plan given; using
  `<path>`.") and implement it.
- **Exit 3** → no single active plan. Do not guess and do not ask. Stop before any change, list the
  candidates it printed on stderr (or "none") in the review file, and end with the
  `"implemented":false` JSON block from step 6.

This command is the **headless Implement driver**. It is spawned autonomously by a runner or a lane
launcher (they set `CADDIS_HEADLESS`) — **no human is present**. It does not design or re-plan: the plan
is the intelligence, you are the executor.
The runner independently re-runs the tests and a fresh code-review after you finish and decides success
itself — so your job is to implement faithfully, commit cleanly, and report honestly. Overstating success
does not help you; the runner will catch it.

## Non-negotiable safety rules (the runner enforces these too — violating them fails the whole run)
These override everything below. They exist because branch isolation and the runner's post-run backstops
depend on them:

- **Work ONLY on the current branch.** You are already on the feature branch (the current branch,
  `git branch --show-current`; that read is the only `git branch` form allowed).
  **NEVER** run `git checkout`, `git switch`, `git branch <name>`, `git switch -c`, or any command that changes,
  creates, or leaves the current branch. Read the default branch with
  `git symbolic-ref --short refs/remotes/origin/HEAD`, which prints `origin/<default>`: remove the
  `origin/` prefix before you compare. If that command fails (origin/HEAD is not set), the default
  branch is `main` or `master`. **Stop immediately, do not commit**, and emit the failure JSON below when
  `git branch --show-current` prints nothing (a detached HEAD) or prints the default branch — a commit
  there is lost or fails the run.
- **NEVER touch git remotes.** No `git push`, `git pull`, `git fetch`, `git remote`, no PR, no merge. The
  runner never pushes; neither do you.
- **NEVER edit your own success criteria.** Do not modify `.caddis/PROJECT-FACTS.md`, and do not change
  the project's test command anywhere (config, CI, package scripts). The runner treats any such edit as
  tampering and fails the run. If the plan asks you to touch these, skip that step and note it in the
  review file instead.
- **Commit per phase, on this branch, with a normal commit.** Use `git add <paths>`, then check `git diff --cached --name-only` lists only those paths (refuse on any
  other staged path: a peer staged it; note it in the review file), then `git commit -m "…" -- <paths>`.
  Never `git add -A`, `.`, `-u` or a folder, and never `git commit -a` (the guard denies them).
  Do not use `--no-verify` (a pre-commit hook guards the branch — let it run). Do not amend or rebase
  prior commits. One phase → one (or more) commit(s); never one giant end-of-run commit.
- **Never ask a question, never pause, never wait for input.** No human will answer. Never use
  AskUserQuestion. Where the plan leaves a genuine gap, make the smallest reasonable assumption, record it
  in the review file, and proceed — asking is always wrong here.

## Keep the session small and quiet

Measured 24-25 Oct 2026: about 60% of usage was cache re-reads in long Opus main sessions (400-600k tokens),
and 95-154 turns per session were started by background events. Each turn re-reads the whole conversation.
- **Small context.** Ask each subagent for a reply under about 200 words. Full reports go to files; read a
  file only for the part you need. Never paste or tail a large output.
- **Handoff at phase end.** At each phase end, write the handoff yourself (see "At every halt" below). Continue
  in the same session only while the conversation is under about 200k tokens. Above that, ask for `/clear`.
- **Model.** The orchestrator runs on Sonnet. Opus stays for plans, designs and critical-code subagents.
- **One phase review.** Run `/caddis:cross-review --range <base>..HEAD` (one other vendor; agy Argon by default).
  Never use a Claude reviewer subagent. Exception: every other-vendor provider failed. Then say so in the review file.
- **Mechanical tasks** (literal tests, moves, deletes, renames) go to agy through
  `python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.167/scripts/caddis_spend.py" run --caller lane-pN -- agy ...`.
- **Fewer wake-ups.** Run one `ci-watch` per PR head. When it times out on a queued run, watch that run once
  with `ci-watch --run <id>`; do not start a new PR watch. Write no "still waiting" turns.

## Three rules: one attempt, one review
1. **Think before you send.** Before a task goes to any coder, write its edge cases and check the facts it depends on (one query or one file read).
2. **Run it before review.** The coder runs only the tests of the files it touched, in the foreground, each command under 10 minutes (split into parts if needed). Name the exact commands in the task. Never start the full suite in the background and never wait on a monitor for it: CI runs the full suite on every PR. Then run the change once on real data.
3. **Review by tier.** Run `python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.167/scripts/caddis_gate.py" review-tier --range <base>...HEAD` (add `--plan <plan> --phase <N>` inside a plan; no `TIER:` line means tier 2).
   Tier 0: gates only. Tier 1-small: your self-check only. Tier 1: one review by another vendor; stop at
   the first CLEAN. Tier 2: one review by another vendor (two only when the owner asks). Fix blocking findings only;
   park the rest. Re-review only the fix diff, and only when the fix changed logic. After 3 rounds, ask the owner.

**Author self-check** (tier 1-small, and before any review). It is not a model review. Answer all five:
1. The CI gates named in the phase passed, with the literal output.
2. Every changed function has a test that fails without the change.
3. No TODO, placeholder or debug print is left.
4. Error paths return or raise. None is swallowed.
5. The diff touches only the phase's files.

This run is headless, so "ask the owner" (after 3 rounds) means: stop the phase, do not commit it, and record the
blocking findings of the 3 rounds in the review file.

## Programme triggers

Small work that does not meet a trigger skips its block.

**Trigger: Always.** Mutation proof: for each gate the phase adds, break the code under test once with a recorded mutation and see the gate fail. Write the mutation and the failing test line in the review file.

**Trigger: The phase computes or shows a number.** Value check: the computed figure must equal an independent source for a fixed past window, never today. Start from the `roadmap` skill's `assets/value-check.template.py`. Run it once with `--prove-it-can-fail` and see it exit 1.

**Trigger: The phase changes UI.** Render check: the changed page must render at 1440 and 400 px wide with 0 console errors, after the network is idle plus the settle time (default 3 s). Start from the `roadmap` skill's `assets/render-check.template.mjs`. Run it once with `--prove-it-can-fail`.

## What to do

**1. Read the plan.** Load the plan file (`$ARGUMENTS`, or the active plan found above). Read its
`## Phases`, `## Affected files`, `## Constraints & decisions`, and `## Tracker`. Read the `AGENTS.md`
at the repo root and in each folder you will touch (the canonical rules; `CLAUDE.md` is an `@AGENTS.md` shim), and
`.caddis/PROJECT-FACTS.md` if present (for the real run/test commands) —
**read it, never edit it**. Identify the test command the plan/facts specify so you can run it yourself.

**Run the machine gates first — they decide, not your reading of the prose below.**

```bash
python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.167/scripts/caddis_gate.py" lane-check    --plan <plan> --phase <N>
python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.167/scripts/caddis_gate.py" tracker-vs-git --plan <plan>
```

Use the shared scale in `caddis_exit.py`: 0 clean, 1 blocked, 2 advisory, 3 could not run,
4 error or bad usage, 5 round limit (`caddis_review.py --plan` only: stop, the owner decides). For `caddis_gate.py`, obey the exit code: **0** proceed · **1** STOP and report
why · **2** proceed but record the note it
printed · **3** wrong lane — the launch command is on stdout, spawn it · **4** the launch command is
malformed, do not run it.

**If the script is missing, proceed** — it degrades open by design, and an older install or a
plugin-only consumer must not be blocked by a gate it does not have. The prose below is the same
contract in words, and remains the fallback.

**Check the phase's `Lane:` before implementing anything.** The plan assigns every phase an
execution lane, and until now nothing read it: on one 14-phase plan, Phases 1 and 2 were both
assigned `glm-headless` and both ran on `claude`, silently, twice in a row — the plan advertised a
cheap lane for 4 of 14 phases that executed nothing, and every cost assumption resting on it was
quietly false. **The `Lane:` line is a routing directive, not a note.**

You cannot always prove your own lane, but you can detect a known mismatch — a Claude session
looking at `Lane: glm-headless`. Apply this **asymmetrically: act on a known mismatch, proceed when
unsure.** On a known mismatch:

- **Interactive session (no `CADDIS_HEADLESS` in the environment)
  → spawn the assigned lane.** Run the phase's literal launch command yourself — e.g.
  `claude-glm -p "/caddis:implement <plan> — Phase N only"` — wait for it, then verify it (below).
  On Windows `claude-glm` is `claude-glm.ps1` and resolves only on the **PowerShell** PATH; a
  Bash `command -v claude-glm` returns nothing and looks like "not installed", which it is not.
  If the spawn fails for any reason, implement the phase here and record the deviation (below) —
  a failed spawn must never silently become a skipped phase.
  > **First, check the launch command carries `-p` or `--print`. If it does not, REFUSE to run it**
  > — report the malformed command and implement here instead. The launchers set `CADDIS_HEADLESS`
  > *only* on `-p`/`--print`, and that variable is the entire loop guard. A launch command missing
  > it spawns a session that is not marked headless, which reads this same `Lane:` line and spawns
  > again — unbounded recursion. Without `-p` the command also opens an interactive session, so the
  > parent waits forever on a child that is sitting at a prompt.
- **Headless session (`CADDIS_HEADLESS` set) → never spawn. Implement here and record the deviation.**
  You may already *be* the spawned lane, and a session that spawns its own lane on every start is
  an infinite loop. The env marker above is the guard: if it is set, someone else placed you.

**After the spawn, verify it — do not assume.** Re-read the plan's Tracker row for that phase and
confirm the status and commit hash the child claims to have written. "Wait for it and report" checks
nothing: a mistyped plan path in the launch command silently implements a *different plan* while you
move on. If the row is unchanged, treat the phase as **not done** and say so.

**If your arguments carry a phase restriction — `— Phase N only` — implement exactly that phase and
stop**, then emit the final JSON block. Every launch command this system generates ends that way, and
nothing used to honour it: a child spawned for phase 2 of 14 would run phases 2 *through 14*, pulling
later `claude`-lane and security-sensitive phases onto the cheap model. That is the precise inverse of
the bug the lane routing exists to fix.

**Record the lane you actually ran on in the Tracker's `Lane` column** — the lane you ran, never the
lane the plan planned. A deviation then shows up as a diff between the phase block and the tracker
row, visible to any later reader without anyone having to catch it live.

**Multi-lane phases — `caddis_lanes.py`.** Use this procedure when the phase launch command is
`python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.167/scripts/caddis_lanes.py" run …`.

1. In an interactive session, run the phase's literal command. The script creates a temporary
   worktree. It runs the lane or its fallback chain inside a resource-capped job. It re-runs the
   gates with the repo interpreter. It runs the DeepSeek review. It then prints a `NEXT:` line.
2. Obey `NEXT:`:
   - `review` → read the packet JSON and inspect `git -C <worktree> diff`. Then decide ACCEPT or REDO.
   - `redo` → run `abandon`. Then run `run` with `--attempt 2 --findings <file with your findings>`.
   - `takeover` → run `abandon`. Then implement the phase yourself on the `claude` lane.
   - `claude-implement` → write the code in the printed worktree. Then run `check`.
   - `stop` → report the result and halt. `stop (host guard killed the lane…)` means
     `FAILED-RESOURCE`. The lane saturated the host. Never re-run it with more load. Fix the phase
     so it proves timing by design.
3. **ACCEPT** means run `caddis_lanes.py accept --plan <plan> --phase N --attempt K --message
   "<the phase's commit message>"`. It runs only on the programme branch, never on `main`. It
   refuses a `BLOCKING` review and a `MISSING` review (no verdict: provider down, 429, filter
   refusal). If you checked the finding and it is false, add
   `--override-review "<why the finding is false>"`. For a `MISSING` review, re-run the review
   first; add the override only if the owner accepts a phase with no vendor verdict. The reason
   must not be empty. The script records it in the packet.
4. Allow at most **2 attempts** per phase on a non-Claude lane. An out-of-budget switch is not an
   attempt. The owner can request TAKEOVER at any time.
5. A UI phase needs a `ui-design-reviewer` screenshot review before ACCEPT. This rule applies
   whichever lane wrote the phase.
6. A phase that Claude wrote needs a vendor review that is not MISSING. If `review.status` is
   `MISSING`, run `codex exec -m gpt-5.6-sol -s read-only -C <worktree> --skip-git-repo-check -`.
   Give the diff to the command on stdin.
6b. **Orchestrator artefacts live under `.caddis/orchestrator/`.** Store packets and locks in
    `lane-runs/`. Store evidence notes as markdown directly in `.caddis/orchestrator/`. Follow its
    `AGENTS.md`. Never write orchestration notes to `.caddis/kb/`.
7. **Never write a load or stress test into a lane prompt or findings file.** The script refuses
   this wording without `--allow-load`. Only the owner gives that flag.
7b. **Write test economy into every agent brief, not only the lane prompt.** The script already adds it
   to its lane prompts. A brief you write yourself (an Agent-tool subagent, a peer session) needs the same
   five lines: after each step run only the tests for the file or module you changed, in the foreground, each
   command under 10 minutes; never start the full suite, and never wait on a monitor for it (CI runs it on every PR);
   run no review loop inside the agent (you review); report progress
   every 20 minutes; never start a second heavy test run while one is still running. **Agents never run
   the full suite.** Measured 2026-10-02 on one shared box: a 2,063-test suite took 2.7 min
   alone and 6.7 min beside a second test-heavy agent, and one agent's brief (baseline, tests after each of 9
   module switches, full gates, in-agent review) cost 30-40 of its 59 minutes.
   On 18-19 Oct 2026 agents started the full suite (about 40 min) in the background and waited through
   monitors with their own timeouts. One missed the finish and sat "Waiting" for over 1 h. Four parallel
   suites also slowed the box. The orchestrator checks a stalled agent by process (pytest alive, CPU moving),
   not by its monitor.
8. Record these Tracker values:
   - `Model` = the packet's `model`.
   - `Lane` = the lanes tried, joined with ` -> ` and followed by the reason. For example,
     `glm -> codex-sol (glm out of budget)`.
   - `Cross-review` = `CLEAN`, `BLOCKING` or `missing`.
   - `Notes` = `attempt K, ACCEPT|TAKEOVER|FAILED-RESOURCE`.
9. The PR body lists every phase accepted with `review.status == MISSING`. It also lists every phase
   accepted while Codex astra stood in for Claude.
9b. **Finish.** After the last phase, run `caddis_lanes.py finish --plan <plan>`. It removes merged
    lane worktrees and branches. It reports unmerged or dirty ones. It pushes the feature branch.
    The plan is not done until it prints `LEFTOVERS: 0`. Then run `/caddis:ship-pr`. Merging and
    post-merge cleanup stay with `/caddis:ship-merge` after the owner's go.
10. **When a dispatched Claude run is out of budget**, read the output from the subagent or
    `claude -p`. If it holds Claude usage-limit text (for example `You've hit your session limit`
    or `You're out of extra usage`; the full list is `BUDGET_PATTERNS["claude"]` in
    `caddis_lanes.py`), run `python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.167/scripts/caddis_lanes.py" next-lane --role <the phase's role> --after <the model that ran>`.
    Re-dispatch the same phase prompt to the printed lane with its direct launch command:
    `codex exec ...` or `python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.167/scripts/caddis_spend.py" run --caller lane-pN -- agy ... -p "..."`,
    using the same form that `/feature-plan` writes. Never start agy without the `caddis_spend.py run`
    prefix: it is the global spend cap. Its own refusals have their own exit codes, never agy's:
    **75** = over the cap or could not lock (treat like out of budget: switch lane, not an attempt);
    **78** = the cap is not configured (stop and tell the owner to write `~/.caddis/spend-cap.toml`).
    Each refusal also prints a `caddis_spend:` line on stderr. Any other exit code is agy's own.
    An out-of-budget switch is not an attempt (item 4). Record the fallback in the Tracker
    `Lane` column, for example `sonnet -> agy (claude out of budget)`.
    If `next-lane` exits 3, stop and report that no lane is left. As a last resort, the owner can
    open `caddis-run codex -m gpt-6-astra` and ask it to follow this same subsection.

**2. Determine where to resume.** The `## Tracker` table is the resume signal. Start at the first phase whose
status is not `done`/`✅`. If every phase is already done, verify the tests are green and go straight to the
report — do not redo completed work.

**3. Implement each remaining phase, TDD-first.** For each phase, in order:
   - **LANE** — **re-check this phase's `Lane:` and apply Step 1's spawn/record rule to it.** Do this
     first, every phase, not just the one you resumed at. Step 1's check only ever saw the *resume*
     phase: on a plan whose phase 1 is `claude` and phase 2 is `glm-headless`, it finds no mismatch and
     this loop then carries you straight through phase 2 — so the lane silently executes nothing for
     every phase after the first, which is the original bug wearing a different hat. For a
     `caddis_lanes.py` launch command, follow "Multi-lane phases" above instead of spawning the command
     blind.
   - **EXECUTION** — read the phase's `Execution:` line. A missing line means `inline` (older plans
     have none). `inline`: run the steps below for the whole phase, as before. `Execution: per-task`:
     run the phase's tasks in order. Give each task a fresh implementer: a subagent on the phase's
     lane and model, with a brief that holds the task's `Files:`, `Interfaces:` and steps, the plan's
     Global Constraints and the test-economy lines (Multi-lane item 7b). If you cannot dispatch a
     subagent, implement the task yourself and note that in the review file. After each task, run
     the author self-check (no model review between tasks). Record each task (name, commit, self-check
     result) under `## Task progress` in the review file. Then run the phase's normal gates: VERIFY,
     the ONE `review-tier` review by one other vendor at the end of the phase, COMMIT and the Tracker.
     Re-check a fix only when it fixes a blocking finding and changes logic.
   - **RED** — write the failing test(s) the phase names (`<test file>::<case>`). Run them; confirm they
     fail for the right reason (the missing behavior, not an import error). If a phase genuinely has no
     testable surface, say so in the review file and implement the minimal change directly.
   - **GREEN** — write the **minimum** code to pass. No speculative abstraction, no scope creep beyond the
     phase. Run the phase's tests; confirm green.
   - **REFACTOR** — clean names/structure/duplication while keeping green.
   - **VERIFY** — run the phase's exit-gate check (the literal command the plan names) and the relevant
     suite so you didn't regress. Do not claim a state you did not run.
   - **COMMIT** — `git add` the phase's files by name, check `git diff --cached --name-only` shows only
     them, and `git commit -m "…" -- <files>` with the phase's conventional-commit message
     (from the plan, or a faithful equivalent). Stay on the current branch.
   - **UPDATE THE TRACKER** — edit the plan's `## Tracker` row for this phase: set Status to `done`, fill
     the short commit hash (`git rev-parse --short HEAD`), set the `Lane` column to the lane this phase
     ACTUALLY ran on (not the planned one — see Step 1), and add a one-line note. This is what lets a
     future session (or the runner) see progress. Commit the Tracker update with the phase (or as a tiny
     follow-up commit) — it lives in the plan file, which is fine to commit on this branch.

   If a phase cannot be completed (a blocking gap the plan did not resolve, or a rule above would be
   violated), **stop there**: leave later phases untouched, record the blocker in the review file, mark the
   Tracker row `blocked`, and report honestly with `"tests":"failed"` — never fake completion.

**3b. Halt only at a boundary.** Implement phase after phase, committing each. Stop for exactly four
reasons — a **milestone boundary**, a phase marked `Session: fresh`, **after** a `risk: high` phase,
or a **failed/blocked** phase. A lane change is not one of them: you spawn the lane yourself (Step 1).

The `risk: high` halt is deliberately *after*, not before. Execute and commit the phase normally; the
halt exists to stop the **next** phase building on it before a human has looked, so the blast radius
stays one reviewable, revertable commit. One exception: when your session prompt itself says the runner
reviews `risk: high` phases (the runner's `plan-resume-prompt.md` says so), do not halt; end the session
`STATUS: CONTINUE`. The runner then reviews the phase twice (`caddis_review.py --plan --phase --runs 2`),
starts one fix session on blocking findings, and stops `BLOCKED review` when findings remain.
`CADDIS_HEADLESS=1` alone is NOT that instruction: without the prompt line, a `risk: high` phase still halts.

**At every halt, PERFORM the handoff yourself, now, before you stop.** Write `relay.md` and update
the Tracker in this session — you are the only party holding the context that makes them worth
anything, and it evaporates the moment you stop.

**Do NOT emit "run `/caddis:handoff`", "do a handoff", or "update the relay" as a next action.**
Naming the command instead of doing the work is the single most common way this step is skipped: the
session ends, the user runs `/clear`, and the durable record that should have been written never is.
`/caddis:handoff` is the same procedure a human may invoke *between* sessions; **at a halt, you are
the one performing it.** The only next action you hand back is the resume line in the halt block.

Then print the halt block as your **last output before the JSON**, so the human has one action rather
than an archaeology job:

```
=== HALT — <one-line reason> ===
Done:    phases <a>-<b> (<milestone>) · commits <sha>, <sha>
Blocked: <what, or "nothing">
You:     /clear, then paste ↓
         read <plan path> and implement Phase <next>
```

**In headless/runner mode, never ask — halt, write the block, and exit.** The block is how a
non-interactive run tells a human what it needs; asking is still forbidden.

**4. Run the tests yourself.** After the last phase you complete, run the tests of the files you touched
once more, in the foreground, each command under 10 minutes (split into parts if needed), and record the
real result. Never start the full suite in the background and never wait on a monitor for it. CI runs the
full suite on every PR and is the gate before merge. The runner re-runs its own gate independently and
that decides success — but you run your tests too so your reported `"tests"` value is truthful, not
assumed. Never report `"passed"` on tests you did not see go green.

**4b. If every phase is now done, tidy the plan into `done/` IN THE SAME COMMIT.** Only when the
whole plan is finished (every `## Tracker` row is `done`, no halt, no blocker) — a mid-plan halt is
not this. Tidy is part of finishing: the plan closes in the PR that finishes it, so nothing is left
for a later session to clean up, and nothing is left uncommitted. Order matters:

1. Edit the final phase's `## Tracker` row to `done` (Step 3). **Do not commit it yet.**
2. Run tidy on THIS plan only. It reads the Tracker, sets the plan's `status: done` and `git mv`s
   it into `done/`. `--only` keeps it off every other file, so another session's finished plan, a
   shipped prompt or a done parking-lot item is never swept into this PR:
   ```
   python "${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.167/scripts/caddis_tidy.py" --repo-root . --apply --only .caddis/plans/<this plan>.md
   ```
   Read the output before you commit. It must say `moved: .caddis/plans/<this plan>.md` and name
   no other file. **Refuse** if it would touch anything else, or prints `ERROR` or `NOT MOVED`:
   stop, do not commit the move, and report the output in the review file.
3. `git add` the moved plan by name (`.caddis/plans/done/<plan>.md`, so the status and Tracker edits
   are staged with the rename), then make the final commit with
   `git commit -m "…" -- .caddis/plans/<plan>.md .caddis/plans/done/<plan>.md` (both sides of the
   rename). The move, the status and the last Tracker row land in one commit.

(Falls back to `scripts/caddis_tidy.py` from a source checkout; **skip this step if the script is
missing** — degrades open, same as the gates in Step 1.) A **collision** (`done/<name>` already
exists) is reported by the script, not fatal: it changes nothing, so commit the Tracker row as
usual and note the collision in the review file; do not fail the run over it. `/caddis:ship-pr`
runs `caddis_tidy.py --check` on the PR's files and stops on a plan whose Tracker is done but whose
status is not, so a skipped tidy is caught before the PR opens.

**5. Write a concise review file** to `.caddis/reviews/<slug>.md`, where `<slug>` is the plan file's
name without `.md`. Create `.caddis/reviews/` if needed.
Keep it short and scannable — this is what the human reviewer reads before merging the branch:

```markdown
---
type: implement-review
feature: <slug>
branch: <current branch>
---

# Implement review — <feature>
**Branch:** `<current branch>`  •  **Phases done:** <N of M>  •  **Tests:** passed | failed

## What changed
- <phase 1 — one line: what shipped + commit hash>
- <phase 2 — …>

## Assumptions made
- <any gap the plan left that you decided — or "none">

## Task progress  *(only for `Execution: per-task` phases)*
- <phase N task N.M — commit <hash> — self-check: clean | fixed <finding>>

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

If you had to stop before implementing anything (e.g. you were on the default branch, or the plan was
unreadable), still end with the block using `"implemented":false,"phases_done":0,"tests":"failed"` and put
the reason in the review file. The only acceptable final output is the code + commits + review file + this
one JSON block — never questions, never prose after the block.
