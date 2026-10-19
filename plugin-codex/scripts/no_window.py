"""Start subprocesses without a visible console window on Windows. No dependencies.

Why this exists
---------------
A process that has NO console (a Claude session started by VS Code, the `claude daemon`, a
background session) makes Windows open a NEW, VISIBLE console for every console program it starts
(git.exe, cmd, python, npx, ruff). Hooks and the status line run in exactly such sessions, so each
`subprocess.run(["git", ...])` flashed a window (owner report, 19 Oct).

`CREATE_NO_WINDOW` fixes it. The child gets a hidden console, and output captured through pipes
still works. When the parent already has a console the flag is harmless.

Never add `DETACHED_PROCESS`: Windows then ignores `CREATE_NO_WINDOW`, the child has no console,
and every program it starts opens its own visible window. `merge()` clears that bit.

Use
---
    from no_window import run                  # a drop-in for subprocess.run
    subprocess.run(argv, **NO_WINDOW_KW)       # or spread the keywords yourself

On POSIX `NO_WINDOW_KW` is empty and `merge()` returns the keywords unchanged.
"""
from __future__ import annotations

import os
import subprocess

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008

NO_WINDOW_KW = {"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {}


def merge(kwargs: dict) -> dict:
    """A copy of `kwargs` with CREATE_NO_WINDOW ORed into `creationflags` (Windows only)."""
    out = dict(kwargs)
    if os.name == "nt":
        out["creationflags"] = (int(out.get("creationflags") or 0) & ~DETACHED_PROCESS) | CREATE_NO_WINDOW
    return out


def run(*args, **kwargs):
    """subprocess.run that never opens a console window on Windows."""
    return subprocess.run(*args, **merge(kwargs))


def popen(*args, **kwargs):
    """subprocess.Popen that never opens a console window on Windows."""
    return subprocess.Popen(*args, **merge(kwargs))
