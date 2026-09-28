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
- A plan's `## Tracker` decides when it is done (R2 Phase 10): when every phase row is `done`,
  tidy sets that plan's `status: done` and moves it. Nothing else sets it. Phase heading
  emoji do not count; they drifted from the Tracker in both directions.
- A `Resolves-Parked: <file>` trailer in the commits of `--commit-range` moves that parking-lot
  item to `done/` with `resolved_by: <short sha>`; `Partly-Resolves-Parked:` only appends a dated
  note. Unknown or out-of-directory names are reported, never created or moved.
- NEVER overwrites an existing `done/<name>`: if any destination exists, the run changes nothing
  at all (no move, no status line, no note) and reports the collision.
- `--prune` (R2 Phase 11) deletes old LOCAL state on fixed ages, with no settings: session-state
  files older than 7 days, and the two logs rotated above 5 MB into one `.1` copy. `.lock` files
  whose document is gone are only counted, never deleted. Only a file git both ignores and does not track qualifies. Relays,
  to-dos, symlinks and anything outside `.caddis/` are never touched; lane worktrees older than
  7 days are only reported. It lists by default; `--prune --apply` deletes.

Usage:
  python scripts/caddis_tidy.py                 # report only (default = dry-run)
  python scripts/caddis_tidy.py --apply          # actually move terminal-status artifacts
  python scripts/caddis_tidy.py --check          # conformance check; exit 1 on a violation
  python scripts/caddis_tidy.py --repo-root <p>  # scan a different repo (default: cwd)
  python scripts/caddis_tidy.py --commit-range origin/main..HEAD   # also read parking trailers
  python scripts/caddis_tidy.py --prune          # list old local state that could be deleted
  python scripts/caddis_tidy.py --prune --apply  # delete it (the user's choice, never automatic)
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

try:
    import caddis_frontmatter
except ModuleNotFoundError as exc:
    if exc.name != "caddis_frontmatter":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-harness" / "scripts"))
    import caddis_frontmatter

try:
    import caddis_todo
except ModuleNotFoundError as exc:
    if exc.name != "caddis_todo":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import caddis_todo
# caddis_todo has put its own dependencies on the path by now; this one ships beside it.
from caddis_file_lock import atomic_write  # noqa: E402

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

# A Markdown table rule such as `|---|:---:|`.
_TABLE_RULE_RE = re.compile(r"^\|(\s*:?-+:?\s*\|)+\s*$")
# Commit trailers that close or annotate a parking-lot item. Keys compare case-insensitively,
# as git's own trailer keys do.
_PARKED_TRAILERS = {"resolves-parked": "resolves", "partly-resolves-parked": "partly"}
# Fixed so `resolved_by:` does not depend on the machine's `core.abbrev`.
_SHA_ABBREV = "12"

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
    return caddis_frontmatter.parse(text)


def tracker_complete(text: str) -> bool:
    """True only when the `## Tracker` heading line has phase rows, all unique, all done.

    The table is read by caddis_todo.tracker_table, the same reader the open-work view uses, and
    a status cell is judged by the same `_is_done`. Stricter here on purpose: that view skips a
    row it cannot read, while a row this cannot read BLOCKS completion. Wrongly moving a live plan
    hides it; wrongly keeping a finished one costs a look.
    """
    table = caddis_todo.tracker_table(text)
    if table is None:
        return False
    columns, lines = table
    status_at = columns.index("status")
    seen: set[int] = set()
    for line in lines:
        row = line.strip()
        if not row.startswith("|") or _TABLE_RULE_RE.match(row):
            continue
        match = caddis_todo._PHASE.match(line)
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if match is None or len(cells) != len(columns):
            return False  # malformed
        number = int(match.group(1))
        if number in seen:
            return False  # two rows for one phase: which one is true is not knowable
        seen.add(number)
        if not caddis_todo._is_done(cells[status_at]):
            return False
    return bool(seen)


