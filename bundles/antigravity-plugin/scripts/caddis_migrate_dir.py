"""caddis_migrate_dir — rename a repo's legacy `.claudster/` artifact dir to `.caddis/`.

The `.claudster` → `.caddis` rename is OPT-IN, per repo, and never automatic: `git mv`-ing a
directory under a concurrent session would move files out from under its in-flight writes (a Stop
hook appending `usage-log.jsonl`, an agent writing a plan). So the SessionStart hook only *nudges*;
this command does the work when you say so.

Everything keeps working either way — every caddis reader tries `.caddis` then `.claudster`, and
every writer writes where the repo already lives. Migration is about consistency, not function.

Behavior (per target repo):
  • SIMPLE CASE — only `.claudster/` exists: one `git mv .claudster .caddis` (history preserved).
  • BOTH EXIST (the straggler case — an out-of-date session or teammate recreated `.claudster/`
    after a migration): per-CHILD merge into `.caddis/`. A child that exists only in the legacy dir
    is moved. A child that exists in BOTH is merged by kind:
      - `.jsonl` append-logs (usage-log / agent-log / memory)  → CONCATENATED, legacy lines FIRST
        (they are older), so no session's history is dropped;
      - directories → recursed, same rules;
      - anything else → left in place and REPORTED (a human decides; we never clobber content).
    An emptied `.claudster/` is removed at the end; one with unresolved conflicts is kept.
  • LIVE REFS are rewritten so the migrated repo's own artifacts don't point at the old dir:
    `.caddis/workstreams.json` (parked-workstream plan paths) and `relay.md`.
  • Idempotent: a re-run on a migrated repo is a no-op. `--dry-run` is the DEFAULT (`--apply`
    executes). Refuses a dirty tree unless `--allow-dirty` — the git mv must be reviewable.

Usage:
    python scripts/caddis_migrate_dir.py [target]           # dry-run (default)
    python scripts/caddis_migrate_dir.py [target] --apply   # execute
    python scripts/caddis_migrate_dir.py [target] --check   # exit 1 if a legacy dir remains (gate)

Exit codes: 0 ok / nothing to do · 1 unresolved conflicts (or --check found a legacy dir) · 2 bad
target / not a git repo / dirty tree.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

NEW_DIR = ".caddis"
OLD_DIR = ".claudster"

#: Append-only JSONL logs: safe to concatenate when both dirs carry one (legacy lines first).
JSONL_MERGE_NAMES = frozenset({"usage-log.jsonl", "agent-log.jsonl", "memory.jsonl"})

#: Files whose CONTENT may name the old dir and is read live after the migration. Historical
#: artifacts (plans, handoffs, past reviews) are deliberately NOT rewritten — they are a record of
#: what was true then, and rewriting them would churn the diff for no functional gain.
LIVE_REF_FILES = ("workstreams.json", "relay.md")


# ── git helpers (mirrors claudster_migrate_rules.py) ─────────────────────────
def _git(target: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(target), capture_output=True, text=True)


def _in_git_repo(target: Path) -> bool:
    r = _git(target, "rev-parse", "--is-inside-work-tree")
    return r.returncode == 0 and r.stdout.strip() == "true"


def _is_dirty(target: Path) -> bool:
    return bool(_git(target, "status", "--porcelain").stdout.strip())


def _is_tracked(target: Path, rel: str) -> bool:
    return _git(target, "ls-files", "--error-unmatch", "--", rel).returncode == 0


def _move(target: Path, src_rel: str, dst_rel: str, apply: bool, report: list[str]) -> None:
    """Move one path, preferring `git mv` so history follows the file."""
    report.append(f"move: {src_rel} -> {dst_rel}")
    if not apply:
        return
    dst = target / dst_rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    if _is_tracked(target, src_rel) and _git(target, "mv", src_rel, dst_rel).returncode == 0:
        return
    # untracked (or git mv refused): a plain move keeps the content; git sees add+delete
    shutil.move(str(target / src_rel), str(dst))


# ── merge (the both-exist case) ──────────────────────────────────────────────
def _concat_jsonl(old: Path, new: Path, apply: bool) -> int:
    """Prepend `old`'s lines to `new` (legacy is older). Returns the number of lines merged.

    Blank lines are dropped and a trailing newline is guaranteed, so a half-written last line in
    either file can't glue two records together.
    """
    old_lines = [ln for ln in old.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    if not apply:
        return len(old_lines)
    new_lines = [ln for ln in new.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    new.write_text("\n".join(old_lines + new_lines) + "\n", encoding="utf-8")
    return len(old_lines)


def _merge_tree(target: Path, old_rel: str, new_rel: str, apply: bool,
                report: list[str], conflicts: list[str]) -> None:
    """Merge `<old_rel>/` into `<new_rel>/`, child by child. Both are repo-relative posix paths."""
    old_dir = target / old_rel
    for child in sorted(old_dir.iterdir()):
        c_old = f"{old_rel}/{child.name}"
        c_new = f"{new_rel}/{child.name}"
        dest = target / c_new
        if not dest.exists():
            _move(target, c_old, c_new, apply, report)
            continue
        if child.is_dir() and dest.is_dir():
            _merge_tree(target, c_old, c_new, apply, report, conflicts)
            continue
        if child.is_file() and dest.is_file() and child.name in JSONL_MERGE_NAMES:
            n = _concat_jsonl(child, dest, apply)
            report.append(f"merge: {c_old} -> {c_new} ({n} legacy line(s), oldest first)")
            if apply:
                _remove(target, c_old)
            continue
        conflicts.append(c_old)
        report.append(f"CONFLICT: {c_old} and {c_new} both exist and cannot be merged — left in place")


def _remove(target: Path, rel: str) -> None:
    """Delete a merged-away file, via `git rm` when tracked so the index stays consistent."""
    if _is_tracked(target, rel) and _git(target, "rm", "-q", "-f", "--", rel).returncode == 0:
        return
    try:
        (target / rel).unlink()
    except OSError:
        pass


def _prune_empty(target: Path, rel: str) -> bool:
    """Remove `<rel>` if it is now empty (depth-first). True when it is gone."""
    d = target / rel
    if not d.is_dir():
        return True
    for child in sorted(d.iterdir()):
        if child.is_dir():
            _prune_empty(target, f"{rel}/{child.name}")
    try:
        d.rmdir()
        return True
    except OSError:
        return False


# ── live-reference rewriting ─────────────────────────────────────────────────
def rewrite_refs_text(text: str) -> str:
    """Replace `.claudster/` path prefixes with `.caddis/` in a live artifact's text. Pure.

    Only the dir followed by a separator is rewritten, so prose about "the .claudster rename"
    survives intact while `.claudster/plans/foo.md` becomes `.caddis/plans/foo.md`. Backslash
    separators are handled too — a Windows-written workstreams.json can carry either.
    """
    return (text.replace(f"{OLD_DIR}/", f"{NEW_DIR}/")
                .replace(f"{OLD_DIR}\\", f"{NEW_DIR}\\"))


def rewrite_live_refs(target: Path, apply: bool, report: list[str]) -> None:
    """Rewrite `.claudster/...` paths inside the migrated dir's live state files."""
    for name in LIVE_REF_FILES:
        p = target / NEW_DIR / name
        if not p.is_file():
            continue
        original = p.read_text(encoding="utf-8", errors="replace")
        updated = rewrite_refs_text(original)
        if updated == original:
            continue
        n = original.count(f"{OLD_DIR}/")
        report.append(f"rewrite: {NEW_DIR}/{name} ({n} legacy path ref(s) -> {NEW_DIR}/)")
        if apply:
            p.write_text(updated, encoding="utf-8")
    # workstreams.json must stay valid JSON — verify, and roll back the rewrite if it doesn't.
    ws = target / NEW_DIR / "workstreams.json"
    if apply and ws.is_file():
        try:
            json.loads(ws.read_text(encoding="utf-8"))
        except Exception:
            report.append(f"WARNING: {NEW_DIR}/workstreams.json is not valid JSON after rewriting "
                          "— check it by hand")


