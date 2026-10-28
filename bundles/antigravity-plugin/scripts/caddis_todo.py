"""The active plan and the plan Tracker reader, for commands, tidy and the gates.

3-store model (owner decision, 21 Oct 2026): the session task list (`.caddis/relay/<name>.tasks.md`), the
parking lot and the roadmap with the plan Tracker. The `.caddis/todo-list/` store and the open-work view
are retired, with the `add`, `done`, `list` and `open-work` sub-commands. `reconcile` stays one more
release as a no-op, because an older /handoff still calls it from its Step 6.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import caddis_exit
    from caddis_frontmatter import parse, split_document
    from caddis_status import is_done, status_state
    from caddis_workstreams import _artifact, _name
except ModuleNotFoundError as exc:
    if exc.name not in {"caddis_exit", "caddis_file_lock", "caddis_frontmatter", "caddis_status",
                        "caddis_workstreams"}:
        raise
    # caddis_tidy imports caddis_file_lock after this module: these two folders stay on the path.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-harness" / "scripts"))
    import caddis_exit
    from caddis_frontmatter import parse, split_document
    from caddis_status import is_done, status_state
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
    """A Tracker status cell that means done. The vocabulary lives in caddis_status; tidy and tests call this name."""
    return is_done(status)


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
    # "## Tracker" or a numbered "## 12. Tracker" (hand-written plans number their sections).
    heading = re.search(r"^##\s+(?:\d+[.)]?\s+)?Tracker\b.*$", text, re.M)
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


def _plan_files(root: Path) -> list[Path]:
    """The plan files to list: `.caddis/plans/*.md`, else the legacy `.github/plans/*.md`. Never `done/`."""
    plans_dir = _artifact(root) / "plans"
    if not plans_dir.is_dir():
        plans_dir = Path(root) / ".github" / "plans"
    if plans_dir.is_symlink() or not plans_dir.is_dir():
        return []
    return sorted(p for p in plans_dir.glob("*.md") if p.is_file() and not p.is_symlink())


_PHASE_HEADING = re.compile(r"^(#{2,3})\s+Phase\s+([^\s:—]+)\s*[:—-]?\s*(.*)$", re.M | re.I)


def phase_key(cell: str) -> str:
    s = cell.replace("`", "").replace("*", "").strip()
    s = re.sub(r"^phase\s+", "", s, flags=re.I)
    s = re.split(r" -|[\s:—]", s, maxsplit=1)[0]
    return s.rstrip(".").lower()


def phase_sections(text: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for m in _PHASE_HEADING.finditer(text):
        key = phase_key(m.group(2))
        if key in out:
            continue
        title = m.group(3).rstrip(" \t\r\n⏳🔲✅\ufe0f").strip()
        rest = text[m.end():]
        stop = re.search(rf"^#{{1,{len(m.group(1))}}} ", rest, re.M)
        body = (rest[:stop.start()] if stop else rest).strip()
        if len(body) > 2000:
            body = body[:2000] + "…"
        out[key] = {"title": title, "text": body}
    return out


def _plan_entry(root: Path, path: Path) -> dict:
    return _plan_entry_text(path.relative_to(Path(root)).as_posix(), path.read_text(encoding="utf-8"))


def _plan_entry_text(rel: str, text: str) -> dict:
    # caddis_tidy imports this module at load time, so this module imports it only here.
    try:
        import caddis_tidy
    except ModuleNotFoundError as exc:
        if exc.name != "caddis_tidy":
            raise
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import caddis_tidy
    meta, body = split_document(text)
    if text.lstrip("﻿").startswith("---") and not meta:
        raise ValueError("frontmatter is not closed or has no keys")
    heading = re.search(r"^# (.+?)\s*$", body, re.M)
    title = heading.group(1) if heading else meta.get("title")
    tracker: list[dict] = []
    table = tracker_table(text)
    if table is not None:
        columns, lines = table
        status_at = columns.index("status")
        ms_at = columns.index("milestone") if "milestone" in columns else None
        for line in lines:
            if not line.strip().startswith("|") or caddis_tidy._TABLE_RULE_RE.match(line.strip()):
                continue
            cells = caddis_tidy._row_cells(line)
            if cells:
                cell = cells[status_at] if len(cells) > status_at else ""
                row: dict = {"phase": cells[0], "key": phase_key(cells[0])}
                if ms_at is not None:
                    row["milestone"] = cells[ms_at].strip() if len(cells) > ms_at else ""
                row["status"] = cell
                row["state"] = status_state(cell)
                tracker.append(row)
    return {"path": rel, "title": title,
            "status": meta.get("status"), "feature": meta.get("feature"),
            "phases": phase_sections(text),
            "tracker": tracker, "open_rows": sum(1 for row in tracker if not _is_done(row["status"]))}


class _Batch:
    """One `git cat-file --batch` process, asked object by object (local git only, no network)."""

    def __init__(self, root: Path):
        self.proc = subprocess.Popen(["git", "-C", str(root), "cat-file", "--batch"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)

    def get(self, name: str) -> tuple[str, str, bytes] | None:
        """(oid, type, content) of `name`, or None when git says it is missing."""
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.proc.stdin.write(name.encode("utf-8") + b"\n")
        self.proc.stdin.flush()
        header = self.proc.stdout.readline().split()
        if len(header) != 3:
            return None  # "<name> missing" (or ambiguous)
        size = int(header[2])
        content = self.proc.stdout.read(size + 1)[:size]  # the content, then one newline
        return header[0].decode("ascii"), header[1].decode("ascii"), content

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        if self.proc.stdout:
            self.proc.stdout.close()


def _tree_blobs(tree: bytes, oid_len: int) -> list[tuple[str, str]]:
    """[(name, blob oid)] from a raw tree object: `<mode> <name>\\0<oid bytes>` repeated. Files only."""
    out: list[tuple[str, str]] = []
    at = 0
    while at < len(tree):
        space = tree.index(b" ", at)
        nul = tree.index(b"\0", space)
        mode, name = tree[at:space], tree[space + 1:nul].decode("utf-8", errors="replace")
        oid = tree[nul + 1:nul + 1 + oid_len].hex()
        at = nul + 1 + oid_len
        if mode in (b"100644", b"100755"):
            out.append((name, oid))
    return out


def _origin_plan_texts(root: Path, branch: str) -> tuple[str, int | None, list[tuple[str, str]]] | None:
    """(commit_oid, commit_at, [(path, text)]) of the plan files on origin/<branch>: `.caddis/plans/*.md`, else
    `.github/plans/*.md`, never `done/`. One git process for the whole read. None when git cannot read the ref."""
    try:
        batch = _Batch(root)
    except OSError:
        return None
    try:
        commit_obj = batch.get(f"refs/remotes/origin/{branch}")
        if commit_obj is None:
            return None
        commit_oid = commit_obj[0]
        commit_at: int | None = None
        for line in commit_obj[2].decode("utf-8", errors="replace").splitlines():
            if not line:
                break
            if line.startswith("committer "):
                try:
                    commit_at = int(line.split()[-2])
                except (IndexError, ValueError):
                    commit_at = None
        for folder in (".caddis/plans", ".github/plans"):
            tree = batch.get(f"refs/remotes/origin/{branch}:{folder}")
            if tree is None or tree[1] != "tree":
                continue
            names = sorted((name, oid) for name, oid in _tree_blobs(tree[2], len(tree[0]) // 2) if name.endswith(".md"))
            if not names:
                continue
            texts: list[tuple[str, str]] = []
            for name, oid in names:
                blob = batch.get(oid)
                if blob is None:
                    return None
                texts.append((f"{folder}/{name}", blob[2].decode("utf-8", errors="replace").replace("\r\n", "\n")))
            return commit_oid, commit_at, texts
        return commit_oid, commit_at, []
    except (OSError, ValueError):
        return None
    finally:
        batch.close()


# How far back the hub looks for a plan's last change. An older plan gets no time and sorts last.
_CHANGED_SINCE = "400.days"


def _origin_plan_times(root: Path, branch: str, folder: str) -> dict[str, int]:
    """{path: commit time} of the last commit on origin/<branch> that touched each plan file in `folder`.
    One local git process (no network). Empty when git fails: the time is a sort hint, never required."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "-c", "core.quotepath=off", "log", f"--since={_CHANGED_SINCE}",
             "--format=%x00%ct", "--name-only", f"refs/remotes/origin/{branch}", "--", folder],
            capture_output=True, timeout=30, creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if out.returncode != 0:
        return {}
    times: dict[str, int] = {}
    for chunk in out.stdout.decode("utf-8", errors="replace").split("\x00")[1:]:
        lines = chunk.strip().splitlines()
        try:
            when = int(lines[0])
        except (ValueError, IndexError):
            continue
        for name in lines[1:]:
            times.setdefault(name.strip(), when)  # git log is newest first: the first time seen is the last change
    return times


