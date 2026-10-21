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
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import caddis_created
import caddis_worktree_safety as safety

GIT_TIMEOUT = 60
NET_TIMEOUT = 120
_GH_FIELDS = "number,state,headRefOid,mergedAt,headRefName"


class PrLookupError(Exception):
    """gh is missing, failed, or the repo cannot be named."""


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"  # a credential prompt must fail, not hang the handoff
    return env


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = GIT_TIMEOUT) -> subprocess.CompletedProcess:
    """Never raises: a missing program or a timeout comes back as returncode -1 with the problem in stderr."""
    try:
        return subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", stdin=subprocess.DEVNULL, timeout=timeout, check=False, env=_env())
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, -1, "", f"{cmd[0]} is not installed")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, -1, "", f"{cmd[0]} timed out after {timeout} s")
    except OSError as exc:
        return subprocess.CompletedProcess(cmd, -1, "", str(exc))


def _git(path: Path, *args: str, timeout: int = GIT_TIMEOUT) -> subprocess.CompletedProcess:
    return _run(["git", "-c", "core.quotepath=off", "-C", str(path), *args], timeout=timeout)


def _err(proc: subprocess.CompletedProcess) -> str:
    text = (proc.stderr or proc.stdout or "").strip()
    return text.splitlines()[-1] if text else f"exit {proc.returncode}"


def _same(a: str | Path, b: str | Path) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _inside(child: str | Path, parent: str | Path) -> bool:
    """`child` is `parent` or under it (both resolved, case-folded on Windows)."""
    c = os.path.normcase(os.path.realpath(child))
    p = os.path.normcase(os.path.realpath(parent))
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)


# -- gh ---------------------------------------------------------------------------------------------------------

def _slug(main_repo: Path) -> str | None:
    """`owner/name` from the origin URL (https, ssh or scp form), else None."""
    proc = _git(main_repo, "remote", "get-url", "origin")
    url = proc.stdout.strip() if proc.returncode == 0 else ""
    if "://" not in url and "@" not in url:
        return None  # a local path origin has no GitHub name
    match = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$", url)
    return f"{match.group(1)}/{match.group(2)}" if match else None


def gh_pr_lookup(main_repo: Path, branch: str | None, pr: str | None) -> list[dict]:
    slug = _slug(main_repo)
    if not slug:
        raise PrLookupError("cannot read owner/name from the origin URL")
    if pr:
        proc = _run(["gh", "pr", "view", pr, "--repo", slug, "--json", _GH_FIELDS], timeout=NET_TIMEOUT)
    elif branch:
        proc = _run(["gh", "pr", "list", "--repo", slug, "--head", branch, "--state", "all", "--limit", "20",
                     "--json", _GH_FIELDS], timeout=NET_TIMEOUT)
    else:
        return []
    if proc.returncode != 0:
        raise PrLookupError(f"gh failed: {_err(proc)}")
    try:
        data = json.loads(proc.stdout or "null")
    except ValueError as exc:
        raise PrLookupError(f"gh printed bad JSON: {exc}") from exc
    data = [data] if isinstance(data, dict) else data
    if not isinstance(data, list):
        raise PrLookupError("gh printed an unexpected shape")
    return [d for d in data if isinstance(d, dict)]


def _pr_number(value: str | None) -> str | None:
    match = re.search(r"(\d+)\s*$", str(value or ""))
    return match.group(1) if match else None


def _pick_pr(prs: list[dict], branch: str | None, by_number: bool) -> tuple[dict | None, str]:
    """(the merged PR, "") or (None, why the worktree is kept)."""
    if not prs:
        return None, f"no merged PR found: no PR for branch {branch}" if branch else "no merged PR found: no PR"
    open_pr = next((p for p in prs if str(p.get("state", "")).upper() == "OPEN"), None)
    pick = open_pr or prs[0]
    state = str(pick.get("state", "")).upper() or "UNKNOWN"
    if state != "MERGED":
        return None, f"PR #{pick.get('number')} is {state}"
    head_name = pick.get("headRefName")
    if by_number and branch and head_name and head_name != branch:
        return None, f"PR #{pick.get('number')} is for branch {head_name}, not {branch}"
    return pick, ""


