"""caddis_governor — run a command inside a capped Job Object so an agent can never saturate the host.

Usage:
    python caddis_governor.py exec --scope session|lane [--budget PATH] -- <command...>
    python caddis_governor.py show [--budget PATH]

Why this exists: on 2026-09-13 a coding-agent lane ran 32 all-core busy loops for about 36 minutes
on a shared dev box that was also a desktop and the CI runners, freezing both. A prompt rule cannot
stop that. A Job Object can: it caps CPU, memory and process count for a process and every process
it starts through normal process creation, whatever the prompt says.

How a process enters the job without a race: the governor assigns ITSELF to the job, then starts
the command. Every normally-created descendant inherits the job. Killing the governor ends its
handle to the job, and KILL_ON_JOB_CLOSE then kills the whole tree. After setup the governor keeps
only a query-only handle, and the job's DACL grants only query access to its owner, so a same-user
child can neither duplicate a writable handle nor open the job writable by name.

THREAT MODEL: an agent that ACCIDENTALLY or naively consumes resources (it was told to load the
box, or it "fixes" slow tests by raising a cap). The limits hold against that. They do NOT hold
against an agent deliberately escaping the job. Known escapes, documented rather than hidden:
  * a same-user process creating a child with a spoofed parent (PROC_THREAD_ATTRIBUTE_PARENT_PROCESS)
    or through out-of-process COM / shell activation (the child lands outside the job);
  * processes created by WMI, Task Scheduler, a service, or elevation;
  * work done inside an already-running server (a database, a model server, a container daemon).
The real fix for a hostile agent is running it under a separate low-privilege account.

Limits come from the user budget (~/.caddis/host-budget.toml) CLAMPED by the machine budget
(%ProgramData%\\caddis\\host-budget.toml on Windows, /etc/caddis/host-budget.toml elsewhere), which only
administrators can write. An agent can lower its own limits; it cannot raise them past the machine
ceiling. With no machine budget file, the ceiling is the built-in defaults, so the user budget can
only lower them.

On Linux the limits are applied with `systemd-run --user --scope`. Where that is unavailable (and on
macOS) the governor refuses (exit 3) unless `--allow-uncapped` is passed explicitly, which runs the
command at lower priority with a warning and never marks it as governed.

Nested jobs MULTIPLY CPU caps (measured 2026-09-14): an inner job's rate is a share of its parent's
allowance. So a lane inside a governed session asks for a rate relative to the session's cap. The
session is identified by a NAMED job (CADDIS_GOVERNED_JOB). The inner governor opens it for query,
proves it is a member, and reads the job's own CPU rate; the environment's percent is informational
only. (QueryInformationJobObject with a NULL handle is NOT a reliable way
to find the immediate job: measured, it returned an outer job's limits.)

Refuses to run the command at all when the limits cannot be applied (exit 3). Degrading open here
would be the exact failure this file exists to prevent.
"""
from __future__ import annotations

import argparse
import os
import secrets
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

EXIT_USAGE = 2
EXIT_CONFIG = 3
SCOPES = ("session", "lane")
MAX_CPU_PERCENT = 100
MAX_MEMORY_MB = 1_048_576
MAX_PROCESSES = 65_535


class GovernorError(Exception):
    """The limits could not be applied; the command must not run ungoverned."""


@dataclass(frozen=True)
class JobLimits:
    cpu_percent: int
    memory_mb: int
    max_processes: int


