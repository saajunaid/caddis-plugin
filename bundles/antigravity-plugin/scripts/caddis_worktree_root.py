"""Where a NEW git worktree goes. One rule, one place; every caller and every doc uses it.

Never %TEMP%: Windows cleanup / Storage Sense can empty it and delete a worktree that holds unmerged work (owner
decision, 20 Oct 2026). The path is

    <root>/<main checkout folder name>/<short-name>

where <root> is, in order:
  1. the `root` argument (a test seam and an explicit override);
  2. the `CADDIS_WORKTREE_ROOT` environment variable, when set and not blank;
  3. `<parent folder of the repo's MAIN checkout>/.worktrees`. For `E:\\Projects\\<repo>` that is
     `E:\\Projects\\.worktrees\\<repo>\\<short-name>`. No machine path is written in code. There is no %TEMP% fallback.

The main checkout is the parent of `git rev-parse --git-common-dir`, so the answer is the same from the main checkout,
from a subfolder and from any linked worktree.

Only the default for a NEW worktree lives here. A worktree that already exists, or whose path a runner recorded,
stays where it is: moving it breaks a venv, which keeps absolute paths.

    worktree_root(repo, root=None)            -> the folder that holds the per-repo folders
    worktree_path(repo, short_name, root=None) -> the path for a new worktree (nothing is created)
    main_checkout(repo)                       -> the main checkout's folder

CLI: `python caddis_worktree_root.py [--repo PATH] [--root PATH] [--record --purpose TEXT] <short-name>` prints the path.
Exit 2 on a bad name or a folder that is not in a git repo.

`--record` also appends the path to this session's created list (`caddis_created.py`, by="helper"), so `/handoff` can
remove the worktree later. The helper creates nothing, so the path is recorded as INTENDED: run `git worktree add` on the
path it printed. A session with no session id, or a record that cannot be written, only prints a warning on stderr: the
path is still printed and the exit code is still 0.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ENV_VAR = "CADDIS_WORKTREE_ROOT"
FALLBACK_DIR = ".worktrees"


class NotARepoError(RuntimeError):
    """The folder is not inside a git repository."""


def _git_out(cwd: Path, *args: str) -> str | None:
    try:
        res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", stdin=subprocess.DEVNULL, check=False)
    except OSError:
        return None
    return res.stdout.strip() if res.returncode == 0 else None


def main_checkout(repo: Path | str) -> Path:
    """The MAIN checkout's folder for `repo` (the main checkout, a subfolder of it or a linked worktree).

    It is the parent of the git common dir. A common dir not named `.git` (a submodule's, a bare repo's) has no such
    parent: then the work-tree top is used, or the common dir itself when there is no work tree."""
    repo = Path(repo).absolute()
    common = _git_out(repo, "rev-parse", "--git-common-dir") if repo.is_dir() else None
    if not common:
        raise NotARepoError(f"{repo} is not inside a git repository")
    common_dir = Path(os.path.normpath(repo / common))  # relative to `repo`, or absolute already
    if common_dir.name == ".git":
        return common_dir.parent
    top = _git_out(repo, "rev-parse", "--show-toplevel")
    return Path(os.path.normpath(top)) if top else common_dir


def _explicit_root(root: Path | str | None) -> Path | None:
    """`root`, else `$CADDIS_WORKTREE_ROOT` when not blank, else None (the fallback needs the main checkout)."""
    if root:
        return Path(root)
    env = os.environ.get(ENV_VAR, "").strip()
    return Path(env) if env else None


def worktree_root(repo: Path | str, root: Path | str | None = None) -> Path:
    """The folder that holds one folder per repo: `root`, else `$CADDIS_WORKTREE_ROOT`, else
    `<parent of the main checkout>/.worktrees`."""
    return _explicit_root(root) or main_checkout(repo).parent / FALLBACK_DIR


def worktree_path(repo: Path | str, short_name: str, root: Path | str | None = None) -> Path:
    """The path for a NEW worktree of `repo`: `<root>/<main checkout folder name>/<short_name>`. Creates nothing.
    `short_name` is one plain folder name: ValueError for an empty name, `.`, `..`, or one with a path separator or a
    colon (a drive such as `C:foo` would replace the root on Windows)."""
    if (not short_name or short_name in (".", "..") or any(c in short_name for c in "/\:")
            or short_name != short_name.strip()):
        raise ValueError(f"the short name must be one plain folder name, not {short_name!r}")
    main = main_checkout(repo)  # one git call
    return (_explicit_root(root) or main.parent / FALLBACK_DIR) / main.name / short_name


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Print the path for a new git worktree (never under %TEMP%).")
    ap.add_argument("short_name", help="one folder name, e.g. fix-login")
    ap.add_argument("--repo", default=".", help="any folder of the repo or of one of its worktrees (default: .)")
    ap.add_argument("--root", default=None, help=f"override the root (default: ${ENV_VAR}, then <repo parent>/.worktrees)")
    ap.add_argument("--record", action="store_true", help="also record the path in this session's created list")
    ap.add_argument("--purpose", default="", help="with --record: why the worktree is made")
    args = ap.parse_args(argv)
    try:
        path = worktree_path(args.repo, args.short_name, args.root)
        repo = main_checkout(args.repo) if args.record else None
    except (ValueError, NotARepoError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(path)
    if args.record:
        _record(path, repo, args.purpose)
    return 0


def _record(path: Path, repo: Path | None, purpose: str) -> None:
    """Append `path` to the session's created list. A failure only warns: the caller still has its path."""
    try:
        import caddis_created
        done = caddis_created.record(path, "worktree", purpose, repo=repo, by="helper")
    except Exception:  # noqa: BLE001 - recording must never break a command that only wants the path
        done = False
    if not done:
        print(f"caddis_worktree_root: not recorded (no usable session id, or the record could not be written): {path}",
              file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