def _file_time(path: Path) -> int | None:
    try:
        return int(path.stat().st_mtime)
    except OSError:
        return None


def _entry_or_error(rel: str, read) -> dict:
    try:
        return read()
    except Exception as exc:  # one bad file must not hide the others
        return {"path": rel, "error": (str(exc).splitlines() or [type(exc).__name__])[0]}


def plans_json(root: Path, branch: str | None = None) -> dict:
    """Every current plan as data: `{"schema": 1, "source": ..., "plans": [...]}`. Never prints, never exits.

    With `branch`, read the plans from the local `origin/<branch>` ref (the hub: a pushed Tracker edit shows with
    no pull); when git cannot read that ref, read the working tree. `source` names which one was read. A file that
    does not parse gives `{"path", "error"}`; the other plans still come back.
    """
    root = Path(root)
    origin = _origin_plan_texts(root, branch) if branch else None
    if origin is not None:
        commit, commit_at, texts = origin
        plans = [_entry_or_error(rel, lambda rel=rel, text=text: _plan_entry_text(rel, text)) for rel, text in texts]
        times = _origin_plan_times(root, branch, texts[0][0].rsplit("/", 1)[0]) if texts else {}
        for plan in plans:
            if "error" not in plan:
                plan["changed_at"] = times.get(plan["path"])
        return {"schema": 1, "source": f"origin/{branch}", "commit": commit[:12], "commit_at": commit_at, "plans": plans}
    plans = []
    for path in _plan_files(root):
        plan = _entry_or_error(path.relative_to(root).as_posix(), lambda path=path: _plan_entry(root, path))
        if "error" not in plan:
            plan["changed_at"] = _file_time(path)
        plans.append(plan)
    return {"schema": 1, "source": "working-tree", "plans": plans}