# -- worktree ---------------------------------------------------------------------------------------------------

def _main_repo(entry: dict, path: Path) -> Path | None:
    """The repo to list worktrees from: the entry's `repo` when it is a git checkout, else from the path's common dir."""
    for start in (entry.get("repo"), str(path)):
        if not start or not os.path.isdir(start):
            continue
        proc = _git(Path(start), "rev-parse", "--path-format=absolute", "--git-common-dir")
        if proc.returncode == 0 and proc.stdout.strip():
            common = Path(proc.stdout.strip())
            return common.parent if common.name == ".git" else Path(start)
    return None


def _default_branch(wt: Path) -> str:
    proc = _git(wt, "symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD")
    name = proc.stdout.strip() if proc.returncode == 0 else ""
    return name.split("/", 1)[1] if name.startswith("origin/") else "main"


def _ref(wt: Path, rev: str) -> str | None:
    proc = _git(wt, "rev-parse", "-q", "--verify", f"{rev}^{{commit}}")
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else None


def _names(wt: Path, a: str, b: str) -> set[str] | None:
    proc = _git(wt, "diff", "--name-only", "-z", "--no-renames", "--no-ext-diff", a, b)
    return None if proc.returncode != 0 else {n for n in proc.stdout.split("\0") if n}


def _check_worktree(entry: dict, path: Path, cwd: str, pr_lookup: Callable) -> tuple[str, str, dict]:
    """("REMOVE", reason, facts) or ("KEPT"/"GONE", reason, {})."""
    if entry.get("by") == "roadmap-run":
        return "KEPT", "owned by the roadmap runner", {}
    if not os.path.lexists(path):
        return "GONE", "", {}
    try:
        if safety.is_link(os.lstat(path)):
            return "KEPT", "the folder is a junction or symlink", {}
    except OSError as exc:
        return "KEPT", f"cannot inspect it: {exc}", {}
    repo = _main_repo(entry, path)
    if repo is None:
        return "KEPT", "not a registered linked worktree (no git repo found)", {}
    listing = _git(repo, "worktree", "list", "--porcelain")
    if listing.returncode != 0:
        return "KEPT", f"git worktree list failed: {_err(listing)}", {}
    blocks = safety._worktree_blocks(listing.stdout)
    if not blocks:
        return "KEPT", "git listed no worktrees", {}
    main = Path(blocks[0][0][len("worktree "):])
    if _same(path, main):
        return "KEPT", "it is the main checkout", {}
    block = next((b for b in blocks[1:] if _same(path, b[0][len("worktree "):])), None)
    if block is None:
        return "KEPT", f"not a registered linked worktree of {main}", {}
    if _inside(cwd, path):
        return "KEPT", "this session is working in it", {}
    status = _git(path, "status", "--porcelain", "--untracked-files=normal")
    if status.returncode != 0:
        return "KEPT", f"git status failed: {_err(status)}", {}
    if status.stdout.strip():
        return "KEPT", "uncommitted changes", {}
    if any(line == "locked" or line.startswith("locked ") for line in block):
        return "KEPT", "it is locked", {}
    sym = _git(path, "symbolic-ref", "--short", "-q", "HEAD")
    branch = sym.stdout.strip() if sym.returncode == 0 and sym.stdout.strip() else (entry.get("branch") or None)
    default = _default_branch(path)
    if branch and branch == default:
        return "KEPT", f"it is on the default branch {default}", {}
    pr = _pr_number(entry.get("pr"))
    if not branch and not pr:
        return "KEPT", "no merged PR found: no branch and no PR in the record", {}
    try:
        prs = pr_lookup(main, branch, pr)
    except PrLookupError as exc:
        return "KEPT", f"no merged PR found: {exc}", {}
    except Exception as exc:  # noqa: BLE001 - any lookup failure keeps the worktree
        return "KEPT", f"no merged PR found: lookup failed: {exc}", {}
    merged, why = _pick_pr(prs, branch, by_number=bool(pr))
    if merged is None:
        return "KEPT", why, {}
    number = str(merged.get("number") or pr or "?")
    head = _ref(path, "HEAD")
    if not head:
        return "KEPT", "cannot read HEAD", {}
    pr_head = str(merged.get("headRefOid") or "").strip().lower()
    if not pr_head or not _ref(path, pr_head):  # a reused branch name: without the PR head, nothing proves HEAD landed
        return "KEPT", f"PR #{number} head commit is not in the local repo", {}
    after = _git(path, "rev-list", "--max-count=1", f"{pr_head}..HEAD")
    if after.returncode != 0:
        return "KEPT", f"git rev-list failed: {_err(after)}", {}
    if after.stdout.strip():
        return "KEPT", f"commits after the merged PR #{number}", {}
    fetch = _git(path, "fetch", "--quiet", "--no-tags", "origin",
                 f"+refs/heads/{default}:refs/remotes/origin/{default}", timeout=NET_TIMEOUT)
    if fetch.returncode != 0:
        return "KEPT", f"cannot fetch origin/{default}: {_err(fetch)}", {}
    target = f"refs/remotes/origin/{default}"
    base = _git(path, "merge-base", target, "HEAD")
    if base.returncode != 0 or not base.stdout.strip():
        return "KEPT", f"no merge base with origin/{default}", {}
    changed = _names(path, base.stdout.strip(), "HEAD")
    differ_all = _names(path, target, "HEAD")
    if changed is None or differ_all is None:
        return "KEPT", f"git diff against origin/{default} failed", {}
    differ = sorted(changed & differ_all)
    if differ:
        return "KEPT", f"{len(differ)} file(s) differ from origin/{default}: {', '.join(differ[:3])}", {}
    facts = {"repo": main, "branch": branch, "pr": number, "pr_head": pr_head, "head": head}
    return "REMOVE", f"PR #{number} merged, clean, tree equals origin/{default}", facts


