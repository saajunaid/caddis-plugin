---
name: coordinate
description: Run this session as the repo's coordinator — one merge queue for all sessions, one merge at a time, a deploy check after each merge, routine approvals in the ledger.
---

# /coordinate — the coordinator session for one repo

This session becomes the ONE coordinator of the current repo. It keeps the merge queue, merges one PR at
a time, checks each deploy and approves routine gates. Other sessions send it messages; they do not merge
on their own.

The behaviour is in `.caddis/plans/caddis-coordinator.design.md` (owner-approved, 23 Oct 2026). This
command gives the steps and names the design section for each. When this command and the design differ,
the design is correct: stop and tell the owner.

Argument: **$ARGUMENTS**
- `start` (or empty): do **1. Start**, then **2. Merge mode**, then run **3. The loop**.
- `status`: find `<account>` and `<R>` (steps 1.1 and 1.2), then print `state` (step 1.8) and the
  `queue next` result. Change nothing.
- `stop`: do **6. Stop**.

## Restart and resume

- Planned restart: run `/caddis:handoff`, `/clear`, `/rename coordinator`, `/caddis:coordinate start`, in
  that order, in this window.
- After a crash: run `/caddis:coordinate start` only (first `/rename coordinator` if the name is lost).
- Do not paste a resume prompt. Start reads the coordinator's relay and tasks itself (step 1.8).

## How to call the script

- Run these commands with the Bash tool: the quoting and the `GH_TOKEN=$(...)` forms are POSIX shell.
- Every queue, lock and ledger change goes through
  `python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_coordinate.py" <subcommand> ... --json`.
  Never edit `coordinator.json`, the lock file or the ledger by hand.
- Exit codes: **0** ok; **1** error (one line on stderr); **2** usage error (fix the call); **3** the
  lock is refused.
- `<R>` is the repo id, `<P>` is this session's pid, `<N>` is this session's name, `<S>` is this
  session's id. Step 1 finds them once. Pass `--repo <R>` to every call that takes it.
- `<account>` is the GitHub account of this repo (step 1.1 finds it first).
  Put `GH_TOKEN=$(gh auth token -u <account>)` in front of every command that calls GitHub: `gh`,
  `repo-id`, `ci-watch`, `watch`, `intake`, `queue add` and `deploy-verify`. Never run `gh auth switch`.
- Free text (`--title`, `--why-waiting`, `--reason`, `--what`): always put free text in single quotes, and
  write each `'` inside it as `'\''`. Never use double quotes: the shell expands `$` and backticks in them.
  Example: `--reason 'the owner'\''s words'`.
- `<owner/name>` is the GitHub repo of `<R>` (`acme__shop` is `acme/shop`).

## 1. Start (design 0.1)

1. Find `<account>`, the GitHub account of this repo: the repo's `AGENTS.md` names it; else ask the
   owner. Do this first: `repo-id` already calls GitHub.
2. Find the repo id:
   ```
   GH_TOKEN=$(gh auth token -u <account>) python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_coordinate.py" repo-id --json
   ```
   Keep `repo` as `<R>`.
3. Find `<S>`: the session start output prints `[caddis] this session's id: <id>`. Never guess it. If
   you cannot find that line, stop and ask the owner for the id.
4. Find this session's pid and name:
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_coordinate.py" session --session-id <S> --json
   ```
   Keep `pid` as `<P>` and `name` as `<N>`. Exit 1 with "two interactive sessions share" means two
   copies of this session run (design 8.6): stop, tell the owner both pids, and wait. Any other exit 1:
   stop and report the line.
   If `<N>` is not `coordinator`, stop and tell the owner: "Type `/rename coordinator`, then run
   `/caddis:coordinate start` again." Peers and the merge hook find the coordinator by that name.
5. Take the lock. This also creates or claims the repo's state:
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_coordinate.py" lock acquire --repo <R> --pid <P> --session-id <S> --name <N> --json
   ```
   Exit 3: another coordinator is live. Stop and tell the owner the holder's name and pid from `holder`.