DEFAULT_BUDGET = {
    "session": JobLimits(50, 24576, 256),
    "lane": JobLimits(25, 8192, 64),
}

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount",
                                                    "OtherOperationCount", "ReadTransferCount",
                                                    "WriteTransferCount", "OtherTransferCount")]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION), ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    class JOBOBJECT_CPU_RATE_CONTROL_INFORMATION(ctypes.Structure):
        _fields_ = [("ControlFlags", wintypes.DWORD), ("CpuRate", wintypes.DWORD)]

    class JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
        _fields_ = [("TotalUserTime", ctypes.c_int64), ("TotalKernelTime", ctypes.c_int64),
                    ("ThisPeriodTotalUserTime", ctypes.c_int64), ("ThisPeriodTotalKernelTime", ctypes.c_int64),
                    ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
                    ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD)]

    class JOBOBJECT_BASIC_PROCESS_ID_LIST(ctypes.Structure):
        _fields_ = [("NumberOfAssignedProcesses", wintypes.DWORD), ("NumberOfProcessIdsInList", wintypes.DWORD),
                    ("ProcessIdList", ctypes.c_size_t * 1024)]

    class SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                    ("bInheritHandle", wintypes.BOOL)]

    JobObjectBasicAccountingInformation = 1
    JobObjectBasicProcessIdList = 3
    JobObjectExtendedLimitInformation = 9
    JobObjectCpuRateControlInformation = 15
    JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x8
    JOB_OBJECT_LIMIT_PRIORITY_CLASS = 0x20
    JOB_OBJECT_LIMIT_JOB_MEMORY = 0x200
    JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x800         # never set: a child could leave the job
    JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK = 0x1000  # never set: same, silently
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    JOB_OBJECT_CPU_RATE_CONTROL_ENABLE = 0x1
    JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP = 0x4
    BELOW_NORMAL_PRIORITY_CLASS = 0x4000
    JOB_OBJECT_QUERY = 0x0004
    ERROR_ALREADY_EXISTS = 183
    CSIDL_COMMON_APPDATA = 0x23
    SDDL_REVISION_1 = 1
    # SYSTEM and Administrators: full. OWNER RIGHTS and Everyone: query only. The explicit OWNER RIGHTS
    # ACE removes the owner's implicit WRITE_DAC, so the creating user cannot grant itself write access.
    JOB_SDDL = "D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;0x4;;;OW)(A;;0x4;;;WD)"

    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.OpenJobObjectW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.OpenJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                   wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    kernel32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    kernel32.IsProcessInJob.restype = wintypes.BOOL
    kernel32.DuplicateHandle.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
                                         ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL,
                                         wintypes.DWORD]
    kernel32.DuplicateHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.ULONG)]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    shell32.SHGetFolderPathW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.HANDLE, wintypes.DWORD,
                                         wintypes.LPWSTR]
    shell32.SHGetFolderPathW.restype = ctypes.c_long


# ── limits ──────────────────────────────────────────────────────────────────

def budget_path() -> Path:
    """The user budget. Agent-writable, so it can only LOWER limits below the machine ceiling."""
    return Path(os.environ.get("CADDIS_HOME") or Path.home()) / ".caddis" / "host-budget.toml"


def machine_budget_path() -> Path:
    """The admin-owned ceiling. Resolved without environment variables an agent could persist."""
    if sys.platform == "win32":
        buf = ctypes.create_unicode_buffer(260)
        if shell32.SHGetFolderPathW(None, CSIDL_COMMON_APPDATA, None, 0, buf) == 0 and buf.value:
            return Path(buf.value) / "caddis" / "host-budget.toml"
        return Path(r"C:\ProgramData") / "caddis" / "host-budget.toml"
    return Path("/etc/caddis/host-budget.toml")


