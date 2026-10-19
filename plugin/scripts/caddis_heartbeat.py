"""One small heartbeat file per live session, so `caddis doctor` can name sessions on an old caddis.

WHY (robustness audit #18, 18 Oct 2026). A plugin update reaches only NEW sessions. A session that
started before the update keeps the old hooks and the old guard until it restarts (or runs
/reload-plugins), and nothing on the machine said which sessions those were. Each SessionStart (and
PreCompact) now writes `~/.caddis/sessions/<session-id>.json`:

    {"session_id", "harness", "caddis_version", "pid", "started", "last_seen"}

`caddis doctor` reads the folder and lists the live sessions whose version is older than the installed one.

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
        pid = int(entry.get("pid", 0))
    except (TypeError, ValueError):
        return False
    return now - last_seen <= STALE_AFTER_S and alive(pid)


def beat(session_id: str, version: "str | None", harness: str, pid: "int | None" = None,
         home: "str | Path | None" = None, now: "float | None" = None) -> "Path | None":
    """Write (or refresh) this session's heartbeat. Returns its path, or None when nothing was written."""
    try:
        if not session_id or not enabled():
            return None
        now = time.time() if now is None else now
        pid = session_pid() if pid is None else pid
        folder = sessions_dir(home)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / (_SAFE_ID.sub("_", session_id)[:120] + ".json")
        old = _read(target)
        started = old.get("started") if old and old.get("pid") == pid else None
        entry = {"session_id": session_id, "harness": harness, "caddis_version": version, "pid": pid,
                 "started": started if isinstance(started, (int, float)) else now, "last_seen": now}
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
