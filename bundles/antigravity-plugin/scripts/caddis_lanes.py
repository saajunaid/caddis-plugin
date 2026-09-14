"""caddis_lanes — run one plan phase on an execution lane, re-check it, and write a result packet.

The pure core resolves configured lanes and builds confined child-process invocations.
"""
from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_CONFIG, EXIT_ALL_OUT = 0, 1, 2, 3, 4
RESULT_OK = "OK"
RESULT_LANE_FAILED = "LANE-FAILED"
RESULT_OUT_OF_BUDGET = "OUT-OF-BUDGET"
RESULT_CONFIG_ERROR = "CONFIG-ERROR"
RESULT_RESOURCE = "FAILED-RESOURCE"
MAX_ATTEMPTS = 2
DEFAULT_TIMEOUT_S = 3600
LANE_IDS = ("claude", "glm", "codex-sol", "codex-astra", "agy")
TASK_TYPES = ("backend", "hard", "ui", "tests", "docs")
LANES_TMP = Path(tempfile.gettempdir()) / "caddis-lanes"
DEFAULT_MODELS = {
    "claude": "claude-opus-5",
    "glm": "glm-5.3[1m]",
    "codex-sol": "gpt-5.6-sol",
    "codex-astra": "gpt-6-astra",
    "agy": "gemini-3.8-flash",
}
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
    "claude": (),
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
    "agy": (r"RESOURCE_EXHAUSTED.*quota", r"Individual quota reached"),
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
    "agy": (r"invalid model selection", r"is not recognized as a known model"),
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


@dataclass
class GateResult:
    cmd: str
    returncode: int
    passed: bool
    tail: str


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


def create_phase_worktree(
    repo_root: Path,
    plan_stem: str,
    phase: int,
    attempt: int,
) -> Worktree:
    base_sha = _git_output(repo_root, "rev-parse", "HEAD")
    branch = f"lane/{plan_stem}/phase-{phase:02d}-a{attempt}"
    repo_hash = hashlib.sha256(str(repo_root.resolve()).encode("utf-8")).hexdigest()[:8]
    path = LANES_TMP / (
        f"{repo_root.name}-{repo_hash}-{plan_stem}-p{phase:02d}-a{attempt}"
    )
    if path.exists():
        raise LaneConfigError(f"worktree already exists: {path} — run abandon first")

    LANES_TMP.mkdir(parents=True, exist_ok=True)
    _git_output(
        repo_root,
        "worktree",
        "add",
        "-b",
        branch,
        str(path),
        base_sha,
    )
    print(f"[caddis-lanes] worktree: {path}", file=sys.stderr)
    return Worktree(path=path, branch=branch, base_sha=base_sha)


def remove_phase_worktree(
    repo_root: Path,
    wt: Worktree,
    delete_branch: bool,
) -> None:
    resolved = wt.path.resolve()
    if LANES_TMP.resolve() not in resolved.parents:
        raise LaneConfigError(f"refusing to remove {resolved}: not under {LANES_TMP}")
    if delete_branch and not wt.branch.startswith("lane/"):
        raise LaneConfigError(f"refusing to delete non-lane branch: {wt.branch}")

    _git_output(repo_root, "worktree", "remove", "--force", str(resolved))
    _git_output(repo_root, "worktree", "prune")
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


def governed_argv(argv: list[str]) -> list[str]:
    return [
        sys.executable,
        str(governor_path()),
        "exec",
        "--scope",
        "lane",
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


def run_lane(
    argv: list[str],
    cwd: Path,
    prompt: str,
    stdin_prompt: bool,
    timeout_s: int,
    env: dict,
) -> LaneRun:
    full = governed_argv(argv)
    if not stdin_prompt:
        full.append(prompt)
    validate_codex_argv(full)

    started = time.time()
    monotonic_started = time.monotonic()
    popen_options = {}
    if sys.platform != "win32":
        popen_options["start_new_session"] = True
    proc = subprocess.Popen(
        full,
        cwd=cwd,
        stdin=subprocess.PIPE if stdin_prompt else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        **popen_options,
    )
    timed_out = False
    output = ""
    try:
        try:
            output, _ = proc.communicate(
                input=prompt if stdin_prompt else None,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired as first_timeout:
            kill_governed(proc)
            timed_out = True
            try:
                output, _ = proc.communicate(timeout=30)
            except subprocess.TimeoutExpired as second_timeout:
                kill_governed(proc)
                captured = second_timeout.output or first_timeout.output or ""
                output = (
                    captured.decode("utf-8", errors="replace")
                    if isinstance(captured, bytes)
                    else captured
                )
    except BaseException:
        kill_governed(proc)
        raise

    return LaneRun(
        returncode=proc.returncode,
        output=output,
        timed_out=timed_out,
        duration_s=time.monotonic() - monotonic_started,
        pid=proc.pid,
        started=started,
    )


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
    results = []
    for command in cmds:
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
            )
        )
    return results


