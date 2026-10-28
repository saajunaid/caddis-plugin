"""One small heartbeat file per live session, so `caddis doctor` can name sessions on an old caddis.

WHY (robustness audit #18, 18 Oct 2026). A plugin update reaches only NEW sessions. A session that
started before the update keeps the old hooks and the old guard until it restarts (or runs
/reload-plugins), and nothing on the machine said which sessions those were. Each SessionStart (and
PreCompact) now writes `~/.caddis/sessions/<session-id>.json`:

    {"session_id", "harness", "caddis_version", "pid", "started", "last_seen"}

`caddis doctor` reads the folder and lists the live sessions whose version is older than the installed one.

STATUS BEATS (26 Oct 2026). The caddis hub lists live sessions. Claude Code sessions come from
`claude agents --json`; any other agent (agy today) writes a STATUS beat into the same folder. It is the
same file with more keys, so `caddis doctor` still reads it:

    {..., "status": "working" | "waiting", "status_since", "cwd", "repo_path", "waiting_for"}

`pid` may be null when the agent process cannot be found; such an entry expires by time only
(NO_PID_STALE_AFTER_S). `agy_beat` is the agy adapter: the PreInvocation hook writes `working`, the
Stop hook writes `waiting`. The format is documented in cli/README.md (the `caddis hub` section).

RULES
- Atomic: a temp file in the same folder, then os.replace. A reader never sees half a file.
- Cheap expiry: every beat prunes the entries whose pid is dead or whose last_seen is older than
  STALE_AFTER_S (a pid reused by another program after a long time). No subprocess: the pid check is
  OpenProcess on Windows and kill(pid, 0) elsewhere.
- Fail open: every public function catches its own errors. A heartbeat must never break a session start.
- `CADDIS_HOME` moves the home folder (tests and sandboxes); `CADDIS_HEARTBEAT=0` turns the writes off.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

STALE_AFTER_S = 7 * 86400  # also used by the CLI doctor (cli/src/util/sessions.ts); keep the two equal
# An entry with no pid cannot be checked for life, so it expires sooner. The hub drops it at the same age
# (AGENT_DROP_AFTER_MS in cli/src/hub/sources/beats.ts); keep the two equal.
NO_PID_STALE_AFTER_S = 86400
STATUSES = ("working", "waiting")
# How many parents agent_pid() climbs: hook <- shell <- agent is the deep case; this leaves room.
_MAX_ANCESTORS = 8
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]")


def sessions_dir(home: "str | Path | None" = None) -> Path:
    root = Path(home) if home else Path(os.environ.get("CADDIS_HOME") or Path.home())
    return root / ".caddis" / "sessions"


def enabled() -> bool:
    return os.environ.get("CADDIS_HEARTBEAT", "1").strip() != "0"


def plugin_version(plugin_root: "str | Path | None") -> "str | None":
    """The caddis version of the plugin this hook runs from, or None when it cannot be read."""
    if not plugin_root:
        return None
    root = Path(plugin_root)
    for manifest in (root / ".claude-plugin" / "plugin.json", root / "plugin.json"):
        try:
            version = json.loads(manifest.read_text(encoding="utf-8")).get("version")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(version, str) and version:
            return version
    return None


def session_pid() -> int:
    """The pid of the agent process. Claude Code exports CLAUDE_PID; otherwise the hook's parent."""
    raw = os.environ.get("CLAUDE_PID", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return os.getppid()


def pid_alive(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if sys.platform == "win32":
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
            return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED: it exists, this user may not open it
        try:
            code = wintypes.DWORD()
            return bool(k.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            k.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read(path: Path) -> "dict | None":
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _is_live(entry: "dict | None", now: float, alive: Callable[[int], bool]) -> bool:
    if not entry:
        return False
    try:
        last_seen = float(entry.get("last_seen", 0))
        if entry.get("pid") is None and entry.get("status") in STATUSES:
            return now - last_seen <= NO_PID_STALE_AFTER_S
        pid = int(entry.get("pid", 0))
    except (TypeError, ValueError):
        return False
    return now - last_seen <= STALE_AFTER_S and alive(pid)


def repo_top(cwd: "str | None") -> "str | None":
    """The folder that holds `.git` (a dir, or a worktree's file) at or above `cwd`. No subprocess, no network."""
    if not cwd:
        return None
    try:
        here = Path(cwd).resolve()
        for folder in (here, *here.parents):
            if (folder / ".git").exists():
                return str(folder)
    except (OSError, ValueError):
        return None
    return None


def _process_table() -> "dict[int, tuple[int, str]]":
    """pid -> (parent pid, image name, lowercase). Windows: one Toolhelp snapshot; Linux: /proc. Else empty."""
    table: dict[int, tuple[int, str]] = {}
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class _Entry(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                        ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
        k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_Entry))
        k.Process32FirstW.restype = wintypes.BOOL
        k.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_Entry))
        k.Process32NextW.restype = wintypes.BOOL
        k.CloseHandle.argtypes = (wintypes.HANDLE,)
        snap = k.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
        if not snap or snap == ctypes.c_void_p(-1).value:
            return table
        try:
            entry = _Entry()
            entry.dwSize = ctypes.sizeof(_Entry)
            more = k.Process32FirstW(snap, ctypes.byref(entry))
            while more:
                table[int(entry.th32ProcessID)] = (int(entry.th32ParentProcessID), entry.szExeFile.lower())
                more = k.Process32NextW(snap, ctypes.byref(entry))
        finally:
            k.CloseHandle(snap)
        return table
    proc = Path("/proc")
    if not proc.is_dir():
        return table
    pid = os.getpid()  # only this process's own chain: a few small reads, not the whole table
    for _ in range(_MAX_ANCESTORS + 1):
        try:
            stat = (proc / str(pid) / "stat").read_text(encoding="utf-8", errors="replace")
            name = stat[stat.index("(") + 1:stat.rindex(")")].lower()
            ppid = int(stat[stat.rindex(")") + 2:].split()[1])
        except (OSError, ValueError, IndexError):
            break
        table[pid] = (ppid, name)
        if ppid <= 0:
            break
        pid = ppid
    return table


