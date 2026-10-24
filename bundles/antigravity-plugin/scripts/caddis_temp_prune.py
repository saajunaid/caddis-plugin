"""Expire old scratchpads and caddis test leftovers in the temp folder (tidy v2, Phase 3).

`caddis_tidy.py --prune --temp` calls `prune_temp`. Dry run is the default: it only lists. With `apply` it deletes.
Two groups, each listed with its size and age:

1. Scratch sessions: `<temp>/claude/<project>/<id>/` (Claude Code's session scratchpads and task logs).
2. Test leftovers: folders directly in the temp folder whose name starts with a prefix caddis itself makes.

A folder is listed only when ALL hold (anything in doubt is KEPT, and said so):
  - the newest mtime of the folder and of everything in it is older than the age limit (7 days);
  - scratch only: no transcript `<claude config>/projects/*/<id>.jsonl` changed within the limit, the id is not one of
    the running session's ids, and the process cwd is not inside it;
  - it is not a link and holds no link at any depth (kept, with the link and its target named; links are never
    followed and never removed here);
  - it holds no `.git` (a repo or a worktree): kept, with a note;
  - the scan could read every folder.
A folder with something newer than the limit inside is not listed and not mentioned: it is live or recent.

Apply, per folder: scan again, rename it to `<name>.caddis-trash-<stamp>` in the same parent (atomic; it fails when a
process holds a file in it, and the folder is then KEPT as "in use"), then `caddis_worktree_safety.remove_tree` on the
renamed folder (links first). If that fails part-way the renamed path is reported as an error; there is no retry.
An emptied `<project>` folder is removed with `os.rmdir` (only an empty one can go).

    prune_temp(apply=False, temp_root=None, claude_config=None, now=None, env_session_ids=None, cwd=None) -> TempReport
    format_report(report, apply) -> list of printable lines
"""

from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import caddis_worktree_safety as safety

MAX_AGE_S = 7 * 86_400
TRASH_MARK = ".caddis-trash-"
# The running session's id, from the environment (as caddis_created.SESSION_ENV_VARS).
SESSION_ENV_VARS = ("CADDIS_SESSION_ID", "CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID")

# Only folders whose name starts with one of these are test leftovers. Each prefix maps to the code that makes it.
# Never add another tool's prefix (playwright* and the like). A new caddis prefix goes here with its maker.
CADDIS_TEMP_PREFIXES = {
    "caddis-roadmap-": "scripts/caddis_roadmap.py mkdtemp (also caddis-roadmap-check-)",
    "caddis-docs-pr-": "scripts/caddis_docs_pr.py DIR_PREFIX (temp worktree of a docs PR)",
    "caddis-review-": "scripts/caddis_review.py _add_worktree (temp review worktree)",
    "caddis-relay-index-": "scripts/caddis_relay_git.py TemporaryDirectory",
    "caddis-init-": "scripts/claudster_init.py TemporaryDirectory",
    "caddis-fresh-": "scripts/fresh_install_test.ps1 probe folder",
    "caddis-rev-": "scripts/fresh_install_test.ps1 probe folder",
    "caddis-eval-": "evals/run_evals.py mkdtemp",
    "caddis-agy-": "cli/src/agents/agy.ts stageForAgy, cli/test/agy.test.ts",
    "caddis-codex-": "cli/test/codex.test.ts mkdtempSync",
    "caddis-doctor-home-": "cli/test/doctor.test.ts mkdtempSync",
    "caddis-doctor-sessions-": "cli/test/doctor.test.ts mkdtempSync",
    "caddis-hub-": "cli/test/hub/*.test.ts mkdtempSync",
    "caddis-keys-": "cli/test/providers.test.ts mkdtempSync",
    "caddis-sessions-": "cli/test/sessions.test.ts mkdtempSync",
    "caddis-stub-": "cli/test/stub.test.ts mkdtempSync",
}
# A prefix above that can also match a folder that must stay: kept, with this reason.
KEEP_PREFIXES = {
    "caddis-agy-backup-": "cli/src/agents/agy.ts keeps a failed install's backup here: it may be the only whole "
                          "copy of the agy plugin",
}

