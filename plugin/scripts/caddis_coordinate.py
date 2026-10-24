"""Deterministic coordinator core for the caddis hub (spec sections 7, 7a, 8).

Why this exists: one coordinator per repository applies owner requests (approve, hold, merge) to a
queue. A model must never write the queue files by hand, so every read and write goes through
this script. It needs one stable key per repository, so that a clone, a fork and a worktree of
the same project share one hub folder: that key is the repo id.
"""

from __future__ import annotations

import argparse
import copy
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

try:
    from caddis_file_lock import _try_lock, _unlock, atomic_write, locked_path, retry_denied
except ModuleNotFoundError as exc:
    if exc.name != "caddis_file_lock":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-harness" / "scripts"))
    from caddis_file_lock import _try_lock, _unlock, atomic_write, locked_path, retry_denied


_TIMEOUT = 10
_SHA = re.compile(r"[0-9a-fA-F]{40}")  # a full git commit SHA
SCHEMA = 1
_READ_SCHEMAS = (SCHEMA - 1, SCHEMA)  # readers accept N and N-1 (spec section 9)
_STATE_CACHE: dict[Path, tuple[tuple[int, int], dict]] = {}  # path -> ((mtime_ns, size), last good parse)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# https://host/owner/name(.git), ssh://user@host(:port)/owner/name(.git), user@host:owner/name(.git)
_URL = re.compile(
    r"^(?:[a-z][a-z0-9+.-]*://(?:[^@/]+@)?[^/]+/|[^@/:]+@[^:/]+:)"
    r"(?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)


def _run(args: list[str], cwd: Path | None = None, timeout: float = _TIMEOUT) -> subprocess.CompletedProcess[str]:
    # utf-8 explicitly: the Windows default code page garbles non-ASCII paths and titles.
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, creationflags=_NO_WINDOW)


def repo_id(remote_name_with_owner: str | None, is_fork_of: str | None, git_root: Path) -> str:
    """Return the hub key: `owner__name` (upstream for a fork), else `local__<folder>__<hash6>`."""
    upstream = is_fork_of or remote_name_with_owner
    if upstream:
        return upstream.strip().lower().replace("/", "__")
    digest = hashlib.sha256(os.path.normcase(str(git_root)).encode("utf-8")).hexdigest()[:6]
    return f"local__{git_root.name}__{digest}"


def _owner_name_from_url(url: str) -> str | None:
    """Return `owner/name` from an https, ssh or scp-style git remote URL, else None."""
    match = _URL.match(url.strip())
    if not match:
        return None
    return f"{match['owner']}/{match['name']}"


def _gh_name_with_owner(path: Path) -> tuple[str | None, str | None]:
    """Return (nameWithOwner, parent nameWithOwner or None) from gh; (None, None) on any failure."""
    try:
        result = _run(["gh", "repo", "view", "--json", "nameWithOwner,parent"], cwd=path)
        if result.returncode != 0:
            return None, None
        data = json.loads(result.stdout)
        name = data.get("nameWithOwner") or None
        if name is None:
            return None, None
        parent = data.get("parent") or {}
        return name, parent.get("nameWithOwner") or None
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        return None, None


def repo_id_for(path: Path) -> str:
    """Return the repo id for a checkout or any of its worktrees."""
    common = _run(["git", "-C", str(path), "rev-parse", "--path-format=absolute", "--git-common-dir"])
    if common.returncode != 0:
        raise ValueError(f"not a git repository: {path}")
    git_root = Path(common.stdout.strip()).parent
    name, parent = _gh_name_with_owner(git_root)
    if name is None:
        origin = _run(["git", "-C", str(git_root), "remote", "get-url", "origin"])
        if origin.returncode == 0:
            name = _owner_name_from_url(origin.stdout)
    return repo_id(name, parent, git_root)


# --- state file and single-coordinator lock (C1.2) ---------------------------------------------------------------


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hub_home() -> Path:
    """Return `$CADDIS_HUB_HOME`, else `~/.caddis/hub`."""
    override = os.environ.get("CADDIS_HUB_HOME")
    return Path(override) if override else Path.home() / ".caddis" / "hub"


