"""The active plan and the plan Tracker reader, for commands, tidy and the gates.

3-store model (owner decision, 21 Oct 2026): the session task list (`.caddis/relay/<name>.tasks.md`), the
parking lot and the roadmap with the plan Tracker. The `.caddis/todo-list/` store and the open-work view
are retired, with the `add`, `done`, `list` and `open-work` sub-commands. `reconcile` stays one more
release as a no-op, because an older /handoff still calls it from its Step 6.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import caddis_exit
    from caddis_frontmatter import parse
    from caddis_workstreams import _artifact, _name
except ModuleNotFoundError as exc:
    if exc.name not in {"caddis_exit", "caddis_file_lock", "caddis_frontmatter", "caddis_workstreams"}:
        raise
    # caddis_tidy imports caddis_file_lock after this module: these two folders stay on the path.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-harness" / "scripts"))
    import caddis_exit
    from caddis_frontmatter import parse
    from caddis_workstreams import _artifact, _name


# No child process opens a console window on Windows (this runs under hooks and status lines that
# have no console). Inline, not scripts/no_window.py: in the source tree this file does not sit beside it.
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

_PHASE = re.compile(r'^\|\s*(\d+)\s*\|', re.M)
_PLAN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,150}")
RECONCILE_RETIRED = "caddis_todo: reconcile is retired (3-store model); nothing to do"


def _resolves_path(root: Path, value: str) -> Path:
    if not isinstance(value, str):
        raise ValueError("resolves must name a parking-lot file")
    name = value.removeprefix("parking-lot/")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*\.md", name) or ".." in name:
        raise ValueError("resolves must name a flat parking-lot .md file")
    parking = _artifact(root) / "parking-lot"
    target = parking / name
    if parking.is_symlink() or target.is_symlink() or not target.is_file() or not target.resolve().is_relative_to(parking.resolve()):
        raise ValueError("unknown parking-lot file")
    if parse(target.read_text(encoding="utf-8")).get("type") != "parking-lot":
        raise ValueError("target is not a parking-lot item")
    return target


def _is_done(status: str) -> bool:
    """A Tracker status cell that means done: "done", "done (note)" or a leading check mark.
    A cell that says work is still pending is not done (owner decision 2026-09-27)."""
    lowered = status.strip().lower()
    first = lowered.split(" ", 1)[0] if lowered else ""
    if "pending" in lowered:
        return False
    return first in {"done", "✅"} or first.startswith("✅")


def _active_plan(root: Path, workstream: str | None) -> Path | None:
    artifact = _artifact(root)
    plans_dir = artifact / "plans"
    if plans_dir.is_symlink() or not plans_dir.is_dir():
        return None
    if workstream:
        relay = artifact / "relay" / f"{_name(workstream)}.md"
        if relay.is_file() and not relay.is_symlink():
            named = parse(relay.read_text(encoding="utf-8")).get("plan")
            if isinstance(named, str) and named:
                # Only a bare file name inside plans/: a relay cannot point the view elsewhere.
                stem = Path(named.replace("\\", "/")).name.removesuffix(".md")
                if _PLAN_NAME.fullmatch(stem):
                    candidate = plans_dir / f"{stem}.md"
                    if candidate.is_file() and not candidate.is_symlink():
                        return candidate
    plans = _current_plans(plans_dir)
    if workstream:
        matches = [p for p in plans if parse(p.read_text(encoding="utf-8")).get("feature") == workstream]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:  # ambiguous by name: never guess further
            return None
    elif len(plans) == 1:
        return plans[0]
    # Several current plans and no name match: the one this branch has changed is the active
    # one. Without this, the first session on a branch (no relay yet) could never seed. Only
    # for no name or a branch-derived name: a named plan workstream must not borrow another plan.
    if workstream and not workstream.startswith("branch."):
        return None
    touched = _plans_changed_on_branch(root, plans)
    return touched[0] if len(touched) == 1 else None


def _current_plans(plans_dir: Path) -> list[Path]:
    return sorted(p for p in plans_dir.glob("*.md") if not p.is_symlink()
                  and parse(p.read_text(encoding="utf-8")).get("status") == "current")


def active_plan(root: Path) -> tuple[str | None, list[str]]:
    """The active plan as a repo-relative POSIX path, else None and the candidates."""
    base = Path(root).resolve()

    def relative(path: Path) -> str:
        return path.resolve().relative_to(base).as_posix()

    try:
        plan = _active_plan(root, None)
        if plan is not None:
            return relative(plan), []
        plans_dir = _artifact(root) / "plans"
        if plans_dir.is_symlink() or not plans_dir.is_dir():
            return None, []
        return None, [relative(p) for p in _current_plans(plans_dir)]
    except ValueError:  # a plan that resolves outside the repo (e.g. a symlinked .caddis)
        return None, []


def _plans_changed_on_branch(root: Path, plans: list[Path]) -> list[Path]:
    """Current plans with commits between the default branch and HEAD; [] when unknown."""
    def git(*args: str) -> str | None:
        try:
            done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=5, check=False,
                                  creationflags=_NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    # The remote's own default branch first; the fixed names only when origin/HEAD is unset.
    remote_default = git("symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    # Local names before remote-tracking ones: an unfetched origin/main is older than main,
    # and base..HEAD would then count plans that main already has.
    local_default = remote_default.split("/", 1)[1] if remote_default and "/" in remote_default else ""
    guesses = tuple(name for name in (local_default, remote_default) if name) + (
        "main", "master", "trunk", "develop", "origin/main", "origin/master", "origin/trunk", "origin/develop")
    base = next((b for b in guesses if git("merge-base", "HEAD", b)), None)
    if base is None:
        return []
    changed = git("log", "--name-only", "--format=", f"{base}..HEAD", "--", ".caddis/plans")
    if not changed:
        return []
    names = {Path(line).name for line in changed.splitlines() if line.strip()}
    return [p for p in plans if p.name in names]


def tracker_table(text: str) -> tuple[list[str], list[str]] | None:
    """The plan's `## Tracker` table: its lower-cased header columns and its other lines.

    None when there is no Tracker heading line, no `| Phase |` header or no Status column. The
    lines are every line of the section except the header; callers pick the rows they trust.
    One reader, so caddis_tidy and any later caller never disagree about the same table.
    """
    # A real heading line only: plan prose may mention "## Tracker" inline before the section.
    heading = re.search(r"^## Tracker\b.*$", text, re.M)
    if heading is None:
        return None
    section = text[heading.end():].split("\n## ", 1)[0]
    table = section.splitlines()
    at = next((i for i, line in enumerate(table) if re.match(r"\|\s*Phase\s*\|", line)), None)
    if at is None:
        return None
    columns = [cell.strip().lower() for cell in table[at].strip("|").split("|")]
    if "status" not in columns:
        return None
    return columns, table[:at] + table[at + 1:]


def main(argv: list[str] | None = None) -> int:
    # Plan paths may carry non-ASCII text; a Windows console defaults to a legacy code page.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path.cwd(), help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("active-plan")
    # Retired: kept one release so an older /handoff Step 6 does not fail. Takes its old flag, ignores it.
    reconcile_p = commands.add_parser("reconcile", help=argparse.SUPPRESS)
    reconcile_p.add_argument("--session-state", type=Path)
    args, extra = parser.parse_known_args(argv)
    if extra and args.command != "reconcile":
        parser.error(f"unrecognized arguments: {' '.join(extra)}")  # only the retired no-op tolerates old flags
    if args.command == "reconcile":
        print(RECONCILE_RETIRED)
        return 0
    try:
        plan, candidates = active_plan(args.root)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"caddis-todo: {exc}", file=sys.stderr)
        return 1
    if plan is None:
        if candidates:
            print("caddis-todo: several current plans; name one:", file=sys.stderr)
            for candidate in candidates:
                print(f"  {candidate}", file=sys.stderr)
        else:
            print("caddis-todo: no current plan in .caddis/plans", file=sys.stderr)
        return caddis_exit.NOT_RUN
    print(plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
