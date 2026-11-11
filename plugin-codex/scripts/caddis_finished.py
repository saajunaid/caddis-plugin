"""Is this worktree or branch finished? One definition, shared by the session-start report and tidy.

Phase 1 of `.caddis/plans/repo-hygiene-report.md`: the pure core, ported 1:1 from the fleet's PowerShell report
`bootstrap/report-stale-worktrees.ps1` (`Get-SessionIdFromPath`, `Get-SessionIdleMinutes`, `Get-WorktreeState`,
`Test-HasLinkedWorktrees`, the porcelain reader and the single-repo Group-Object fix), plus the report-grade branch
state. Stdlib only. Importing this module starts no process and scans nothing.

    session_id_from_path(path)               -> the owning session id of a scratchpad worktree, or None
    session_idle_minutes(id, root, now)      -> minutes since that session wrote its transcript; -1 = UNKNOWN
    worktree_state(exists, dirty, owned, ..) -> "orphan-registration" | "DIRTY" | "removable" | "IN USE" |
                                                "idle-session"
    has_linked_worktrees(git_dir)            -> False proves there is nothing to report (no git spawn needed)
    parse_worktree_porcelain(text)           -> [{"path", "branch", "locked"}], main working tree first
    count_by_repo(findings)                  -> [(repo, count)], count descending, then name
    branch_report_state(tip, prs, is_anc)    -> (state, reason) from the cheap PR list; report-grade, never deletes

Phase 2: the DELETION-grade proofs, moved from `caddis_own_cleanup.py` (which keeps its old private names as
aliases), so "finished" has one definition for `/handoff` own-cleanup and `caddis_tidy.py --hygiene`:

    prove_worktree_finished(entry, path, cwd, pr_lookup) -> ("REMOVE", reason, facts) | ("KEPT"/"GONE", reason, {})
    prove_branch_finished(repo, branch, pr_lookup)       -> ("REMOVE", reason, facts) | ("KEPT"/"TRIAGE", reason, {})
    remove_finished(path | None, facts, remover=None)    -> ("REMOVED" | "FAILED", notes); path None = branches only

`pr_lookup(main_repo, branch, pr) -> list[{number, state, headRefOid, headRefName}]` (newest first) is the gh seam;
it raises PrLookupError. `gh_pr_lookup` calls plain `gh` with the inherited environment (never `gh auth switch`).
Anything in doubt is KEPT. TRIAGE (no PR, or a CLOSED unmerged PR) is never removed. These functions run git and gh
when CALLED; `caddis_worktree_safety` is imported inside them only, so the pure functions above need nothing else.

The invariant (measured 2026-09-11: of 19 worktrees the old logic called removable, 15 belonged to a session that was
running at that moment): evidence that a session is ALIVE never produces `removable`. The converse keeps the report
useful: the absence of that evidence is not proof the session ended, so it yields the weaker `idle-session`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path

ACTIVE_WITHIN_MINUTES: int = 60

_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def session_id_from_path(path: str | None) -> str | None:
    """The owning session id of a scratchpad worktree, or None.

    A scratchpad worktree lives at `<temp>/claude/<encoded-project>/<session-id>/scratchpad/<name>`, so the owning
    session id is the segment before `scratchpad`. A session id is a uuid: matching the SHAPE keeps a folder that
    merely sits above a scratchpad from being read as one. Any other path has no owning session.
    """
    if not path:
        return None
    parts = path.replace("\\", "/").split("/")
    for i in range(1, len(parts)):
        if parts[i] == "scratchpad" and _UUID.match(parts[i - 1]):
            return parts[i - 1]
    return None


def session_idle_minutes(session_id: str | None, projects_root: Path | None = None, now: float | None = None) -> int:
    """Minutes since the owning session last wrote `<session_id>.jsonl` under `projects_root`, or -1.

    -1 means UNKNOWN (no id, no root, no transcript), never "0 minutes ago": conflating the two is how a guard
    inverts itself. A transcript dated in the future (clock skew) reads as 0, never as -1, because -1 is the
    reading that can lead to `removable`.
    """
    if not session_id:
        return -1
    root = projects_root if projects_root is not None else Path.home() / ".claude" / "projects"
    if not root.is_dir():
        return -1
    name = f"{session_id}.jsonl"
    for dirpath, _dirs, files in os.walk(root):
        if name in files:
            try:
                mtime = os.stat(os.path.join(dirpath, name)).st_mtime
            except OSError:
                return -1
            current = time.time() if now is None else now
            return max(0, int((current - mtime) // 60))
    return -1


def worktree_state(exists: bool, dirty: bool, has_owning_session: bool, session_idle_minutes: int = -1,
                   active_within_minutes: int = ACTIVE_WITHIN_MINUTES) -> str:
    """PURE classification of one linked worktree, in the order of `Get-WorktreeState`.

    orphan (folder gone) > DIRTY > no owning session = removable > written within the window = IN USE >
    any other reading = idle-session > -1 (session id in the path but no transcript at all) = removable.

    The idle minutes default to -1, an ordinary int that cannot be confused with a real reading. (The PowerShell
    original avoided [Nullable[int]] because PowerShell unwraps it to 0 at binding, so "unknown" became "active 0
    minutes ago".) A recent write PROVES live. No write proves nothing, so it never earns `removable`.
    `removable` here means "nothing uncommitted would be lost and nobody is using it"; tidy still requires a merged
    proof before it removes anything.
    """
    if not exists:
        return "orphan-registration"
    if dirty:
        return "DIRTY"
    if not has_owning_session:
        return "removable"
    if 0 <= session_idle_minutes <= active_within_minutes:
        return "IN USE"
    if session_idle_minutes >= 0:
        return "idle-session"
    return "removable"  # a session id in the path but no transcript at all: the session is gone


def has_linked_worktrees(git_dir: Path) -> bool:
    """True when `<git_dir>/worktrees` holds at least one registration, a stale one too.

    Git records every linked worktree there, so a missing or empty folder proves there is nothing to report and the
    repo needs no `git worktree list` spawn (measured 2026-09-26: those spawns were 1.1 s of a 2.1 s hook).
    """
    wt_dir = Path(git_dir) / "worktrees"
    try:
        with os.scandir(wt_dir) as entries:
            return any(e.is_dir() for e in entries)
    except OSError:
        return False


def parse_worktree_porcelain(text: str) -> list[dict]:
    """`git worktree list --porcelain` -> one dict per block: {"path", "branch", "locked"}.

    `branch` is the name after `refs/heads/`, or "(detached)". The first dict is the main working tree.
    """
    records: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        if line.startswith("worktree "):
            if current is not None:
                records.append(current)
            current = {"path": line[len("worktree "):], "branch": "(detached)", "locked": False}
        elif current is None:
            continue
        elif line.startswith("branch refs/heads/"):
            current["branch"] = line[len("branch refs/heads/"):]
        elif line == "locked" or line.startswith("locked "):
            current["locked"] = True
    if current is not None:
        records.append(current)
    return records


def count_by_repo(findings: list[dict]) -> list[tuple[str, int]]:
    """Group findings on `finding["repo"]`: [(repo, count)], count descending, then name.

    Always a list of groups. The PowerShell original needed `@()` around Group-Object: with a SINGLE repo it
    returned one group, and `.Count` then read that group's member count ("3 repos" for one repo).
    """
    counts = Counter(f["repo"] for f in findings)
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def branch_report_state(tip: str, prs: list[dict], is_ancestor: Callable[[str, str], bool]) -> tuple[str, str]:
    """REPORT-grade state of one local branch, from the cheap PR list. It never decides a deletion.

    `prs` are the PRs whose `headRefName` equals the branch, newest first. Any OPEN PR wins. Otherwise the newest
    PR decides: MERGED counts as merged-not-deleted only when the tip IS the merged head or an ancestor of it.
    A tip with commits after the merged head (a reused name), a CLOSED PR, or no PR is needs-triage.
    """
    for pr in prs:
        if pr.get("state") == "OPEN":
            return "open-pr", f"PR #{pr.get('number')} open"
    if not prs:
        return "needs-triage", "no PR"
    newest = prs[0]
    number = newest.get("number")
    if newest.get("state") == "MERGED":
        head = newest.get("headRefOid") or ""
        if head and (tip == head or is_ancestor(tip, head)):
            return "merged-not-deleted", f"PR #{number} merged"
        return "needs-triage", f"commits after merged PR #{number}"
    return "needs-triage", f"PR #{number} closed unmerged"


# ================================================================ Phase 2: the deletion-grade proofs (run git and gh)
# Moved from caddis_own_cleanup.py with the same bodies; the old private names stay there as aliases.

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

def repo_slug(main_repo: Path) -> str | None:
    """`owner/name` from the origin URL (https, ssh or scp form), else None."""
    proc = _git(main_repo, "remote", "get-url", "origin")
    return slug_from_url(proc.stdout.strip() if proc.returncode == 0 else "")


def slug_from_url(url: str) -> str | None:
    """PURE: `owner/name` from an origin URL (https, ssh or scp form), else None. The session-start hook reads the
    URL through its own no-console-window seam and parses it here, so the rule stays in one place."""
    if "://" not in url and "@" not in url:
        return None  # a local path origin has no GitHub name
    match = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$", url)
    return f"{match.group(1)}/{match.group(2)}" if match else None


def gh_pr_lookup(main_repo: Path, branch: str | None, pr: str | None) -> list[dict]:
    slug = repo_slug(main_repo)
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


def pr_number(value: str | None) -> str | None:
    match = re.search(r"(\d+)\s*$", str(value or ""))
    return match.group(1) if match else None


def pick_pr(prs: list[dict], branch: str | None, by_number: bool) -> tuple[dict | None, str]:
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


# -- git facts --------------------------------------------------------------------------------------------------

def main_repo(entry: dict, path: Path) -> Path | None:
    """The repo to list worktrees from: the entry's `repo` when it is a git checkout, else from the path's common dir."""
    for start in (entry.get("repo"), str(path)):
        if not start or not os.path.isdir(start):
            continue
        proc = _git(Path(start), "rev-parse", "--path-format=absolute", "--git-common-dir")
        if proc.returncode == 0 and proc.stdout.strip():
            common = Path(proc.stdout.strip())
            return common.parent if common.name == ".git" else Path(start)
    return None


def default_branch(wt: Path) -> str:
    proc = _git(wt, "symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD")
    name = proc.stdout.strip() if proc.returncode == 0 else ""
    return name.split("/", 1)[1] if name.startswith("origin/") else "main"


def ref(wt: Path, rev: str) -> str | None:
    proc = _git(wt, "rev-parse", "-q", "--verify", f"{rev}^{{commit}}")
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else None


def changed_names(wt: Path, a: str, b: str) -> set[str] | None:
    proc = _git(wt, "diff", "--name-only", "-z", "--no-renames", "--no-ext-diff", a, b)
    return None if proc.returncode != 0 else {n for n in proc.stdout.split("\0") if n}


def branch_tip(repo: Path, branch: str) -> str | None:
    proc = _git(repo, "rev-parse", "-q", "--verify", f"refs/heads/{branch}")
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else None


def _landed(where: Path, rev: str, number: str, pr_head: str, default: str) -> str | None:
    """None when `rev` has no commit after the merged PR head and every file it changed equals origin/<default>.

    Else why not. The squash-merge proof: fetch origin/<default> first, then compare only the files `rev` changed
    since the merge base (a later commit on the default branch to another file does not block it). Shared by both
    proofs, with `rev` = HEAD (worktree) or `refs/heads/<branch>` (branch), so the check is written once.
    """
    after = _git(where, "rev-list", "--max-count=1", f"{pr_head}..{rev}")
    if after.returncode != 0:
        return f"git rev-list failed: {_err(after)}"
    if after.stdout.strip():
        return f"commits after the merged PR #{number}"
    fetch = _git(where, "fetch", "--quiet", "--no-tags", "origin",
                 f"+refs/heads/{default}:refs/remotes/origin/{default}", timeout=NET_TIMEOUT)
    if fetch.returncode != 0:
        return f"cannot fetch origin/{default}: {_err(fetch)}"
    target = f"refs/remotes/origin/{default}"
    base = _git(where, "merge-base", target, rev)
    if base.returncode != 0 or not base.stdout.strip():
        return f"no merge base with origin/{default}"
    changed = changed_names(where, base.stdout.strip(), rev)
    differ_all = changed_names(where, target, rev)
    if changed is None or differ_all is None:
        return f"git diff against origin/{default} failed"
    differ = sorted(changed & differ_all)
    if differ:
        return f"{len(differ)} file(s) differ from origin/{default}: {', '.join(differ[:3])}"
    return None


# -- the proofs -------------------------------------------------------------------------------------------------

def prove_worktree_finished(entry: dict, path: Path, cwd: str, pr_lookup: Callable) -> tuple[str, str, dict]:
    """("REMOVE", reason, facts) or ("KEPT"/"GONE", reason, {}). An owner-specific KEPT is the caller's, first."""
    import caddis_worktree_safety as safety

    if not os.path.lexists(path):
        return "GONE", "", {}
    try:
        if safety.is_link(os.lstat(path)):
            return "KEPT", "the folder is a junction or symlink", {}
    except OSError as exc:
        return "KEPT", f"cannot inspect it: {exc}", {}
    repo = main_repo(entry, path)
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
    default = default_branch(path)
    if branch and branch == default:
        return "KEPT", f"it is on the default branch {default}", {}
    pr = pr_number(entry.get("pr"))
    if not branch and not pr:
        return "KEPT", "no merged PR found: no branch and no PR in the record", {}
    try:
        prs = pr_lookup(main, branch, pr)
    except PrLookupError as exc:
        return "KEPT", f"no merged PR found: {exc}", {}
    except Exception as exc:  # noqa: BLE001 - any lookup failure keeps the worktree
        return "KEPT", f"no merged PR found: lookup failed: {exc}", {}
    merged, why = pick_pr(prs, branch, by_number=bool(pr))
    if merged is None:
        return "KEPT", why, {}
    number = str(merged.get("number") or pr or "?")
    head = ref(path, "HEAD")
    if not head:
        return "KEPT", "cannot read HEAD", {}
    pr_head = str(merged.get("headRefOid") or "").strip().lower()
    if not pr_head or not ref(path, pr_head):  # a reused branch name: without the PR head, nothing proves HEAD landed
        return "KEPT", f"PR #{number} head commit is not in the local repo", {}
    problem = _landed(path, "HEAD", number, pr_head, default)
    if problem:
        return "KEPT", problem, {}
    facts = {"repo": main, "branch": branch, "pr": number, "pr_head": pr_head, "head": head}
    return "REMOVE", f"PR #{number} merged, clean, tree equals origin/{default}", facts


def _triage(repo: Path, branch: str, default: str, why: str) -> tuple[str, str, dict]:
    """TRIAGE is never removed. The reason carries the branch's age (last commit date) and its own-commit count."""
    ct = _git(repo, "log", "-1", "--format=%ct", f"refs/heads/{branch}")
    try:
        age = f"{max(0, int(time.time() - int(ct.stdout.strip())) // 86400)}d"
    except ValueError:
        age = "?d"
    count = _git(repo, "rev-list", "--count", f"refs/remotes/origin/{default}..refs/heads/{branch}")
    own = count.stdout.strip() if count.returncode == 0 and count.stdout.strip().isdigit() else "?"
    return "TRIAGE", f"{why}, {age} old, {own} own commits", {}


def prove_branch_finished(repo: Path, branch: str, pr_lookup: Callable) -> tuple[str, str, dict]:
    """A local branch: ("REMOVE", reason, facts), ("KEPT", reason, {}) or ("TRIAGE", reason, {}).

    The same merged-PR, head and squash checks as `prove_worktree_finished`, against `refs/heads/<branch>` instead
    of HEAD. No PR, or a CLOSED unmerged newest PR, is TRIAGE. The default branch, a branch checked out in any
    worktree, an OPEN PR, a lookup failure or any other doubt is KEPT.
    """
    default = default_branch(repo)
    if branch == default:
        return "KEPT", f"it is the default branch {default}", {}
    tip = branch_tip(repo, branch)
    if not tip:
        return "KEPT", f"no local branch {branch}", {}
    listing = _git(repo, "worktree", "list", "--porcelain")
    if listing.returncode != 0:
        return "KEPT", f"git worktree list failed: {_err(listing)}", {}
    holder = next((w for w in parse_worktree_porcelain(listing.stdout) if w["branch"] == branch), None)
    if holder is not None:
        return "KEPT", f"checked out in {holder['path']}", {}
    try:
        prs = pr_lookup(repo, branch, None)
    except PrLookupError as exc:
        return "KEPT", f"no merged PR found: {exc}", {}
    except Exception as exc:  # noqa: BLE001 - any lookup failure keeps the branch
        return "KEPT", f"no merged PR found: lookup failed: {exc}", {}
    if not prs:
        return _triage(repo, branch, default, "no PR")
    open_pr = next((p for p in prs if str(p.get("state", "")).upper() == "OPEN"), None)
    if open_pr is not None:
        return "KEPT", f"PR #{open_pr.get('number')} is open", {}
    newest = prs[0]
    number = str(newest.get("number") or "?")
    state = str(newest.get("state", "")).upper() or "UNKNOWN"
    if state == "CLOSED":
        return _triage(repo, branch, default, f"PR #{number} closed unmerged")
    if state != "MERGED":
        return "KEPT", f"PR #{number} is {state}", {}
    head_name = newest.get("headRefName")
    if head_name and head_name != branch:
        return "KEPT", f"PR #{number} is for branch {head_name}, not {branch}", {}
    pr_head = str(newest.get("headRefOid") or "").strip().lower()
    if not pr_head or not ref(repo, pr_head):  # a reused branch name: without the PR head, nothing proves it landed
        return "KEPT", f"PR #{number} head commit is not in the local repo", {}
    problem = _landed(repo, f"refs/heads/{branch}", number, pr_head, default)
    if problem:
        return "KEPT", problem, {}
    facts = {"repo": repo, "branch": branch, "pr": number, "pr_head": pr_head, "head": tip}
    return "REMOVE", f"PR #{number} merged, tree equals origin/{default}", facts


def remove_finished(path: Path | None, facts: dict, remover: Callable | None = None,
                    branches_first: bool = False) -> tuple[str, str]:
    """Remove what a proof returned REMOVE for: ("REMOVED", notes) or ("FAILED", problem).

    `path` None skips the worktree step and removes only the branches; then any kept branch is "FAILED", so a
    caller that reads only the outcome never reports a kept branch as removed. Worktree: `safe_remove_worktree(...,
    force=False)` (links first, never --force). Local branch: only while its tip is HEAD or the PR head and no
    worktree has it checked out. Remote branch: only while its tip is the PR head or HEAD, as one compare-and-delete
    push. `remover(path) -> None | problem` replaces `git worktree remove` (an Orca worktree goes through Orca).
    `branches_first`: detach the worktree's HEAD, delete the branches, then remove the worktree. For a session that
    removes its own Orca worktree: the removal stops that session, so nothing may be left to do after it.
    """
    import caddis_worktree_safety as safety

    repo, branch, head, pr_head = facts["repo"], facts["branch"], facts["head"], facts["pr_head"]
    landed = {pr_head, head.lower()} - {""}  # only tips this proof showed landed
    if path is not None and branches_first:
        if branch:  # update-ref detaches without running a post-checkout hook (git switch would run it)
            detach = _git(path, "update-ref", "--no-deref", "HEAD", head)
            if detach.returncode != 0:
                return "FAILED", f"git update-ref --no-deref HEAD failed: {_err(detach)}"
        notes = _delete_branches(repo, branch, landed)
        problem = safety.safe_remove_worktree(repo, path, force=False, env=_env(), remover=remover)
        if problem:
            return "FAILED", "; ".join([problem, *notes, "HEAD was detached and the branches went first"])
        return "REMOVED", "; ".join(notes)
    local_tip = branch_tip(repo, branch) if branch else None
    if path is not None:
        problem = safety.safe_remove_worktree(repo, path, force=False, env=_env(), remover=remover)
        if problem:
            return "FAILED", problem
    notes = _delete_branches(repo, branch, landed, local_tip)
    if path is None and any(" branch kept:" in n for n in notes):
        return "FAILED", "; ".join(notes)
    return "REMOVED", "; ".join(notes)


def _delete_branches(repo: Path, branch: str | None, landed: set[str], local_tip: str | None = None) -> list[str]:
    """Delete the local and the remote `branch`, each only while its tip is one the proof showed landed."""
    import caddis_worktree_safety as safety

    notes: list[str] = []
    if not branch:
        return notes
    local_tip = local_tip or branch_tip(repo, branch)
    if local_tip:
        listing = _git(repo, "worktree", "list", "--porcelain")
        if listing.returncode != 0 or f"branch refs/heads/{branch}" in listing.stdout.splitlines():
            notes.append("local branch kept: another worktree has it checked out")
        elif local_tip.lower() not in landed:
            notes.append("local branch kept: its tip is not the removed HEAD or the PR head")
        else:
            gone = _git(repo, "branch", "-D", "--", branch)
            notes.append("local branch deleted" if gone.returncode == 0 else f"local branch kept: {_err(gone)}")
    ls = _git(repo, "ls-remote", "--heads", "origin", f"refs/heads/{branch}", timeout=NET_TIMEOUT)
    tips = [ln.split()[0] for ln in ls.stdout.splitlines() if ln.strip()] if ls.returncode == 0 else []
    if ls.returncode != 0:
        notes.append(f"remote branch kept: ls-remote failed: {_err(ls)}")
    elif tips:
        tip = tips[0].lower()
        if tip in landed:
            try:
                push = _git(repo, *safety.remote_delete_args(branch, tip), timeout=NET_TIMEOUT)
                notes.append("remote branch deleted" if push.returncode == 0 else f"remote branch kept: {_err(push)}")
            except ValueError as exc:
                notes.append(f"remote branch kept: {exc}")
        else:
            notes.append("remote branch kept: its tip moved past the PR head")
    return notes
