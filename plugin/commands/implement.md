---
description: Headless plan executor — implement an approved plan phase-by-phase on the current feature branch, TDD-first, committing per phase
argument-hint: <path to .caddis/plans/<slug>.md>
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

**Run the machine gates first — they decide, not your reading of the prose below.**

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_gate.py" lane-check    --plan <plan> --phase <N>
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_gate.py" verdict-gate  --plan <plan> --phase <N>
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_gate.py" tracker-vs-git --plan <plan>
```

Obey the exit code: **0** proceed · **1** STOP and report why · **2** proceed but record the note it
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

- **Interactive session (no `CADDIS_HEADLESS`, no `DOCKET_PLAN`/`DOCKET_BRANCH` in the environment)
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
- **Headless or docket-runner session → never spawn. Implement here and record the deviation.**
  You may already *be* the spawned lane, and a session that spawns its own lane on every start is
  an infinite loop. The env markers above are the guard: if either is set, someone else placed you.

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
row, visible to any later reader without an Advisory Hub having to catch it live.

**Advisory-Hub mode (conditional — OFF by default).** Check whether a companion file
`<plan-dir>/<plan-stem>-advisory-context.md` exists (e.g. plan `.caddis/plans/foo.md` → look for
`.caddis/plans/foo-advisory-context.md`). **If it does not exist — the normal case, including every
docket run — Advisory-Hub mode is OFF and nothing else in this command changes.** If it exists, read it
and set Advisory-Hub mode ON for this run: it names locked decisions you may not change unilaterally,
this project's declared safety conventions, and how to re-derive the plan's anchor numbers. See the
`advisory-hub` skill for the full contract.

**In Advisory-Hub mode, the previous phase's VERDICT gates this one.** Before starting phase N, require
a verdict in `.caddis/advisory-hub-reports/` that satisfies **all three** of:

1. **It covers phase N-1.** Usually `phase-(N-1).verdict.md`, but a **batched** verdict counts: a file
   whose `phase:` is a range — `phase-10-11.verdict.md`, `phase: 10-11` — satisfies the gate for every
   phase the range **covers**. Batched pairs are normal, not exotic: one live plan alone carries
   `phase-05-06`, `08-09`, `10-11` and `13-14`. A literal `phase-(N-1)` lookup sends phase 12 hunting
   for a `phase-11.verdict.md` that will never exist, and falsely blocks a properly validated plan.
2. **It belongs to the plan you are implementing.** The report directory is flat and shared, so with two
   hub-mode plans in one repo, plan A's `phase-02.verdict.md` would otherwise satisfy plan B's phase-3
   gate. Match the verdict's identity field against the plan. **Accept either `plan:` (a path) or
   `feature:` (a slug) — both are in live fleet use** and neither is wrong; one project's verdicts carry
   one, another's carry the other. If a verdict carries neither, treat its identity as unproven: say so
   and do not let it gate anything.
3. **It carries `verdict: accept` or `verdict: accept-with-correction`.**

- **Missing** → the Hub has not validated it yet. **STOP.** Mark the Tracker row
  `blocked-pending-hub` and say which verdict you are waiting on.
- **`verdict: reject`** → **STOP.** The phase is to be redone, not built upon.
- **`verdict: accept-degraded`** → the Hub validated it **without an advisory context**, so the
  locked-decision and safety-rule re-checks never ran. It is a partial check wearing an accept. Proceed
  only if the phase is low-stakes, and **say in your report that you did so on a degraded verdict**.
- Phase 1 (or the first phase of the plan) has no predecessor — proceed.

This is the Hub's central power and until now it ran on human discipline alone: the verdict recorded
whether the next phase could start, and *nothing read it*. Five lines of check make the claim true by
machine.

### Ringing the Hub, and waiting for it (Claude Code only, optional)

Two moments in Advisory-Hub mode currently cost the user a copy-paste. Both are optional, both
degrade to today's behaviour, and neither replaces a file.

**After you file `phase-NN.report.md`** — if `ListAgents` is available, look for a peer session whose
name starts with **this repo's directory name**. Sessions are auto-named `<repo-dir>-<hash>`, so a
same-repo peer is the Hub:

```
SendMessage({to: "<peer-name>", summary: "phase-05 report filed",
             message: "phase-05.report.md is filed and awaiting a verdict."})
```

**When you are BLOCKED on a verdict** — instead of stopping dead, subscribe once:

```
SendMessage({to: "<peer-name>", notify_when_idle: true,
             message: "blocked on phase-05 verdict; ping me when you have written it"})
