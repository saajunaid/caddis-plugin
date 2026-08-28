---
name: safe-cleanup
description: Use BEFORE deleting any directory tree, clearing a scratchpad, removing git worktrees, or "tidying up" generated folders - especially on Windows, where a recursive delete that meets a junction or symlink destroys the link's TARGET. Also use when verifying that a Python venv or node_modules survived a cleanup, because pip check and file counts both report healthy on a half-deleted environment.
---

# Safe Cleanup

## Overview

Cleanup looks like the safest thing you do all day. It is the most destructive.

This skill exists because of a real incident: an agent created 31 directory
junctions from throwaway worktrees into live repositories, unlinked them, saw
"31 unlinked, 0 failed", then recursively deleted the parent. A junction it had
never seen survived the scan, the delete followed it, and **five repositories'
development environments were destroyed**. Every verification afterwards said
"intact", because the verification was wrong too.

Two hours of repair. None of it would have happened with the rules below.

## The one-paragraph version

On Windows, `Remove-Item -Recurse` **follows junctions and deletes their
targets**. Enumerating with `-ErrorAction SilentlyContinue` hides the ones you
cannot read. And after the damage, `pip check`, `pip list` and file counts all
report success, because metadata survives while package files do not. So: never
link into somewhere real, never recurse through a link, prefer rename over
delete, and verify by *using* the thing rather than counting it.

---

## RULE 1 - Prefer rename over delete

Rename is atomic. Recursive delete is not: it can fail half way and leave a
directory that looks present and is unusable.

```powershell
Rename-Item -Path $target -NewName ".broken-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
```

In the incident, a venv holding `_greenlet.cp314-win_amd64.pyd` open **refused to
delete** but **renamed fine**. Had the delete been retried or forced, it would
have half-emptied the directory.

Rename first, build fresh alongside, delete the old copy later when nothing holds
it. Disk is cheap. An environment nobody can recover is not.

## RULE 2 - Never recurse a delete through a reparse point

Junctions and symlinks are transparent to `Remove-Item -Recurse`. Deleting a
folder that contains a link to `C:\live\thing` deletes **the contents of
`C:\live\thing`**.

Check first, and **fail if the check itself cannot complete**:

```powershell
$links = @(Get-ChildItem $path -Recurse -Force -Directory -ErrorAction Stop |
           Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint })
if ($links.Count) {
    $links | ForEach-Object { Write-Host "  $($_.FullName) -> $($_.Target)" }
    throw "refusing: $($links.Count) link(s) inside $path"
}
```

`-ErrorAction SilentlyContinue` on that scan is precisely what caused the
incident. A link inside a directory the scanner could not read was skipped in
silence and never appeared in the count. **A scan that cannot see everything must
fail, not shrug.**

To remove a link itself, unlink it - never delete through it:

```powershell
[System.IO.Directory]::Delete($linkPath, $false)   # link only, never the target
cmd /c rmdir "$linkPath"                            # same effect
```

## RULE 3 - Do not create links into live directories

The safest delete is the one with nothing to follow.

If a throwaway workspace needs dependencies, **build them there**, or point the
tool at an absolute interpreter path. Do not junction `<scratch>\.venv` to
`<live-repo>\.venv` for convenience - that is a loaded gun aimed at the repo, and
any cleanup above the link can fire it.

If you must link, remove the link the moment you are done, and never leave one
inside a directory that something else will clean up.

## RULE 4 - Verify by using, not by counting

After any cleanup near an environment, prove it still works. These all LIE on a
half-deleted Python venv, because dist-info metadata survives while package files
are removed:

| Check | Why it lies |
|---|---|
| `Test-Path .venv\Scripts\python.exe` | Proves the interpreter exists. Says nothing about packages. |
| file or directory counts | Metadata directories inflate the count. |
| `pip list` | Reads metadata. |
| `pip check` | Reads metadata. Reported "No broken requirements found" on a venv that could not import fastapi. |
| `pip install -e .` | Reads metadata, calls the package satisfied, **skips it, and reports success**. |

The honest check is whether the interpreter can import what the project declares:

```python
import importlib.util
importlib.util.find_spec("fastapi") is None   # -> True means genuinely missing
```

For node, check that a real entry point resolves, not that `node_modules` exists.

**Map distribution names to import names.** `pyjwt` imports as `jwt`,
`python-ulid` as `ulid`, `python-dotenv` as `dotenv`. A naive audit produces false
positives and will have you rebuilding healthy environments - which is its own way
of causing an outage.

## RULE 5 - Stop what holds the files, or refuse

A running service turns a delete into a **partial** delete - the worst outcome.

Stop named services first. Then check for surviving processes and **refuse rather
than force**:

```powershell
$held = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
          Where-Object { $_.ExecutablePath -like "$venv\*" })
if ($held.Count) { throw "refusing: still held by PID $($held[0].ProcessId)" }
```

In the incident's repair, this refused on one repo because a **VS Code language
server** had held that venv since the previous day. Not a service, not safe to
kill, not the script's business. That repo was fixed a different way. **Refusing
was correct.**

## RULE 6 - One agent at a time on a shared resource

Two agents installing into the same environment concurrently can produce exactly
this partial state. Three sessions were live in one repository during the
incident. Whoever is repairing says so; everyone else keeps out.

## RULE 7 - Verify against the source of truth, not the working copy

Checkouts go stale. During the same incident a subagent reported a file as absent
from a configuration, contradicting a change made hours earlier. The file was
present on `origin/main`; the working copy was **10 commits behind**.

Before asserting something is missing, check `git show origin/main:<path>`, not
the file on disk.

---

## Before you delete anything - the checklist

1. Can I **rename** instead? Do that.
2. Does the tree contain **reparse points**? Scan with `-ErrorAction Stop`. Refuse if any, or if the scan fails.
3. Does anything **hold files open**? Stop services; refuse on surviving processes.
4. Did I create any **links into live directories** earlier in this session? Unlink them explicitly, by name.
5. After: **verify by using**, not by counting.
6. If something looks wrong: check `origin/main`, not the working copy.

## What good verification output looks like

Not this:

```
.venv intact: True          <- only proves python.exe exists
31 unlinked, 0 failed       <- says nothing about what the scan missed
No broken requirements found <- reads metadata, not reality
```

This:

```
service-a      OK   declared=24  missing=0     <- every declared dep imported
service-b      OK   declared=19  missing=0
```

## Reference implementation

The estate this skill came from keeps working tools at `.caddis/tools/`:

- `venv-audit.py` - imports every dependency each `pyproject.toml` declares
- `rebuild-venv.ps1` - renames aside, rebuilds, restarts services, refuses on links or live processes
- `README-venv-safety.md` - the incident record

Adapt rather than copy: the rules matter more than the scripts.
