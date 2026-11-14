---
description: Publish a plan's phases as development stories to the Jira Epic's Confluence page — one marked section per plan
argument-hint: <plan path>
stage: knowledge
---

# /stories — plan phases as development stories on Confluence

One plan phase becomes one sprint-sized development story. The script writes a "Development stories" table to the
Confluence page whose title is the plan's Jira Epic key, under the page in `confluence_parent`. It writes only the
plan's own marked section. It never changes other page content and never deletes a page. Copying the stories into
Jira is the reader's job: caddis does not call Jira.

## Input

- Usage: `/caddis:stories <plan path>`. The plan path is `$ARGUMENTS`; with no argument, ask for it.
- When no argument is given, find the plan with
  `python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_todo.py" active-plan`.
- The plan frontmatter must hold `jira_epic: <KEY>` and `confluence_parent: <URL of the HLA or HLSA page>`.
- The keys must be in the environment or in `~/.caddis/keys.env`: `CONFLUENCE_URL` (https only) and
  `CONFLUENCE_TOKEN` (a personal access token). Never print, echo or show the token.

## Steps

1. Show the table. Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_stories.py" render --plan <plan path>` and
   show its output to the user.
2. Check the login and the parent page. Run
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_stories.py" check --plan <plan path>`. It makes read-only calls and
   prints `USER:` and `PARENT:` lines.
3. Do a dry run. Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_stories.py" sync --plan <plan path> --dry-run`.
   Show the `ACTION:` and `PAGE:` lines. It writes nothing.
4. Write. Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_stories.py" sync --plan <plan path>`. Report the
   `ACTION:` and `PAGE:` lines, and each `WARN:` line.

Stop at the first step that does not exit 0, and report its output.

## Exit codes

| Exit | Meaning | What to do |
|---|---|---|
| 0 | Synced, or the section is unchanged | Nothing |
| 1 | Confluence refused (HTTP error, a second version conflict) or the markers on the page are broken | Read the message. Broken markers: fix the page by hand |
| 3 | Not configured (no keys, or no `jira_epic` / `confluence_parent`), or the network failed | Add the keys or the fields, or try again later |
| 4 | Bad input: the plan cannot be read, a bad Epic key, or the parent page is on another host | Fix the plan |

## Rules

- The token goes only to the `CONFLUENCE_URL` host. A `confluence_parent` on another host stops the sync before any
  call.
- A sync rewrites the plan's whole section. A phase removed from the plan leaves the table.
- When the stored section has the same hash, the sync writes nothing and makes no new page version.