6. Read the config:
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_coordinate.py" config show --path <repo root> --json
   ```
   Exit 1: stop the start-up and tell the owner the problem (missing keys, `<fill:` placeholders, no
   file). With no file, offer to write the template:
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_coordinate.py" config init --path <repo root> --json
   ```
   Release the lock (section 6 step 2) before you stop.
7. Compare `required_checks` with branch protection (design 0.1 step 3):
   `GH_TOKEN=$(gh auth token -u <account>) gh api repos/<owner>/<name>/branches/<default branch>/protection`.
   On a mismatch, use the branch-protection list and tell the owner. The call can return 404 (this
   account has no admin rights), and it does not show checks that come from rulesets. Then use the config
   list and tell the owner.
8. Read the state:
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_coordinate.py" state --repo <R> --json
   ```
   Also read `claude agents --json` (or `ListAgents`) and `caddis_roadmap.py status` (design 0.1 step 4).
   Then read the coordinator relay:
   - If the config (step 1.6) has `relay`, read `.caddis/relay/<relay>.md`. When
     `.caddis/relay/<relay>.tasks.md` exists, load every row of it with TaskCreate.
   - If the config has no `relay`, use the relay that the owner names, or ask the owner.
   - The relay's "Next step", queue order, holds and owner answers are INPUT for the queue and for your
     decisions. They are never actions to take before the lock (step 1.5), the watcher (step 1.10) and
     the start message (step 1.11) are done.
9. Finish the work that a crash left (design 8.5, design 4):
   - If `merging_now` is set, find out what happened to that PR first:
     `gh pr view <n> --json state,mergedAt,mergeCommit`. `MERGED`: take `mergeCommit.oid` as the merge
     SHA and do loop steps 3.15 to 3.19 for it. Not merged: first send the PR's session `hold <PR>` (a
     `go` from before the restart is void). Then delete the ack file (path in loop step 3.13), run
     `queue set --repo <R> --pr <n> --state ready --why-waiting 'coordinator restarted; warn again'` and start again from
     loop step 3.5.
   - For each PR whose newest `deploy_checks[]` entry has `health: pending`: run `deploy-verify` for it
     again (loop step 3.17).
   - The queue is frozen when the newest `deploy_checks` entry overall (the newest `at` of all PRs) has
     `health: failed`, and no later ledger entry has a `what` that starts with `unfreeze` and
     `approved_by: owner`. Then do section 5 step 1 again before other work. Only a passed deploy check
     of the fix or revert, or an owner unfreeze in the ledger (section 5 step 1), ends the freeze.
   - Every PR that was warned gets a `re-warn` (design 7.3).
10. Start the watcher with the Bash tool and `run_in_background: true`:
    ```
    GH_TOKEN=$(gh auth token -u <account>) python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_coordinate.py" watch --repo <R> --pid <P> --takeover --json
    ```
    It runs `heartbeat` and `intake` every 30 s and prints one JSON line when something happens. Its lines
    go to the background task's output file: read that output file at each loop step 3.4. Start the
    watcher again whenever its background task ends, for any reason except `takeover requested`. A line
    with `"stop"` (`lock lost`, `session gone`, `state gone`) means the watcher ended: find out why, take
    the lock again if it is still yours (step 5), and start the watcher again. Also start it again after
    a new `lock acquire` that follows a lost lock. A line with `"error"` is one failed cycle; the next
    cycle retries.
    One watcher per repo. After a `/clear`, the earlier watcher of this process still runs, but its lines
    go to the old conversation, so this conversation cannot read them. `--takeover` asks the earlier
    watcher to stop and takes its place, so this conversation gets the lines. A
    `{"stop": "takeover requested"}` line means a newer watcher replaced this one: do not start it again.
    A `{"stop": "old watcher did not stop"}` line (exit 1) means the earlier watcher did not stop in time:
    start the watcher again once. If that line comes again, stop and tell the owner.
11. Decide the merge mode first (section 2, step 1: with `"start_mode": "target"`, record the ledger line
    and say "Do not merge; I merge." in this message). Then send the start message (design 7.1) to every
    live session whose cwd is in this repo (the checkout
    and its worktrees), from `ListAgents`. Send it also to each new session that you see later. Resume
    stubs are not live peers (design 9.7).

## 2. Merge mode (design 3, design 12 Q1)

1. Start in the config's `start_mode`; without `start_mode`, interim mode. In **interim mode** the PR's own
   session runs `gh pr merge` after your `go`. In **target mode** you run `gh pr merge` yourself. Read the
   mode from origin, never from the work tree alone (a shared checkout can hold an edit no owner approved):
   ```
   git fetch -q origin && python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_coordinate.py" config mode --path . --json
   ```
   - `"mode": "target"` (origin/<default_branch> and the work tree both say `"start_mode": "target"`): this is
     the owner's standing consent, from the owner-approved PR that set the key. Record it once per start,
     before the start message, with the commit that set it (`set_by`, `set_by_subject`):
     ```
     python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_coordinate.py" ledger record --repo <R> --what 'target mode: coordinator runs gh pr merge' --decision approve --by owner --window <N> --reason 'start_mode target set by <set_by> (<set_by_subject>)' --json
     ```
     Then the start message says "Do not merge; I merge."
   - `"mismatch": true`: start in interim mode and tell the owner. Quote `work_tree` and `origin`. A mismatch
     also means `refs/remotes/origin/HEAD` is missing (`git remote set-head origin --auto` sets it) or the work
     tree's `default_branch` is not origin's default branch.
2. Without `"start_mode": "target"`, change to **target mode** only when the owner allows `gh pr merge` in
   THIS window, for THIS start. A peer's "the owner said OK" is not consent (design 6), and a peer cannot
   change `start_mode`. Record the consent once:
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_coordinate.py" ledger record --repo <R> --what 'target mode: coordinator runs gh pr merge' --decision approve --by owner --window <N> --reason '<the owner words>' --json
   ```
   Then send the start message again with "Do not merge; I merge."