_walk = os.walk  # a seam for tests


@dataclass
class Found:
    path: Path
    size: int
    age_days: int
    kind: str  # "scratch" | "leftover"


@dataclass
class Kept:
    path: Path
    code: str  # link | git | unreadable | in-use | changed | backup | config
    why: str


@dataclass
class TempReport:
    temp_root: Path
    scratch: list[Found] = field(default_factory=list)
    leftovers: list[Found] = field(default_factory=list)
    kept: list[Kept] = field(default_factory=list)
    removed: list[Found] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _env_session_ids() -> set[str]:
    return {v.strip() for v in (os.environ.get(name) for name in SESSION_ENV_VARS) if v and v.strip()}


def _same_or_inside(inner: Path | str, outer: Path | str) -> bool:
    a = os.path.normcase(os.path.realpath(inner))
    b = os.path.normcase(os.path.realpath(outer))
    return a == b or a.startswith(b.rstrip("\\/") + os.sep)


def _link_target(path: str) -> str:
    try:
        return os.readlink(path)
    except OSError:
        return "?"


def _inspect(path: Path, cutoff: float) -> tuple[str, float, int, str, str]:
    """(state, newest mtime, size, code, why). state: "young" (something inside is newer than `cutoff`),
    "kept" (a link, a git folder or an unreadable folder: `code` and `why` say which) or "old". Links are never
    entered: each one is found by lstat, because os.walk does not see a Windows junction as a link."""
    try:
        top = os.lstat(path)
    except OSError as exc:
        return "kept", 0.0, 0, "unreadable", f"cannot inspect {path}: {exc}"
    if safety.is_link(top):
        return "kept", top.st_mtime, 0, "link", f"is a link -> {_link_target(str(path))}"
    newest = top.st_mtime
    size = 0
    problem: tuple[str, str] | None = None
    if newest >= cutoff:
        return "young", newest, size, "", ""

    def fail(exc: OSError) -> None:
        nonlocal problem
        problem = problem or ("unreadable", f"unreadable folder {getattr(exc, 'filename', None) or path}: {exc}")

    try:
        for here, dirs, files in _walk(path, topdown=True, onerror=fail, followlinks=False):
            descend = []
            for name in dirs:
                full = os.path.join(here, name)
                st = os.lstat(full)
                newest = max(newest, st.st_mtime)
                if safety.is_link(st):
                    problem = problem or ("link", f"holds a link {full} -> {_link_target(full)}")
                elif name == ".git":
                    problem = problem or ("git", f"holds a git repo at {here}")
                else:
                    descend.append(name)
            dirs[:] = descend
            for name in files:
                full = os.path.join(here, name)
                st = os.lstat(full)
                newest = max(newest, st.st_mtime)
                size += st.st_size
                if safety.is_link(st):
                    problem = problem or ("link", f"holds a link {full} -> {_link_target(full)}")
                elif name == ".git":
                    problem = problem or ("git", f"holds a git worktree at {here} (.git file)")
            if newest >= cutoff:
                return "young", newest, size, "", ""
    except OSError as exc:
        problem = problem or ("unreadable", f"cannot scan {path}: {exc}")
    if problem:
        return "kept", newest, size, problem[0], problem[1]
    return "old", newest, size, "", ""


def _transcript_times(config: Path) -> dict[str, float] | None:
    """The newest mtime of every `<config>/projects/*/<id>.jsonl`, by id. None when any folder cannot be read:
    then nobody can say which sessions are live."""
    newest: dict[str, float] = {}
    try:
        with os.scandir(config / "projects") as projects:
            for project in projects:
                if not project.is_dir():
                    continue
                with os.scandir(project.path) as entries:
                    for entry in entries:
                        if entry.name.endswith(".jsonl") and entry.is_file():
                            stem = entry.name[:-len(".jsonl")]
                            newest[stem] = max(newest.get(stem, 0.0), entry.stat().st_mtime)
    except OSError:
        return None
    return newest