def _set_header(text: str, fields: dict[str, str]) -> str | None:
    """`text` with these top-level header keys set, every other byte kept. None when there is no
    header the shared reader accepts, or when the reader would not read the new values back."""
    bom = "\ufeff" if text.startswith("\ufeff") else ""
    lines = text[len(bom):].splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return None
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip("\r\n") == "---"), None)
    if end is None:
        return None
    eol = "\r\n" if lines[0].endswith("\r\n") else "\n"
    for key, value in fields.items():
        at = [i for i in range(1, end)
              if lines[i][:1].strip() and lines[i].partition(":")[0] == key]
        for i in at:
            lines[i] = f"{key}: {value}{eol}"
        if not at:
            lines.insert(end, f"{key}: {value}{eol}")
            end += 1
    out = bom + "".join(lines)
    header = caddis_frontmatter.parse(out)
    if any(header.get(key) != value for key, value in fields.items()):
        return None
    return out


def _read_exact(path: Path) -> str | None:
    """The file's text with its line endings untouched, or None if it is not clean UTF-8.
    A rewrite must never drop bytes the way a lenient read would."""
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


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
            phases_all_done=tracker_complete(text),
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
    # Plans whose Tracker is complete: their `status:` is (or would be) set to `done`.
    completed: list[Path] = field(default_factory=list)
    # Parking-lot items a `Resolves-Parked:` trailer closes, with the short sha that closed them.
    resolved: list[tuple[Path, str]] = field(default_factory=list)
    # Parking-lot items a `Partly-Resolves-Parked:` trailer annotates. They stay open.
    noted: list[Path] = field(default_factory=list)
    # Trailer names that were not acted on, with the reason: (name as written, why).
    parked_refused: list[tuple[str, str]] = field(default_factory=list)
    # Anything that stopped the run: a bad commit range (nothing changed) or an I/O failure.
    errors: list[str] = field(default_factory=list)
    # Subset of frontmatter_less/unknown_status that ISN'T grandfathered by
    # LEGACY_FRONTMATTER_EXEMPT - these are what actually fail --check.
    check_flagged: list[Path] = field(default_factory=list)
    # parking-lot only. Each carries its own message because "your parking-lot item is wrong" is
    # useless to the agent that has to fix it - it needs to know WHICH rule and WHAT the legal
    # values are, in the failure text, without opening another document.
    violations: list[tuple[Path, str]] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        """True when --apply must not (or did not) finish: a collision or an error."""
        return bool(self.collisions or self.errors)

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
            ["git", "mv", "--", str(src), str(dst)],
            cwd=str(repo_root), capture_output=True, text=True, timeout=30,
        )
        return result.returncode == 0
    except Exception:
        return False


def _destination(src: Path) -> Path:
    return src.parent / "done" / src.name


def _collides(src: Path) -> bool:
    done_dir = src.parent / "done"
    dst = _destination(src)
    return (done_dir.exists() and not done_dir.is_dir()) or dst.exists() or dst.is_symlink()


