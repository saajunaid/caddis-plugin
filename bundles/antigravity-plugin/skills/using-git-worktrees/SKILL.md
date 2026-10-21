---
name: using-git-worktrees
description: "Use when starting feature work that needs isolation from the current workspace, or before executing an implementation plan: creates an isolated git worktree safely."
---

# Using Git Worktrees

A worktree gives one branch its own folder. It shares the repository with the main checkout.

**Branch in place by default.** Run `git switch -c <branch>`. Never create a sibling repository folder.
Use a worktree only when the checkout is not safe to move.

**Announce at start:** "I am using the using-git-worktrees skill to set up an isolated workspace."

## When to use a worktree

Use a worktree when any of these is true:

1. The repo `AGENTS.md` says `Shared checkout: yes` (a dev service serves from it) and your change touches
   served code. A change to `.caddis/` or `docs/` only may use a branch.
2. Another session or agent may be live in the checkout, or you cannot tell. Codex and agy cannot detect
   peers. For them, "cannot tell" means not safe.
3. `git status` shows changes you did not make. Never stash, commit, reset or carry them.
4. Two or more agents edit at the same time. Each editing agent gets its own worktree. The orchestrator
   creates and removes them. Read-only subagents share the checkout and never move HEAD.

If none is true, stop here and use `git switch -c`.

## Create the worktree

1. Fetch: `git fetch origin`.
2. Find the default branch (`main` in most repos): `git symbolic-ref --short refs/remotes/origin/HEAD`.
   It prints `origin/main`. Use the part after `origin/` as `<default>`.
3. Create the worktree from `origin/<default>`, never from the local HEAD, at
   `<worktree root>\<repo>\<short-name>`. Never under `%TEMP%`: Windows cleanup (Storage Sense) can empty it
   and delete a worktree that holds unmerged work. The worktree root is `$env:CADDIS_WORKTREE_ROOT` when set,
   else the `.worktrees` folder beside the main checkout (for `E:\Projects\<repo>` that is
   `E:\Projects\.worktrees\<repo>\<short-name>`). `<repo>` is the main checkout's folder name. The caddis
   script `caddis_worktree_root.py` prints the path; use it so the rule lives in one place:

```powershell
$wt = python "<caddis scripts>\caddis_worktree_root.py" <short-name> --record --purpose "<why>"   # run in the repo; prints the path
git worktree add -b <branch> $wt origin/<default>
```

   `--record` also writes the path to this session's created list (`caddis_created.py`), so `/handoff` can remove the
   worktree later. Always record it, subagents most of all: their tool calls are in a separate transcript that the
   Stop hook does not read. If you create a worktree without the helper, run
   `python "<caddis scripts>\caddis_created.py" record --path <path> --kind worktree --purpose "<why>"` right after
   `git worktree add`.

   `<caddis scripts>` is the `scripts` folder of the installed caddis plugin. Do not create worktrees inside the
   repo. An existing worktree stays where it is: moving it breaks a venv, which keeps absolute paths.
4. State the full path of the worktree. Work only there, and do not switch branches in it.

## Install dependencies fresh

Install inside the worktree. Use the project's own command (`npm ci`, `python -m venv .venv` then
`.venv\Scripts\python -m pip install -r requirements.txt`, `cargo build`, `go mod download`). Call the
venv's own `python`; a bare `pip` can install into the global Python.

Never link `node_modules` or a venv from another folder. Tools that follow the link then change the
shared copy, and a careless delete can follow it too.

## Verify a clean baseline

Run the project tests. If they fail, report the failures and ask before you go on. Then report:

```
Worktree ready at <full-path> (branch <branch>, from origin/<default>)
Tests passing (<N> tests, 0 failures)
```

## Remove it when done

A worktree you create is yours to remove. Do it when the PR merges or the work stops. Remove all three:

1. The worktree.
2. The local branch.
3. The remote branch, but only when its work is merged, or the owner says it is abandoned. If the work
   only paused, keep the remote branch: it can be the only copy.

After a squash merge, compare trees (content), not ancestry, before you delete.

Do not delete a worktree folder by hand or with `rm -rf`: on Windows it can follow a junction into
another folder. Use the `safe-cleanup` skill, or `scripts/caddis_worktree_close.py` after a merged PR.

Check for leftovers with `git worktree list`.

## Red flags

**Never:**
- Create a worktree from the local HEAD or a stale branch.
- Put a worktree in the repo folder or in a sibling of the repo.
- Link `node_modules` or a venv into a worktree.
- Leave a worktree, local branch or merged remote branch behind after the work ends.
- Use a worktree when `git switch -c` is safe.

## Integration

**Called by:**
- **brainstorming** (Phase 4) - when the design is approved and implementation follows
- Any skill that needs an isolated workspace

**Pairs with:**
- **finishing-a-development-branch** - cleanup after the work is complete
- **executing-plans** or **subagent-driven-development** - the work happens in this worktree
