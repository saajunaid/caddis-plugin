"""The checkpoint tier of /caddis:handoff: a cheap mid-phase handoff in two calls.

PREPARE (`checkpoint --session-id <id> [--name <ws>] [--plan <path> --phase <id>]`) reads the relay hash
BEFORE the model composes the new relay, and prints the exact FINISH command. FINISH (`--relay-file` given)
writes the relay with `put --require-status --expected-hash`, so a peer's change made in between is never
overwritten, runs the cheap checklist rows, and prints the resume block as its last output.

Every repo path (relay, session state, plan, sub-tool `--root`) is under the git top level of the cwd, resolved once
(`git rev-parse --show-toplevel`; outside a git repo, the cwd), so a checkpoint run from a subfolder writes the relay
where the next session's inject_relay hook reads it. Every sibling runs with that root as its cwd. A relative `--plan`
is relative to the root; a relative `--relay-file` is relative to the cwd.

Refusals (exit 1): a headless session (`CADDIS_HEADLESS`), the coordinator's relay, a coordinator check that
cannot run or cannot be read (the safe side is to refuse), FINISH without `--idle`, a failed relay write, and a
relay over the 4,000-character budget. After the relay is written, a late error (no resume block, an exception)
exits 1 with the last line `ERROR after relay write: ...`; FINISH still prints the resume block when it can. Any
other internal error exits 1 with `CHECKPOINT: internal error: ...` on stderr. In a shared checkout the checkpoint changes
no tracked file (the Tracker row is skipped; card state goes in the local relay). Siblings run as subprocesses
with `sys.executable`, found in this script's dir, then `<dir>/../claude-harness/scripts` (source tree).
A missing sibling degrades open (`skipped: <script> not installed`), except the relay write, the coordinator
check and the resume block.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

BUDGET = 4000
HEADLESS_VALUES = {"1", "true", "yes", "on"}
ROWS = ("knowledge-transfer", "plan-tracker", "relay", "tasks-file", "kb-index", "violations-report",
        "usage-record", "tidy-apply", "state-prune", "prune-list", "handover-check", "own-cleanup")
CHECKPOINT_TIER_ROWS = ("kb-index", "violations-report", "tidy-apply", "state-prune", "prune-list", "own-cleanup")
SHARED_SKIP = "skipped: shared checkout (card state is in the relay)"
_HERE = Path(__file__).resolve().parent


def _sibling(name: str) -> Path | None:
    for folder in (_HERE, _HERE.parent / "claude-harness" / "scripts"):
        path = folder / name
        if path.is_file():
            return path
    return None


def _run(root: Path, script: str, *args: str) -> subprocess.CompletedProcess | None:
    """Run a sibling script in `root`; None when it is not installed. Never `python -I` (siblings import siblings)."""
    path = _sibling(script)
    if path is None:
        return None
    return subprocess.run([sys.executable, str(path), *args], cwd=root, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _output(res: subprocess.CompletedProcess) -> str:
    return ((res.stdout or "") + (res.stderr or "")).strip()


def _headless() -> bool:
    return os.environ.get("CADDIS_HEADLESS", "").strip().lower() in HEADLESS_VALUES


def _git(cwd: Path, *args: str) -> str | None:
    try:
        res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, encoding="utf-8",
                             errors="replace")
    except OSError:
        return None
    return res.stdout.strip() if res.returncode == 0 else None


def _repo_root() -> Path:
    """The git top level of the cwd (a worktree's own folder in a worktree), else the cwd. inject_relay.py reads the
    relay at the same place, so a checkpoint from a subfolder lands where the next session looks."""
    cwd = Path.cwd()
    top = _git(cwd, "rev-parse", "--show-toplevel")
    return Path(top) if top else cwd


def _plan_path(root: Path, plan: str) -> Path:
    path = Path(plan)
    return path if path.is_absolute() else root / path


def _resolve_name(args: argparse.Namespace) -> str | None:
    if args.name:
        return args.name
    root = args.root
    extra = ["--plan", Path(args.plan).stem] if args.plan else []
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if not extra and branch and branch != "HEAD":
        # On the default branch there is no workstream name: without --default-branch the resolver names it `branch.main`.
        head = _git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD") or ""
        extra = ["--branch", branch, "--default-branch", head.split("/", 1)[-1] if head else "main"]
    res = _run(root, "caddis_workstreams.py", "resolve", *extra)
    if res is None or res.returncode != 0:
        return None
    return res.stdout.strip() or None


_NO_COORDINATOR = "no coordinator config"


def _coordinator_relay(root: Path) -> tuple[bool, str | None]:
    """(known, relay). known is False when the check cannot run or its answer cannot be read."""
    res = _run(root, "caddis_coordinate.py", "config", "show", "--path", str(root), "--json")
    if res is None:
        return False, "caddis_coordinate.py not installed"
    if res.returncode != 0:
        out = _output(res)
        if _NO_COORDINATOR in out:
            return True, None
        return False, out[:200] or f"exit {res.returncode}"
    try:
        data = json.loads(res.stdout)
    except ValueError:
        return False, "config show did not print JSON"
    if not isinstance(data, dict):
        return False, "config show did not print a JSON object"
    relay = data.get("relay")
    return True, relay if isinstance(relay, str) else None


def _own_files(root: Path, session_id: str) -> list[str]:
    """The `## Files changed this session` list of the session state file (handoff Step 0, point 1)."""
    path = root / ".caddis" / "session-state" / f"{session_id}.md"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return []
    out, inside = [], False
    for line in lines:
        if line.startswith("## "):
            inside = line.strip() == "## Files changed this session"
        elif inside and line.strip().startswith("- "):
            out.append(line.strip())
    return out


def _shared(root: Path, session_id: str) -> str:
    """`no`, `yes <reason>`, or `unknown (<why>)`. FINISH treats anything but `no` as shared."""
    fd, tmp = tempfile.mkstemp(prefix="caddis-own-files-", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(_own_files(root, session_id)) + "\n")
        res = _run(root, "caddis_checkout_guard.py", "shared", "--root", str(root), "--own-files", tmp)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    if res is None:
        return "unknown (caddis_checkout_guard.py not installed)"
    for line in res.stdout.splitlines():
        if line.startswith("SHARED: "):
            return line[len("SHARED: "):].strip()
    return "unknown (" + (_output(res)[:200] or "no answer") + ")"


def _tasks_file(root: Path, session_id: str, name: str) -> tuple[str, str]:
    """Run `session_state.py tasks-file`; return (row status, tasks line text)."""
    res = _run(root, "session_state.py", "tasks-file", "--session-id", session_id, "--relay", name,
               "--root", str(root))
    if res is None:
        status = "skipped: session_state.py not installed"
    elif res.returncode != 0:
        status = "failed: " + (_output(res)[:200] or f"exit {res.returncode}")
    else:
        status = "done"
    rel = f".caddis/relay/{name}.tasks.md"  # printed repo-relative, checked under the root
    if (root / rel).is_file():
        return status, f"{rel} (put this line in the resume prompt: Load every row of {rel} with TaskCreate.)"
    return status, "none"


def _refusals(root: Path, name: str) -> int | None:
    if _headless():
        print("CHECKPOINT: refused headless: return BLOCKED with your state")
        return 1
    known, relay = _coordinator_relay(root)
    if not known:
        print(f"CHECKPOINT: cannot tell if {name} is the coordinator relay ({relay}): run /caddis:handoff")
        return 1
    if name == relay:
        print("CHECKPOINT: coordinator: run /caddis:handoff")
        return 1
    return None


def prepare(args: argparse.Namespace) -> int:
    if _headless():
        print("CHECKPOINT: refused headless: return BLOCKED with your state")
        return 1
    name = _resolve_name(args)
    if not name:
        print("CHECKPOINT: no workstream name: pass --name <ws>")
        return 1
    root = args.root
    refused = _refusals(root, name)
    if refused is not None:
        return refused
    hashed = _run(root, "caddis_workstreams.py", "hash", name, "--root", str(root))
    if hashed is None or hashed.returncode != 0:
        why = "caddis_workstreams.py not installed" if hashed is None else _output(hashed)[:200]
        print(f"CHECKPOINT: cannot read the relay hash: {why}")
        return 1
    digest = hashed.stdout.strip() or "none"
    shared = _shared(root, args.session_id)
    _status, tasks = _tasks_file(root, args.session_id, name)
    plan = f" --plan {args.plan} --phase {args.phase}" if args.plan and args.phase else ""
    print(f"workstream: {name}")
    print(f"relay: .caddis/relay/{name}.md")
    print(f"hash: {digest}")
    print(f"shared: {shared}")
    print(f"tasks: {tasks}")
    print(f"budget: {BUDGET}")
    print("format: the relay file needs frontmatter (type: relay, workstream, branch, plan, session_id, generated.at), a `## Resume prompt` section with one fenced block, and a last line `STATUS: CONTINUE` (or OWNER-GATE, BLOCKED, FAILED)")
    print(f'next: python "{Path(__file__).resolve()}" checkpoint --session-id {args.session_id} --name {name} '
          f"--relay-file <tmp> --expected-hash {digest} --kt <done|skipped:reason> --idle{plan}")
    return 0


def _tracker_row(root: Path, plan: str | None, phase: str | None, shared: str) -> str:
    if shared != "no":
        return SHARED_SKIP
    if not plan or not phase:
        return "skipped: no --plan and --phase"
    try:
        lines = _plan_path(root, plan).read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError) as exc:
        return f"failed: cannot read {plan}: {exc}"
    pattern = re.compile(rf"^(phase\s+)?{re.escape(phase)}(\s|$)", re.IGNORECASE)
    inside = False
    for line in lines:
        if line.startswith("## "):
            inside = line.strip().lower().startswith("## tracker")
        elif inside and line.lstrip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells and pattern.match(cells[0]):
                if "in progress" in line.lower():
                    return "done"
                return f"failed: the Tracker row for phase {phase} does not say in progress"
    return f"failed: no Tracker row for phase {phase} in {plan}"


def _kt_row(kt: str | None) -> str:
    if kt == "done":
        return "done"
    if kt and kt.startswith("skipped:"):
        return kt if kt.startswith("skipped: ") else "skipped: " + kt[len("skipped:"):].strip()
    return "failed: --kt must be done or skipped:<reason>"


def _checklist(rows: dict[str, str]) -> None:
    print("=== CHECKPOINT CHECKLIST ===")
    for i, name in enumerate(ROWS, start=1):
        print(f"{i:>2} {name:<18} {rows.get(name, 'skipped: not run')}")


def finish(args: argparse.Namespace) -> int:
    if _headless():
        print("CHECKPOINT: refused headless: return BLOCKED with your state")
        return 1
    if not args.idle:
        print("CHECKPOINT: wait until no agent or background command runs")
        return 1
    if not args.name or not args.expected_hash:
        print("CHECKPOINT: finish needs --name and --expected-hash (run prepare first)")
        return 1
    root = args.root
    refused = _refusals(root, args.name)
    if refused is not None:
        return refused
    name, rows = args.name, {}
    try:
        rows["knowledge-transfer"] = _kt_row(args.kt)
        rows["plan-tracker"] = _tracker_row(root, args.plan, args.phase, _shared(root, args.session_id))

        # `put` accepts `none` (lower case) or a lower-case SHA-256 hex digest.
        expected = args.expected_hash.strip().lower()
        # The sibling runs in the root: a relative --relay-file is made absolute against the caller's cwd first.
        put = _run(root, "caddis_workstreams.py", "put", name, os.path.abspath(args.relay_file), "--require-status",
                   "--expected-hash", expected, "--session-id", args.session_id, "--root", str(root))
    except Exception as exc:  # no traceback: the next step must be a clear line, and nothing was written
        print(f"CHECKPOINT: error before the relay write: {type(exc).__name__}: {exc}; the relay was not written")
        return 1
    if put is None or put.returncode != 0:
        print(_output(put) if put is not None else "caddis_workstreams.py not installed")
        print("CHECKPOINT: row 3 relay failed: the relay was not written; nothing after it ran")
        return 1
    print(f"relay written: .caddis/relay/{name}.md")
    state = {"resume": False}
    try:
        return _after_put(args, name, rows, state)
    except Exception as exc:  # the relay is written: never exit 0 without the resume text
        if not state["resume"]:
            try:
                _resume_block(root, name, args.session_id, state)
            except Exception:
                pass
        _late_error(f"{type(exc).__name__}: {exc}")
        return 1


def _late_error(reason: str) -> None:
    print(f"ERROR after relay write: {reason}; the relay IS written, resume with the printed relay path")


def _resume_block(root: Path, name: str, session_id: str, state: dict) -> str | None:
    """Print the resume block; return None when printed, else the reason it could not be built."""
    block = _run(root, "caddis_fleet.py", "resume-block", "--name", name, "--session-id", session_id,
                 "--root", str(root))
    if block is None:
        return "caddis_fleet.py not installed, no resume block"
    sys.stdout.write(block.stdout)
    if block.returncode != 0:
        sys.stdout.write(block.stderr)
        return "resume-block failed: " + ((block.stderr or "").strip()[:200] or f"exit {block.returncode}")
    state["resume"] = "=== RESUME ===" in block.stdout
    return None


def _after_put(args: argparse.Namespace, name: str, rows: dict[str, str], state: dict) -> int:
    root = args.root
    rows["relay"] = "done"
    index = _run(root, "caddis_workstreams.py", "render-index", "--session-id", args.session_id, "--root", str(root))
    if index is not None and index.returncode != 0:
        rows["relay"] = "done (render-index failed: " + _output(index)[:160] + ")"

    rows["tasks-file"], _tasks = _tasks_file(root, args.session_id, name)

    gate = _run(root, "caddis_gate.py", "handover-check", "--doc", str(root / ".caddis" / "relay" / f"{name}.md"),
                "--repo-root", str(root), "--max-chars", str(BUDGET))
    if gate is None:
        rows["handover-check"] = "skipped: caddis_gate.py not installed"
    elif gate.returncode != 0:
        rows["handover-check"] = "failed: " + (_output(gate)[:200] or f"exit {gate.returncode}")
        print(_output(gate))
        _checklist(rows)
        print(f"CHECKPOINT: handover-check failed: fix .caddis/relay/{name}.md (budget {BUDGET}), then run "
              "the hash and the finish again")
        return 1
    else:
        rows["handover-check"] = "done"

    usage = _run(root, "session_state.py", "usage", "--session-id", args.session_id, "--root", str(root))
    if usage is None:
        rows["usage-record"] = "skipped: session_state.py not installed"
    elif usage.returncode != 0:
        rows["usage-record"] = "failed: " + (_output(usage)[:200] or f"exit {usage.returncode}")
    else:
        rows["usage-record"] = "done"
    for row in CHECKPOINT_TIER_ROWS:
        rows[row] = "skipped: checkpoint tier"

    if args.plan and _git(root, "status", "--porcelain", "--", str(_plan_path(root, args.plan))):
        print("plan file modified, not committed")
    _checklist(rows)
    failed = _resume_block(root, name, args.session_id, state)
    if failed is not None:
        _late_error(failed)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("checkpoint", help="prepare (no --relay-file) or finish (--relay-file) a checkpoint")
    p.add_argument("--session-id", required=True)
    p.add_argument("--name", help="workstream name (default: caddis_workstreams.py resolve)")
    p.add_argument("--plan")
    p.add_argument("--phase")
    p.add_argument("--relay-file", help="FINISH: the new relay text, written by the Write tool")
    p.add_argument("--expected-hash", help="FINISH: the hash PREPARE printed")
    p.add_argument("--kt", help="FINISH: done | skipped:<reason>")
    p.add_argument("--idle", action="store_true", help="FINISH: no agent or background command runs")
    args = parser.parse_args(argv)
    try:
        args.root = _repo_root()  # once: every path and every sibling call uses it
        return finish(args) if args.relay_file else prepare(args)
    except Exception as exc:  # documented: an internal error exits 1, with no RESUME block
        print(f"CHECKPOINT: internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
