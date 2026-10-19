"""SessionStart: where this checkout stands against the remote default branch.

WHY IT FETCHES. Nobody runs git by hand before opening an agent — so without a fetch,
`origin/main` is whatever it was last time. The agent then branches from a stale ref and
believes it is current. The fetch is what makes every later "branch from origin/main"
mean the newest main. One consumer repo carries the same lesson as a rule of its own:
audit `origin/main`, never the working tree.

FAIL OPEN, ALWAYS. Every path exits 0 and every git call is wrapped. A hook that can hang
or fail a session start is worse than the staleness it prevents, so a failed or slow fetch
reports and continues.

NO LOCKS, NO PROMPTS, A TIME BUDGET (robustness audit #6, 18 Oct 2026). Every git call
runs with GIT_OPTIONAL_LOCKS=0 (and `git status` with --no-optional-locks), so this hook never takes
index.lock from a peer session mid-commit. Every call runs with GIT_TERMINAL_PROMPT=0 and
GCM_INTERACTIVE=never, so a credential helper can never pop a sign-in window. The fetch runs in a
job object (Windows) or process group (POSIX), so `git-remote-https` dies with `git` on a timeout
instead of surviving it holding a ref lock. All git calls share one 18 s budget under the 25 s hook
timeout; with less than the fetch timeout left, the fetch is skipped and the output says so.

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
import signal
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
TOTAL_BUDGET_S = 18         # all git calls together; the hook timeout in hooks.json is 25 s
FETCH_MAX_AGE_S = 600       # a restart within 10 minutes reuses the last fetch
PEER_FRESH_S = 1800         # live peer session-state threshold (30 minutes, matches inject_relay)
STAMP_NAME = "caddis-freshness-stamp"

# No git child opens a console window on Windows (a hook is not a place for flashing windows).
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_NEW_PROCESS_GROUP = 0x00000200
# Never take an optional lock, never ask for a credential, never open a credential-manager window.
_GIT_ENV_OVERRIDES = {"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}

_deadline: float | None = None      # time.monotonic() value that ends this run's git budget; None = no budget


def _git_env() -> dict:
    """os.environ plus the no-lock, no-prompt overrides. A fresh dict each call."""
    return {**os.environ, **_GIT_ENV_OVERRIDES}


def _remaining() -> float:
    """Seconds left in the git budget. Effectively unbounded outside report()."""
    return float("inf") if _deadline is None else _deadline - time.monotonic()


def _git(cwd: str, *args: str, timeout: int = 15) -> tuple[int, str]:
    """(exit code, stdout). Never raises; a timeout is just a non-zero code. No call starts once the budget is
    gone, and no call may run past it."""
    left = _remaining()
    if left <= 0:
        return 1, ""
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=min(timeout, left),
                           stdin=subprocess.DEVNULL, env=_git_env(), creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return r.returncode, (r.stdout or "").strip()


# -- the bounded runner for the fetch ---------------------------------------------------------------------------
# Equivalent to caddis_roadmap.run_bounded (job object, tree kill), kept local on purpose: that module cannot take a
# cwd or creation flags, costs ~120 ms to import, and agy ships this file in a bundle where scripts/ may not sit
# beside it. A hook that cannot import its helper must still work.


class _Job:
    """A Windows job object holding one process and its children. KILL_ON_JOB_CLOSE: closing the handle (or the
    death of this process) ends the whole tree, even after the first process has exited."""

    def __init__(self, proc: "subprocess.Popen"):
        import ctypes
        from ctypes import wintypes

        class _Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class _Io(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class _Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", _Io), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        k.SetInformationJobObject.restype = wintypes.BOOL
        k.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        k.AssignProcessToJobObject.restype = wintypes.BOOL
        k.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        k.TerminateJobObject.restype = wintypes.BOOL
        k.CloseHandle.argtypes = (wintypes.HANDLE,)
        k.CloseHandle.restype = wintypes.BOOL
        self._k = k
        self.handle = k.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        info = _Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            err = ctypes.get_last_error()
            k.CloseHandle(self.handle)
            raise OSError(err, "SetInformationJobObject failed")
        if not k.AssignProcessToJobObject(self.handle, int(proc._handle)):  # type: ignore[attr-defined]
            err = ctypes.get_last_error()
            k.CloseHandle(self.handle)
            raise OSError(err, "AssignProcessToJobObject failed")

    def terminate(self) -> None:
        self._k.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        self._k.CloseHandle(self.handle)


def _kill_tree(proc: "subprocess.Popen", job: "_Job | None") -> None:
    try:
        if job is not None:
            job.terminate()
        elif os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                           stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW, timeout=5)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        pass            # the kill is best effort; the caller still reports the timeout


def _run_bounded(argv: list[str], cwd: str, timeout: float, env: dict) -> "int | None":
    """Run `argv` with no stdin and no output. Returns its exit code, 1 when it cannot start, or None on timeout.
    On a timeout the whole process tree is killed (job object on Windows, process group elsewhere). The tree is
    also killed on any other way out, Ctrl+C included, and when this process dies (Windows job)."""
    kwargs: dict = {"cwd": cwd, "env": env, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL}
    if os.name != "nt":
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(argv, creationflags=(_NO_WINDOW | _NEW_PROCESS_GROUP) if os.name == "nt" else 0, **kwargs)
    except (OSError, subprocess.SubprocessError):
        return 1
    job = None
    if os.name == "nt":
        try:
            job = _Job(proc)
        except Exception:
            job = None          # no job object: taskkill /T is the fallback
    try:
        try:
            return proc.wait(timeout=max(timeout, 0))
        except subprocess.TimeoutExpired:
            _kill_tree(proc, job)
            try:
                proc.wait(timeout=5)
            except subprocess.SubprocessError:
                pass
            return None
    except BaseException:
        _kill_tree(proc, job)
        raise
    finally:
        if job is not None:
            job.close()


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
        left = _remaining()
        if left <= 0:
            return []
        r = subprocess.run(["git", "--no-optional-locks", "status", "--porcelain", "-z"], cwd=top,
                           capture_output=True, timeout=min(15, left), stdin=subprocess.DEVNULL,
                           env=_git_env(), creationflags=_NO_WINDOW)
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


def _fetch(cwd: str) -> "bool | None":
    """`git fetch origin` through the bounded runner. True = fetched, False = failed or timed out, None = skipped
    because less than FETCH_TIMEOUT_S of the budget is left. Never raises. Maintenance is off for this one call:
    a background `gc --auto` would be killed with the job and could leave its lock behind."""
    left = _remaining()
    if left < FETCH_TIMEOUT_S:
        return None
    argv = ["git", "-c", "gc.auto=0", "-c", "maintenance.auto=false", "fetch", "origin", "--quiet"]
    try:
        return _run_bounded(argv, cwd, min(FETCH_TIMEOUT_S, left), _git_env()) == 0
    except Exception:
        return False


def report(cwd: str, own_session_id: str = "") -> list[str]:
    """The lines to print. Empty when there is nothing worth saying."""
    global _deadline
    _deadline = time.monotonic() + TOTAL_BUDGET_S
    try:
        return _report(cwd, own_session_id)
    finally:
        _deadline = None


def _report(cwd: str, own_session_id: str = "") -> list[str]:
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
        fetched = _fetch(cwd)
        if fetched:
            _mark_fetched(git_dir)
        elif fetched is None:
            lines.append("[HARNESS] skipped the fetch - the session-start time budget was nearly spent. "
                         "The figures below may be stale.")
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
