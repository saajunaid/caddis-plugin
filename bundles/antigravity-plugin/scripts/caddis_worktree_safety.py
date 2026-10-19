"""Remove a git worktree, or a folder that held one, without deleting through a link.

On Windows, `git worktree remove --force` and `shutil.rmtree` can follow a directory junction and delete its
TARGET: a shared `.venv`, a `node_modules`, the live repo. So every symlink and junction in the tree goes first,
removed as a link (never entered), and only then is the tree removed. If a link cannot be removed, nothing is
deleted: the caller gets the problem back.

    remove_links(root)                 -> the links removed (raises LinkRemovalError when one cannot go)
    remove_tree(path)                  -> None, or the problem (links first, then rmtree)
    safe_remove_worktree(repo, wt)     -> None, or the problem (refuses the main checkout, unregistered paths, and
                                          a locked or dirty worktree that git would keep, before any link goes)
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_DIRECTORY = getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0x10)


class LinkRemovalError(OSError):
    """A link could not be removed. `removed` holds the links that were already removed before the failure; no
    other file was deleted."""

    def __init__(self, cause: OSError, removed: list[Path]):
        detail = str(cause)
        if removed:
            detail += (f" (removed {len(removed)} link(s) before the failure: "
                       f"{', '.join(str(p) for p in removed)})")
        super().__init__(detail)
        self.cause = cause
        self.removed = removed


def is_link(st: os.stat_result) -> bool:
    """A symlink, or on Windows any reparse point (a junction included), from `os.lstat`."""
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & _REPARSE)


def _unlink_link(path: str, st: os.stat_result) -> None:
    """Remove the link itself, never its target: on Windows a junction or a directory symlink with os.rmdir, any
    other link with os.unlink."""
    if os.name == "nt" and getattr(st, "st_file_attributes", 0) & _DIRECTORY:
        os.rmdir(path)
    else:
        os.unlink(path)


def remove_links(root: Path) -> list[Path]:
    """Remove every symlink and junction at or under `root`, bottom-up, never following one. Returns the links
    removed. Raises LinkRemovalError (an OSError) when a link cannot be removed; the links removed before it are in
    its `removed`. The caller must then delete nothing more, because a delete through a link destroys its target.
    A missing `root` removes nothing."""
    root = Path(root)
    try:
        st = os.lstat(root)
    except FileNotFoundError:
        return []
    if is_link(st):
        try:
            _unlink_link(str(root), st)
        except OSError as exc:
            raise LinkRemovalError(exc, []) from exc
        return [root]
    folders = [str(root)]
    order: list[str] = []
    while folders:                      # top-down collection of real folders only; a link is never entered
        folder = folders.pop()
        order.append(folder)
        with os.scandir(folder) as entries:
            for entry in entries:
                entry_st = os.lstat(entry.path)
                if not is_link(entry_st) and stat.S_ISDIR(entry_st.st_mode):
                    folders.append(entry.path)
    removed: list[Path] = []
    try:
        for folder in reversed(order):      # bottom-up removal of the links in each folder
            with os.scandir(folder) as entries:
                found = [(entry.path, os.lstat(entry.path)) for entry in entries]
            for path, entry_st in found:
                if is_link(entry_st):
                    _unlink_link(path, entry_st)
                    removed.append(Path(path))
    except OSError as exc:
        raise LinkRemovalError(exc, removed) from exc
    return removed


def remove_tree(path: Path) -> str | None:
    """Delete the folder `path` (for example the temp folder that held a worktree): its links first, then the
    rest. None when it is gone, else the problem. When a link cannot go, no file is deleted (the links removed
    before the failure are named in the problem)."""
    path = Path(path)
    if not os.path.lexists(path):
        return None
    try:
        remove_links(path)
    except OSError as exc:
        return f"not removed: {path}: a link could not be removed: {exc}; no file was deleted"
    shutil.rmtree(path, ignore_errors=True)
    return f"not removed: {path}" if os.path.lexists(path) else None


def _same(a: Path | str, b: Path | str) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _run_git(repo: Path, args: Sequence[str], git_flags: Sequence[str],
             env: Mapping[str, str] | None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *git_flags, "-C", str(repo), *args], capture_output=True, text=True, check=False,
                          encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                          env=dict(env) if env is not None else None)


def _worktree_blocks(porcelain: str) -> list[list[str]]:
    """`git worktree list --porcelain` split into one list of lines per worktree."""
    blocks: list[list[str]] = []
    for line in porcelain.splitlines():
        if line.startswith("worktree "):
            blocks.append([line])
        elif line.strip() and blocks:
            blocks[-1].append(line)
    return blocks


def safe_remove_worktree(repo: Path, worktree: Path, *, force: bool = True, force_locked: bool = False,
                         git_flags: Sequence[str] = (), env: Mapping[str, str] | None = None) -> str | None:
    """Remove the linked worktree `worktree` of `repo`: its links first, then `git worktree remove`.

    None when git removed it, else the problem. Before any link is touched it refuses a path that is a link, the
    main checkout, a path that is not a registered linked worktree of `repo`, a locked worktree unless
    `force_locked`, and a dirty one unless `force`: git would keep those, and a kept worktree must keep its links.
    `force` passes `--force` (a dirty worktree goes); `force_locked` passes it twice (a locked one goes too). A
    relative `worktree` is taken from `repo`, not from the process cwd. `git_flags` go before `-C` (for example
    `-c core.hooksPath=...`); `env` is the git environment."""
    worktree = Path(worktree)
    if not worktree.is_absolute():
        worktree = Path(repo) / worktree
    try:
        if os.path.lexists(worktree) and is_link(os.lstat(worktree)):
            return f"refusing to remove {worktree}: the worktree folder is a junction or symlink"
    except OSError as exc:
        return f"refusing to remove {worktree}: cannot inspect it: {exc}"
    listing = _run_git(Path(repo), ("worktree", "list", "--porcelain"), git_flags, env)
    if listing.returncode != 0:
        return f"refusing to remove {worktree}: git worktree list failed: {(listing.stderr or '').strip()}"
    blocks = _worktree_blocks(listing.stdout)
    if not blocks:
        return f"refusing to remove {worktree}: git listed no worktrees"
    if _same(worktree, blocks[0][0][len("worktree "):]):
        return f"refusing to remove {worktree}: it is the main checkout"
    if _same(worktree, repo):
        return f"refusing to remove {worktree}: it is the checkout git runs in"
    block = next((b for b in blocks[1:] if _same(worktree, b[0][len("worktree "):])), None)
    if block is None:
        return f"refusing to remove {worktree}: not a registered worktree of {repo}"
    if not force_locked and any(line == "locked" or line.startswith("locked ") for line in block):
        return f"refusing to remove {worktree}: it is locked (git worktree unlock it first); its links were kept"
    if not force and os.path.lexists(worktree):
        status = _run_git(worktree, ("status", "--porcelain"), git_flags, env)
        if status.returncode != 0:
            return f"refusing to remove {worktree}: git status failed: {(status.stderr or '').strip()}"
        if status.stdout.strip():
            return f"refusing to remove {worktree}: it has uncommitted changes; its links were kept"
    try:
        removed = remove_links(worktree)
    except OSError as exc:
        return f"not removed: {worktree}: a link could not be removed: {exc}; no file was deleted"
    flags = ["--force", "--force"] if force_locked else (["--force"] if force else [])
    proc = _run_git(Path(repo), ("worktree", "remove", *flags, str(worktree)), git_flags, env)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() or str(worktree)
        if removed:
            detail += f" ({len(removed)} link(s) inside it were removed first)"
        return f"git worktree remove failed: {detail}"
    return None
