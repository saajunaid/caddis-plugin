#!/usr/bin/env python3
"""caddis_hidden_desktop - run a command on a separate, invisible Windows desktop.

Why (20 Oct 2026, seen on the owner's screen): agy starts its own tool processes (shell commands, MCP servers) as
visible consoles, so every agy call flashed windows on the desktop. CREATE_NO_WINDOW and SW_HIDE on agy do not
reach those grandchildren. A process started on another desktop opens all its windows there, and its children
inherit that desktop, so nothing appears on the owner's screen.

    python caddis_hidden_desktop.py -- <program> [args...]

- Creates (or opens, when it exists) the desktop "caddis-hidden" in this process's window station and starts the
  command on it with CREATE_NO_WINDOW. The command inherits this process's stdin, stdout and stderr handles, its
  environment and its working directory.
- The command runs in a job object with KILL_ON_JOB_CLOSE: when this launcher ends for any reason (normal exit,
  Ctrl-C, taskkill), the command and everything it started end too.
- Exits with the command's exit code.
- When the hidden desktop cannot be used, runs the command normally (CREATE_NO_WINDOW) and says so on stderr once.
  Hiding never makes a call fail. A program that does not exist exits 127.
- On other operating systems it just runs the command.

caddis_spend.hidden_argv() builds the command line that uses this file; set CADDIS_AGY_VISIBLE=1 to opt out.
"""

from __future__ import annotations

import os
import subprocess
import sys

DESKTOP_NAME = "caddis-hidden"
CREATE_NO_WINDOW = 0x08000000
EXIT_NOT_FOUND = 127
EXIT_INTERRUPTED = 130


def _signed(code: int) -> int:
    """A DWORD exit code as the signed int sys.exit accepts on Windows (same bits for ExitProcess)."""
    return code - (1 << 32) if code >= (1 << 31) else code


def _fallback(argv: list[str], reason: str) -> int:
    print(f"caddis_hidden_desktop: {reason}; running the command on the normal desktop", file=sys.stderr, flush=True)
    return _run_plain(argv)