def _as_int(scope: str, key: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GovernorError(f"invalid [{scope}] {key}: {value!r}")
    return value


def _read_table(file: Path, scope: str) -> dict:
    try:
        import tomllib
    except ImportError as exc:
        # An existing budget that cannot be read must not silently become the (looser) defaults.
        raise GovernorError(f"{file} exists but this Python has no tomllib (need 3.11+)") from exc
    try:
        data = tomllib.loads(file.read_text(encoding="utf-8"))
    except Exception as exc:  # a broken budget must never silently fall back to defaults
        raise GovernorError(f"cannot parse {file}: {exc}") from exc
    table = data.get(scope, {})
    if not isinstance(table, dict):
        raise GovernorError(f"[{scope}] in {file} is not a table")
    return table


def _validated(scope: str, table: dict, base: JobLimits) -> JobLimits:
    values = {
        "cpu_percent": _as_int(scope, "cpu_percent", table.get("cpu_percent", base.cpu_percent)),
        "memory_mb": _as_int(scope, "memory_mb", table.get("memory_mb", base.memory_mb)),
        "max_processes": _as_int(scope, "max_processes", table.get("max_processes", base.max_processes)),
    }
    if not 1 <= values["cpu_percent"] <= MAX_CPU_PERCENT:
        raise GovernorError(f"invalid [{scope}] cpu_percent: {values['cpu_percent']}")
    if not 256 <= values["memory_mb"] <= MAX_MEMORY_MB:
        raise GovernorError(f"invalid [{scope}] memory_mb: {values['memory_mb']}")
    if not 4 <= values["max_processes"] <= MAX_PROCESSES:
        raise GovernorError(f"invalid [{scope}] max_processes: {values['max_processes']}")
    return JobLimits(**values)


def load_limits(scope: str, path: Path | None = None, machine_path: Path | None = None) -> JobLimits:
    """The limits for `scope`: the user budget (or defaults), clamped by the machine ceiling.

    With no machine budget file the defaults are the ceiling. A broken or unreadable file is an error.
    An optional machine_path adds a stricter ceiling; it never replaces the real machine budget.
    """
    if scope not in SCOPES:
        raise GovernorError(f"unknown scope: {scope!r} (expected one of {', '.join(SCOPES)})")
    user_file = path or budget_path()
    limits = DEFAULT_BUDGET[scope]
    if user_file.is_file():
        limits = _validated(scope, _read_table(user_file, scope), limits)
    ceiling_file = machine_budget_path()
    # No admin ceiling: the defaults ARE the ceiling, so an agent-writable budget can only lower them.
    ceiling = DEFAULT_BUDGET[scope]
    if ceiling_file.is_file():
        # Keys the admin file does not set keep the DEFAULT ceiling: a partial or empty admin file
        # must never be weaker than no file at all.
        ceiling = _validated(scope, _read_table(ceiling_file, scope), DEFAULT_BUDGET[scope])
    if machine_path is not None and machine_path.is_file():
        requested = _validated(scope, _read_table(machine_path, scope), ceiling)
        ceiling = JobLimits(min(ceiling.cpu_percent, requested.cpu_percent),
                            min(ceiling.memory_mb, requested.memory_mb),
                            min(ceiling.max_processes, requested.max_processes))
    return JobLimits(min(limits.cpu_percent, ceiling.cpu_percent),
                     min(limits.memory_mb, ceiling.memory_mb),
                     min(limits.max_processes, ceiling.max_processes))


# ── nesting ─────────────────────────────────────────────────────────────────

def verified_parent_percent(env: dict | None = None) -> int | None:
    """The enclosing governed job's machine percent, or None when it cannot be PROVEN (Windows).

    Opens the job named by CADDIS_GOVERNED_JOB for query, requires that this process is a member and
    that the job has CPU hard-cap control, and reads the job's own CpuRate (rounded up). The
    environment's percent is informational only and never used here.
    """
    if sys.platform != "win32":
        return None
    e = os.environ if env is None else env
    name = str(e.get("CADDIS_GOVERNED_JOB", "")).strip()
    if not name:
        return None
    job = kernel32.OpenJobObjectW(JOB_OBJECT_QUERY, False, name)
    if not job:
        return None
    try:
        member = wintypes.BOOL()
        if not kernel32.IsProcessInJob(kernel32.GetCurrentProcess(), job, ctypes.byref(member)) or not member.value:
            return None
        cr = JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
        if not kernel32.QueryInformationJobObject(job, JobObjectCpuRateControlInformation, ctypes.byref(cr),
                                                  ctypes.sizeof(cr), None):
            return None
        want = JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP
        if cr.ControlFlags & want != want or cr.CpuRate < 1:
            return None
        # A nested job's CpuRate is a share of ITS parent, so it bounds the machine percent from above.
        # The environment's percent is deliberately NOT used: this value is a divisor, so a lower
        # number would widen the lane's cap. Round up for the same reason.
        return max(1, (cr.CpuRate + 99) // 100)
    finally:
        kernel32.CloseHandle(job)


def effective_cpu_rate(limits: JobLimits, parent_percent: int | None) -> int:
    """CpuRate for the job: percent x 100, relative to an enclosing governed job when nested.

    Nested job caps multiply, so a lane inside a 50% session asks for 25/50 of the session's
    allowance to end up with 25% of the machine. With no verified parent the rate is absolute.
    """
    if parent_percent is None:
        return limits.cpu_percent * 100
    return max(1, min(10000, round(limits.cpu_percent * 10000 / parent_percent)))


def effective_machine_percent(limits: JobLimits, parent_percent: int | None) -> int:
    return limits.cpu_percent if parent_percent is None else min(limits.cpu_percent, parent_percent)


# ── Windows Job Objects ─────────────────────────────────────────────────────

def _winerr(call: str) -> GovernorError:
    return GovernorError(f"{call} failed: winerror {ctypes.get_last_error()}")


def new_job_name() -> str:
    return f"Local\\caddis-governor-{os.getpid()}-{secrets.token_hex(8)}"


def create_job(limits: JobLimits, cpu_rate: int | None = None, name: str | None = None) -> int:
    """A new, non-inheritable, full-access job handle with every limit applied. Windows only.

    A named job gets a DACL that grants its owner query access only, and refuses a name that exists.
    """
    sd = ctypes.c_void_p()
    sa = None
    if name is not None:
        if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(JOB_SDDL, SDDL_REVISION_1,
                                                                            ctypes.byref(sd), None):
            raise _winerr("ConvertStringSecurityDescriptorToSecurityDescriptorW")
        sa = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), sd, False)
    try:
        job = kernel32.CreateJobObjectW(ctypes.byref(sa) if sa is not None else None, name)
        err = ctypes.get_last_error()  # read before LocalFree can overwrite it
    finally:
        if sd:
            kernel32.LocalFree(sd)
    already = err == ERROR_ALREADY_EXISTS
    if not job:
        raise GovernorError(f"CreateJobObjectW failed: winerror {err}")
    try:
        if name is not None and already:
            raise GovernorError(f"a job named {name} already exists; refusing to join a job we did not create")
        flags = (JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
                 | JOB_OBJECT_LIMIT_PRIORITY_CLASS | JOB_OBJECT_LIMIT_JOB_MEMORY)
        if flags & (JOB_OBJECT_LIMIT_BREAKAWAY_OK | JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK):
            raise GovernorError("breakaway flags must never be set")
        ext = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        ext.BasicLimitInformation.LimitFlags = flags
        ext.BasicLimitInformation.ActiveProcessLimit = limits.max_processes
        ext.BasicLimitInformation.PriorityClass = BELOW_NORMAL_PRIORITY_CLASS
        ext.JobMemoryLimit = limits.memory_mb * 1024 * 1024
        if not kernel32.SetInformationJobObject(job, JobObjectExtendedLimitInformation,
                                                ctypes.byref(ext), ctypes.sizeof(ext)):
            raise _winerr("SetInformationJobObject(extended limits)")
        rate = limits.cpu_percent * 100 if cpu_rate is None else cpu_rate
        cr = JOBOBJECT_CPU_RATE_CONTROL_INFORMATION(
            JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP, rate)
        if not kernel32.SetInformationJobObject(job, JobObjectCpuRateControlInformation,
                                                ctypes.byref(cr), ctypes.sizeof(cr)):
            raise _winerr("SetInformationJobObject(cpu rate)")
    except BaseException:
        kernel32.CloseHandle(job)
        raise
    return job


