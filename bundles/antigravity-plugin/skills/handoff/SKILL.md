---
name: handoff
description: End-of-session handoff — capture exact state so the next session resumes with zero re-discovery
---

# /handoff — stop cleanly, write the resume doc

You are ending a work session. Produce/refresh this workstream's resume doc (`.caddis/relay/<name>.md`) so the next session
(you, a future you, or another agent on any tool) can resume immediately. This is the anti-context-rot checkpoint.

Several sessions to close together? Run `/caddis:fleet-close` in one of them instead; it asks each session to run this
command and collects one restart sheet.

## Step 0 — is this a shared checkout?
Another session may have uncommitted edits in this checkout. A handoff that commits here can carry
them into its commit, so check first, before Step 1.

1. Write this session's own files to a temp file: copy the list under `## Files changed this session`
   in `.caddis/session-state/<session-id>.md` (the `` - `path` `` lines can be copied as they are).
   No state file or no list means an empty file.
2. Run:
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_checkout_guard.py" shared --root . --own-files <temp-file>
   ```
   It prints `SHARED: yes <reason>` or `SHARED: no` and exits 0. It says yes when the root `AGENTS.md`
   has a line `Shared checkout: yes`, or when `git status` lists a path this session did not change.
3. **On `SHARED: no`,** do the steps below as written.
4. **On `SHARED: yes`,** write NO tracked file in this checkout. Run:
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_docs_pr.py" start --repo .
   ```
   It makes a new worktree from `origin/<default>` on a `docs/handoff-<utc>` branch and prints
   `WORKTREE: <path>`. That worktree is this session's only; no other session's edits can enter it.
   Then, in the steps below:
   - Step 1: tell the `knowledge-transfer` subagent to edit files ONLY under the `WORKTREE:` path.
   - Step 3, point 4: make the plan's Tracker edit in `<worktree>/.caddis/plans/<feature>.md`, and write
     any new parking-lot item under `<worktree>/.caddis/parking-lot/`, not in this checkout.
   - Step 4: skip `caddis_tidy.py --apply` (report `skipped: shared checkout`).
   - Step 6: retired; nothing to skip (row 8 reports `skipped: retired (see the 3-store model)`).
   - Step 6b: skip `session_state.py prune` (report `skipped: shared checkout`).
   - Step 6c: run `--reindex` in the worktree (it edits the tracked `DOC-MAP.md`).
   - The relay stays in this checkout: `.caddis/relay/` is local and gitignored.
   After Step 6c, run:
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_docs_pr.py" finish --worktree <path> --title "docs(handoff): <name> session notes" --body "Handoff doc edits from a shared checkout."
   ```
   It commits only the worktree's changed files, pushes, opens a PR, and prints `PR: <url>` and one
   `FILE: <path>` line per file (or `PR: none` when nothing changed). It always removes the worktree, and
   it never merges. On a failure it prints `PATCH: <path>` with the edits; report that path. Put the
   `PR:` line and the file list in your final report, under `Docs PR needed:`.

## Checklist
The handoff is a fixed checklist. Every row ends as `done`, `skipped: <reason>` or `failed: <error>`, and
Step 8 prints all 13 in this order. Never drop a row from the report, even when its step did not apply.
Rows 3 and 8 are retired (the 3-store model, 21 Oct 2026): they stay in the list so the row numbers and the
13-row report do not move for a fleet that mixes caddis versions, and each always reports
`skipped: retired (see the 3-store model)`. A later release removes them with their scripts.

| # | Row | What it is | Shared checkout (Step 0) |
|---|---|---|---|
| 1 | `knowledge-transfer` | Step 1 | edits only in the Step 0 worktree |
| 2 | `plan-tracker` | the plan's Tracker row (Rules) | edit in the Step 0 worktree |
| 3 | `open-work-row` | retired: always `skipped: retired (see the 3-store model)` | never runs |
| 4 | `relay` | Step 3: the relay, written from scratch with current state only | the relay is local; runs |
| 5 | `tasks-file` | Step 3c | runs |
| 6 | `kb-index` | Step 6c: refresh the KB index | in the Step 0 worktree |
| 7 | `violations-report` | Step 6c: report standing violations, each with a one-line fix command | runs (report only) |
| 8 | `todo-reconcile` | retired: always `skipped: retired (see the 3-store model)` | never runs |
| 9 | `usage-record` | Step 6b: `session_state.py usage` | runs |
| 10 | `tidy-apply` | Step 4: `caddis_tidy.py --apply` | `skipped: shared checkout` |
| 11 | `state-prune` | Step 6b: `session_state.py prune` | `skipped: shared checkout` |
| 12 | `prune-list` | Step 6b: `caddis_tidy.py --prune`, list only | runs (lists, never applies) |
| 13 | `handover-check` | Step 5 | runs |

`tidy-apply` and `state-prune` run only on `SHARED: no`. Handoff never runs
`caddis_tidy.py --prune --apply` on its own, in any checkout; only the user can ask for it (Step 6b). In a
shared checkout the report also lists every tracked file Step 1 changed, under `Docs PR needed:`.

## Step 1 — capture learnings FIRST (knowledge-transfer)
**Before** gathering git signals or writing relay.md, decide on `knowledge-transfer` — and the default
is to run it.

- **Trigger (default ON):** if this session's `git diff` touched any code or config, OR you debugged
  anything / proved a non-obvious behavior → you **MUST** dispatch the `knowledge-transfer` subagent first.
- **Skip ONLY if** the session was purely read-only, design/planning, or discussion — nothing was built,
  fixed, or proven. When in doubt, dispatch. "I already wrote some docs by hand" is **not** a reason to
  skip — the subagent routes/consolidates across the right files and catches what you'd miss.
- It writes durable findings (root causes, workarounds, constraints, rejected approaches) into the right
  AGENTS.md (the canonical rules file) / instructions / runbooks. Docs only — never code.
- **Record the outcome** in relay.md's `## Learnings captured` line (below). A skip must state its reason.