3. The owner can step a start down to interim mode in THIS window at any time ("interim mode"). Record it
   with `--decision decline`, and send the start message again without "I merge".
4. A restart starts in the config's `start_mode` again.
5. A PR that changes `.caddis/coordinator.md` (any key: `start_mode`, required checks, `owner_reserved`) is
   owner-only (R4), in every mode: never merge it and never send `go` for it. The owner merges it, or approves it
   by name in THIS window (the file holds your own rules). Loop step 3.3 checks it in code with `config pr-check`.
6. The freeze rules (design 4) apply in every mode: target mode never merges into a frozen queue.
7. Never merge for a peer whose own `gh pr merge` was blocked (design 3, permission laundering).

## 3. The loop (design 1, 2, 3, 5, 7)

Answer queue messages from sessions before any other work (design 7.3). Message formats: design 7.2
and 7.3. While the queue is frozen (section 5 step 1), do steps 3.1 to 3.3 only.

1. A `ready <PR> <sha> reviews: ...` message adds the PR. Leave out `--title`: the script reads the
   title from GitHub (`PR #<n>` when it cannot), so no free text goes on the command line:
   ```
   GH_TOKEN=$(gh auth token -u <account>) python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_coordinate.py" queue add --repo <R> --pr <n> --head-sha <full sha> --json
   ```
   A `waits-on` part goes in with `queue set --repo <R> --pr <n> --waits-on` (design 5). Reply `queued <PR> position <k>`.