def assign_current_process(job: int) -> None:
    if not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()):
        raise _winerr("AssignProcessToJobObject")


def reduce_to_query_handle(job: int) -> int:
    """Swap the full-access handle for a JOB_OBJECT_QUERY-only duplicate and close the original.

    A same-user child can duplicate any handle the governor holds. After this, the only handle it
    can reach cannot change limits. The query handle keeps the job alive, so KILL_ON_JOB_CLOSE still
    fires when the governor exits.
    """
    me = kernel32.GetCurrentProcess()
    query = wintypes.HANDLE()
    if not kernel32.DuplicateHandle(me, job, me, ctypes.byref(query), JOB_OBJECT_QUERY, False, 0):
        raise _winerr("DuplicateHandle(JOB_OBJECT_QUERY)")
    kernel32.CloseHandle(job)
    return query.value


def job_cpu_seconds(job: int) -> float:
    acc = JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
    if not kernel32.QueryInformationJobObject(job, JobObjectBasicAccountingInformation, ctypes.byref(acc),
                                              ctypes.sizeof(acc), None):
        raise _winerr("QueryInformationJobObject(accounting)")
    return (acc.TotalUserTime + acc.TotalKernelTime) / 1e7


def job_process_ids(job: int) -> list[int]:
    """Up to 1024 process ids in the job (the fixed buffer size)."""
    lst = JOBOBJECT_BASIC_PROCESS_ID_LIST()
    if not kernel32.QueryInformationJobObject(job, JobObjectBasicProcessIdList, ctypes.byref(lst),
                                              ctypes.sizeof(lst), None):
        raise _winerr("QueryInformationJobObject(process ids)")
    return [int(lst.ProcessIdList[i]) for i in range(lst.NumberOfProcessIdsInList)]


