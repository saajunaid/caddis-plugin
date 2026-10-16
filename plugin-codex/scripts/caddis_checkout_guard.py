"""Protect a shared checkout from lanes writing into it, and tell handoff when a checkout is shared.

`shared` (handoff-integrity Phase 5, the design of fleet-handoff Phase 2): a checkout is shared when its root
`AGENTS.md` says `Shared checkout: yes`, or when `git status` lists a path this session did not change. In a
shared checkout handoff writes no tracked file there; it uses `caddis_docs_pr.py` instead.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

try:
    import caddis_exit
except ModuleNotFoundError as exc:
    if exc.name != "caddis_exit":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-harness" / "scripts"))
    import caddis_exit


def get_porcelain_lines(repo: Path) -> tuple[int, list[str]]:
    """Run git status --porcelain=v1 --untracked-files=all -z and parse entries."""
    proc = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain=v1", "--untracked-files=all", "-z"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        return proc.returncode, []

    raw = proc.stdout
    if not raw:
        return 0, []

    parts = raw.split("\0")
    if parts and parts[-1] == "":
        parts.pop()

    entries: list[str] = []
    idx = 0
    while idx < len(parts):
        part = parts[idx]
        # A rename or copy (X or Y is R or C) is followed by one more field: the original path.
        if ("R" in part[:2] or "C" in part[:2]) and idx + 1 < len(parts):
            orig_path = parts[idx + 1]
            entries.append(f"{part} -> {orig_path}")
            idx += 2
        else:
            entries.append(part)
            idx += 1
    return 0, entries


SHARED_RE = re.compile(r"^Shared checkout:\s*yes\b", re.IGNORECASE | re.MULTILINE)


def entry_paths(entry: str) -> list[str]:
    """The paths of one `get_porcelain_lines` entry: `XY path`, or `XY new -> orig` (both count) for a rename."""
    rest = entry[3:]
    if ("R" in entry[:2] or "C" in entry[:2]) and " -> " in rest:
        new, orig = rest.split(" -> ", 1)
        return [new, orig]
    return [rest]


def _norm(path: str) -> str:
    return path.strip().replace("\\", "/")


def is_shared_checkout(root: Path, own_files: set[str]) -> tuple[bool, str]:
    """(True, reason) when handoff must not write tracked files in `root`; else (False, "").

    `Shared checkout: no` in AGENTS.md never hides a change this session did not make. When git status cannot
    run, the checkout counts as shared: a wrong "no" could commit another session's files.
    """
    agents = Path(root) / "AGENTS.md"
    try:
        text = agents.read_text(encoding="utf-8", errors="replace") if agents.is_file() else ""
    except OSError:
        text = ""
    if SHARED_RE.search(text):
        return True, "AGENTS.md says Shared checkout: yes"
    ret, lines = get_porcelain_lines(Path(root))
    if ret != 0:
        return True, "git status failed, so changes by other sessions cannot be ruled out"
    own = {_norm(p) for p in own_files}
    foreign: list[str] = []
    for entry in lines:
        for path in entry_paths(entry):
            if _norm(path) not in own and path not in foreign:
                foreign.append(path)
    if foreign:
        return True, "changes not made by this session: " + ", ".join(foreign[:3])
    return False, ""


def read_own_files(path: Path | None) -> set[str]:
    """One path per line. The session-state list form `- `path`` is read too; blank lines are skipped.

    A missing or unreadable file gives an empty set, so every dirty path counts as foreign (the safe side).
    """
    if path is None:
        return set()
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    own: set[str] = set()
    for line in raw.splitlines():
        item = line.strip()
        if item.startswith("- "):
            item = item[2:].strip()
        if len(item) >= 2 and item.startswith("`") and item.endswith("`"):
            item = item[1:-1]
        if item:
            own.add(_norm(item))
    return own


def shared(root: Path, own_files_path: Path | None) -> int:
    """Print `SHARED: yes <reason>` or `SHARED: no`; always exit 0."""
    is_shared, reason = is_shared_checkout(root, read_own_files(own_files_path))
    print(f"SHARED: {'yes' if is_shared else 'no'} {reason}".rstrip())
    return caddis_exit.CLEAN


def snapshot(repo: Path, out_path: Path) -> int:
    """Take a snapshot of current porcelain entries."""
    ret, lines = get_porcelain_lines(repo)
    if ret != 0:
        sys.stderr.write(f"git status failed on {repo}\n")
        return caddis_exit.NOT_RUN

    data = {
        "repo": str(repo),
        "lines": lines,
    }
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        sys.stderr.write(f"failed to write snapshot to {out_path}: {exc}\n")
        return caddis_exit.NOT_RUN
    return caddis_exit.CLEAN


def compare(repo: Path, snapshot_path: Path) -> int:
    """Compare current entries to snapshot."""
    if not snapshot_path.is_file():
        sys.stderr.write(f"snapshot file not found: {snapshot_path}\n")
        return caddis_exit.NOT_RUN

    try:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("lines"), list):
            raise ValueError("no 'lines' list")
        snapshot_lines = set(data["lines"])
    except Exception as exc:
        sys.stderr.write(f"invalid snapshot JSON {snapshot_path}: {exc}\n")
        return caddis_exit.NOT_RUN

    ret, current_lines = get_porcelain_lines(repo)
    if ret != 0:
        sys.stderr.write(f"git status failed on {repo}\n")
        return caddis_exit.NOT_RUN

    new_entries = [entry for entry in current_lines if entry not in snapshot_lines]
    if new_entries:
        for entry in new_entries:
            print(f"NEW {entry}")
        return caddis_exit.BLOCKED
    else:
        print("checkout unchanged")
        return caddis_exit.CLEAN


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for caddis_checkout_guard."""
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(description="Shared checkout guard.")
    subparsers = parser.add_subparsers(dest="command")

    snap_parser = subparsers.add_parser("snapshot")
    snap_parser.add_argument("--repo", required=True, type=Path, help="Repository path")
    snap_parser.add_argument("--out", required=True, type=Path, help="Snapshot output path")

    cmp_parser = subparsers.add_parser("compare")
    cmp_parser.add_argument("--repo", required=True, type=Path, help="Repository path")
    cmp_parser.add_argument("--snapshot", required=True, type=Path, help="Snapshot file path")

    shared_parser = subparsers.add_parser("shared", help="print SHARED: yes|no <reason> for handoff")
    shared_parser.add_argument("--root", required=True, type=Path, help="Repository root")
    shared_parser.add_argument("--own-files", type=Path, default=None,
                               help="File with one path per line: the files this session changed")

    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return caddis_exit.NOT_RUN

    if args.command == "snapshot":
        return snapshot(args.repo, args.out)
    elif args.command == "compare":
        return compare(args.repo, args.snapshot)
    elif args.command == "shared":
        return shared(args.root, args.own_files)
    else:
        parser.print_help(sys.stderr)
        return caddis_exit.NOT_RUN


if __name__ == "__main__":
    sys.exit(main())