def _move_one(repo_root: Path, src: Path, report: Report) -> None:
    """One named `git mv` into the sibling `done/`; a plain rename when git cannot (no repo, or
    an untracked file). Only called once every destination is known to be free."""
    dst = _destination(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    moved_via_git = False
    if _is_git_repo(repo_root):
        moved_via_git = _run_git_mv(repo_root, src, dst)
    if not moved_via_git:
        src.rename(dst)
    report.moved.append(src)


@dataclass
class Resolution:
    """One parking-lot trailer from one commit in the range."""
    kind: str  # "resolves" or "partly"
    name: str  # the trailer value as written
    sha: str
    date: str  # the commit date, YYYY-MM-DD
    path: Path | None = None  # the open item; None when refused or already in done/
    problem: str | None = None  # why it was refused; None when it can be acted on


def _parked_target(root: Path, name: str) -> tuple[Path | None, str | None]:
    """Where a trailer value points: (open item, None), (None, None) when it is already in done/,
    or (None, reason) when it is refused or missing. Only a top-level item of this repo's
    `.caddis/parking-lot/` is ever a target, named bare, as `parking-lot/<file>` (what
    `caddis_todo.py done` prints) or by its repo-relative path. The last word is
    caddis_todo._resolves_path, the check `caddis_todo add --resolves` already applies."""
    lot = root / ".caddis" / PARKING_LOT_DIR
    posix = name.replace("\\", "/")
    if not posix:
        return None, "empty value"
    if posix.startswith("/") or re.match(r"^[A-Za-z]:", posix):
        return None, "refused: absolute path"
    parts = posix.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None, "refused: `.`, `..` and empty path parts are not allowed"
    # Exact prefixes only: `.caddis/foo.md` must not resolve to `.caddis/parking-lot/foo.md`.
    if parts[:2] == [".caddis", PARKING_LOT_DIR]:
        parts = parts[2:]
    elif parts[:1] == [PARKING_LOT_DIR]:
        parts = parts[1:]
    if len(parts) != 1:
        return None, f"refused: not a top-level item of .caddis/{PARKING_LOT_DIR}/"
    leaf = parts[0]
    path = lot / leaf
    # The exact name, not a case-insensitive filesystem's match: `git mv` needs the indexed name.
    listed = path.is_file() and not lot.is_symlink() and leaf in {p.name for p in lot.iterdir()}
    if not listed and not path.is_symlink():
        if (lot / "done" / leaf).is_file():
            return None, None  # closed by an earlier run: rerunning a range is a no-op
        return None, f"does not exist in .caddis/{PARKING_LOT_DIR}/"
    try:
        caddis_todo._resolves_path(root, f"{PARKING_LOT_DIR}/{leaf}")
    except (OSError, ValueError) as exc:
        return None, f"refused: {exc}"
    return path, None


def parked_resolutions(root: Path, commit_range: str) -> list[Resolution]:
    """Every `Resolves-Parked:` / `Partly-Resolves-Parked:` trailer in `commit_range`, oldest
    commit first. Reads git only; changes nothing. Raises ValueError when git cannot read the
    range, so the caller can refuse the whole run instead of acting on half an answer."""
    # `A..B` only: a bare ref would read the whole history, and `A...B` adds the base's own
    # commits, neither of which is the change being tidied.
    if commit_range.startswith("-") or commit_range.count("..") != 1 or "..." in commit_range:
        raise ValueError(f"not a commit range (use BASE..HEAD): {commit_range!r}")
    try:
        done = subprocess.run(
            ["git", "log", "--reverse", "--date=short", f"--abbrev={_SHA_ABBREV}",
             "--format=%h%x1f%cd%x1f%(trailers:only,unfold)%x1e", commit_range, "--"],
            cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"git log failed: {exc}") from exc
    if done.returncode != 0:
        raise ValueError(f"git log {commit_range} failed: {done.stderr.strip()}")
    found = []
    for record in done.stdout.split("\x1e"):
        fields = record.strip("\n").split("\x1f")
        if len(fields) != 3:
            continue
        sha, date, trailers = fields
        for line in trailers.splitlines():
            key, sep, value = line.partition(":")
            kind = _PARKED_TRAILERS.get(key.strip().lower())
            if not sep or kind is None:
                continue
            name = value.strip()
            path, problem = _parked_target(root, name)
            found.append(Resolution(kind, name, sha, date, path, problem))
    return found


def _with_note(text: str, line: str) -> str:
    """Append one note line, keeping consecutive notes together as one list."""
    eol = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    last = next((ln for ln in reversed(lines) if ln.strip()), "")
    lead = "" if last.startswith("- ") and ": partly resolved by " in last else eol
    body = text if text.endswith(("\n", "\r")) or not text else text + eol
    return f"{body}{lead}{line}{eol}"


def _plan_parked(root: Path, commit_range: str, report: Report,
                 moves: list[Path], rewrites: dict[Path, str]) -> None:
    try:
        found = parked_resolutions(root, commit_range)
    except ValueError as exc:
        report.errors.append(str(exc))
        return
    closing: dict[Path, Resolution] = {}
    for res in found:
        if res.problem:
            report.parked_refused.append((res.name, res.problem))
        elif res.path is not None and res.kind == "resolves":
            closing.setdefault(res.path, res)  # the oldest commit in the range closed it
    for path, res in closing.items():
        text = _read_exact(path)
        status = str(caddis_frontmatter.parse(text or "").get("status") or "").strip().lower()
        if status == "dropped":
            # `dropped` carries a written reason it was abandoned; a trailer must not overwrite it.
            report.parked_refused.append((res.name, "refused: the item is dropped"))
            continue
        new = None if text is None else _set_header(text, {"status": "done",
                                                           "resolved_by": res.sha})
        if new is None:
            report.parked_refused.append((res.name, "refused: no readable header to stamp"))
            continue
        rewrites[path] = new
        if path not in moves:
            moves.append(path)
        report.resolved.append((path, res.sha))
    for res in found:
        if res.kind != "partly" or res.problem or res.path is None or res.path in closing:
            continue
        text = rewrites.get(res.path) or _read_exact(res.path)
        if text is None:
            report.parked_refused.append((res.name, "refused: not clean UTF-8"))
            continue
        line = f"- {res.date}: partly resolved by {res.sha}"
        if line in text.splitlines():
            continue  # this commit's note is already there
        rewrites[res.path] = _with_note(text, line)
        if res.path not in report.noted:
            report.noted.append(res.path)


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
          kinds: tuple[str, ...] = _KINDS, commit_range: str | None = None) -> Report:
    """Plan every change first, then make all of them or none.

    Nothing is written until the whole set is known and every destination is free. One existing
    `done/<name>` (or an unreadable commit range) leaves every file exactly as it was.
    """
    report = Report()
    moves: list[Path] = []
    rewrites: dict[Path, str] = {}  # applied before the moves, so a failed move leaves a
    # finished status at the top level, where the next run moves it by status alone
    for kind in kinds:
        items = scan(repo_root / ".caddis" / kind)
        for item in items:
            if kind == PARKING_LOT_DIR:
                _check_parking_lot_item(item, report)
                # A terminal item still moves even if it broke another rule. Sweeping finished work
                # out of the way is independent of whether its frontmatter was tidy.
                if classify_status(item.status, PARKING_LOT_DIR) == "terminal":
                    moves.append(item.path)
                continue
            cls = classify_status(item.status)
            if cls == "terminal":
                moves.append(item.path)
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
            if item.phases_all_done and kind == "plans":
                text = _read_exact(item.path)
                new = None if text is None else _set_header(text, {"status": "done"})
                if new is not None:
                    rewrites[item.path] = new
                    moves.append(item.path)
                    report.completed.append(item.path)
                    continue
            if item.phases_all_done:
                report.stale_suspects.append(item.path)
    if commit_range is not None and PARKING_LOT_DIR in kinds:
        _plan_parked(repo_root, commit_range, report, moves, rewrites)

    report.collisions.extend(src for src in moves if _collides(src))
    if not apply:
        report.would_move.extend(src for src in moves if src not in report.collisions)
        return report
    if report.blocked:
        return report
    # Past this point only an I/O failure can stop the run. Every step is safe to repeat: a
    # written status or stamp that did not move yet is moved by status on the next run, and a
    # note already present is not appended again.
    try:
        for path, text in rewrites.items():
            atomic_write(path, text)
        for src in moves:
            _move_one(repo_root, src, report)
    except (OSError, ValueError) as exc:
        report.errors.append(f"stopped part-way, run again to finish: {exc}")
    return report