def agent_pid(image: str, start: "int | None" = None,
              table: "dict[int, tuple[int, str]] | None" = None) -> "int | None":
    """The pid of the nearest ancestor whose image is `image` (or `image`.exe), else None. Never raises.

    A hook's parent may be a short-lived shell, so the parent pid alone would look dead at once. Climbing to
    the agent's own process gives the hub a pid that lives as long as the session's window.
    """
    try:
        want = {image.lower(), image.lower() + ".exe"}
        table = _process_table() if table is None else table
        pid = os.getpid() if start is None else start
        for _ in range(_MAX_ANCESTORS):
            row = table.get(pid)
            if row is None:
                return None
            ppid = row[0]
            parent = table.get(ppid)
            if parent is None or ppid == pid:
                return None
            if parent[1] in want:
                return ppid
            pid = ppid
    except Exception:
        return None
    return None


def beat(session_id: str, version: "str | None", harness: str, pid: "int | None" = None,
         home: "str | Path | None" = None, now: "float | None" = None, *, status: "str | None" = None,
         cwd: "str | None" = None, waiting_for: "str | None" = None) -> "Path | None":
    """Write (or refresh) this session's heartbeat. Returns its path, or None when nothing was written.

    Without `status` this is the Claude Code heartbeat, and `pid=None` means "this session's pid". With
    `status` (one of STATUSES) it is a status beat for the hub: `pid=None` stays null (unknown), and the
    status keys are added.
    """
    try:
        if not session_id or not enabled():
            return None
        if status is not None and status not in STATUSES:
            return None
        now = time.time() if now is None else now
        if pid is None and status is None:
            pid = session_pid()
        folder = sessions_dir(home)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / (_SAFE_ID.sub("_", session_id)[:120] + ".json")
        old = _read(target)
        started = old.get("started") if old and old.get("pid") == pid else None
        entry = {"session_id": session_id, "harness": harness, "caddis_version": version, "pid": pid,
                 "started": started if isinstance(started, (int, float)) else now, "last_seen": now}
        if status is not None:
            since = old.get("status_since") if old and old.get("status") == status else None
            entry.update({"status": status, "status_since": since if isinstance(since, (int, float)) else now,
                          "cwd": cwd or None, "repo_path": repo_top(cwd),
                          "waiting_for": waiting_for if status == "waiting" else None})
        fd, tmp = tempfile.mkstemp(dir=str(folder), prefix=".hb-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(entry, fh)
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        prune(home=home, now=now, keep=target)
        return target
    except Exception:
        return None


_AGY_WAITING_FOR = {"max_steps_exceeded": "step limit reached", "error": "an error to be read"}


def agy_beat(data: object, status: str, home: "str | Path | None" = None, now: "float | None" = None,
             plugin_root: "str | Path | None" = None) -> "Path | None":
    """The agy adapter: write a status beat from an agy hook payload. Never raises.

    agy's payload (camelCase) gives `conversationId` and `workspacePaths`; the hook's own cwd is the plugin
    folder, so it is never used as the session's folder. With no id, the id is stable per agy process.
    """
    try:
        data = data if isinstance(data, dict) else {}
        pid = agent_pid("agy")
        conv = data.get("conversationId")
        session_id = conv.strip() if isinstance(conv, str) and conv.strip() else f"agy-{pid or os.getppid()}"
        roots = data.get("workspacePaths")
        roots = [r for r in roots if isinstance(r, str) and r.strip()] if isinstance(roots, list) else []
        reason = data.get("terminationReason")
        waiting_for = _AGY_WAITING_FOR.get(reason, "input needed") if isinstance(reason, str) else "input needed"
        return beat(session_id, plugin_version(plugin_root), "agy", pid=pid, home=home, now=now,
                    status=status, cwd=roots[0] if roots else None, waiting_for=waiting_for)
    except Exception:
        return None


def prune(home: "str | Path | None" = None, now: "float | None" = None,
          alive: Callable[[int], bool] = pid_alive, keep: "Path | None" = None) -> int:
    """Remove dead or stale heartbeats (and temp files older than an hour). Returns how many went."""
    removed = 0
    try:
        now = time.time() if now is None else now
        for path in sessions_dir(home).iterdir():
            if keep is not None and path == keep:
                continue
            try:
                if path.name.startswith(".hb-"):
                    gone = now - path.stat().st_mtime > 3600
                elif path.suffix == ".json":
                    gone = not _is_live(_read(path), now, alive)
                else:
                    continue
                if gone:
                    path.unlink()
                    removed += 1
            except OSError:
                continue
    except OSError:
        pass
    return removed


def live(home: "str | Path | None" = None, now: "float | None" = None,
         alive: Callable[[int], bool] = pid_alive) -> list[dict]:
    """The live heartbeats, oldest start first. Read-only."""
    now = time.time() if now is None else now
    out = []
    try:
        for path in sessions_dir(home).glob("*.json"):
            entry = _read(path)
            if _is_live(entry, now, alive):
                out.append(entry)
    except OSError:
        return []
    return sorted(out, key=lambda e: e.get("started") or 0)
