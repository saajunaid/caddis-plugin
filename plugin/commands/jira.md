---
description: Jira for a plan — read the Epic, run the human-gated Q&A loop, sync one Story per phase or per milestone, move issues through the workflow, set up a Jira dev dashboard
argument-hint: <check | read KEY | qa-draft | qa-post | qa-pull | qa-status | sync-stories | transition | transition-milestone | dashboard-setup> [args]
stage: plan
---

# /jira — the Epic, the Q&A loop and the Stories in Jira

Jira holds the demand (the Epic), the open questions and the development Stories. caddis talks to it through one
script, `caddis_jira.py`. Run every step with the stable launcher:

```
python "<home>/.caddis/bin/caddis_run.py" caddis_jira.py <command> [args]
```

The request is **$ARGUMENTS**. With no argument, run `check`, then ask which step the user wants.

## Rules that never bend

- **Strictly opt-in.** A plan with no `jira_epic:` (or `jira_epic: none`), a hotfix and a standalone PR never need
  Jira. Every command that takes `--plan` prints `SKIPPED: no jira_epic` and exits 0 for such a plan.
- **Stories live in Jira, not GitHub.** Never create GitHub Issues for development stories.
- **Confluence holds architecture only** (HLA, LLD, DB catalog). Never write stories or progress there.
- **Issue type:** `Story` by default. A plan whose Epic holds Tasks sets `jira_issue_type: Task` (or the alias
  `jira_story_type: Task`) in its frontmatter; `--issue-type <type>` beats both for one run.
- **Granularity:** one Story per phase by default. A plan that would flood Jira with 10 to 15 tiny tickets sets
  `jira_granularity: milestone` (or a run passes `--granularity milestone`, the alias `--by-milestone`): then one
  Story stands for each deliverable milestone of the plan's `## Tracker` (its `Milestone` column).
- **Component is optional.** Many Jira projects have no components. It is sent only when `--component <name>`
  (repeat it, or use commas) or `jira_component:` (a name or a list) names one. When it is unset, `components` is
  left out of every request, never sent empty. `--component none` unsets the plan's value for one run.
- **Nothing private goes to Jira.** No personal data, secrets, host names, internal URLs, file paths, SQL or table
  names in a question or a Story. The leak lint blocks them; reword the text, never bypass the lint.
- **A person approves every Q&A post.** `qa-post --approve` is a human step. It is refused whenever
  `CADDIS_HEADLESS` is set. Never approve a hash for the user, and never run `--approve` in an unattended run.
- **Look before you write.** Run `sync-stories --dry-run`, `transition --dry-run` and the `dashboard-setup` preview
  first and show the output. caddis never deletes a Jira issue, filter or dashboard.
- The keys come from the environment or `~/.caddis/keys.env`: `JIRA_URL` (https, with the server context path such
  as `/jira` on Data Center), `JIRA_TOKEN`, and for Cloud `JIRA_MODE=cloud` and `JIRA_EMAIL`. Never print a token.

## Steps

1. **Check the login.** `check` prints `mode`, `version` and `authenticated: yes`. A 3xx answer means `JIRA_URL`
   misses the context path.
2. **Read the Epic.** `read <KEY> --children --discover-schema` shows the status, the transitions, the child counts
   and the field ids (Epic Link, Story Points, Acceptance Criteria). `epic --plan <path>` prints the plan's Epic.
3. **Ask the open questions (Q&A loop).**
   1. `qa-draft --epic <KEY> --question "..." [--question "..."]` writes the ledger `.caddis/qa/<KEY>.yaml` and the
      draft `.caddis/qa/<KEY>-round-<N>.draft.md`. Ids `Q1`, `Q2`, ... are never reused. At most 7 open questions
      in a round.
   2. The user edits the draft in an editor: reword, add `### NEW`, delete a question, or mark it `State: PARKED`,
      `State: DEFAULTED` with `Default: ...`, or `Blocking: no`.
   3. `qa-post --epic <KEY> --round <N>` shows the exact comment and `APPROVE_SHA256`. It sends nothing. Show the
      preview to the user.
   4. The user reads the preview and runs `qa-post --epic <KEY> --round <N> --approve <hash>` (the 8-character
      prefix or the full hash). An edit after the preview changes the hash, and the old one is refused.
   5. `qa-pull --epic <KEY> [--promote-decisions]` reads the replies (`Q1: ...` lines) into the ledger. A reply with
      no `Q<n>` tag is flagged `NEEDS CONFIRMATION`, never guessed: show it to the user.
   6. `qa-status --epic <KEY> --gate` (or `--plan <path> --gate`) exits 0 only when no blocking question is open.