def nudge_line(repo_root: Path) -> str | None:
    """The single SessionStart nudge line, or None. PURE dry-run scan (no subprocess, no LLM, no
    auto-fix), mirroring claudster_doctor.nudge_line's contract - visibility only, never a move."""
    try:
        report = tidy(repo_root, apply=False)
    except Exception:
        return None
    if report.collisions:
        # /handoff cannot move anything while this stands, so do not send people there.
        return (f"[caddis] tidy is blocked by {len(report.collisions)} done/ name collision(s) "
                "— run scripts/caddis_tidy.py to see them")
    n = len(report.would_move)
    if not n:
        return None
    plural = "artifact" if n == 1 else "artifacts"
    return f"[caddis] {n} finished {plural} awaiting tidy — /handoff moves them"


# ── prune: old local state on fixed ages (R2 Phase 11) ──────────────────────────────────────────
# `.caddis/` grew without bound: one session-state file per session, a `.lock` left beside every
# document ever locked, and two append-only logs. These ages and sizes are FIXED on purpose; a
# settings surface for them was considered and rejected. Git decides what is local: a file is only
# ever listed when git both ignores it and does not track it, so a tracked or user-visible file can
# never be deleted, whatever its age. Outside a git repo that cannot be proven, so prune refuses.
PRUNE_MAX_AGE_S = 7 * 86_400
LOG_ROTATE_BYTES = 5 * 1024 * 1024
ROTATED_LOGS = ("usage-log.jsonl", "agent-log.jsonl")
# Top-level `.caddis/` folders never walked for locks: relays and to-dos have their own writers.
_PRUNE_SKIP_DIRS = {"relay", "todo-list"}
_LANE_BRANCH_PREFIX = "refs/heads/lane/"