def close_job(job: int) -> None:
    """Close a job handle. Never call it on the last handle of a job the calling process belongs to."""
    kernel32.CloseHandle(job)


# ── other platforms ─────────────────────────────────────────────────────────

def posix_argv(argv: list[str], limits: JobLimits, which=shutil.which, cpu_count=os.cpu_count) -> list[str] | None:
    """systemd user scope limits. Weaker than a Job Object: user scopes do not nest (a lane scope is
    a sibling of its session scope), an agent can call `systemd-run --user` itself, and CPUQuota is
    silently ignored when the cpu controller is not delegated to the user manager. TasksMax counts
    THREADS, not processes, so on Linux `max_processes` is a thread limit."""
    if not which("systemd-run"):
        return None
    return ["systemd-run", "--user", "--scope", "--quiet",
            "-p", f"CPUQuota={limits.cpu_percent * (cpu_count() or 1)}%",
            "-p", f"MemoryMax={limits.memory_mb}M",
            "-p", f"TasksMax={limits.max_processes}",
            "--", *argv]


# ── exec ────────────────────────────────────────────────────────────────────

def _run_child(argv: list[str], env: dict) -> int:
    try:
        # CreateProcess does not search PATHEXT. Resolve npm-style .CMD shims before launch.
        command = shutil.which(argv[0], path=env.get("PATH"))
        if command is None:
            raise FileNotFoundError(argv[0])
        return subprocess.run([command, *argv[1:]], env=env).returncode
    except FileNotFoundError:
        sys.stderr.write(f"[caddis-governor] command not found: {argv[0]}\n")
        return 127
    except KeyboardInterrupt:
        return 130


def _host_kind() -> str:
    """Return "windows" (native Python), "non-native-windows" (MSYS2/Cygwin on Windows) or "posix"."""
    if sys.platform in ("cygwin", "msys") or (os.name == "nt" and sys.platform != "win32"):
        return "non-native-windows"
    return "windows" if sys.platform == "win32" else "posix"


