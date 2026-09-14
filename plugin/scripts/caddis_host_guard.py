"""caddis_host_guard — end runaway agent-started processes after sustained host saturation.

Usage:
    python caddis_host_guard.py run [--budget PATH] [--max-ticks N]
    python caddis_host_guard.py once [--budget PATH]
    python caddis_host_guard.py summary [--hours N]

Layer 3 of caddis resource protection (layer 1: BelowNormal priority; layer 2: Job Objects through
caddis_governor.py). It covers what layer 2 cannot: agents started without `caddis-run`, and a cap
set too loose. It runs as a LocalSystem service, because some agent sandboxes run commands under a
separate local account.

Every `sample_seconds` it samples host CPU and free memory. Every 2 seconds it records which
processes descend from a root agent image (claude.exe, codex.exe, agy.exe). A process stays marked
after its parent exits; creation times guard against a reused process id. After `sustain_seconds`
above `host_cpu_percent`, or below `min_free_memory_mb`, it ends the heaviest marked processes until
the excess is covered.

It never ends a root agent image, and never ends a process it has not marked (CI runners, the
desktop, services, dev servers); it reports those instead. Its settings come only from the
admin-owned machine budget, never from a user-writable file.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

EXIT_CONFIG = 3
LINEAGE_POLL_SECONDS = 2.0


class GuardError(Exception):
    """The guard's configuration cannot be used."""


@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    exe: str       # lowercased basename
    created: int   # creation time in 100 ns units; 0 when unknown
    governor: bool = False


@dataclass(frozen=True)
class GuardConfig:
    mode: str
    host_cpu_percent: int
    sustain_seconds: int
    sample_seconds: int
    min_free_memory_mb: int
    root_images: tuple[str, ...]


DEFAULT_GUARD = GuardConfig("enforce", 85, 60, 10, 4096, ("claude.exe", "codex.exe", "agy.exe"))


@dataclass
class Sample:
    ts: float
    host_cpu: float
    free_mb: int
    cpu_s: dict[int, float]
    mem_mb: dict[int, int] = field(default_factory=dict)


@dataclass
class Action:
    kind: str          # "end", "would-end" or "report"
    pid: int | None
    exe: str | None
    reason: str


# ── configuration ───────────────────────────────────────────────────────────

