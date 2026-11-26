---
name: jira
description: Jira for a plan — read the Epic, run the human-gated Q&A loop, sync one Story per phase, move issues through the workflow
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
- **Nothing private goes to Jira.** No personal data, secrets, host names, internal URLs, file paths, SQL or table
  names in a question or a Story. The leak lint blocks them; reword the text, never bypass the lint.
- **A person approves every Q&A post.** `qa-post --approve` is a human step. It is refused whenever
  `CADDIS_HEADLESS` is set. Never approve a hash for the user, and never run `--approve` in an unattended run.
- **Look before you write.** Run `sync-stories --dry-run` and `transition --dry-run` first and show the output.
  caddis never deletes a Jira issue.
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
5. **Move an issue.** `transition <KEY> --to "<status>" --dry-run` names the transition; without `--dry-run` it moves
   the issue. Add `--fix-version <version>` to set the release version too.

Stop at the first step that does not exit 0 and report its output.

## Exit codes

| Exit | Meaning | What to do |
|---|---|---|
| 0 | Done, or `SKIPPED: no jira_epic` | Report the output. |
| 1 | Jira refused, the gate is closed, the leak lint blocked, or the approval does not match | Show the lines; fix the text or ask the user. |
| 3 | Not configured or a network failure | Name the missing key; never print its value. |
| 4 | Bad input (key, plan, draft, issue type) | Show the error and the fix. |
