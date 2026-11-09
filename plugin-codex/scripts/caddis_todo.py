"""The active plan and the plan Tracker reader, for commands, tidy and the gates.

3-store model (owner decision, 21 Oct 2026): the session task list (`.caddis/relay/<name>.tasks.md`), the
parking lot and the roadmap with the plan Tracker. The `.caddis/todo-list/` store and the open-work view
are retired, with the `add`, `done`, `list` and `open-work` sub-commands. `reconcile` stays one more
release as a no-op, because an older /handoff still calls it from its Step 6.
"""

from __future__ import annotations

import argparse
import copy
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


PLAN_STATUS_RANK: dict[str, int] = {"draft": 0, "proposed": 0, "ready": 0, "current": 1, "done": 2, "superseded": 2}


def _status_rank(status: object) -> int:
    return PLAN_STATUS_RANK.get(status, 0) if isinstance(status, str) else 0


def pick_pr(cands: list[dict]) -> tuple[dict, list[int]]:
    """D6: the PR with the newest `updated_at` (ISO text compare; tie: higher number) and the others' numbers."""
    best = max(cands, key=lambda pr: (pr["updated_at"], pr["number"]))
    return best, sorted(pr["number"] for pr in cands if pr is not best)


def _first_by_key(rows: list[dict]) -> dict[str, dict]:
    """D4.6: the first row with each non-empty key."""
    out: dict[str, dict] = {}
    for row in rows:
        if row["key"] and row["key"] not in out:
            out[row["key"]] = row
    return out


def overlay_plan(main: dict | None, base: dict | None, head: dict, pr: dict, also: list[int]) -> dict:
    """One plan with an open PR branch laid over main: rows by D4, plan status by D5. Inputs are never changed."""
    overlay = {"pr": pr["number"], "draft": bool(pr.get("draft")), "head_ref": pr["head_ref"], "also": list(also)}
    if main is None:  # D5: a plan only on the branch takes every field from the head entry
        out = copy.deepcopy(head)
        out["tracker"] = [{**row, "source": "branch"} for row in out["tracker"]]
        out["changed_at"] = None
    else:
        out = copy.deepcopy(main)
        heads = _first_by_key(head["tracker"])
        bases = _first_by_key(base["tracker"]) if base is not None else {}

        def untouched(h: dict) -> bool:  # D4.2 / D4.4: the branch left the row as it was at the merge base
            b = bases.get(h["key"])
            return b is not None and h["status"] == b["status"]

        tracker: list[dict] = []
        matched: set[str] = set()
        for m in out["tracker"]:
            h = heads.get(m["key"]) if m["key"] and m["key"] not in matched else None
            if m["key"]:
                matched.add(m["key"])
            if h is None or untouched(h):  # D4.1, D4.2 (and D4.5: an empty key is kept)
                tracker.append({**m, "source": "main"})
            elif m["state"] in ("done", "moved") and h["state"] not in ("done", "moved"):  # D4.3: done never goes back
                tracker.append({**m, "source": "main"})
            else:
                tracker.append({**copy.deepcopy(h), "source": "branch"})
        for key, h in heads.items():  # D4.4: dict order is head order
            if key not in matched and not untouched(h):
                tracker.append({**copy.deepcopy(h), "source": "branch"})
        out["tracker"] = tracker
        base_status = base.get("status") if base is not None else None
        if (base is None or head.get("status") != base_status) and _status_rank(main.get("status")) != 2:
            out["status"] = head.get("status")
    out["open_rows"] = sum(1 for row in out["tracker"] if not _is_done(row["status"]))
    out["overlay"] = overlay
    return out


