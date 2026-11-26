#!/usr/bin/env python3
"""Deferred cross-vendor audit queue for owner-waived same-vendor reviews.

When one vendor hits quota (e.g. Claude weekly cap), an owner may explicitly waive
the same-vendor check on low/medium-risk PRs via `oss_review.py --waive-same-vendor
--reason "..."`. Every waived review appends a `pending` record here so one command:

    python scripts/caddis_review_catchup.py run

replays true cross-vendor review (without waiver) once the second vendor is available
and marks each item `AUDITED_CLEAN` or `FOLLOWUP_NEEDED`.

Stdlib-only. Repo-agnostic and agent-agnostic.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Iterator, Mapping

DEFAULT_CATCHUP_FILE = Path.home() / ".caddis" / "review-catchup.jsonl"
VALID_STATUSES = ("pending", "AUDITED_CLEAN", "FOLLOWUP_NEEDED", "DISMISSED")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@contextlib.contextmanager
def _file_lock(target: Path, timeout_s: float = 5.0) -> Iterator[None]:
    """Portable lockfile around read-modify-write for concurrent catch-up writers."""
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_suffix(target.suffix + ".lock")
    deadline = time.monotonic() + timeout_s
    fd = None
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii"))
            os.close(fd)
            fd = None
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


def catchup_path(env: Mapping[str, str] | None = None, path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    src = os.environ if env is None else env
    override = (src.get("CADDIS_CATCHUP_FILE") or "").strip()
    return Path(override) if override else DEFAULT_CATCHUP_FILE


def _now_utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_id(repo: str, git_range: str, created_at: str) -> str:
    raw = f"{repo}|{git_range}|{created_at}|{os.getpid()}|{uuid.uuid4().hex}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:10]


def _load_records(p: Path) -> list[tuple[dict | None, str]]:
    """Read raw JSONL records, preserving unparseable lines verbatim.

    Returns [] only when the queue file does not exist (FileNotFoundError);
    unexpected OSError / PermissionError propagates so callers never overwrite
    an unreadable audit queue.
    """
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    records: list[tuple[dict | None, str]] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            rec = json.loads(stripped)
        except json.JSONDecodeError:
            records.append((None, raw))
            continue
        if isinstance(rec, dict) and rec.get("id"):
            records.append((rec, stripped))
        else:
            records.append((None, raw))
    return records


def load_entries(path: Path | str | None = None, env: Mapping[str, str] | None = None) -> list[dict]:
    p = catchup_path(env, path)
    return [rec for rec, _raw in _load_records(p) if rec is not None]


def _write_records(records: list[tuple[dict | None, str]], p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        (json.dumps(rec, ensure_ascii=False) if rec is not None else raw.rstrip("\r\n")) + "\n"
        for rec, raw in records
    ]
    payload = "".join(lines)
    fd, tmp_name = tempfile.mkstemp(prefix=".catchup-", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        _replace_with_retry(tmp_name, p)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _write_entries(entries: list[dict], p: Path) -> None:
    _write_records([(e, "") for e in entries], p)


def append_waiver(
    *,
    repo: str,
    git_range: str,
    author: str,
    tier: str = "1",
    interim_reviewer: str,
    interim_verdict: str,
    reason: str,
    pr: str | None = None,
    path: Path | str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict:
    p = catchup_path(env, path)
    created_at = _now_utc()
    entry = {
        "id": _make_id(repo, git_range, created_at),
        "repo": str(Path(repo).resolve()) if repo else "",
        "pr": str(pr) if pr is not None else "",
        "range": git_range,
        "author": author,
        "tier": tier,
        "interim_reviewer": interim_reviewer,
        "interim_verdict": interim_verdict,
        "reason": reason,
        "status": "pending",
        "created_at": created_at,
        "audited_at": "",
        "audit_note": "",
    }
    with _file_lock(p):
        records = _load_records(p)
        records.append((entry, ""))
        _write_records(records, p)
    return entry


def pending_count(path: Path | str | None = None, env: Mapping[str, str] | None = None) -> int:
    return sum(1 for e in load_entries(path, env) if e.get("status") == "pending")


def mark_entry(
    entry_id: str,
    status: str,
    *,
    note: str = "",
    path: Path | str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status {status!r}; expected one of {VALID_STATUSES}")
    p = catchup_path(env, path)
    with _file_lock(p):
        records = _load_records(p)
        target = None
        for entry, _raw in records:
            if entry is not None and entry.get("id") == entry_id:
                entry["status"] = status
                entry["audited_at"] = _now_utc()
                if note:
                    entry["audit_note"] = note
                target = entry
                break
        if target is None:
            raise KeyError(f"catch-up entry not found: {entry_id}")
        _write_records(records, p)
    return target


def _oss_review_script() -> Path | None:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[1] / ".github" / "tools" / "oss_review.py",
        here.parent / "oss_review.py",
    ]
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


_IMMUTABLE_RANGE_RE = re.compile(r"^([0-9a-f]{40})\.\.([0-9a-f]{40})$")


def _is_replayable_range(git_range: str) -> bool:
    """Only two distinct 40-char immutable commit SHAs (<base_sha>..<head_sha>) are replayable."""
    m = _IMMUTABLE_RANGE_RE.match((git_range or "").strip())
    return bool(m and m.group(1) != m.group(2))


def _build_oss_review_cmd(entry: dict, script: Path) -> list[str]:
    git_range = str(entry.get("range") or "").strip()
    if not _is_replayable_range(git_range):
        raise ValueError(
            f"unreplayable range {git_range!r}: catch-up requires two distinct 40-char commit SHAs (<base_sha>..<head_sha>)"
        )
    return [
        sys.executable,
        str(script),
        "--author", str(entry.get("author") or "agy"),
        "--tier", str(entry.get("tier") or "1"),
        "--cwd", str(entry.get("repo") or "."),
        "--range", git_range,
    ]


def _summarize_blocking_output(out: str, max_chars: int = 1000) -> str:
    """Return a single-line bounded excerpt of blocking review output (finding headers + verdict)."""
    lines = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    if not lines:
        return "BLOCKING"
    if len(lines) == 1:
        return lines[0][:max_chars]
    last = lines[-1]
    body_lines = lines[:-1]
    combined = " | ".join(body_lines) + f" | {last}"
    if len(combined) <= max_chars:
        return combined
    suffix = f" ... | {last}"
    if len(suffix) >= max_chars:
        return last[:max_chars]
    budget = max_chars - len(suffix)
    joined_body = " | ".join(body_lines)
    prefix = joined_body[:budget].rstrip()
    if "blocking" not in prefix.lower():
        for i, ln in enumerate(body_lines):
            if "blocking" in ln.lower():
                prefix = " | ".join(body_lines[i:])[:budget].rstrip()
                break
    return f"{prefix}{suffix}"


def _invoke_oss_review(entry: dict, env: Mapping[str, str] | None = None) -> tuple[int, str]:
    script = _oss_review_script()
    if script is None:
        return 3, "oss_review.py not found"
    cmd = _build_oss_review_cmd(entry, script)
    proc_env = dict(os.environ, **env) if env is not None else None
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=proc_env,
        creationflags=_NO_WINDOW,
    )
    output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return proc.returncode, output.strip()


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage deferred cross-vendor review catch-up queue.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="List pending and completed catch-up entries.")
    p_status.add_argument("--all", action="store_true", help="Show audited entries too.")
    p_status.add_argument("--json", action="store_true", help="Output JSON.")

    p_add = sub.add_parser("add", help="Manually log a waived review entry.")
    p_add.add_argument("--repo", required=True)
    p_add.add_argument("--range", required=True)
    p_add.add_argument("--author", required=True)
    p_add.add_argument("--tier", default="1")
    p_add.add_argument("--interim-reviewer", required=True)
    p_add.add_argument("--interim-verdict", default="CLEAN")
    p_add.add_argument("--reason", required=True)
    p_add.add_argument("--pr", default=None)

    p_mark = sub.add_parser("mark", help="Mark a catch-up entry's audit outcome.")
    p_mark.add_argument("--id", required=True)
    p_mark.add_argument("--status", required=True, choices=VALID_STATUSES)
    p_mark.add_argument("--note", default="")

    p_run = sub.add_parser("run", help="Run true cross-vendor review over pending waived entries.")
    p_run.add_argument("--id", default=None, help="Audit only one entry id.")
    p_run.add_argument("--dry-run", action="store_true", help="Show what would be audited without running.")

    args = parser.parse_args(argv)
    store = catchup_path(env)

    if args.command == "status":
        entries = load_entries(store)
        shown = entries if args.all else [e for e in entries if e.get("status") == "pending"]
        if args.json:
            print(json.dumps(shown, indent=2))
            return 0
        if not shown:
            print("No pending waived reviews awaiting cross-vendor audit.")
            return 0
        for e in shown:
            pr_part = f" PR#{e['pr']}" if e.get("pr") else ""
            print(f"{e['id']} [{e['status']}]{pr_part} {e['repo']} {e['range']} (author={e['author']}, interim={e['interim_reviewer']}, reason={e['reason']})")
        return 0

    if args.command == "add":
        rec = append_waiver(
            repo=args.repo,
            git_range=args.range,
            author=args.author,
            tier=args.tier,
            interim_reviewer=args.interim_reviewer,
            interim_verdict=args.interim_verdict,
            reason=args.reason,
            pr=args.pr,
            path=store,
        )
        print(json.dumps(rec))
        return 0

    if args.command == "mark":
        try:
            rec = mark_entry(args.id, args.status, note=args.note, path=store)
        except (KeyError, ValueError) as exc:
            sys.stderr.write(f"{exc}\n")
            return 1
        print(json.dumps(rec))
        return 0

    if args.command == "run":
        entries = [e for e in load_entries(store) if e.get("status") == "pending"]
        if args.id:
            entries = [e for e in entries if e.get("id") == args.id]
        if not entries:
            print("No pending waived reviews to audit.")
            return 0
        any_followup = False
        for entry in entries:
            if not _is_replayable_range(str(entry.get("range") or "")):
                note = f"unreplayable range {entry.get('range')!r}: requires <base_sha>..<head_sha>"
                if args.dry_run:
                    print(f"[dry-run] {entry['id']} -> UNREPLAYABLE ({note})")
                    continue
                any_followup = True
                mark_entry(entry["id"], "FOLLOWUP_NEEDED", note=note, path=store)
                print(f"[catchup] {entry['id']} -> FOLLOWUP_NEEDED ({note})")
                continue
            if args.dry_run:
                print(f"[dry-run] would audit {entry['id']} ({entry['repo']} {entry['range']} author={entry['author']} tier={entry['tier']})")
                continue
            rc, out = _invoke_oss_review(entry, env=env) if env is not None else _invoke_oss_review(entry)
            if rc == 0:
                mark_entry(entry["id"], "AUDITED_CLEAN", note="cross-vendor review clean", path=store)
                print(f"[catchup] {entry['id']} -> AUDITED_CLEAN")
            elif rc == 1:
                any_followup = True
                snippet = _summarize_blocking_output(out)
                mark_entry(entry["id"], "FOLLOWUP_NEEDED", note=snippet, path=store)
                print(f"[catchup] {entry['id']} -> FOLLOWUP_NEEDED ({snippet})")
            else:
                print(f"[catchup] {entry['id']} -> STILL PENDING (provider unavailable, exit {rc})")
        return 1 if any_followup else 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
