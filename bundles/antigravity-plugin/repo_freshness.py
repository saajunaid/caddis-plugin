"""SessionStart: where this checkout stands against the remote default branch.

WHY IT FETCHES. Nobody runs git by hand before opening an agent — so without a fetch,
`origin/main` is whatever it was last time. The agent then branches from a stale ref and
believes it is current. The fetch is what makes every later "branch from origin/main"
mean the newest main. One consumer repo carries the same lesson as a rule of its own:
audit `origin/main`, never the working tree.

FAIL OPEN, ALWAYS. Every path exits 0 and every git call is wrapped. A hook that can hang
or fail a session start is worse than the staleness it prevents, so a failed or slow fetch
reports and continues.

IT ONLY PRINTS. It never switches, stashes, resets, commits or creates anything except one
throttle stamp inside .git/. A SessionStart hook cannot ask a question, and these checkouts
are shared with other live sessions — acting without an answer could take work with it.

QUIET WHEN THERE IS NOTHING TO SAY. On the default branch, clean and level, it prints
nothing at all, so the output stays worth reading.

Ported into caddis 2026-09-12 from a personal hook that existed on one machine only
(~/.claude/hooks/repo-freshness.sh), so agy gets it too and it is versioned and tested.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

try:
    _cfg_scripts = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
    if _cfg_scripts not in sys.path:
        sys.path.insert(0, _cfg_scripts)
    from claudster_config import ARTIFACT_DIRS, artifact_root  # noqa: E402
except Exception:  # pragma: no cover — defensive; a hook must never crash a session start
    ARTIFACT_DIRS = (".caddis",)

    def artifact_root(root):
        return os.path.join(str(root), ARTIFACT_DIRS[0])

# A narrow Windows console (cp1252) must not raise on a branch name with any Unicode in it.
_reconfig = getattr(sys.stdout, "reconfigure", None)
if _reconfig:
    try:
        _reconfig(encoding="utf-8")
    except Exception:
        pass

FETCH_TIMEOUT_S = 15        # ceiling: a slow or unreachable remote must not stall a session
FETCH_MAX_AGE_S = 600       # a restart within 10 minutes reuses the last fetch
PEER_FRESH_S = 1800         # live peer session-state threshold (30 minutes, matches inject_relay)
STAMP_NAME = "caddis-freshness-stamp"


def _git(cwd: str, *args: str, timeout: int = 15) -> tuple[int, str]:
    """(exit code, stdout). Never raises; a timeout is just a non-zero code."""
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return r.returncode, (r.stdout or "").strip()


def _default_ref(cwd: str) -> str:
    """The remote's default branch, e.g. origin/main. '' when there is no usable one."""
    code, out = _git(cwd, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if code == 0 and out:
        return out
    for cand in ("origin/main", "origin/master"):
        if _git(cwd, "rev-parse", "--verify", "--quiet", cand)[0] == 0:
            return cand
    return ""


def _fetch_is_due(git_dir: str) -> bool:
    stamp = os.path.join(git_dir, STAMP_NAME)
    try:
        return (time.time() - os.path.getmtime(stamp)) > FETCH_MAX_AGE_S
    except OSError:
        return True


def _mark_fetched(git_dir: str) -> None:
    try:
        with open(os.path.join(git_dir, STAMP_NAME), "w", encoding="utf-8") as fh:
            fh.write(str(int(time.time())))
    except OSError:
        pass          # the throttle is an optimisation, never a reason to fail


def _count(cwd: str, rev_range: str) -> int:
    code, out = _git(cwd, "rev-list", "--count", rev_range)
    return int(out) if code == 0 and out.isdigit() else 0


def _norm_path(raw: str) -> str:
    """One path for comparison: no backticks, forward slashes, no leading `./`."""
    norm = raw.strip().replace("`", "").strip().replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    return norm


def _status_entries(top: str) -> list[list[str]]:
    """`git status --porcelain -z` at the repo top: one list of paths per entry (a rename gives two).
    NUL-separated, so a path is never quoted. [] when git fails."""
    try:
        r = subprocess.run(["git", "status", "--porcelain", "-z"], cwd=top, capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0:
        return []
    parts = (r.stdout or b"").decode("utf-8", errors="replace").split("\0")
    entries: list[list[str]] = []
    i = 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if len(entry) < 4:
            continue
        paths = [entry[3:]]
        if ("R" in entry[:2] or "C" in entry[:2]) and i < len(parts):
            paths.append(parts[i])
            i += 1
        entries.append(paths)
    return entries


def _parse_session_state(text: str) -> tuple[str, list[str]]:
    m = re.search(r"\*\*Branch:\*\*\s*`?([^\s`·]+)`?", text)
    branch = m.group(1).strip() if m else "unknown"
    files: list[str] = []
    in_files = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("## "):
            in_files = (s == "## Files changed this session")
            continue
        if in_files and s.startswith("- "):
            item = s[2:].strip()
            if item and not item.startswith("_("):
                item = _norm_path(item)
                if item:
                    files.append(item)
    return branch, files


def _dirty_owners(top: str, dirty_paths: set[str], own_session_id: str = "") -> list[str]:
    """Live peer sessions whose recorded files are dirty here. `top` is the repo top level: the
    session-state folder and every path are read from there, whatever the session's cwd is."""
    try:
        if not dirty_paths:
            return []
        base = os.path.join(artifact_root(top), "session-state")
        if not os.path.isdir(base):
            legacy = os.path.join(top, ".claudster", "session-state")
            if os.path.isdir(legacy):
                base = legacy
            else:
                return []
        now = time.time()
        owners: list[str] = []
        for name in sorted(os.listdir(base)):
            try:
                if not name.endswith(".md"):
                    continue
                sid = name[:-3]
                if own_session_id and sid == own_session_id:
                    continue
                path = os.path.join(base, name)
                mtime = os.path.getmtime(path)
                if now - mtime > PEER_FRESH_S:
                    continue
                ended = os.path.join(base, sid + ".ended")
                try:
                    if os.path.getmtime(ended) >= mtime:
                        continue
                except OSError:
                    pass
                with open(path, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
                peer_branch, peer_files = _parse_session_state(text)
                matched = False
                for pf in peer_files:
                    if pf in dirty_paths or any(
                        dp.endswith("/") and pf.startswith(dp) for dp in dirty_paths
                    ):
                        matched = True
                        break
                if matched:
                    label = f"owned by session {sid[:8]} (branch {peer_branch})"
                    if label not in owners:
                        owners.append(label)
            except Exception:
                continue
        return owners
    except Exception:
        return []


def report(cwd: str, own_session_id: str = "") -> list[str]:
    """The lines to print. Empty when there is nothing worth saying."""
    if _git(cwd, "rev-parse", "--is-inside-work-tree")[0] != 0:
        return []                                   # not a git repository
    branch = _git(cwd, "branch", "--show-current")[1]
    if not branch:
        return []                                   # detached HEAD: nothing useful to say
    lines: list[str] = []
    # A repo with no `origin` has nothing to be behind. Fetching it would fail every time and
    # the "could not fetch" note would be pure noise — common for scratch and local-only repos.
    has_origin = "origin" in _git(cwd, "remote")[1].split()
    git_dir = _git(cwd, "rev-parse", "--absolute-git-dir")[1] or os.path.join(cwd, ".git")
    if has_origin and _fetch_is_due(git_dir):
        if _git(cwd, "fetch", "origin", "--quiet", timeout=FETCH_TIMEOUT_S)[0] == 0:
            _mark_fetched(git_dir)
        else:
            lines.append("[HARNESS] could not fetch origin - the figures below may be stale.")

    ref = _default_ref(cwd) if has_origin else ""
    # The repo top level, so a session started in a subfolder still finds `.caddis/session-state`.
    top = _git(cwd, "rev-parse", "--show-toplevel")[1] or cwd
    entries = _status_entries(top)
    dirty = len(entries)
    dirty_paths = {_norm_path(p) for paths in entries for p in paths if _norm_path(p)}
    behind = _count(cwd, f"HEAD..{ref}") if ref else 0
    ahead = _count(cwd, f"{ref}..HEAD") if ref else 0
    default_branch = ref.split("/", 1)[-1] if ref else ""

    # With no remote to compare against, the only honest line left is the dirty warning.
    if ref and (branch != default_branch or behind or dirty):
        lines.append(f"[HARNESS] branch '{branch}' | {behind} behind {ref} | {ahead} ahead "
                     f"| {dirty} uncommitted")
    if dirty:
        msg = ("[HARNESS] There are uncommitted changes here. They may not be yours - these "
               "checkouts are shared. Look before you touch: git status")
        owners = _dirty_owners(top, dirty_paths, own_session_id=own_session_id)
        if owners:
            msg = f"{msg} ({'; '.join(owners)})"
        lines.append(msg)
    # The recommendation, only when following it can lose nothing: behind, clean, and with
    # nothing of your own unpushed. Suggesting a branch switch to someone holding uncommitted
    # work in a shared checkout is how the branch-switch hazard gets triggered.
    if behind and not dirty and not ahead:
        lines.append(f"[HARNESS] This checkout is behind and clean. Start new work with: "
                     f"git checkout -b <type>/<name> {ref}")
    if ahead:
        lines.append(f"[HARNESS] {ahead} local commit(s) are not on {ref}. Do not reset or "
                     f"re-branch without checking them: git log --oneline {ref}..HEAD")
    return lines


def main() -> int:
    # The session's cwd, not the hook process's: a session launched in one repo but working
    # in another must be reported on the repo it is actually in (same rule as inject_relay).
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    cwd = (payload.get("cwd") if isinstance(payload, dict) else None) or os.getcwd()
    session_id = (payload.get("session_id") if isinstance(payload, dict) else None) or ""
    try:
        for line in report(cwd, own_session_id=str(session_id)):
            print(line)
    except Exception:
        pass          # fail open: a freshness report must never break a session start
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
