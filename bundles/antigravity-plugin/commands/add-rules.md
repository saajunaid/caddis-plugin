---
description: Create canonical rules for ANY folder — write <folder>/AGENTS.md (from the folder template) + a <folder>/CLAUDE.md @import shim. For folders the stack-map generator doesn't cover.
argument-hint: <folder> [one-line purpose]
---

# /add-rules — add canonical rules to a folder

Create a rules file for a folder the deterministic generator doesn't cover (stack-map only writes
`src/`, `frontend/`, `tests/`). `AGENTS.md` is the **canonical** rules file; `CLAUDE.md` is a thin
`@AGENTS.md` import shim beside it. This command writes both.

Context / args: **$ARGUMENTS** — the first token is the target `<folder>` (repo-relative); the rest is
an optional one-line purpose.

## Steps

1. **Parse args.** `<folder>` = first token; `[purpose]` = the remainder (may be empty). If `<folder>`
   is missing, ask which folder and stop. Resolve `<folder>` relative to the repo root; if it doesn't
   exist, say so and stop (create the folder first, or fix the path).

2. **Refuse to clobber.** If `<folder>/AGENTS.md` already exists, STOP — do **not** overwrite it. Point
   the user at the `knowledge-transfer` / `claude-md-curator` agents for *updating* existing rules (they
   target ANY existing `AGENTS.md`). This command only *creates* new folder rules.

3. **Seed from the folder.** Read a representative sample of `<folder>`'s contents (a few files, the
   most-imported modules, any local README) to learn the real conventions, layering, naming, test
   pattern, and non-obvious gotchas. Combine that with `[purpose]`. Do not invent rules the code
   doesn't support; prefer a short honest file over a padded one.

4. **Write `<folder>/AGENTS.md`** from the folder template `claude-md/folder-agents.md.tmpl` (resolve
   `<harness-root>` the same way `/setup-project-ai` does: `${CLAUDE_PLUGIN_ROOT}/claude-md/…` for a
   plugin install, else the `claude-harness/claude-md/…` checkout path). Fill `{{FOLDER}}` and
   `{{FOLDER_PURPOSE}}`, then replace the `<…>` section stubs (Conventions, Gotchas / non-obvious,
   Adding functionality) with what you learned in Step 3. Keep it lean (the ~80-line budget applies).

5. **Write `<folder>/CLAUDE.md`** as the exact 2-line shim (nothing more — never put rules here):
   ```
   # Folder conventions — canonical in AGENTS.md (imported below; Claude Code inlines it)
   @AGENTS.md
   ```

6. **Report + remind.** Show the two files written. Remind that ongoing updates flow through the
   `knowledge-transfer` (end-of-session capture) and `claude-md-curator` (periodic prune) agents — they
   match ANY existing `AGENTS.md`, so no per-folder upkeep command is needed. Codex and Antigravity
   (`agy`) read the `AGENTS.md` directly; Claude Code inlines it via the `CLAUDE.md` shim.
