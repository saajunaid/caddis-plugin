# Investigation: .github Pool Files Polluting Downstream Project Git Trees

**Date:** 2026-04-15  
**Affected repos:** `<org>/project-a`, `<org>/project-b` (and any other project using `caddis-pull`)  
**Status:** Mitigated in affected repos. Extension fix required (see § Recommended Fix).

---

## 1. Symptom

After running `caddis-pull` (or "Update Agent Pool" in VS Code), downstream project repos showed
40–670 modified/deleted files in their git working tree. Most were inside `.github/` — agents,
skills, instructions, etc. that are pool-managed and not meaningful to the project's own source
history.

---

## 2. Root Causes (three compounding changes)

### 2a — `b717e27` (2026-03-24): `caddis-pull` switched from overwrite to wipe-then-copy

**Before:**
```powershell
Copy-Item $src $target -Recurse -Force   # overwrote changed files, left others unchanged
```

**After (`sync.ps1`):**
```powershell
if ($CLEAN_FOLDERS -contains $folder) {
    Remove-Item $dest -Recurse -Force     # ← wipe whole folder first
}
Copy-Item $src $target -Recurse -Force
```

`$CLEAN_FOLDERS = @("agents", "skills", "prompts", "instructions", "tools", "recipes")`

**Intent:** Correct — prevents stale files from lingering when pool renames/deletes an agent or skill.

**Side-effect:** Any project-specific file that lived inside a `$CLEAN_FOLDER` (e.g.
`project-b-frontend.instructions.md`) is silently deleted and shows up as `D` in git status.
Previously those files were untouched.

---

### 2b — `6f42539` (2026-04-04): `agent-docs/`, `handoffs/`, `plans/` added to `POOL_FOLDERS`

**Before:**
```powershell
$POOL_FOLDERS = @("agents", "skills", "prompts", "instructions", "diagrams", "tools")
```

**After:**
```powershell
$POOL_FOLDERS = @("agents", "skills", "prompts", "instructions", "diagrams", "tools",
                  "recipes", "agent-docs", "handoffs", "plans")
```

**Intent:** Correct — these folders contain reference content the pipeline agents rely on
(`agent-docs/ARTIFACTS.md`, `plans/backlog/`, etc.) and need to be kept in sync.

**Side-effect:** `caddis-pull` now overwrites project-specific pipeline artefacts in those
folders (e.g. `plans/backlog/project-b-v4-mockup.md`). Files that don't exist in the pool
survive, but any pool-side README or placeholder gets written unconditionally. These folders
were previously "yours only" — they never changed after initial install.

---

### 2c — Large content batch (2026-04-04 → 2026-04-14): Biggest pool growth ever

In the preceding 12 days, ~10 pool commits landed:

| Commit | Impact |
|--------|--------|
| `6ef1d26` | recipes/ added, 4 agents updated, instructions updated |
| `436b30d` | 3 new skills, windows-deployment, data-contracts instructions |
| `203863e` | Preflight agent, 5 new skills, 17 agent updates, orchestrator overhaul |
| `e80281c` | Dark-mode token fix in instructions |
| `fa0f40f` | data-contract-pipeline skill expanded |
| `797c0ed` | Recipe discovery, onboard-project, validation-discipline instruction |
| `9a1e211` | browser-first agent + planning notes |
| `92b1c59` | 4 new skills (responsive-mobile-native, ci-cd-pipeline, caching-patterns, windows-deployment), 1688 insertions |
| `2d13f5a` | terse-response instruction added |

**Before this period, pool updates were incremental (a few files at a time).** The April
burst was the largest single growth wave the pool had ever seen. When `caddis-pull` ran in
a downstream repo immediately after pulling this batch, all three factors hit simultaneously:
wipe-copy semantics × more folders touched × many new/changed files = 40–670 dirty files.

---

## 3. Why .github Was Tracked in the First Place

Two legitimate reasons:

1. **Pipeline artefacts belong to the project** — `pipeline-state.json`, `project-config.md`,
   `agent-docs/ARTIFACTS.md`, `plans/backlog/*.md` etc. are project-specific state that must
   survive across machines and should be in source control.