_RESERVED = frozenset(["con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                       *(f"lpt{i}" for i in range(1, 10))])  # Windows device names, also with any extension


def _repo_dir(rid: str) -> Path:
    # The repo id names a folder: refuse anything that could leave `<hub>/repos`, or that Windows would not
    # store as given (a trailing dot or space is dropped; a device name opens the device, not a folder).
    if (not rid or rid == "." or ".." in rid or any(c in rid for c in "/\\:") or rid[-1] in ". "
            or rid.split(".", 1)[0].lower() in _RESERVED):
        raise ValueError(f"bad repo id: {rid!r}")
    return hub_home() / "repos" / rid


def state_path(rid: str) -> Path:
    return _repo_dir(rid) / "coordinator.json"


def _lock_path(rid: str) -> Path:
    return _repo_dir(rid) / "coordinator.lock.json"


def _watcher_lock_path(rid: str) -> Path:
    return _repo_dir(rid) / "watcher.lock"


def _watcher_stop_path(rid: str) -> Path:
    return _repo_dir(rid) / "watcher.stop"


def read_state(rid: str) -> dict | None:
    """Return the last good parse of `coordinator.json`; None when it is missing or was never good.

    A transient Windows sharing error is retried first (`retry_denied`). A partial file (a writer died mid-write)
    or a sharing error that remains returns the cached last good parse, never an exception. The cache is keyed by
    path and checked against the file's mtime and size, and lives in this process only: a one-shot process (each
    CLI call) has no last good parse and gets None, so the hub must keep its own last good state.
    """
    path = state_path(rid)
    cached = _STATE_CACHE.get(path)
    try:
        info = retry_denied(path.stat)
    except FileNotFoundError:
        return None
    except OSError:
        return copy.deepcopy(cached[1]) if cached else None
    key = (info.st_mtime_ns, info.st_size)
    if cached and cached[0] == key:
        return copy.deepcopy(cached[1])
    try:
        data = json.loads(retry_denied(path.read_bytes).decode("utf-8"))
        if not isinstance(data, dict) or data.get("schema") not in _READ_SCHEMAS:
            raise ValueError("not a coordinator state")
    except FileNotFoundError:
        return None
    except (OSError, ValueError):  # sharing error, partial file, bad UTF-8 (UnicodeDecodeError is a ValueError)
        return copy.deepcopy(cached[1]) if cached else None
    _STATE_CACHE[path] = (key, data)
    return copy.deepcopy(data)


def _read_state_strict(path: Path) -> dict:
    """Read the state file now, for read/modify/write under its lock: no cache, raises on any failure.

    `read_state` falls back to the last good parse, which is right for display but would write an old snapshot
    over newer state here (a lost update).
    """
    data = json.loads(retry_denied(path.read_bytes).decode("utf-8"))
    if not isinstance(data, dict) or data.get("schema") not in _READ_SCHEMAS:
        raise ValueError(f"not a coordinator state: {path}")
    return data


def _write_state_unlocked(path: Path, state: dict) -> None:
    atomic_write(path, json.dumps(state, indent=2) + "\n")


def write_state(rid: str, state: dict) -> None:
    """Validate `schema == 1`, stamp `heartbeat_at`, and replace `coordinator.json` atomically under its lock."""
    if not isinstance(state, dict) or state.get("schema") != SCHEMA:
        raise ValueError(f"coordinator state must have schema {SCHEMA}")
    state = {**state, "heartbeat_at": _now()}
    with locked_path(state_path(rid)) as path:
        _write_state_unlocked(path, state)


def heartbeat(rid: str) -> None:
    """Rewrite `heartbeat_at` only. Raises (OSError, ValueError) when the file cannot be read and parsed now."""
    with locked_path(state_path(rid)) as path:
        state = _read_state_strict(path)
        state["heartbeat_at"] = _now()
        _write_state_unlocked(path, state)


def new_state(rid: str, session: dict) -> dict:
    """Return an empty `coordinator.json` document for this repo and coordinator session (spec section 8)."""
    return {
        "schema": SCHEMA,
        "repo": rid,
        "coordinator_session": {"name": session.get("name"), "sessionId": session.get("sessionId"),
                                "pid": session.get("pid")},
        "heartbeat_at": _now(),
        "queue": [],
        "merging_now": None,
        "deploy_checks": [],
        "ledger": [],
        "processed_requests": [],
    }


# Copied from scripts/caddis_roadmap.py (_win_open_process, _pid_alive). Not imported: importing that module
# loads four more modules and changes sys.path (controller ruling R4).
def _win_open_process(pid: int) -> tuple[bool | None, int]:
    """Windows: (still running, 0) when OpenProcess works; (None, GetLastError()) when it does not."""
    import ctypes
    from ctypes import wintypes

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k.OpenProcess.restype = wintypes.HANDLE
    k.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    k.GetExitCodeProcess.restype = wintypes.BOOL
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None, ctypes.get_last_error()
    code = wintypes.DWORD()
    ok = k.GetExitCodeProcess(handle, ctypes.byref(code))
    k.CloseHandle(handle)
    return bool(ok) and code.value == 259, 0  # STILL_ACTIVE


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        running, error = _win_open_process(pid)
        if running is None:
            return error == 5  # ERROR_ACCESS_DENIED: the process exists, this user may not open it
        return running
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# Copied from scripts/caddis_roadmap.py (PID_START_TOLERANCE_S, _filetime_utc, _win_process_start,
# _proc_process_start, process_start_time), for the same reason as _pid_alive above.
PID_START_TOLERANCE_S = 5.0  # `started_at` has whole seconds; the holder's own process started before it


def _filetime_utc(value: int) -> datetime.datetime:
    return datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(microseconds=value // 10)


def _win_process_start(pid: int) -> datetime.datetime | None:
    import ctypes
    from ctypes import wintypes

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k.OpenProcess.restype = wintypes.HANDLE
    k.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
    k.GetProcessTimes.restype = wintypes.BOOL
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not k.GetProcessTimes(handle, *(ctypes.byref(x) for x in times)):
            return None
        created = times[0]
        return _filetime_utc((created.dwHighDateTime << 32) | created.dwLowDateTime)
    finally:
        k.CloseHandle(handle)


def _proc_process_start(pid: int) -> datetime.datetime | None:
    """POSIX with /proc: field 22 of /proc/<pid>/stat (clock ticks after boot) plus `btime` of /proc/stat."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        ticks = int(stat.rsplit(")", 1)[1].split()[19])
        btime = next(int(line.split()[1]) for line in Path("/proc/stat").read_text(encoding="utf-8").splitlines()
                     if line.startswith("btime "))
        hz = os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, StopIteration, AttributeError):
        return None
    return datetime.datetime.fromtimestamp(btime + ticks / hz, datetime.timezone.utc)


def process_start_time(pid: int) -> datetime.datetime | None:
    """When the process now holding `pid` started, or None when it cannot be read (psutil when installed, else
    GetProcessTimes on Windows, else /proc)."""
    try:
        import psutil  # optional
        return datetime.datetime.fromtimestamp(psutil.Process(pid).create_time(), datetime.timezone.utc)
    except ImportError:
        pass
    except Exception:  # no such process, access denied: fall through to the platform reader
        pass
    try:
        return _win_process_start(pid) if os.name == "nt" else _proc_process_start(pid)
    except Exception:
        return None


def _parse_utc(text: object) -> datetime.datetime | None:
    if not isinstance(text, str):
        return None
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def _holder_alive(holder: dict) -> bool:
    """Alive: the pid runs, and that process started at or before `started_at` + tolerance.

    When the start time or `started_at` cannot be read, a running pid counts as alive (refuse, fail closed).
    """
    if not _pid_alive(holder["pid"]):
        return False
    started = _parse_utc(holder.get("started_at"))
    born = process_start_time(holder["pid"]) if started is not None else None
    return born is None or born <= started + datetime.timedelta(seconds=PID_START_TOLERANCE_S)


def _read_holder(path: Path) -> dict | None:
    """Return the lock holder, or None when there is no lock or its content is not a holder (treated as free).

    A transient sharing error is retried. Any other OSError is raised: a file that cannot be read may name a live
    holder, so the caller must refuse (fail closed), never treat it as free."""
    try:
        data = json.loads(retry_denied(path.read_bytes).decode("utf-8"))
    except FileNotFoundError:
        return None
    except ValueError:  # bad JSON or UTF-8: atomic_write never leaves this, so no live holder wrote it
        return None
    return data if isinstance(data, dict) and isinstance(data.get("pid"), int) else None


def acquire_lock(rid: str, pid: int, session_id: str, name: str) -> tuple[bool, dict | None]:
    """Take the single-coordinator lock: (True, None), or (False, holder) while another live pid holds it.

    A holder whose pid is dead, or whose pid now belongs to a process that started after the lock was taken
    (pid reuse, often after a reboot), is replaced. The same pid taking it again refreshes it. A lock file that
    cannot be read is refused, with a holder whose pid is None (fail closed).
    """
    with locked_path(_lock_path(rid)) as path:
        try:
            holder = _read_holder(path)
        except OSError as exc:
            return False, {"pid": None, "sessionId": None, "name": None,
                           "error": f"lock file unreadable: {' '.join(str(exc).split()) or type(exc).__name__}"}
        if holder is not None and holder["pid"] != pid and _holder_alive(holder):
            return False, holder
        atomic_write(path, json.dumps({"pid": pid, "sessionId": session_id, "name": name,
                                       "started_at": _now()}) + "\n")
        return True, None


def lock_holder(rid: str) -> dict | None:
    """Return the lock holder with its `alive` flag, or None when no holder. Never takes or changes the lock.

    Raise OSError when the lock file cannot be read (the caller fails closed)."""
    holder = _read_holder(_lock_path(rid))
    if holder is None:
        return None
    return {"pid": holder["pid"], "sessionId": holder.get("sessionId"), "name": holder.get("name"),
            "started_at": holder.get("started_at"), "alive": _holder_alive(holder)}


def release_lock(rid: str, pid: int) -> None:
    """Remove the lock if `pid` holds it; do nothing otherwise."""
    with locked_path(_lock_path(rid)) as path:
        holder = _read_holder(path)
        if holder is not None and holder["pid"] == pid:
            retry_denied(lambda: path.unlink(missing_ok=True))


# --- queue operations (C1.3) --------------------------------------------------------------------------------------

QUEUE_STATES = ("waiting", "ci", "ready", "merging", "blocked", "held")  # spec section 8


def _mutate_state(rid: str, change: Callable[[dict], bool | None]) -> None:
    """Read `coordinator.json` strictly under its lock, apply `change(state)`, write it back.

    Raises ValueError when the repo has no state file: these operations need a coordinator that has started.
    When `change` raises, or returns False (no change), nothing is written.
    """
    if not state_path(rid).exists():  # checked first so an unknown repo id leaves no folder or lock file behind
        raise ValueError(f"no coordinator state for repo {rid!r}")
    with locked_path(state_path(rid)) as path:
        try:
            state = _read_state_strict(path)
        except FileNotFoundError:
            raise ValueError(f"no coordinator state for repo {rid!r}") from None
        if change(state) is False:
            return
        _write_state_unlocked(path, state)


def _find(queue: list[dict], pr: int) -> dict | None:
    return next((item for item in queue if item.get("pr") == pr), None)


def _names_pr(merging_now: object, pr: int) -> bool:
    """`merging_now` is a PR number or an object with `pr` (schema); True when it names `pr`."""
    if isinstance(merging_now, dict):
        merging_now = merging_now.get("pr")
    return not isinstance(merging_now, bool) and merging_now == pr


def _mutate_item(rid: str, pr: int, change: Callable[[dict], None]) -> None:
    """`_mutate_state` for a change to one queue item (`change(state)`), keeping `merging_now` in step with it.

    The item entering `merging` sets `merging_now` to its PR. The item leaving `merging` (another state, a new
    head, or removal) clears `merging_now` when it names this PR."""
    def wrapped(state: dict) -> None:
        before = _find(state["queue"], pr)
        was = before is not None and before.get("state") == "merging"
        change(state)
        after = _find(state["queue"], pr)
        if after is not None and after.get("state") == "merging":
            state["merging_now"] = pr
        elif was and _names_pr(state.get("merging_now"), pr):
            state["merging_now"] = None
    _mutate_state(rid, wrapped)


def _set_head(item: dict, head_sha: str) -> None:
    """Record a new head. It has not been ready yet and is untested: clear the ready time and demote `ready` or
    `merging` to `ci` (ruling R5). The same head changes nothing."""
    if item.get("head_sha") == head_sha:
        return
    item["head_sha"] = head_sha
    item["entered_ready_at"] = None
    if item.get("state") in ("ready", "merging"):
        item["state"] = "ci"


def queue_add(rid: str, pr: int, head_sha: str, title: str) -> None:
    """Add a PR as `waiting`. Adding a PR already in the queue updates its title and head (a new head demotes a
    `ready` or `merging` item to `ci`), nothing else."""
    def change(state: dict) -> None:
        queue = state["queue"]
        item = _find(queue, pr)
        if item is None:
            queue.append({"pr": pr, "head_sha": head_sha, "title": title, "state": "waiting", "why_waiting": "",
                          "waits_on": [], "hotfix": False, "held": False, "entered_ready_at": None})
            return
        item["title"] = title
        _set_head(item, head_sha)
    _mutate_item(rid, pr, change)


def queue_set(rid: str, pr: int, *, state: str | None = None, head_sha: str | None = None,
              why_waiting: str | None = None, waits_on: list[dict] | None = None) -> None:
    """Change the given fields of one queue item. Raises ValueError for an unknown state or a PR not in the queue.

    `entered_ready_at` is stamped the first time the item is set `ready`, and kept when it leaves and re-enters
    `ready` with the same head. A new head clears it and demotes `ready`/`merging` to `ci` (ruling R5); a `state`
    given in the same call is applied after that. `held` is not touched here (ruling R1).

    Entering `merging` sets `merging_now` to this PR, and leaving it clears `merging_now`. Raises ValueError when
    another queued PR is merging now (one merge at a time); nothing is written then.
    """
    if state is not None and state not in QUEUE_STATES:
        raise ValueError(f"unknown queue state: {state!r}")

    def change(doc: dict) -> None:
        queue = doc["queue"]
        item = _find(queue, pr)
        if item is None:
            raise ValueError(f"PR {pr} is not in the queue")
        if state == "merging":
            other = next((i.get("pr") for i in queue if i.get("pr") != pr and (
                i.get("state") == "merging" or _names_pr(doc.get("merging_now"), i.get("pr")))), None)
            if other is not None:
                raise ValueError(f"PR {other} is merging now: one merge at a time")
        if head_sha is not None:
            _set_head(item, head_sha)
        if why_waiting is not None:
            item["why_waiting"] = why_waiting
        if waits_on is not None:
            item["waits_on"] = [dict(w) for w in waits_on]
        if state is not None:
            item["state"] = state
            if state == "ready" and not item.get("entered_ready_at"):
                item["entered_ready_at"] = _now()
    _mutate_item(rid, pr, change)


def queue_remove(rid: str, pr: int) -> None:
    """Remove a PR from the queue; do nothing when it is not there."""
    def change(state: dict) -> None:
        state["queue"] = [item for item in state["queue"] if item.get("pr") != pr]
    _mutate_item(rid, pr, change)


def queue_order(state: dict) -> list[dict]:
    """Return the queue in merge order (spec D5). Pure: the state is not changed.

    The `merging` item comes first. Then hotfix items, then the rest. Inside each group, ready items that are not
    held go first by `entered_ready_at` ascending; held and non-ready items follow in add order.
    """
    queue = list(state.get("queue") or [])

    def ready(item: dict) -> bool:
        return item.get("state") == "ready" and not item.get("held")

    def rank(index_item: tuple[int, dict]) -> tuple:
        index, item = index_item
        if item.get("state") == "merging":
            return (0, 0, 0, "", index)
        group = 1 if item.get("hotfix") else 2
        if ready(item):
            at = item.get("entered_ready_at")
            return (group, 0, 0 if at else 1, at or "", index)  # a ready item without a time sorts last of the ready
        return (group, 1, 0, "", index)

    return [item for _, item in sorted(enumerate(queue), key=rank)]


def queue_next(state: dict) -> dict | None:
    """Return the item to merge next (pure): the `merging` item; else the first `ready`, not held item in
    `queue_order`; else None."""
    for item in queue_order(state):
        if item.get("state") == "merging" or (item.get("state") == "ready" and not item.get("held")):
            return item
    return None


# --- owner requests and intake (C1.4) -----------------------------------------------------------------------------

REQUEST_V = 1
_REQUEST_VS = (REQUEST_V - 1, REQUEST_V)  # readers accept N and N-1
_REQUEST_KEYS = frozenset(("v", "id", "created_at", "expires_at", "repo", "pr", "head_sha", "action", "args"))
# Inside one batch only the last request per (pr, family) is applied.
_FAMILY = {"hotfix": "hotfix", "unhotfix": "hotfix", "hold": "hold", "release": "hold",
           "approve": "approve", "decline": "approve"}
PROCESSED_KEEP = datetime.timedelta(hours=24)
MAX_REQUEST_LIFE = datetime.timedelta(hours=1)
MAX_CLOCK_SKEW = datetime.timedelta(minutes=5)  # a request created later than now + this is refused


def requests_path(rid: str) -> Path:
    return _repo_dir(rid) / "requests.jsonl"


def _cursor_path(rid: str) -> Path:
    return _repo_dir(rid) / "intake.cursor"


def _fmt(when: datetime.datetime) -> str:
    return when.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_request(rid: str, req: dict) -> None:
    """Append one request as one JSON line under the requests file's lock.

    Under the lock, a tail with no newline can only come from a writer that died. It is closed with a newline
    first, so it becomes one bad line (rejected by intake) and never joins this request.
    """
    if not isinstance(req, dict):
        raise ValueError("a request is a JSON object")
    line = (json.dumps(req, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")
    with locked_path(requests_path(rid)) as path:
        def append() -> None:
            with open(path, "a+b") as fh:
                fh.seek(0, os.SEEK_END)
                prefix = b""
                if fh.tell() > 0:
                    fh.seek(-1, os.SEEK_END)
                    if fh.read(1) != b"\n":
                        prefix = b"\n"
                fh.write(prefix + line)  # append mode: always at the end
                fh.flush()
                os.fsync(fh.fileno())
        retry_denied(append)


def _read_cursor(path: Path) -> int:
    try:
        value = int(retry_denied(lambda: path.read_text(encoding="utf-8")).strip())
    except (OSError, ValueError):  # missing or unreadable: start from 0; processed ids prevent replay
        return 0
    return max(value, 0)


def _check_request(req: object, rid: str) -> str | None:
    """Return the rejection reason for a malformed request, or None when it is well formed."""
    if not isinstance(req, dict) or set(req) != _REQUEST_KEYS:
        return "bad request"
    if not isinstance(req["action"], str) or req["action"] not in _FAMILY:
        return "unknown action"
    if (isinstance(req["v"], bool) or req["v"] not in _REQUEST_VS or req["repo"] != rid
            or not isinstance(req["id"], str) or not req["id"]
            or not isinstance(req["args"], dict)):
        return "bad request"
    if _parse_utc(req["created_at"]) is None or _parse_utc(req["expires_at"]) is None:
        return "bad request"
    pr = req["pr"]
    if pr is None:  # ruling R2: only approve/decline may name no PR, and then `args.what` says what is decided
        what = req["args"].get("what")
        if _FAMILY[req["action"]] != "approve" or not isinstance(what, str) or not what.strip():
            return "bad request"
        return None
    if isinstance(pr, bool) or not isinstance(pr, int) or pr <= 0:
        return "bad request"
    if not isinstance(req["head_sha"], str) or not _SHA.fullmatch(req["head_sha"]):
        return "bad request"
    return None


def _window_ok(req: dict, now: datetime.datetime) -> bool:
    """Spec rule 4 gives expires_at = created_at + 30 min. A longer window could outlive the 24 h dedup of
    processed ids and replay after a lost cursor, so a window over 1 hour, one that ends before it starts, or one
    created more than `MAX_CLOCK_SKEW` in the future is refused. Checked after expiry: an expired request has no
    effect, so it cannot replay."""
    created, expires = _parse_utc(req["created_at"]), _parse_utc(req["expires_at"])
    return created <= expires <= created + MAX_REQUEST_LIFE and created <= now + MAX_CLOCK_SKEW


def _new_lines(rid: str, offset: int, stop: int | None = None) -> tuple[list[tuple[int, bytes]], int]:
    """Return the complete lines after `offset` as (byte offset, line), and the new cursor (just after the last
    newline). A tail with no newline is left for the next cycle. Bytes at or after `stop` are not read."""
    try:
        data = retry_denied(requests_path(rid).read_bytes)
    except FileNotFoundError:
        return [], offset
    if offset > len(data):  # the file was replaced by a shorter one: read it again from the start
        offset = 0
    if stop is not None:
        data = data[:stop]
    end = data.rfind(b"\n", offset)
    if end < 0:
        return [], offset
    lines, start = [], offset
    for raw in data[offset:end].split(b"\n"):
        lines.append((start, raw))
        start += len(raw) + 1
    return lines, end + 1


def _parse_line(start: int, raw: bytes) -> tuple[str, object]:
    """Return (key, parsed request or None). A line with no usable id is named by its byte offset, which stays
    the same when the file is read again."""
    try:
        req = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):  # bad JSON, bad UTF-8, or nesting too deep
        req = None
    given = req.get("id") if isinstance(req, dict) else None
    return (given if isinstance(given, str) and given else f"line@{start}"), req


def _live_heads(rid: str, lines: list[tuple[int, bytes]], head_of: Callable[[int], str | None],
                now: datetime.datetime) -> dict:
    """Look up the live head once per PR named by a well-formed, unexpired, not yet processed line. Called with
    no lock held, so the processed ids come from a plain read; a stale read only costs an extra lookup.

    Any lookup failure gives None: an unknown head (ruling R3)."""
    done = {p.get("id") for p in (read_state(rid) or {}).get("processed_requests") or [] if isinstance(p, dict)}
    prs: list[int] = []
    for start, raw in lines:
        if not raw.strip():
            continue
        key, req = _parse_line(start, raw)
        if (key not in done and _check_request(req, rid) is None and now <= _parse_utc(req["expires_at"])
                and _window_ok(req, now) and req["pr"] is not None and req["pr"] not in prs):
            prs.append(req["pr"])
    heads: dict[int, str | None] = {}
    for pr in prs:
        try:
            heads[pr] = head_of(pr)
        except Exception:
            heads[pr] = None
    return heads


def intake(rid: str, now: datetime.datetime, head_of: Callable[[int], str | None]) -> list[dict]:
    """Apply new owner requests to the queue and ledger; return this cycle's results (spec section 7 rule 5).

    Reads the complete lines after `intake.cursor`. A request id already in `processed_requests` is skipped with
    no result, so a lost cursor never replays a request. State and cursor are written in one locked section,
    state first: a crash between the two re-reads lines whose ids are already processed. `head_of(pr)` gives the
    live head SHA, or None when it is unknown; then the request is rejected (fail closed, ruling R3).
    """
    if not state_path(rid).exists():  # checked first so an unknown repo id leaves no folder or lock file behind
        raise ValueError(f"no coordinator state for repo {rid!r}")
    at = _fmt(now)
    cursor_path = _cursor_path(rid)
    # head_of may call gh and take seconds. Other writers wait at most 5 s for the state lock, so the live heads
    # are looked up first, with no lock held. A head that moves in the gap is the same race as one that moves
    # just after the check. Lines that arrive in the gap are left for the next cycle (`stop`).
    seen_lines, stop = _new_lines(rid, _read_cursor(cursor_path))
    heads = _live_heads(rid, seen_lines, head_of, now)
    with locked_path(state_path(rid)) as path:
        try:
            state = _read_state_strict(path)
        except FileNotFoundError:
            raise ValueError(f"no coordinator state for repo {rid!r}") from None
        offset = _read_cursor(cursor_path)
        lines, new_offset = _new_lines(rid, offset, stop)

        processed = [p for p in state.get("processed_requests") or [] if isinstance(p, dict)]
        seen = {p.get("id") for p in processed}
        results: dict[str, dict | None] = {}  # id -> result, in line order; None until the winner is applied
        winners: dict[tuple, dict] = {}
        for start, raw in lines:
            if not raw.strip():
                continue
            key, req = _parse_line(start, raw)
            if key in seen or key in results:
                continue
            reason = _check_request(req, rid)
            if reason is not None:
                results[key] = {"id": key, "result": "rejected", "reason": reason, "at": at}
            elif now > _parse_utc(req["expires_at"]):
                results[key] = {"id": key, "result": "expired", "reason": "expired", "at": at}
            elif not _window_ok(req, now):
                results[key] = {"id": key, "result": "rejected", "reason": "bad request", "at": at}
            else:
                family = _FAMILY[req["action"]]
                # Two non-PR decisions supersede each other only when they decide the same thing.
                group = (req["pr"], family) if req["pr"] is not None else (None, family, req["args"]["what"].strip())
                earlier = winners.get(group)
                if earlier is not None:
                    results[earlier["id"]] = {"id": earlier["id"], "result": "rejected", "reason": "superseded",
                                              "at": at}
                winners[group] = req
                results[key] = None

        for req in winners.values():
            results[req["id"]] = _apply(state, req, heads, at)
        out = list(results.values())

        cutoff = now - PROCESSED_KEEP
        kept = [p for p in processed if (_parse_utc(p.get("at")) or cutoff) > cutoff]
        if out or len(kept) != len(state.get("processed_requests") or []):
            state["processed_requests"] = kept + out
            _write_state_unlocked(path, state)
        if new_offset != offset:
            atomic_write(cursor_path, f"{new_offset}\n")
        return out


def _apply(state: dict, req: dict, heads: dict[int, str | None], at: str) -> dict:
    """Check one winning request against the queue and the live head, then apply it. Returns its result.

    `heads` comes from `_live_heads`; a PR missing from it has an unknown head."""
    def result(kind: str, reason: str) -> dict:
        return {"id": req["id"], "result": kind, "reason": reason, "at": at}

    action, pr = req["action"], req["pr"]
    item = None
    if pr is not None:
        item = _find(state["queue"], pr)
        if item is None:
            return result("rejected", "not in queue")
        live = heads.get(pr)
        if not isinstance(live, str) or not live:
            return result("rejected", "head unknown")
        if live.lower() != req["head_sha"].lower():
            return result("rejected", "head moved")
    if action in ("hotfix", "unhotfix"):
        item["hotfix"] = action == "hotfix"
    elif action in ("hold", "release"):
        item["held"] = action == "hold"
    else:
        what = req["args"].get("what")
        what = what.strip() if isinstance(what, str) and what.strip() else f"PR #{pr}"
        # The owner's click in the hub is the approval (spec 7a): that is its reason and its window.
        state.setdefault("ledger", []).append(_ledger_entry(what=what, decision=action, by="owner",
                                                            reason="owner click", window="hub",
                                                            request_id=req["id"], at=at))
    return result("done", "")


# --- merge record, deploy checks, ledger (C1.6) -------------------------------------------------------------------

DEPLOY_HEALTH = ("pending", "ok", "failed")
LEDGER_DECISIONS = ("approve", "decline")
LEDGER_BY = ("owner", "coordinator")  # spec D15, D16: routine gates by the coordinator, the owner-only list by the owner


def queue_merged(rid: str, pr: int, merge_sha: str) -> bool:
    """Record a merge: remove the PR from the queue, clear `merging_now` when it names this PR, and append a
    `pending` deploy check. Returns True when recorded now.

    Idempotent: when the PR is not in the queue but a deploy check with this `pr` and `merge_sha` exists, the
    merge was already recorded (a retry after a successful write): returns False and writes nothing. Raises
    ValueError for a merge SHA that is not 40 hex characters, or a PR neither queued nor recorded with this SHA
    (nothing written). The SHA is stored lower-cased."""
    if not isinstance(merge_sha, str) or not _SHA.fullmatch(merge_sha):
        raise ValueError(f"a merge SHA is 40 hex characters: {merge_sha!r}")
    merge_sha = merge_sha.lower()

    def change(state: dict) -> bool:
        if _find(state["queue"], pr) is None:
            if any(isinstance(c, dict) and c.get("pr") == pr and c.get("merge_sha") == merge_sha
                   for c in state.get("deploy_checks") or []):
                return False
            raise ValueError(f"PR {pr} is not in the queue")
        state["queue"] = [item for item in state["queue"] if item.get("pr") != pr]
        if _names_pr(state.get("merging_now"), pr):
            state["merging_now"] = None
        state.setdefault("deploy_checks", []).append({"pr": pr, "merge_sha": merge_sha, "deploy_run": None,
                                                      "health": "pending", "at": _now()})
        return True

    outcome: list[bool] = []

    def change_and_keep(state: dict) -> bool:
        outcome.append(change(state))
        return outcome[-1]
    _mutate_state(rid, change_and_keep)
    return outcome[-1]


def deploy_check_set(rid: str, pr: int, *, deploy_run: int | None = None, health: str | None = None) -> None:
    """Set the deploy run and/or health of the newest deploy check for a PR; a health also sets `at` to now.
    Raises ValueError for a health not in `DEPLOY_HEALTH`, a run that is not an integer, or a PR with no deploy check."""
    if health is not None and health not in DEPLOY_HEALTH:
        raise ValueError(f"unknown deploy health: {health!r}")
    if deploy_run is not None and (isinstance(deploy_run, bool) or not isinstance(deploy_run, int)):
        raise ValueError(f"a deploy run is an integer: {deploy_run!r}")

    def change(state: dict) -> None:
        check = next((c for c in reversed(state.get("deploy_checks") or [])
                      if isinstance(c, dict) and c.get("pr") == pr), None)
        if check is None:
            raise ValueError(f"no deploy check for PR {pr}")
        if deploy_run is not None:
            check["deploy_run"] = deploy_run
        if health is not None:  # stamp `at`, so the newest entry by `at` is the newest health (freeze rule)
            check["health"] = health
            check["at"] = _now()
    _mutate_state(rid, change)


def _ledger_entry(*, what: str, decision: str, by: str, reason: str, window: str | None, request_id: str | None,
                  at: str) -> dict:
    """Validate and build one ledger entry (keys in schema order). Raises ValueError."""
    def text(name: str, value: object, optional: bool) -> str | None:
        if value is None and optional:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"ledger {name} must be a non-empty string")
        return value.strip()

    if decision not in LEDGER_DECISIONS:
        raise ValueError(f"unknown ledger decision: {decision!r}")
    if by not in LEDGER_BY:
        raise ValueError(f"unknown approver: {by!r}")
    return {"what": text("what", what, False), "decision": decision, "approved_by": by,
            "reason": text("reason", reason, False), "window": text("window", window, True),
            "request_id": text("request_id", request_id, True), "at": at}


def ledger_record(rid: str, *, what: str, decision: str, by: str, reason: str, window: str | None = None,
                  request_id: str | None = None) -> None:
    """Append a decision to the ledger: a routine gate by the coordinator, or an owner decision given in a session
    window (D15, D16). `window` names the session window it was decided in. Raises ValueError (nothing written)."""
    entry = _ledger_entry(what=what, decision=decision, by=by, reason=reason, window=window, request_id=request_id,
                          at=_now())
    _mutate_state(rid, lambda state: state.setdefault("ledger", []).append(entry))


# --- command line (C1.5) ------------------------------------------------------------------------------------------

EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_LOCK_REFUSED = 0, 1, 2, 3


def _gh_head_of(rid: str) -> Callable[[int], str | None]:
    """Return `head_of(pr)` for intake: the live head SHA from gh, or None (ruling R3).

    None for a `local__` id (no GitHub repository) and on any gh failure. gh reads `GH_TOKEN` from the inherited
    environment when it is set; this script never chooses an account."""
    def head_of(pr: int) -> str | None:
        if rid.startswith("local__") or "__" not in rid:
            return None
        owner, name = rid.split("__", 1)  # GitHub owners have no underscore, so the first `__` splits them
        try:
            result = _run(["gh", "pr", "view", str(pr), "-R", f"{owner}/{name}", "--json", "headRefOid",
                           "-q", ".headRefOid"])
        except (OSError, subprocess.SubprocessError):
            return None
        sha = result.stdout.strip() if result.returncode == 0 else ""
        return sha or None
    return head_of


def _gh_title(rid: str, pr: int) -> str:
    """The PR title from gh, so the model never puts free text on a command line; `PR #<n>` on any failure."""
    fallback = f"PR #{pr}"
    if rid.startswith("local__") or "__" not in rid:
        return fallback
    owner, name = rid.split("__", 1)
    try:
        result = _run(["gh", "pr", "view", str(pr), "-R", f"{owner}/{name}", "--json", "title", "-q", ".title"])
    except (OSError, subprocess.SubprocessError):
        return fallback
    title = result.stdout.strip() if result.returncode == 0 else ""
    return title or fallback


def _claim_state(rid: str, session: dict) -> None:
    """After the lock is taken: create `coordinator.json`, or record the new coordinator session in it."""
    with locked_path(state_path(rid)) as path:
        try:
            state = _read_state_strict(path)
        except FileNotFoundError:
            state = new_state(rid, session)
        state["coordinator_session"] = {"name": session["name"], "sessionId": session["sessionId"],
                                        "pid": session["pid"]}
        state["heartbeat_at"] = _now()
        _write_state_unlocked(path, state)


def session_lookup(sessions: list[dict], *, session_id: str | None = None, name: str | None = None) -> dict:
    """Return `{"pid", "sessionId", "name"}` of the ONE interactive session with this sessionId or name.

    Background entries are ignored: their pid is not a long-lived Claude Code session (ruling R12)."""
    if (session_id is None) == (name is None):
        raise ValueError("session_lookup takes exactly one of session_id or name")
    key, wanted = ("sessionId", session_id) if session_id is not None else ("name", name)
    hits = [s for s in sessions if isinstance(s, dict) and s.get("kind") == "interactive" and s.get(key) == wanted]
    if not hits:
        raise ValueError(f"no such session: {key} {wanted!r}")
    if len(hits) > 1:
        pids = ", ".join(str(s.get("pid")) for s in hits)
        raise ValueError(f"two interactive sessions share {key} {wanted!r}: pids {pids}")
    hit = hits[0]
    pid = hit.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise ValueError(f"session {key} {wanted!r} has no valid pid: {pid!r}")
    for field in ("sessionId", "name"):
        if not isinstance(hit.get(field), str) or not hit[field]:
            raise ValueError(f"session {key} {wanted!r} has no {field}")
    return {"pid": pid, "sessionId": hit["sessionId"], "name": hit["name"]}


# --- the per-repo config `.caddis/coordinator.md` (C2.2, ruling R10: one fenced json block) --------------------

CONFIG_KEYS = ("schema", "default_branch", "merge_method", "required_checks", "not_required", "docs_only",
               "main_workflow", "reviews", "peer_ack", "deploy", "owner_reserved", "stall", "quiet")
OPTIONAL_CONFIG_KEYS = ("relay", "start_mode")  # relay: `.caddis/relay/<relay>.md`; start_mode: see START_MODES
# The merge mode a start begins in. "target" in the reviewed, merged config is the owner's standing consent
# for the coordinator to run `gh pr merge` (command section 2). Missing means "interim".
START_MODES = ("interim", "target")
CONFIG_SCHEMA = 1
_PLACEHOLDER = "<fill:"
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*([^\s`]*)")  # a Markdown code fence and its info string
_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "coordinator.md"


def config_path(repo_root: Path) -> Path:
    return Path(repo_root) / ".caddis" / "coordinator.md"


def _closes(line: str, fence: str) -> bool:
    """True when `line` closes a block opened by `fence`: same character, at least as long, nothing after it."""
    closed = re.match(r"^ {0,3}(`{3,}|~{3,})[ \t]*$", line)
    return bool(closed) and closed.group(1)[0] == fence[0] and len(closed.group(1)) >= len(fence)


def _config_block(text: str) -> object:
    """Parse the FIRST fenced block whose info string is `json`. Raise ValueError when there is none."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        opened = _FENCE.match(lines[i])
        if not opened:
            i += 1
            continue
        fence, info = opened.group(1), opened.group(2).lower()
        body: list[str] = []
        i += 1
        while i < len(lines) and not _closes(lines[i], fence):
            body.append(lines[i])
            i += 1
        i += 1
        if info == "json":
            try:
                return json.loads("\n".join(body))
            except ValueError as exc:
                raise ValueError(f"the json block in the config does not parse: {exc}") from exc
    raise ValueError("the config has no fenced json block")


def _placeholders(value: object, where: str = "") -> list[str]:
    """Every key path (at any depth) whose value is a string that starts with `<fill:`."""
    if isinstance(value, str):
        return [where] if value.startswith(_PLACEHOLDER) else []
    if isinstance(value, dict):
        return [hit for k, v in value.items() for hit in _placeholders(v, f"{where}.{k}" if where else str(k))]
    if isinstance(value, list):
        return [hit for n, v in enumerate(value) for hit in _placeholders(v, f"{where}[{n}]")]
    return []


def load_config(repo_root: Path) -> dict:
    """Read `<repo_root>/.caddis/coordinator.md` and return its json block.

    Raise FileNotFoundError when the file is missing, ValueError when there is no json block, a key is missing,
    `schema` is not 1, a value is still a `<fill: ...>` placeholder, the optional `relay` is not a plain
    workstream name (`caddis_workstreams.is_plain_name`: lower case `a-z0-9_-`, no Windows device name), or the
    optional `start_mode` is not one of START_MODES."""
    path = config_path(repo_root)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"no coordinator config at {path} (run: caddis_coordinate.py config init)") from exc
    config = _config_block(text)
    if not isinstance(config, dict):
        raise ValueError("the config json block must be one JSON object")
    missing = [key for key in CONFIG_KEYS if key not in config]
    if missing:
        raise ValueError(f"the config is missing keys: {', '.join(missing)}")
    schema = config["schema"]
    if not isinstance(schema, int) or isinstance(schema, bool) or schema != CONFIG_SCHEMA:
        raise ValueError(f"the config schema must be {CONFIG_SCHEMA}, not {schema!r}")
    unfilled = _placeholders(config)
    if unfilled:
        raise ValueError(f"the config still has {_PLACEHOLDER} placeholders at: {', '.join(unfilled)}")
    if "relay" in config and not _plain_workstream_name(config["relay"]):
        raise ValueError(f"the config relay must be a plain workstream name such as coordinator, "
                         f"not {config['relay']!r}")
    if "start_mode" in config and config["start_mode"] not in START_MODES:
        raise ValueError(f"the config start_mode must be one of {', '.join(START_MODES)}, "
                         f"not {config['start_mode']!r}")
    return config


_CONFIG_REL = ".caddis/coordinator.md"


def _start_mode_at(repo_root: Path, rev: str) -> str | None:
    """`start_mode` in the config at `rev`: a mode, None (no file or no key) or "invalid"."""
    shown = _run(["git", "-C", str(repo_root), "show", f"{rev}:{_CONFIG_REL}"])
    if shown.returncode != 0:
        return None
    try:
        block = _config_block(shown.stdout)
    except ValueError:
        return "invalid"
    if not isinstance(block, dict):
        return "invalid"
    if "start_mode" not in block:
        return None
    return block["start_mode"] if block["start_mode"] in START_MODES else "invalid"


def _origin_default_branch(repo_root: Path) -> str | None:
    """The default branch from `refs/remotes/origin/HEAD`, never from the work tree (review, 24 Oct 2026)."""
    out = _run(["git", "-C", str(repo_root), "symbolic-ref", "--short", "refs/remotes/origin/HEAD"])
    ref = out.stdout.strip() if out.returncode == 0 else ""
    return ref[len("origin/"):] if ref.startswith("origin/") and len(ref) > len("origin/") else None


def _set_target_commit(repo_root: Path, ref: str) -> tuple[str | None, str | None]:
    """The commit on `ref` where `start_mode` last became "target" (newest first: the oldest commit of the newest
    unbroken run of target versions). The ledger cites it as the owner's consent."""
    out = _run(["git", "-C", str(repo_root), "log", "--format=%H%x09%s", ref, "--", _CONFIG_REL])
    if out.returncode != 0:
        return None, None
    found: tuple[str | None, str | None] = (None, None)
    for line in out.stdout.splitlines():
        sha, _, subject = line.partition("\t")
        if _start_mode_at(repo_root, sha) != "target":
            break
        found = (sha, subject)
    return found


def config_mode(repo_root: Path) -> dict:
    """The merge mode a start begins in. Target only when origin's default branch AND the work tree both say
    `"start_mode": "target"`: the work tree of a shared checkout can hold an uncommitted edit that no owner
    approved (review, 24 Oct 2026). The branch comes from `origin/HEAD`, not from the work-tree config; a work
    tree whose `default_branch` differs is a mismatch. Returns mode, work_tree, origin, mismatch, set_by (the
    commit that set target) and set_by_subject. Fetch first; a stale origin ref gives a stale answer."""
    work = load_config(repo_root)
    branch = _origin_default_branch(repo_root)
    origin = _start_mode_at(repo_root, f"origin/{branch}") if branch else "invalid"
    work_mode = work.get("start_mode")
    set_by = set_by_subject = None
    if origin == "target":
        set_by, set_by_subject = _set_target_commit(repo_root, f"origin/{branch}")

    def effective(value: str | None) -> str:  # missing means interim
        return value or "interim"
    mismatch = (origin == "invalid" or branch != work["default_branch"]
                or effective(work_mode) != effective(origin))
    mode = "target" if not mismatch and effective(origin) == "target" else "interim"
    return {"mode": mode, "work_tree": work_mode, "origin": origin, "mismatch": mismatch,
            "set_by": set_by, "set_by_subject": set_by_subject}


def config_changed(diff: str) -> bool:
    """True when a unified diff touches .caddis/coordinator.md in any way: add, delete, rename to or from it,
    edit, binary or mode-only change. That file holds the coordinator's own rules (start_mode, required checks,
    owner_reserved), so such a PR is owner-only (R4) in every mode. File-level on purpose: a text match on keys
    can be dodged with JSON escapes (review, 24 Oct 2026)."""
    marks = (f"+++ b/{_CONFIG_REL}", f"--- a/{_CONFIG_REL}", f"rename from {_CONFIG_REL}", f"rename to {_CONFIG_REL}",
             f"copy from {_CONFIG_REL}", f"copy to {_CONFIG_REL}")
    for line in diff.splitlines():
        if line in marks:
            return True
        if line.startswith("diff --git ") and (line.startswith(f"diff --git a/{_CONFIG_REL} ")
                                               or line.endswith(f" b/{_CONFIG_REL}")):
            return True
    return False


def _plain_workstream_name(value: object) -> bool:
    """The relay name rule of `caddis_workstreams` (one rule, so a relay that loads here can also be read there)."""
    try:
        import caddis_workstreams
    except ModuleNotFoundError as exc:
        if exc.name != "caddis_workstreams":
            raise
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import caddis_workstreams
    return caddis_workstreams.is_plain_name(value)


def init_config(repo_root: Path) -> Path:
    """Copy the template to `<repo_root>/.caddis/coordinator.md` when it is absent. Never overwrite."""
    path = config_path(repo_root)
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "x", encoding="utf-8", newline="") as handle:  # "x": fails if the file exists, no race
            handle.write(template)
    except FileExistsError:
        pass
    return path


# --- the watcher loop (C2.3) --------------------------------------------------------------------------------------


def _say(exc: BaseException) -> str:
    return " ".join(str(exc).split()) or type(exc).__name__


def watch_cycle(rid: str, pid: int, now: datetime.datetime, head_of: Callable[[int], str | None]) -> dict:
    """One watcher cycle: check the lock still names `pid` and that session is alive, then heartbeat and intake.

    Returns `{"stop": "lock lost" | "session gone" | "state gone"}` when the watcher must end, else
    `{"stop": None, "results": [...], "error": str | None}`. A transient failure (a lock file or state file that
    cannot be read now, a lock timeout) goes into `error` and is never raised: the next cycle retries. The watcher
    never takes the lock and changes the queue only through `intake`. The pid check is local (no `claude agents`).
    """
    def failed(message: str) -> dict:
        return {"stop": None, "results": [], "error": message}

    try:
        holder = _read_holder(_lock_path(rid))
    except OSError as exc:  # fail closed: it may still name us, so retry next tick rather than stop
        if not _pid_alive(pid):  # ... unless our own session is dead: then nothing is left to watch for
            return {"stop": "session gone"}
        return failed(f"lock file unreadable: {_say(exc)}")
    if holder is None or holder["pid"] != pid:
        return {"stop": "lock lost"}
    if not _holder_alive(holder):  # the pid is dead, or now belongs to a newer process (pid reuse)
        return {"stop": "session gone"}
    if not state_path(rid).exists():  # checked first: heartbeat must never recreate the repo folder
        return {"stop": "state gone"}
    try:
        heartbeat(rid)
        results = intake(rid, now, head_of)
    except FileNotFoundError:
        return {"stop": "state gone"}
    except ValueError as exc:
        if not state_path(rid).exists():
            return {"stop": "state gone"}
        return failed(_say(exc))
    except OSError as exc:  # sharing error, lock timeout (TimeoutError): retry next tick
        return failed(_say(exc))
    except Exception as exc:  # e.g. a hand-edited state file: report it, keep watching
        return failed(f"unexpected {type(exc).__name__}: {_say(exc)}")
    return {"stop": None, "results": results, "error": None}


_TAKEOVER_MAX_S = 150.0  # the longest a `--takeover` waits for the old watcher
_TAKEOVER_POLL_S = 0.2


def _print_line(value: dict) -> None:
    print(json.dumps(value, separators=(",", ":")), flush=True)


def _takeover_wait(interval: float) -> float:
    """The old watcher checks the stop file right after each sleep, and one cycle can run long (gh calls): wait one
    interval plus 30 s, at most `_TAKEOVER_MAX_S`."""
    return min(interval + 30, _TAKEOVER_MAX_S)


def _remove_stop_file(rid: str) -> None:
    retry_denied(lambda: _watcher_stop_path(rid).unlink(missing_ok=True))


def _remove_own_stop_file(rid: str) -> None:
    """Remove the stop file only when this process wrote it: a newer takeover's request stays."""
    try:
        owner = json.loads(_watcher_stop_path(rid).read_text(encoding="utf-8")).get("pid")
    except (OSError, ValueError, AttributeError):
        return
    if owner == os.getpid():
        _remove_stop_file(rid)


def watch(rid: str, pid: int, interval: float, max_cycles: int | None = None, takeover: bool = False) -> int:
    """Run `watch_cycle` every `interval` seconds. Print one JSON line (flushed) for each cycle with results or a
    stop, and for an error that differs from the previous cycle's error; print nothing for a quiet cycle or a
    repeated error. Return 0 on a stop or after `max_cycles` cycles.

    One watcher per repo: the loop holds the OS lock on `<hub>/repos/<rid>/watcher.lock` for its whole life (the OS
    frees it when the process dies). When another watcher holds it:
    - without `takeover`, print `{"stop": "another watcher is running"}` and return 0 at once;
    - with `takeover`, write `<hub>/repos/<rid>/watcher.stop` and wait (`_takeover_wait`) for the lock. The old
      watcher sees the stop file right after its next sleep, prints `{"stop": "takeover requested"}` and ends.
      A `finally` removes this process's own stop file (on success, timeout or an exception; a newer takeover's
      file stays). When the lock does not come in time, print `{"stop": "old watcher did not stop"}` and
      return 1. After a `/clear` the old watcher runs on in the same process, but its output belongs to the old
      conversation: takeover gives the new conversation a watcher whose output it can read.
    The watcher that gets the lock removes any stop file before its first cycle. When the repo folder does not
    exist, no lock or stop file is made: the first cycle then stops (it never recreates the folder)."""
    path = _watcher_lock_path(rid)
    if not path.parent.is_dir():
        return _watch_loop(rid, pid, interval, max_cycles)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    with os.fdopen(os.open(path, flags, 0o666), "r+b") as handle:
        held = _try_lock(handle)
        if not held and not takeover:
            _print_line({"stop": "another watcher is running"})
            return EXIT_OK
        if not held:
            try:
                atomic_write(_watcher_stop_path(rid), json.dumps({"pid": os.getpid(), "at": _now()}) + "\n")
                deadline = time.monotonic() + _takeover_wait(interval)
                while not held and time.monotonic() < deadline:
                    time.sleep(_TAKEOVER_POLL_S)
                    held = _try_lock(handle)
            finally:  # on success, on timeout and on an exception: never leave this process's request behind
                _remove_own_stop_file(rid)
            if not held:
                _print_line({"stop": "old watcher did not stop"})
                return EXIT_ERROR
        try:
            _remove_stop_file(rid)
            return _watch_loop(rid, pid, interval, max_cycles)
        finally:
            _unlock(handle)


def _watch_loop(rid: str, pid: int, interval: float, max_cycles: int | None) -> int:
    head_of = _gh_head_of(rid)
    cycles = 0
    last_error: str | None = None
    try:
        while True:
            out = watch_cycle(rid, pid, datetime.datetime.now(datetime.timezone.utc), head_of)
            error = out.get("error")
            if out.get("stop") or out.get("results") or (error and error != last_error):
                print(json.dumps(out, separators=(",", ":")), flush=True)
            last_error = error
            if out.get("stop"):
                return EXIT_OK
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                return EXIT_OK
            time.sleep(interval)
            if _watcher_stop_path(rid).exists():  # right after the sleep: a newer watcher asked for the lock
                _print_line({"stop": "takeover requested"})
                return EXIT_OK
    except KeyboardInterrupt:
        return EXIT_OK


# --- deploy check D1-D5 by script (C2.4, ruling R11) -------------------------------------------------------------

DEPLOY_CHECKS = ("D1", "D2", "D3", "D4", "D5")
_DEPLOY_TIMEOUT = 60  # one subprocess: `git fetch --tags`, or curl with its own --max-time 20
_CURL_MAX_TIME = "20"


def _deploy_run(args: list[str]) -> subprocess.CompletedProcess[str]:
    """The default runner of `deploy_verify`: `_run` with a timeout longer than curl's own `--max-time`."""
    return _run(args, timeout=_DEPLOY_TIMEOUT)


def _curl() -> str:
    """Windows: System32 curl.exe under %SystemRoot%, by full path, when it exists (a bare name lets CreateProcess
    pick a curl.exe from the current folder first), else `curl.exe` on PATH. Elsewhere: `curl` on PATH."""
    if os.name != "nt":
        return "curl"
    system = Path(os.environ.get("SystemRoot") or "") / "System32" / "curl.exe"
    return str(system) if os.environ.get("SystemRoot") and system.is_file() else "curl.exe"


def _plain_path(path: object) -> str:
    """A URL path compared for `never_health_path`: lowercased, no query string or fragment, no trailing slash."""
    return re.split(r"[?#]", str(path), maxsplit=1)[0].rstrip("/").lower()


def _unset(value: object) -> bool:
    return value is None or (isinstance(value, str) and value.strip().lower() in ("", "none", "null"))


def _checks_summary(checks: dict, docs_only: bool) -> str:
    """`passed: D1, D2, D5; skipped: D3, D4`, from the checks dict, with a `docs-only: ` prefix."""
    parts = []
    for label, mark in (("passed", "pass"), ("skipped", "skip")):
        names = [name for name, value in checks.items() if value == mark]
        if names:
            parts.append(f"{label}: {', '.join(names)}")
    return ("docs-only: " if docs_only else "") + "; ".join(parts)


class _CheckFailed(Exception):
    def __init__(self, reason: str, health: str = "failed") -> None:
        super().__init__(reason)
        self.health = health


def _call(runner: Callable[[list[str]], subprocess.CompletedProcess[str]], argv: list[str],
          what: str) -> subprocess.CompletedProcess[str]:
    """Run one command; a missing tool, a timeout or a non-zero exit is a check failure, never a crash."""
    try:
        result = runner(argv)
    except subprocess.TimeoutExpired:
        raise _CheckFailed(f"{what} timed out") from None
    except (OSError, subprocess.SubprocessError) as exc:
        raise _CheckFailed(f"{what} could not run ({Path(argv[0]).name}): {_say(exc)}") from None
    if result.returncode != 0:
        detail = " ".join((result.stderr or result.stdout or "").split()) or f"exit {result.returncode}"
        raise _CheckFailed(f"{what} failed: {detail}")
    return result


def deploy_verify(rid: str, cfg: dict, pr: int, merge_sha: str, *, docs_only: bool,
                  runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
                  env=os.environ, repo_root: Path | None = None) -> dict:
    """Run deploy checks D1-D5 for a merged PR, record the result with `deploy_check_set`, and return
    `{"checks": {"D1".."D5": "pass|fail|skip"}, "run": int | None, "health": "ok|failed|pending", "reason": str}`.

    Checks run in order and stop at the first failure (the rest are `skip`). D2 does not wait: the model waits
    with `caddis_lanes.py ci-watch --run` first. Docs-only runs D1, D2 and D5 only, and D2 fails when the run
    contradicts the flag (a job named `deploy...` succeeded, or `deploy.jobs` jobs succeeded). A non-docs run needs
    `deploy.jobs` successful jobs, and every job when it has more. `deploy.never_health_path` is never requested.
    `GH_TOKEN` comes from the inherited environment only. `repo_root` is where the git commands of D3 run.
    A run still in progress at D2 records health `pending`, not `failed`.
    Raises ValueError, before any network call and with nothing recorded, for a merge SHA that is not a full SHA,
    a PR with no deploy check, or a merge SHA that differs from the one in the PR's newest deploy check."""
    if not isinstance(merge_sha, str) or not _SHA.fullmatch(merge_sha):
        raise ValueError(f"the merge SHA must be a full 40-character SHA: {merge_sha!r}")
    state = read_state(rid)
    check = next((c for c in reversed((state or {}).get("deploy_checks") or [])
                  if isinstance(c, dict) and c.get("pr") == pr), None)
    if check is None:
        raise ValueError(f"no deploy check for PR {pr} (run queue merged first)")
    if str(check.get("merge_sha", "")).lower() != merge_sha.lower():
        raise ValueError(f"merge SHA {merge_sha[:12]} is not the recorded merge SHA "
                         f"{str(check.get('merge_sha'))[:12]} of PR {pr}")
    runner = runner or _deploy_run
    deploy = cfg.get("deploy") if isinstance(cfg.get("deploy"), dict) else {}
    sha = merge_sha.lower()
    checks = {name: "skip" for name in DEPLOY_CHECKS}
    found: dict = {"run": None}

    def curl(path: str, *extra: str) -> list[str]:
        auth = deploy.get("auth")
        if _unset(auth):
            auth_args: list[str] = []
        elif auth == "ntlm":
            auth_args = ["--ntlm", "-u", ":"]
        else:
            raise _CheckFailed(f"unknown deploy.auth {auth!r} (known: ntlm, none)")
        name = deploy.get("base_url_env")
        if _unset(name):
            raise _CheckFailed("deploy.base_url_env is not set in the config")
        base = env.get(name)
        if not base:
            raise _CheckFailed(f"base URL env {name} not set")
        if not isinstance(path, str) or not path.startswith("/"):
            raise _CheckFailed(f"a deploy path must start with '/': {path!r}")
        never = deploy.get("never_health_path")
        if not _unset(never) and _plain_path(path) == _plain_path(never):
            raise _CheckFailed(f"refused: {path} is deploy.never_health_path")
        return [_curl(), "-s", "--max-time", _CURL_MAX_TIME, *auth_args, *extra, base.rstrip("/") + path]

    def d1() -> None:
        if rid.startswith("local__") or "__" not in rid:
            raise _CheckFailed(f"repo {rid} has no GitHub repository")
        owner, name = rid.split("__", 1)
        branch, workflow = cfg.get("default_branch"), cfg.get("main_workflow")
        event = deploy.get("event") or "push"
        if _unset(workflow) or not isinstance(workflow, str):
            raise _CheckFailed("main_workflow is not set in the config")
        out = _call(runner, ["gh", "run", "list", "-R", f"{owner}/{name}", "--branch", str(branch),
                             "--event", str(event), "--workflow", workflow, "--limit", "50",
                             "--json", "databaseId,headSha,status,conclusion"], "gh run list")
        try:
            runs = json.loads(out.stdout)
        except ValueError:
            raise _CheckFailed("gh run list did not print JSON") from None
        hits = [r for r in runs if isinstance(r, dict) and str(r.get("headSha", "")).lower() == sha] \
            if isinstance(runs, list) else []
        if not hits:
            raise _CheckFailed(f"no {event} run of {workflow} on {branch} for {merge_sha[:12]}")
        found["run"] = hits[0]  # gh lists newest first
        run_id = hits[0].get("databaseId")
        found["id"] = run_id if isinstance(run_id, int) and not isinstance(run_id, bool) else None

    def d2() -> None:
        run = found["run"]
        status, conclusion = run.get("status"), run.get("conclusion")
        if status != "completed":
            raise _CheckFailed(f"run {found['id']} still running: wait for it with ci-watch --run first", "pending")
        if conclusion != "success":
            raise _CheckFailed(f"run {found['id']} concluded {conclusion}")
        want = deploy.get("jobs")
        want_ok = isinstance(want, int) and not isinstance(want, bool) and want >= 1
        if not docs_only and not want_ok:
            raise _CheckFailed(f"deploy.jobs must be a job count of 1 or more, not {want!r}")
        if found["id"] is None:
            raise _CheckFailed("the push run has no databaseId")
        owner, name = rid.split("__", 1)
        out = _call(runner, ["gh", "run", "view", str(found["id"]), "-R", f"{owner}/{name}", "--json", "jobs"],
                    "gh run view")
        try:
            jobs = json.loads(out.stdout).get("jobs")
        except (ValueError, AttributeError):
            jobs = None
        if not isinstance(jobs, list):
            raise _CheckFailed("gh run view did not print a jobs list")
        succeeded = [j for j in jobs if isinstance(j, dict) and j.get("conclusion") == "success"]
        done = len(succeeded)
        if docs_only:  # a docs-only push deploys nothing: a run that deployed contradicts the flag
            deployed = any("deploy" in str(j.get("name", "")).lower() for j in succeeded)
            if deployed or (want_ok and done >= want):
                raise _CheckFailed(f"docs-only flag contradicts the run: {done} jobs succeeded")
            return
        others = ", ".join(f"{j.get('name')}={j.get('conclusion')}" for j in jobs
                           if isinstance(j, dict) and j.get("conclusion") != "success")
        detail = f" ({others})" if others else ""
        if done < want:
            raise _CheckFailed(f"run {found['id']}: {done} of {want} jobs succeeded{detail}")
        if len(jobs) != want and done != len(jobs):  # extra jobs: every one must succeed
            raise _CheckFailed(f"run {found['id']}: {len(jobs)} jobs, not {want}, and not all succeeded{detail}")

    def d3() -> None:
        git = ["git", "-C", str(repo_root)] if repo_root is not None else ["git"]
        _call(runner, [*git, "fetch", "--tags"], "git fetch --tags")
        out = _call(runner, [*git, "tag", "--points-at", merge_sha], "git tag --points-at")
        if not out.stdout.strip():
            raise _CheckFailed(f"no release tag points at {merge_sha[:12]}")

    def d4() -> None:
        path = deploy.get("version_path")
        out = _call(runner, curl(path), f"curl {path}")
        try:
            body = json.loads(out.stdout)
        except ValueError:
            raise _CheckFailed(f"{path} did not return JSON") from None
        reported = body.get("sha") if isinstance(body, dict) else None
        if not isinstance(reported, str) or not reported.lower().startswith(sha):
            raise _CheckFailed(f"{path} reports sha {reported!r}, not {merge_sha[:12]}")

    def d5() -> None:
        path = deploy.get("health_path")
        if _unset(path):
            raise _CheckFailed("deploy.health_path is not set in the config")
        null = "NUL" if os.name == "nt" else "/dev/null"
        out = _call(runner, curl(path, "-o", null, "-w", "%{http_code}"), f"curl {path}")
        code = out.stdout.strip()
        if code != "200":
            raise _CheckFailed(f"{path} returned HTTP {code or 'nothing'}, not 200")

    steps = [("D1", d1, True), ("D2", d2, True),
             ("D3", d3, not docs_only and not _unset(deploy.get("tag"))),
             ("D4", d4, not docs_only and not _unset(deploy.get("version_path"))),
             ("D5", d5, True)]
    health, reason = "ok", ""
    for name, step, applies in steps:
        if not applies:
            continue
        try:
            step()
        except _CheckFailed as exc:
            checks[name], health, reason = "fail", exc.health, str(exc)
            break
        checks[name] = "pass"
    if health == "ok":
        reason = _checks_summary(checks, docs_only)
    run_id = found.get("id")
    deploy_check_set(rid, pr, deploy_run=run_id, health=health)
    return {"checks": checks, "run": run_id, "health": health, "reason": reason}


def _deploy_root(config_path_arg: str) -> Path:
    """`--config-path` names the config file or the repo root; return the repo root."""
    given = Path(config_path_arg)
    if given.is_dir():
        return given
    root = given.resolve().parent.parent
    if config_path(root).resolve() != given.resolve():
        raise ValueError(f"--config-path must be a repo root or its .caddis/coordinator.md: {given}")
    return root


def _claude_agents() -> list[dict]:
    """Run `claude agents --json` and return its list. Raise OSError or ValueError on failure."""
    claude = shutil.which("claude")  # on Windows this finds claude.CMD
    if not claude:
        raise OSError("claude not found on PATH")
    try:
        result = _run([claude, "agents", "--json"])
    except subprocess.TimeoutExpired as exc:
        raise OSError(f"claude agents --json timed out after {_TIMEOUT} s") from exc
    if result.returncode != 0:
        detail = " ".join((result.stderr or result.stdout or "").split()) or f"exit {result.returncode}"
        raise OSError(f"claude agents --json failed: {detail}")
    try:
        value = json.loads(result.stdout)
    except ValueError as exc:
        raise ValueError("claude agents --json did not print JSON") from exc
    if not isinstance(value, list):
        raise ValueError("claude agents --json did not print a JSON list")
    return value


def _waits_on(text: str) -> list[dict]:
    try:
        value = json.loads(text)
    except ValueError:
        value = None
    if not isinstance(value, list) or not all(isinstance(w, dict) for w in value):
        raise argparse.ArgumentTypeError('takes a JSON list of objects, for example [{"repo": "acme__lib", "pr": 3}]')
    return value


class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # raise instead of sys.exit, so main() returns 2
        raise _UsageError(f"{self.prog}: {message}")


def _parser() -> argparse.ArgumentParser:
    top = _Parser(prog="caddis_coordinate.py", description="Deterministic coordinator core for the caddis hub.")
    sub = top.add_subparsers(dest="command", required=True, parser_class=_Parser)

    def command(name: str, parent=sub, repo: bool = True) -> argparse.ArgumentParser:
        p = parent.add_parser(name)
        p.add_argument("--json", action="store_true", help="print JSON on stdout")
        if repo:
            p.add_argument("--repo", help="repo id (default: the repo id of the current folder)")
        return p

    p = command("repo-id", repo=False)
    p.add_argument("--path", default=".", help="a folder inside the checkout (default: current folder)")

    config = sub.add_parser("config").add_subparsers(dest="config_command", required=True, parser_class=_Parser)
    for name in ("show", "init", "mode"):
        p = command(name, config, repo=False)
        p.add_argument("--path", default=".", help="the repo root (default: current folder)")
    p = command("pr-check", config, repo=False)
    p.add_argument("--pr", type=int, required=True, help="the PR whose diff to check (`gh pr diff`)")
    p.add_argument("--gh-repo", help="owner/name for `gh pr diff -R` (default: the current folder's repo)")

    p = command("session", repo=False)
    which = p.add_mutually_exclusive_group(required=True)
    which.add_argument("--session-id", help="the Claude Code sessionId to find")
    which.add_argument("--name", help="the Claude Code session name to find")

    lock = sub.add_parser("lock").add_subparsers(dest="lock_command", required=True, parser_class=_Parser)
    p = command("acquire", lock)
    p.add_argument("--pid", type=int, required=True)
    p.add_argument("--session-id", required=True)
    p.add_argument("--name", required=True)
    p = command("release", lock)
    p.add_argument("--pid", type=int, required=True)
    command("holder", lock)

    command("heartbeat")
    command("intake")
    p = command("watch")
    p.add_argument("--pid", type=int, required=True, help="the coordinator session pid that holds the lock")
    p.add_argument("--interval", type=float, default=30.0, help="seconds between cycles (default 30)")
    p.add_argument("--max-cycles", type=int, help="stop after this many cycles (for tests)")
    p.add_argument("--takeover", action="store_true",
                   help="ask a running watcher of this repo to stop, then take its place (after a /clear)")
    command("state")

    queue = sub.add_parser("queue").add_subparsers(dest="queue_command", required=True, parser_class=_Parser)
    p = command("add", queue)
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--head-sha", required=True)
    p.add_argument("--title", help="the PR title (default: read from gh; `PR #<n>` when gh fails)")
    p = command("set", queue)
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--state", choices=QUEUE_STATES)
    p.add_argument("--head-sha")
    p.add_argument("--why-waiting")
    p.add_argument("--waits-on", type=_waits_on)
    p = command("remove", queue)
    p.add_argument("--pr", type=int, required=True)
    p = command("ready", queue)
    p.add_argument("--pr", type=int, required=True)
    command("next", queue)
    p = command("merged", queue)
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--merge-sha", required=True)

    deploy = sub.add_parser("deploy-check").add_subparsers(dest="deploy_command", required=True, parser_class=_Parser)
    p = command("set", deploy)
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--run", type=int, help="the deploy run id")
    p.add_argument("--health", choices=DEPLOY_HEALTH)

    p = command("deploy-verify")
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--merge-sha", required=True, help="the full merge commit SHA")
    p.add_argument("--config-path", required=True, help="the repo root, or its .caddis/coordinator.md")
    p.add_argument("--docs-only", action="store_true", help="a docs-only merge: D1, D2 and D5 only")

    ledger = sub.add_parser("ledger").add_subparsers(dest="ledger_command", required=True, parser_class=_Parser)
    p = command("record", ledger)
    p.add_argument("--what", required=True)
    p.add_argument("--decision", choices=LEDGER_DECISIONS, required=True)
    p.add_argument("--by", choices=LEDGER_BY, required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--window", help="the session window the decision was made in")
    p.add_argument("--request-id")
    return top


def _emit(args: argparse.Namespace, value: object, text: str) -> None:
    print(json.dumps(value, indent=2) if args.json else text)


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "repo-id":
        rid = repo_id_for(Path(args.path))
        _emit(args, {"repo": rid}, rid)
        return EXIT_OK
    if args.command == "session":
        found = session_lookup(_claude_agents(), session_id=args.session_id, name=args.name)
        _emit(args, found, f"pid {found['pid']} ({found['name']})")
        return EXIT_OK
    if args.command == "config":
        if args.config_command == "init":
            path = init_config(Path(args.path))
            _emit(args, {"path": str(path)}, str(path))
        elif args.config_command == "mode":
            got = config_mode(Path(args.path))
            _emit(args, got, got["mode"] + (" (work tree and origin differ)" if got["mismatch"] else ""))
        elif args.config_command == "pr-check":
            cmd = ["gh", "pr", "diff", str(args.pr)] + (["-R", args.gh_repo] if args.gh_repo else [])
            out = _run(cmd)
            if out.returncode != 0:
                raise ValueError(f"gh pr diff {args.pr} failed: {out.stderr.strip()[:200]}")
            changed = config_changed(out.stdout)
            _emit(args, {"pr": args.pr, "changes_config": changed},
                  "owner-only: the PR changes .caddis/coordinator.md" if changed else "no coordinator config change")
            return EXIT_LOCK_REFUSED if changed else EXIT_OK
        else:
            loaded = load_config(Path(args.path))
            _emit(args, loaded, json.dumps(loaded, indent=2))
        return EXIT_OK
    rid = args.repo or repo_id_for(Path.cwd())
    _repo_dir(rid)  # refuse a bad id before anything is written

    if args.command == "lock":
        if args.lock_command == "acquire":
            ok, holder = acquire_lock(rid, args.pid, args.session_id, args.name)
            if not ok:
                _emit(args, {"acquired": False, "holder": holder}, f"refused: {holder['error']}" if holder.get("error")
                      else f"refused: held by pid {holder.get('pid')} ({holder.get('name')})")
                return EXIT_LOCK_REFUSED
            _claim_state(rid, {"name": args.name, "sessionId": args.session_id, "pid": args.pid})
            _emit(args, {"acquired": True, "holder": None}, "acquired")
            return EXIT_OK
        if args.lock_command == "holder":
            holder = lock_holder(rid)
            _emit(args, holder or {"holder": None}, "no holder" if holder is None else
                  f"pid {holder['pid']} ({holder['name']}, session {holder['sessionId']}, "
                  f"{'alive' if holder['alive'] else 'not alive'})")
            return EXIT_OK
        release_lock(rid, args.pid)
        _emit(args, {"released": True}, "released")
        return EXIT_OK
    if args.command == "heartbeat":
        if not state_path(rid).exists():  # checked first so an unknown repo id leaves no folder or lock file behind
            raise ValueError(f"no coordinator state for repo {rid!r}")
        heartbeat(rid)
        _emit(args, {"ok": True}, "ok")
        return EXIT_OK
    if args.command == "watch":
        return watch(rid, args.pid, args.interval, args.max_cycles, takeover=args.takeover)
    if args.command == "intake":
        results = intake(rid, datetime.datetime.now(datetime.timezone.utc), _gh_head_of(rid))
        lines = [f"{r['id']}: {r['result']} {r['reason']}".rstrip() for r in results]
        _emit(args, results, "\n".join(lines) or "no new requests")
        return EXIT_OK
    if args.command == "state":
        state = read_state(rid)
        if state is None:
            raise ValueError(f"no coordinator state for repo {rid!r}")
        _emit(args, state, json.dumps(state, indent=2))
        return EXIT_OK
    if args.command == "queue" and args.queue_command == "next":
        state = read_state(rid)
        if state is None:
            raise ValueError(f"no coordinator state for repo {rid!r}")
        item = queue_next(state)
        _emit(args, {"next": item}, f"PR #{item['pr']}" if item else "none")
        return EXIT_OK
    if args.command == "deploy-verify":
        root = _deploy_root(args.config_path)
        out = deploy_verify(rid, load_config(root), args.pr, args.merge_sha, docs_only=args.docs_only,
                            runner=_deploy_run, repo_root=root)
        marks = " ".join(f"{name}={mark}" for name, mark in out["checks"].items())
        _emit(args, out, f"{out['health']}: {marks} ({out['reason']})")
        return EXIT_OK if out["health"] == "ok" else EXIT_ERROR
    if args.command == "deploy-check":
        deploy_check_set(rid, args.pr, deploy_run=args.run, health=args.health)
    elif args.command == "ledger":
        ledger_record(rid, what=args.what, decision=args.decision, by=args.by, reason=args.reason,
                      window=args.window, request_id=args.request_id)
    elif args.queue_command == "add":
        queue_add(rid, args.pr, args.head_sha, args.title if args.title is not None else _gh_title(rid, args.pr))
    elif args.queue_command == "set":
        queue_set(rid, args.pr, state=args.state, head_sha=args.head_sha, why_waiting=args.why_waiting,
                  waits_on=args.waits_on)
    elif args.queue_command == "ready":
        queue_set(rid, args.pr, state="ready")
    elif args.queue_command == "merged":
        if not queue_merged(rid, args.pr, args.merge_sha):
            _emit(args, {"ok": True, "result": "already recorded"}, "already recorded")
            return EXIT_OK
    else:
        queue_remove(rid, args.pr)
    _emit(args, {"ok": True}, "ok")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Run one subcommand. Exit 0 on success, 1 on an error (one line on stderr), 2 on a usage error, 3 when the
    lock is refused."""
    try:
        parser = _parser()
        args = parser.parse_args(argv)
        if args.command == "deploy-check" and args.run is None and args.health is None:
            parser.error("deploy-check set needs --run or --health")
        if args.command == "deploy-verify" and not _SHA.fullmatch(args.merge_sha):
            parser.error("deploy-verify --merge-sha must be a full 40-character SHA")
        if args.command == "lock" and args.lock_command == "acquire" and args.pid <= 0:
            parser.error("lock acquire --pid must be a positive process id")
        if args.command == "watch":
            if args.pid <= 0:
                parser.error("watch --pid must be a positive process id")
            if not 1 <= args.interval <= 86400:  # also refuses NaN and inf (time.sleep(inf) raises)
                parser.error("watch --interval must be 1 to 86400 seconds")
            if args.max_cycles is not None and args.max_cycles <= 0:
                parser.error("watch --max-cycles must be 1 or more")
    except _UsageError as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except SystemExit as exc:  # -h prints help and exits 0
        return EXIT_OK if exc.code in (0, None) else EXIT_USAGE
    try:
        return _dispatch(args)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        message = " ".join(str(exc).split()) or type(exc).__name__
        print(f"error: {message}", file=sys.stderr)
        return EXIT_ERROR
    except Exception as exc:  # last resort, e.g. a hand-edited state file: one line, no traceback
        message = " ".join(str(exc).split())
        print(f"error: unexpected {type(exc).__name__}" + (f": {message}" if message else ""), file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