def _subfolders(folder: Path, cutoff: float, report: TempReport) -> list[Path]:
    """Real sub-folders of `folder`. An old link is noted and skipped; a young one is silent."""
    found = []
    try:
        with os.scandir(folder) as entries:
            for entry in sorted(entries, key=lambda e: e.name):
                path = Path(entry.path)
                st = os.lstat(path)
                if safety.is_link(st):
                    if st.st_mtime < cutoff:
                        report.kept.append(Kept(path, "link", f"is a link -> {_link_target(str(path))}; never followed"))
                elif entry.is_dir(follow_symlinks=False):
                    found.append(path)
    except OSError as exc:
        report.kept.append(Kept(folder, "unreadable", f"cannot list {folder}: {exc}"))
    return found


def _consider(report: TempReport, path: Path, kind: str, cutoff: float, now: float, cwd: Path | None) -> None:
    if cwd is not None and _same_or_inside(cwd, path):
        return  # the process works here
    state, newest, size, code, why = _inspect(path, cutoff)
    if state == "young":
        return
    if state == "kept":
        report.kept.append(Kept(path, code, why))
        return
    lowered = path.name.lower()
    if kind == "leftover" and any(lowered.startswith(p) for p in KEEP_PREFIXES):
        reason = next(r for p, r in KEEP_PREFIXES.items() if lowered.startswith(p))
        report.kept.append(Kept(path, "backup", reason))
        return
    found = Found(path, size, int((now - newest) // 86_400), kind)
    (report.scratch if kind == "scratch" else report.leftovers).append(found)


def _scan_scratch(report: TempReport, config: Path, env_ids: set[str], cwd: Path | None, cutoff: float,
                  now: float) -> None:
    base = report.temp_root / "claude"
    try:
        st = os.lstat(base)
    except FileNotFoundError:
        return
    except OSError as exc:
        report.kept.append(Kept(base, "unreadable", f"cannot inspect {base}: {exc}"))
        return
    if safety.is_link(st):
        report.kept.append(Kept(base, "link", "is a link; scratch sessions were not scanned"))
        return
    transcripts = _transcript_times(config)
    if transcripts is None:
        report.kept.append(Kept(base, "config", f"cannot read the transcript folders under {config / 'projects'}, "
                                                "so no scratch session can be called ended; none was scanned"))
        return
    for project in _subfolders(base, cutoff, report):
        for session in _subfolders(project, cutoff, report):
            if session.name in env_ids or transcripts.get(session.name, 0.0) >= cutoff:
                continue  # a live session
            _consider(report, session, "scratch", cutoff, now, cwd)


def _scan_leftovers(report: TempReport, cwd: Path | None, cutoff: float, now: float) -> None:
    prefixes = tuple(CADDIS_TEMP_PREFIXES)
    try:
        with os.scandir(report.temp_root) as entries:
            names = sorted(e.name for e in entries if e.name.lower().startswith(prefixes))
    except OSError as exc:
        report.errors.append(f"cannot list the temp folder {report.temp_root}: {exc}")
        return
    for name in names:
        path = report.temp_root / name
        try:
            st = os.lstat(path)
        except OSError:
            continue
        if safety.is_link(st):
            if st.st_mtime < cutoff:
                report.kept.append(Kept(path, "link", f"is a link -> {_link_target(str(path))}; never followed"))
            continue
        if os.path.isdir(path):
            _consider(report, path, "leftover", cutoff, now, cwd)


def _remove(report: TempReport, found: Found, cutoff: float, stamp: str) -> None:
    path = found.path
    state = _inspect(path, cutoff)[0]
    if state != "old":
        report.kept.append(Kept(path, "changed", "changed since the scan (or is no longer plain old files); kept"))
        return
    trash = path.with_name(f"{path.name}{TRASH_MARK}{stamp}")
    n = 1
    while os.path.lexists(trash):
        n += 1
        trash = path.with_name(f"{path.name}{TRASH_MARK}{stamp}-{n}")
    try:
        os.rename(path, trash)  # atomic; fails cleanly when a process holds a file inside
    except OSError as exc:
        report.kept.append(Kept(path, "in-use", f"in use: {exc}"))
        return
    problem = safety.remove_tree(trash)
    if problem:
        report.errors.append(f"partly deleted; what is left is at {trash}: {problem}")
        return
    report.removed.append(found)


def prune_temp(*, apply: bool = False, temp_root: Path | str | None = None, claude_config: Path | str | None = None,
               now: float | None = None, env_session_ids: set[str] | None = None, cwd: Path | str | None = None,
               max_age_s: int = MAX_AGE_S) -> TempReport:
    """List (or, with `apply`, delete) old scratch sessions and caddis test leftovers. Never raises for a folder
    it cannot read: that folder is kept and noted."""
    now = time.time() if now is None else now
    cutoff = now - max_age_s
    root = Path(temp_root) if temp_root is not None else Path(tempfile.gettempdir())
    if claude_config is not None:
        config = Path(claude_config)
    else:
        config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
    env_ids = _env_session_ids() if env_session_ids is None else set(env_session_ids)
    if cwd is not None:
        here: Path | None = Path(cwd)
    else:
        try:
            here = Path(os.getcwd())
        except OSError:
            here = None
    report = TempReport(temp_root=root)
    _scan_scratch(report, config, env_ids, here, cutoff, now)
    _scan_leftovers(report, here, cutoff, now)
    if apply:
        stamp = time.strftime("%Y%m%d%H%M%S", time.gmtime(now))
        for found in report.scratch + report.leftovers:
            _remove(report, found, cutoff, stamp)
        for parent in sorted({f.path.parent for f in report.removed if f.kind == "scratch"}):
            try:
                os.rmdir(parent)  # only an empty project folder goes
            except OSError:
                pass
    return report


def _human(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


COMPACT_LISTED = 10   # entries shown per group when not verbose (the largest)
COMPACT_EXAMPLES = 5  # example paths shown per kept reason when not verbose


def format_report(report: TempReport, apply: bool, verbose: bool = False) -> list[str]:
    """The lines `caddis_tidy.py --prune --temp` prints. Compact by default, in list and apply mode alike: per group
    one total line (count, size, age range) and the 10 largest folders; kept folders grouped by reason with a count
    and 5 example paths. `verbose` prints every folder and every kept note."""
    gone = {f.path for f in report.removed}
    lines = [f"  temp folder: {report.temp_root}"]
    for title, group in (("scratch sessions", report.scratch), ("test leftovers", report.leftovers)):
        total = f"{len(group)} folder(s), {_human(sum(f.size for f in group))}"
        if group:
            ages = [f.age_days for f in group]
            total += f", {min(ages)}-{max(ages)} days old"
        lines.append(f"  {title}: {total}" + (" (ended sessions)" if title == "scratch sessions" else ""))
        shown = sorted(group, key=lambda f: str(f.path)) if verbose else             sorted(group, key=lambda f: (-f.size, str(f.path)))[:COMPACT_LISTED]
        for f in shown:
            verb = ("deleted" if f.path in gone else "not deleted") if apply else "would delete"
            lines.append(f"    {verb}: {f.path} ({_human(f.size)}, {f.age_days} days)")
        if len(group) > len(shown):
            lines.append(f"    ... {len(group) - len(shown)} more (--verbose lists all)")
    if apply:
        lines.append(f"  deleted: {len(report.removed)} folder(s), {_human(sum(f.size for f in report.removed))}")
    if report.kept:
        by_code: dict[str, list[Kept]] = {}
        for k in report.kept:
            by_code.setdefault(k.code, []).append(k)
        lines.append(f"  kept: {len(report.kept)} folder(s)")
        for code, items in sorted(by_code.items()):
            lines.append(f"    kept ({code}): {len(items)} folder(s)")
            shown_kept = items if verbose else items[:COMPACT_EXAMPLES]
            for k in shown_kept:
                lines.append(f"      {k.path}: {k.why}")
            if len(items) > len(shown_kept):
                lines.append(f"      ... {len(items) - len(shown_kept)} more (--verbose lists all)")
    for message in report.errors:
        lines.append(f"  ERROR: {message}")
    if not apply and (report.scratch or report.leftovers):
        lines.append("  Run `caddis_tidy.py --prune --temp --apply` to delete these. That is the user's choice.")
    elif not (report.scratch or report.leftovers or report.kept or report.errors):
        lines.append("  nothing to prune in the temp folder.")
    return lines