2. **MCP server workspace discovery** — `server.py` walks up the filesystem looking for a
   `.github` directory to find the workspace root. It does **not** read the git index; it
   just needs the directory to exist on disk. So tracking `.github` in git was never strictly
   required for runtime — it was largely a side-effect of "track everything by default".

---

## 4. Mitigation Applied to Affected Repos

For both `project-a` and `project-b` the following was applied manually:

### Step 1 — Append to `.gitignore`

```gitignore
# ── Selective .github Tracking ───────────────────────
.github/*
!.github/agent-docs/
!.github/agent-docs/**
!.github/plans/
!.github/plans/**
!.github/copilot-instructions.md
!.github/project-config.md
!.github/pipeline-state.json
```

### Step 2 — Remove all `.github` from git index, re-add only exceptions

```powershell
git rm -r --cached .github
git add -f .github/agent-docs
git add -f .github/plans
git add -f .github/copilot-instructions.md
git add -f .github/project-config.md
git add -f .github/pipeline-state.json
git commit -m "chore(git): track only selected .github paths"
git push origin main
```

**Result:** Pool files (`agents/`, `skills/`, `instructions/`, `tools/`, `recipes/`, etc.)
are ignored by git permanently. `caddis-pull` can still update them locally for Copilot to
use — they just never show up as dirty in the git tree again.

**Rollback branches** exist on both repos at
`backup/pre-github-selective-track-<timestamp>`.

---

## 5. Recommended Fix — Extension (`junai-vscode/src/extension.ts`)

The extension should make this selective tracking the **default** for every project it
initialises or updates. No project should ever need the manual steps in § 4 again.

### 5a — Add `scaffoldSelectiveGithubGitignore(workspaceRoot: string): void`

Insert the function alongside the other `scaffold*` helpers (around line 1960 in
`extension.ts`):

```typescript
/**
 * Ensures the project's .gitignore contains the junai selective-tracking block
 * for .github/.  Pool-managed dirs (agents/, skills/, instructions/, etc.) are
 * ignored; project-owned dirs (agent-docs/, plans/) and key root files are
 * kept tracked.
 *
 * Idempotent — safe to call on every init/update; skips if the block is
 * already present.
 */
function scaffoldSelectiveGithubGitignore(workspaceRoot: string): void {
    const MARKER = '# ── junai: selective .github tracking ──';
    const gitignorePath = path.join(workspaceRoot, '.gitignore');

    // Skip if we already wrote this block
    if (fs.existsSync(gitignorePath)) {
        const existing = fs.readFileSync(gitignorePath, 'utf8');
        if (existing.includes(MARKER)) { return; }
    }

    const block = [
        '',
        MARKER,
        '.github/*',
        '!.github/agent-docs/',
        '!.github/agent-docs/**',
        '!.github/plans/',
        '!.github/plans/**',
        '!.github/handoffs/',
        '!.github/handoffs/**',
        '!.github/copilot-instructions.md',
        '!.github/project-config.md',
        '!.github/pipeline-state.json',
        '',
    ].join('\n');

    fs.appendFileSync(gitignorePath, block, 'utf8');
}
```

> **Note on `handoffs/`:** Not currently kept tracked in the manually-fixed repos, but
> included here because `handoffs/` is a project artefact folder (`POOL_FOLDERS` in
> `sync.ps1`). If you want to exclude it (pool-default READMEs only), remove those two
> lines.

### 5b — Call it in all three init/update paths

In `cmdInit` (around line 596), `cmdInitPool` (around line 1163), and `cmdUpdatePool`
(around line 1083) — add one call **before** the `gitCommitPoolUpdate` step:

```typescript
scaffoldSelectiveGithubGitignore(workspaceFolders[0].uri.fsPath);  // ← add this
git.result = gitCommitPoolUpdate(workspaceFolders[0].uri.fsPath, ...);
```

