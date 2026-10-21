"""caddis_lanes — run one plan phase on an execution lane, re-check it, and write a result packet.

The pure core resolves configured lanes and builds confined child-process invocations.
"""
from __future__ import annotations

import importlib.util
import hashlib
from functools import lru_cache
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    import caddis_exit
    from caddis_heavy_slot import HeavySlotBusy, heavy_slot
except ModuleNotFoundError as exc:
    if exc.name not in {"caddis_exit", "caddis_heavy_slot"}:
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-harness" / "scripts"))
    import caddis_exit
    from caddis_heavy_slot import HeavySlotBusy, heavy_slot

import caddis_checkout_guard
import caddis_created
import caddis_routing
import caddis_redact
import caddis_spend
import caddis_worktree_root
import caddis_worktree_safety

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

EXIT_OK = caddis_exit.CLEAN
EXIT_FAIL = caddis_exit.BLOCKED
EXIT_USAGE = caddis_exit.ERROR
EXIT_CONFIG = caddis_exit.NOT_RUN
EXIT_ALL_OUT = caddis_exit.NOT_RUN
EXIT_NOT_RUN = caddis_exit.NOT_RUN
RESULT_OK = "OK"
RESULT_LANE_FAILED = "LANE-FAILED"
RESULT_STALLED = "LANE-STALLED"
RESULT_OUT_OF_BUDGET = "OUT-OF-BUDGET"
RESULT_CONFIG_ERROR = "CONFIG-ERROR"
RESULT_RESOURCE = "FAILED-RESOURCE"
MAX_ATTEMPTS = 2
DEFAULT_TIMEOUT_S = 3600
DEFAULT_IDLE_TIMEOUT_S = 900
IDLE_SAMPLE_S = 15
LANE_IDS = ("claude", "glm", "codex-sol", "codex-astra", "agy")
TASK_TYPES = ("backend", "hard", "ui", "tests", "docs")
# Where lane git WORKTREES live.
# New lane worktrees go to `<worktree root>/<repo>/caddis-lane-<hash>-<plan>-p<NN>-a<K>` (`lane_worktree_path`, which asks
# `caddis_worktree_root`: $CADDIS_WORKTREE_ROOT, else `<parent of the main checkout>/.worktrees`). Never %TEMP%: Windows
# cleanup (Storage Sense) can empty it and delete a lane worktree that holds unmerged work (owner decision, 20 Oct 2026).
# LANES_TMP is the OLD place, kept ONLY so lanes made before that decision keep working where they are: it is read to
# accept, finish and abandon an old record, and is never written to. Nothing else lives under it. Lane scratch that is not
# a worktree (packets, locks) is under `<repo>/.caddis/orchestrator/lane-runs/` (`run_dir`); it never used LANES_TMP.
LANES_TMP = Path(tempfile.gettempdir()) / "caddis-lanes"
LANE_WORKTREE_PREFIX = "caddis-lane-"
DEFAULT_MODELS = {
    "claude": "claude-opus-5",
    "glm": "glm-5.3[1m]",
    "codex-sol": "gpt-5.6-sol",
    "codex-astra": "gpt-6-astra",
    "agy": "gemini-4-argon",
}
AGY_FALLBACK_MODEL = "gemini-3.8-flash"  # used when `agy models` does not offer the default (other teams)
AGY_PROBE_TIMEOUT_S = 30
_AGY_MODELS_CACHE: str | None = None
DEFAULT_EFFORT = {
    "claude": "high",
    "glm": "medium",
    "codex-sol": "medium",
    "codex-astra": "high",
    "agy": "medium",
}
DEFAULT_CHAINS = {
    "backend": ("glm", "codex-sol", "claude"),
    "hard": ("claude", "codex-astra"),
    "ui": ("claude", "codex-astra"),
    "tests": ("codex-sol", "glm", "claude"),
    "docs": ("agy", "glm", "claude"),
}
BUDGET_PATTERNS: dict[str, tuple[str, ...]] = {
    # Claude Code 2.1.283 CLI bundle (limit-message builder and its prefix list).
    "claude": (
        r"You[’']ve hit your (?:session|weekly|Opus|Sonnet|Fable|usage credit) limit\b",
        r"You[’']ve hit your (?:channel's )?monthly spend limit\b",
        r"You[’']ve hit your team's shared budget\b",
        r"You[’']ve reached your Fable limit\b",
        r"You[’']re out of (?:usage credits|extra usage)\b",
        r"Your org is out of usage\b",
        r"Your usage allocation has been disabled by your admin\b",
        r"Your group's usage limit is set to \$0\b",
    ),
    # https://docs.z.ai/api-reference/api-code
    "glm": (
        r"API Error: 429.*\"type\"\s*:\s*\"(?:1113|1308|1309|1310|1316|1317)\"",
        r"Insufficient balance or no resource package",
        r"Usage limit reached for",
        r"Limit Exhausted",
    ),
    # https://raw.githubusercontent.com/openai/codex/main/codex-rs/protocol/src/error.rs
    "codex-sol": (
        r"You've hit your usage limit",
        r"Quota exceeded\. Check your plan",
        r"workspace is out of credits",
    ),
    # https://raw.githubusercontent.com/openai/codex/main/codex-rs/protocol/src/error.rs
    "codex-astra": (
        r"You've hit your usage limit",
        r"Quota exceeded\. Check your plan",
        r"workspace is out of credits",
    ),
    # caddis_spend refusing over the global EUR cap: the chain moves on, like a provider quota.
    "agy": (r"RESOURCE_EXHAUSTED.*quota", r"Individual quota reached", r"(?m)^caddis_spend: over cap",
            r"(?m)^caddis_spend: could not lock"),
}
CONFIG_PATTERNS: dict[str, tuple[str, ...]] = {
    "claude": (),
    "glm": (
        r"API Error: 400 \[1211\]",
        r"Unknown Model, please check the model code",
        r"no API key for provider",
    ),
    "codex-sol": (
        r"model is not supported when using Codex",
        r"Model metadata for .* not found",
    ),
    "codex-astra": (
        r"model is not supported when using Codex",
        r"Model metadata for .* not found",
    ),
    "agy": (r"invalid model selection", r"is not recognized as a known model",
            r"(?m)^caddis_spend: spend cap not configured",
            r"(?m)^caddis_spend: could not check the spend cap"),
}
LOAD_WORDING = (
    r"(?i)\bcpu\s+burner",
    r"(?i)\bburner",
    r"(?i)stress[- ]?test",
    r"(?i)load[- ]?test",
    r"(?i)every\s+(logical\s+)?(core|processor)",
    r"(?i)\bsaturat\w*",
    r"(?i)busy[- ]?(loop|spin|wait)",
    r"(?i)do\s+not\s+lower\s+(its|the)\s+priority",
)
ORCHESTRATOR_AGENTS_MD = """# .caddis/orchestrator/ — multi-lane orchestration artefacts

Created by caddis_lanes.py. Binding for every agent that writes here.

- Everything the multi-lane orchestration machinery writes in this repo lives in this folder.
- `lane-runs/<plan-stem>/` holds run packets (`phase-NN.attempt-K.json`) and phase locks. It is gitignored. Never commit it, and never edit a packet by hand.
- Evidence notes (recorded lane exit signals, live runs, dry runs, bake-off results) are markdown files directly in this folder, with caddis frontmatter (`type: analysis` or `type: review`). They are tracked.
- Never write orchestration notes to `.caddis/kb/`, the repo root or `.github/`.
- Never overwrite this file.
"""


class LaneConfigError(Exception):
    """A lane, chain, model or flag set that must not run."""


@dataclass
class LaneRun:
    returncode: int | None
    output: str
    timed_out: bool
    duration_s: float
    pid: int
    started: float
    stalled: bool = False
    idle_seconds: int = 0
    processes: list[dict] | None = None


@dataclass
class LaneProbe:
    mtime_ns: int
    cpu_seconds: float | None
    pids: frozenset[int] | None
    processes: list[dict]


@dataclass
class GateResult:
    cmd: str
    returncode: int
    passed: bool
    tail: str
    duration_s: float = 0.0


@dataclass
class ReviewResult:
    status: str
    returncode: int | None
    tail: str


@dataclass
class Worktree:
    path: Path
    branch: str
    base_sha: str