@dataclass
class PruneReport:
    delete: list[Path] = field(default_factory=list)   # listed: old session-state files
    rotate: list[Path] = field(default_factory=list)   # listed: logs above LOG_ROTATE_BYTES
    # Report only. Deleting a lock a writer is waiting on lets a second writer create a new lock
    # file and enter at the same time (POSIX), so orphan locks are never deleted. They are empty.
    orphan_locks: list[Path] = field(default_factory=list)
    deleted: list[Path] = field(default_factory=list)
    rotated: list[Path] = field(default_factory=list)
    old_worktrees: list[tuple[Path, int]] = field(default_factory=list)  # (path, days); report only
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    refused: str | None = None


def _git_run(root: Path, *args: str, stdin: bytes | None = None):
    try:
        return subprocess.run(["git", "-C", str(root), *args], input=stdin,
                              capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None


def _prune_refusal(root: Path) -> str | None:
    """Why prune may not run here, or None. It needs the top of a git work tree."""
    result = _git_run(root, "rev-parse", "--is-inside-work-tree", "--show-cdup")
    if result is None or result.returncode != 0:
        return "not a git repository, so no file can be proven untracked."
    lines = result.stdout.decode("utf-8", "replace").splitlines()
    if not lines or lines[0].strip() != "true":
        return "not inside a git work tree."
    if len(lines) > 1 and lines[1].strip():
        return "not the top of its git repository; pass --repo-root <repo root>."
    if (root / ".caddis").is_symlink():
        return "`.caddis` is a symlink; prune never follows one."
    return None


def _regular(path: Path) -> os.stat_result | None:
    """lstat of a regular file, or None (missing, a symlink, a folder...). Links never followed."""
    try:
        st = os.lstat(path)
    except OSError:
        return None
    return st if stat.S_ISREG(st.st_mode) else None


def _old_session_states(caddis: Path, now: float) -> list[Path]:
    folder = caddis / "session-state"
    if folder.is_symlink() or not folder.is_dir():
        return []
    found = []
    for entry in os.scandir(folder):
        path = Path(entry.path)
        st = _regular(path)
        # Only `*.md`: the `.session-state-*.tmp` files are session_state.py's write scratch.
        if entry.name.endswith(".md") and st and now - st.st_mtime > PRUNE_MAX_AGE_S:
            found.append(path)
    return sorted(found)


def _orphan_locks(caddis: Path) -> list[Path]:
    """`x.lock` files whose document `x` is gone (the caddis_file_lock naming)."""
    found = []
    for dirpath, dirnames, filenames in os.walk(caddis, followlinks=False):
        at_top = Path(dirpath) == caddis
        if at_top:
            dirnames[:] = [d for d in dirnames if d not in _PRUNE_SKIP_DIRS]
        for name in filenames:
            if not name.endswith(".lock") or (at_top and name.startswith("relay.md")):
                continue
            path = Path(dirpath) / name
            if _regular(path) and not os.path.lexists(str(path)[:-len(".lock")]):
                found.append(path)
    return sorted(found)


def _local_only(root: Path, rels: list[str]) -> set[str] | None:
    """The subset of `rels` (repo-relative, posix) that git ignores and does not track."""
    if not rels:
        return set()
    tracked = _git_run(root, "ls-files", "-z", "--", ".caddis")
    ignored = _git_run(root, "check-ignore", "-z", "--stdin",
                       stdin=b"\0".join(r.encode("utf-8") for r in rels) + b"\0")
    # check-ignore exits 1 when nothing is ignored; anything else non-zero is a failure.
    if tracked is None or tracked.returncode != 0 or ignored is None or ignored.returncode > 1:
        return None
    tracked_set = set(tracked.stdout.decode("utf-8", "replace").split("\0"))
    ignored_set = set(ignored.stdout.decode("utf-8", "replace").split("\0"))
    return {r for r in rels if r in ignored_set and r not in tracked_set}


def _old_lane_worktrees(root: Path, now: float) -> list[tuple[Path, int]]:
    result = _git_run(root, "worktree", "list", "--porcelain")
    if result is None or result.returncode != 0:
        return []
    found = []
    for block in result.stdout.decode("utf-8", "replace").split("\n\n"):
        fields = dict(line.split(" ", 1) for line in block.splitlines() if " " in line)
        if not fields.get("branch", "").startswith(_LANE_BRANCH_PREFIX) or "worktree" not in fields:
            continue
        path = Path(fields["worktree"])
        try:
            touched = os.lstat(path).st_mtime
        except OSError:
            continue
        # The folder's mtime misses edits in subfolders, so a new commit also counts as use.
        head = _git_run(path, "log", "-1", "--format=%ct")
        if head is not None and head.returncode == 0 and head.stdout.strip().isdigit():
            touched = max(touched, int(head.stdout.strip()))
        age = now - touched
        if age > PRUNE_MAX_AGE_S:
            found.append((path, int(age // 86_400)))
    return found


def prune(root: Path, *, apply: bool = False, now: float | None = None) -> PruneReport:
    """List (or, with `apply`, delete) old local state under `<root>/.caddis/`."""
    root = Path(root)
    now = time.time() if now is None else now
    report = PruneReport()
    report.refused = _prune_refusal(root)
    if report.refused:
        return report
    caddis = root / ".caddis"
    if not caddis.is_dir():
        return report

    def rel(p: Path) -> str:
        return p.relative_to(root).as_posix()

    files = _old_session_states(caddis, now)
    locks = _orphan_locks(caddis)
    logs = []
    for name in ROTATED_LOGS:
        log = caddis / name
        st = _regular(log)
        if st and st.st_size > LOG_ROTATE_BYTES:
            logs.append(log)
    copies = {log: log.with_name(log.name + ".1") for log in logs}
    local = _local_only(root, [rel(p) for p in files + locks + logs]
                        + [rel(c) for c in copies.values()])
    if local is None:
        report.errors.append("git could not say which files are ignored; nothing was listed.")
        return report

    report.delete = [p for p in files if rel(p) in local]
    report.orphan_locks = [p for p in locks if rel(p) in local]
    for log in logs:
        copy = copies[log]
        if rel(log) not in local:
            continue
        if rel(copy) not in local:
            report.notes.append(f"not rotating {rel(log)}: {rel(copy)} is not gitignored, or is "
                                "tracked. Add it to .gitignore.")
        elif os.path.lexists(copy) and not _regular(copy):
            report.notes.append(f"not rotating {rel(log)}: {rel(copy)} is not a regular file.")
        else:
            report.rotate.append(log)
    report.old_worktrees = _old_lane_worktrees(root, now)
    if not apply:
        return report

    for path in report.delete:
        if not _regular(path):
            report.notes.append(f"skipped {rel(path)}: no longer a regular file.")
            continue
        try:
            os.unlink(path)
        except OSError as exc:
            report.errors.append(f"could not delete {rel(path)}: {exc}")
            continue
        report.deleted.append(path)
    for log in report.rotate:
        try:
            os.replace(log, copies[log])  # replaces the one `.1` copy; there is never a `.2`
            report.rotated.append(log)
        except OSError as exc:
            report.errors.append(f"could not rotate {rel(log)}: {exc}")
    return report


def _print_prune(root: Path, report: PruneReport, apply: bool) -> int:
    def rel(p: Path) -> str:
        return p.relative_to(root).as_posix()

    print(f"[caddis_tidy] mode=PRUNE-{'APPLY' if apply else 'LIST'} root={root}")
    if report.refused:
        print(f"  REFUSED: {report.refused} Nothing was listed or deleted.")
        return 1
    for p in (report.deleted if apply else report.delete):
        print(f"  {'deleted' if apply else 'would delete'} (session state older than 7 days): "
              f"{rel(p)}")
    if report.orphan_locks:
        print(f"  {len(report.orphan_locks)} orphan lock file(s) left in place (report only; "
              "empty files, and deleting a lock a writer waits on is unsafe)")
    for p in (report.rotated if apply else report.rotate):
        print(f"  {'rotated' if apply else 'would rotate'} (over 5 MB): {rel(p)} -> {rel(p)}.1")
    for path, days in report.old_worktrees:
        print(f"  lane worktree {days} days old (report only; `caddis_lanes.py abandon` removes "
              f"it): {path}")
    for note in report.notes:
        print(f"  NOTE: {note}")
    for msg in report.errors:
        print(f"  ERROR: {msg}")
    if not apply and (report.delete or report.rotate):
        print("  Run `caddis_tidy.py --prune --apply` to delete these. That is the user's choice.")
    elif not (report.delete or report.rotate or report.old_worktrees or report.orphan_locks
              or report.notes or report.errors):
        print("  nothing to prune.")
    return 1 if report.errors else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Move finished plans, prompts and parking-lot items "
                                             "into done/")
    ap.add_argument("--repo-root", default=".", help="repo root containing .caddis/ (default: cwd)")
    ap.add_argument("--apply", action="store_true", help="actually move files (default: dry-run report)")
    ap.add_argument("--check", action="store_true",
                     help="conformance check - exit 1 if any top-level artifact lacks a known status")
    ap.add_argument("--commit-range", default=None,
                     help="also read Resolves-Parked / Partly-Resolves-Parked trailers in these "
                          "commits only, e.g. origin/main..HEAD (default: read no trailers)")
    ap.add_argument("--prune", action="store_true",
                    help="list old local state under .caddis/ (with --apply: delete it)")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    if args.prune:
        if args.check or args.commit_range:
            ap.error("--prune runs alone: not with --check or --commit-range")
        return _print_prune(repo_root, prune(repo_root, apply=args.apply), args.apply)
    report = tidy(repo_root, apply=args.apply, check=args.check, commit_range=args.commit_range)

    def rel(p: Path) -> str:
        return p.relative_to(repo_root).as_posix()

    mode = "APPLY" if args.apply else ("CHECK" if args.check else "DRY-RUN")
    print(f"[caddis_tidy] mode={mode} root={repo_root}")
    done_now = args.apply and not report.blocked
    for msg in report.errors:
        print(f"  ERROR: {msg}")
    for p in report.completed:
        print(f"  {'set' if done_now else 'would set'} status: done (Tracker complete): {rel(p)}")
    for p, sha in report.resolved:
        print(f"  {'resolved' if done_now else 'would resolve'}: {rel(p)} (Resolves-Parked in {sha})")
    for p in report.noted:
        print(f"  {'noted' if done_now else 'would note'}: {rel(p)} (Partly-Resolves-Parked)")
    moved_or_would = report.moved if args.apply else report.would_move
    label = "moved" if args.apply else "would move"
    for p in moved_or_would:
        print(f"  {label}: {rel(p)}")
    for name, why in report.parked_refused:
        print(f"  REFUSED trailer `{name}`: {why}")
    for p in report.collisions:
        print(f"  COLLISION (done/ already has this name): {rel(p)}")
    if report.blocked:
        print("  BLOCKED: " + ("nothing was changed." if args.apply else
                               "--apply would change nothing.")
              + " Fix the collision or error above and run again.")
    for p in report.stale_suspects:
        print(f"  stale-suspect (all phases done, status still active): {rel(p)}")
    if args.check:
        exempt = [p for p in report.frontmatter_less if p not in report.check_flagged]
        detailed = {p for p, _ in report.violations}
        for p, msg in report.violations:
            print(f"  CHECK VIOLATION: {rel(p)}: {msg}")
        for p in report.check_flagged:
            if p not in detailed:
                print(f"  CHECK VIOLATION: no status field: {rel(p)}")
        for p in exempt:
            print(f"  (legacy, grandfathered): {rel(p)}")

    # A collision is reported, not fatal: /handoff and /implement surface it and carry on.
    if report.errors:
        return 1
    if args.check:
        return 1 if report.check_violations() else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