# ── the migration ────────────────────────────────────────────────────────────
def migrate(target: Path, apply: bool) -> tuple[int, list[str]]:
    """Migrate `target`. Returns `(exit_code, report_lines)`."""
    report: list[str] = []
    conflicts: list[str] = []
    old, new = target / OLD_DIR, target / NEW_DIR

    if not old.is_dir():
        report.append(f"nothing to do: no {OLD_DIR}/ in this repo"
                      + (f" ({NEW_DIR}/ already present)" if new.is_dir() else ""))
        return 0, report

    if not new.exists():
        _move(target, OLD_DIR, NEW_DIR, apply, report)
    else:
        report.append(f"both {OLD_DIR}/ and {NEW_DIR}/ exist — merging per child "
                      "(a straggler dir recreated by an out-of-date session)")
        _merge_tree(target, OLD_DIR, NEW_DIR, apply, report, conflicts)
        if apply:
            if _prune_empty(target, OLD_DIR):
                report.append(f"removed: empty {OLD_DIR}/")
            else:
                report.append(f"kept: {OLD_DIR}/ still holds {len(conflicts)} unmerged path(s)")

    rewrite_live_refs(target, apply, report)

    if conflicts:
        report.append(f"\n{len(conflicts)} conflict(s) need a human: " + ", ".join(conflicts))
        return 1, report
    return 0, report