def exec_governed(argv: list[str], scope: str, budget: Path | None = None,
                  machine_budget: Path | None = None, allow_uncapped: bool = False) -> int:
    """Run `argv` under the scope's limits and return its exit code.

    On Windows this puts the CURRENT process into the job for the rest of its life, so it is only
    called from the `exec` entry point. The last job handle is never closed explicitly: the governor
    is a member, so closing it would kill the governor before it returns the exit code. Process exit
    closes it instead, which also kills any descendants the command left behind.
    """
    try:
        host = _host_kind()
        if host == "non-native-windows":
            raise GovernorError(f"a non-native Python ({sys.platform}) on Windows cannot create Job "
                                "Objects; run the governor with a native Windows python")
        limits = load_limits(scope, budget, machine_budget)
        env = dict(os.environ)
        if host == "windows":
            parent = verified_parent_percent(os.environ)
            rate = effective_cpu_rate(limits, parent)
            machine_pct = effective_machine_percent(limits, parent)
            name = new_job_name()
            job = create_job(limits, rate, name)
            try:
                assign_current_process(job)
            except BaseException:
                close_job(job)  # safe: the assignment failed, so we are not a member
                raise
            reduce_to_query_handle(job)  # the query handle stays open for the governor's lifetime
            env["CADDIS_GOVERNED"] = scope
            env["CADDIS_GOVERNED_JOB"] = name
            env["CADDIS_GOVERNED_CPU_PERCENT"] = str(machine_pct)
            sys.stderr.write(f"[caddis-governor] scope={scope} cpu={machine_pct}% "
                             f"mem={limits.memory_mb}MB procs={limits.max_processes} pid={os.getpid()}\n")
            sys.stderr.flush()
            return _run_child(argv, env)
        wrapped = posix_argv(argv, limits)
        if wrapped is None:
            if not allow_uncapped:
                raise GovernorError("no systemd-run on this platform, so no cap can be applied; "
                                    "pass --allow-uncapped to run at lower priority only")
            try:
                os.nice(10)
                how = "lower priority only"
            except (AttributeError, OSError) as exc:
                how = f"priority could NOT be lowered ({type(exc).__name__})"
            sys.stderr.write(f"[caddis-governor] WARNING: --allow-uncapped: no CPU cap; {how}\n")
            wrapped = argv  # CADDIS_GOVERNED is NOT set: nothing downstream may believe a cap exists
        else:
            env["CADDIS_GOVERNED"] = scope
        sys.stderr.flush()
        return _run_child(wrapped, env)
    except GovernorError as exc:
        sys.stderr.write(f"[caddis-governor] REFUSING to run ungoverned: {exc}\n")
        return EXIT_CONFIG


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    command: list[str] = []
    if "--" in raw:
        i = raw.index("--")
        raw, command = raw[:i], raw[i + 1:]
    parser = argparse.ArgumentParser(prog="caddis_governor", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_exec = sub.add_parser("exec", help="run a command inside a capped job")
    p_exec.add_argument("--scope", choices=SCOPES, required=True)
    p_exec.add_argument("--budget", type=Path)
    p_exec.add_argument("--machine-budget", type=Path, help=argparse.SUPPRESS)  # additional ceiling only
    p_exec.add_argument("--allow-uncapped", action="store_true",
                        help="where no cap can be applied (no systemd-run, macOS), run at lower priority anyway")
    p_show = sub.add_parser("show", help="print the effective limits")
    p_show.add_argument("--budget", type=Path)
    p_show.add_argument("--machine-budget", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(raw)

    if args.cmd == "show":
        try:
            for scope in SCOPES:
                lim = load_limits(scope, args.budget, args.machine_budget)
                print(f"{scope} cpu={lim.cpu_percent}% mem={lim.memory_mb}MB procs={lim.max_processes}")
        except GovernorError as exc:
            sys.stderr.write(f"[caddis-governor] {exc}\n")
            return EXIT_CONFIG
        return 0

    if not command:
        sys.stderr.write("usage: caddis_governor.py exec --scope session|lane [--budget PATH] -- <command...>\n")
        return EXIT_USAGE
    return exec_governed(command, args.scope, args.budget, args.machine_budget, args.allow_uncapped)


if __name__ == "__main__":
    sys.exit(main())