def _branch_tip(repo: Path, branch: str) -> str | None:
    proc = _git(repo, "rev-parse", "-q", "--verify", f"refs/heads/{branch}")
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else None


def _remove_worktree(path: Path, facts: dict) -> tuple[str, str]:
    repo, branch, head, pr_head = facts["repo"], facts["branch"], facts["head"], facts["pr_head"]
    local_tip = _branch_tip(repo, branch) if branch else None
    problem = safety.safe_remove_worktree(repo, path, force=False, env=_env())
    if problem:
        return "FAILED", problem
    notes: list[str] = []
    if branch and local_tip:
        listing = _git(repo, "worktree", "list", "--porcelain")
        if listing.returncode != 0 or f"branch refs/heads/{branch}" in listing.stdout.splitlines():
            notes.append("local branch kept: another worktree has it checked out")
        elif local_tip not in {head, pr_head}:
            notes.append("local branch kept: its tip is not the removed HEAD or the PR head")
        else:
            gone = _git(repo, "branch", "-D", "--", branch)
            notes.append("local branch deleted" if gone.returncode == 0 else f"local branch kept: {_err(gone)}")
    if branch:
        ls = _git(repo, "ls-remote", "--heads", "origin", f"refs/heads/{branch}", timeout=NET_TIMEOUT)
        tips = [ln.split()[0] for ln in ls.stdout.splitlines() if ln.strip()] if ls.returncode == 0 else []
        if ls.returncode != 0:
            notes.append(f"remote branch kept: ls-remote failed: {_err(ls)}")
        elif tips:
            tip = tips[0].lower()
            if tip in {pr_head, head.lower()} - {""}:  # only a tip this check proved landed
                try:
                    push = _git(repo, *safety.remote_delete_args(branch, tip), timeout=NET_TIMEOUT)
                    notes.append("remote branch deleted" if push.returncode == 0
                                 else f"remote branch kept: {_err(push)}")
                except ValueError as exc:
                    notes.append(f"remote branch kept: {exc}")
            else:
                notes.append("remote branch kept: its tip moved past the PR head")
    return "REMOVED", "; ".join(notes)


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