4. **Sync the Stories.** `sync-stories --plan <path> --dry-run` lists one row per plan phase: `CREATE`, `UPDATE`,
   `UNCHANGED`, `BLOCKED` (leak lint) or `CONFLICT` (two issues claim one phase). Show it. Then
   `sync-stories --plan <path>` writes: summary `[<plan> P<n>] <title>`, Goal and Exit gate in the description, the
   Exit gate as Acceptance Criteria when the field is on the create screen, Story Points from the phase risk, the
   Epic link, and the label `caddis-<plan>-p<n>`. It writes `**Jira Story:** <KEY>` under each new phase heading.
   A re-run updates; it never duplicates.
   - **By milestone.** `sync-stories --plan <path> --by-milestone --dry-run` (or `jira_granularity: milestone`) groups
     the phases by their Tracker `Milestone` cell and plans one row per milestone: summary
     `[<plan> milestone <ID>] <title>`, the milestone's phases and their exit gates in the description, Story Points
     from the riskiest phase, and the label `caddis-<plan>-m-<milestone>`. Phases with no milestone share one
     plan-level Story (`caddis-<plan>-m-plan`). A plan with no milestone at all is an error with `--by-milestone`,
     and one plan-level Story when only the frontmatter asks. Each phase of a milestone gets the same
     `**Jira Story:** <KEY>` line, so one Story can be linked from many phases and PRs. It never deletes a Story.
     `caddis_gate.py gate2` reads `jira_granularity:` and `jira_component:` from the plan only (not the command line):
     set `jira_granularity: milestone` in the plan, or the gate expects one Story per phase.
   - **With a component.** `sync-stories --plan <path> --by-milestone --component Billing` checks the name against the
     project's components (a name Jira does not know is exit 4), sets `components` on a new Story and adds a missing
     component to an existing one. It never removes a component a person set.
5. **Move an issue.** `transition <KEY> --to "<status>" --dry-run` names the transition; without `--dry-run` it moves
   the issue. Add `--fix-version <version>` to set the release version too. Re-running it is a no-op.
   When a milestone is delivered, move its single Story:
   `transition-milestone --plan <path> --milestone <ID> --to "<status>" --fix-version <version> --dry-run`
   finds the Story by its label `caddis-<plan>-m-<milestone>` under the plan's Epic (else by the key stamped on its
   phases), sets the fix version and moves it. Without `--dry-run` it writes; `NOT SYNCED` (exit 1) means run
   `sync-stories --by-milestone` first.
6. **Set up a dev dashboard.** `dashboard-setup` builds four saved JQL filters and a dev dashboard for any scope. It
   needs at least one selector, and they combine with AND: `--project <KEY>`, `--component <NAME>` (optional, repeat
   or use commas), `--epics <K1,K2>` (the issues under those Epics: `"Epic Link" in (...)` on Data Center,
   `parent in (...)` on Cloud), `--label <LABEL>`, `--jql "<clause>"` (no ORDER BY; it must be balanced and is
   wrapped in parentheses). Every value is checked and quoted. Examples:
   - `dashboard-setup --project PROJ --epics PROJ-1,PROJ-2` (no component)
   - `dashboard-setup --project PROJ --component Billing`
   - `dashboard-setup --jql "labels = release-train AND issuetype = Story" --name "Release train"`
   The filters are `<name>: All Deliverables`, `Active / In Progress`, `Delivered by Fix Version` and
   `Blocked / Waiting`. `--name` sets the title prefix (default `PROJ - Billing`, `PROJ`, or `Engineering`).
   `--share private|project|global` is private by default, so nothing leaks to other projects.
   1. **Preview.** `dashboard-setup <selectors>` (or `--dry-run`) only reads Jira. It prints the four filters with
      their JQL (`CREATE`, `UPDATE` or `UNCHANGED` by exact name), the dashboard plan, and `APPROVE_SHA256`. Show it.
   2. **Approve.** A person runs `dashboard-setup <the same selectors> --approve <hash>`. A changed selector or name
      gives a new hash and the old one is refused. `--approve` is refused whenever `CADDIS_HEADLESS` is set: never
      run it for the user or in an unattended run.
   3. **Result.** It creates or updates the filters (a re-run changes nothing that is unchanged, and never deletes),
      then tries the dashboard and its four gadgets: Status Breakdown, Status x Fix Version Matrix, Active Work and
      Blocked / Waiting. Many Jira servers lock the dashboard and gadget calls. Then it still exits 0 with
      `dashboard_mode: blueprint_fallback`, keeps the filters, and prints a **Dev Dashboard Gadget Blueprint**: each
      filter id, link and JQL, and the four gadgets with their settings, for a person to add by hand.

Stop at the first step that does not exit 0 and report its output.

## Exit codes

| Exit | Meaning | What to do |
|---|---|---|
| 0 | Done, or `SKIPPED: no jira_epic` | Report the output. |
| 1 | Jira refused, the gate is closed, the leak lint blocked, or the approval does not match | Show the lines; fix the text or ask the user. |
| 3 | Not configured or a network failure | Name the missing key; never print its value. |
| 4 | Bad input (key, plan, draft, issue type) | Show the error and the fix. |
