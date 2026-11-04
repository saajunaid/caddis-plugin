"""Remove THIS session's own leftovers at handoff: merged, clean worktrees and scratch folders (tidy v2, Phase 2).

Input is the session's record (`caddis_created.read`): only the paths this session made. Each entry with status
`created` gets one decision; the first rule that matches wins. Anything in doubt is KEPT, with the reason.

Worktree (in order):
  by roadmap-run -> KEPT (the runner reuses and removes its own) | missing -> GONE | a link, the main checkout, or
  not a registered linked worktree -> KEPT | the process cwd is in it -> KEPT | `git status` not clean (untracked
  counts) -> KEPT | locked -> KEPT | on the default branch -> KEPT | no merged PR (no gh, gh error, no PR, PR not
  MERGED, PR head branch differs) -> KEPT | PR head commit unknown here, or commits after it -> KEPT | a file the branch changed differs
  from `origin/<default>` (fetched first; this is the squash-merge proof that the work landed) -> KEPT |
  else REMOVE: `safe_remove_worktree` (links first, never --force), then the local branch (only while its tip is
  HEAD or the PR head and no other worktree has it), then the remote branch (only while its tip is the PR head or
  the local tip, as one compare-and-delete push).
Scratch: missing -> GONE | a link, a root or home folder, or holds the cwd -> KEPT | inside a git checkout and
  holds tracked files -> KEPT | a full scan (links never followed) that hits an unreadable folder -> KEPT | holds a git repo that is dirty, has commits on no remote, or is
  a linked worktree -> KEPT | else REMOVE via `remove_tree` (links first).

Dry run is the default; `apply=True` acts and records `status=removed` (GONE too). Nothing raises to the caller.

    cleanup(session_id, *, apply, home, pr_lookup, cwd) -> list[{path, kind, action, reason}]
      action: REMOVE (dry run) | REMOVED | KEPT | GONE | FAILED
    summary(results, apply) -> "[OWN-CLEANUP] removed <n>, kept <n>, gone <n>, failed <n>"
    run(session_id, apply, as_json) -> 0                 (the `caddis_created.py cleanup` CLI)

`pr_lookup(main_repo, branch, pr) -> list[{number, state, headRefOid, headRefName}]` (newest first) is the gh
seam; it raises PrLookupError. The default calls plain `gh` with the inherited environment (never `gh auth switch`).
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

import caddis_created
import caddis_finished
import caddis_worktree_safety as safety

# The worktree proof, the gh seam and the removal live in caddis_finished (one definition of "finished", shared with
# `caddis_tidy.py --hygiene`). The old private names stay here as aliases: the tests and the scratch code use them.
GIT_TIMEOUT = caddis_finished.GIT_TIMEOUT
NET_TIMEOUT = caddis_finished.NET_TIMEOUT
PrLookupError = caddis_finished.PrLookupError
gh_pr_lookup = caddis_finished.gh_pr_lookup
_env = caddis_finished._env
_run = caddis_finished._run
_git = caddis_finished._git
_err = caddis_finished._err
_same = caddis_finished._same
_inside = caddis_finished._inside
_slug = caddis_finished.repo_slug
_pr_number = caddis_finished.pr_number
_pick_pr = caddis_finished.pick_pr
_main_repo = caddis_finished.main_repo
_default_branch = caddis_finished.default_branch
_ref = caddis_finished.ref
_names = caddis_finished.changed_names
_branch_tip = caddis_finished.branch_tip
_remove_worktree = caddis_finished.remove_finished


# -- worktree ---------------------------------------------------------------------------------------------------

def _check_worktree(entry: dict, path: Path, cwd: str, pr_lookup: Callable) -> tuple[str, str, dict]:
    """("REMOVE", reason, facts) or ("KEPT"/"GONE", reason, {})."""
    if entry.get("by") == "roadmap-run":
        return "KEPT", "owned by the roadmap runner", {}
    return caddis_finished.prove_worktree_finished(entry, path, cwd, pr_lookup)


# -- scratch ----------------------------------------------------------------------------------------------------

def _scan_scratch(path: Path) -> str | None:
    """None when the folder may go, else why not. Walks every folder (links never followed); errors raise."""
    def fail(exc: OSError) -> None:
        raise exc

    try:
        for top, dirs, files in os.walk(path, topdown=True, onerror=fail, followlinks=False):
            # os.walk does not see a Windows junction as a link: prune every link by lstat, so none is walked
            dirs[:] = [d for d in dirs if not safety.is_link(os.lstat(os.path.join(top, d)))]
            if ".git" not in dirs and ".git" not in files:
                continue
            repo = Path(top)
            if os.path.isfile(repo / ".git"):
                return f"holds a linked git worktree at {repo}; remove it as a worktree"
            status = _git(repo, "status", "--porcelain")
            if status.returncode != 0:
                return f"holds a git repo at {repo} whose status failed: {_err(status)}"
            if status.stdout.strip():
                return f"holds a git repo with uncommitted changes at {repo}"
            local = _git(repo, "rev-list", "--max-count=1", "--all", "--not", "--remotes")
            if local.returncode != 0 or local.stdout.strip():
                return f"holds a git repo with commits or a stash on no remote at {repo}"
            dirs[:] = [d for d in dirs if d != ".git"]
    except OSError as exc:
        return f"cannot scan: {exc}"
    return None


def _check_scratch(path: Path, cwd: str) -> tuple[str, str]:
    if not os.path.lexists(path):
        return "GONE", ""
    try:
        if safety.is_link(os.lstat(path)):
            return "KEPT", "the folder is a junction or symlink"
    except OSError as exc:
        return "KEPT", f"cannot inspect it: {exc}"
    if not path.is_dir():
        return "KEPT", "not a folder"
    resolved = Path(os.path.realpath(path))
    if resolved.parent == resolved or _same(resolved, Path.home()) or _inside(Path.home(), resolved):
        return "KEPT", "a root or home folder is never scratch"
    if _inside(cwd, path):
        return "KEPT", "this session is working in it"
    if not os.path.lexists(path / ".git"):  # a folder inside a checkout must not take tracked files with it
        inside = _git(path, "rev-parse", "--is-inside-work-tree")
        if inside.returncode == 0 and inside.stdout.strip() == "true":
            tracked = _git(path, "ls-files", "-z", "--", ".")
            if tracked.returncode != 0 or tracked.stdout.strip("\0"):
                return "KEPT", "inside a git checkout and holds tracked files"
    problem = _scan_scratch(path)
    return ("KEPT", problem) if problem else ("REMOVE", "scratch folder of this session")


# -- driver -----------------------------------------------------------------------------------------------------

def _mark_removed(entry: dict, sid: str, home, pr: str | None = None) -> None:
    by = entry.get("by") if entry.get("by") in caddis_created.BYS else "cli"
    caddis_created.record(entry["path"], entry["kind"], "", pr=pr, status="removed", by=by, session_id=sid,
                          home=home)


def cleanup(session_id: str, *, apply: bool = False, home: Path | str | None = None,
            pr_lookup: Callable | None = None, cwd: str | Path | None = None) -> list[dict]:
    lookup = pr_lookup or gh_pr_lookup
    here = str(cwd) if cwd is not None else os.getcwd()
    results: list[dict] = []
    for entry in caddis_created.read(session_id, home=home):
        if entry.get("status") != "created":
            continue
        path = Path(entry["path"])
        try:
            if entry["kind"] == "worktree":
                action, reason, facts = _check_worktree(entry, path, here, lookup)
            else:
                (action, reason), facts = _check_scratch(path, here), {}
            if apply and action == "GONE":
                _mark_removed(entry, session_id, home)
            elif apply and action == "REMOVE":
                if entry["kind"] == "worktree":
                    action, notes = _remove_worktree(path, facts)
                    if action != "REMOVED":
                        reason = notes
                    elif notes:
                        reason = f"{reason}; {notes}"
                else:
                    problem = safety.remove_tree(path)
                    action, reason = ("FAILED", problem) if problem else ("REMOVED", reason)
                if action == "REMOVED":
                    _mark_removed(entry, session_id, home, facts.get("pr"))
        except Exception as exc:  # noqa: BLE001 - one bad entry must not stop the others
            action, reason = "FAILED", f"unexpected error: {exc}"
        results.append({"path": str(path), "kind": entry["kind"], "action": action, "reason": reason})
    return results


def line(result: dict) -> str:
    action, path, reason = result["action"], result["path"], result["reason"]
    if action == "GONE":
        return f"GONE {path}"
    if action in ("REMOVE", "REMOVED"):
        return f"{action} {path}" + (f" ({reason})" if reason else "")
    return f"{action} {path}: {reason}"


def summary(results: list[dict], apply: bool) -> str:
    count = {a: sum(1 for r in results if r["action"] == a) for a in ("REMOVE", "REMOVED", "KEPT", "GONE", "FAILED")}
    head = f"removed {count['REMOVED']}" if apply else f"would remove {count['REMOVE']}"
    return f"[OWN-CLEANUP] {head}, kept {count['KEPT']}, gone {count['GONE']}, failed {count['FAILED']}"


def run(session_id: str | None, apply: bool, as_json: bool) -> int:
    """The CLI body. Always 0: a handoff must never fail on its cleanup row."""
    if not session_id:
        print("caddis_created: no usable session id; nothing to clean up", file=sys.stderr)
        results: list[dict] = []
    else:
        results = cleanup(session_id, apply=apply)
    if as_json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return 0
    for result in results:
        print(line(result))
    print(summary(results, apply))
    return 0