class _Batch:
    """One `git cat-file --batch` process, asked object by object (local git only, no network)."""

    def __init__(self, root: Path):
        self.proc = subprocess.Popen(["git", "-C", str(root), "cat-file", "--batch"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)

    def get(self, name: str) -> tuple[str, str, bytes] | None:
        """(oid, type, content) of `name`, or None when git says it is missing."""
        assert self.proc.stdin is not None and self.proc.stdout is not None
        try:
            self.proc.stdin.write(name.encode("utf-8") + b"\n")
            self.proc.stdin.flush()
        except OSError:  # git already exited (not a repo): its stdin is closed, so the object is missing
            return None
        header = self.proc.stdout.readline().split()
        if len(header) != 3:
            return None  # "<name> missing" (or ambiguous)
        size = int(header[2])
        content = self.proc.stdout.read(size + 1)[:size]  # the content, then one newline
        return header[0].decode("ascii"), header[1].decode("ascii"), content

    def close(self) -> None:
        if self.proc.stdin:
            try:
                self.proc.stdin.close()
            except OSError:  # a failed write left bytes that cannot reach an exited git
                pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        if self.proc.stdout:
            self.proc.stdout.close()


def _tree_entries(tree: bytes, oid_len: int) -> list[tuple[bytes, str, str]]:
    """[(mode, name, oid)] from a raw tree object: `<mode> <name>\\0<oid bytes>` repeated."""
    out: list[tuple[bytes, str, str]] = []
    at = 0
    while at < len(tree):
        space = tree.index(b" ", at)
        nul = tree.index(b"\0", space)
        mode, name = tree[at:space], tree[space + 1:nul].decode("utf-8", errors="replace")
        out.append((mode, name, tree[nul + 1:nul + 1 + oid_len].hex()))
        at = nul + 1 + oid_len
    return out


def _tree_blobs(tree: bytes, oid_len: int) -> list[tuple[str, str]]:
    """[(name, blob oid)] from a raw tree object. Files only."""
    return [(name, oid) for mode, name, oid in _tree_entries(tree, oid_len) if mode in (b"100644", b"100755")]


def _origin_plan_texts(root: Path, branch: str
                       ) -> tuple[str, int | None, list[tuple[str, str]], str | None] | None:
    """(commit_oid, commit_at, [(path, text)], done_tree) of the plan files on origin/<branch>: `.caddis/plans/*.md`,
    else `.github/plans/*.md`, never `done/`. `done_tree` is the oid of `<folder>/done` for the folder that held the
    plans (`.caddis/plans` when none did), read from the folder's tree object, or None when there is no such tree.
    One git process for the whole read. None when git cannot read the ref."""
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
        default_done: str | None = None  # the done tree of `.caddis/plans` when no folder holds a current plan
        for folder in (_PLANS_DIR, ".github/plans"):
            tree = batch.get(f"refs/remotes/origin/{branch}:{folder}")
            if tree is None or tree[1] != "tree":
                continue
            entries = _tree_entries(tree[2], len(tree[0]) // 2)
            done_tree = next((oid for mode, name, oid in entries if name == "done" and mode == b"40000"), None)
            names = sorted((name, oid) for mode, name, oid in entries
                           if mode in (b"100644", b"100755") and name.endswith(".md"))
            if not names:
                if folder == _PLANS_DIR:
                    default_done = done_tree
                continue
            texts: list[tuple[str, str]] = []
            for name, oid in names:
                blob = batch.get(oid)
                if blob is None:
                    return None
                texts.append((f"{folder}/{name}", blob[2].decode("utf-8", errors="replace").replace("\r\n", "\n")))
            return commit_oid, commit_at, texts, done_tree
        return commit_oid, commit_at, [], default_done
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


_PR_SUFFIX = re.compile(r"\(#(\d+)\)")
_PR_MERGE = re.compile(r"\bMerge pull request #(\d+)\b")
_TITLE_SUFFIX = re.compile(r"\s+[—–-]+\s*Implementation Plan\s*$", re.I)


def pr_of_subject(subject: str) -> int | None:
    """D3: the PR a commit subject names: the last `(#n)` (squash and Gitea merges), else `Merge pull request #n`."""
    found = _PR_SUFFIX.findall(subject)
    if found:
        return int(found[-1])
    merge = _PR_MERGE.search(subject)
    return int(merge.group(1)) if merge else None


def done_entry(rel: str, text: str, closed_at: int | None, pr: int | None) -> dict:
    """D5: one done-plan row. Title from the first `# ` heading less ` — Implementation Plan`; phases = Tracker
    rows, else unique `Phase` headings."""
    entry = _plan_entry_text(rel, text)
    title = entry["title"] if isinstance(entry["title"], str) and entry["title"].strip() else None
    title = (_TITLE_SUFFIX.sub("", title).strip() if title else "") or rel.rsplit("/", 1)[-1].removesuffix(".md")
    return {"path": rel, "title": title, "closed_at": closed_at,
            "phases": len(entry["tracker"]) or len(entry["phases"]), "pr": pr}


def _origin_done_adds(root: Path, branch: str, folder: str) -> dict[str, tuple[int, int | None]]:
    """{path: (commit time, PR)} of the newest first-parent commit on origin/<branch> that ADDED each file under
    `<folder>/done` (D3). One local git process. Empty when git fails: the date is shown as unknown."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "-c", "core.quotepath=off", "log", "--no-renames", "--first-parent",
             "--diff-merges=first-parent", "--diff-filter=A", "--format=%x00%ct%x09%s", "--name-only",
             f"refs/remotes/origin/{branch}", "--", f"{folder}/done"],
            capture_output=True, timeout=30, creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if out.returncode != 0:
        return {}
    adds: dict[str, tuple[int, int | None]] = {}
    for chunk in out.stdout.decode("utf-8", errors="replace").split("\x00")[1:]:
        lines = chunk.splitlines()
        if not lines:
            continue
        when, _, subject = lines[0].partition("\t")
        try:
            at = int(when)
        except ValueError:
            continue
        pr = pr_of_subject(subject)
        for name in lines[1:]:
            if name.strip():
                adds.setdefault(name.strip(), (at, pr))  # git log is newest first: the first add seen is the newest
    return adds


def done_plans(root: Path, branch: str, folder: str, tree_oid: str) -> dict:
    """`{"tree": tree_oid, "plans": [...]}`: every `<folder>/done/*.md` in the tree, newest close first, then path
    A-Z; no close date sorts last (D4). One `git log` and one `cat-file --batch`. A file that fails gives
    `{"path", "error"}`."""
    adds = _origin_done_adds(root, branch, folder)
    rows: list[dict] = []
    batch = _Batch(root)
    try:
        tree = batch.get(tree_oid)
        if tree is None or tree[1] != "tree":
            raise ValueError(f"{folder}/done is not a tree on origin/{branch}")
        for name, oid in sorted(_tree_blobs(tree[2], len(tree[0]) // 2)):
            if not name.endswith(".md"):
                continue
            rel = f"{folder}/done/{name}"
            blob = batch.get(oid)
            if blob is None:
                rows.append({"path": rel, "error": "the file is missing from the git store"})
                continue
            text = blob[2].decode("utf-8", errors="replace").replace("\r\n", "\n")
            closed_at, pr = adds.get(rel, (None, None))
            rows.append(_entry_or_error(rel, lambda rel=rel, text=text, closed_at=closed_at, pr=pr:
                                        done_entry(rel, text, closed_at, pr)))
    finally:
        batch.close()

    def order(row: dict) -> tuple:
        at = adds.get(row["path"], (None, None))[0]
        return (at is None, -(at or 0), row["path"])

    return {"tree": tree_oid, "plans": sorted(rows, key=order)}


def _done_slot(root: Path, branch: str, folder: str, tree: str | None, known: str | None) -> dict:
    """D2/D6: the `done` value of an origin source."""
    if tree is None:
        return {"tree": None, "plans": []}
    if tree == known:
        return {"tree": tree, "unchanged": True}
    try:
        return done_plans(root, branch, folder, tree)
    except Exception as exc:  # done plans must never hide the current plans
        return {"error": (str(exc).splitlines() or [type(exc).__name__])[0]}


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


MAX_PRS = 20  # D3: per repo, only the newest open PRs are looked at (bounds the merge-base cost)
_HEAD_REF = re.compile(r"^(?!-|/)(?!.*\.\.)[^\x00-\x20\x7f:~^?*\[\\]+$")  # D3: a ref name git and `cat-file --batch` accept
_PLANS_DIR = ".caddis/plans"


def branch_plan_changes(batch: _Batch, root: Path, default_branch: str, head_ref: str
                        ) -> dict[str, tuple[str, str | None]] | None:
    """The plan files a PR branch changed: `{".caddis/plans/<name>.md": (head_text, merge_base_text_or_None)}`.

    Local git only. None when `refs/remotes/origin/<head_ref>` is missing or `git merge-base` fails; {} when the
    plans folder is the same tree on head and default (no `merge-base` runs) or no plan file differs.
    """
    head_ref_name = f"refs/remotes/origin/{head_ref}"
    default_ref_name = f"refs/remotes/origin/{default_branch}"
    if batch.get(head_ref_name) is None:
        return None
    head_tree = batch.get(f"{head_ref_name}:{_PLANS_DIR}")
    default_tree = batch.get(f"{default_ref_name}:{_PLANS_DIR}")
    if head_tree is None or head_tree[1] != "tree":
        return {}  # the branch has no plan folder: it deletes or never had plans, nothing to overlay
    if default_tree is not None and default_tree[0] == head_tree[0]:
        return {}
    try:
        found = subprocess.run(["git", "-C", str(root), "merge-base", default_ref_name, head_ref_name],
                               capture_output=True, timeout=30, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    base = found.stdout.decode("ascii", errors="replace").strip()
    if found.returncode != 0 or not base:
        return None
    base_tree = batch.get(f"{base}:{_PLANS_DIR}")
    base_blobs = dict(_tree_blobs(base_tree[2], len(base_tree[0]) // 2)) if base_tree and base_tree[1] == "tree" else {}
    changes: dict[str, tuple[str, str | None]] = {}
    for name, oid in sorted(_tree_blobs(head_tree[2], len(head_tree[0]) // 2)):
        if not name.endswith(".md") or base_blobs.get(name) == oid:
            continue
        head_blob = batch.get(oid)
        if head_blob is None:
            continue
        base_blob = batch.get(base_blobs[name]) if name in base_blobs else None
        changes[f"{_PLANS_DIR}/{name}"] = (
            head_blob[2].decode("utf-8", errors="replace").replace("\r\n", "\n"),
            base_blob[2].decode("utf-8", errors="replace").replace("\r\n", "\n") if base_blob else None)
    return changes


def _usable_prs(prs: list[dict], branch: str) -> list[dict]:
    """D3: same-repo PRs with a safe head ref that is not the default branch; the newest MAX_PRS of them."""
    usable = []
    for pr in prs:
        if not isinstance(pr, dict) or pr.get("fork") or isinstance(pr.get("number"), bool) \
                or not isinstance(pr.get("number"), int):
            continue
        ref = pr.get("head_ref")
        if not isinstance(ref, str) or not ref or ref == branch or not _HEAD_REF.fullmatch(ref):
            continue
        usable.append({**pr, "updated_at": pr["updated_at"] if isinstance(pr.get("updated_at"), str) else ""})
    usable.sort(key=lambda pr: (pr["updated_at"], pr["number"]), reverse=True)
    return usable[:MAX_PRS]


def _overlay_prs(root: Path, branch: str, plans: list[dict], prs: list[dict]) -> int:
    """Lay open PR branches over `plans` (changed in place). Returns how many plans got an overlay."""
    usable = _usable_prs(prs, branch)
    if not usable:
        return 0
    try:
        batch = _Batch(root)
    except OSError:
        return 0
    cands: dict[str, list[tuple[dict, dict, dict | None]]] = {}  # plan path -> [(pr, head entry, base entry)]
    try:
        for pr in usable:
            try:
                changes = branch_plan_changes(batch, root, branch, pr["head_ref"])
            except (OSError, ValueError):
                changes = None
            for path, (head_text, base_text) in (changes or {}).items():
                try:
                    head = _plan_entry_text(path, head_text)
                    base = _plan_entry_text(path, base_text) if base_text is not None else None
                except Exception:  # a branch plan that does not parse is skipped; main shows
                    continue
                cands.setdefault(path, []).append((pr, head, base))
    finally:
        batch.close()
    by_path = {plan["path"]: i for i, plan in enumerate(plans)}
    count = 0
    for path, found in cands.items():
        pr, also = pick_pr([item[0] for item in found])
        _, head, base = next(item for item in found if item[0] is pr)
        at = by_path.get(path)
        if at is None:
            if base is not None:
                continue  # main deleted a plan the branch still edits: a deleted plan is not shown from the branch
            plans.append(overlay_plan(None, None, head, pr, also))
        elif "error" in plans[at]:
            continue
        else:
            plans[at] = overlay_plan(plans[at], base, head, pr, also)
        count += 1
    return count


def plans_json(root: Path, branch: str | None = None, prs: list[dict] | None = None,
               done_known: str | None = None) -> dict:
    """Every current plan as data: `{"schema": 1, "source": ..., "plans": [...]}`. Never prints, never exits.

    With `branch`, read the plans from the local `origin/<branch>` ref (the hub: a pushed Tracker edit shows with
    no pull); when git cannot read that ref, read the working tree. `source` names which one was read. A file that
    does not parse gives `{"path", "error"}`; the other plans still come back.

    An origin source also carries `done` (the finished plans in `<folder>/done`): `{"tree": None, "plans": []}`
    with no done tree, `{"tree": t, "unchanged": True}` when `t == done_known` (the caller keeps its list),
    `{"tree": t, "plans": [...]}` (`done_plans`), or `{"error": ...}`. A working-tree source has no `done` key.

    With `prs` (the open PRs, D2 items) and an origin source, plans a PR branch changed get that branch's Tracker
    laid over main's (`overlay_plan`) and the result carries `overlay`. Without `prs` the output has no overlay key.
    """
    root = Path(root)
    origin = _origin_plan_texts(root, branch) if branch else None
    if origin is not None:
        commit, commit_at, texts, done_tree = origin
        folder = texts[0][0].rsplit("/", 1)[0] if texts else _PLANS_DIR
        plans = [_entry_or_error(rel, lambda rel=rel, text=text: _plan_entry_text(rel, text)) for rel, text in texts]
        times = _origin_plan_times(root, branch, folder) if texts else {}
        for plan in plans:
            if "error" not in plan:
                plan["changed_at"] = times.get(plan["path"])
        data = {"schema": 1, "source": f"origin/{branch}", "commit": commit[:12], "commit_at": commit_at, "plans": plans,
                "done": _done_slot(root, branch, folder, done_tree, done_known)}
        if prs is not None:
            count = _overlay_prs(root, branch, plans, prs)
            data["overlay"] = {"state": "on", "reason": None, "count": count}
        return data
    plans = []
    for path in _plan_files(root):
        plan = _entry_or_error(path.relative_to(root).as_posix(), lambda path=path: _plan_entry(root, path))
        if "error" not in plan:
            plan["changed_at"] = _file_time(path)
        plans.append(plan)
    data = {"schema": 1, "source": "working-tree", "plans": plans}
    if prs is not None:
        data["overlay"] = {"state": "off", "reason": "no git", "count": 0}
    return data


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
