---
name: preload-review
description: Show what loads before the first prompt in every repo (rules, memory index, skills, MCP names) and list what to shorten
---

# /preload-review — what loads before the first prompt

Measure the size of what Claude loads before you type anything: your user rules, the enabled
skills, the MCP server names, and, for every repo under a root folder, the repo rules and the
memory index. The command reads files only. It shows estimates (characters divided by 4), not exact
token counts. It changes nothing unless you say yes.

## Step 1 — find the script

Resolve the script path:
- Plugin install: `${HOME}/.codex/plugins/cache/caddis/caddis-codex/1.3.188/scripts/caddis_preload_review.py`
- harness (caddis) checkout: `scripts/caddis_preload_review.py`

## Step 2 — run it

Run it from the project root:
```
python "<resolved-path>" $ARGUMENTS
```

- With no flags, the root folder is the parent of the current git repo. Pass `--root PATH` to scan
  another folder.
- The script prints Markdown to stdout. It also has `--json`, `--limit-repo-startup N` and
  `--limit-memory N`.
- The script exits 0 always. Cut candidates are advice, not a failure.

## Step 3 — show the output

Show the Markdown output as it is. Then add **one sentence** that names the largest start-up cost
(a repo, the skills or the user rules). Do not repeat every row in prose: the table is the output.

## Step 4 — point to /context

Tell the user to run `/context` once in a session. The script cannot see the exact MCP tool lists,
or skills that do not come from the plugin cache. Compare the `/context` output with the table.

## Step 5 — offer actions only

For each cut candidate, say the one action it names (run `caddis:claude-md-curator`, shorten the
memory index lines, move how-to text into a doc that loads on demand, or turn a plugin off).

**Never edit a rules file, a memory file or a setting without the owner's yes.** Show the change
first. Then ask.

## Step 6 — record the review

After the owner has read the report, run the script again with `--stamp`:
```
python "<resolved-path>" [--root PATH] --stamp
```

This writes `.caddis/.last-preload-review` for the current repo: the review date and a hash of the
enabled plugin set. Then say that the stamp is written.

## Notes

- The stamp file is local and gitignored. It is the only file the script ever writes. Without
  `--stamp` the script writes nothing.
- The SessionStart hook reads the stamp. It prints one line when the last review is more than
  30 days old, or when the enabled plugins changed since then. It prints nothing when both are fresh.
- The script prints only names from `~/.claude.json` and `~/.claude/settings.json`. It never
  prints a value, a URL, an argument or an env var from them.
- Nested `CLAUDE.md` and `AGENTS.md` files load only when Claude works in that folder. The report
  lists them apart and never adds them to the start-up total.