def _run_plain(argv: list[str]) -> int:
    flags = {"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        proc = subprocess.Popen(argv, **flags)
    except FileNotFoundError:
        print(f"caddis_hidden_desktop: command not found: {argv[0]}", file=sys.stderr, flush=True)
        return EXIT_NOT_FOUND
    try:
        return proc.wait()
    except BaseException:
        proc.kill()
        raise


def _run_hidden(argv: list[str], started: list[bool]) -> int:  # pragma: no cover - Windows only
    """Sets started[0] once the command runs: from then on an error must never start it a second time."""
    import ctypes
    import ctypes.wintypes as wt
    import _winapi

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    u32 = ctypes.WinDLL("user32", use_last_error=True)

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR), ("lpTitle", wt.LPWSTR),
                    ("dwX", wt.DWORD), ("dwY", wt.DWORD), ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
                    ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD),
                    ("dwFlags", wt.DWORD), ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
                    ("lpReserved2", ctypes.c_void_p), ("hStdInput", wt.HANDLE), ("hStdOutput", wt.HANDLE),
                    ("hStdError", wt.HANDLE)]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE), ("dwProcessId", wt.DWORD),
                    ("dwThreadId", wt.DWORD)]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes",
                                                     "OtherBytes")]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wt.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wt.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wt.DWORD), ("SchedulingClass", wt.DWORD)]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION), ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    GENERIC_ALL = 0x10000000
    CREATE_SUSPENDED = 0x00000004
    STARTF_USESTDHANDLES = 0x00000100
    UOI_NAME = 2
    WAIT_OBJECT_0 = 0
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JobObjectExtendedLimitInformation = 9

    u32.GetProcessWindowStation.restype = wt.HANDLE
    u32.GetUserObjectInformationW.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD,
                                              ctypes.POINTER(wt.DWORD)]
    u32.CreateDesktopW.restype = wt.HANDLE
    u32.CreateDesktopW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, ctypes.c_void_p, wt.DWORD, wt.DWORD, ctypes.c_void_p]
    u32.CloseDesktop.argtypes = [wt.HANDLE]
    k32.CreateProcessW.argtypes = [wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wt.BOOL, wt.DWORD,
                                   ctypes.c_void_p, wt.LPCWSTR, ctypes.POINTER(STARTUPINFOW),
                                   ctypes.POINTER(PROCESS_INFORMATION)]
    k32.CreateJobObjectW.restype = wt.HANDLE
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
    k32.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
    k32.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
    k32.TerminateJobObject.argtypes = [wt.HANDLE, wt.UINT]
    k32.ResumeThread.argtypes = [wt.HANDLE]
    k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    k32.WaitForSingleObject.restype = wt.DWORD
    k32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
    k32.CloseHandle.argtypes = [wt.HANDLE]

    # The desktop must live in this process's window station (WinSta0 for a logged-on user, another one for a
    # service); a desktop path in a station the process cannot reach makes CreateProcessW fail.
    station = "WinSta0"
    buf = ctypes.create_unicode_buffer(256)
    needed = wt.DWORD()
    hsta = u32.GetProcessWindowStation()
    if hsta and u32.GetUserObjectInformationW(hsta, UOI_NAME, buf, ctypes.sizeof(buf), ctypes.byref(needed)):
        station = buf.value or station

    hdesk = u32.CreateDesktopW(DESKTOP_NAME, None, None, 0, GENERIC_ALL, None)  # opens it when it exists
    if not hdesk:
        return _fallback(argv, f"cannot create the hidden desktop (error {ctypes.get_last_error()})")

    me = _winapi.GetCurrentProcess()
    inherited: list[int] = []

    def inheritable(which: int) -> int:
        handle = _winapi.GetStdHandle(which)
        if not handle or handle == _winapi.INVALID_HANDLE_VALUE:
            return 0
        try:
            dup = _winapi.DuplicateHandle(me, handle, me, 0, True, _winapi.DUPLICATE_SAME_ACCESS)
        except OSError:
            return 0
        inherited.append(dup)
        return dup

    job = None
    pi = PROCESS_INFORMATION()
    try:
        si = STARTUPINFOW()
        si.cb = ctypes.sizeof(si)
        si.lpDesktop = f"{station}\\{DESKTOP_NAME}"
        si.dwFlags = STARTF_USESTDHANDLES
        si.hStdInput = inheritable(_winapi.STD_INPUT_HANDLE)
        si.hStdOutput = inheritable(_winapi.STD_OUTPUT_HANDLE)
        si.hStdError = inheritable(_winapi.STD_ERROR_HANDLE)
        cmdline = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
        if not k32.CreateProcessW(None, cmdline, None, None, True, CREATE_NO_WINDOW | CREATE_SUSPENDED, None, None,
                                  ctypes.byref(si), ctypes.byref(pi)):
            error = ctypes.get_last_error()
            if error in (2, 3):  # ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND
                print(f"caddis_hidden_desktop: command not found: {argv[0]}", file=sys.stderr, flush=True)
                return EXIT_NOT_FOUND
            return _fallback(argv, f"cannot start the command on the hidden desktop (error {error})")
        started[0] = True
        for dup in inherited:  # the child has its own copies now
            _winapi.CloseHandle(dup)
        inherited.clear()

        job = k32.CreateJobObjectW(None, None)
        if job:
            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not (k32.SetInformationJobObject(job, JobObjectExtendedLimitInformation, ctypes.byref(info),
                                                ctypes.sizeof(info))
                    and k32.AssignProcessToJobObject(job, pi.hProcess)):
                k32.CloseHandle(job)  # the caller's taskkill /T still reaches the child through its parent id
                job = None
        k32.ResumeThread(pi.hThread)
        try:
            # Short waits so Ctrl-C gets through. Loop only on a timeout: WAIT_FAILED (a bad handle) must not spin.
            while k32.WaitForSingleObject(pi.hProcess, 200) == 0x00000102:  # WAIT_TIMEOUT
                pass
        except KeyboardInterrupt:
            if job:
                k32.TerminateJobObject(job, EXIT_INTERRUPTED)
            else:
                _winapi.TerminateProcess(int(pi.hProcess), EXIT_INTERRUPTED)
            return EXIT_INTERRUPTED
        code = wt.DWORD()
        k32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
        return _signed(code.value)
    finally:
        for dup in inherited:
            _winapi.CloseHandle(dup)
        if pi.hThread:
            k32.CloseHandle(pi.hThread)
        if pi.hProcess:
            k32.CloseHandle(pi.hProcess)
        if job:
            k32.CloseHandle(job)  # KILL_ON_JOB_CLOSE: anything the command left running ends here
        u32.CloseDesktop(hdesk)


def run(argv: list[str]) -> int:
    if not argv:
        print("usage: caddis_hidden_desktop.py -- <program> [args...]", file=sys.stderr)
        return 2
    if os.name != "nt":
        return _run_plain(argv)
    started = [False]
    try:
        return _run_hidden(argv, started)
    except Exception as exc:
        if started[0]:  # it ran (and may have spent): never run it twice; the job already ended it
            raise
        return _fallback(argv, f"hidden desktop failed ({exc!r})")  # never fail a call because hiding failed


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--"]:
        args = args[1:]
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
