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

`python caddis_worktree_root.py --bootstrap [--repo PATH]` runs INSIDE a linked worktree and gives it its own
dependencies (uv sync, or venv + pip; npm ci per package-lock.json). The pre-push gate needs that `.venv`.
Exit 0 done, 1 a step failed or a tool is missing, 2 not a linked worktree.

`--record` also appends the path to this session's created list (`caddis_created.py`, by="helper"), so `/handoff` can
remove the worktree later. The helper creates nothing, so the path is recorded as INTENDED: run `git worktree add` on the
path it printed. A session with no session id, or a record that cannot be written, only prints a warning on stderr: the
path is still printed and the exit code is still 0.
"""

from __future__ import annotations

import argparse
import os
import shutil
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
    if (not short_name or short_name in (".", "..") or any(c in short_name for c in "/\\:")
            or short_name != short_name.strip()):
        raise ValueError(f"the short name must be one plain folder name, not {short_name!r}")
    main = main_checkout(repo)  # one git call
    return (_explicit_root(root) or main.parent / FALLBACK_DIR) / main.name / short_name


# ---- bootstrap: give a fresh worktree its own dependencies ---------------------------------------------------------
# A worktree installs its dependencies fresh. It never links or borrows a venv or node_modules from another folder
# (the main checkout's venv belongs to a running dev service and is often behind). The pre-push gate uses only the
# worktree's own `.venv`, so this is the one command that makes a new worktree pass it.

NPM_FOLDERS = (".", "frontend")  # folders checked for a package-lock.json


def is_linked_worktree(repo: Path) -> bool:
    """True when `repo` is inside a linked worktree (its git dir is not the common dir)."""
    git_dir = _git_out(repo, "rev-parse", "--absolute-git-dir")
    common = _git_out(repo, "rev-parse", "--git-common-dir")
    if not git_dir or not common:
        return False
    return os.path.normcase(os.path.normpath(git_dir)) != os.path.normcase(os.path.normpath(repo / common))


def venv_python(venv: Path) -> Path:
    """The interpreter inside a venv folder (Windows `Scripts/`, POSIX `bin/`)."""
    win = venv / "Scripts" / "python.exe"
    return win if win.exists() or os.name == "nt" else venv / "bin" / "python"


def _declares_dev_extra(pyproject: Path) -> tuple[bool, bool]:
    """(has a [project] table, declares a `dev` optional-dependency group)."""
    try:
        import tomllib
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - unreadable or invalid TOML: treat as "declares nothing"
        return False, False
    project = data.get("project")
    if not isinstance(project, dict):
        return False, False
    return True, "dev" in (project.get("optional-dependencies") or {})


def plan_bootstrap(root: Path) -> list[tuple[Path, list[str]]]:
    """The commands (cwd, argv) that bootstrap the worktree at `root`. Reads files only; runs nothing.

    Python: `uv sync --frozen --all-extras` when `uv.lock` exists (pip would not honour the lock), else `python -m venv .venv`
    then `pip install` of what the repo declares (`-e .[dev]` or `-e .`, then requirements.txt / requirements-dev.txt).
    Node: `npm ci` in each of NPM_FOLDERS that has a `package-lock.json`."""
    steps: list[tuple[Path, list[str]]] = []
    pyproject = root / "pyproject.toml"
    reqs = [f for f in ("requirements.txt", "requirements-dev.txt") if (root / f).is_file()]
    if (root / "uv.lock").is_file():
        steps.append((root, ["uv", "sync", "--frozen", "--all-extras"]))
    elif pyproject.is_file() or reqs:
        has_project, has_dev = _declares_dev_extra(pyproject) if pyproject.is_file() else (False, False)
        if has_project or reqs:  # a pyproject with only tool config declares nothing to install
            venv = root / ".venv"
            if not venv_python(venv).is_file():  # the folder alone is not enough: an interrupted `venv` leaves it empty
                steps.append((root, [sys.executable, "-m", "venv", ".venv"]))
            py = str(venv_python(venv))
            if has_project:
                steps.append((root, [py, "-m", "pip", "install", "-e", ".[dev]" if has_dev else "."]))
            for f in reqs:
                steps.append((root, [py, "-m", "pip", "install", "-r", f]))
    for folder in NPM_FOLDERS:
        d = root / folder
        if (d / "package-lock.json").is_file():
            steps.append((d, ["npm", "ci"]))
    return steps


def bootstrap(repo: Path | str = ".", run=subprocess.run, which=shutil.which) -> int:
    """Install the dependencies of the linked worktree that contains `repo`. Returns 0, 1 (a step failed or a tool is
    missing) or 2 (not a linked worktree: this never touches a main checkout). `run` and `which` are test seams."""
    repo = Path(repo).absolute()
    top = _git_out(repo, "rev-parse", "--show-toplevel") if repo.is_dir() else None
    if not top:
        print(f"error: {repo} is not inside a git repository", file=sys.stderr)
        return 2
    root = Path(os.path.normpath(top))
    if not is_linked_worktree(root):
        print(f"error: {root} is a main checkout, not a linked worktree. Bootstrap only runs in a worktree "
              "(it would change the checkout's own venv and node_modules).", file=sys.stderr)
        return 2
    steps = plan_bootstrap(root)
    if not steps:
        print(f"bootstrap: nothing to install in {root} (no pyproject.toml, requirements*.txt or package-lock.json)")
        return 0
    for cwd, argv in steps:
        exe = which(argv[0]) if argv[0] in ("uv", "npm") else argv[0]
        if exe is None:
            hint = " (uv.lock needs uv; pip would ignore the lock)" if argv[0] == "uv" else ""
            print(f"error: `{argv[0]}` not found on PATH{hint}", file=sys.stderr)
            return 1
        cmd = [exe, *argv[1:]]
        print(f"bootstrap: ({cwd}) {' '.join(cmd)}", flush=True)
        if run(cmd, cwd=cwd, check=False).returncode != 0:
            print(f"error: step failed: {' '.join(cmd)}", file=sys.stderr)
            return 1
    print(f"bootstrap: done - {root} has its own dependencies")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Print the path for a new git worktree (never under %TEMP%).")
    ap.add_argument("short_name", nargs="?", help="one folder name, e.g. fix-login (not used with --bootstrap)")
    ap.add_argument("--bootstrap", action="store_true",
                    help="instead of printing a path: install the dependencies of the worktree that contains --repo "
                         "(uv sync or venv + pip, and npm ci); exit 2 in a main checkout")
    ap.add_argument("--repo", default=".", help="any folder of the repo or of one of its worktrees (default: .)")
    ap.add_argument("--root", default=None, help=f"override the root (default: ${ENV_VAR}, then <repo parent>/.worktrees)")
    ap.add_argument("--record", action="store_true", help="also record the path in this session's created list")
    ap.add_argument("--purpose", default="", help="with --record: why the worktree is made")
    args = ap.parse_args(argv)
    if args.bootstrap:
        return bootstrap(args.repo)
    if not args.short_name:
        ap.error("a short name is required (or use --bootstrap)")
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
