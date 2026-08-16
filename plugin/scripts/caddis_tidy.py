#!/usr/bin/env python3
"""caddis_tidy — deterministic done/-folder lifecycle for `.caddis/plans/` and `.caddis/prompts/`.

WHY
---
`.caddis/plans/` and `.caddis/prompts/` accumulate finished artifacts. Moving a terminal-status
file into its sibling `done/` was done BY HAND twice in one week (2026-08-05, 2026-08-06) across
this repo alone. `.caddis/plans/artifact-lifecycle-tidy.md` designed the fix; this is Phase 1.

DESIGN (locked, see the plan doc — do not re-litigate here)
-------------------------------------------------------------
- Frontmatter `status:` is the single source of truth. Terminal = `done` (canonical) and
  `superseded`; `shipped`/`implemented` are accepted legacy synonyms, all case-insensitive.
  Everything else (`draft`, `current`, `ready`, ...) is active. `ready` is approved-and-waiting,
  NOT terminal.
- A DETERMINISTIC SCRIPT does the moving — never model judgment, never a mutating hook. With
  multiple concurrent sessions per repo, a background hook that moves files mid-session is a
  race; a command-invoked script is predictable and testable.
- Dry-run by default; --apply moves; --check validates conformance (frontmatter-less or an
  unknown status on a top-level artifact) and exits 1 on a violation, for a future CI/pre-push
  gate. Legacy frontmatter-less prompts are left alone by the mover, only flagged by --check.
- NEVER auto-flips `status:` (that's the implementing session's judgment call) and NEVER
  overwrites an existing `done/<name>` — a collision is reported and skipped, not clobbered.

Usage:
  python scripts/caddis_tidy.py                 # report only (default = dry-run)
  python scripts/caddis_tidy.py --apply          # actually move terminal-status artifacts
  python scripts/caddis_tidy.py --check          # conformance check; exit 1 on a violation
  python scripts/caddis_tidy.py --repo-root <p>  # scan a different repo (default: cwd)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

TERMINAL_STATUSES = {"done", "superseded", "shipped", "implemented"}

# Legacy prompts written before the frontmatter convention existed (2026-07-23). They were
# moved by hand already, per this feature's own Non-goals: "No retro-tagging of historical
# prompts... the convention applies going forward." Without this allowlist, --check could never
# be wired into CI/pre-push in THIS repo - it would exit 1 forever on content nobody intends to
# retrofit. New violations (a prompt written after 2026-07-23 with no frontmatter) still fail.
LEGACY_FRONTMATTER_EXEMPT = {
    "prompts/caddis-rename-and-publish.md",
    "prompts/db-diagram-fix-er-arrows-theme-formatting.md",
    "prompts/docket-phase-2c-ux-correctness.md",
    "prompts/docket-phase-3-f12-worktree.md",
    "prompts/docket-reaudit-f12-and-pipeline-runner.md",
    "prompts/driver-remaining-toolchain-work.md",
    "prompts/fable-inspect-claudster.md",
    "prompts/fable-inspect-docket.md",
    "prompts/fable-verify-docket-reaudit.md",
}

_PHASE_HEADING_RE = re.compile(r"^#{2,4}\s*Phase\s+.+$", re.MULTILINE)
_DONE_MARKERS = ("✅",)
_NOT_DONE_MARKERS = ("⏳", "🔨", "🔲")

_KINDS = ("plans", "prompts", "parking-lot")

# ── parking-lot: the ONE register of future work ────────────────────────────────────────────
# Before this landed, future work lived in nine places at once (measured 2026-08-14 in this repo):
# individual parking-lot files, a 90 KB `future-work-register.md`, parked plans, relay.md's
# "things owed", KB notes, `.caddis/plans/backlog/`, the comms register, docket, and the Hub's
# carried-open lists. Nothing was wrong with any single one; the DEFECT was that a reader had to
# know all nine to answer "what is left to do?". Nobody did, so items were re-raised and dropped.
#
# The rule is now: one item, one file, in `.caddis/parking-lot/`. Everything else POINTS here.
# These constants are what makes that a check instead of a sentence.
PARKING_LOT_DIR = "parking-lot"
PARKING_LOT_TYPE = "parking-lot"
# Lifecycle. Deliberately four words and no synonyms — the plans/prompts vocabulary accreted three
# legacy spellings of "done" and every consumer now has to know all of them.
PARKING_LOT_STATUSES = {"open", "doing", "done", "dropped"}
PARKING_LOT_TERMINAL = {"done", "dropped"}
# `dropped` is terminal ON PURPOSE, and it must carry a reason in the body. An item deleted outright
# gets re-raised by the next session that has the same idea; an item kept with "no, because ..."
# does not. That is the whole difference between a backlog and a memory.
#
# COMMITMENT is a second, INDEPENDENT axis from status. `future: yes` means decided-and-owed;
# absent or `no` means candidate. Folding this into `status:` was considered and rejected — an item
# that is both committed AND in progress would have had no legal value.
FUTURE_KEY = "future"
FUTURE_VALUES = {"yes", "no"}
# A parking-lot file over this size is a REGISTER wearing an item's clothes. This is the exact
# shape being retired: `future-work-register.md` was 90,079 bytes and hid 3 open items among ~40
# resolved ones, so in practice nobody read it and its open items went unworked for weeks. The
# longest genuine single item in the same directory is 9,961 bytes, so 20 KB leaves real headroom.
PARKING_LOT_MAX_BYTES = 20_000


def _parse_frontmatter(text: str) -> dict:
    text = text.lstrip("﻿")
    if not text.startswith("---"):
        return {}
    lines = text.splitlines()
    if lines[0].strip() != "---":
        return {}
    fm: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm


def _phases_all_done(text: str) -> bool:
    headings = _PHASE_HEADING_RE.findall(text)
    if not headings:
        return False
    for h in headings:
        if any(m in h for m in _NOT_DONE_MARKERS):
            return False
        if not any(m in h for m in _DONE_MARKERS):
            return False
    return True


def classify_status(status: str | None, kind: str = "plans") -> str:
    """`terminal` (move it) / `active` (leave it) / `none` (no status field) / `unknown` (bad word).

    `unknown` is returned for parking-lot only. plans/prompts deliberately keep their open
    vocabulary — `draft`, `current`, `ready` and friends all mean "not finished" and the mover only
    ever needed to know "is this terminal?". parking-lot is a CLOSED vocabulary because its whole
    job is to be countable: "how many open items are there?" has no answer if `wip`, `todo` and
    `pending` are all legal spellings of the same state.
    """
    if status is None:
        return "none"
    s = status.strip().lower()
    if kind == PARKING_LOT_DIR:
        if s not in PARKING_LOT_STATUSES:
            return "unknown"
        return "terminal" if s in PARKING_LOT_TERMINAL else "active"
    return "terminal" if s in TERMINAL_STATUSES else "active"


@dataclass
class Item:
    path: Path
    status: str | None
    frontmatter: dict
    phases_all_done: bool
    size: int = 0


def scan(dir_path: Path) -> list[Item]:
    """Top-level `*.md` only — `done/` (or anything else nested) is excluded by construction."""
    if not dir_path.is_dir():
        return []
    items = []
    for f in sorted(dir_path.glob("*.md")):
        if f.name.lower() == "readme.md":
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        fm = _parse_frontmatter(text)
        items.append(Item(
            path=f,
            status=fm.get("status"),
            frontmatter=fm,
            phases_all_done=_phases_all_done(text),
            size=len(text.encode("utf-8")),
        ))
    return items


@dataclass
class Report:
    moved: list[Path] = field(default_factory=list)
    would_move: list[Path] = field(default_factory=list)
    stale_suspects: list[Path] = field(default_factory=list)
    frontmatter_less: list[Path] = field(default_factory=list)
    unknown_status: list[Path] = field(default_factory=list)
    collisions: list[Path] = field(default_factory=list)
    # Subset of frontmatter_less/unknown_status that ISN'T grandfathered by
    # LEGACY_FRONTMATTER_EXEMPT - these are what actually fail --check.
    check_flagged: list[Path] = field(default_factory=list)
    # parking-lot only. Each carries its own message because "your parking-lot item is wrong" is
    # useless to the agent that has to fix it - it needs to know WHICH rule and WHAT the legal
    # values are, in the failure text, without opening another document.
    violations: list[tuple[Path, str]] = field(default_factory=list)

    def check_violations(self) -> int:
        return len(self.check_flagged)

    def _flag(self, path: Path, message: str) -> None:
        self.violations.append((path, message))
        if path not in self.check_flagged:
            self.check_flagged.append(path)


def _is_git_repo(repo_root: Path) -> bool:
    return (repo_root / ".git").exists()


def _run_git_mv(repo_root: Path, src: Path, dst: Path) -> bool:
    """Returns True on success. Degrades to plain move (caller's job) on any failure."""
    try:
        result = subprocess.run(
            ["git", "mv", str(src), str(dst)],
            cwd=str(repo_root), capture_output=True, text=True, timeout=30,
        )
        return result.returncode == 0
    except Exception:
        return False


def _move_one(repo_root: Path, item: Item, apply: bool, report: Report) -> None:
    done_dir = item.path.parent / "done"
    dst = done_dir / item.path.name
    if dst.exists():
        report.collisions.append(item.path)
        return
    if not apply:
        report.would_move.append(item.path)
        return
    done_dir.mkdir(parents=True, exist_ok=True)
    moved_via_git = False
    if _is_git_repo(repo_root):
        moved_via_git = _run_git_mv(repo_root, item.path, dst)
    if not moved_via_git:
        dst.parent.mkdir(parents=True, exist_ok=True)
        item.path.rename(dst)
    report.moved.append(item.path)


def _is_legacy_exempt(repo_root: Path, path: Path) -> bool:
    try:
        rel = path.relative_to(repo_root / ".caddis").as_posix()
    except ValueError:
        return False
    return rel in LEGACY_FRONTMATTER_EXEMPT


def _check_parking_lot_item(item: Item, report: Report) -> None:
    """Validate ONE future-work item against the closed contract. Records every violation it finds,
    it does not stop at the first - an agent that fixes one rule per run needs three round trips."""
    fm = item.frontmatter
    if not fm:
        report.frontmatter_less.append(item.path)
        report._flag(item.path, "no frontmatter. A parking-lot item needs at least "
                                "`type: parking-lot` and `status: open`.")
        return

    got_type = (fm.get("type") or "").strip().lower()
    if got_type != PARKING_LOT_TYPE:
        shown = got_type or "(missing)"
        report._flag(item.path, f"type is `{shown}`, must be `{PARKING_LOT_TYPE}`. "
                                "Everything in this directory is one future-work item, whatever "
                                "it started life as.")

    cls = classify_status(item.status, PARKING_LOT_DIR)
    if cls == "none":
        report.frontmatter_less.append(item.path)
        report._flag(item.path, "no `status:` field. Use one of: "
                                f"{', '.join(sorted(PARKING_LOT_STATUSES))}.")
    elif cls == "unknown":
        report.unknown_status.append(item.path)
        report._flag(item.path, f"status is `{item.status}`, which is not a legal value. Use one "
                                f"of: {', '.join(sorted(PARKING_LOT_STATUSES))}.")

    if FUTURE_KEY in fm:
        val = (fm.get(FUTURE_KEY) or "").strip().lower()
        if val not in FUTURE_VALUES:
            report._flag(item.path, f"`{FUTURE_KEY}:` is `{val or '(empty)'}`, must be "
                                    f"{' or '.join(sorted(FUTURE_VALUES))}. `yes` means committed "
                                    "work, not a candidate.")

    if item.size > PARKING_LOT_MAX_BYTES:
        report._flag(item.path, f"{item.size:,} bytes, over the {PARKING_LOT_MAX_BYTES:,} byte "
                                "ceiling. This is a register, not one item. Split each open item "
                                "into its own file and move the resolved history to done/.")


def tidy(repo_root: Path, apply: bool = False, check: bool = False,
          kinds: tuple[str, ...] = _KINDS) -> Report:
    report = Report()
    for kind in kinds:
        items = scan(repo_root / ".caddis" / kind)
        for item in items:
            if kind == PARKING_LOT_DIR:
                _check_parking_lot_item(item, report)
                # A terminal item still moves even if it broke another rule. Sweeping finished work
                # out of the way is independent of whether its frontmatter was tidy.
                if classify_status(item.status, PARKING_LOT_DIR) == "terminal":
                    _move_one(repo_root, item, apply, report)
                continue
            cls = classify_status(item.status)
            if cls == "terminal":
                _move_one(repo_root, item, apply, report)
                continue
            if cls == "none":
                report.frontmatter_less.append(item.path)
                # never moved, never even attempted - the mover leaves it silently in --apply;
                # --check is what surfaces it (unless grandfathered as pre-convention legacy).
                if not _is_legacy_exempt(repo_root, item.path):
                    report.check_flagged.append(item.path)
                if item.phases_all_done:
                    report.stale_suspects.append(item.path)
                continue
            # active status
            if item.phases_all_done:
                report.stale_suspects.append(item.path)
    return report


def nudge_line(repo_root: Path) -> str | None:
    """The single SessionStart nudge line, or None. PURE dry-run scan (no subprocess, no LLM, no
    auto-fix), mirroring claudster_doctor.nudge_line's contract - visibility only, never a move."""
    try:
        report = tidy(repo_root, apply=False)
    except Exception:
        return None
    n = len(report.would_move)
    if not n:
        return None
    plural = "artifact" if n == 1 else "artifacts"
    return f"[caddis] {n} finished {plural} awaiting tidy — /handoff moves them"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Move terminal-status plans/prompts into done/")
    ap.add_argument("--repo-root", default=".", help="repo root containing .caddis/ (default: cwd)")
    ap.add_argument("--apply", action="store_true", help="actually move files (default: dry-run report)")
    ap.add_argument("--check", action="store_true",
                     help="conformance check - exit 1 if any top-level artifact lacks a known status")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    report = tidy(repo_root, apply=args.apply, check=args.check)

    mode = "APPLY" if args.apply else ("CHECK" if args.check else "DRY-RUN")
    print(f"[caddis_tidy] mode={mode} root={repo_root}")
    moved_or_would = report.moved if args.apply else report.would_move
    label = "moved" if args.apply else "would move"
    for p in moved_or_would:
        print(f"  {label}: {p.relative_to(repo_root)}")
    for p in report.collisions:
        print(f"  COLLISION (skipped, done/ already has this name): {p.relative_to(repo_root)}")
    for p in report.stale_suspects:
        print(f"  stale-suspect (all phases done, status still active): {p.relative_to(repo_root)}")
    if args.check:
        exempt = [p for p in report.frontmatter_less if p not in report.check_flagged]
        detailed = {p for p, _ in report.violations}
        for p, msg in report.violations:
            print(f"  CHECK VIOLATION: {p.relative_to(repo_root)}: {msg}")
        for p in report.check_flagged:
            if p not in detailed:
                print(f"  CHECK VIOLATION: no status field: {p.relative_to(repo_root)}")
        for p in exempt:
            print(f"  (legacy, grandfathered): {p.relative_to(repo_root)}")

    if args.check:
        return 1 if report.check_violations() else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