def _governor():
    """caddis_governor.py sits beside this file in the source tree, the plugin bundle and ProgramData."""
    path = Path(__file__).resolve().with_name("caddis_governor.py")
    if not path.is_file():
        raise GuardError(f"caddis_governor.py not found beside {Path(__file__).name}")
    spec = importlib.util.spec_from_file_location("_caddis_governor_for_guard", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # registered BEFORE exec: @dataclass looks the module up
    spec.loader.exec_module(mod)
    return mod


def _int(key: str, value: object, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise GuardError(f"invalid [guard] {key}: {value!r} (expected an integer {low}..{high})")
    return value


def load_guard_config(path: Path | None = None) -> GuardConfig:
    """The [guard] table of the MACHINE budget. A missing file means defaults; a broken one is an error."""
    file = path or _governor().machine_budget_path()
    if not file.is_file():
        return DEFAULT_GUARD
    try:
        import tomllib
    except ImportError as exc:
        raise GuardError(f"{file} exists but this Python has no tomllib (need 3.11+)") from exc
    try:
        table = tomllib.loads(file.read_text(encoding="utf-8")).get("guard", {})
    except Exception as exc:
        raise GuardError(f"cannot parse {file}: {exc}") from exc
    if not isinstance(table, dict):
        raise GuardError(f"[guard] in {file} is not a table")
    d = DEFAULT_GUARD
    mode = table.get("mode", d.mode)
    if mode not in ("enforce", "report"):
        raise GuardError(f"invalid [guard] mode: {mode!r} (expected 'enforce' or 'report')")
    roots = table.get("root_images", list(d.root_images))
    if not isinstance(roots, list) or not roots or not all(isinstance(r, str) and r.strip() for r in roots):
        raise GuardError(f"invalid [guard] root_images: {roots!r}")
    return GuardConfig(
        mode=mode,
        host_cpu_percent=_int("host_cpu_percent", table.get("host_cpu_percent", d.host_cpu_percent), 50, 99),
        sustain_seconds=_int("sustain_seconds", table.get("sustain_seconds", d.sustain_seconds), 1, 3600),
        sample_seconds=_int("sample_seconds", table.get("sample_seconds", d.sample_seconds), 1, 600),
        min_free_memory_mb=_int("min_free_memory_mb", table.get("min_free_memory_mb", d.min_free_memory_mb),
                                0, 1_048_576),
        root_images=tuple(r.strip().lower() for r in roots),
    )


# ── lineage and decisions (pure) ────────────────────────────────────────────

class Lineage:
    """Which live processes descend from a root agent image. A mark persists after the parent exits."""

    def __init__(self) -> None:
        self.marked: dict[int, int] = {}  # pid -> creation time when marked
        self.verified: set[int] = set()
        self.root_images: tuple[str, ...] = DEFAULT_GUARD.root_images

    def update(self, procs: dict[int, Proc], roots: tuple[str, ...]) -> None:
        self.root_images = roots
        self.verified = set()
        for pid in list(self.marked):
            p = procs.get(pid)
            if p is None or (p.created != 0 and p.created != self.marked[pid]):
                del self.marked[pid]  # exited, or the id now belongs to a different process
            elif p.created == self.marked[pid]:
                self.verified.add(pid)
        changed = True
        while changed:
            changed = False
            for p in procs.values():
                if p.pid in self.marked or p.created == 0:
                    continue
                if p.exe in roots or (p.ppid in self.verified and self.marked[p.ppid] <= p.created):
                    self.marked[p.pid] = p.created
                    self.verified.add(p.pid)
                    changed = True

    def is_agent(self, pid: int) -> bool:
        return pid in self.marked

    @staticmethod
    def is_root(proc: Proc, roots: tuple[str, ...]) -> bool:
        return proc.exe in roots


def protected_ancestors(procs: dict[int, Proc], roots: tuple[str, ...]) -> set[int]:
    """Protect roots, job owners, and every ancestor that could end them indirectly."""
    protected: set[int] = set()
    for proc in procs.values():
        if not (proc.exe in roots or proc.governor or proc.exe == "caddis_governor.exe"):
            continue
        current = proc
        while current.pid not in protected:
            protected.add(current.pid)
            parent = procs.get(current.ppid)
            if parent is None or (parent.created and current.created and parent.created > current.created):
                break
            current = parent
    return protected


def decide(window: list[Sample], lineage: Lineage, procs: dict[int, Proc], cfg: GuardConfig,
           cpu_count: int) -> list[Action]:
    """What to do about `window` (samples, oldest first). Pure: it never touches a process."""
    if not window:
        return []
    cutoff = window[-1].ts - cfg.sustain_seconds
    before = next((sample for sample in reversed(window) if sample.ts < cutoff), None)
    window = [sample for sample in window if sample.ts >= cutoff]
    if before is not None and window and window[0].ts > cutoff:
        after = window[0]
        fraction = (cutoff - before.ts) / (after.ts - before.ts)
        cpu_s = {pid: before.cpu_s.get(pid, value) + (value - before.cpu_s.get(pid, value)) * fraction
                 for pid, value in after.cpu_s.items()}
        window.insert(0, Sample(cutoff, after.host_cpu, after.free_mb, cpu_s, after.mem_mb))
    first, last = window[0], window[-1]
    span = last.ts - first.ts
    saturated = (len(window) >= 2 and span >= cfg.sustain_seconds
                 and all(s.host_cpu > cfg.host_cpu_percent for s in window))
    low_memory = last.free_mb < cfg.min_free_memory_mb
    if not (saturated or low_memory):
        return []

    protected = protected_ancestors(procs, cfg.root_images)
    candidates = [pid for pid, p in procs.items()
                  if pid in lineage.verified and lineage.marked.get(pid) == p.created
                  and pid not in protected]
    mean_cpu = sum(s.host_cpu for s in window) / len(window)
    kind = "end" if cfg.mode == "enforce" else "would-end"
    chosen: list[Action] = []

    if low_memory and last.mem_mb:
        by_mem = sorted((pid for pid in candidates if last.mem_mb.get(pid, 0) > 0),
                        key=lambda pid: last.mem_mb[pid], reverse=True)
        if by_mem:
            pid = by_mem[0]
            chosen.append(Action(kind, pid, procs[pid].exe,
                                 f"free memory {last.free_mb} MB; process uses {last.mem_mb[pid]} MB"))
            return chosen

    if span <= 0:
        return [Action("report", None, None,
                       "host saturated but no agent-descended process is using CPU")]

    used = {pid: max(0.0, last.cpu_s.get(pid, 0.0) - first.cpu_s.get(pid, 0.0)) for pid in candidates}
    ranked = sorted((pid for pid in candidates if used[pid] > 0), key=lambda pid: used[pid], reverse=True)
    excess = (mean_cpu - cfg.host_cpu_percent) / 100 * cpu_count
    if low_memory:
        excess = max(excess, 1.0)
    covered = 0.0
    for pid in ranked:
        if covered >= excess:
            break
        cores = used[pid] / span
        covered += cores
        chosen.append(Action(kind, pid, procs[pid].exe,
                             f"host cpu {mean_cpu:.0f}% for {span:.0f}s; process used {cores:.2f} cores"))
    if not chosen:
        chosen.append(Action("report", None, None,
                             "host saturated but no agent-descended process is using CPU"))
    return chosen


# ── log ─────────────────────────────────────────────────────────────────────

def guard_log_path() -> Path:
    override = os.environ.get("CADDIS_GUARD_LOG")
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "caddis" / "host-guard.jsonl"
    return Path.home() / ".caddis" / "host-guard.jsonl"


def append_log(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def summarise(log: Path, hours: int = 24, now: float | None = None) -> str:
    """One line for SessionStart about recent guard actions, or "" when there were none. Never raises."""
    try:
        cutoff = (time.time() if now is None else now) - hours * 3600
        hits = []
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("kind") in ("end", "end-failed", "would-end") and float(rec.get("ts", 0)) >= cutoff:
                hits.append(rec)
        if not hits:
            return ""
        ended = sum(len(r.get("killed", [])) for r in hits if r["kind"] == "end")
        flagged = sum(r["kind"] == "would-end" for r in hits)
        failed = sum(r["kind"] == "end-failed" or (r["kind"] == "end" and not r.get("killed"))
                     for r in hits)
        counts = []
        if ended:
            counts.append(f"{ended} agent process(es) ended")
        if flagged:
            counts.append(f"{flagged} agent process(es) flagged")
        if failed:
            counts.append(f"{failed} end attempt(s) without confirmed termination")
        last = hits[-1]
        when = datetime.fromtimestamp(float(last["ts"]), timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        return (f"[caddis] host guard: {', '.join(counts)} in the last {hours}h "
                f"(last: {last.get('exe')} pid {last.get('pid')} at {when}) — see {log}")
    except Exception:
        return ""


# ── Windows sampling (part 2) ───────────────────────────────────────────────

TH32CS_SNAPPROCESS = 0x2
PROCESS_TERMINATE = 0x1
PROCESS_VM_READ = 0x10
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ERROR_NO_MORE_FILES = 18

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")

    class UNICODE_STRING(ctypes.Structure):
        _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT),
                    ("Buffer", ctypes.c_void_p)]

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
                    ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
                    ("ullAvailExtendedVirtual", ctypes.c_uint64)]

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]

    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    kernel32.GetSystemTimes.argtypes = [ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME),
                                        ctypes.POINTER(FILETIME)]
    kernel32.GetSystemTimes.restype = wintypes.BOOL
    kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
    kernel32.GlobalMemoryStatusEx.restype = wintypes.BOOL
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME),
                                         ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME)]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                  wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    ntdll.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p,
                                               wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
    ntdll.NtQueryInformationProcess.restype = wintypes.LONG
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                                           wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL


def _win_error(call: str) -> GuardError:
    return GuardError(f"{call} failed: winerror {ctypes.get_last_error()}")


def _filetime_value(value: FILETIME) -> int:
    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)


def _times_for_handle(handle: int) -> tuple[int, float] | None:
    created = FILETIME()
    exited = FILETIME()
    kernel = FILETIME()
    user = FILETIME()
    if not kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                    ctypes.byref(kernel), ctypes.byref(user)):
        return None
    cpu_s = (_filetime_value(kernel) + _filetime_value(user)) / 1e7
    return _filetime_value(created), cpu_s


def host_cpu_percent(prev: tuple[int, int, int] | None) -> tuple[float, tuple[int, int, int]]:
    """Return CPU use since `prev`, plus the current GetSystemTimes counters."""
    idle = FILETIME()
    kernel = FILETIME()
    user = FILETIME()
    if not kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        raise _win_error("GetSystemTimes")
    current = (_filetime_value(idle), _filetime_value(kernel), _filetime_value(user))
    if prev is None:
        return 0.0, current
    di, dk, du = (current[i] - prev[i] for i in range(3))
    total = dk + du
    busy = 0.0 if total <= 0 else (total - di) / total * 100
    return max(0.0, min(100.0, busy)), current


def free_memory_mb() -> int:
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(status)
    if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise _win_error("GlobalMemoryStatusEx")
    return int(status.ullAvailPhys // (1024 * 1024))


def _open_process(pid: int, access: int = PROCESS_QUERY_LIMITED_INFORMATION) -> int | None:
    handle = kernel32.OpenProcess(access, False, pid)
    return int(handle) if handle else None


def _image_for_handle(handle: int) -> str | None:
    size = wintypes.DWORD(32768)
    buffer = ctypes.create_unicode_buffer(size.value)
    if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
        return None
    return Path(buffer.value).name.lower()


def _governor_for_handle(handle: int, exe: str) -> bool:
    if exe == "caddis_governor.exe":
        return True
    if not exe.startswith(("python", "pypy")):
        return False
    # ProcessCommandLineInformation returns a UNICODE_STRING backed by our buffer.
    # Treat an unreadable Python command line as a possible job owner.
    size = wintypes.ULONG()
    ntdll.NtQueryInformationProcess(handle, 60, None, 0, ctypes.byref(size))
    if not ctypes.sizeof(UNICODE_STRING) <= size.value <= 131072:
        return True
    buffer = ctypes.create_string_buffer(size.value)
    if ntdll.NtQueryInformationProcess(handle, 60, buffer, len(buffer), ctypes.byref(size)) < 0:
        return True
    value = UNICODE_STRING.from_buffer(buffer)
    start, end = ctypes.addressof(buffer), ctypes.addressof(buffer) + len(buffer)
    if (not value.Buffer or value.Length % 2 or value.Buffer < start
            or value.Buffer + value.Length > end):
        return True
    command = ctypes.wstring_at(value.Buffer, value.Length // 2).lower()
    return "caddis_governor" in command


def snapshot() -> dict[int, Proc]:
    """Return the current process table. An unreadable process has creation time zero."""
    # Convert Unix nanoseconds to the Windows FILETIME epoch before acquiring ancestry.
    started = time.time_ns() // 100 + 116444736000000000
    handle = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if handle == INVALID_HANDLE_VALUE:
        raise _win_error("CreateToolhelp32Snapshot")
    procs: dict[int, Proc] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        more = kernel32.Process32FirstW(handle, ctypes.byref(entry))
        if not more and ctypes.get_last_error() != ERROR_NO_MORE_FILES:
            raise _win_error("Process32FirstW")
        while more:
            pid = int(entry.th32ProcessID)
            exe = Path(entry.szExeFile).name.lower()
            created = 0
            governor = exe.startswith(("python", "pypy")) or exe == "caddis_governor.exe"
            process = _open_process(pid)
            if process is not None:
                try:
                    times = _times_for_handle(process)
                    image = _image_for_handle(process)
                    if times is not None and 0 < times[0] <= started and image == exe:
                        created = times[0]
                        governor = _governor_for_handle(process, image)
                finally:
                    kernel32.CloseHandle(process)
            procs[pid] = Proc(pid, int(entry.th32ParentProcessID), exe, created, governor)
            more = kernel32.Process32NextW(handle, ctypes.byref(entry))
        if ctypes.get_last_error() not in (0, ERROR_NO_MORE_FILES):
            raise _win_error("Process32NextW")
    finally:
        kernel32.CloseHandle(handle)
    return procs


def process_cpu_seconds(pids) -> dict[int, float]:
    values: dict[int, float] = {}
    for pid in pids:
        handle = _open_process(int(pid))
        if handle is None:
            continue
        try:
            times = _times_for_handle(handle)
            if times is not None:
                values[int(pid)] = times[1]
        finally:
            kernel32.CloseHandle(handle)
    return values


def process_memory_mb(pids) -> dict[int, int]:
    """Return each readable process's resident working set in MiB."""
    values: dict[int, int] = {}
    for pid in pids:
        handle = _open_process(int(pid), PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ)
        if handle is None:
            continue
        try:
            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(counters)
            if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                values[int(pid)] = int(counters.WorkingSetSize // (1024 * 1024))
        finally:
            kernel32.CloseHandle(handle)
    return values


def terminate_tree(pid: int, lineage: Lineage, procs: dict[int, Proc]) -> list[int]:
    """End a verified subtree, leaves first; hold identities through the whole operation."""
    target = procs.get(pid)
    if (target is None or target.created == 0 or lineage.marked.get(pid) != target.created
            or pid not in lineage.verified or pid in protected_ancestors(procs, lineage.root_images)):
        return []

    children: dict[int, list[int]] = {}
    for proc in procs.values():
        parent = procs.get(proc.ppid)
        if (parent is not None and (not parent.created or not proc.created
                                    or parent.created <= proc.created)):
            children.setdefault(parent.pid, []).append(proc.pid)

    order: list[int] = []
    seen: set[int] = set()

    def visit(current: int) -> None:
        if current in seen:
            return
        seen.add(current)
        for child in children.get(current, []):
            visit(child)
        order.append(current)

    visit(pid)
    ended: list[int] = []
    handles: dict[int, int] = {}
    try:
        # Check the entire subtree before ending any member. Unknown or reused identities
        # cannot establish that this is still safe, especially for a job owner.
        for current in order:
            proc = procs[current]
            if (not proc.created or current not in lineage.verified
                    or lineage.marked.get(current) != proc.created):
                return []
            handle = _open_process(current, PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION)
            if handle is None:
                return []
            handles[current] = handle
            times = _times_for_handle(handle)
            image = _image_for_handle(handle)
            if (times is None or times[0] != proc.created or image != proc.exe
                    or image in lineage.root_images or _governor_for_handle(handle, image)):
                return []
        for current in order:
            if kernel32.TerminateProcess(handles[current], 1):
                ended.append(current)
    finally:
        for handle in handles.values():
            kernel32.CloseHandle(handle)
    return ended


def _sample(prev_cpu: tuple[int, int, int] | None, lineage: Lineage,
            cfg: GuardConfig) -> tuple[Sample, tuple[int, int, int], dict[int, Proc]]:
    procs = snapshot()
    lineage.update(procs, cfg.root_images)
    cpu, current_cpu = host_cpu_percent(prev_cpu)
    sample = Sample(time.time(), cpu, free_memory_mb(), process_cpu_seconds(procs),
                    process_memory_mb(procs))
    return sample, current_cpu, procs


def _track_until(deadline: float, lineage: Lineage, roots: tuple[str, ...]) -> None:
    """Refresh lineage at most two seconds apart until the next full sample is due."""
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(LINEAGE_POLL_SECONDS, remaining))
        if deadline - time.monotonic() > 0:
            lineage.update(snapshot(), roots)


def run(budget: Path | None = None, max_ticks: int | None = None) -> int:
    if sys.platform != "win32":
        print("[caddis-host-guard] Windows-only in this build")
        return 0
    cfg = load_guard_config(budget)
    lineage = Lineage()
    window: list[Sample] = []
    previous_cpu = None
    ticks = 0
    while max_ticks is None or ticks < max_ticks:
        sample, previous_cpu, procs = _sample(previous_cpu, lineage, cfg)
        window.append(sample)
        cutoff = sample.ts - cfg.sustain_seconds
        while len(window) > 2 and window[1].ts <= cutoff:
            window.pop(0)  # retain one boundary sample so the window covers the full sustain period
        actions = decide(window, lineage, procs, cfg, os.cpu_count() or 1)
        for action in actions:
            ended = (terminate_tree(action.pid, lineage, procs)
                     if action.kind == "end" and action.pid is not None else [])
            kind = "end-failed" if action.kind == "end" and not ended else action.kind
            record = {"ts": sample.ts, "host_cpu": sample.host_cpu, "free_mb": sample.free_mb,
                      "kind": kind, "pid": action.pid, "exe": action.exe,
                      "reason": action.reason, "killed": ended, "ended_count": len(ended)}
            append_log(guard_log_path(), record)
            print(json.dumps(record, sort_keys=True), flush=True)
        ticks += 1
        if max_ticks is not None and ticks >= max_ticks:
            break
        _track_until(time.monotonic() + cfg.sample_seconds, lineage, cfg.root_images)
    return 0


def _once(budget: Path | None = None) -> int:
    if sys.platform != "win32":
        print("[caddis-host-guard] Windows-only in this build")
        return 0
    cfg = load_guard_config(budget)
    _, previous = host_cpu_percent(None)
    time.sleep(1)
    cpu, _ = host_cpu_percent(previous)
    procs = snapshot()
    lineage = Lineage()
    lineage.update(procs, cfg.root_images)
    print(json.dumps({"host_cpu": cpu, "free_mb": free_memory_mb(),
                      "agent_processes": len(lineage.marked)}, sort_keys=True))
    return 0


def _positive(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a positive integer") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="monitor the host continuously")
    run_parser.add_argument("--budget", type=Path)
    run_parser.add_argument("--max-ticks", type=_positive)
    once_parser = commands.add_parser("once", help="sample the host without taking action")
    once_parser.add_argument("--budget", type=Path)
    summary_parser = commands.add_parser("summary", help="report recent guard actions")
    summary_parser.add_argument("--hours", type=_positive, default=24)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return run(args.budget, args.max_ticks)
        if args.command == "once":
            return _once(args.budget)
        line = summarise(guard_log_path(), args.hours)
        if line:
            print(line)
        return 0
    except GuardError as exc:
        print(f"[caddis-host-guard] ERROR: {exc}", file=sys.stderr)
        return EXIT_CONFIG


if __name__ == "__main__":
    raise SystemExit(main())