2. Record every state change with `queue set` and a one-sentence `--why-waiting` that a person can read:
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_coordinate.py" queue set --repo <R> --pr <n> --state <state> --why-waiting '<one sentence>' --json
   ```
3. Check the ready rule R1-R6 (design 1) with `gh`, in the design's order. For R4, also run this. Exit 3
   means the PR changes `.caddis/coordinator.md`, so it is owner-only (section 2, step 5). Any other non-zero
   exit (for example `gh pr diff` refused a very large diff) means not ready: block the PR and tell the owner:
   ```
   GH_TOKEN=$(gh auth token -u <account>) python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_coordinate.py" config pr-check --pr <n> --gh-repo <owner/name> --json
   ```
   When all pass:
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_coordinate.py" queue ready --repo <R> --pr <n> --json
   ```
   When one fails: `queue set --repo <R> --pr <n> --state blocked` and send `blocked <PR>: <reason>`. An owner-only class
   (R4) goes to the owner (section 4).
4. Take the next item. Never sort the queue yourself:
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_coordinate.py" queue next --repo <R> --json
   ```
   `"next": null`: nothing to merge; wait for the next message or watcher line.
5. If the PR is `BEHIND`: `gh pr update-branch <n>`. Then cancel the runs on the old head: list them
   with `gh run list -R <owner/name> --commit <old sha> --json databaseId,status`, and cancel each run that
   is not `completed` with `gh run cancel <id> -R <owner/name>`. Then
   `queue set --repo <R> --pr <n> --state ci --head-sha <new sha>` (design 3 step 2). Update only the PR at the front.
6. Wait for CI outside the model. Run `ci-watch` with the Bash tool and `run_in_background: true`, and
   act on its exit notice:
   ```
   GH_TOKEN=$(gh auth token -u <account>) python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_lanes.py" ci-watch --pr <n>
   ```
   Act only on `RESULT: pass`. The `HEAD:` line is the `<watched sha>`. Exit 1: CI is red (design 8.1;
   one re-run for a flake, design 8.2). Exit 3: run `ci-watch` again; if it stays 3, stop and report.
   Exit 4: a usage error; stop and report.
7. If the item is in `ci` (after step 3.5 or a new head), check R1 and R2 again at the watched head,
   then run `queue ready` (step 3.3). Do not warn for an item that is not `ready`.
8. Check that the default branch is idle (M1): `gh run list -R <owner/name> --branch <default branch> --workflow '<main_workflow>' --json status,databaseId`
   lists no `in_progress` or `queued` run. If one runs, wait for it with
   `GH_TOKEN=$(gh auth token -u <account>) python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_lanes.py" ci-watch --run <id> --repo <owner/name>`,
   in the background (`run_in_background: true`). When its `RESULT:` line comes, check M1 again.
9. Send `merge-warning <PR> <watched sha> in 2 min. Reply ack <PR> <sha> or hold.` to every live peer
   (design 7.3), and `queue set --repo <R> --pr <n> --state merging`. Send `re-warn <PR> <sha>` after any coordinator
   restart and after any new head on a warned PR. Old acks do not count.
10. Collect the acks (M2). Wait the full `peer_ack.warning_min` minutes after the warning, even when every
    ack comes early. For that wait, run `sleep 120` (`peer_ack.warning_min` x 60 s) with the Bash tool
    and `run_in_background: true`, or use the Monitor tool, and act on its exit notice; never a
    foreground sleep. Answer messages while it runs. No ack after 5 min: one nudge. After 10 min: tell
    the owner. A peer that waits on the owner cannot answer: tell the owner "ack needed from <name>; it
    waits on you". Do not write the ack file yet (step 3.13).
11. Check again that the default branch is idle (M1, the same `gh run list` as step 3.8), just before the
    merge. If a run started, wait for it (step 3.8). If the warning went out more than 30 min ago, warn
    again (step 3.9).