## Step 2 — gather verified signals (don't guess)
```
git status --short
git branch --show-current
git log --oneline -5
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_inventory.py"          # what EXISTS — do not compose this from memory
```
Then read the active plan in `.caddis/plans/` (falling back to legacy `.github/plans/` if present) and its tracker.

**Read the inventory before writing anything.** It enumerates plans, PRDs, prompts, handoffs, KB
notes, the parking-lot backlog, open comms, every script and its purpose, and any generated artefact
committed before its generator last changed. Paste the parts a next session needs; do not retype
them from memory.

**Why this step is mechanical.** A handover used to be composed from what the outgoing session
remembered, so it was only ever as complete as that memory. Bringing one successor session to a usable state took
nine corrective round trips and the user caught six of them — including *"the handover listed no
reports, documents, KB notes or scripts"*. None of those are judgement calls; every one is a
directory listing. An agent recalls **what it did**; a generator enumerates **what exists**, and
those are different sets. Your judgement is still needed for what matters and what to do next —
that half cannot be derived and is the only half you should be writing.

**Crash / interrupted-work check.** Cross-check the tracker against `git status` + `git log`: if a phase is
marked in-progress but has **uncommitted changes** (work left mid-flight), or a phase is marked done with
**no commit** to back it, the last session was interrupted. Say so explicitly in `## Next step` ("resume
mid-phase N — `<files>` left uncommitted; re-run its tests first") so the next session doesn't assume a
clean phase boundary and lose or double-do the work.

**Digression check.** If this session abandoned a mid-flight plan for a *different* one (relay.md or the
tracker shows plan A in progress, but the work moved to plan B), suggest the user run `/digress` to park
plan A on the workstream stack — so its exact resume point survives and `/catchup [name]` can pop it back later.

## Step 2b — was any of it the harness?

<!-- shared:harness-friction-question — keep byte-identical across commands; a test pins it -->
**One question, asked here because here is where you are already reflecting.** The observations
that reach caddis today are the ones someone happened to recall days later — so small, frequent
friction never arrives, which is exactly the friction worth fixing.

If a command was awkward, a gate fired wrongly, a doc sent you the wrong way: park it against the
harness, not this repo.

```
/caddis:park --harness <what was awkward, and what you expected>
```

Nothing to say is the normal answer. Say nothing and move on — this must not become a ritual.
<!-- /shared:harness-friction-question -->

## Step 3 — write the resume doc (overwrite) with exactly these sections
Write the relay from scratch with the current state only. Never append to the old text: git keeps the
history, and the relay has a 4,000-character budget (`caddis_budget.py`).

> **Where to write:** this session's own workstream relay, `.caddis/relay/<name>.md`, through the
> locked script — never with a plain file edit, which would skip the conflict check. `.caddis/relay.md`
> is a generated index of all workstreams; do not write it by hand.
>
> Your session id is printed at session start as `[caddis] this session's id: <id>`; use it for
> `session_id` and `--session-id`. Never guess one: a wrong id disables session matching.
>
> 1. **Name the workstream** (active plan's `feature`, else the branch; the script prints nothing
>    on the default branch with no plan — run `caddis_workstreams.py list` (`python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_workstreams.py" list`) to show existing workstreams, then ask the user which one to use or for a short name):
>    `python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_workstreams.py" resolve --plan <feature> --branch <branch> --default-branch <main>`
> 2. **Legacy repo:** if `.caddis/relay.md` exists and does not start with
>    `<!-- caddis-workstream-index-v1 -->`, or an old `/digress` stack `.caddis/workstreams.json`
>    exists, run `caddis_workstreams.py migrate-legacy` once first.
>    It backs up the old file and stops without deleting anything on a conflict; report a conflict
>    to the user and stop.
> 3. **Read the stored version's hash** before you compose: `caddis_workstreams.py hash <name>`
>    (prints `none` for a new workstream).
> 4. **Place every open item in its store (the 3-store model).** An open item lives in the store that
>    matches how long it lives:
>    - **This session's own tasks:** the native task list. Step 3c saves it to
>      `.caddis/relay/<name>.tasks.md`, a snapshot that the next handoff replaces. It is never a backlog.
>    - **An item that must outlive the next handoff** (an owner decision, deferred work, a watch item):
>      file it with `/caddis:park`, once, and name its slug in the relay's `## Open questions / blockers`.
>      Park only work we will do later (`park.md` Step 1). A parking-lot file is tracked, so in a shared
>      checkout (Step 0) write it in the Step 0 worktree.
>    - **The order of work:** the plan Tracker and the roadmap (below). Set the Tracker row of each phase this
>      session finished (Rules).
>    Row 3 (`open-work-row`) is retired: report it exactly as `skipped: retired (see the 3-store model)`.
>    The `.caddis/open-work.md` and `.caddis/todo-list/` stores are retired. Never write them. A repo that
>    still holds an old file keeps it as its own document; caddis no longer reads or writes it.
>    **Order of work:** when the repo has a roadmap (`caddis_roadmap.py list` prints a slug), the
>    roadmap on origin is the order of work. Write the relay's "Next step (exact)" as
>    `next: top open item of roadmap <slug> (caddis_roadmap.py status --roadmap <slug>)`. Never copy a
>    list of open items into the relay.
> 5. **Write** the relay below to a temp file, then
>    `python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_workstreams.py" put <name> <temp-file> --require-status --expected-hash <hash>`.
>    It refuses a relay whose last line is not a valid status line (see "Programme triggers" below).
>    Exit 1 also means another session changed the relay since step 3: it prints the diff and writes
>    nothing. Show the diff, merge by hand, and retry with the new hash. Never force it.
> 6. **Refresh the index:** `caddis_workstreams.py render-index --session-id <id> --branch <branch>`.
>
> (Source checkout: `scripts/caddis_workstreams.py`.) A repo still on the pre-rename `.claudster/`
> won't see this relay until it's converted — `/caddis:migrate-dir` does that.

```markdown
---
type: relay
workstream: <name>
branch: <branch>
plan: <plan file name, or empty>
session_id: <session id>
generated:
  by: <model>
  at: <ISO time>
---

# Relay — <feature>
**Updated:** <ISO timestamp>

## Current workstream
<Active plan path + which phase. One line on the goal.>

## Done (this session / across sessions)
- <evidence-backed bullet — cite file/commit, only what's actually complete>

## Next step (exact)
<The single next action. Include the command/phase. Add a fallback if blocked.>

## Read first on resume
Paths are relative to the repo root.
- `<path>` — why it matters
- `.caddis/plans/<feature>.md` — the plan + tracker

## Validation state
<Commands run this session and their result: pass / fail / not-run. Be honest.>

## Open questions / blockers
<Decisions needed, ambiguities, anything unverified. "None" if truly none. An item that must outlive the
next handoff is filed with `/caddis:park`: name its slug here, never copy its text.>

## Learnings captured
knowledge-transfer: <✓ ran → files written | ✗ skipped → reason>

## Resume prompt
\`\`\`
Read .caddis/relay/<name>.md, then the plan it points to. Continue from <phase/step>. Next action: <exact>.
Load every row of .caddis/relay/<name>.tasks.md with TaskCreate.
\`\`\`
(Keep the `Load every row` sentence only when Step 3c wrote `.caddis/relay/<name>.tasks.md`.)

STATUS: <CONTINUE | OWNER-GATE <P>-OG<n> | BLOCKED <owner> | FAILED <reason>>
```

## Programme triggers

Small work that does not meet a trigger skips its block.

**Trigger: Always.** The relay ends with a status line, the last non-empty line, and it is exactly one of `STATUS: CONTINUE`, `STATUS: OWNER-GATE <P>-OG<n>`, `STATUS: BLOCKED <owner>` or `STATUS: FAILED <reason>`. In Step 3, point 5, write the relay with `python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_workstreams.py" put <name> <temp-file> --require-status --expected-hash <hash>` instead of `write` (in short: put --require-status), with the same hash Step 3 read, so a peer's newer relay is never overwritten. It rejects a relay with no valid status line, and renders the index.

## Step 3c - Save the open tasks
The task list dies with the session unless it is saved. Write this session's open tasks beside
the relay:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/session_state.py" tasks-file --session-id <session-id> --relay <name> --root .
```
It reads the `## Tasks` table of `.caddis/session-state/<session-id>.md`, keeps the rows that are
not `done` or `deleted`, and prints `[TASKS] <n> open task(s) -> <path>` or `[TASKS] none open`
(with no open task it deletes an old `.caddis/relay/<name>.tasks.md`). When it wrote a file, the
relay's resume prompt must hold the sentence
`Load every row of .caddis/relay/<name>.tasks.md with TaskCreate.`: Step 5 blocks a relay whose
tasks file exists and is not named. If you wrote the relay before running this, rewrite it with
Step 3, point 5.

## Step 4 — tidy finished artifacts
Flip any plan/prompt's frontmatter `status:` to `done` (or `superseded`) if this session actually
finished it — that is your judgment call; the script below never makes it and never auto-flips
status. In a shared checkout (Step 0), make the `status:` flip in the Step 0 worktree copy of the plan,
never in this checkout. Then run (skip it in a shared checkout, Step 0: it moves tracked files):
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_tidy.py" --apply
```
(falls back to `scripts/caddis_tidy.py` from a source checkout). **If the script is missing,
skip this step** — it degrades open, same as the other machine gates; an older install must not
be blocked by a script it does not have. Include its report in your output. A **collision**
(`done/<name>` already exists) is reported by the script, not fatal — surface it, do not fail the
handoff over it. Exit 2 means a plan is held because its Tracker still has open rows (`held (open Tracker rows): ...` lines, from Phase 3): show those lines; finish, park (`.caddis/parking-lot/<file>.md` in the row) or mark the rows `dropped: <reason>`, or set the plan status back. Do not fail the handoff over it.

After step 4, for each item this session closed (a phase `<plan>#<n>`, a plan slug, or a parking-lot slug), run `mentions` to check whether another relay's Next step still names it:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_workstreams.py" mentions --item "<item>" --except <name>
```
Print a `WARNING:` line per hit (`WARNING: relay <other> still names closed item <item> in its Next step`). Never edit another workstream's relay (`caddis_workstreams.py mentions` only reads).

## Step 5 — check the handover you just wrote

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_gate.py" handover-check --doc .caddis/relay/<name>.md --max-chars 4000
```
(falls back to `scripts/caddis_gate.py` in a source checkout; degrades open when the script is
missing.) **Run it in the repo the handover is about** — a handover describing another repo will
report that repo's paths as missing, which is the tool being right about the wrong question.

It fails when the handover names a file that does not exist. The incoming session has **no other
source** for those paths, so it cannot tell a typo from a real file: one live handover sent an
incoming session looking for a prompt that was never written. Fix what it lists, then re-run.

It also notes any generated artefact committed before its generator last changed. That is advisory,
not blocking — but do not quote a report the note names without rebuilding it first.

## Step 6 — retired (task reconcile)
This step is retired. It used to reconcile the `todo-list/` store, which is retired too (the 3-store model),
so the step does nothing: do not run any script for it. Report row 8 (`todo-reconcile`) as
`skipped: retired (see the 3-store model)`. The script stays in place for older installs only.

## Step 6b — record usage and tidy session state
The Stop hook only writes the session-state file. These two used to run on every turn; they run
here, once:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/session_state.py" usage --session-id <session-id>
python "${CLAUDE_PLUGIN_ROOT}/scripts/session_state.py" prune
```
`usage` finds this session's transcript by its id and appends one token-and-skill record to
`.caddis/usage-log.jsonl`, which `/usage-review` reads. Pass `--transcript <path>` if you know the
path and it is not under the Claude config folder. `prune` keeps the newest 8 files in
`.caddis/session-state/`; run it after Step 6, which reads this session's file. Skip `prune` in a
shared checkout (Step 0). Include the
`[USAGE]` line in your output. Both always exit 0; if the script is missing, skip this step.

Then list old local state (falls back to `scripts/caddis_tidy.py`; skip if missing):
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_tidy.py" --prune
```
It only lists: session-state files older than 7 days, logs over 5 MB to rotate, and (report
only, never deleted) orphan `.lock` files and lane worktrees older than 7 days. Include its report. **Never
add `--apply` yourself**; deleting is the user's choice. If they ask, run `--prune --apply`.

## Step 6c — KB index and standing violations
Both scripts fall back to `claude-harness/scripts/check_doc_coverage.py` and `scripts/caddis_tidy.py` in a
source checkout; a script that is missing is `skipped: <script> not installed`.

Checklist row 6, `kb-index` (in a shared checkout, run it in the Step 0 worktree, before the Step 0
`finish`; it edits `DOC-MAP.md`):
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/check_doc_coverage.py" --reindex
```
Checklist row 7, `violations-report` (all three only report; never fix files here):
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_tidy.py" --check
python "${CLAUDE_PLUGIN_ROOT}/scripts/check_doc_coverage.py"
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_budget.py" check --root . --report
```
`caddis_budget.py` lists each handoff-grown file over its size budget (`OVER <path>: ...; fix: <rule>`); the
`fix:` text is the one-line fix for that row.
List each violation they print with a one-line command that fixes it (for example `/caddis:kb` for an
un-indexed note, or `caddis_tidy.py --apply` for a finished artifact in the wrong folder). A violation is
not a failure of the handoff: the row is `done` when all three ran. If a script is missing, the row is
`skipped: <script> not installed`.

Then, when the repo has a roadmap (`.caddis/roadmaps/`), re-render its page so phases built by hand show too
(best effort, not a checklist row; it writes only under `~/.caddis/roadmap-pages/`, never in this checkout):
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_roadmap.py" render --all
```

## Step 7 — push prompt (interactive only)
If this is an interactive session, ask the user every time — never reuse an earlier answer:
`Push this note for another machine? (y/N)`
Only on an explicit `y` in this session, run:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_relay_git.py" push <name> --user-said-yes
```
It publishes only `.caddis/relay/<name>.md` to `refs/caddis/relay/<name>` — never the branch, the
index or staged files — after the secret filter passes. Report its one-line result. Anything but
`y` means do nothing. Headless runs never ask and never push (the script also refuses headless).
On the other machine, `/catchup <name>` fetches it.

## Step 8 — the checklist report
Print this block, every row filled with `done`, `skipped: <reason>` or `failed: <error>`:

```
=== HANDOFF CHECKLIST ===
1 knowledge-transfer   done | skipped: <reason> | failed: <error>
2 plan-tracker         <same three forms>
3 open-work-row        skipped: retired (see the 3-store model)
4 relay                <same three forms>
5 tasks-file           <same three forms>
6 kb-index             <same three forms>
7 violations-report    <same three forms>
8 todo-reconcile       skipped: retired (see the 3-store model)
9 usage-record         <same three forms>
10 tidy-apply          <same three forms>
11 state-prune         <same three forms>
12 prune-list          <same three forms>
13 handover-check      <same three forms>
Shared checkout: yes|no <reason>
```

Then, in a shared checkout, `Docs PR needed:` with the `PR:` line and the file list from Step 0.

Step 9 prints after this report. It is the last output of the handoff.

## Step 9 — print the resume prompt (always the last output)
The owner should never have to ask for the resume prompt. After the checklist report, run:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_fleet.py" resume-block --name <name> --session-id <session-id> --root .
```
`<name>` is the workstream name from Step 3. It reads the relay's `## Resume prompt` block verbatim, and
the session name (`session-state/<session-id>.name` when `whoami` wrote it, else the first 8 characters of
the id). It prints, and you print its output as it is, with nothing after it:
```
=== RESUME ===
Session: <session name> (<session id>)
Workstream: <name>
<the resume prompt, in a fenced block>
Start line:
claude --name <role>-<MMDD>-<HH> '<the resume prompt on one line>'
```
- **Fleet close.** When this handoff runs because a peer sent `FLEET CLOSE from <coordinator>`, add
  `--fleet`. The Start line is then `Start line: from the restart sheet`: the restart sheet is the only
  start line in a fleet close. The `FLEET-ACK` reply is a separate message and does not change.
- **Exit 1** (no `## Resume prompt` block, or no relay) prints nothing on stdout. The handoff is not
  complete: fix the relay (Step 3, point 5) and run the command again. Never write the block by hand.
- Workstream with no `whoami` record: the new name uses the workstream name as its role. Pass
  `--role <role>` to set another.

## Rules
- **One next action, by priority ladder.** `## Next step` names exactly ONE action — not a menu. Pick it in
  order: (1) interrupted mid-phase work → finish + commit it; else (2) the active plan's next not-started
  phase; else (3) the top open question/decision. Everything else is context, not the next step.
- Only verified facts and real paths. Mark anything unconfirmed as `Unknown`.
- Update the plan's tracker rows too (status + last commit) — relay and tracker must agree. In a shared
  checkout, edit the Tracker in the Step 0 worktree, never in this checkout.
- Don't commit unless asked. Report which `.caddis/relay/<name>.md` was written and the one next action.
- **Prune the Done section — two rules, both apply:**
  1. **Merge-based:** Phases already merged to `main` (confirmed by a tag or commit) must be compressed
     to a single line: `- **RW-N**: merged to main as vYYYY.MM.DD.N (<commit>) ✅`. Only the current
     in-progress phase keeps detailed bullets.
  2. **Count-based:** The Done section must contain at most **8 bullets total** after writing. If there
     are more, collapse the oldest into one summary line:
     `- [N prior milestones — see git log for full history]`
     Keep the 8 most recent bullets below it.
  Target: the relay stays at most 4,000 characters (handover-check enforces it). inject_relay.py caps injection at 120 lines as a
  safety net, but the file itself should never reach that ceiling.
