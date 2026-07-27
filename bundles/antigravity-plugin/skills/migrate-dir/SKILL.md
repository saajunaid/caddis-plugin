---
name: migrate-dir
description: Rename this repo's legacy `.claudster/` artifact dir to `.caddis/` — dry-run first, `git mv` to keep history, merges a straggler dir, rewrites live refs. Opt-in, never automatic.
---

# /migrate-dir — rename `.claudster/` → `.caddis/`

caddis writes its per-repo artifacts (plans, handoffs, kb, relay, usage log, …) to **`.caddis/`**.
Repos created before the rename have **`.claudster/`**. Both work — every reader tries `.caddis`
then `.claudster`, and every writer writes **where the repo already lives** — so this migration is
about consistency, not function. It is **opt-in and never automatic**: renaming a directory under a
concurrent session would move files out from under its in-flight writes.

Context / args: **$ARGUMENTS** — an optional target repo path (default: this repo) and an optional
`--apply` (default is a dry run).

## Step 1 — locate the migrator
It ships with the harness. Try, in order:
- `${CLAUDE_PLUGIN_ROOT}/scripts/caddis_migrate_dir.py` — a plugin install.
- `scripts/caddis_migrate_dir.py` — the harness source repo itself.

## Step 2 — check the tree first (L1: shared worktrees)
```
git -C <target> status --short
```
The migration **refuses a dirty tree** (a rename mixed into unrelated edits is unreviewable, and
these working trees are shared with parallel sessions). If it's dirty: commit or stash first. Never
pass `--allow-dirty` on a tree whose changes you didn't make.

## Step 3 — dry run
```
python <path>/caddis_migrate_dir.py <target>
```
Read the plan it prints. Two shapes:
- **Simple** — only `.claudster/` exists → one `git mv .claudster .caddis` (history preserved).
- **Both exist** — a straggler `.claudster/` was recreated by an out-of-date session → a per-child
  merge into `.caddis/`. Append-only JSONL logs (`usage-log` / `agent-log` / `memory`) are
  **concatenated with the legacy lines first**; directories recurse; anything else that collides is
  reported as a **CONFLICT** and left untouched for a human.

Show the user the dry-run output before applying.

## Step 4 — apply
```
python <path>/caddis_migrate_dir.py <target> --apply
```
It also rewrites `.claudster/…` path references inside the repo's **live** state — `.caddis/relay.md`
and `.caddis/workstreams.json` (parked-workstream plan paths). Historical artifacts (past plans,
handoffs, reviews) are deliberately **not** rewritten: they record what was true then.

Resolve any CONFLICT it reported by hand, then re-run — the command is idempotent.

## Step 5 — verify, then commit
```
git -C <target> status --short          # renames should show as R (history preserved)
python <path>/caddis_migrate_dir.py <target> --check    # exit 0 = no legacy dir left
```
Then run the repo's own gate (its tests, and `check_doc_coverage.py --check` if present) and commit
the rename **on its own**, e.g. `chore(caddis): migrate .claudster/ -> .caddis/`.

**Do not push** a repo that deploys on push without its owner's go.

## Notes
- Also grep the repo for stale refs the migrator leaves alone on purpose:
  `.gitignore`, CI workflows, `.docket/config.json`, and any script hardcoding `.claudster/`.
  Update those by hand in the same commit.
- Repos that haven't migrated keep working indefinitely — the `.claudster` read-fallback is removed
  only after the whole fleet has migrated and soaked.
