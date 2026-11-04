#!/usr/bin/env python3
"""caddis_tidy.py --hygiene: list every worktree and local branch of one repo, and remove only what is proved finished.

Dry run is the default; only `apply=True` acts. Every row gets one action and a reason:

  REMOVE   proved finished (dry run)              REMOVED  removed (--apply)
  KEPT     a guard holds it, the reason says which TRIAGE   no PR or a CLOSED unmerged PR: listed, never removed
  GONE     the folder vanished before removal     FAILED   removal was tried and did not complete

Order per linked worktree, first match wins: orphan registration (folder gone) -> a junction or symlink -> the
process cwd is inside it -> Orca-managed -> DIRTY (incl. untracked) -> IN USE -> idle-session -> locked -> the
deletion-grade proof `caddis_finished.prove_worktree_finished` (merged PR, no commit after its head, every changed
file equals origin/<default>). A branch with no worktree gets `caddis_finished.prove_branch_finished`.

The live-session rule is the PowerShell report's: a transcript written within 60 min PROVES a session is live;
an older one proves nothing (idle-session, KEPT). A session id with no transcript is "removable" to the classifier,
but tidy still needs the merged proof. Removal goes through `caddis_finished.remove_finished` (links first,
`force=False`, compare-and-delete push), so the rules live in one place.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import caddis_finished as cf

ORCA_TIMEOUT_S = 10.0
_ACTIONS = ("REMOVE", "REMOVED", "KEPT", "TRIAGE", "GONE", "FAILED")


def _key(path: str | Path) -> str:
    return os.path.normcase(os.path.realpath(path))


def orca_lookup(run: Callable = subprocess.run, which: Callable = shutil.which,
                timeout_s: float = ORCA_TIMEOUT_S) -> tuple[dict[str, str] | None, str]:
    """({normcase(realpath(path)): id}, "") from `orca worktree list`, or (None, why) when the list cannot be trusted.

    None (not on PATH, non-zero exit, timeout, bad JSON, `ok` false, `truncated` true) means NO worktree counts as
    Orca-managed; the caller prints the reason every run (plan decision 7).
    """
    if not which("orca"):
        return None, "orca not on PATH"
    cmd = ["orca", "worktree", "list", "--limit", "10000", "--json"]
    try:
        proc = run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                   stdin=subprocess.DEVNULL, timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired:
        return None, f"orca took longer than {timeout_s:g} s"
    except OSError as exc:
        return None, f"orca could not start: {exc}"
    if proc.returncode != 0:
        text = (proc.stderr or proc.stdout or "").strip()
        return None, f"orca failed: {text.splitlines()[-1] if text else f'exit {proc.returncode}'}"
    try:
        data = json.loads(proc.stdout or "null")
    except ValueError:
        return None, "orca printed bad JSON"
    if not isinstance(data, dict) or not data.get("ok"):
        return None, "orca answered not ok"
    result = data.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("worktrees"), list):
        return None, "orca printed an unexpected shape"
    if result.get("truncated"):
        return None, "orca list is truncated"
    ids: dict[str, str] = {}
    for wt in result["worktrees"]:
        if isinstance(wt, dict) and wt.get("path") and wt.get("id"):
            ids[_key(str(wt["path"]))] = str(wt["id"])
    return ids, ""


def _row(kind: str, name: str, path: str | None, action: str, reason: str) -> dict:
    return {"kind": kind, "name": name, "path": path, "action": action, "reason": reason}


def _triage_reason(reason: str) -> str | None:
    """The `why` for TRIAGE when a KEPT proof reason means "no PR" or "a CLOSED unmerged PR", else None."""
    if reason.startswith("no merged PR found: no PR"):
        return "no PR"
    if reason.startswith("PR #") and reason.endswith(" is CLOSED"):
        return f"{reason[:-len(' is CLOSED')]} closed unmerged"
    return None


def _listing(repo: Path) -> list[dict] | None:
    proc = cf._git(repo, "worktree", "list", "--porcelain")
    return cf.parse_worktree_porcelain(proc.stdout) if proc.returncode == 0 else None


def _prune(repo: Path, path: str) -> tuple[str, str]:
    proc = cf._git(repo, "worktree", "prune")
    if proc.returncode != 0:
        return "FAILED", f"git worktree prune failed: {cf._err(proc)}"
    after = _listing(repo)
    if after is None:
        return "FAILED", "git worktree list failed after the prune"
    if any(_key(w["path"]) == _key(path) for w in after):
        return "FAILED", "git kept the registration"
    return "REMOVED", "registration pruned"


def _worktree_row(repo: Path, rec: dict, *, default: str, cwd: str, orca: dict[str, str] | None,
                  pr_lookup: Callable, projects_root: Path | None, now: float | None) -> tuple[dict, dict]:
    """(row, facts) for one linked worktree; facts is non-empty only for REMOVE from the merged proof."""
    path, branch = rec["path"], rec["branch"]
    name = branch

    def row(action: str, reason: str) -> tuple[dict, dict]:
        return _row("worktree", name, path, action, reason), {}

    if not os.path.lexists(path):
        if rec["locked"]:
            return row("KEPT", "folder gone but locked; git worktree prune keeps it")
        return _row("worktree", name, path, "REMOVE", "folder gone; git worktree prune"), {"orphan": True}
    try:
        import caddis_worktree_safety as safety

        if safety.is_link(os.lstat(path)):
            return row("KEPT", "the folder is a junction or symlink")
    except OSError as exc:
        return row("KEPT", f"cannot inspect it: {exc}")
    if cf._inside(cwd, path):
        return row("KEPT", "this session is working in it")
    if orca is not None and _key(path) in orca:
        return row("KEPT", f"Orca-managed: remove it in Orca (`orca worktree rm --worktree id:{orca[_key(path)]}`)")
    status = cf._git(Path(path), "status", "--porcelain", "--untracked-files=normal")
    if status.returncode != 0:
        return row("KEPT", f"git status failed: {cf._err(status)}")
    session = cf.session_id_from_path(path)
    idle = cf.session_idle_minutes(session, projects_root, now) if session else -1
    state = cf.worktree_state(True, bool(status.stdout.strip()), session is not None, idle)
    if state == "DIRTY":
        return row("KEPT", "DIRTY: uncommitted changes (incl. untracked)")
    if state == "IN USE":
        return row("KEPT", f"IN USE: session {session[:8]} wrote {idle} min ago")
    if state == "idle-session":
        return row("KEPT", f"owned by session {session[:8]}, idle {idle} min; not proof it ended")
    if state != "removable":
        return row("KEPT", f"unexpected state {state}")
    if rec["locked"]:
        return row("KEPT", "it is locked")
    entry = {"repo": str(repo), "branch": None if branch == "(detached)" else branch}
    action, reason, facts = cf.prove_worktree_finished(entry, Path(path), cwd, pr_lookup)
    if action == "KEPT":
        why = _triage_reason(reason)
        if why and entry["branch"]:
            action, reason, _ = cf._triage(repo, branch, default, why)
    return _row("worktree", name, path, action, reason), facts


def _local_branches(repo: Path) -> list[str] | None:
    proc = cf._git(repo, "for-each-ref", "--format=%(refname)", "refs/heads")
    if proc.returncode != 0:
        return None
    return [ln[len("refs/heads/"):] for ln in proc.stdout.splitlines() if ln.startswith("refs/heads/")]


def tidy_repo(repo_root: Path, *, apply: bool = False, cwd: str | None = None, pr_lookup: Callable | None = None,
              orca_lookup: Callable | None = None, projects_root: Path | None = None,
              now: float | None = None) -> tuple[list[dict], list[str]]:
    """(rows, notes) for every worktree and every local non-default branch with no worktree. `apply` acts on REMOVE."""
    pr_lookup = pr_lookup or cf.gh_pr_lookup
    ask_orca = orca_lookup or globals()["orca_lookup"]
    cwd = cwd or os.getcwd()
    now = time.time() if now is None else now
    notes: list[str] = []
    repo = cf.main_repo({"repo": str(repo_root)}, Path(repo_root))
    if repo is None:
        return [], [f"[TIDY] skipped: {repo_root} is not a git repository"]
    records = _listing(repo)
    if not records:  # None (git failed) or empty (unparseable): never guess which is the main checkout
        return [], ["[TIDY] skipped: git worktree list failed or was empty; nothing is listed or removed"]
    default = cf.default_branch(repo)
    rows: list[dict] = []
    main, linked = records[0], records[1:]
    rows.append(_row("worktree", main["branch"], main["path"], "KEPT", "it is the main checkout"))
    orca: dict[str, str] | None = {}
    if linked:
        orca, why = ask_orca()
        if orca is None:
            notes.append(f"[TIDY] skipped: Orca check - {why}; no worktree is treated as Orca-managed")
    for rec in linked:
        row, facts = _worktree_row(repo, rec, default=default, cwd=cwd, orca=orca, pr_lookup=pr_lookup,
                                   projects_root=projects_root, now=now)
        if apply and row["action"] == "REMOVE":
            if facts.get("orphan"):  # no folder and no PR proof: only the registration goes, never a branch
                row["action"], row["reason"] = _prune(repo, rec["path"])
            elif not os.path.lexists(rec["path"]):
                row["action"], row["reason"] = "GONE", "the folder vanished before removal"
            else:
                row["action"], row["reason"] = cf.remove_finished(Path(rec["path"]), facts)
        rows.append(row)
    branches = _local_branches(repo)
    if branches is None:
        notes.append("[TIDY] skipped: branches - git for-each-ref failed; no branch is listed or removed")
        return rows, notes
    checked_out = {rec["branch"] for rec in records}
    for branch in branches:
        if branch == default or branch in checked_out:
            continue  # the default branch is never a candidate; a checked-out branch is its worktree's row
        action, reason, facts = cf.prove_branch_finished(repo, branch, pr_lookup)
        if apply and action == "REMOVE":
            action, reason = cf.remove_finished(None, facts)
        rows.append(_row("branch", branch, None, action, reason))
    return rows, notes


def print_rows(rows: list[dict], notes: list[str], apply: bool) -> None:
    """The notes, one line per row, then `[TIDY] <would remove|removed> <n>, kept <n>, triage <n>, gone <n>, failed <n>`."""
    for note in notes:
        print(note)
    for r in rows:
        where = f" ({r['path']})" if r["path"] else ""
        print(f"[TIDY] {r['action']:<7} {r['kind']:<8} {r['name']}{where}: {r['reason']}")
    n = {a: sum(1 for r in rows if r["action"] == a) for a in _ACTIONS}
    done = f"removed {n['REMOVED']}" if apply else f"would remove {n['REMOVE']}"
    print(f"[TIDY] {done}, kept {n['KEPT']}, triage {n['TRIAGE']}, gone {n['GONE']}, failed {n['FAILED']}")


def run_cli(repo_root: Path, *, apply: bool, as_json: bool) -> int:
    """`caddis_tidy.py --hygiene`: 0 when nothing failed, 1 when a removal FAILED, 2 when the repo cannot be read."""
    rows, notes = tidy_repo(Path(repo_root), apply=apply)
    if as_json:
        print(json.dumps({"apply": apply, "rows": [dict(r, path=None if r["path"] is None else str(r["path"]))
                                                   for r in rows], "notes": notes}, indent=2))
    else:
        print(f"[TIDY] hygiene {'APPLY' if apply else 'DRY-RUN'} {repo_root}")
        print_rows(rows, notes, apply)
    if not rows:
        return 2
    return 1 if any(r["action"] == "FAILED" for r in rows) else 0