def _git_output(repo_root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise LaneConfigError(str(exc)) from exc
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise LaneConfigError(message or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def lane_worktree_path(repo_root: Path, plan_stem: str, phase: int, attempt: int) -> Path:
    """The path of a NEW lane worktree: `<worktree root>/<repo>/caddis-lane-<repo hash>-<plan>-p<NN>-a<K>`.
    Creates nothing. The hash keeps two repos with the same folder name apart."""
    repo_hash = hashlib.sha256(str(repo_root.resolve()).encode("utf-8")).hexdigest()[:8]
    short_name = f"{LANE_WORKTREE_PREFIX}{repo_hash}-{plan_stem}-p{phase:02d}-a{attempt}"
    try:
        return caddis_worktree_root.worktree_path(repo_root, short_name)
    except (ValueError, caddis_worktree_root.NotARepoError) as exc:
        raise LaneConfigError(str(exc)) from exc


def is_lane_worktree_path(repo_root: Path, path: Path) -> bool:
    """True for a folder that a lane may remove: an OLD one under LANES_TMP (any depth, as before), or a NEW one named
    `caddis-lane-*` directly inside this repo's folder under the current worktree root."""
    resolved = path.resolve()
    if LANES_TMP.resolve() in resolved.parents:
        return True
    if not resolved.name.startswith(LANE_WORKTREE_PREFIX):
        return False
    try:
        lane_dir = caddis_worktree_root.worktree_path(repo_root, resolved.name).parent
    except (ValueError, caddis_worktree_root.NotARepoError):
        return False
    return resolved.parent == lane_dir.resolve()


def create_phase_worktree(
    repo_root: Path,
    plan_stem: str,
    phase: int,
    attempt: int,
) -> Worktree:
    base_sha = _git_output(repo_root, "rev-parse", "HEAD")
    branch = f"lane/{plan_stem}/phase-{phase:02d}-a{attempt}"
    path = lane_worktree_path(repo_root, plan_stem, phase, attempt)
    if path.exists():
        raise LaneConfigError(f"worktree already exists: {path} — run abandon first")

    path.parent.mkdir(parents=True, exist_ok=True)
    _git_output(
        repo_root,
        "worktree",
        "add",
        "-b",
        branch,
        str(path),
        base_sha,
    )
    caddis_created.record(path, "worktree", f"lane {plan_stem} phase {phase:02d} attempt {attempt}", repo=repo_root,
                          branch=branch, by="lanes")
    print(f"[caddis-lanes] worktree: {path}", file=sys.stderr)
    return Worktree(path=path, branch=branch, base_sha=base_sha)


def remove_phase_worktree(
    repo_root: Path,
    wt: Worktree,
    delete_branch: bool,
) -> None:
    resolved = wt.path.resolve()
    if not is_lane_worktree_path(repo_root, resolved):
        raise LaneConfigError(f"refusing to remove {resolved}: not a lane worktree (a caddis-lane-* folder under the worktree root, or an old one under {LANES_TMP})")
    if delete_branch and not wt.branch.startswith("lane/"):
        raise LaneConfigError(f"refusing to delete non-lane branch: {wt.branch}")

    try:
        problem = caddis_worktree_safety.safe_remove_worktree(repo_root, resolved)
    except OSError as exc:
        raise LaneConfigError(f"worktree remove failed: {exc}") from exc
    if not problem and os.path.lexists(resolved):
        problem = f"worktree remove left {resolved} on disk"
    if problem:
        raise LaneConfigError(problem)
    caddis_created.record(resolved, "worktree", "", repo=repo_root, branch=wt.branch, status="removed", by="lanes")
    if delete_branch:
        _git_output(repo_root, "branch", "-D", "--", wt.branch)


def _venv_python(venv_root: Path) -> Path | None:
    for candidate in (
        venv_root / "Scripts" / "python.exe",
        venv_root / "bin" / "python",
    ):
        if candidate.exists():
            return candidate
    return None


def repo_python(repo_root: Path) -> str:
    python = _venv_python(repo_root / ".venv")
    return str(python) if python is not None else sys.executable


def gate_env(repo_root: Path, base: dict) -> dict:
    env = base.copy()
    venv = repo_root / ".venv"
    if not venv.exists():
        return env

    env["VIRTUAL_ENV"] = str(venv)
    for scripts_dir in (venv / "Scripts", venv / "bin"):
        if scripts_dir.exists():
            env["PATH"] = str(scripts_dir) + os.pathsep + env.get("PATH", "")
            break
    return env


def freeze_snapshot(python: str) -> str | None:
    try:
        result = subprocess.run(
            [python, "-m", "pip", "freeze", "--all"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return None
    return result.stdout


def shared_venv_pythons(repo_root: Path, cfg: dict) -> list[str]:
    pythons = []
    shared_venvs = cfg.get("shared_venvs", [])
    if not isinstance(shared_venvs, list):
        return pythons

    for configured_path in shared_venvs:
        if not isinstance(configured_path, str):
            continue
        venv = Path(configured_path)
        if not venv.is_absolute():
            venv = repo_root / venv
        python = _venv_python(venv)
        if python is not None:
            pythons.append(str(python))
    return pythons


def governor_path() -> Path:
    shipped = Path(__file__).with_name("caddis_governor.py")
    if shipped.exists():
        return shipped
    source = (
        Path(__file__).resolve().parents[1]
        / "claude-harness"
        / "scripts"
        / "caddis_governor.py"
    )
    if source.exists():
        return source
    raise LaneConfigError(
        "caddis_governor.py not found; refusing to run a lane without resource limits"
    )


def governed_argv(argv: list[str], job_name: str | None = None) -> list[str]:
    return [
        sys.executable,
        str(governor_path()),
        "exec",
        "--scope",
        "lane",
        *(["--job-name", job_name] if job_name else []),
        "--",
        *argv,
    ]


def kill_governed(proc: subprocess.Popen) -> None:
    if sys.platform == "win32":
        proc.kill()
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except ProcessLookupError:
        pass


def process_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == 259
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _acquisition_guard(lock: Path) -> int:
    guard = lock.with_name(lock.name + ".guard")
    fd = os.open(guard, os.O_CREAT | os.O_RDWR)
    try:
        if sys.platform == "win32":
            import msvcrt

            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _release_acquisition_guard(fd: int) -> None:
    try:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def acquire_lock(lock: Path) -> None:
    lock.parent.mkdir(parents=True, exist_ok=True)
    guard_fd = _acquisition_guard(lock)
    try:
        while True:
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    content = lock.read_text(encoding="utf-8").strip()
                except FileNotFoundError:
                    continue

                try:
                    pid = int(content)
                except ValueError:
                    pid = 0
                if pid > 0 and process_alive(pid):
                    raise LaneConfigError(
                        f"phase is locked by {lock} (pid {content}); "
                        "another worker holds this phase"
                    ) from None

                lock.unlink(missing_ok=True)
                continue

            try:
                os.write(fd, str(os.getpid()).encode("ascii"))
                os.fsync(fd)
            finally:
                os.close(fd)
            return
    finally:
        _release_acquisition_guard(guard_fd)


def release_lock(lock: Path) -> None:
    if not lock.parent.exists():
        return
    guard_fd = _acquisition_guard(lock)
    try:
        lock.unlink(missing_ok=True)
    finally:
        _release_acquisition_guard(guard_fd)


def newest_file_mtime(cwd: Path) -> int:
    newest = 0
    files = 0
    pending = [cwd]
    while pending and files < 20000:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name == ".git" or (
                        directory == cwd / ".caddis" and entry.name == "orchestrator"
                    ):
                        continue
                    pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    files += 1
                    newest = max(newest, entry.stat(follow_symlinks=False).st_mtime_ns)
                    if files >= 20000:
                        break
    return newest


def default_probe(pid: int, cwd: Path, job_name: str | None) -> LaneProbe:
    mtime = newest_file_mtime(cwd)
    if sys.platform == "win32":
        governor = _governor_probe_module()
        cpu, pids = governor.query_named_job(job_name)
        names = _windows_process_names(pids)
    elif sys.platform.startswith("linux"):
        ticks = os.sysconf("SC_CLK_TCK")
        members = []
        for path in Path("/proc").iterdir():
            if not path.name.isdecimal():
                continue
            try:
                stat = (path / "stat").read_text(encoding="utf-8")
                fields = stat[stat.rfind(")") + 2 :].split()
                if int(fields[3]) == pid:
                    members.append((int(path.name), stat[stat.find("(") + 1 : stat.rfind(")")],
                                    (int(fields[11]) + int(fields[12])) / ticks))
            except (OSError, ValueError, IndexError):
                continue
        pids = [item[0] for item in members]
        cpu = sum(item[2] for item in members)
        names = {item[0]: item[1] for item in members}
    else:
        return LaneProbe(mtime, None, None, [])
    return LaneProbe(mtime, cpu, frozenset(pids),
                     [{"pid": member, "name": names.get(member, "unknown")} for member in sorted(pids)])


@lru_cache(maxsize=1)
def _governor_probe_module():
    return _load_file_module("_caddis_governor_probe", governor_path())


def _windows_process_names(pids: list[int]) -> dict[int, str]:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                    wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    names = {}
    for pid in pids:
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            continue
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buffer))
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                names[pid] = Path(buffer.value).name
        finally:
            kernel32.CloseHandle(handle)
    return names


def _refused_run(returncode: int, message: str) -> LaneRun:
    """A lane that never started: the spend cap refused it. pid 0, no time spent."""
    return LaneRun(returncode=returncode, output=message + "\n", timed_out=False, duration_s=0.0,
                   pid=0, started=time.time())


def run_lane(
    argv: list[str],
    cwd: Path,
    prompt: str,
    stdin_prompt: bool,
    timeout_s: int,
    env: dict,
    idle_timeout_s: int = DEFAULT_IDLE_TIMEOUT_S,
    clock=time.monotonic,
    sleep=time.sleep,
    probe=default_probe,
    spend_caller: str = "lane",
) -> LaneRun:
    # Every agy launch is booked against the global spend cap first (caddis_spend). ci_watch reaches
    # agy through here too, so each call is booked exactly once. Any spend problem refuses the lane
    # (fail closed) and never crashes the unattended chain.
    spend_id = None
    if Path(argv[0]).stem.lower() == "agy":
        spend_home = Path.home()
        try:
            spend_id = caddis_spend.reserve(spend_home, spend_caller, datetime.now(timezone.utc))
        except caddis_spend.NotConfigured:
            return _refused_run(3, caddis_spend.NOT_CONFIGURED_MESSAGE)
        except TimeoutError as exc:
            return _refused_run(3, str(exc))
        except Exception as exc:  # an unreadable log or file error: refuse, never crash
            return _refused_run(3, f"caddis_spend: could not check the spend cap: {exc!r}")
        if spend_id is None:
            return _refused_run(1, "caddis_spend: over cap: agy refused ("
                                + caddis_spend.status_line(spend_home, datetime.now(timezone.utc)) + ")")
        argv = caddis_spend.hidden_argv(argv, env)  # agy's tool consoles open on a hidden desktop, not on screen
    job_name = f"Local\\caddis-governor-{os.getpid()}-{secrets.token_hex(8)}" if sys.platform == "win32" else None
    full = governed_argv(argv, job_name)
    if not stdin_prompt:
        full.append(prompt)
    validate_codex_argv(full)

    started = time.time()
    monotonic_started = clock()
    popen_options = {}
    if sys.platform != "win32":
        popen_options["start_new_session"] = True
    try:
        proc = subprocess.Popen(
            full,
            cwd=cwd,
            stdin=subprocess.PIPE if stdin_prompt else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            **popen_options,
        )
    except OSError:
        if spend_id is not None:  # nothing started, nothing was spent
            try:
                caddis_spend.settle(spend_home, spend_id, (0, 0), datetime.now(timezone.utc))
            except Exception:
                pass
        raise
    timed_out = stalled = False
    idle_seconds = 0
    processes = None
    chunks: list[bytes] = []
    byte_count = [0]

    def read_output() -> None:
        assert proc.stdout is not None
        try:
            while chunk := proc.stdout.read1(65536):
                chunks.append(chunk)
                byte_count[0] += len(chunk)
        except OSError:
            pass  # the pipe can close when the governed process is killed

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    try:
        if stdin_prompt:
            assert proc.stdin is not None
            stdin_pipe = proc.stdin

            def write_prompt() -> None:
                # On its own thread: a child that never reads its stdin would block this write for
                # ever, and the wall-clock and idle limits below must still apply to it.
                try:
                    stdin_pipe.write(prompt.encode("utf-8"))
                except (BrokenPipeError, OSError, ValueError):
                    pass
                finally:
                    try:
                        stdin_pipe.close()
                    except (BrokenPipeError, OSError, ValueError):
                        pass

            threading.Thread(target=write_prompt, daemon=True).start()
        previous = None
        previous_bytes = byte_count[0]
        last_active = monotonic_started
        last_sample = monotonic_started
        next_sample = monotonic_started + IDLE_SAMPLE_S
        if idle_timeout_s:
            try:
                previous = probe(proc.pid, cwd, job_name)
            except Exception:
                pass
        while proc.poll() is None:
            now = clock()
            if now - monotonic_started >= timeout_s:
                timed_out = True
                kill_governed(proc)
                break
            until_sample = max(next_sample - now, 0) if idle_timeout_s else 0.25
            sleep(min(0.25, until_sample, timeout_s - (now - monotonic_started)))
            if proc.poll() is not None or not idle_timeout_s:
                continue
            now = clock()
            if now < next_sample:
                continue
            next_sample = now + IDLE_SAMPLE_S
            try:
                current = probe(proc.pid, cwd, job_name)
            except Exception:
                current = None
            if current is None or previous is None:
                last_active = now  # unknown activity must not cause a false stall
            else:
                elapsed = max(now - last_sample, 0)
                active = (byte_count[0] != previous_bytes or
                          current.mtime_ns != previous.mtime_ns or
                          current.pids != previous.pids or
                          (current.cpu_seconds is not None and previous.cpu_seconds is not None and
                           current.cpu_seconds - previous.cpu_seconds > elapsed / 60))
                if active:
                    last_active = now
            previous, previous_bytes, last_sample = current, byte_count[0], now
            if now - last_active >= idle_timeout_s and now - monotonic_started < timeout_s:
                stalled = True
                idle_seconds = int(now - last_active)
                processes = current.processes
                kill_governed(proc)
                break
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            kill_governed(proc)
        reader.join(timeout=30)
    except BaseException:
        kill_governed(proc)
        raise

    # Mask key values before any caller sees the lane's output (printed tails, ci-watch reports); packets are
    # masked again in write_packet, which also covers the gate and review tails.
    output = caddis_redact.redact(b"".join(chunks).decode("utf-8", errors="replace"),
                                  caddis_redact.load_secrets(Path.home()))
    if spend_id is not None:
        # Tokens only from JSON mode: in text mode the model's own lines could pose as a usage document.
        if proc.returncode == 127:
            counts = (0, 0)  # the governor found no agy binary: nothing ran, nothing was spent
        else:
            counts = caddis_spend.tokens_from_output(output) if caddis_spend.json_mode(argv) else None
        try:
            caddis_spend.settle(spend_home, spend_id, counts, datetime.now(timezone.utc),
                                duration_s=clock() - monotonic_started)
        except Exception as exc:  # the pending reserve keeps counting; never lose the lane's result
            output += f"\ncaddis_spend: could not settle {spend_id}: {exc!r}\n"
    return LaneRun(
        returncode=proc.returncode,
        output=output,
        timed_out=timed_out,
        duration_s=clock() - monotonic_started,
        pid=proc.pid,
        started=started,
        stalled=stalled,
        idle_seconds=idle_seconds,
        processes=processes,
    )



# ci_watch compares its `run_agy` argument with this by identity (see the idle watchdog note there).
_LANE_RUNNER = run_lane

def gate_commands(repo_root: Path, worktree: Path, cfg: dict) -> list[list[str]]:
    configured = cfg.get("gate_cmds")
    if isinstance(configured, list) and configured:
        return [shlex.split(command) for command in configured]

    inventory_path = Path(__file__).resolve().parent / "caddis_inventory.py"
    spec = importlib.util.spec_from_file_location(
        "_caddis_inventory_for_lanes", inventory_path
    )
    if spec is None or spec.loader is None:
        raise LaneConfigError(f"could not load {inventory_path}")
    inventory = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = inventory
    spec.loader.exec_module(inventory)
    command = list(inventory._test_command(worktree))
    if command and command[0] == sys.executable:
        command[0] = repo_python(repo_root)
    return [command]


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stdout or "") + (result.stderr or "")


def _as_text(output: str | bytes | None) -> str:
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output or ""


def run_gates(
    cmds: list[list[str]],
    cwd: Path,
    env: dict,
    timeout_s: int = 1800,
) -> list[GateResult]:
    try:
        with heavy_slot("gates"):
            results = []
            for command in cmds:
                gate_started = time.monotonic()
                try:
                    completed = subprocess.run(
                        governed_argv(command),
                        cwd=cwd,
                        env=env,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=timeout_s,
                    )
                except subprocess.TimeoutExpired:
                    results.append(
                        GateResult(
                            cmd=shlex.join(command),
                            returncode=-1,
                            passed=False,
                            tail=f"timed out after {timeout_s}s",
                            duration_s=time.monotonic() - gate_started,
                        )
                    )
                    continue

                output = _combined_output(completed)
                passed = completed.returncode == 0 or (
                    completed.returncode == 5 and "pytest" in " ".join(command)
                )
                results.append(
                    GateResult(
                        cmd=shlex.join(command),
                        returncode=completed.returncode,
                        passed=passed,
                        tail=output[-2000:],
                        duration_s=time.monotonic() - gate_started,
                    )
                )
            return results
    except HeavySlotBusy as exc:
        msg = f"heavy-run slot busy: {exc.holder}" if exc.holder else "heavy-run slot busy"
        if cmds:
            return [
                GateResult(
                    cmd=shlex.join(command),
                    returncode=EXIT_NOT_RUN,
                    passed=False,
                    tail=msg,
                )
                for command in cmds
            ]
        return [
            GateResult(
                cmd="",
                returncode=EXIT_NOT_RUN,
                passed=False,
                tail=msg,
            )
        ]


def oss_review_path() -> Path | None:
    sibling = Path(__file__).with_name("oss_review.py")
    if sibling.exists():
        return sibling
    source = Path(__file__).resolve().parents[1] / ".github" / "tools" / "oss_review.py"
    return source if source.exists() else None


def run_review(worktree: Path, env: dict, timeout_s: int = 900) -> ReviewResult:
    fake_review = os.environ.get("CADDIS_REVIEW_FAKE")
    if fake_review:
        return ReviewResult(fake_review, 0 if fake_review == "CLEAN" else 1, f"fake review: {fake_review}")

    path = oss_review_path()
    if path is None:
        return ReviewResult("MISSING", None, "oss_review.py not found")

    try:
        completed = subprocess.run(
            [sys.executable, str(path), "--cwd", str(worktree)],
            cwd=worktree,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        captured = _as_text(exc.stdout) + _as_text(exc.stderr)
        tail = (captured + f"\ntimed out after {timeout_s}s").lstrip("\n")[-3000:]
        return ReviewResult("MISSING", None, tail)
    except OSError as exc:
        return ReviewResult("MISSING", None, str(exc)[-3000:])

    status = {0: "CLEAN", 1: "BLOCKING"}.get(completed.returncode, "MISSING")
    return ReviewResult(status, completed.returncode, _combined_output(completed)[-3000:])


def changed_files(worktree: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(worktree), "status", "--porcelain=v1", "--untracked-files=all"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise LaneConfigError(message or "git status failed")

    paths = []
    for line in result.stdout.splitlines():
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path)
    return sorted(paths)


def worktree_digest(worktree: Path, files: list[str]) -> str:
    """Hash each changed path's mode and content (or link target, or a marker), in the given order.

    `files` is the sorted list from changed_files(); accept can then prove nothing changed since check.
    """
    digest = hashlib.sha256()
    for name in files:
        path = worktree / name
        digest.update(name.encode("utf-8") + b"\0")
        try:
            info = path.lstat()
            digest.update(f"{info.st_mode:o}\0".encode("ascii"))
            if path.is_symlink():
                digest.update(b"link:" + os.fsencode(os.readlink(path)))
            elif path.is_file():
                digest.update(path.read_bytes())
            else:
                digest.update(b"<not-a-file>")
        except FileNotFoundError:
            digest.update(b"<absent>")
        except OSError as exc:
            digest.update(f"<unreadable:{exc.errno}>".encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _host_guard_module():
    candidates = (
        Path(__file__).with_name("caddis_host_guard.py"),
        Path(__file__).resolve().parents[1]
        / "claude-harness"
        / "scripts"
        / "caddis_host_guard.py",
    )
    path = next((candidate for candidate in candidates if candidate.exists()), None)
    if path is None:
        return None

    spec = importlib.util.spec_from_file_location("_caddis_host_guard_for_lanes", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def guard_killed_since(
    started: float,
    pids: set[int],
    log: Path | None = None,
) -> bool:
    host_guard = _host_guard_module()
    if host_guard is None:
        return False
    log_path = log or host_guard.guard_log_path()
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False

    for line in lines:
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        killed = record.get("killed", [])
        record_pids = {record.get("pid")}
        if isinstance(killed, list):
            record_pids.update(killed)
        if (
            # Phase 9 names this event "kill"; the current guard records it as "end".
            record.get("kind") in ("kill", "end")
            and isinstance(record.get("ts"), (int, float))
            and record["ts"] >= started
            and bool(pids.intersection(record_pids))
        ):
            return True
    return False


def packet_created() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def orchestrator_dir(repo_root: Path) -> Path:
    directory = repo_root / ".caddis" / "orchestrator"
    directory.mkdir(parents=True, exist_ok=True)
    for path, content in (
        (directory / "AGENTS.md", ORCHESTRATOR_AGENTS_MD),
        (directory / ".gitignore", "lane-runs/\n"),
    ):
        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
        except FileExistsError:
            pass
    return directory


def run_dir(repo_root: Path, plan_stem: str) -> Path:
    return orchestrator_dir(repo_root) / "lane-runs" / plan_stem


def write_packet(path: Path, packet: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    # Every string in the packet (gate and review tails come from model-written code) is masked here,
    # the one place all packets pass through.
    safe = caddis_redact.redact_obj(packet, caddis_redact.load_secrets(Path.home()))
    temporary.write_text(
        json.dumps(safe, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path


def load_lanes_config(repo_root: Path) -> dict:
    config_path = repo_root / ".caddis" / "config.toml"
    if not config_path.exists():
        return {}
    try:
        import tomllib
    except ImportError as exc:
        raise LaneConfigError(
            f"cannot parse {config_path}: Python 3.11 or later is required"
        ) from exc
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LaneConfigError(f"cannot parse {config_path}: {exc}") from exc

    lanes = data.get("lanes", {})
    if not isinstance(lanes, dict):
        raise LaneConfigError(f"[lanes] in {config_path} is not a table")
    idle_timeout(lanes)
    return lanes


def idle_timeout(cfg: dict, override: int | None = None) -> int:
    value = cfg.get("idle_timeout_s", DEFAULT_IDLE_TIMEOUT_S) if override is None else override
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LaneConfigError(f"invalid [lanes] idle_timeout_s: {value!r}")
    return value


def _probe_agy_models() -> str:
    """The text of `agy models` (one model id per line), or "" when agy is missing, fails or prints nothing. Only a
    non-empty listing is cached for the process: a failed probe is not cached, so a later call asks agy again."""
    global _AGY_MODELS_CACHE
    if _AGY_MODELS_CACHE:
        return _AGY_MODELS_CACHE
    agy = shutil.which("agy")
    if not agy:
        return ""
    try:
        proc = subprocess.run(
            caddis_spend.hidden_argv([agy, "models"]), capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=AGY_PROBE_TIMEOUT_S, check=False, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    listing = (proc.stdout or "") if proc.returncode == 0 else ""
    if listing.strip():
        _AGY_MODELS_CACHE = listing
    return listing


# The agy default is used at three effort levels: ci-watch uses -low, lanes -medium, review -high. Keep it only
# when `agy models` offers all three exact ids.
AGY_DEFAULT_EFFORT_IDS = ("low", "medium", "high")
_AGY_FALLBACK_NOTED = False


def _agy_default_model(probe=None) -> str:
    """The configured default agy model when `agy models` lists every `<default>-low`, `-medium` and `-high` id
    exactly, else AGY_FALLBACK_MODEL. The fallback note goes to stderr once per process."""
    global _AGY_FALLBACK_NOTED
    probe = probe or _probe_agy_models
    default = DEFAULT_MODELS["agy"]
    try:
        listing = probe()
    except (OSError, subprocess.SubprocessError):
        listing = ""
    offered = {line.split()[0] for line in (listing or "").splitlines() if line.split()}  # id, then a name
    if all(f"{default}-{level}" in offered for level in AGY_DEFAULT_EFFORT_IDS):
        return default
    if not _AGY_FALLBACK_NOTED:
        _AGY_FALLBACK_NOTED = True
        print(f"[caddis-lanes] agy: {default} not offered here; using {AGY_FALLBACK_MODEL}", file=sys.stderr)
    return AGY_FALLBACK_MODEL


def resolve_models(cfg: dict, *, probe=None) -> dict[str, str]:
    models = DEFAULT_MODELS.copy()
    configured = cfg.get("models", {})
    for key, value in configured.items():
        if key not in LANE_IDS:
            raise LaneConfigError(f"unknown lane in [lanes.models]: {key}")
        if not isinstance(value, str) or not value:
            raise LaneConfigError(f"empty model id for lane {key}")
        models[key] = value
    if "agy" not in configured:  # a config pin wins and is never probed
        models["agy"] = _agy_default_model(probe)
    return models


def resolve_chain(task_type: str, cfg: dict, first_lane: str | None = None) -> tuple[str, ...]:
    if task_type not in TASK_TYPES:
        raise LaneConfigError(f"unknown task type: {task_type}")

    configured_chain = cfg.get("chains", {}).get(task_type)
    chain = configured_chain if isinstance(configured_chain, list) else DEFAULT_CHAINS[task_type]
    if not chain:
        raise LaneConfigError(f"empty chain for {task_type}")
    for lane in chain:
        if lane not in LANE_IDS:
            raise LaneConfigError(f"unknown lane in chain {task_type}: {lane}")

    if first_lane is None:
        return tuple(chain)
    if first_lane not in LANE_IDS:
        raise LaneConfigError(f"unknown first lane: {first_lane}")
    return (first_lane, *(lane for lane in chain if lane != first_lane))


def build_argv(
    lane: str,
    model: str,
    effort: str,
    worktree: Path,
    which=shutil.which,
) -> list[str]:
    fake = os.environ.get("CADDIS_LANES_FAKE")
    if fake:
        return [sys.executable, fake, lane]
    if lane == "claude":
        raise LaneConfigError(
            "the claude lane is run by the orchestrating session, not by this script"
        )

    if lane == "glm":
        tool = "claude-glm"
    elif lane in ("codex-sol", "codex-astra"):
        tool = "codex"
    elif lane == "agy":
        tool = "agy"
    else:
        raise LaneConfigError(f"unknown lane: {lane}")

    binary = which(tool)
    if binary is None:
        raise LaneConfigError(f"{tool} not found on PATH")

    if lane == "glm":
        return [binary, "-p", "--permission-mode", "acceptEdits"]
    if lane in ("codex-sol", "codex-astra"):
        return [
            binary,
            "exec",
            "-m",
            model,
            "-c",
            f"model_reasoning_effort={effort}",
            "-s",
            "workspace-write",
            "-C",
            str(worktree),
            "--skip-git-repo-check",
            "-",
        ]
    return [
        binary,
        "--model",
        f"{model}-{effort}",
        "--mode",
        "accept-edits",
        "--dangerously-skip-permissions",
        "--add-dir",
        str(worktree),
        "--print-timeout",
        "60m",
        "--output-format",
        "json",
        "-p",
    ]


def prompt_via_stdin(lane: str) -> bool:
    if os.environ.get("CADDIS_LANES_FAKE"):
        return True
    return lane in ("glm", "codex-sol", "codex-astra")


def validate_codex_argv(argv: list[str]) -> None:
    codex_index = next(
        (
            index
            for index, value in enumerate(argv[:-1])
            if Path(value).stem.lower() in ("codex",)
            and argv[index + 1] == "exec"
        ),
        None,
    )
    if codex_index is None:
        return
    codex_argv = argv[codex_index:]
    if "danger-full-access" in codex_argv:
        raise LaneConfigError("codex must run with -s workspace-write or -s read-only")

    try:
        sandbox = codex_argv[codex_argv.index("-s") + 1]
    except (ValueError, IndexError):
        sandbox = None
    if sandbox not in ("workspace-write", "read-only"):
        raise LaneConfigError("codex must run with -s workspace-write or -s read-only")

    if sandbox == "workspace-write":
        try:
            worktree = codex_argv[codex_argv.index("-C") + 1]
        except (ValueError, IndexError):
            worktree = ""
        if not worktree:
            raise LaneConfigError(
                "codex workspace-write must be confined with -C <worktree>"
            )


# Robustness #4: a lane agent can be prompt-injected through a plan or a diff, so it gets no publish token and no
# credential prompt, and cannot switch the guard off. The same list as caddis_roadmap_run.SESSION_SECRET_VARS. The
# gh keyring login stays on the machine; the guard denies push, merge and publish when CADDIS_HEADLESS=1.
LANE_SECRET_VARS = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "NPM_TOKEN", "NODE_AUTH_TOKEN",
                    "CADDIS_ALLOW_PUBLISH", "CADDIS_GUARD_DISABLED")
LANE_NO_PROMPT_ENV = {"GH_PROMPT_DISABLED": "1", "GIT_TERMINAL_PROMPT": "0"}


def child_env(base: dict, lane: str, model: str) -> dict:
    env = base.copy()
    for name in LANE_SECRET_VARS:
        env.pop(name, None)
    env.update(LANE_NO_PROMPT_ENV)
    try:
        env = caddis_spend.bump_headless_depth(env)  # sets CADDIS_HEADLESS=1 and the depth (robustness #19)
    except caddis_spend.HeadlessDepthExceeded as exc:
        raise LaneConfigError(str(exc)) from exc
    if lane == "glm":
        env["OSS_MODEL"] = model
    return env


def classify_exit(
    lane: str,
    returncode: int | None,
    output: str,
    timed_out: bool,
    guard_killed: bool = False,
    stalled: bool = False,
) -> str:
    if guard_killed:
        return RESULT_RESOURCE
    if stalled:
        return RESULT_STALLED
    if timed_out:
        return RESULT_LANE_FAILED
    if any(re.search(pattern, output, re.I) for pattern in CONFIG_PATTERNS[lane]):
        return RESULT_CONFIG_ERROR
    if any(re.search(pattern, output, re.I) for pattern in BUDGET_PATTERNS[lane]):
        return RESULT_OUT_OF_BUDGET
    if returncode == 3 and lane == "glm":
        return RESULT_CONFIG_ERROR
    if returncode == 127:
        return RESULT_CONFIG_ERROR
    if returncode == 0:
        return RESULT_OK
    return RESULT_LANE_FAILED


CLAUDE_FAMILY = frozenset({"opus", "sonnet", "claude"})


def next_lane(
    role: str,
    after: str,
    *,
    home: Path,
    repo: Path,
    which=shutil.which,
) -> str | None:
    """Find the next available model, sharing one budget across Claude models."""
    routing = caddis_routing.resolve(home, repo, which=which)
    chain = routing[role]
    if role != "coding" and after not in chain and after not in CLAUDE_FAMILY:
        # `after` came from the coding fallback (a Claude model ran out first): carry on down
        # the coding chain, and never hand the exhausted Claude budget back.
        coding = routing["coding"]
        if after not in coding:
            return None
        rest = [model for model in coding[coding.index(after) + 1:] if model not in CLAUDE_FAMILY]
        return rest[0] if rest else None
    candidates = chain[chain.index(after) + 1:] if after in chain else chain
    if after in CLAUDE_FAMILY:
        candidates = [model for model in candidates if model not in CLAUDE_FAMILY]
        if not candidates and role != "coding":
            # Fall to coding models this role has not already tried. The coding chain ran before
            # its own Claude fallback, and a role that lists agy or codex ran them before Claude;
            # restarting either would loop.
            candidates = [
                model for model in routing["coding"]
                if model not in CLAUDE_FAMILY and model not in chain
            ]
    return candidates[0] if candidates else None


# Why gh waits and agy only summarises (measured 2026-10-15): agy `--print` moves a long command
# (`gh pr checks --watch`) into its own background task, reports "root agent idle", then ends that task
# on exit and returns no report. agy also does not read stdin in text mode, so any data it needs must
# sit inside the prompt. So `gh` always does the waiting, and agy gets one short, tool-free job after a
# failure: read the failed log (placed in the prompt) and name the failing job and first error.
_CI_SUMMARY_MAX_CHARS = 300
_CI_LOG_TAIL_LINES = 80
_CI_LOG_TAIL_CHARS = 8000
_CI_AGY_TIMEOUT_S = 300
_CI_GH_SHORT_TIMEOUT_S = 60
_RUN_ID_IN_URL = re.compile(r"/actions/runs/(\d+)")


def _print_ci_watch(result: str, checks: str, merge_state: str, failing: str, watcher: str,
                    summary: str | None = None, head: str = "n/a") -> None:
    print(f"RESULT: {result}")
    print(f"CHECKS: {checks}")
    print(f"MERGE_STATE: {merge_state}")
    print(f"HEAD: {head}")
    print(f"FAILING: {failing}")
    print(f"WATCHER: {watcher}")
    print(f"SUMMARY: {summary or 'none'}")


_ROLLUP_GREEN = {"SUCCESS", "SKIPPED", "NEUTRAL"}
_STATUS_CONTEXT_DONE = {"SUCCESS", "FAILURE", "ERROR"}  # a commit status' final states; PENDING/EXPECTED are not


def _rollup_verdict(rollup) -> tuple[int, list[str], list[str]] | None:
    """(green count, failed names, unfinished names) from `statusCheckRollup` of the PR's head commit.

    A check run is green only when COMPLETED with SUCCESS, SKIPPED or NEUTRAL; a status context only on SUCCESS.
    None when the rollup is missing, empty or not a list: nothing proves the head is green.
    """
    if not isinstance(rollup, list) or not rollup:
        return None
    green, failed, unfinished = 0, [], []
    for item in rollup:
        if not isinstance(item, dict):
            return None
        name = str(item.get("name") or item.get("context") or "?")
        kind = item.get("__typename") or ("StatusContext" if "context" in item and "status" not in item
                                          else "CheckRun")
        if kind == "StatusContext":  # a commit status
            state = str(item.get("state") or "").upper()
            outcome = state if state in _STATUS_CONTEXT_DONE else ""
        else:  # a check run
            done = str(item.get("status") or "").upper() == "COMPLETED"
            outcome = str(item.get("conclusion") or "").upper() if done else ""
        if outcome in _ROLLUP_GREEN:
            green += 1
        elif outcome:  # FAILURE, CANCELLED, TIMED_OUT, ... and any final state not known here: never a pass
            failed.append(name)
        else:
            unfinished.append(name)
    return green, failed, unfinished


def _parse_pr_checks(output: str) -> list[tuple[str, str, str]]:
    """Read `gh pr checks` rows (tab-separated: name, state, elapsed, url) as (name, state, url).

    `--watch` may print the table more than once; a later row for the same name replaces an earlier one.
    """
    rows: dict[str, tuple[str, str]] = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 2 or not parts[0].strip():
            continue
        url = parts[3].strip() if len(parts) > 3 else ""
        rows[parts[0].strip()] = (parts[1].strip().lower(), url)
    return [(name, state, url) for name, (state, url) in rows.items()]


def _ci_gh_run(run_gh, argv: list[str], repo: Path, timeout_s: float):
    """One short gh call. Returns the CompletedProcess, or None on any start or time-out problem."""
    try:
        return run_gh(argv, cwd=repo, capture_output=True, text=True,
                      encoding="utf-8", errors="replace", timeout=timeout_s)
    except (subprocess.TimeoutExpired, OSError):
        return None


def _ci_failure_summary(
    log_tail: str, *, agy_path: str, repo: Path, remaining_s: float, run_agy,
) -> str | None:
    """Ask agy for a one-line failure summary. The log is inside the prompt. None on any problem."""
    masked_values = caddis_redact.load_secrets(Path.home())
    prompt = (
        "Do not run any tools. Read this CI failure log and reply with one line: the failing job "
        "and the first failing test or error line. LOG:\n" + caddis_redact.redact(log_tail, masked_values)
    )
    try:
        model = resolve_models(load_lanes_config(repo))["agy"]
        effort = "low"  # a one-line summary needs no deep thinking
        argv = [
            # The log is untrusted (a PR can write anything into it), so this call can use no tools:
            # plan mode and the sandbox, and never --dangerously-skip-permissions. Checked 2026-10-15:
            # with these flags agy wrote a plan and did not run the command a prompt asked for.
            agy_path, "--model", f"{model}-{effort}", "--mode", "plan", "--sandbox",
            "--output-format", "json", "--print",
        ]
        # The idle watchdog is off for ci-watch (as before); the wall-clock limit still applies.
        runner = ((lambda *a: run_lane(*a, idle_timeout_s=0, spend_caller="ci-watch"))
                  if run_agy is _LANE_RUNNER else run_agy)
        run = runner(argv, repo, prompt, False, min(_CI_AGY_TIMEOUT_S, remaining_s),
                     child_env(os.environ, "agy", model))
    except LaneConfigError as exc:
        print(f"[caddis-lanes] ci-watch: agy summary skipped ({exc})", file=sys.stderr)
        return None
    except OSError as exc:
        print(f"[caddis-lanes] ci-watch: agy could not start ({exc}); no summary", file=sys.stderr)
        return None
    if run.timed_out:
        print("[caddis-lanes] ci-watch: agy summary timed out; no summary", file=sys.stderr)
        return None
    if run.returncode != 0:
        print(f"[caddis-lanes] ci-watch: agy exited {run.returncode}; no summary", file=sys.stderr)
        return None
    reply = caddis_redact.redact(caddis_spend.result_text(run.output), masked_values)
    for line in reply.splitlines():
        line = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", line).strip()
        if line:
            return line[:_CI_SUMMARY_MAX_CHARS]
    print("[caddis-lanes] ci-watch: agy gave an empty reply; no summary", file=sys.stderr)
    return None


def _ci_summary_from_log(gh_path, run_id, repo_args, repo, run_gh, remaining, agy_path, run_agy) -> str | None:
    """Fetch the failed log, then ask agy for one line. None (with a stderr note) on any problem."""
    if run_id is None:
        print("[caddis-lanes] ci-watch: no run id for the failed check; no summary", file=sys.stderr)
        return None
    left = remaining()
    if left <= 0:
        print("[caddis-lanes] ci-watch: time budget used up; no summary", file=sys.stderr)
        return None
    log = _ci_gh_run(
        run_gh, [gh_path, "run", "view", run_id, "--log-failed", *repo_args],
        repo, min(_CI_GH_SHORT_TIMEOUT_S, left),
    )
    text = (log.stdout or "") if log is not None and log.returncode == 0 else ""
    tail = "\n".join(text.splitlines()[-_CI_LOG_TAIL_LINES:]).strip()[-_CI_LOG_TAIL_CHARS:]
    if not tail:
        print("[caddis-lanes] ci-watch: no failed log available; no summary", file=sys.stderr)
        return None
    left = remaining()
    if left <= 0:
        print("[caddis-lanes] ci-watch: time budget used up; no summary", file=sys.stderr)
        return None
    try:
        return _ci_failure_summary(tail, agy_path=agy_path, repo=repo, remaining_s=left, run_agy=run_agy)
    except Exception as exc:  # agy must never change the result or the exit code
        print(f"[caddis-lanes] ci-watch: agy summary failed ({exc!r}); no summary", file=sys.stderr)
        return None


def ci_watch(
    target_kind: str,
    target_id: int,
    repo_slug: str | None,
    timeout_s: int,
    *,
    home: Path,
    repo: Path,
    which=shutil.which,
    run_agy=run_lane,
    run_gh=subprocess.run,
    clock=time.monotonic,
) -> int:
    """Wait for CI with `gh`, using one shared time budget. agy only summarises a failure.

    `gh pr checks --watch` (or `gh run watch`) does the waiting, but its exit code is not proof. On a PR,
    RESULT is `pass` only when the check rollup of the PR's head (one `gh pr view --json
    mergeStateStatus,headRefOid,statusCheckRollup`) is non-empty and every check is COMPLETED and green, and
    the head is the one read before the watch began (a push during the watch is exit 3). On a run, `gh run
    view --json status,conclusion,headSha` must read COMPLETED and SUCCESS (a skipped run ran no job). HEAD prints
    the commit. When the result is `fail` and the `ci-watch` routing chain holds agy, agy reads the last lines
    of the failed log (inside its prompt) and returns one line for SUMMARY. agy never changes the result or
    the exit code.
    """
    if target_kind not in {"pr", "run"} or target_id <= 0 or timeout_s <= 0:
        print("[caddis-lanes] ci-watch: target and timeout must be positive", file=sys.stderr)
        _print_ci_watch("timeout", "n/a", "n/a", "none", "gh")
        return EXIT_CONFIG
    if repo_slug is not None and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo_slug):
        print("[caddis-lanes] ci-watch: --repo must be OWNER/NAME", file=sys.stderr)
        _print_ci_watch("timeout", "n/a", "n/a", "none", "gh")
        return EXIT_CONFIG

    started = clock()
    try:
        watchers = caddis_routing.resolve(home, repo, which=which)["ci-watch"]
    except caddis_routing.RoutingConfigError as exc:
        print(f"[caddis-lanes] {exc}", file=sys.stderr)
        _print_ci_watch("timeout", "n/a", "n/a", "none", "gh")
        return EXIT_CONFIG

    def remaining() -> float:
        return timeout_s - (clock() - started)

    if remaining() <= 0:
        print("[caddis-lanes] ci-watch: time budget expired before gh", file=sys.stderr)
        _print_ci_watch("timeout", "n/a", "n/a", "none", "gh")
        return EXIT_CONFIG
    gh_path = which("gh")
    if gh_path is None:
        print("[caddis-lanes] ci-watch: gh not found on PATH", file=sys.stderr)
        _print_ci_watch("timeout", "n/a", "n/a", "none", "gh")
        return EXIT_CONFIG
    repo_args = ["--repo", repo_slug] if repo_slug else []
    head_before: str | None = None
    if target_kind == "pr":
        # The head before the watch: a push during the watch can make a new head look green before all its
        # checks exist, so a pass needs the same head after the watch.
        before = _ci_gh_run(run_gh, [gh_path, "pr", "view", str(target_id), "--json", "headRefOid", *repo_args],
                            repo, min(_CI_GH_SHORT_TIMEOUT_S, remaining()))
        if before is not None and before.returncode == 0:
            try:
                head_before = str(json.loads(before.stdout or "").get("headRefOid") or "") or None
            except (ValueError, AttributeError):
                head_before = None
        command = [gh_path, "pr", "checks", str(target_id), "--watch", "--interval", "30", *repo_args]
    else:
        command = [gh_path, "run", "watch", str(target_id), "--exit-status", "--interval", "30", *repo_args]
    try:
        completed = run_gh(
            command, cwd=repo, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=remaining(),
        )
    except subprocess.TimeoutExpired:
        print("[caddis-lanes] ci-watch: gh timed out", file=sys.stderr)
        _print_ci_watch("timeout", "n/a", "n/a", "none", "gh")
        return EXIT_CONFIG
    except OSError as exc:
        print(f"[caddis-lanes] ci-watch: gh could not start ({exc})", file=sys.stderr)
        _print_ci_watch("timeout", "n/a", "n/a", "none", "gh")
        return EXIT_CONFIG
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    if output:
        print("\n".join(output.splitlines()[-40:]), file=sys.stderr)
    no_checks = "no checks reported" in output.lower()
    code = EXIT_OK if completed.returncode == 0 else (
        EXIT_FAIL if completed.returncode == 1 and not no_checks else EXIT_CONFIG
    )
    result = "pass" if code == EXIT_OK else "fail" if code == EXIT_FAIL else "timeout"

    checks, merge_state = "n/a", "n/a"
    failing = "see gh output" if code == EXIT_FAIL else "none"
    run_id: str | None = str(target_id) if target_kind == "run" else None
    if target_kind == "pr" and code != EXIT_CONFIG:
        rows = _parse_pr_checks(completed.stdout or "")
        if rows:
            # `skipping` is not a failure: count it as passed.
            passed = sum(1 for _, state, _ in rows if state in {"pass", "skipping"})
            checks = f"{passed}/{len(rows)}"
            # Failed checks first; cancelled ones only when nothing failed (they name the wrong run).
            bad = ([(name, url) for name, state, url in rows if state == "fail"]
                   or [(name, url) for name, state, url in rows if state == "cancel"])
            if code == EXIT_FAIL and bad:
                failing = ", ".join(name for name, _ in bad)
            for _, url in bad:
                found = _RUN_ID_IN_URL.search(url)
                if found:
                    run_id = found.group(1)
                    break
    head = "n/a"
    if target_kind == "pr" and code != EXIT_CONFIG:
        # The watch table alone is not proof. gh exited 0 on 16 Oct 2026 with a cancelled row (CHECKS 6/7) and
        # with a row still unfinished (5/6), and its table can still show an older head's checks. So a pass
        # also needs the check rollup of the PR's CURRENT head: every check COMPLETED and green. HEAD names
        # that commit, so a caller can merge only that head.
        rollup_view = None
        left = remaining()
        if left > 0:
            view = _ci_gh_run(
                run_gh,
                [gh_path, "pr", "view", str(target_id), "--json", "mergeStateStatus,headRefOid,statusCheckRollup",
                 *repo_args],
                repo, min(_CI_GH_SHORT_TIMEOUT_S, left),
            )
            if view is not None and view.returncode == 0:
                try:
                    rollup_view = json.loads(view.stdout or "")
                except ValueError:
                    rollup_view = None
        if isinstance(rollup_view, dict):
            merge_state = str(rollup_view.get("mergeStateStatus") or "") or "n/a"
            head = str(rollup_view.get("headRefOid") or "") or "n/a"
        verdict = _rollup_verdict(rollup_view.get("statusCheckRollup")) if isinstance(rollup_view, dict) else None
        if code == EXIT_OK:
            if verdict is None or head == "n/a":
                print("[caddis-lanes] ci-watch: gh said pass, but the head's checks could not be read",
                      file=sys.stderr)
                code, result, failing = EXIT_CONFIG, "timeout", "none"
            else:
                green, failed, unfinished = verdict
                checks = f"{green}/{green + len(failed) + len(unfinished)}"
                if failed:
                    code, result, failing = EXIT_FAIL, "fail", ", ".join(failed)
                elif unfinished:
                    print(f"[caddis-lanes] ci-watch: gh said pass, but not finished: {', '.join(unfinished)}",
                          file=sys.stderr)
                    code, result, failing = EXIT_CONFIG, "timeout", "none"
                elif head_before is None:
                    print("[caddis-lanes] ci-watch: the head before the watch could not be read, so a push "
                          "during the watch cannot be ruled out; watch again", file=sys.stderr)
                    code, result, failing = EXIT_CONFIG, "timeout", "head not read before the watch"
                elif head != head_before:
                    print(f"[caddis-lanes] ci-watch: the head moved during the watch ({head_before} -> {head}); "
                          "watch again", file=sys.stderr)
                    code, result, failing = EXIT_CONFIG, "timeout", "head moved during the watch"
    elif target_kind == "run" and code == EXIT_OK:
        # The same rule for one run: pass only when the run reads COMPLETED and SUCCESS; HEAD is its commit. A whole
        # run that is SKIPPED or NEUTRAL ran no job (gh run watch --exit-status exits 0 on it): could not tell.
        run_view = None
        left = remaining()
        if left > 0:
            view = _ci_gh_run(
                run_gh, [gh_path, "run", "view", str(target_id), "--json", "status,conclusion,headSha", *repo_args],
                repo, min(_CI_GH_SHORT_TIMEOUT_S, left),
            )
            if view is not None and view.returncode == 0:
                try:
                    run_view = json.loads(view.stdout or "")
                except ValueError:
                    run_view = None
        if not isinstance(run_view, dict) or not run_view.get("headSha"):
            print("[caddis-lanes] ci-watch: gh said pass, but the run could not be read", file=sys.stderr)
            code, result = EXIT_CONFIG, "timeout"
        else:
            head = str(run_view["headSha"])
            status = str(run_view.get("status") or "").upper()
            conclusion = str(run_view.get("conclusion") or "").upper()
            if status != "COMPLETED":
                print(f"[caddis-lanes] ci-watch: gh said pass, but run {target_id} is {status.lower() or 'unknown'}",
                      file=sys.stderr)
                code, result = EXIT_CONFIG, "timeout"
            elif conclusion in {"SKIPPED", "NEUTRAL"}:
                print(f"[caddis-lanes] ci-watch: run {target_id} is {conclusion.lower()}: no job ran, so this is "
                      "not a pass", file=sys.stderr)
                code, result, failing = EXIT_CONFIG, "timeout", f"run {target_id} ({conclusion.lower()})"
            elif conclusion != "SUCCESS":
                code, result, failing = EXIT_FAIL, "fail", f"run {target_id} ({conclusion.lower() or 'unknown'})"

    summary: str | None = None
    # Walk the chain in order: agy summarises only when it comes before claude (claude = no helper).
    helper = next((w for w in watchers if w in {"agy", "claude"}), None)
    if code == EXIT_FAIL and helper == "agy":
        agy_path = which("agy")
        if agy_path is not None:
            summary = _ci_summary_from_log(
                gh_path, run_id, repo_args, repo, run_gh, remaining, agy_path, run_agy,
            )
    _print_ci_watch(result, checks, merge_state, failing, "gh+agy" if summary else "gh", summary, head)
    return code


def load_wording_findings(text: str) -> list[str]:
    findings = []
    seen = set()
    for pattern in LOAD_WORDING:
        for match in re.finditer(pattern, text):
            value = match.group(0)
            if value not in seen:
                seen.add(value)
                findings.append(value)
    return findings


def build_prompt(
    plan_rel: str,
    phase: int,
    attempt: int,
    findings: str,
    limits_line: str,
) -> str:
    prompt = (
        f"You are an implementation lane for caddis. Implement ONLY Phase {phase} "
        f"of the plan at {plan_rel} (read it from this working directory).\n"
        "Rules:\n"
        "- Work only inside this working directory. Do not touch files outside it.\n"
        "- Follow the phase's TDD steps: write the failing test first, run it and "
        "confirm it fails for the right reason, then implement until it passes.\n"
        "- Do NOT commit, push, open a PR, or merge. Leave your changes uncommitted; "
        "the orchestrator reviews and commits them.\n"
        "- Never use --no-verify. Never read or edit .env files or any secret. Never "
        "run anything against production.\n"
        "- Do not implement any other phase.\n"
        "- Run every command in the foreground and wait for it to finish. Start no background tasks, watchers or dev servers.\n"
        "- Test economy: after each step run only the tests for the file or module you changed. Run the full suite "
        "only for the baseline and once at the end. Do not run a review loop in this lane; the orchestrator reviews. "
        "Print a progress line every 20 minutes. Never start a second heavy test run while one is still running.\n"
        "Resource budget (enforced by the machine, not by this text):\n"
        f"- You run inside a Windows Job Object: {limits_line}. Exceeding it slows "
        "you down; it does not stop the limit.\n"
        "- This host is shared with a desktop, CI runners and services. Never start "
        "load generators, CPU burners, stress or load tests, or background processes "
        "that outlive your command.\n"
        "- Prove timing behaviour by design: event-driven fakes, ordering assertions, "
        "and an A/B check that fails against the racy version.\n"
        "- When done, print a short summary: files changed, tests run, and their final "
        "result line.\n"
    )
    if attempt > 1 and findings:
        prompt += (
            f"\nThis is attempt {attempt}. The previous attempt was rejected. "
            f"Fix these findings:\n{findings}\n"
        )
    return prompt


def _load_file_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise LaneConfigError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise LaneConfigError(f"could not load {path}: {exc}") from exc
    return module


def phase_block_text(plan: Path, phase: int) -> str:
    gate_path = Path(__file__).with_name("caddis_gate.py")
    gate = _load_file_module("_caddis_gate_for_lanes", gate_path)
    try:
        text = plan.read_text(encoding="utf-8")
    except OSError as exc:
        raise LaneConfigError(f"could not read {plan}: {exc}") from exc
    block = gate.phase_block(text, phase)
    if not block:
        raise LaneConfigError(f"phase {phase} not found in {plan}")
    return block


def resource_limits_line() -> str:
    path = governor_path()
    governor = _load_file_module("_caddis_governor_limits_for_lanes", path)
    try:
        limits = governor.load_limits("lane")
    except Exception as exc:
        raise LaneConfigError(f"could not load lane resource limits: {exc}") from exc
    return (
        f"cpu {limits.cpu_percent}% of the machine, memory {limits.memory_mb} MB, "
        f"at most {limits.max_processes} processes, BelowNormal priority"
    )


def _repo_path(value: Path | None) -> Path:
    start = Path.cwd() if value is None else value.resolve()
    return Path(_git_output(start, "rev-parse", "--show-toplevel")).resolve()


def _plan_path(repo: Path, value: Path) -> tuple[Path, str]:
    plan = value if value.is_absolute() else repo / value
    plan = plan.resolve()
    if not plan.is_file():
        raise LaneConfigError(f"plan does not exist: {plan}")
    try:
        plan_rel = plan.relative_to(repo).as_posix()
    except ValueError as exc:
        raise LaneConfigError(f"plan must be inside the repository: {plan}") from exc
    return plan, plan_rel


def _packet_path(repo: Path, plan_stem: str, phase: int, attempt: int) -> Path:
    return run_dir(repo, plan_stem) / f"phase-{phase:02d}.attempt-{attempt}.json"


def _freeze_path(packet_path: Path) -> Path:
    return packet_path.with_suffix(".freeze.json")


def _new_packet(
    plan_rel: str,
    phase: int,
    attempt: int,
    task_type: str = "",
) -> dict:
    return {
        "plan": plan_rel,
        "phase": phase,
        "attempt": attempt,
        "task_type": task_type,
        "lanes_tried": [],
        "lane": "",
        "model": "",
        "result": "",
        "worktree": "",
        "branch": "",
        "base_sha": "",
        "changed_files": [],
        "gates": [],
        "gates_passed": False,
        "review": {"status": "MISSING", "returncode": None, "tail": ""},
        "freeze_unchanged": None,
        "next": "stop",
        "created": packet_created(),
    }


def _read_packet(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LaneConfigError(f"could not read packet {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LaneConfigError(f"packet is not an object: {path}")
    return value


def _worktree_from_packet(packet: dict) -> Worktree:
    try:
        path = Path(packet["worktree"])
        branch = str(packet["branch"])
        base_sha = str(packet["base_sha"])
    except (KeyError, TypeError) as exc:
        raise LaneConfigError("packet does not identify a worktree") from exc
    if not str(path) or not branch:
        raise LaneConfigError("packet does not identify a worktree")
    return Worktree(path, branch, base_sha)


def _gate_dict(result: GateResult) -> dict:
    return {
        "cmd": result.cmd,
        "returncode": result.returncode,
        "passed": result.passed,
        "tail": result.tail,
        "duration_s": round(result.duration_s, 1),
    }


def _time_split(packet: dict, gates: list[GateResult], review_s: float) -> dict:
    """Measured seconds the orchestrator can read: the lane run, the gate commands, the review.

    What happens INSIDE the lane (edits versus the lane's own test runs) is not measured: the idle
    sampler sees process image names every IDLE_SAMPLE_S seconds, not command lines, so it cannot tell a
    pytest run from any other python process.
    """
    return {
        "lane_s": round(sum(float(lane.get("duration_s") or 0) for lane in packet.get("lanes_tried", [])), 1),
        "gates_s": round(sum(gate.duration_s for gate in gates), 1),
        "gate_runs": len(gates),
        "review_s": round(review_s, 1),
        "in_lane": "not measured: only process names are visible inside a lane",
    }


def _review_dict(result: ReviewResult) -> dict:
    return {
        "status": result.status,
        "returncode": result.returncode,
        "tail": result.tail,
    }


def _run_post_checks(
    repo: Path,
    cfg: dict,
    packet: dict,
    before: dict[str, str | None],
) -> tuple[str, int]:
    worktree = Path(packet["worktree"])
    # The heavy-run slot covers the project's own test commands only. The review is a network call and
    # must not hold a slot that another gate is waiting for.
    try:
        with heavy_slot("gates"):
            gates = run_gates(
                gate_commands(repo, worktree, cfg),
                worktree,
                gate_env(repo, dict(os.environ)),
            )
    except HeavySlotBusy as exc:
        msg = f"heavy-run slot busy: {exc.holder}" if exc.holder else "heavy-run slot busy"
        packet.update(
            {
                "gates": [{"cmd": "gates", "returncode": EXIT_NOT_RUN, "passed": False, "tail": msg}],
                "gates_passed": False,
                "next": "stop",
            }
        )
        packet.pop("_freeze_before", None)
        return "stop", EXIT_NOT_RUN

    review_started = time.monotonic()
    review = run_review(worktree, dict(os.environ))
    review_s = time.monotonic() - review_started
    pythons = list(before)
    if pythons:
        after = {python: freeze_snapshot(python) for python in pythons}
        freeze_unchanged = all(
            before[python] is not None
            and after[python] is not None
            and before[python] == after[python]
            for python in pythons
        )
    else:
        freeze_unchanged = None

    gates_passed = all(gate.passed for gate in gates)
    if gates_passed and freeze_unchanged is not False:
        next_step = "review"
        exit_code = EXIT_OK
    else:
        next_step = "takeover" if packet["attempt"] >= MAX_ATTEMPTS else "redo"
        exit_code = EXIT_FAIL

    changed = changed_files(worktree)
    packet.update(
        {
            "changed_files": changed,
            "worktree_digest": worktree_digest(worktree, changed),
            "gates": [_gate_dict(gate) for gate in gates],
            "gates_passed": gates_passed,
            "review": _review_dict(review),
            "time_split": _time_split(packet, gates, review_s),
            "freeze_unchanged": freeze_unchanged,
            "next": next_step,
        }
    )
    packet.pop("_freeze_before", None)
    return next_step, exit_code


def _run_command(
    args,
    repo: Path,
    plan: Path,
    plan_rel: str,
    packet_path: Path,
) -> int:
    cfg = load_lanes_config(repo)
    idle_timeout_s = idle_timeout(cfg, args.idle_timeout)
    block = phase_block_text(plan, args.phase)
    findings_text = ""
    if args.findings is not None:
        findings_path = args.findings
        if not findings_path.is_absolute():
            findings_path = repo / findings_path
        try:
            findings_text = findings_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise LaneConfigError(f"could not read findings {findings_path}: {exc}") from exc

    packet = _new_packet(plan_rel, args.phase, args.attempt, args.type)
    hits = load_wording_findings(block + findings_text)
    if hits and not args.allow_load:
        packet.update({"result": RESULT_CONFIG_ERROR, "next": "stop"})
        write_packet(packet_path, packet)
        print(
            "NEXT: stop (load or stress wording found: "
            f"{hits}; the owner must pass --allow-load)"
        )
        return EXIT_CONFIG
    if hits:
        print("[caddis-lanes] --allow-load given; resource limits still apply")

    chain = resolve_chain(args.type, cfg, first_lane=args.lane)
    models = resolve_models(cfg)
    prompt = build_prompt(
        plan_rel,
        args.phase,
        args.attempt,
        findings_text,
        resource_limits_line(),
    )
    wt = create_phase_worktree(repo, plan.stem, args.phase, args.attempt)
    pythons = shared_venv_pythons(repo, cfg)
    before = {python: freeze_snapshot(python) for python in pythons}
    packet.update(
        {
            "worktree": str(wt.path),
            "branch": wt.branch,
            "base_sha": wt.base_sha,
        }
    )
    wt_plan = wt.path / plan_rel
    if not wt_plan.exists() and plan.exists():
        wt_plan.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(plan, wt_plan)

    for lane in chain:
        model = models[lane]
        effort = DEFAULT_EFFORT[lane]
        packet.update({"lane": lane, "model": model})
        if lane == "claude":
            packet.update(
                {
                    "result": "PENDING",
                    "next": "claude-implement",
                }
            )
            write_packet(_freeze_path(packet_path), before)
            write_packet(packet_path, packet)
            print(f"NEXT: claude-implement worktree={wt.path}")
            return EXIT_OK

        lane_argv = build_argv(lane, model, effort, wt.path)
        validate_codex_argv(lane_argv)
        lane_run = run_lane(
            lane_argv,
            wt.path,
            prompt,
            prompt_via_stdin(lane),
            args.timeout,
            child_env(dict(os.environ), lane, model),
            idle_timeout_s=idle_timeout_s,
            spend_caller=f"lane:{lane}:{plan.stem}:p{args.phase}",
        )
        killed = guard_killed_since(lane_run.started, {lane_run.pid})
        result = classify_exit(
            lane,
            lane_run.returncode,
            lane_run.output,
            lane_run.timed_out,
            killed,
            lane_run.stalled,
        )
        packet["lanes_tried"].append(
            {
                "lane": lane,
                "model": model,
                "effort": effort,
                "result": result,
                "returncode": lane_run.returncode,
                "duration_s": lane_run.duration_s,
                "timed_out": lane_run.timed_out,
                "stalled": lane_run.stalled,
                "idle_seconds": lane_run.idle_seconds,
            }
        )
        packet["result"] = result
        if lane_run.stalled:
            packet.update({
                "stall": "idle",
                "idle_seconds": lane_run.idle_seconds,
                "tail": f"idle for {lane_run.idle_seconds}s; process tree before kill: "
                        f"{json.dumps(lane_run.processes or [])}",
            })
        if result == RESULT_RESOURCE:
            packet["next"] = "stop"
            write_packet(packet_path, packet)
            print("NEXT: stop (host guard killed the lane; see the guard log)")
            return EXIT_FAIL
        if result == RESULT_OUT_OF_BUDGET:
            print(f"[caddis-lanes] {lane} out of budget; trying next lane")
            continue
        if result == RESULT_CONFIG_ERROR:
            packet["next"] = "stop"
            write_packet(packet_path, packet)
            print(f"NEXT: stop (config error on {lane})")
            return EXIT_CONFIG
        if result in (RESULT_LANE_FAILED, RESULT_STALLED):
            packet["next"] = (
                "takeover" if args.attempt >= MAX_ATTEMPTS else "redo"
            )
            write_packet(packet_path, packet)
            if result == RESULT_STALLED:
                print(f"NEXT: {packet['next']} (lane idle {lane_run.idle_seconds}s; see packet)")
            else:
                print(f"NEXT: {packet['next']}")
            return EXIT_FAIL
        break
    else:
        packet.update({"result": RESULT_OUT_OF_BUDGET, "next": "stop"})
        write_packet(packet_path, packet)
        print("NEXT: stop (every lane in the chain is out of budget)")
        return EXIT_ALL_OUT

    next_step, exit_code = _run_post_checks(repo, cfg, packet, before)
    write_packet(packet_path, packet)
    print(f"NEXT: {next_step} packet={packet_path}")
    return exit_code


def _check_command(
    args,
    repo: Path,
    plan: Path,
    _plan_rel: str,
    packet_path: Path,
) -> int:
    packet = _read_packet(packet_path)
    if packet is None:
        print(f"refusing: packet not found: {packet_path}")
        return EXIT_USAGE
    if packet.get("result") != "PENDING":
        print(f"refusing: packet result={packet.get('result')}")
        return EXIT_USAGE

    wt = _worktree_from_packet(packet)
    _validate_packet_worktree(repo, plan, args.phase, args.attempt, wt)
    cfg = load_lanes_config(repo)
    stored_before = _read_packet(_freeze_path(packet_path))
    configured_pythons = set(shared_venv_pythons(repo, cfg))
    if stored_before is None or not configured_pythons <= set(stored_before):
        print("refusing: freeze snapshot missing")
        return EXIT_USAGE
    before = {
        python: snapshot
        for python, snapshot in stored_before.items()
        if python in configured_pythons
        and (isinstance(snapshot, str) or snapshot is None)
    }
    packet["result"] = RESULT_OK
    next_step, exit_code = _run_post_checks(repo, cfg, packet, before)
    write_packet(packet_path, packet)
    _freeze_path(packet_path).unlink(missing_ok=True)
    print(f"NEXT: {next_step} packet={packet_path}")
    return exit_code


_TERMINAL_ESCAPES = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"  # CSI (colours, cursor)
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?"  # OSC (titles, links)
    r"|\x1b[@-Z\\-_]"  # other two-byte escapes
)
_CONTROL_CHARS = re.compile(r"[\x00-\x09\x0b-\x1f\x7f]")


def _printable(value: object) -> str:
    """Text safe to print: no ANSI escapes and no C0 control characters except newline."""
    text = _TERMINAL_ESCAPES.sub("", str(value if value is not None else ""))
    return _CONTROL_CHARS.sub("", text)


# Accept fast-forwards the SESSION checkout. In a checkout a dev service serves from, or one that holds a peer's
# uncommitted edits, that moves files under them (robustness #11). The lane's own scaffolding is not a peer's change.
_LANE_OWN_PREFIX = ".caddis/orchestrator/"


def shared_checkout_reason(repo: Path) -> str:
    """Why accept must not fast-forward `repo`, or ''. Shared (AGENTS.md) and/or foreign changes (git status):
    every reason that holds, joined with "; ", so an --allow-shared audit records all of them."""
    reasons = []
    if caddis_checkout_guard.checkout_is_shared(repo):
        reasons.append("AGENTS.md says Shared checkout: yes")
    try:
        dirty = caddis_checkout_guard.foreign_changes(repo)
    except caddis_checkout_guard.CheckoutStatusError:
        reasons.append("git status failed, so changes by other sessions cannot be ruled out")
        dirty = []
    foreign = [path for path in dirty if not path.replace("\\", "/").startswith(_LANE_OWN_PREFIX)]
    if foreign:
        reasons.append("changes not made by this lane: " + ", ".join(foreign[:3]))
    return "; ".join(reasons)


def _accept_command(
    args,
    repo: Path,
    plan: Path,
    _plan_rel: str,
    packet_path: Path,
) -> int:
    programme = _git_output(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if programme in ("main", "master", "HEAD"):
        print("NEXT: stop (accept runs on the programme branch, not main)")
        return EXIT_USAGE

    packet = _read_packet(packet_path)
    if packet is None:
        print(f"refusing: packet not found: {packet_path}")
        return EXIT_USAGE
    if packet.get("next") != "review":
        print(f"refusing: packet next={packet.get('next')}")
        return EXIT_USAGE
    # Fail closed: only an exact CLEAN verdict merges without an owner override.
    review = packet.get("review") or {}
    if not isinstance(review, dict):
        review = {}
    review_status = review.get("status")
    override_reason = (getattr(args, "override_review", None) or "").strip()
    if review_status != "CLEAN" and not override_reason:
        if review_status == "BLOCKING":
            print("refusing: review BLOCKING; pass --override-review with a reason")
        else:
            # MISSING = no verdict (provider down, 429, secret-filter refusal). Anything else
            # that is not CLEAN (absent, null, unknown, lowercase) is also no valid verdict.
            cause = " ".join(_printable(review.get("tail")).split())[-300:] or "no reason recorded"
            label = (
                "MISSING" if review_status == "MISSING"
                else f"status {_printable(review_status)!r}"
            )
            print(f"refusing: review {label} (no verdict: {cause}); re-run the review, "
                  "or pass --override-review with a reason")
        return EXIT_USAGE
    if _git_output(repo, "rev-parse", "HEAD") != packet.get("base_sha"):
        print("refusing: programme branch moved since the attempt started")
        return EXIT_FAIL

    wt = _worktree_from_packet(packet)
    _validate_packet_worktree(repo, plan, args.phase, args.attempt, wt)
    files = packet.get("changed_files")
    if not isinstance(files, list) or not files:
        print("refusing: packet has no changed files")
        return EXIT_USAGE
    if not packet.get("worktree_digest"):
        print("refusing: packet has no worktree digest; run check again")
        return EXIT_USAGE
    if (changed_files(wt.path) != files
            or packet["worktree_digest"] != worktree_digest(wt.path, files)):
        print("refusing: worktree changed since check")
        return EXIT_FAIL
    unsafe = shared_checkout_reason(repo)
    if unsafe and not getattr(args, "allow_shared", False):
        print(f"refusing: the session checkout is not safe to fast-forward ({_printable(unsafe)}). "
              "Run the programme from a worktree of origin/<default> (git worktree add; `caddis_worktree_root.py` prints the path, never %TEMP%), "
              "or pass --allow-shared to fast-forward here anyway")
        return EXIT_USAGE
    if unsafe:
        packet["allow_shared"] = unsafe
        write_packet(packet_path, packet)
        print(f"ALLOW SHARED: {_printable(unsafe)}")
    if args.override_review is not None:
        packet["override_review"] = args.override_review
        write_packet(packet_path, packet)
        print(f"OVERRIDE REVIEW: {args.override_review}")
        if review_status != "CLEAN":
            print(
                f"WARNING: merged without a vendor review (status {_printable(review_status)}): "
                f"{args.override_review}"
            )
    _git_output(wt.path, "add", "--", *(str(path) for path in files))
    _git_output(wt.path, "commit", "-m", args.message)
    accepted_sha = _git_output(wt.path, "rev-parse", "HEAD")
    _git_output(repo, "merge", "--ff-only", wt.branch)
    remove_phase_worktree(repo, wt, delete_branch=True)
    _freeze_path(packet_path).unlink(missing_ok=True)
    print(f"ACCEPTED {accepted_sha[:7]}")
    return EXIT_OK


def _abandon_command(
    args,
    repo: Path,
    plan: Path,
    _plan_rel: str,
    packet_path: Path,
) -> int:
    packet = _read_packet(packet_path)
    if packet is None:
        print(f"refusing: packet not found: {packet_path}")
        return EXIT_USAGE
    wt = _worktree_from_packet(packet)
    _validate_packet_worktree(repo, plan, args.phase, args.attempt, wt)
    remove_phase_worktree(repo, wt, delete_branch=True)
    _freeze_path(packet_path).unlink(missing_ok=True)
    print(f"ABANDONED {wt.branch}")
    return EXIT_OK


def branch_is_merged(repo: Path, branch: str) -> bool:
    ancestor = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", branch, "HEAD"],
        capture_output=True,
    )
    if ancestor.returncode == 0:
        return True
    merge_base = _git_output(repo, "merge-base", branch, "HEAD")
    files = _git_output(repo, "diff", "--name-only", merge_base, branch).splitlines()
    if not files:
        return False
    same_tree = subprocess.run(
        ["git", "-C", str(repo), "diff", "--quiet", branch, "HEAD", "--", *files],
        capture_output=True,
    )
    return same_tree.returncode == 0


def _worktree_entries(repo: Path) -> list[tuple[Path, str]]:
    entries = []
    current: dict[str, str] = {}
    output = _git_output(repo, "worktree", "list", "--porcelain")
    for line in [*output.splitlines(), ""]:
        if not line:
            if "worktree" in current:
                branch = current.get("branch", "")
                prefix = "refs/heads/"
                if branch.startswith(prefix):
                    branch = branch[len(prefix) :]
                entries.append((Path(current["worktree"]), branch))
            current = {}
            continue
        key, _, value = line.partition(" ")
        if key in ("worktree", "branch"):
            current[key] = value
    return entries


def _validate_packet_worktree(
    repo: Path,
    plan: Path,
    phase: int,
    attempt: int,
    wt: Worktree,
) -> None:
    resolved = wt.path.resolve()
    expected_branch = f"lane/{plan.stem}/phase-{phase:02d}-a{attempt}"
    if not is_lane_worktree_path(repo, resolved):
        raise LaneConfigError(f"refusing packet worktree that is not a lane worktree: {resolved}")
    if wt.branch != expected_branch:
        raise LaneConfigError(
            f"refusing packet branch {wt.branch}: expected {expected_branch}"
        )
    registered = {(path.resolve(), branch) for path, branch in _worktree_entries(repo)}
    if (resolved, wt.branch) not in registered:
        raise LaneConfigError(
            f"refusing packet worktree not registered on {wt.branch}: {resolved}"
        )


def _finish_command(args) -> int:
    repo = _repo_path(args.repo)
    plan, _ = _plan_path(repo, args.plan)
    programme = _git_output(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if programme in ("main", "master", "HEAD"):
        print("NEXT: stop (finish runs on the programme branch, not main)")
        return EXIT_USAGE

    prefix = f"lane/{plan.stem}/"
    leftovers: list[tuple[str, str]] = []
    locked_phases = set()
    directory = run_dir(repo, plan.stem)
    for lock in sorted(directory.glob("*.lock")):
        try:
            pid = int(lock.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pid = 0
        if pid > 0 and process_alive(pid):
            phase_match = re.fullmatch(r"phase-(\d+)\.lock", lock.name)
            if phase_match:
                locked_phases.add(int(phase_match.group(1)))
            leftovers.append(("LOCKED", str(lock)))
        else:
            lock.unlink(missing_ok=True)

    def branch_is_locked(branch: str) -> bool:
        match = re.fullmatch(
            rf"{re.escape(prefix)}phase-(\d+)-a\d+",
            branch,
        )
        return bool(match and int(match.group(1)) in locked_phases)

    main_path = repo.resolve()
    for path, branch in _worktree_entries(repo):
        resolved = path.resolve()
        if resolved == main_path:
            continue
        if not branch.startswith(prefix) or not is_lane_worktree_path(repo, resolved):
            print(f"OTHER {path} {branch or 'HEAD'}")
            continue
        if branch_is_locked(branch):
            continue
        if _git_output(path, "status", "--porcelain"):
            leftovers.append(("DIRTY", str(path)))
        elif branch_is_merged(repo, branch):
            remove_phase_worktree(repo, Worktree(path, branch, ""), delete_branch=True)
            print(f"REMOVED {path} {branch}")
        else:
            leftovers.append(("UNMERGED", branch))

    held_branches = {branch for _, branch in _worktree_entries(repo) if branch}
    branches = _git_output(
        repo,
        "for-each-ref",
        "--format=%(refname:short)",
        f"refs/heads/{prefix}",
    ).splitlines()
    for branch in branches:
        if branch in held_branches or branch_is_locked(branch):
            continue
        if branch_is_merged(repo, branch):
            _git_output(repo, "branch", "-D", "--", branch)
            print(f"REMOVED {branch}")
        else:
            leftovers.append(("UNMERGED", branch))

    if not leftovers and not args.no_push:
        remotes = _git_output(repo, "remote").splitlines()
        if "origin" in remotes:
            pushed = subprocess.run(
                ["git", "-C", str(repo), "push", "-u", "origin", programme],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if pushed.returncode == 0:
                short_sha = _git_output(repo, "rev-parse", "--short", "HEAD")
                print(f"PUSHED {programme} {short_sha}")
            else:
                leftovers.append(("PUSH-FAILED", programme))

    for kind, target in leftovers:
        print(f"LEFTOVER {kind} {target}")
    print(f"LEFTOVERS: {len(leftovers)}")
    if leftovers:
        print("NEXT: resolve leftovers")
        return EXIT_FAIL
    print(
        "NEXT: ship-pr (open the PR with /caddis:ship-pr; merging to main and "
        "post-merge cleanup stay with /caddis:ship-merge after the owner's go)"
    )
    return EXIT_OK


def _add_phase_arguments(parser) -> None:
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--phase", type=int, required=True)
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument("--repo", type=Path)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    show_chain = subparsers.add_parser("show-chain")
    show_chain.add_argument("--type", required=True)
    show_chain.add_argument("--lane")
    show_chain.add_argument("--repo", type=Path)

    next_model = subparsers.add_parser("next-lane")
    next_model.add_argument("--role", required=True, choices=tuple(caddis_routing.DEFAULT_ROUTING))
    next_model.add_argument("--after", required=True)

    watch = subparsers.add_parser("ci-watch")
    watch_target = watch.add_mutually_exclusive_group(required=True)
    watch_target.add_argument("--pr", type=int)
    watch_target.add_argument("--run", type=int)
    watch.add_argument("--repo")
    watch.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S)

    run = subparsers.add_parser("run")
    _add_phase_arguments(run)
    run.add_argument("--type", required=True)
    run.add_argument("--lane")
    run.add_argument("--findings", type=Path)
    run.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S)
    run.add_argument("--idle-timeout", type=int)
    run.add_argument("--allow-load", action="store_true")

    check = subparsers.add_parser("check")
    _add_phase_arguments(check)
    accept = subparsers.add_parser("accept")
    _add_phase_arguments(accept)
    accept.add_argument("--message", required=True)
    accept.add_argument("--override-review")
    accept.add_argument("--allow-shared", action="store_true",
                        help="fast-forward a shared checkout or one with foreign changes anyway (recorded)")
    abandon = subparsers.add_parser("abandon")
    _add_phase_arguments(abandon)
    finish = subparsers.add_parser("finish")
    finish.add_argument("--plan", type=Path, required=True)
    finish.add_argument("--repo", type=Path)
    finish.add_argument("--no-push", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.command == "next-lane":
            if args.after not in caddis_routing.KNOWN_MODELS:
                print(f"[caddis-lanes] next-lane: unknown model {args.after!r}", file=sys.stderr)
                return EXIT_CONFIG
            try:
                candidate = next_lane(
                    args.role, args.after, home=Path.home(), repo=Path.cwd(), which=shutil.which
                )
            except caddis_routing.RoutingConfigError as exc:
                print(f"[caddis-lanes] next-lane: {exc}", file=sys.stderr)
                return EXIT_CONFIG
            if candidate is None:
                print(
                    f"[caddis-lanes] next-lane: no lane left for {args.role} after {args.after}",
                    file=sys.stderr,
                )
                return EXIT_CONFIG
            print(candidate)
            return EXIT_OK
        if args.command == "ci-watch":
            return ci_watch(
                "pr" if args.pr is not None else "run",
                args.pr if args.pr is not None else args.run,
                args.repo,
                args.timeout,
                home=Path.home(),
                repo=Path.cwd(),
            )
        if args.command == "show-chain":
            cfg = load_lanes_config(args.repo if args.repo is not None else Path.cwd())
            chain = resolve_chain(args.type, cfg, first_lane=args.lane)
            print(" -> ".join(chain))
            return EXIT_OK
        if args.command == "finish":
            return _finish_command(args)

        repo = _repo_path(args.repo)
        plan, plan_rel = _plan_path(repo, args.plan)
        packet_path = _packet_path(repo, plan.stem, args.phase, args.attempt)
        lock = run_dir(repo, plan.stem) / f"phase-{args.phase:02d}.lock"
        acquire_lock(lock)
        try:
            handlers = {
                "run": _run_command,
                "check": _check_command,
                "accept": _accept_command,
                "abandon": _abandon_command,
            }
            return handlers[args.command](args, repo, plan, plan_rel, packet_path)
        finally:
            release_lock(lock)
    except LaneConfigError as exc:
        print(f"[caddis-lanes] {exc}", file=sys.stderr)
        return EXIT_CONFIG

    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