```

`notify_when_idle` is one-shot and costs the Hub nothing extra. **Never poll `ListAgents` in a loop,
and never send "are you done yet?"** — that burns both sessions' context to no purpose.

**The rules that keep this from becoming a mess:**

- **The file is the decision; the message is a doorbell.** Never treat a chat message as a verdict.
  If a peer says "accepted", still read `phase-NN.verdict.md` — the gate above checks the FILE, and
  a message cannot be re-read next week or by a third session.
- **No `ListAgents`, no peer, or more than one same-repo peer → do nothing and carry on.** caddis
  also runs on agy and Codex, which have no cross-session messaging at all. Everything above is an
  accelerant on one harness; the file protocol is the portable layer and is what actually works.
- **Headless runs never message.** There is no copy-paste to save.
- **Never ask a peer to perform work your own session was denied.** Permission boundaries are
  per-session, and routing blocked work through another session launders the user's decision.

**If a `phase-NN.prompt.md` exists for the phase you are about to run, it is the INSTRUCTION OF
RECORD** — read it, and measure your DEVIATIONS against it, not against the plan alone. The Hub writes
that file before the phase precisely so a deviation is falsifiable; an executor that never reads it
undermines the whole argument.

**2. Determine where to resume.** The `## Tracker` table is the resume signal. Start at the first phase whose
status is not `done`/`✅`. If every phase is already done, verify the tests are green and go straight to the
report — do not redo completed work.

**3. Implement each remaining phase, TDD-first.** For each phase, in order:
   - **LANE** — **re-check this phase's `Lane:` and apply Step 1's spawn/record rule to it.** Do this
     first, every phase, not just the one you resumed at. Step 1's check only ever saw the *resume*
     phase: on a plan whose phase 1 is `claude` and phase 2 is `glm-headless`, it finds no mismatch and
     this loop then carries you straight through phase 2 — so the lane silently executes nothing for
     every phase after the first, which is the original bug wearing a different hat.
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
     the short commit hash (`git rev-parse --short HEAD`), set the `Lane` column to the lane this phase
     ACTUALLY ran on (not the planned one — see Step 1), and add a one-line note. This is what lets a
     future session (or the runner) see progress. Commit the Tracker update with the phase (or as a tiny
     follow-up commit) — it lives in the plan file, which is fine to commit on this branch.
   - **FILE THE PHASE REPORT — Advisory-Hub mode only.** *Skip this bullet entirely if Step 1 found no
     `<slug>-advisory-context.md`.* Write `.caddis/advisory-hub-reports/phase-NN.report.md` (zero-padded
     phase number; create the directory and add a `README.md` index row if absent — and when you
     create `.caddis/advisory-hub-reports/` for the first time, also write an **`AGENTS.md`** there
     carrying the naming, frontmatter and role rules from the `advisory-hub` skill, so they bind every
     agent that writes to that directory including ones that never loaded the skill. The skill claims
     this file ships; nothing ever created it, so it exists only where a Hub hand-wrote one.
     **Never overwrite an existing `AGENTS.md`** — the hand-written ones in the fleet are the good
     copies) using the
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

**3b. Halt only at a boundary.** Implement phase after phase, committing each. Stop for exactly four
reasons — a **milestone boundary**, a phase marked `Session: fresh`, **after** a `risk: high` phase,
or a **failed/blocked** phase. A lane change is not one of them: you spawn the lane yourself (Step 1).

The `risk: high` halt is deliberately *after*, not before. Execute and commit the phase normally; the
halt exists to stop the **next** phase building on it before a human has looked, so the blast radius
stays one reviewable, revertable commit.

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

**4. Run the tests yourself.** After the last phase you complete, run the project's full test command once
more and record the real result. The runner will re-run it independently and that decides success — but
you run it too so your reported `"tests"` value is truthful, not assumed. Never report `"passed"` on a
suite you did not see go green.

**4b. If every phase is now done, tidy the plan into `done/`.** Only when the whole plan is
finished (every `## Tracker` row is `done`, no halt, no blocker) — a mid-plan halt is not this.
Flip the plan's own frontmatter `status:` to `done` (your judgment call: only if the Tracker
genuinely backs it up), commit that with the final phase, then run:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_tidy.py" --apply
```
(falls back to `scripts/caddis_tidy.py` from a source checkout; **skip this step if the script is
missing** — degrades open, same as the gates in Step 1). A **collision**
(`done/<name>` already exists) is reported by the script, not fatal — note it in the review file,
do not fail the run over it.

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
