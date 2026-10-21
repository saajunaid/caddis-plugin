---
type: prompt
title: Plan resume prompt for {{slug}}
description: The prompt for one fresh runner session of the plan {{slug}} (runner plan mode). It does one batch and ends with a status line.
status: current
timestamp: {{date}}
---

You are a fresh session for the plan `{{slug}}`. Do ONE batch, then stop.

In the commands below, `<scripts>` is the caddis scripts folder `{{scripts}}` (put it in quotes if it holds a space).
Use the scripts in that folder; do not look for them in another caddis install.

## 1. Read

1. The plan `.caddis/plans/{{slug}}.md`: its goal, its decisions, its tracker. Every decision binds you.
2. The relay `.caddis/relay/{{slug}}.md`. Its "Next step" says where to start.
3. The open parking-lot items (`.caddis/parking-lot/*.md` with `status: open`) that name this plan, when any.

## 2. Step 0: reconcile

The relay can be old. Before you act, compare it with the real state: the plan tracker, worktrees, local branches, open
pull requests and remote branches. If they disagree, trust the real state. Fix the relay and the tracker. Do not build on a
guess.

## 3. Pick the batch

A batch is ONE tracker phase (the first row that is not done and not blocked), or ONE named batch that the plan or the relay
names. If no row can start, end with the status line that says why (an owner gate, a block, or FAILED).

The phase number chosen by the roadmap runner (empty: choose the batch yourself as above): {{phase}}
When it holds a number, that phase is the batch. Do only that phase.

Roadmap mode (a number above): the runner, not you, publishes the work. The runner made the branch you are on
(`caddis/roadmap/<roadmap>/<plan>-p<n>`, fresh from the default branch). Stay on it: never switch or create a branch,
never push, never open a pull request, and never edit anything under `.caddis/roadmaps/` (the runner refuses to
publish a branch that does). Commit the phase there, with its tracker row set to `done`. When you end with
`STATUS: CONTINUE` and new commits on that branch, the runner pushes it, opens the pull request and stops with
`BLOCKED waiting for merge`; the recheck task restarts the runner after the merge.

## 4. Work

- Do ONE batch with `/caddis:implement` discipline: tests first, the phase's exit gate, a commit per phase.
- agy sessions only: run `python {{scripts}}/caddis_spend.py check` before each agy call. Stop at the cap (exit 1 over
  the cap, 3 not configured).
- You may do everything except pass an owner gate. Never pass an owner gate. Never raise a cap. Never delete a STOP file.
- The runner reviews `risk: high` phases. A phase marked `**Risk:** high`: do not halt for it and do not run the
  review yourself. When its exit gate is green, set its row `done` and end with `STATUS: CONTINUE`. The runner then
  reviews it twice and, on findings, starts one fix session.
- Set the tracker row of the batch to `done` (with its evidence) when its exit gate is green. Work you defer on
  purpose is filed once with `/caddis:park` (a parking-lot item); never write a to-do or backlog file.

## 5. Write the relay

Write the relay with `python <scripts>/caddis_workstreams.py put --require-status {{slug}} <file>`. Write `<file>` outside
the repo (for example in the temp folder). Read the current relay first with `python <scripts>/caddis_workstreams.py read {{slug}}`;
keep its frontmatter shape (`type: relay`, `workstream: {{slug}}`, `branch`, `session_id`, `plan`, `generated.at`). The LAST
non-empty line must be exactly one of these four:

```
STATUS: CONTINUE
STATUS: OWNER-GATE <P>-OG<n>
STATUS: BLOCKED <owner>
STATUS: FAILED <reason>
```

Use `STATUS: CONTINUE` only when the next batch can start with no owner input. A missing or bad line counts as FAILED.
An owner gate id has the form `<P>-OG<n>`: the plan's 2 to 4 capital-letter prefix (for example `PM-OG1`). Name the gate
in the plan's decisions with that id. Any other form is a bad line.

## 6. Notify and end

When the status is not CONTINUE, call the `PushNotification` tool as your last action. Put the plan, the status line and the
next step in the message. After the call succeeds, print the line `PUSH-SENT`. The runner looks for that marker. Without it,
the runner sends the notification itself.

Then end the session.
