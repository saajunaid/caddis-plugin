"""What a session CREATED and must clean up: worktrees and scratch folders, recorded per session.

Why a file of its own. The Stop hook rewrites `.caddis/session-state/<id>.md` every turn, so a record kept there is
lost. A session also often makes worktrees in OTHER repos. So the record lives outside every repo:

    ~/.caddis/sessions/<session-id>.created.jsonl        (append-only; one JSON object per line)

(`~` is `$CADDIS_HOME` when set, else the user's home folder; the `home` argument beats both. The folder also holds
other code's `<session-id>.json` files; this module never touches those.)

A line is one fact about one path:

    {"path", "kind": "worktree"|"scratch", "created": <ISO UTC>, "purpose", "pr": str|null, "repo": str|null,
     "branch": str|null, "status": "created"|"removed", "by": "helper"|"lanes"|"roadmap-run"|"docs-pr"|
     "transcript"|"cli"}

`read` FOLDS the lines by normalised path (case-insensitive on Windows): `created` keeps the first value and every
other field takes the latest non-null value. So "record again with the PR number" and "mark removed" are just new
lines. One exception, which is a safety rule: a `created` line for a path whose last status was `removed` starts a
NEW entry. A path that is used again (a roadmap worktree has a fixed name) must not inherit the old PR.

This module only RECORDS. It deletes nothing; `cleanup` hands off to `caddis_own_cleanup.py`, which does.

    session_id(explicit=None)  -> a safe session id, or None
    record(path, kind, purpose, *, pr, repo, branch, status, by, session_id, home) -> bool   (never raises)
    read(session_id, home=None) -> list[dict]       (folded; oldest first; bad lines skipped)

CLI (exit 0 on success; `record` with no session id warns on stderr and still exits 0, so a caller never breaks;
exit 2 on bad arguments):
    python caddis_created.py record --path P --kind worktree --purpose "why" [--pr N] [--repo R] [--branch B]
                                    [--status removed] [--by cli] [--session-id S]
    python caddis_created.py list [--session-id S] [--json]
    python caddis_created.py cleanup [--session-id S] [--apply] [--json]   (dry run by default; always exit 0)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SESSION_ENV_VARS = ("CADDIS_SESSION_ID", "CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID")  # as caddis_adhoc.session_key
KINDS = ("worktree", "scratch")
STATUSES = ("created", "removed")
BYS = ("helper", "lanes", "roadmap-run", "docs-pr", "transcript", "cli")
_SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,100}")  # no separator, drive colon or dots: a plain file-name stem
_FIELDS = ("purpose", "pr", "repo", "branch", "by")


def _sid(explicit: str | None = None) -> str | None:
    """`explicit` (even "", which gives None), else the first non-blank session env var. None when there is none or not a safe file
    name (a bad explicit id does NOT fall back to the environment: that would record under the wrong session)."""
    candidates = [explicit] if explicit is not None else [os.environ.get(name) for name in SESSION_ENV_VARS]
    for raw in candidates:
        value = (raw or "").strip()
        if value:
            return value if _SAFE_ID.fullmatch(value) else None
    return None


def session_id(explicit: str | None = None) -> str | None:
    """The session id to record under: see `_sid`."""
    return _sid(explicit)


def _file(sid: str, home: Path | str | None) -> Path:
    root = Path(home) if home else Path(os.environ.get("CADDIS_HOME") or Path.home())
    return root / ".caddis" / "sessions" / f"{sid}.created.jsonl"


def _normalise(path: str | os.PathLike) -> str:
    """Absolute, `..` collapsed. Not resolved: resolving would follow a link, and the record names the path as made."""
    return os.path.abspath(os.fspath(path))


def _key(path: str) -> str:
    return os.path.normcase(path)  # lower-case and backslashes on Windows; unchanged elsewhere


def record(path: str | os.PathLike, kind: str, purpose: str = "", *, pr: str | int | None = None,
           repo: str | os.PathLike | None = None, branch: str | None = None, status: str = "created",
           by: str = "cli", session_id: str | None = None, home: Path | str | None = None) -> bool:
    """Append one line. False, and nothing written, with no usable session id, an unknown kind or status, or any I/O
    error. Never raises: callers are hooks and runners."""
    try:
        sid = _sid(session_id)
        if not sid or kind not in KINDS or status not in STATUSES or not str(path).strip():
            return False
        line = {
            "path": _normalise(path), "kind": kind,
            "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "purpose": str(purpose or ""), "pr": None if pr is None or str(pr) == "" else str(pr),
            "repo": _normalise(repo) if repo else None, "branch": branch or None, "status": status, "by": by,
        }
        target = _file(sid, home)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")  # one write call: appends do not interleave
        return True
    except Exception:  # noqa: BLE001 - a recording failure must never break the caller
        return False


def read(session_id: str, home: Path | str | None = None) -> list[dict]:
    """The session's entries, folded by path, oldest `created` first. [] when there is no file; bad lines are skipped."""
    try:
        sid = session_id if _SAFE_ID.fullmatch(session_id or "") else None  # strict: no env fallback when reading
        if not sid:
            return []
        text = _file(sid, home).read_text(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return []
    folded: dict[str, dict] = {}
    for raw in text.splitlines():
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if not (isinstance(line, dict) and isinstance(line.get("path"), str) and line["path"]
                and line.get("kind") in KINDS and line.get("status") in STATUSES):
            continue
        key = _key(line["path"])
        entry = folded.get(key)
        if entry is None or (entry["status"] == "removed" and line["status"] == "created"):
            folded[key] = {"path": line["path"], "kind": line["kind"], "created": str(line.get("created") or ""),
                           "status": line["status"], **{name: line.get(name) for name in _FIELDS}}
            continue
        entry["status"] = line["status"]
        entry["kind"] = line["kind"]
        for name in _FIELDS:
            if line.get(name) is not None and not (name == "purpose" and line[name] == ""):
                entry[name] = line[name]
    return sorted(folded.values(), key=lambda e: e["created"])  # stable: equal stamps keep file order


def _summary(entry: dict) -> str:
    text = f"{entry['path']} | {entry['kind']} | {entry['status']} | {entry.get('purpose') or ''}"
    return text + (f" | PR {entry['pr']}" if entry.get("pr") else "")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Record or list what this session created (worktrees, scratch folders).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record", help="append one line for a path")
    rec.add_argument("--path", required=True)
    rec.add_argument("--kind", required=True, choices=KINDS)
    rec.add_argument("--purpose", default="")
    rec.add_argument("--pr", default=None)
    rec.add_argument("--repo", default=None)
    rec.add_argument("--branch", default=None)
    rec.add_argument("--status", default="created", choices=STATUSES)
    rec.add_argument("--by", default="cli", choices=BYS)
    rec.add_argument("--session-id", default=None)
    lst = sub.add_parser("list", help="print the folded entries")
    lst.add_argument("--session-id", default=None)
    lst.add_argument("--json", action="store_true")
    cln = sub.add_parser("cleanup", help="remove this session's merged, clean worktrees and scratch folders")
    cln.add_argument("--session-id", default=None)
    cln.add_argument("--apply", action="store_true", help="act; without it, only list (the default)")
    cln.add_argument("--json", action="store_true")
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    sid = session_id(args.session_id)
    if args.cmd == "record":
        if not record(args.path, args.kind, args.purpose, pr=args.pr, repo=args.repo, branch=args.branch,
                      status=args.status, by=args.by, session_id=args.session_id):
            why = "no usable session id" if not sid else "the record could not be written"
            print(f"caddis_created: not recorded ({why}): {args.path}", file=sys.stderr)
        return 0
    if args.cmd == "cleanup":
        import caddis_own_cleanup  # it deletes, so it lives apart from this record-only module (and imports it)
        return caddis_own_cleanup.run(sid, args.apply, args.json)
    if not sid:
        print("caddis_created: no usable session id; nothing to list", file=sys.stderr)
    entries = read(sid) if sid else []
    if args.json:
        print(json.dumps(entries, indent=2, ensure_ascii=False))
    else:
        for entry in entries:
            print(_summary(entry))
    return 0


if __name__ == "__main__":
    sys.exit(main())