def main(argv: list[str] | None = None) -> int:
    # Plan paths may carry non-ASCII text; a Windows console defaults to a legacy code page.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path.cwd(), help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("active-plan")
    plans_p = commands.add_parser("plans", help="list the plans as JSON")
    plans_p.add_argument("--json", action="store_true", dest="as_json")
    # `plans --root R` works too. SUPPRESS: when absent here, the global --root (or cwd) stays.
    plans_p.add_argument("--root", type=Path, default=argparse.SUPPRESS, help="the project folder")
    # Retired: kept one release so an older /handoff Step 6 does not fail. Takes its old flag, ignores it.
    reconcile_p = commands.add_parser("reconcile", help=argparse.SUPPRESS)
    reconcile_p.add_argument("--session-state", type=Path)
    args, extra = parser.parse_known_args(argv)
    if extra and args.command != "reconcile":
        parser.error(f"unrecognized arguments: {' '.join(extra)}")  # only the retired no-op tolerates old flags
    if args.command == "reconcile":
        print(RECONCILE_RETIRED)
        return 0
    if args.command == "plans":
        if not args.as_json:
            parser.error("plans needs --json")
        try:
            print(json.dumps(plans_json(args.root), ensure_ascii=False))
        except (OSError, ValueError) as exc:  # a .caddis that escapes the project
            print(f"caddis-todo: {exc}", file=sys.stderr)
            return 1
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
