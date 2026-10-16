"""Write handoff's tracked doc edits in a temp worktree this session owns, then open one docs PR.

A shared checkout (see `caddis_checkout_guard.py shared`) may hold another session's uncommitted edits, so
handoff must not commit there. Instead:

    caddis_docs_pr.py start --repo <root>
        git fetch origin, then `git worktree add -b docs/handoff-<utc> <tmp> origin/<default>`;
        prints `WORKTREE: <path>`. The worktree is new and belongs to this session only, so no other
        session's edits can enter it.
    caddis_docs_pr.py finish --worktree <path> --title T --body B
        first stages every change in the worktree and saves the full diff (staged, unstaged and
        untracked) to a new patch file. Then it commits, pushes, opens a PR with
        `gh api repos/<owner>/<repo>/pulls`, prints `PR: <url>` and one `FILE: <path>` line per file.
        With no change it prints `PR: none`. On any failure after the patch is saved it prints
        `PATCH: <path>`. It removes the worktree and the local branch only after a PR opened, after the
        patch was saved, or when there was no change. If the patch cannot be saved, it keeps the worktree
        and prints `WORKTREE KEPT: <path>`. It never merges.

`finish` acts only on a linked worktree that `start` made: its git dir differs from the common git dir, it is
not the main worktree, it is under the temp folder, and its branch is `docs/handoff-<utc>[-n]`. Anything else
is refused (exit 4) and left as it is.

Exit codes (caddis_exit): 0 clean (PR opened, or no change), 1 blocked (the PR could not be opened),
3 could not run (git or the push failed, no GitHub origin), 4 error (bad usage, not a docs-PR worktree).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import caddis_exit
    import caddis_checkout_guard
    import caddis_roadmap as roadmap
except ModuleNotFoundError as exc:
    if exc.name not in {"caddis_exit", "caddis_checkout_guard", "caddis_roadmap"}:
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-harness" / "scripts"))
    import caddis_exit
    import caddis_checkout_guard
    import caddis_roadmap as roadmap

BRANCH_PREFIX = "docs/handoff-"
DIR_PREFIX = "caddis-docs-pr-"
BRANCH_RE = re.compile(r"^docs/handoff-\d{14}(?:-\d+)?$")


class DocsPrError(Exception):
    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code


def _git(root: Path, *args: str, check: bool = True):
    """git through caddis_roadmap: no credential prompt, and a timeout on fetch and push."""
    return roadmap._git(Path(root), *args, check=check)


def _utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")


def start(repo: Path, out=print) -> int:
    repo = Path(repo).resolve()
    base = roadmap.fetch(repo)
    stamp = _utc()
    tmp_root = Path(tempfile.gettempdir())
    # Two starts in one second must not collide on the path or the branch.
    suffix = ""
    n = 1
    while (tmp_root / f"{DIR_PREFIX}{stamp}{suffix}").exists() or \
            _git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{BRANCH_PREFIX}{stamp}{suffix}",
                 check=False).returncode == 0:
        n += 1
        suffix = f"-{n}"
    worktree = tmp_root / f"{DIR_PREFIX}{stamp}{suffix}"
    branch = f"{BRANCH_PREFIX}{stamp}{suffix}"
    _git(repo, "worktree", "add", "--quiet", "-b", branch, str(worktree), f"origin/{base}")
    out(f"WORKTREE: {worktree}")
    return caddis_exit.CLEAN


def _abs(base: Path, raw: str) -> Path:
    path = Path(raw.strip())
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _main_repo(worktree: Path) -> Path:
    """The main checkout: the first entry of `git worktree list --porcelain`."""
    for line in _git(worktree, "worktree", "list", "--porcelain").stdout.splitlines():
        if line.startswith("worktree "):
            return Path(line[len("worktree "):]).resolve()
    raise DocsPrError(f"git worktree list gave no main worktree for {worktree}", caddis_exit.ERROR)


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return path != parent


def _check_owned(worktree: Path) -> tuple[Path, str]:
    """(main repo, branch) of a worktree `start` made; DocsPrError(ERROR) for anything else."""
    if not worktree.is_dir():
        raise DocsPrError(f"not a directory: {worktree}", caddis_exit.ERROR)
    proc = _git(worktree, "rev-parse", "--show-toplevel", check=False)
    if proc.returncode != 0:
        raise DocsPrError(f"not a git worktree: {worktree}", caddis_exit.ERROR)
    if Path(proc.stdout.strip()).resolve() != worktree.resolve():
        raise DocsPrError(f"not the top of a worktree: {worktree}", caddis_exit.ERROR)
    git_dir = _abs(worktree, _git(worktree, "rev-parse", "--git-dir").stdout)
    common = _abs(worktree, _git(worktree, "rev-parse", "--git-common-dir").stdout)
    if git_dir == common:
        raise DocsPrError(f"{worktree} is not a linked worktree; nothing done", caddis_exit.ERROR)
    main = _main_repo(worktree)
    if main == worktree.resolve():
        raise DocsPrError(f"{worktree} is the main checkout, not a docs-PR worktree; nothing done",
                          caddis_exit.ERROR)
    branch = _git(worktree, "branch", "--show-current").stdout.strip()
    if not BRANCH_RE.match(branch):
        raise DocsPrError(f"{worktree} is on branch '{branch}', not a {BRANCH_PREFIX}<utc> branch; nothing done",
                          caddis_exit.ERROR)
    resolved = worktree.resolve()
    if resolved.parent != Path(tempfile.gettempdir()).resolve() or not resolved.name.startswith(DIR_PREFIX):
        raise DocsPrError(f"{worktree} is not a {DIR_PREFIX}* folder directly in the temp folder that start uses; "
                          "nothing done", caddis_exit.ERROR)
    return main, branch


def _changed_files(worktree: Path) -> list[str]:
    """Every path in `git status --porcelain -z`, parsed on NUL, so spaces, ' -> ' and non-ASCII stay exact.

    A rename or copy entry is followed by one more NUL field, the original path; both paths count.
    """
    proc = subprocess.run(["git", "-C", str(worktree), "status", "--porcelain=v1", "--untracked-files=all", "-z"],
                          capture_output=True, stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise DocsPrError(f"git status failed in {worktree}", caddis_exit.NOT_RUN)
    parts = proc.stdout.decode("utf-8", errors="surrogateescape").split("\0")
    files: list[str] = []
    idx = 0
    while idx < len(parts):
        entry = parts[idx]
        idx += 1
        if len(entry) < 4:
            continue
        xy, paths = entry[:2], [entry[3:]]
        if ("R" in xy or "C" in xy) and idx < len(parts):
            paths.append(parts[idx])
            idx += 1
        for path in paths:
            if path and path not in files:
                files.append(path)
    return files


def open_pr(gh_repo: str, branch: str, base: str, title: str, body: str) -> str:
    """Open a PR with the REST API and return its URL. `gh` takes the account from GH_TOKEN when it is set."""
    proc = roadmap.run_bounded(["gh", "api", f"repos/{gh_repo}/pulls", "-f", f"title={title}", "-f",
                                f"head={branch}", "-f", f"base={base}", "-f", f"body={body}"],
                               roadmap.GH_TIMEOUT, "gh api (open the PR)")
    if proc.returncode != 0:
        raise DocsPrError(f"could not open the PR: {(proc.stderr or proc.stdout).strip()[:300]}",
                          caddis_exit.BLOCKED)
    try:
        return str(json.loads(proc.stdout)["html_url"])
    except (ValueError, KeyError, TypeError) as exc:
        raise DocsPrError(f"gh api gave no PR URL: {exc}", caddis_exit.BLOCKED) from exc


def _save_patch(worktree: Path) -> Path:
    """Stage every change and write the full staged diff to a new patch file (mkstemp: no predictable path).

    `git add -A` is safe here: this worktree was made by `start` for this session only (see _check_owned).
    """
    _git(worktree, "add", "-A")
    proc = subprocess.run(["git", "-C", str(worktree), "diff", "--cached", "--binary"],
                          capture_output=True, stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise DocsPrError(f"git diff failed in {worktree}", caddis_exit.NOT_RUN)
    fd, name = tempfile.mkstemp(prefix=DIR_PREFIX, suffix=".patch")
    with os.fdopen(fd, "wb") as handle:
        handle.write(proc.stdout)
    return Path(name)


def _remove(main: Path, worktree: Path, branch: str) -> None:
    for args in (("worktree", "remove", "--force", "--force", str(worktree)), ("worktree", "prune"),
                 ("branch", "-D", branch)):
        try:
            _git(main, *args, check=False)
        except (roadmap.RoadmapError, OSError):
            pass
    if worktree.exists():
        shutil.rmtree(worktree, ignore_errors=True)


def finish(worktree: Path, title: str, body: str, out=print) -> int:
    worktree = Path(worktree).resolve()
    main, branch = _check_owned(worktree)  # refuses before anything is changed or removed
    # Save the session's edits FIRST. Until the patch exists, nothing may remove the worktree.
    try:
        files = _changed_files(worktree)
        patch = _save_patch(worktree) if files else None
    except (DocsPrError, roadmap.RoadmapError, OSError) as exc:
        out(f"docs PR failed: could not save the change: {exc}")
        out(f"WORKTREE KEPT: {worktree}")
        return getattr(exc, "code", caddis_exit.NOT_RUN)
    if patch is None:
        _remove(main, worktree, branch)
        out("PR: none")
        return caddis_exit.CLEAN
    pushed = False
    try:
        gh_repo = roadmap.gh_repo_of(main)
        if gh_repo is None:
            raise DocsPrError("origin is not a GitHub remote; cannot open a docs PR", caddis_exit.NOT_RUN)
        base = roadmap.default_branch(main)
        _git(worktree, "commit", "--quiet", "-m", title)
        _git(worktree, "push", "--quiet", "-u", "origin", branch)
        pushed = True
        url = open_pr(gh_repo, branch, base, title, body)
    except (DocsPrError, roadmap.RoadmapError, OSError) as exc:
        out(f"docs PR failed: {exc}")
        out(f"PATCH: {patch}")
        if pushed:
            try:
                _git(main, "push", "--quiet", "origin", "--delete", branch, check=False)
            except (roadmap.RoadmapError, OSError):
                pass
        _remove(main, worktree, branch)
        return getattr(exc, "code", caddis_exit.NOT_RUN)
    out(f"PR: {url}")
    for path in files:
        out(f"FILE: {path}")
    _remove(main, worktree, branch)
    try:
        patch.unlink()
    except OSError:
        pass
    return caddis_exit.CLEAN


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Handoff's docs PR from a temp worktree.")
    sub = parser.add_subparsers(dest="command")
    p_start = sub.add_parser("start", help="make the worktree from origin/<default>")
    p_start.add_argument("--repo", required=True, type=Path)
    p_finish = sub.add_parser("finish", help="save a patch, commit, push and open the PR, then remove the worktree")
    p_finish.add_argument("--worktree", required=True, type=Path)
    p_finish.add_argument("--title", required=True)
    p_finish.add_argument("--body", required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return caddis_exit.ERROR
    try:
        if args.command == "start":
            return start(args.repo)
        if args.command == "finish":
            return finish(args.worktree, args.title, args.body)
    except (DocsPrError, roadmap.RoadmapError) as exc:
        print(f"caddis_docs_pr: {exc}", file=sys.stderr)
        return exc.code
    parser.print_help(sys.stderr)
    return caddis_exit.ERROR


if __name__ == "__main__":
    sys.exit(main())
