"""Locked, local to-do lists and a read-only view of active plan work."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path

try:
    import caddis_exit
    from caddis_file_lock import atomic_write, locked_path, retry_denied
    from caddis_frontmatter import parse, split_document
    from caddis_workstreams import _artifact, _name
except ModuleNotFoundError as exc:
    if exc.name not in {"caddis_exit", "caddis_file_lock", "caddis_frontmatter", "caddis_workstreams"}:
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-harness" / "scripts"))
    import caddis_exit
    from caddis_file_lock import atomic_write, locked_path, retry_denied
    from caddis_frontmatter import parse, split_document
    from caddis_workstreams import _artifact, _name


_ITEM = re.compile(r'^- \[([ x])\] (.+?) <!-- caddis: (\{.*\}) -->$')
_PHASE = re.compile(r'^\|\s*(\d+)\s*\|', re.M)
_WORD = re.compile(r'[a-z0-9]{3,}')
_PLAN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,150}")
# Trailing status markers on phase headings: arrows/clocks (U+2300-U+27BF), emoji, VS16.
_STATUS_MARKER = re.compile("[\\s\u2300-\u27bf\U0001f300-\U0001faff\ufe0f]+$")


def _path(root: Path, workstream: str | None) -> tuple[Path, Path]:
    artifact = _artifact(root)
    name = _name(workstream) if workstream is not None else "inbox"
    folder = artifact / "todo-list"
    if folder.is_symlink() or not folder.resolve().is_relative_to(artifact.resolve()):
        raise ValueError("todo-list path escapes artifact root")
    path = folder / f"{name}.md"
    # Reads are unlocked, so refuse here as well as in locked_path. On Windows a writer replacing the file
    # makes this probe (and the read below) fail with PermissionError for an instant, so both retry.
    if retry_denied(path.is_symlink):
        raise ValueError("to-do file may not be a symlink")
    return artifact, path


def _read(path: Path, workstream: str | None) -> list[dict]:
    if not retry_denied(path.exists):
        return []
    text = retry_denied(lambda: path.read_text(encoding="utf-8"))
    header, body = split_document(text)
    name = workstream or "inbox"
    if header.get("type") != "todo" or header.get("workstream") != name or header.get("status") not in {"current", "done"}:
        raise ValueError(f"invalid to-do header: {path}")
    items = []
    for line in body.splitlines():
        if not line.strip() or line == "# To-dos":
            continue
        match = _ITEM.fullmatch(line)
        if not match:
            raise ValueError(f"invalid to-do row: {path}")
        data = json.loads(match.group(3))
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            raise ValueError(f"invalid to-do item: {path}")
        uuid.UUID(data["id"])
        if "resolves" in data:
            _resolves_path(path.parents[2], data["resolves"])
        items.append({"id": data["id"], "title": match.group(2), "done": match.group(1) == "x",
                      **{key: data[key] for key in ("resolves", "partial") if key in data}})
    if len({item["id"] for item in items}) != len(items):
        raise ValueError(f"duplicate to-do id: {path}")
    expected = "done" if workstream not in (None, "inbox") and items and all(item["done"] for item in items) else "current"
    if header["status"] != expected:
        raise ValueError(f"to-do status mismatch: {path}")
    return items


def _write(path: Path, root: Path, workstream: str | None, items: list[dict]) -> None:
    status = "done" if workstream not in (None, "inbox") and items and all(item["done"] for item in items) else "current"
    lines = ["---", "type: todo", f"status: {status}", f"workstream: {workstream or 'inbox'}",
             "---", "", "# To-dos", ""]
    for item in items:
        metadata = {"id": item["id"]}
        for key in ("resolves", "partial"):
            if key in item:
                metadata[key] = item[key]
        box = "x" if item["done"] else " "
        lines.append(f'- [{box}] {item["title"]} <!-- caddis: {json.dumps(metadata, sort_keys=True)} -->')
    atomic_write(path, "\n".join(lines) + "\n", root=root)


def _title(value: str) -> str:
    title = " ".join(value.split())
    if not title or len(title) > 300 or "<!--" in title or "-->" in title:
        raise ValueError("to-do text must be one plain line (1-300 characters)")
    return title


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


def _suggest(root: Path, title: str) -> list[str]:
    parking = _artifact(root) / "parking-lot"
    if not parking.is_dir() or parking.is_symlink():
        return []
    words = set(_WORD.findall(title.lower()))
    found = []
    for path in sorted(parking.glob("*.md")):
        if path.is_symlink() or path.name == "README.md":
            continue
        if words & set(_WORD.findall(path.stem.lower())) or path.name.lower() in title.lower():
            found.append(f"parking-lot/{path.name}")
    return found


def add(root: Path, title: str, workstream: str | None = None, *, resolves: str | None = None,
        partial: bool = False) -> dict:
    title = _title(title)
    artifact, path = _path(root, workstream)
    if partial and not resolves:
        raise ValueError("--partial requires --resolves")
    linked = f"parking-lot/{_resolves_path(root, resolves).name}" if resolves else None
    with locked_path(path, root=artifact):
        items = _read(path, workstream)
        item = {"id": str(uuid.uuid4()), "title": title, "done": False}
        if linked:
            item["resolves"] = linked
            if partial:
                item["partial"] = True
        items.append(item)
        _write(path, artifact, workstream, items)
    return item


def done(root: Path, item_id: str, workstream: str) -> dict:
    artifact, path = _path(root, workstream)
    with locked_path(path, root=artifact):
        items = _read(path, workstream)
        matches = [item for item in items if item["id"] == item_id]
        if not matches:
            raise ValueError("unknown to-do id")
        item = matches[0]
        if not item["done"]:
            item["done"] = True
            _write(path, artifact, workstream, items)
        return item


def list_items(root: Path, workstream: str | None = None) -> list[dict]:
    _, path = _path(root, workstream)
    return [item for item in _read(path, workstream) if not item["done"]]


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
                                  encoding="utf-8", errors="replace", timeout=5, check=False)
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
    One reader, so the open-work view and caddis_tidy never disagree about the same table.
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


def _plan_rows(plan: Path | None) -> list[dict]:
    if plan is None:
        return []
    text = plan.read_text(encoding="utf-8")
    table = tracker_table(text)
    if table is None:
        return []
    columns, lines = table
    rows = []
    for line in lines:
        match = _PHASE.match(line)
        if not match:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != len(columns) or _is_done(cells[columns.index("status")]):
            continue
        number = match.group(1)
        heading = re.search(rf"^### Phase {number}\s+[-—]\s+(.+)$", text, re.M)
        # Drop the heading's trailing status marker (🔲, ⏳, ✅ ...): status lives in the Tracker.
        title = _STATUS_MARKER.sub("", heading.group(1)) if heading else f"Phase {number}"
        rows.append({"id": f"phase:{number}", "kind": "phase", "title": title})
    return rows


def open_work(root: Path, workstream: str | None = None) -> list[dict]:
    rows = _plan_rows(_active_plan(root, workstream))
    for name in (None, workstream) if workstream and workstream != "inbox" else (None,):
        rows.extend({"id": item["id"], "kind": "todo", "title": item["title"],
                     **{key: item[key] for key in ("resolves", "partial") if key in item}}
                    for item in list_items(root, name))
    return rows


def _extract_completed_ids(text: str) -> set[str]:
    """Open-work ids of the done rows in a session-state file's "## Tasks" table.

    Only the marker session_state.py writes after a task's subject counts, as in
    ``| 3 | done | Fix x <!-- caddis: {"id": "..."} --> |``. A UUID that merely appears in a
    task's text is never trusted: "depends on <uuid>" must not close that other item.
    """
    ids: set[str] = set()
    in_tasks = False
    for line in text.splitlines():
        row = line.strip()
        if row.startswith("## "):
            in_tasks = row == "## Tasks"
            continue
        if not in_tasks or not row.startswith("|") or row.startswith("|---"):
            continue
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        # Status is the second cell; a "|" inside the subject only shifts later cells.
        if len(cells) < 3 or cells[1].lower() not in {"done", "completed"}:
            continue
        marker = re.search(r"<!--\s*caddis:\s*(\{.*?\})\s*-->\s*\|?$", row)
        if not marker:
            continue
        try:
            value = json.loads(marker.group(1)).get("id")
        except (ValueError, AttributeError):
            continue
        if isinstance(value, str) and value:
            ids.add(value.lower())
    return ids


def reconcile(root: Path, session_state: Path) -> list[str]:
    """Reconcile completed task rows from session-state into todo-lists.

    Marks ad-hoc todo items done by metadata ID.
    Never edits the Tracker; phase rows are ignored.
    """
    if not session_state.is_file():
        return []

    text = session_state.read_text(encoding="utf-8", errors="replace")
    completed_ids = _extract_completed_ids(text)
    if not completed_ids:
        return []

    artifact = _artifact(root)
    todo_dir = artifact / "todo-list"
    if not todo_dir.is_dir():
        return []

    reconciled: list[str] = []
    # Ignore phase rows — Tracker is never edited!
    adhoc_ids = {cid for cid in completed_ids if not cid.startswith("phase:")}
    if not adhoc_ids:
        return []

    wanted = {a.lower() for a in adhoc_ids}
    for todo_file in todo_dir.glob("*.md"):
        if todo_file.is_symlink() or not todo_file.is_file():
            continue
        workstream_name = todo_file.stem
        try:
            items = _read(todo_file, workstream_name)
        except (ValueError, OSError):
            continue  # a hand-edited file caddis cannot read; the others still reconcile
        for item in items:
            item_id = item.get("id")
            if item_id and item_id.lower() in wanted and not item.get("done"):
                done(root, item_id, workstream_name)
                reconciled.append(item_id)

    return reconciled


def main(argv: list[str] | None = None) -> int:
    # Titles carry non-ASCII text; a Windows console defaults to a legacy code page.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list")
    listing.add_argument("workstream", nargs="?")
    adding = commands.add_parser("add")
    adding.add_argument("text")
    adding.add_argument("--workstream")
    adding.add_argument("--resolves")
    adding.add_argument("--partial", action="store_true")
    finishing = commands.add_parser("done")
    finishing.add_argument("id")
    finishing.add_argument("--workstream", required=True)
    view = commands.add_parser("open-work")
    view.add_argument("--workstream")
    view.add_argument("--json", action="store_true")
    reconcile_p = commands.add_parser("reconcile")
    reconcile_p.add_argument("--session-state", type=Path, required=True)
    commands.add_parser("active-plan")
    args = parser.parse_args(argv)
    try:
        if args.command == "add":
            item = add(args.root, args.text, args.workstream, resolves=args.resolves, partial=args.partial)
            print(item["id"])
            if not args.resolves:
                for suggestion in _suggest(args.root, item["title"]):
                    print(f"Suggested parking item: {suggestion}")
        elif args.command == "done":
            item = done(args.root, args.id, args.workstream)
            if "resolves" in item:
                prefix = "Partly-Resolves-Parked" if item.get("partial") else "Resolves-Parked"
                print(f'{prefix}: {item["resolves"]}')
        elif args.command == "list":
            for item in list_items(args.root, args.workstream):
                print(f'{item["id"]} {item["title"]}')
        elif args.command == "active-plan":
            plan, candidates = active_plan(args.root)
            if plan is None:
                if candidates:
                    print("caddis-todo: several current plans; name one:", file=sys.stderr)
                    for candidate in candidates:
                        print(f"  {candidate}", file=sys.stderr)
                else:
                    print("caddis-todo: no current plan in .caddis/plans", file=sys.stderr)
                return caddis_exit.NOT_RUN
            print(plan)
        elif args.command == "reconcile":
            reconciled = reconcile(args.root, args.session_state)
            for rid in reconciled:
                print(f"Reconciled: {rid}")
        else:
            rows = open_work(args.root, args.workstream)
            if args.json:
                print(json.dumps(rows, ensure_ascii=False))
            else:
                for row in rows:
                    print(f'{row["id"]} [{row["kind"]}] {row["title"]}')
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"caddis-todo: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