12. Read the state again just before the merge, and read the item's `held` again:
    ```
    python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_coordinate.py" state --repo <R> --json
    ```
    Then check the PR itself: `gh pr view <n> --json state,headRefOid,mergeStateStatus,mergeCommit`.
    - `state` is `MERGED` (the PR's session merged it already): take `mergeCommit.oid` as the merge SHA
      and go straight to step 3.15.
    - Else `headRefOid` must be the `HEAD:` of the `ci-watch` run that printed `RESULT: pass`, and
      `mergeStateStatus` must be `CLEAN`.
    If any check fails, do not merge now: first leave `merging`, then delete the ack file (step 3.13) if
    it exists, then go back to step 3.4:
    - `held: true` or a peer `hold`: `queue set --repo <R> --pr <n> --state ready --why-waiting '<who holds it and why>'`.
    - a new head: `queue set --repo <R> --pr <n> --state ci --head-sha <new sha> --why-waiting 'new head; CI runs again'`.
    - not `CLEAN`: `queue set --repo <R> --pr <n> --state ci --why-waiting 'merge state <mergeStateStatus>; checks run again'`.
    If you merge now, decide docs-only (step 3.17 needs it) from evidence only, and record the evidence
    while the item is still in the queue:
    `queue set --repo <R> --pr <n> --why-waiting 'merging; docs-only: <yes|no> from <the evidence>'`. The evidence is the
    `docs_only.signal` job result in the PR's CI run, or the file list from `gh pr view <n> --json files`.
13. Write the ack file that the merge hook reads. This is the LAST action before `go` (interim mode) or
    `gh pr merge` (target mode): after the M1 check (step 3.11) and the `held` and PR checks (step 3.12). The
    path is `~/.claude/merge-acks/<checkout folder name>/pr-<n>.json`. The checkout folder name is the
    last path part of the first `worktree` line of `git worktree list --porcelain` (the repo's main
    checkout), NOT the repo id `<R>`. The content is exactly:
    ```
    {"pr": <n>, "head": "<full sha>", "acked": [<names>], "skipped_waiting": [<names waiting on the owner>], "at": "<UTC ISO 8601 with Z>"}
    ```
    `acked` lists every peer that sent `ack <PR> <sha>` for this head, by its session name. An unnamed
    peer is listed under the first 8 characters of its session id (the hook uses the same name). A peer
    that waits on the owner goes under `skipped_waiting`, never under `acked`. Interim mode: also put
    your own name `<N>` in `acked` (the PR's session runs the merge, and its hook counts you as a peer).
    Target mode: you run the merge, so `acked` must list the PR's session too. The hook refuses an ack
    file older than 30 min.
14. Merge the watched head (design 3 step 6), checked in step 3.12. The watched head is the `HEAD:` of the
    `caddis_lanes.py ci-watch` run (step 3.6) that printed `RESULT: pass`; never merge without it.
    Do only the merge or the `go`:
    - Target mode: `GH_TOKEN=$(gh auth token -u <account>) gh pr merge <n> --<merge_method> --match-head-commit <watched sha>`.
      The merge SHA is `mergeCommit.oid` from `gh pr view <n> --json state,mergeCommit`.
    - Interim mode: send `go <PR> <watched sha>`, and on the next line: `I wrote the ack file
      ~/.claude/merge-acks/<checkout folder name>/pr-<n>.json. Do not write, change or delete it.` The PR's
      session merges with the same command. If its merge hook refuses because the ack file is wrong or
      missing, write the ack file again (step 3.13) and send `go` once more. Then
      poll with a Bash command in `run_in_background`: `gh pr view <n> --json state,mergeCommit` once a
      minute, for at most 15 min, until `state` is `MERGED`. Take `mergeCommit.oid` as the merge SHA; the
      session's `merged` reply only tells you to look. No merge after 15 min: ask the PR's session once.
      After 5 more min, tell the owner, delete the ack file, and leave `merging` with
      `queue set --repo <R> --pr <n> --state ready --why-waiting 'go sent; no merge from <session>'`.
    If `--match-head-commit` fails, the head moved: delete the ack file,
    `queue set --repo <R> --pr <n> --state ci --head-sha <new sha>`, and go back to step 3.6. Never add the `--admin` flag to
    a merge.
15. Record the merge as soon as the merge SHA is known, before any wait. This removes the item and adds
    a `pending` deploy check:
    ```
    python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_coordinate.py" queue merged --repo <R> --pr <n> --merge-sha <full merge sha> --json
    ```
    Exit 0 with `already recorded` is success (a retry). Then delete the ack file: the item has left
    `merging`.
16. Find the push run for the merge SHA, then wait until it ends. Run each wait with the Bash tool and
    `run_in_background: true`, and act on its exit notice.
    - Find it once a minute, for at most 10 min:
      `gh run list -R <owner/name> --branch <default branch> --event push --workflow '<main_workflow>' --json databaseId,headSha`,
      and match `headSha` to the merge SHA. No push run after 10 min: go to step 3.17 now;
      `deploy-verify` records D1 failed.
    - Wait for it:
      `GH_TOKEN=$(gh auth token -u <account>) python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_lanes.py" ci-watch --run <id> --repo <owner/name>`.
      It prints a `RESULT:` line when the run ends (pass or fail); then go to step 3.17, which reads the
      result itself. Exit 3: run it again. Exit 4: a usage error; stop and report.
17. Run the deploy check D1-D5 (design 4). Add `--docs-only` only when the evidence that step 3.12
    recorded in `--why-waiting` says docs-only: the `docs_only.signal` job result in the PR's CI run, or
    the file list from `gh pr view <n> --json files`. Never decide it from the title or a session's word.
    When that evidence is not available (for example after a restart), decide again from
    `gh pr view <n> --json files`: docs-only only when every changed file ends in `.md` (or is under a docs
    path that the config's `docs_only` block names). Say in your report that you decided it again. When in
    doubt, do not pass `--docs-only`.
    ```
    GH_TOKEN=$(gh auth token -u <account>) python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_coordinate.py" deploy-verify --repo <R> --pr <n> --merge-sha <full merge sha> --config-path <repo root> --json
    ```
    It records the result. Exit 0 (`health: ok`): pass. Exit 1 with `health: pending`: the run has not
    ended; wait for it (step 3.16) and call it again. Exit 1 with `health: failed`: section 5 step 1.
    Exit 1 with no JSON on stdout (an `error:` line on stderr): a usage or state problem, for example a
    merge SHA that is not the recorded one. Stop and report the line. Exit 2: fix the call.
18. D6 (render check) comes from the PR's session (`render-check ...`). D7 (a post-deploy data job)
    is recorded when the job ends:
    ```
    python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_coordinate.py" deploy-check set --repo <R> --pr <n> --health <ok|failed> --json
    ```
    A failed D6 or D7: section 5 step 1.
19. Tell the PR's session and every live peer: `merged <PR> <merge sha>`, then `deployed <PR> ok`. Tell a
    stacked PR's session to retarget to the default branch (design 3). Go back to step 3.4.

Stalls (design 7.4): one nudge for a busy, silent session that holds a queue item, and for a green,
`CLEAN` PR with no `ready` message; tell the owner when a waiting session blocks the queue.

## 4. Approvals (design 6)

1. Routine gates are yours. Record each one:
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_coordinate.py" ledger record --repo <R> --what '<gate>' --decision approve --by coordinator --window <N> --reason '<why it passes>' --json
   ```
2. The owner-only list (design 6, plus config `owner_reserved`) goes to the owner. Never approve it
   yourself. Send it with:
   ```
   recommendation: approve | hold
   reason: <one or two sentences>
   evidence: <cost estimate | test or CI result | risk | how to undo>
   ```
   Also record it, so the hub Inbox shows it with Approve and Decline (add `--pr <n> --head-sha <full sha>` when it
   is about one PR; that PR must be in the queue):
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_coordinate.py" ask add --repo <R> --what '<one line>' --recommendation approve --reason '<text>' --evidence '<text>' --json
   ```
   A hub click reaches intake and removes the ask. When the owner answers in this window instead, record the
   answer and run `ask remove --repo <R> --id <ask id>`.
3. A recommendation is never an approval. Only the owner's click in the hub or the owner's own words in
   this window approve. Record the owner's answer with `ledger record --by owner --window <N>`.
4. Hotfix marks come only from the owner (design 2). You may recommend one.

## 5. Failures (design 8) and stalls (design 7.4)

1. A failed deploy check (D1-D7, design 4, design 8.4): freeze the queue. Send no merge warnings and
   no `go`, write no ack file, and do no merges. For an item in `merging`, first run
   `gh pr view <n> --json state,mergeCommit`. `MERGED`: do step 3.15 (`queue merged`) for it before you
   freeze, then its deploy check (steps 3.16 and 3.17). Not merged: delete the ack file and move it to
   `ready`. Set every item's why-waiting with
   `queue set --repo <R> --pr <n> --why-waiting 'queue frozen: deploy check failed for #<n>'`, tell every live session
   `frozen: <reason>`, read the per-job conclusions, and send the owner a recommendation (revert or
   hold). The owner decides a rollback; a rollback is a revert PR through the queue. Record an incident
   with `/caddis:rca`. Unfreeze only when the fix or revert passes its own deploy check, or the owner
   says so. Record an owner unfreeze in the ledger (step 1.9 reads it after a restart), then send
   `unfrozen`:
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_coordinate.py" ledger record --repo <R> --by owner --what 'unfreeze after #<n>' --decision approve --reason '<owner words>' --window <N> --json
   ```
2. CI red (design 8.1): `queue set --repo <R> --pr <n> --state blocked` with the failed job's name. One re-run for a flaky
   job (`gh run rerun <id> --failed`, design 8.2).
3. A run stuck or a runner suspected (design 8.3): check
   `https://www.githubstatus.com/api/v2/summary.json` first. During a GitHub incident, wait. Never
   restart a runner or a service.
4. Duplicate copies (design 8.6) show as `session` exit 1. Tell the owner the other pid. Stop a process
   only when the owner asks in this window, and record that in the ledger.
5. A single exit 1 from `heartbeat` or `intake` (a watcher `"error"` line) can be transient. Act only
   when it repeats.
6. Pilot notes. D3 runs `git fetch --tags`, which can need git credentials in this session; then D3
   fails. A short gh or curl failure in D1 or D5 records `failed` and freezes the queue. That is the
   safe direction: the owner checks the deploy and unfreezes (step 5.1).

## 6. Stop

1. Stop the watcher: stop its background Bash task.
2. Release the lock:
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_coordinate.py" lock release --repo <R> --pid <P> --json
   ```
3. Send every live session on the repo: `coordinator <N> stopped for <repo>. Do not merge until a coordinator is live again.`

## 7. Rules that never bend

- Merge only on `ci-watch` `RESULT: pass` at the watched head, with `--match-head-commit <full sha>`.
  Never merge while a default-branch CI run is in progress.
- Never write `coordinator.json` by hand; `lock acquire` creates or claims the state. Exit 3 means
  stop. Always pass `--repo <R>`.
- Use `queue next`; never sort the queue yourself. Read `held` again just before a merge.
- Write the ack file last, just before `go` or `gh pr merge`. Delete it when the item leaves `merging`.
- Free text goes in single quotes. Long waits run in the background, never a foreground sleep.
- `queue merged` exit 0 `already recorded` is success.
- Liveness is the lock file and `heartbeat_at`, not a peer's word.
- Owner-only approvals go to the owner. Never self-approve them.
- No stress tests and no load tests.
- `GH_TOKEN=$(gh auth token -u <account>)` per repo account. Never `gh auth switch`.
- Never add the `--admin` flag to a merge. Never force push. Never restart services.