def oss_review_path() -> Path | None:
    sibling = Path(__file__).with_name("oss_review.py")
    if sibling.exists():
        return sibling
    source = Path(__file__).resolve().parents[1] / ".github" / "tools" / "oss_review.py"
    return source if source.exists() else None


def run_review(worktree: Path, env: dict, timeout_s: int = 900) -> ReviewResult:
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
    temporary.write_text(
        json.dumps(packet, indent=2, sort_keys=True) + "\n",
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
    return lanes


def resolve_models(cfg: dict) -> dict[str, str]:
    models = DEFAULT_MODELS.copy()
    for key, value in cfg.get("models", {}).items():
        if key not in LANE_IDS:
            raise LaneConfigError(f"unknown lane in [lanes.models]: {key}")
        if not isinstance(value, str) or not value:
            raise LaneConfigError(f"empty model id for lane {key}")
        models[key] = value
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


def child_env(base: dict, lane: str, model: str) -> dict:
    env = base.copy()
    env["CADDIS_HEADLESS"] = "1"
    if lane == "glm":
        env["OSS_MODEL"] = model
    return env


def classify_exit(
    lane: str,
    returncode: int | None,
    output: str,
    timed_out: bool,
    guard_killed: bool = False,
) -> str:
    if guard_killed:
        return RESULT_RESOURCE
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
    gates = run_gates(
        gate_commands(repo, worktree, cfg),
        worktree,
        gate_env(repo, dict(os.environ)),
    )
    review = run_review(worktree, dict(os.environ))
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
        )
        killed = guard_killed_since(lane_run.started, {lane_run.pid})
        result = classify_exit(
            lane,
            lane_run.returncode,
            lane_run.output,
            lane_run.timed_out,
            killed,
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
            }
        )
        packet["result"] = result
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
        if result == RESULT_LANE_FAILED:
            packet["next"] = (
                "takeover" if args.attempt >= MAX_ATTEMPTS else "redo"
            )
            write_packet(packet_path, packet)
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
    review_status = packet.get("review", {}).get("status")
    if review_status == "BLOCKING" and not getattr(args, "override_review", None):
        print("refusing: review BLOCKING; pass --override-review with a reason")
        return EXIT_USAGE
    if review_status == "MISSING":
        print("WARNING: review MISSING")
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
    if args.override_review is not None:
        packet["override_review"] = args.override_review
        write_packet(packet_path, packet)
        print(f"OVERRIDE REVIEW: {args.override_review}")
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
    if LANES_TMP.resolve() not in resolved.parents:
        raise LaneConfigError(f"refusing packet worktree outside {LANES_TMP}: {resolved}")
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
        in_lanes_tmp = LANES_TMP.resolve() in resolved.parents
        if not branch.startswith(prefix) or not in_lanes_tmp:
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

    run = subparsers.add_parser("run")
    _add_phase_arguments(run)
    run.add_argument("--type", required=True)
    run.add_argument("--lane")
    run.add_argument("--findings", type=Path)
    run.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S)
    run.add_argument("--allow-load", action="store_true")

    check = subparsers.add_parser("check")
    _add_phase_arguments(check)
    accept = subparsers.add_parser("accept")
    _add_phase_arguments(accept)
    accept.add_argument("--message", required=True)
    accept.add_argument("--override-review")
    abandon = subparsers.add_parser("abandon")
    _add_phase_arguments(abandon)
    finish = subparsers.add_parser("finish")
    finish.add_argument("--plan", type=Path, required=True)
    finish.add_argument("--repo", type=Path)
    finish.add_argument("--no-push", action="store_true")
    args = parser.parse_args(argv)

    try:
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
