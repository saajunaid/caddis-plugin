#!/usr/bin/env python3
"""Universal, repo-agnostic & agent-agnostic caddis Task List store.

Persists tasks atomically to `<repo>/.caddis/relay/<workstream>.tasks.md` in human-readable
Markdown table format so Claude Code, agy, Codex, and Orca bots share one durable task list
across compactions, handoffs, and restarts.

Stdlib-only.
"""
from __future__ import annotations

import contextlib
import datetime
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Iterator

VALID_STATUSES = ("pending", "in_progress", "completed", "blocked")
_SAFE_WS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_NUM_ID_RE = re.compile(r"^T?(\d+)$", re.I)


@contextlib.contextmanager
def _file_lock(target: Path, timeout_s: float = 5.0) -> Iterator[None]:
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_suffix(target.suffix + ".lock")
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii"))
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime > 30.0:
                    lock_path.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for lock {lock_path}")
            time.sleep(0.02)
    try:
        yield
    finally:
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass


def _replace_with_retry(src: str, dst: Path, attempts: int = 8) -> None:
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i + 1 >= attempts:
                raise
            time.sleep(0.02 * (i + 1))


def _now_utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean_cell(val: str) -> str:
    return str(val or "").replace("|", "/").replace("\r", " ").replace("\n", " ").strip()


def resolve_tasks_file(repo: Path | str, workstream: str = "default") -> Path:
    ws = (workstream or "default").strip()
    if not _SAFE_WS_RE.match(ws):
        raise ValueError(f"invalid workstream name: {workstream!r}")
    return Path(repo).resolve() / ".caddis" / "relay" / f"{ws}.tasks.md"


def _parse_blocked(raw: str) -> list[str]:
    text = (raw or "").strip()
    if not text or text in ("-", "—", "none"):
        return []
    return [tok.strip() for tok in text.split(",") if tok.strip()]


def _is_table_line(raw: str) -> bool:
    line = raw.strip()
    return line.startswith("|") and line.endswith("|") and len(line) >= 2


def _parse_tasks_document(text: str) -> tuple[list[str], list[dict], list[str], bool]:
    """Split a tasks markdown file into (prefix_lines, tasks, suffix_lines, found_table).

    Preserves surrounding prose/sections outside the task table and preserves
    unrecognized status strings on existing rows instead of mutating them.
    """
    raw_lines = text.splitlines()
    headers: list[str] = []
    header_idx: int | None = None
    for idx, raw in enumerate(raw_lines):
        if not _is_table_line(raw):
            continue
        cells = [c.strip() for c in raw.strip()[1:-1].split("|")]
        if all(set(c) <= {"-", ":", " "} for c in cells):
            continue
        lower = [c.lower() for c in cells]
        if "subject" in lower and "status" in lower:
            headers = lower
            header_idx = idx
            break
    if header_idx is None:
        return raw_lines, [], [], False

    tasks: list[dict] = []
    end_idx = header_idx + 1
    while end_idx < len(raw_lines) and _is_table_line(raw_lines[end_idx]):
        cells = [c.strip() for c in raw_lines[end_idx].strip()[1:-1].split("|")]
        end_idx += 1
        if all(set(c) <= {"-", ":", " "} for c in cells):
            continue
        row = {headers[i]: (cells[i] if i < len(cells) else "") for i in range(len(headers))}
        tid = row.get("id") or row.get("old #") or row.get("#") or ""
        subj = row.get("subject") or ""
        if not tid and not subj:
            continue
        st = (row.get("status") or "pending").strip().lower()
        tasks.append({
            "id": tid,
            "status": st,
            "priority": row.get("priority", ""),
            "track": row.get("track", ""),
            "owner": row.get("owner", ""),
            "blocked_by": _parse_blocked(row.get("blocked_by", "")),
            "subject": subj,
            "description": row.get("description", ""),
            "updated_at": row.get("updated_at", ""),
        })
    return raw_lines[:header_idx], tasks, raw_lines[end_idx:], True


def _update_frontmatter_saved(prefix_lines: list[str], now: str) -> list[str]:
    if not prefix_lines or prefix_lines[0].strip() != "---":
        return list(prefix_lines)
    updated = list(prefix_lines)
    for i in range(1, len(updated)):
        if updated[i].strip() == "---":
            break
        if updated[i].startswith("saved:"):
            updated[i] = f"saved: {now}"
            break
    return updated