def main(argv: list[str] | None = None) -> int:
    for _stream in (sys.stdout, sys.stderr):  # Windows cp1252 can't encode the em-dashes below
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(
        description=f"Migrate a repo's legacy {OLD_DIR}/ artifact dir to {NEW_DIR}/.")
    ap.add_argument("target", nargs="?", default=".", type=Path)
    ap.add_argument("--apply", action="store_true", help="Execute (default is --dry-run).")
    ap.add_argument("--allow-dirty", action="store_true", help="Proceed even if the tree is dirty.")
    ap.add_argument("--check", action="store_true",
                    help=f"Report only; exit 1 if {OLD_DIR}/ is still present (gate mode).")
    args = ap.parse_args(argv)

    target = args.target.resolve()
    if not target.is_dir():
        print(f"ERROR: target not a directory: {target}", file=sys.stderr)
        return 2

    if args.check:
        if (target / OLD_DIR).is_dir():
            print(f"  legacy {OLD_DIR}/ present — run /caddis:migrate-dir to convert it.")
            return 1
        print(f"No legacy {OLD_DIR}/ — this repo is on {NEW_DIR}/.")
        return 0

    apply = args.apply
    if not _in_git_repo(target):
        print(f"ERROR: {target} is not a git repository (the migration uses git mv to keep history).",
              file=sys.stderr)
        return 2
    # The dirty-tree refusal only applies when there is actually a rename to make — a re-run on an
    # already-migrated repo is a no-op and must not fail just because the tree has unrelated edits.
    if apply and (target / OLD_DIR).is_dir() and _is_dirty(target) and not args.allow_dirty:
        print("ERROR: working tree is dirty — commit/stash first, or pass --allow-dirty.\n"
              "       (A rename mixed into unrelated edits is unreviewable, and this repo's tree "
              "may be shared with a live session.)", file=sys.stderr)
        return 2

    print(f"=== caddis-migrate-dir -> {target} {'(APPLY)' if apply else '(dry-run)'}")
    rc, report = migrate(target, apply)
    for line in report:
        print(f"   {line}")
    if not apply:
        print("\n(dry-run — no files changed; pass --apply to execute)")
    elif rc == 0:
        print("\nMigrated. Review with `git status` / `git diff --staged`, then commit.")
    print(f"\nresult: {'CONFLICTS' if rc else 'ok'}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