For `cmdInitPool` (which doesn't currently have a git commit step), call it after
`writeWorkspacePoolVersion(...)`:

```typescript
writeWorkspacePoolVersion(context, githubDir);
scaffoldSelectiveGithubGitignore(targetFolder);  // ← add this
```

### 5c — `gitCommitPoolUpdate` — no changes needed

The function already stages `.github/agent-docs`, `.github/plans`, and `.github/handoffs`
explicitly (line ~2001). Once `.gitignore` ignores the other pool dirs, `git add` on
an ignored path is silently a no-op — so `agents/`, `skills/`, etc. just don't get
staged anymore. The function is already correct; it just needs the `.gitignore` to be
in place first.

---

## 6. Impact Assessment

| Concern | Impact |
|---------|--------|
| Extension install / update behaviour | ✅ No change — pool still deployed in full to disk |
| Copilot agents / skills / instructions in VS Code | ✅ No change — files present locally, Copilot reads from filesystem not git |
| MCP server workspace discovery | ✅ No change — looks for `.github/` directory on disk, not in git index |
| `pipeline-state.json` read by MCP | ✅ Tracked — explicitly kept as git exception |
| `.github/tools/` (pipeline-runner, MCP server) | ⚠️ No longer tracked in git — but deployed fresh by `caddis-pull`/extension on every machine. Acceptable if every dev machine runs `Update Agent Pool` before using the pipeline |
| `caddis-pull` (sync.ps1) wipe semantics | ✅ Unchanged — pool still overwrites managed folders; git just stops caring |
| Downstream repo CI/deploy (Gitea Actions) | ✅ Confirmed zero `.github` references in both `ci.yml` and `deploy.ps1` |

---

## 7. Files Changed Summary

| Repo | File | Change |
|------|------|--------|
| `project-a` | `.gitignore` | Selective `.github` tracking block + `.claude/` ignore appended |
| `project-a` | `.github/**` (670 files) | Removed from git index; 37 project files re-added |
| `project-b` | `.gitignore` | Selective `.github` tracking block + `.claude/` ignore appended |
| `project-b` | `.github/**` (676 files) | Removed from git index; 28 project files re-added |
| `junai-vscode` | `src/extension.ts` | **Not yet changed** — see § 5 above |

### Additional finding: `.claude/` runtime directory

Both repos also had a `.claude/` directory written by the Claude desktop app (agent rules,
session state, etc.) with 568–1297 files. These were untracked but not ignored, causing VS Code
Source Control to expand the whole directory into individual file entries — the source of the
"600 changes" report the user saw.

**Fix applied:** `.claude/` added to `.gitignore` in both repos.

The extension's `scaffoldSelectiveGithubGitignore` function (§ 5) should also append this entry:

```typescript
'.claude/',                          // Claude desktop agent runtime — never commit
```

---

## 8. Quick Reference — What to Track vs. Ignore

| Path | Track in git? | Reason |
|------|--------------|--------|
| `.github/agents/` | ❌ Ignore | Pool-managed, overwritten on every pull |
| `.github/skills/` | ❌ Ignore | Pool-managed |
| `.github/instructions/` | ❌ Ignore | Pool-managed |
| `.github/prompts/` | ❌ Ignore | Pool-managed |
| `.github/recipes/` | ❌ Ignore | Pool-managed |
| `.github/tools/` | ❌ Ignore | Pool-managed (MCP server, pipeline-runner) |
| `.github/diagrams/` | ❌ Ignore | Pool-managed |
| `.github/.junai-pool-version` | ❌ Ignore | Pool-managed metadata |
| `.github/agent-docs/` | ✅ Track | Project artefacts (ARTIFACTS.md, reviews, etc.) |
| `.github/plans/` | ✅ Track | Project implementation plans and backlog |
| `.github/handoffs/` | ✅ Track (optional) | Project handoff notes |
| `.github/copilot-instructions.md` | ✅ Track | Project-specific Copilot context |
| `.github/project-config.md` | ✅ Track | Active project profile |
| `.github/pipeline-state.json` | ✅ Track | Pipeline gate/stage state |