def list_tasks(repo: Path | str, workstream: str = "default", status: str | None = None) -> list[dict]:
    path = resolve_tasks_file(repo, workstream)
    if not path.is_file():
        return []
    _prefix, tasks, _suffix, _found = _parse_tasks_document(
        path.read_text(encoding="utf-8", errors="replace")
    )
    if status:
        tasks = [t for t in tasks if t["status"] == status]
    return tasks


def _write_tasks(repo: Path | str, workstream: str, tasks: list[dict]) -> Path:
    ws = (workstream or "default").strip()
    path = resolve_tasks_file(repo, ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = _now_utc()
    table_lines = [
        "| ID | Status | Priority | Track | Owner | Blocked_By | Subject | Description | Updated_At |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for t in tasks:
        blocked = ", ".join(t.get("blocked_by") or [])
        table_lines.append(
            f"| {_clean_cell(t['id'])} | {_clean_cell(t['status'])} | {_clean_cell(t.get('priority', ''))} "
            f"| {_clean_cell(t.get('track', ''))} | {_clean_cell(t.get('owner', ''))} "
            f"| {_clean_cell(blocked)} | {_clean_cell(t.get('subject', ''))} "
            f"| {_clean_cell(t.get('description', ''))} | {_clean_cell(t.get('updated_at') or now)} |"
        )
    if path.is_file():
        prefix_lines, _old_tasks, suffix_lines, found_table = _parse_tasks_document(
            path.read_text(encoding="utf-8", errors="replace")
        )
        prefix_lines = _update_frontmatter_saved(prefix_lines, now)
        if found_table:
            lines = [*prefix_lines, *table_lines, *suffix_lines]
        else:
            spacer = [""] if prefix_lines and prefix_lines[-1].strip() else []
            lines = [*prefix_lines, *spacer, *table_lines]
    else:
        lines = [
            "---",
            "type: todo",
            "status: open",
            f"relay: {ws}",
            f"saved: {now}",
            "---",
            f"# {ws} - tasks",
            "",
            *table_lines,
        ]
    payload = "\n".join(lines) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=".tasks-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        _replace_with_retry(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


def _next_id(tasks: list[dict]) -> str:
    hi = 0
    for t in tasks:
        m = _NUM_ID_RE.match(str(t.get("id") or ""))
        if m:
            hi = max(hi, int(m.group(1)))
    return f"T{hi + 1}"


def _validate_blocked_by(blocked_by: list[str] | None) -> list[str]:
    if blocked_by is None:
        return []
    if not isinstance(blocked_by, (list, tuple)):
        raise ValueError("blocked_by must be a list of strings")
    out: list[str] = []
    for item in blocked_by:
        if not isinstance(item, str):
            raise ValueError("blocked_by items must be strings")
        cleaned = _clean_cell(item)
        if cleaned:
            out.append(cleaned)
    return out


def create_task(
    repo: Path | str,
    *,
    workstream: str = "default",
    subject: str,
    description: str = "",
    status: str = "pending",
    priority: str = "",
    track: str = "",
    owner: str = "",
    blocked_by: list[str] | None = None,
    task_id: str | None = None,
) -> dict:
    clean_subj = _clean_cell(subject)
    if not clean_subj:
        raise ValueError("subject is required")
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status {status!r}; expected one of {VALID_STATUSES}")
    clean_blocked = _validate_blocked_by(blocked_by)
    path = resolve_tasks_file(repo, workstream)
    with _file_lock(path):
        tasks = list_tasks(repo, workstream)
        tid = (task_id or "").strip() or _next_id(tasks)
        if not _SAFE_WS_RE.match(tid):
            raise ValueError(f"invalid task id: {task_id!r}")
        if any(t["id"] == tid for t in tasks):
            raise ValueError(f"task id already exists: {tid}")
        task = {
            "id": tid,
            "status": status,
            "priority": _clean_cell(priority),
            "track": _clean_cell(track),
            "owner": _clean_cell(owner),
            "blocked_by": clean_blocked,
            "subject": clean_subj,
            "description": _clean_cell(description),
            "updated_at": _now_utc(),
        }
        tasks.append(task)
        _write_tasks(repo, workstream, tasks)
    return task


def get_task(repo: Path | str, *, workstream: str = "default", task_id: str) -> dict:
    for t in list_tasks(repo, workstream):
        if t["id"] == task_id:
            return t
    raise KeyError(f"task not found: {task_id}")


def update_task(
    repo: Path | str,
    *,
    workstream: str = "default",
    task_id: str,
    subject: str | None = None,
    description: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    track: str | None = None,
    owner: str | None = None,
    blocked_by: list[str] | None = None,
) -> dict:
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f"invalid status {status!r}; expected one of {VALID_STATUSES}")
    if subject is not None and not _clean_cell(subject):
        raise ValueError("subject cannot be empty")
    clean_blocked = _validate_blocked_by(blocked_by) if blocked_by is not None else None
    path = resolve_tasks_file(repo, workstream)
    with _file_lock(path):
        tasks = list_tasks(repo, workstream)
        target = None
        for t in tasks:
            if t["id"] == task_id:
                if subject is not None:
                    t["subject"] = _clean_cell(subject)
                if description is not None:
                    t["description"] = _clean_cell(description)
                if status is not None:
                    t["status"] = status
                if priority is not None:
                    t["priority"] = _clean_cell(priority)
                if track is not None:
                    t["track"] = _clean_cell(track)
                if owner is not None:
                    t["owner"] = _clean_cell(owner)
                if clean_blocked is not None:
                    t["blocked_by"] = clean_blocked
                t["updated_at"] = _now_utc()
                target = t
                break
        if target is None:
            raise KeyError(f"task not found: {task_id}")
        _write_tasks(repo, workstream, tasks)
    return target


def clear_tasks(repo: Path | str, *, workstream: str = "default", completed_only: bool = True) -> int:
    path = resolve_tasks_file(repo, workstream)
    if not path.is_file():
        return 0
    with _file_lock(path):
        tasks = list_tasks(repo, workstream)
        if completed_only:
            kept = [t for t in tasks if t["status"] != "completed"]
        else:
            kept = []
        removed = len(tasks) - len(kept)
        _write_tasks(repo, workstream, kept)
    return removed


def summarize(tasks: list[dict]) -> dict:
    counts = {s: 0 for s in VALID_STATUSES}
    for t in tasks:
        st = t.get("status", "pending")
        counts[st] = counts.get(st, 0) + 1
    counts["total"] = len(tasks)
    return counts


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Universal caddis task list CLI.")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--workstream", default="default")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_list = sub.add_parser("list")
    p_list.add_argument("--status", default=None, choices=VALID_STATUSES)
    p_add = sub.add_parser("create")
    p_add.add_argument("--id", dest="task_id", default=None)
    p_add.add_argument("--subject", required=True)
    p_add.add_argument("--description", default="")
    p_add.add_argument("--status", default="pending", choices=VALID_STATUSES)
    p_add.add_argument("--priority", default="")
    p_add.add_argument("--track", default="")
    p_add.add_argument("--owner", default="")
    p_add.add_argument("--blocked-by", default="")
    p_get = sub.add_parser("get")
    p_get.add_argument("--id", dest="task_id", required=True)
    p_upd = sub.add_parser("update")
    p_upd.add_argument("--id", dest="task_id", required=True)
    p_upd.add_argument("--subject", default=None)
    p_upd.add_argument("--description", default=None)
    p_upd.add_argument("--status", default=None, choices=VALID_STATUSES)
    p_upd.add_argument("--priority", default=None)
    p_upd.add_argument("--track", default=None)
    p_upd.add_argument("--owner", default=None)
    p_upd.add_argument("--blocked-by", default=None)
    p_clr = sub.add_parser("clear")
    p_clr.add_argument("--all", dest="clear_all", action="store_true", default=False)
    args = parser.parse_args()
    if args.cmd == "list":
        rows = list_tasks(args.repo, args.workstream, status=args.status)
        print(json.dumps({"tasks": rows, "summary": summarize(rows)}, indent=2))
    elif args.cmd == "create":
        blocked = [b.strip() for b in args.blocked_by.split(",") if b.strip()] if args.blocked_by else None
        print(json.dumps(create_task(
            args.repo, workstream=args.workstream, subject=args.subject,
            description=args.description, status=args.status, priority=args.priority,
            track=args.track, owner=args.owner, blocked_by=blocked, task_id=args.task_id,
        ), indent=2))
    elif args.cmd == "get":
        print(json.dumps(get_task(args.repo, workstream=args.workstream, task_id=args.task_id), indent=2))
    elif args.cmd == "update":
        blocked = (
            [b.strip() for b in args.blocked_by.split(",") if b.strip()]
            if args.blocked_by is not None else None
        )
        print(json.dumps(update_task(
            args.repo, workstream=args.workstream, task_id=args.task_id,
            subject=args.subject, description=args.description, status=args.status,
            priority=args.priority, track=args.track, owner=args.owner, blocked_by=blocked,
        ), indent=2))
    elif args.cmd == "clear":
        removed = clear_tasks(args.repo, workstream=args.workstream, completed_only=not args.clear_all)
        print(json.dumps({"removed": removed}, indent=2))
