"""Read a roadmap from the default branch on origin, pick the next batch, and change the roadmap only by docs PRs.

The roadmap file `.caddis/roadmaps/<slug>/roadmap.md` on `origin/<default>` is the only truth. Every command runs
`git fetch origin` first and reads the roadmap and plans with `git show origin/<default>:<path>`; it never reads the
working tree. A phase ref `p-alpha#2` is done only when its Tracker Status cell in the origin copy of
`.caddis/plans/p-alpha.md` (or `.caddis/plans/done/p-alpha.md`) starts with `done` or a check mark.

Rules the runner trusts unattended:
- a malformed roadmap fails closed: every command but `check` refuses (exit 4) and prints the parse errors;
- only `rollup` writes Status `done`, and only with every phase merged and no open blocker but `data-condition`;
- `rollup` also needs every `Depends on` milestone `done` or `not-needed`;
- `next` skips a milestone whose first not-done phase is held by another live runner lock (`<plan>#<n>` from a
  roadmap runner, `<plan>#*` from a plan-mode runner; `<git common dir>/caddis-runner/<roadmap|plan>-<slug>/runner.lock`, and persistent claims in
  `<git common dir>/caddis-runner/claims/`);
- a calendar blocker's Check is an ISO date `YYYY-MM-DD`; `recheck` clears it once the date has passed (UTC) and
  never runs it; a calendar row whose Check is `-` stays until it is unblocked;
- `set` Status `not-needed` needs `--reason "dropped: <why>"` or `--reason .caddis/parking-lot/<file>.md` (on
  origin); the reason lands as `- <id> not-needed: <reason> (<date>)` under `## Notes` in the same PR;
- `status` adds `old blockers: <id> <type> (<N> days)` for a blocker row older than 14 days; the age is the date of
  the newest commit on origin that added that exact row (`git log -S`), so the roadmap never holds it;
- owner-only changes (`set` Status `not-needed`, any `set` Owner, `unblock` of an `owner-gate`, `block --check`) need
  `--by-owner` and are refused headless: CADDIS_HEADLESS or CLAUDECODE in the
  environment (any value, even empty), stdin not a terminal, or (Windows) stdin not a console (a NUL stdin is not);
- Exit check and Check commands run in a temporary worktree of `origin/<default>` (the merged code), with no stdin,
  in their own process group (a job object on Windows); the tree is killed on every exit;
- that worktree has no venv, no node_modules and no build. An optional roadmap line `**Exit setup:** <command>` runs
  first in it (900 s) and must install fresh into it; a failing setup is exit 3 and writes nothing. An exit check
  that fails because the environment is missing (ENV_FAILURE_PATTERNS, exit 9009/127/126) is exit 3 and writes
  nothing; a real failure writes an `external` blocker whose reason ends with the masked tail of the output (one
  line, the whole cell at most 200 characters; deduped and unblocked by its stable `exit check failing (exit N)`
  part). Both keep the last 64 KB of output (masked) in `.caddis/roadmaps/<slug>/.local/exit-check-<id>-<utc>.log`
  (the newest 10 per roadmap);
- every network call has a timeout (git fetch/ls-remote/push 120 s, gh 60 s, the merge chain 1800 s) and runs with
  GIT_TERMINAL_PROMPT=0 and GCM_INTERACTIVE=never; a timeout is exit 3 (a merge-chain timeout is logged as
  "merge_exit": "timeout"); Ctrl+C kills the tree too;
- `## Milestones` and `## Blockers` hold only blank lines, ONE table whose every line starts with `|`, and prose with
  no unescaped `|` set apart from the table by a blank line; any other line is a parse error (exit 4).
- a roadmap is a whitelist: ATX headings, plain paragraphs, lists and pipe tables (with a strict delimiter row) only.
  A code fence, an HTML comment or block, a setext heading, a control character, a lone CR, a line or paragraph
  separator, non-ASCII whitespace or a zero-width character anywhere is a parse error (exit 4): GitHub would hide,
  split or move lines this parser reads.

Writes (`set`, `block`, `unblock`, `rollup`, `recheck`) take `<git common dir>/caddis-roadmaps/<slug>.write.lock`,
commit on a `roadmap/<slug>-<id>-<utc>` branch made from `origin/<default>` in a temp worktree, push, open a PR with
`gh api` (the account comes from GH_TOKEN when set) and hand it to `caddis_merge_chain.py --docs-only`. `--dry-run`
prints the diff it would write and the commands it would run, and runs and writes nothing.

Exit codes (caddis_exit): 0 clean, 1 blocked (nothing ready, check failing, PR not merged), 3 could not run
(no origin, no roadmap, lock busy, an exit check or Exit setup that cannot run in the merged checkout), 4 error
(malformed roadmap, unknown id, column or value, refused change).

Usage: caddis_roadmap.py status --roadmap SLUG [--root DIR] [--json]
       caddis_roadmap.py next --roadmap SLUG [--root DIR] [--json]
       caddis_roadmap.py check --roadmap SLUG [--root DIR]
       caddis_roadmap.py set --roadmap SLUG [--root DIR] --id ID --col Status|Owner|Target --value V [--by-owner]
                         [--reason "dropped: WHY" | --reason .caddis/parking-lot/FILE.md] [--dry-run]
       caddis_roadmap.py block --roadmap SLUG [--root DIR] --id ID --type TYPE --reason TEXT [--check CMD --by-owner]
                         [--dry-run]
       caddis_roadmap.py unblock --roadmap SLUG [--root DIR] --id ID --type TYPE --reason TEXT [--check CMD]
                         [--by-owner] [--dry-run]
       caddis_roadmap.py rollup --roadmap SLUG [--root DIR] --id ID [--dry-run]
       caddis_roadmap.py recheck --roadmap SLUG [--root DIR] [--dry-run]
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import difflib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path

try:
    import caddis_exit
    import caddis_redact
    import caddis_rows
    import caddis_worktree_safety
except ModuleNotFoundError as exc:
    if exc.name not in {"caddis_exit", "caddis_redact", "caddis_rows", "caddis_worktree_safety"}:
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-harness" / "scripts"))
    import caddis_exit
    import caddis_redact
    import caddis_rows
    import caddis_worktree_safety

# No child process opens a console window on Windows (this runs under hooks and status lines that
# have no console). Inline, not scripts/no_window.py: in the source tree this file does not sit beside it.
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

SCRIPTS_DIR = Path(__file__).resolve().parent
STATUSES = ("todo", "in-progress", "code-done/data-pending", "done", "not-needed")
FINISHED = ("done", "not-needed")
OPEN = ("todo", "in-progress")
BLOCKER_TYPES = ("owner-gate", "external", "shared", "calendar", "data-condition")
SETTABLE = ("Status", "Owner", "Target")
MILESTONE_COLS = ["ID", "Milestone", "Phases", "Depends on", "Exit check", "Status", "Owner", "Target"]
BLOCKER_COLS = ["Milestone", "Type", "Reason", "Check"]
HEADLESS_VARS = ("CADDIS_HEADLESS", "CLAUDECODE")
EXIT_CHECK_TIMEOUT = 300
EXIT_SETUP_TIMEOUT = 900  # a fresh venv + pip install, or npm ci + a build, is slower than a check
RECHECK_TIMEOUT = 120
# Exit codes of a shell that could not start the command: 9009 cmd.exe "not recognized", 127 sh "command not
# found", 126 sh "found but not executable".
SHELL_CANNOT_RUN_CODES = (9009, 127, 126)
# Output that says the merged checkout lacks the project's environment (no venv, no node_modules, no build), not that
# the product fails (serve-sight #301). Matched case-insensitively, only on a check that exits non-zero; a match is
# NOT_RUN (exit 3): no blocker, no PR. Each pattern has a sample in test_caddis_roadmap.py ENV_SAMPLES.
ENV_FAILURE_PATTERNS = (
    "not recognized as an internal or external command",  # cmd.exe: the tool is not on PATH
    "command not found",  # sh / bash: the tool is not on PATH
    "No module named",  # Python: no venv, or a package not installed
    "ModuleNotFoundError",  # Python: the same, as a traceback names it
    "Cannot find module",  # Node (CommonJS): no node_modules
    "ERR_MODULE_NOT_FOUND",  # Node (ES modules): no node_modules
    "ENOENT",  # Node: a file or binary that a build or an install makes is missing
    "run npm run build first",  # a check that needs the front-end bundle
    "is not installed",  # a tool or a browser (Playwright) that an install step adds
    "could not find a version",  # pip: a package index the setup cannot reach
)
ENV_FAILURE_RE = re.compile("|".join(re.escape(p) for p in ENV_FAILURE_PATTERNS), re.IGNORECASE)
ENV_SCAN_LINES = 40  # the patterns are searched only in this many last non-empty output lines
REASON_TAIL_LINES = 3  # a real failure's blocker reason ends with this many last non-empty output lines
REASON_CELL_CHARS = 200  # the whole stored Reason cell of a rollup blocker, after every escape
ROLLUP_PREFIX_RE = re.compile(r"exit check failing \((?:exit -?\d+|timed out after \d+ s)\)")  # its stable part
KEEP_CHECK_LOGS = 10  # exit-check-*.log files kept per roadmap; older ones are removed
# Masks for the output tail that goes to origin and for the local log, after caddis_redact (which masks only the
# values of secret-named variables). The token rules are copied from the high-confidence SECRET_RULES in
# .github/tools/secret_filter.py (that folder is not on this script's import path in an installed plugin).
OUTPUT_MASKS: list[tuple[re.Pattern, str]] = [
    # secret_filter private-key, widened to the WHOLE block: BEGIN to END, or to the end of the output with no END.
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.DOTALL), "***"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "***"),  # secret_filter aws-key
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), "***"),  # secret_filter github-token
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), "***"),  # secret_filter slack-token
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "***"),  # secret_filter jwt
    # secret_filter assignment, widened: a quoted value may hold spaces (a passphrase of several words).
    (re.compile(r"(?i)([A-Za-z0-9_]*(?:password|passwd|secret|api[_-]?key|token)[A-Za-z0-9_]*\s*[:=]\s*)"
                r"(['\"])[^'\"\n]{8,}\2"), r"\1\2***\2"),
    (re.compile(r"(?im)^(\s*(?:export\s+)?[A-Za-z0-9_]*(?:PASSWORD|PASSWD|SECRET|API_KEY|APIKEY|TOKEN|PRIVATE_KEY)"
                r"[A-Za-z0-9_]*\s*=\s*)[^\s'\"#]{8,}"), r"\1***"),  # secret_filter env-assignment
    (re.compile(r"\b([A-Za-z][A-Za-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@"), r"\1***@"),  # URL credentials
    # Absolute paths, which can name a user or a host. A path may hold spaces, so each one runs to the end of the
    # line or a quote; a Windows drive or UNC path also stops at `<`, `>` or `|` (never part of a Windows path).
    (re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\r\n'\"<>|]*"), "<path>"),  # a Windows drive path
    (re.compile(r"(?<![\w\\])\\\\[^\s\\'\"<>|]+\\[^\r\n'\"<>|]*"), "<path>"),  # a UNC path
    (re.compile(r"(?<![\w:/.~-])/(?:home|Users|tmp|root|var|etc|opt)/[^\r\n'\"]*"), "<path>"),  # a POSIX path
]
EXIT_SETUP_RE = re.compile(r"^\*\*Exit setup:\*\*[ \t]*(.*?)[ \t]*$")
LOCK_TIMEOUT = 30
LOCK_MALFORMED_STALE_S = 60  # an empty or non-JSON lock file older than this is stale
_WINDOWS = os.name == "nt"  # a create can fail with PermissionError while a deleted lock's delete is pending
OUTPUT_TAIL_BYTES = 64 * 1024
OUTPUT_FILE_CAP = 1024 * 1024  # a check's on-disk output never grows past this
GIT_NET_TIMEOUT = 120
GH_TIMEOUT = 60
MERGE_CHAIN_TIMEOUT = 1800
GIT_NETWORK_CMDS = ("fetch", "ls-remote", "push")
NO_PROMPT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
WINDOWS = os.name == "nt"
SLUG_RE_TEXT = r"^[a-z0-9][a-z0-9-]{0,62}$"  # THE roadmap slug rule; roadmap-run.ps1 and roadmap-recheck.ps1 use it
SLUG_RE = re.compile(SLUG_RE_TEXT)
ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
REF_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)#(\d+)$")
PIPE_RE = re.compile(r"(?<!\\)\|")  # an unescaped pipe
HOST_RE = re.compile(r"^Runner host:\s*(.*?)\s*$")
HEADING_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*#*[ \t]*$")  # [ \t], never \s: NBSP is no space
FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
DEP_CITE_RE = re.compile(r"\(dep[^)]*:\s*[A-Za-z]+-?\d+\)", re.IGNORECASE)
GH_URL_RE = re.compile(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")  # a calendar blocker's Check
PARKING_RE = re.compile(r"^\.caddis/parking-lot/[A-Za-z0-9._-]+\.md$")  # a not-needed reason that names a parked item
DROPPED_PREFIX = "dropped:"
OLD_BLOCKER_DAYS = 14  # status lists a blocker whose row is older than this


class RoadmapError(Exception):
    """A refused or impossible request; carries the caddis exit code."""

    def __init__(self, message: str, code: int = caddis_exit.ERROR):
        super().__init__(message)
        self.code = code


# -- git -------------------------------------------------------------------------------------------------------


# The login this process's own git, gh and merge-chain calls use (GH_TOKEN from the runner's --gh-account). It is
# never put in os.environ, so a session or lane started from os.environ cannot inherit it (robustness #4).
AUTH_ENV: dict[str, str] = {}


def _quiet_env() -> dict:
    """The environment for git, gh and the merge chain: never wait for a credential prompt. A fresh dict each call,
    with AUTH_ENV on top."""
    env = dict(os.environ)
    env.update(NO_PROMPT_ENV)
    env.update(AUTH_ENV)
    return env


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    argv = ["git", "-C", str(root), *args]
    if args and args[0] in GIT_NETWORK_CMDS:
        proc = run_bounded(argv, GIT_NET_TIMEOUT, f"git {args[0]}")
    else:
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              stdin=subprocess.DEVNULL, env=_quiet_env(), creationflags=_NO_WINDOW)
    if check and proc.returncode != 0:
        raise RoadmapError(f"git {' '.join(args)} failed: {(proc.stderr or proc.stdout).strip()[:300]}",
                           caddis_exit.NOT_RUN)
    return proc


def default_branch(root: Path) -> str:
    """origin/HEAD's branch; when it is not set locally, ask the remote (`git ls-remote --symref origin HEAD`)."""
    proc = _git(root, "symbolic-ref", "refs/remotes/origin/HEAD", check=False)
    ref = proc.stdout.strip()
    if proc.returncode == 0 and ref.startswith("refs/remotes/origin/"):
        return ref[len("refs/remotes/origin/"):]
    remote = _git(root, "ls-remote", "--symref", "origin", "HEAD", check=False)
    for line in remote.stdout.splitlines():
        match = re.match(r"^ref:\s*refs/heads/(\S+)\s+HEAD$", line)
        if match:
            return match.group(1)
    raise RoadmapError("cannot tell origin's default branch: origin/HEAD is not set and the remote did not say",
                       caddis_exit.NOT_RUN)


def fetch(root: Path) -> str:
    """Fetch origin and return the default branch name."""
    _git(root, "fetch", "--quiet", "origin")
    return default_branch(root)


def show(root: Path, branch: str, path: str) -> str | None:
    proc = subprocess.run(["git", "-C", str(root), "show", f"origin/{branch}:{path}"], capture_output=True,
                          stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
    if proc.returncode != 0:
        return None
    # Bytes, not text mode: text mode would turn CRLF into LF and a write would change every line ending.
    return proc.stdout.decode("utf-8", errors="replace")


def gh_repo_of(root: Path) -> str | None:
    """OWNER/NAME from `git remote get-url origin`, or None when origin is not a GitHub URL."""
    url = _git(root, "remote", "get-url", "origin", check=False).stdout.strip()
    match = GH_URL_RE.search(url)
    return f"{match.group(1)}/{match.group(2)}" if match else None


def roadmap_path(slug: str) -> str:
    return f".caddis/roadmaps/{slug}/roadmap.md"


def local_dir(root: Path, slug: str) -> Path:
    return root / ".caddis" / "roadmaps" / slug / ".local"


def lock_path(root: Path, slug: str) -> Path:
    """The write lock lives in the git common dir, so every worktree of one repo shares it."""
    common = Path(_git(root, "rev-parse", "--git-common-dir").stdout.strip())
    if not common.is_absolute():
        common = Path(root) / common
    return common.resolve() / "caddis-roadmaps" / f"{slug}.write.lock"


# -- parsing ---------------------------------------------------------------------------------------------------


def _mask_fences(lines: list[str]) -> list[str]:
    """Blank every line of a fenced code block (fence lines included), keeping line numbers.

    CommonMark: a fence opens with 3+ backticks or tildes (up to 3 spaces of indent); it closes only on a line of the
    same character, at least as long, with nothing else on it. A line with an info string never closes it.
    """
    out: list[str] = []
    fence: str | None = None
    for line in lines:
        if fence is None:
            match = FENCE_OPEN_RE.match(line)
            if match and not (match.group(1)[0] == "`" and "`" in match.group(2)):
                fence = match.group(1)
                out.append("")
            else:
                out.append(line)
            continue
        stripped = line.strip()
        # A tab before the fence is 4 columns of indent in CommonMark, so it never closes a fence.
        if (len(line) - len(line.lstrip(" ")) <= 3 and line.lstrip(" ").startswith(fence[0])
                and len(stripped) >= len(fence)
                and set(stripped) == {fence[0]}):
            fence = None
        out.append("")
    return out


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(c and set(c) <= set("-: ") and "-" in c for c in cells)


@dataclass
class Table:
    heading: str  # the heading line, stripped ("" when none)
    header_idx: int
    rows: list[int]
    columns: list[str]


def _is_strict_delimiter(header: list[str], cells: list[str]) -> bool:
    """A GFM delimiter row: every cell is `:?-+:?`, and there are as many cells as in the header row."""
    return bool(cells) and len(cells) == len(header) and all(STRICT_DELIM_CELL_RE.match(c) for c in cells)


def _scan(text: str) -> tuple[list[str], list[str], list[Table], list[str]]:
    """(lines, masked lines, tables, layout errors) for a plan: fenced code is skipped."""
    lines = text.splitlines()
    return _tables(lines, _mask_fences(lines), strict=False)


def _tables(lines: list[str], masked: list[str], strict: bool) -> tuple[list[str], list[str], list[Table], list[str]]:
    """Pipe lines that do not form a table are errors. `strict` (a roadmap) also needs a GFM delimiter row."""
    tables: list[Table] = []
    errors: list[str] = []
    heading = ""
    i, n = 0, len(masked)
    while i < n:
        line = masked[i]
        if HEADING_RE.match(line):
            heading = line.strip()
        if line.lstrip().startswith("|") and not line.startswith("|"):
            errors.append(f"line {i + 1}: indented table row `{line.strip()[:60]}`")
            i += 1
            continue
        if not line.startswith("|"):
            i += 1
            continue
        start = i
        i += 1
        # A table is the run of lines that start with `|`. A line after it without a leading pipe is not a row; in
        # `## Milestones` and `## Blockers` it is a parse error (see _strict_sections).
        while i < n and masked[i].startswith("|"):
            i += 1
        delim = caddis_rows.split_cells(masked[start + 1]) if i - start >= 2 else []
        is_table = (_is_strict_delimiter(caddis_rows.split_cells(masked[start]), delim) if strict
                    else _is_separator(delim))
        if is_table:
            tables.append(Table(heading, start, list(range(start + 2, i)), caddis_rows.split_cells(masked[start])))
        else:
            for idx in range(start, i):
                errors.append(f"line {idx + 1}: table row outside a table (no header and separator above it): "
                              f"`{masked[idx].strip()[:60]}`")
    return lines, masked, tables, errors


STRICT_SECTIONS = ("## Milestones", "## Blockers")
STRICT_DELIM_CELL_RE = re.compile(r"^[ \t]*:?-+:?[ \t]*$")
HTML_TABLE_RE = re.compile(r"^\s*<(table|tr)\b", re.IGNORECASE)


def _strict_sections(masked: list[str]) -> list[str]:
    """Errors for `## Milestones` and `## Blockers` (each until the next heading of level 1 or 2).

    Allowed: blank lines, ONE table whose every line starts with `|`, and prose with no unescaped `|`, set apart
    from the table by a blank line. Anything else could hide a row from this parser and fails closed. Fenced code
    is already blanked in `masked` (a roadmap has none: it is refused).
    """
    errors: list[str] = []
    section: str | None = None
    in_table = table_seen = False
    prev_blank = True
    for i, line in enumerate(masked):
        heading = HEADING_RE.match(line)
        if heading and len(heading.group(1)) <= 2:
            section = line.strip() if line.strip() in STRICT_SECTIONS else None
            in_table = table_seen = False
            prev_blank = True
            continue
        if section is None:
            continue
        where = f"line {i + 1}: in `{section}`"
        if not line.strip():
            in_table, prev_blank = False, True
            continue
        if line.startswith("|"):
            if not in_table:
                if table_seen:
                    errors.append(f"{where}: a second table; a section holds exactly one table")
                elif not prev_blank:
                    errors.append(f"{where}: the table starts directly after a prose line; put a blank line between")
                table_seen = in_table = True
        elif in_table:
            errors.append(f"{where}: a line directly after the table without a blank line (a row must start with "
                          f"`|`; prose needs a blank line before it): `{line.strip()[:60]}`")
        elif HTML_TABLE_RE.match(line):
            errors.append(f"{where}: an HTML table line; use a pipe table: `{line.strip()[:60]}`")
        elif PIPE_RE.search(line):
            errors.append(f"{where}: a `|` outside the table (a headerless table or prose with a pipe); "
                          f"escape it as `\\|`: `{line.strip()[:60]}`")
        prev_blank = False
    return errors


def _cell_text(cell: str) -> str:
    """A cell's text: `\\|` unescaped, one pair of wrapping backticks removed, `-` means empty."""
    value = cell.replace("\\|", "|").strip()
    if len(value) >= 2 and value.startswith("`") and value.endswith("`") and value.count("`") == 2:
        value = value[1:-1].strip()
    return "" if value == "-" else value


def _list_cell(cell: str) -> list[str]:
    value = _cell_text(cell)
    return [item.strip() for item in value.split(",") if item.strip()] if value else []


@dataclass
class Milestone:
    id: str
    name: str
    phases: list[str]
    depends: list[str]
    exit_check: str
    status: str
    owner: str
    target: str
    line: int


@dataclass
class Blocker:
    milestone: str
    type: str
    reason: str
    check: str
    line: int

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.milestone, self.type, self.reason, self.check)


@dataclass
class Roadmap:
    runner_host: str = ""
    exit_setup: str = ""  # the `**Exit setup:**` command run before an Exit check; empty when there is none
    milestones: list[Milestone] = field(default_factory=list)
    blockers: list[Blocker] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    blocker_table: Table | None = None

    def get(self, mid: str) -> Milestone | None:
        return next((m for m in self.milestones if m.id == mid), None)

    def blockers_of(self, mid: str) -> list[Blocker]:
        return [b for b in self.blockers if b.milestone == mid]


def _section(tables: list[Table], name: str, columns: list[str], errors: list[str]) -> Table | None:
    """The one table under exactly `## <name>`; a near-miss heading or a second table is an error."""
    exact = f"## {name}"
    found: Table | None = None
    for table in tables:
        heading_text = HEADING_RE.match(table.heading).group(2) or "" if table.heading else ""
        looks_like = heading_text.lower().startswith(name.lower().rstrip("s")) or table.columns == columns
        if table.heading == exact:
            if found is not None:
                errors.append(f"line {table.header_idx + 1}: a second table under `{exact}`")
            else:
                found = table
        elif looks_like:
            errors.append(f"line {table.header_idx + 1}: a {name} table under `{table.heading or '(no heading)'}`; "
                          f"the heading must be exactly `{exact}`")
    if found is None:
        errors.append(f"no table under `{exact}`")
    elif found.columns != columns:
        errors.append(f"{name} columns are {found.columns}, want {columns}")
        return None
    return found


HTML_COMMENT_RE = re.compile(r"<!--|-->")
# An HTML block start: `<` then a letter, `/`, `!` or `?` (CommonMark block types 1-7), at any indent. An autolink
# (`<https://x>`, `<a@b.c>`) is not HTML and is allowed.
HTML_BLOCK_RE = re.compile(r"^[ \t]*<[A-Za-z/!?]")
AUTOLINK_RE = re.compile(r"^[ \t]*<(?:[A-Za-z][A-Za-z0-9+.-]{1,31}:[^ \t<>]*|[^ \t<>@]+@[^ \t<>]+)>")
SETEXT_RE = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*$")
# A table delimiter row with no pipe (`:-`, `:-:`, `-:`) makes GitHub render a one-column table.
PIPELESS_DELIM_RE = re.compile(r"^[ \t]*(?::-+:?|-+:)[ \t]*$")
# A code fence opener at any indent, also inside a list item or a block quote (`- ```, `1. ~~~`, `> ````).
ANY_FENCE_RE = re.compile(r"^[ \t]*(?:(?:[-*+>]|\d{1,9}[.)])[ \t]*)*(?:```|~~~)")
# Characters that end or split a line for some reader but not for GitHub (or the reverse): C0 controls but tab and
# LF, DEL, NEL, U+2028 and U+2029. A CR is allowed only as part of CRLF (CRLF is made LF before this check).
BAD_CHAR_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\x85\u2028\u2029\r]")
FRONTMATTER_FENCE_RE = re.compile(r"^---[ \t]*$")


def _frontmatter_end(lines: list[str]) -> int:
    """The index of the `---` line that closes a YAML frontmatter block opened on line 1, or -1 when there is none."""
    if not lines or not FRONTMATTER_FENCE_RE.match(lines[0]):
        return -1
    return next((i for i in range(1, len(lines)) if FRONTMATTER_FENCE_RE.match(lines[i])), -1)


def _char_name(ch: str) -> str:
    name = unicodedata.name(ch, "")
    return f"U+{ord(ch):04X}" + (f" {name}" if name else "")


def _roadmap_lines(text: str) -> tuple[list[str], int, list[str]]:
    """(lines, frontmatter end index, errors). One BOM at the start is dropped, CRLF becomes LF, and the text is split
    on LF only: never splitlines(), which also splits on form feed, NEL, U+2028 and others where GitHub does not.

    Refused anywhere: BAD_CHAR_RE. Refused outside the frontmatter: non-ASCII whitespace (category Zs) and format
    characters (category Cf: a zero-width space, a BOM that is not at the start, bidi marks).
    """
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.replace("\r\n", "\n").split("\n")
    front_end = _frontmatter_end(lines)
    errors: list[str] = []
    for i, line in enumerate(lines):
        bad = set(BAD_CHAR_RE.findall(line))
        if i > front_end:
            bad |= {ch for ch in line if ord(ch) > 0x7F and unicodedata.category(ch) in ("Zs", "Cf")}
        if bad:
            names = ", ".join(_char_name(ch) for ch in sorted(bad))
            errors.append(f"line {i + 1}: a control, line-separator, non-ASCII space or zero-width character "
                          f"({names}); a roadmap allows plain text only")
    return lines, front_end, errors


def _hidden_markup(lines: list[str], front_end: int) -> list[str]:
    """Errors for markup GitHub renders differently from this parser. A roadmap is a whitelist, so each fails closed.

    A code fence (also one in a list item or a block quote) hides lines on GitHub, and where it opens and closes is
    easy to make disagree, so a roadmap has none. An HTML comment or block hides lines on GitHub that this parser
    reads. A setext heading (a text line with a `===` or `---` line under it) is a heading on GitHub but not here,
    so a table after it would render outside the section this parser puts it in.
    """
    errors: list[str] = []
    for i, line in enumerate(lines):
        where = f"line {i + 1}"
        if ANY_FENCE_RE.match(line):
            errors.append(f"{where}: a code fence (``` or ~~~); a roadmap allows no code fences, use inline code: "
                          f"`{line.strip()[:60]}`")
        elif HTML_COMMENT_RE.search(line):
            errors.append(f"{where}: an HTML comment (`<!--` or `-->`) can hide lines on GitHub; write it as plain "
                          f"prose: `{line.strip()[:60]}`")
        elif HTML_BLOCK_RE.match(line) and not AUTOLINK_RE.match(line):
            errors.append(f"{where}: an HTML block line can hide lines on GitHub; use Markdown: "
                          f"`{line.strip()[:60]}`")
        elif 0 < i < front_end and "|" in line:
            errors.append(f"{where}: a `|` in the frontmatter; GitHub may render a frontmatter it cannot read as "
                          f"Markdown, so a roadmap's frontmatter holds no table characters")
        elif i > front_end and PIPELESS_DELIM_RE.match(line):
            errors.append(f"{where}: `{line.strip()}` is a table delimiter row with no pipe, so GitHub renders a "
                          f"one-column table here; remove it")
        elif (i > front_end and i > 0 and SETEXT_RE.match(line) and lines[i - 1].strip()
              and not lines[i - 1].startswith("|") and not HEADING_RE.match(lines[i - 1])):
            errors.append(f"{where}: a setext heading underline under `{lines[i - 1].strip()[:40]}`; use an ATX "
                          f"heading (`## ...`), or put a blank line above a `---` break")
    return errors


def parse_roadmap(text: str) -> Roadmap:
    """Parse a roadmap. Line numbers index `text` split on LF; the frontmatter is not read (GitHub shows it apart)."""
    rm = Roadmap()
    raw, front_end, char_errors = _roadmap_lines(text)
    view = [""] * (front_end + 1) + raw[front_end + 1:]
    lines, _view, tables, rm.errors = _tables(view, view, strict=True)
    rm.errors[:0] = char_errors
    rm.errors.extend(_hidden_markup(raw, front_end))
    rm.errors.extend(_strict_sections(view))
    rm.runner_host = next((m.group(1) for m in map(HOST_RE.match, view) if m), "")
    if not rm.runner_host:
        rm.errors.append("no `Runner host: <host>` line")
    setups = [(i, m.group(1)) for i, m in enumerate(map(EXIT_SETUP_RE.match, view)) if m]
    if len(setups) > 1:
        rm.errors.append("more than one `**Exit setup:**` line (lines "
                         + ", ".join(str(i + 1) for i, _ in setups) + "); a roadmap has at most one")
    elif setups:
        rm.exit_setup = _cell_text(setups[0][1])

    table = _section(tables, "Milestones", MILESTONE_COLS, rm.errors)
    seen: set[str] = set()
    for idx in table.rows if table else []:
        cells = caddis_rows.split_cells(lines[idx])
        if len(cells) != len(MILESTONE_COLS):
            rm.errors.append(f"line {idx + 1}: {len(cells)} cells, want {len(MILESTONE_COLS)}")
            continue
        ms = Milestone(id=_cell_text(cells[0]), name=cells[1], phases=_list_cell(cells[2]),
                       depends=_list_cell(cells[3]), exit_check=_cell_text(cells[4]), status=_cell_text(cells[5]),
                       owner=_cell_text(cells[6]), target=_cell_text(cells[7]), line=idx)
        if not ID_RE.match(ms.id):
            rm.errors.append(f"line {idx + 1}: milestone id `{ms.id}` is not [A-Za-z0-9_-]+")
            continue
        if ms.id in seen:
            rm.errors.append(f"line {idx + 1}: duplicate ID {ms.id}")
        seen.add(ms.id)
        if ms.status not in STATUSES:
            rm.errors.append(f"{ms.id}: Status `{ms.status}` is not one of {', '.join(STATUSES)}")
        for ref in ms.phases:
            if not REF_RE.match(ref):
                rm.errors.append(f"{ms.id}: phase ref `{ref}` is not <plan>#<phase>")
        rm.milestones.append(ms)
    for ms in rm.milestones:
        for dep in ms.depends:
            if dep not in seen:
                rm.errors.append(f"{ms.id}: Depends on unknown milestone {dep}")

    rm.blocker_table = _section(tables, "Blockers", BLOCKER_COLS, rm.errors)
    for idx in rm.blocker_table.rows if rm.blocker_table else []:
        cells = caddis_rows.split_cells(lines[idx])
        if len(cells) != len(BLOCKER_COLS):
            rm.errors.append(f"line {idx + 1}: {len(cells)} cells, want {len(BLOCKER_COLS)}")
            continue
        b = Blocker(milestone=_cell_text(cells[0]), type=_cell_text(cells[1]),
                    reason=cells[2].replace("\\|", "|").strip(), check=_cell_text(cells[3]), line=idx)
        if b.type not in BLOCKER_TYPES:
            rm.errors.append(f"line {idx + 1}: blocker type `{b.type}` is not one of {', '.join(BLOCKER_TYPES)}")
        if b.milestone not in seen:
            rm.errors.append(f"line {idx + 1}: blocker on unknown milestone `{b.milestone}`")
        rm.blockers.append(b)
    return rm


def parse_tracker(text: str) -> dict[int, str]:
    """Phase number -> Status cell, from the table under a `## Tracker...` heading."""
    lines, _masked, tables, _errors = _scan(text)
    for table in tables:
        if "tracker" not in table.heading.lower():
            continue
        cols = [c.strip().lower() for c in table.columns]
        if "phase" not in cols or "status" not in cols:
            continue
        p_idx, s_idx = cols.index("phase"), cols.index("status")
        out: dict[int, str] = {}
        for idx in table.rows:
            cells = caddis_rows.split_cells(lines[idx])
            if len(cells) <= max(p_idx, s_idx):
                continue
            num = re.sub(r"^(phase\s*|p)", "", cells[p_idx].strip(), flags=re.IGNORECASE)
            if num.isdigit():
                out[int(num)] = cells[s_idx].strip()
        return out
    return {}


def _is_done_status(cell: str) -> bool:
    value = cell.strip().lstrip("*").strip()
    return value.lower().startswith("done") or value.startswith("✅")


class PhaseIndex:
    """Phase done-ness read from the origin copy of each plan's Tracker; cached per command."""

    def __init__(self, root: Path, branch: str):
        self.root, self.branch = root, branch
        self._trackers: dict[str, dict[int, str] | None] = {}

    def tracker(self, plan: str) -> dict[int, str] | None:
        if plan not in self._trackers:
            text = show(self.root, self.branch, f".caddis/plans/{plan}.md")
            if text is None:
                text = show(self.root, self.branch, f".caddis/plans/done/{plan}.md")
            self._trackers[plan] = parse_tracker(text) if text is not None else None
        return self._trackers[plan]

    def state(self, ref: str) -> str:
        """'done', 'open' or 'unknown'."""
        match = REF_RE.match(ref)
        if not match:
            return "unknown"
        rows = self.tracker(match.group(1))
        if rows is None or int(match.group(2)) not in rows:
            return "unknown"
        return "done" if _is_done_status(rows[int(match.group(2))]) else "open"


# -- loading ----------------------------------------------------------------------------------------------------


@dataclass
class Snapshot:
    root: Path
    slug: str
    branch: str
    text: str
    roadmap: Roadmap
    phases: PhaseIndex
    errors: list[str]


def load(root: Path, slug: str, strict: bool = True) -> Snapshot:
    """Fetch and read the origin copy. strict: any parse error or unknown phase ref refuses (exit 4)."""
    if not SLUG_RE.match(slug):
        raise RoadmapError(f"bad roadmap slug `{slug}`")
    root = Path(root)
    branch = fetch(root)
    text = show(root, branch, roadmap_path(slug))
    if text is None:
        raise RoadmapError(f"{roadmap_path(slug)} is not on origin/{branch}", caddis_exit.NOT_RUN)
    rm = parse_roadmap(text)
    phases = PhaseIndex(root, branch)
    errors = list(rm.errors)
    for ms in rm.milestones:
        for ref in ms.phases:
            if REF_RE.match(ref) and phases.state(ref) == "unknown":
                errors.append(f"{ms.id}: unknown phase ref {ref} (no such plan or Tracker row on origin/{branch})")
    if strict and errors:
        raise RoadmapError(f"{roadmap_path(slug)} on origin/{branch} has {len(errors)} error(s); fix it by a PR:\n"
                           + "\n".join(f"  - {e}" for e in errors))
    return Snapshot(root, slug, branch, text, rm, phases, errors)


# -- reading commands ------------------------------------------------------------------------------------------


def runner_ineligible(rm: Roadmap, ms: Milestone) -> str | None:
    """Why the runner may not act on this milestone (its phases or its rollup), or None. The ONE rule both `next` and
    the runner's rollup sweep use: every Depends on milestone finished, no blocker, Owner the runner (or empty)."""
    unmet = [d for d in ms.depends if rm.get(d) is None or rm.get(d).status not in FINISHED]
    if unmet:
        return "depends on " + ", ".join(f"{d} ({rm.get(d).status if rm.get(d) else 'unknown'})" for d in unmet)
    blocks = rm.blockers_of(ms.id)
    if blocks:
        return "; ".join(f"blocked: {b.type} {b.reason}" for b in blocks)
    if ms.owner not in ("", "runner"):
        return f"owner {ms.owner} (not the runner)"
    return None


def _select(snap: Snapshot, skip: dict | None = None,
            held_out: list | None = None) -> tuple[dict | None, list[tuple[str, str]]]:
    """The first ready milestone's first not-done phase, and why each milestone before it was skipped.

    `skip` maps a batch (`<plan>#<n>`, or `<plan>#*` for a whole plan) to what holds it (a label, or a
    live_runner_holders dict); any held batch of a plan holds every phase of that plan: a milestone whose first
    not-done phase is in a held plan is skipped (never its later phases
    instead: phases of a milestone run in order). `held_out`, when given, receives one dict per held skip
    (`ref`, `kind`, `holder`) so callers never parse the reason text."""
    skip = skip or {}
    rm = snap.roadmap
    reasons: list[tuple[str, str]] = []
    for ms in rm.milestones:
        if ms.status not in OPEN:
            reasons.append((ms.id, f"status {ms.status}"))
            continue
        not_runners = runner_ineligible(rm, ms)
        if not_runners:
            reasons.append((ms.id, not_runners))
            continue
        states = [(ref, snap.phases.state(ref)) for ref in ms.phases]
        unknown = [ref for ref, state in states if state == "unknown"]
        if unknown:
            reasons.append((ms.id, "unknown phase ref " + ", ".join(unknown)))
            continue
        ref = next((r for r, state in states if state == "open"), None)
        if ref is None:
            reasons.append((ms.id, "every phase merged; waits for rollup"))
            continue
        # A plan in flight anywhere holds the WHOLE plan: any held `<plan>#<n>` (or `<plan>#*`) holds every phase.
        held = skip.get(ref) or skip.get(f"{match_ref(ref)}#*") or next(
            (h for batch, h in skip.items() if match_ref(batch) == match_ref(ref)), None)
        if held:
            reasons.append((ms.id, f"phase {ref} is held by {holder_label(held)}"))
            if held_out is not None:
                held_out.append({"ref": ref, **(held if isinstance(held, dict) else {"kind": "lock", "holder": held})})
            continue
        match = REF_RE.match(ref)
        assert match
        return {"milestone": ms.id, "plan": match.group(1), "phase": int(match.group(2))}, reasons
    return None, reasons


def match_ref(ref: str) -> str:
    """The plan of a phase ref `<plan>#<n>`."""
    return ref.split("#", 1)[0]


def next_with_snapshot(root: Path, slug: str) -> tuple[dict | None, Snapshot]:
    """The next batch (as next_batch) and the origin snapshot it was chosen from (one fetch)."""
    snap = load(Path(root), slug)
    batch, _reasons = _select(snap, other_roadmap_batches(Path(root), slug))
    return batch, snap


def next_batch(root: Path, slug: str) -> dict | None:
    return next_with_snapshot(root, slug)[0]


def _utc_today() -> datetime.date:
    return datetime.datetime.now(datetime.timezone.utc).date()


def iso_date(value: str) -> datetime.date | None:
    """The date of a calendar Check (`YYYY-MM-DD`, backticks allowed), or None when it is not a real ISO date."""
    text = (value or "").strip().strip("`").strip()
    if not ISO_DATE_RE.match(text):
        return None
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        return None


def blocker_since(root: Path, branch: str, slug: str, row_line: str) -> datetime.date | None:
    """The date of the newest commit on origin/<branch> that changed the count of this exact row line in the roadmap
    (for a row that exists now: the commit that added it). None on any error. The roadmap text never holds the date."""
    try:
        proc = _git(Path(root), "log", "-1", "--format=%cs", "-S", row_line, f"origin/{branch}", "--",
                    roadmap_path(slug), check=False)
        if proc.returncode != 0:
            return None
        return datetime.date.fromisoformat(proc.stdout.strip())
    except Exception:  # age is advice: it never breaks status
        return None


def _old_blockers(snap: Snapshot, today: datetime.date) -> list[str]:
    """`<id> <type> (<N> days)` for each blocker of an unfinished milestone older than OLD_BLOCKER_DAYS, oldest
    first."""
    rm = snap.roadmap
    lines = snap.text.splitlines()
    aged: list[tuple[int, int, str]] = []
    for ms in rm.milestones:
        if ms.status in FINISHED:
            continue
        for b in rm.blockers_of(ms.id):
            if not 0 <= b.line < len(lines):
                continue
            since = blocker_since(snap.root, snap.branch, snap.slug, lines[b.line])
            if since is None:
                continue
            days = (today - since).days
            if days > OLD_BLOCKER_DAYS:
                aged.append((-days, len(aged), f"{b.milestone} {b.type} ({days} day{'' if days == 1 else 's'})"))
    return [text for _days, _order, text in sorted(aged)]


def status(root: Path, slug: str, today: datetime.date | None = None) -> dict:
    snap = load(Path(root), slug)
    rm = snap.roadmap
    batch, _reasons = _select(snap, other_roadmap_batches(Path(root), slug))
    milestones = []
    for ms in rm.milestones:
        milestones.append({
            "id": ms.id, "status": ms.status, "owner": ms.owner or "runner", "target": ms.target,
            "depends": ms.depends,
            "phases": [{"ref": ref, "state": snap.phases.state(ref)} for ref in ms.phases],
            "blockers": [{"type": b.type, "reason": b.reason, "check": b.check} for b in rm.blockers_of(ms.id)],
        })
    done = sum(1 for ms in rm.milestones if ms.status in FINISHED)
    parts = [f"{done} of {len(rm.milestones)} done", f"next {batch['milestone'] if batch else 'none'}"]
    for ms in rm.milestones:
        if ms.status in FINISHED:
            continue
        parts.extend(f"{ms.id} waits for: {b.type} {b.reason}" for b in rm.blockers_of(ms.id))
    old = _old_blockers(snap, today or _utc_today())
    if old:
        parts.append("old blockers: " + ", ".join(old))
    return {"roadmap": slug, "branch": snap.branch, "runner_host": rm.runner_host, "done": done,
            "total": len(rm.milestones), "next": batch, "milestones": milestones, "line": "; ".join(parts)}


def check(root: Path, slug: str) -> tuple[list[str], list[str]]:
    """(errors, warnings) for the origin copy of the roadmap."""
    snap = load(Path(root), slug, strict=False)
    errors = list(snap.errors)
    for ms in snap.roadmap.milestones:
        if not ms.phases and not ms.exit_check:
            errors.append(f"{ms.id}: no phase refs and no Exit check, so nothing could ever show it done")
    return errors, _dep_warnings(snap)


def _dep_warnings(snap: Snapshot) -> list[str]:
    """Warn when the last commit touching the roadmap changed a Depends on cell without citing a decision."""
    path = roadmap_path(snap.slug)
    last = _git(snap.root, "log", "-1", "--format=%H", f"origin/{snap.branch}", "--", path, check=False).stdout.strip()
    if not last:
        return []
    before = _git(snap.root, "show", f"{last}~1:{path}", check=False)
    if before.returncode != 0:
        return []
    old = {m.id: m.depends for m in parse_roadmap(before.stdout).milestones}
    warnings = []
    for ms in snap.roadmap.milestones:
        if ms.id in old and old[ms.id] != ms.depends and not DEP_CITE_RE.search(ms.name):
            warnings.append(f"{ms.id}: Depends on changed in {last[:12]} without a decision id in the Milestone "
                            f"cell, e.g. `{ms.id} (dep waived: D1)`")
    return warnings


# -- edits (pure text -> text; line endings kept) --------------------------------------------------------------


def _eol(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _clean_value(value: str, what: str) -> str:
    value = value.strip()
    # splitlines, not "\n": U+2028, U+2029, U+0085, \v and \f also end a line for a reader of the file.
    if len(value.splitlines()) > 1:
        raise RoadmapError(f"{what} must be one line")
    return value.replace("|", "\\|")


def _replace_line(text: str, idx: int, new_line: str) -> str:
    lines = text.splitlines(keepends=True)
    body = lines[idx].rstrip("\r\n")
    lines[idx] = new_line + lines[idx][len(body):]
    return "".join(lines)


def edit_cell(text: str, mid: str, col: str, value: str) -> str:
    rm = parse_roadmap(text)
    ms = rm.get(mid)
    if ms is None:
        raise RoadmapError(f"unknown milestone id {mid}")
    cells = caddis_rows.split_cells(text.splitlines()[ms.line])
    cells[MILESTONE_COLS.index(col)] = _clean_value(value, col) or "-"
    return _replace_line(text, ms.line, "| " + " | ".join(cells) + " |")


_CALENDAR_NEEDS_DATE = ("a calendar blocker needs --check with an ISO date YYYY-MM-DD (recheck clears it when the "
                        "date has passed, UTC)")


def add_blocker(text: str, mid: str, btype: str, reason: str, check_cmd: str = "", same_prefix: str = "") -> str:
    """The text with one more Blockers row. No change when the same milestone, type and reason exist, or (with
    `same_prefix`, rollup's stable `exit check failing (...)`) a row whose reason is that prefix or starts with it
    and `: `."""
    rm = parse_roadmap(text)
    if rm.get(mid) is None:
        raise RoadmapError(f"unknown milestone id {mid}")
    if rm.blocker_table is None:
        raise RoadmapError("the roadmap has no `## Blockers` table")
    reason_cell = _clean_value(reason, "--reason")
    if not reason_cell:
        raise RoadmapError("--reason is empty")
    if btype == "calendar":
        when = iso_date(check_cmd)
        if when is None:
            raise RoadmapError(_CALENDAR_NEEDS_DATE)
        check_cmd = when.isoformat()
    if any(b.milestone == mid and b.type == btype and (b.reason == reason.strip() or (
            same_prefix and (b.reason == same_prefix or b.reason.startswith(same_prefix + ": "))))
           for b in rm.blockers):
        return text
    check_cell = _clean_value(check_cmd, "--check")
    if check_cell and "`" not in check_cell:
        check_cell = f"`{check_cell}`"
    eol = _eol(text)
    row = f"| {mid} | {btype} | {reason_cell} | {check_cell or '-'} |"
    lines = text.splitlines(keepends=True)
    table = rm.blocker_table
    after = table.rows[-1] if table.rows else table.header_idx + 1
    if not lines[after].endswith(("\n", "\r")):
        lines[after] += eol
    lines.insert(after + 1, row + eol)
    return "".join(lines)


def remove_blockers(text: str, rows: list[Blocker]) -> str:
    drop = {b.line for b in rows}
    return "".join(line for i, line in enumerate(text.splitlines(keepends=True)) if i not in drop)


def _find_blockers(rm: Roadmap, mid: str, btype: str, reason: str, check_cmd: str | None = None) -> list[Blocker]:
    """The rows to remove. More than one row with this milestone, type and reason needs --check to pick one.
    A reason that is only rollup's stable prefix (`exit check failing (exit N)`) removes EVERY row of this milestone
    and type whose reason is that prefix or starts with it and `: ` (each is the same blocker with another tail)."""
    if ROLLUP_PREFIX_RE.fullmatch(reason.strip()):
        prefix = reason.strip()
        rows = [b for b in rm.blockers if b.milestone == mid and b.type == btype
                and (b.reason == prefix or b.reason.startswith(prefix + ": "))]
        if not rows:
            raise RoadmapError(f"no `{btype}` blocker on {mid} with reason `{prefix}` (or `{prefix}: ...`)")
        if check_cmd is not None:
            rows = [b for b in rows if b.check == _cell_text(check_cmd)]
        return rows
    rows = [b for b in rm.blockers if b.milestone == mid and b.type == btype and b.reason == reason.strip()]
    if not rows:
        raise RoadmapError(f"no `{btype}` blocker on {mid} with reason `{reason.strip()}`")
    if check_cmd is not None:
        wanted = _cell_text(check_cmd)
        rows = [b for b in rows if b.check == wanted]
        if not rows:
            raise RoadmapError(f"no `{btype}` blocker on {mid} with reason `{reason.strip()}` and Check `{wanted}`")
    if len({b.key for b in rows}) > 1:
        raise RoadmapError(f"{len(rows)} `{btype}` blockers on {mid} have reason `{reason.strip()}`; "
                           "add --check with the row's Check text to pick one")
    return rows[:1]  # identical rows: one unblock removes one row (the first)


# -- headless / owner ------------------------------------------------------------------------------------------


def _stdin_isatty() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (ValueError, OSError):
        return False


def _stdin_is_console() -> bool:
    """Windows: GetConsoleMode on the stdin handle. isatty() is True for NUL (a character device); this is not."""
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetConsoleMode.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.GetConsoleMode.restype = wintypes.BOOL
        handle = msvcrt.get_osfhandle(sys.stdin.fileno())
        mode = wintypes.DWORD()
        return bool(kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
    except Exception:  # no stdin, no fileno, not Windows: not a console
        return False


def is_headless(env=None) -> bool:
    """Unattended: any HEADLESS_VARS name in the environment (any value, even empty), stdin not a terminal, or on
    Windows stdin not a console (GetConsoleMode fails for NUL, a pipe or a file)."""
    env = os.environ if env is None else env
    if any(name in env for name in HEADLESS_VARS):
        return True
    if not _stdin_isatty():
        return True
    return WINDOWS and not _stdin_is_console()


def _require_owner(by_owner: bool, what: str) -> None:
    if is_headless():
        raise RoadmapError(f"{what} is owner-only and this session is headless "
                           f"({', '.join(HEADLESS_VARS)} in the environment, or stdin is not a console)")
    if not by_owner:
        raise RoadmapError(f"{what} is owner-only: run it yourself with --by-owner")


# -- running Exit check / Check commands -----------------------------------------------------------------------


@contextlib.contextmanager
def merged_checkout(root: Path, branch: str):
    """A temporary detached worktree at origin/<branch>: checks run the merged code, never the working tree."""
    tmp = Path(tempfile.mkdtemp(prefix="caddis-roadmap-check-"))
    worktree = tmp / "wt"
    try:
        _git(root, "worktree", "add", "--quiet", "--detach", str(worktree), f"origin/{branch}")
        yield worktree
    finally:
        caddis_worktree_safety.safe_remove_worktree(root, worktree, force_locked=True, env=_quiet_env())
        _git(root, "worktree", "prune", check=False)
        caddis_worktree_safety.remove_tree(tmp)     # links first: a junction's target survives


def _kill_tree(proc: subprocess.Popen) -> None:
    if WINDOWS:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                       stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9


def _job_limit_struct():
    """ctypes JOBOBJECT_EXTENDED_LIMIT_INFORMATION."""
    import ctypes
    from ctypes import wintypes

    class _Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _Io(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", _Io), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    return _Extended


class _WinJob:
    """A Windows job object that holds one process and every process it starts, so the tree can be killed even
    after the first process has exited (taskkill /T cannot find the children of a process that is gone).
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: when the handle closes (also when this process dies), the tree dies."""

    def __init__(self, proc: subprocess.Popen):
        import ctypes
        from ctypes import wintypes

        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        k.SetInformationJobObject.restype = wintypes.BOOL
        k.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        k.AssignProcessToJobObject.restype = wintypes.BOOL
        k.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        k.TerminateJobObject.restype = wintypes.BOOL
        k.CloseHandle.argtypes = (wintypes.HANDLE,)
        k.CloseHandle.restype = wintypes.BOOL
        self._k = k
        self.handle = k.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        info = _job_limit_struct()()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k.SetInformationJobObject(self.handle, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                                         ctypes.byref(info), ctypes.sizeof(info)):
            err = ctypes.get_last_error()
            k.CloseHandle(self.handle)
            raise OSError(err, "SetInformationJobObject failed")
        if not k.AssignProcessToJobObject(self.handle, int(proc._handle)):  # type: ignore[attr-defined]
            err = ctypes.get_last_error()
            k.CloseHandle(self.handle)
            raise OSError(err, "AssignProcessToJobObject failed")

    def limit_flags(self) -> int:
        """The job's LimitFlags (QueryInformationJobObject); for tests."""
        import ctypes
        from ctypes import wintypes

        q = self._k.QueryInformationJobObject
        q.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p)
        q.restype = wintypes.BOOL
        info = _job_limit_struct()()
        if not q(self.handle, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS, ctypes.byref(info),
                 ctypes.sizeof(info), None):
            raise OSError(ctypes.get_last_error(), "QueryInformationJobObject failed")
        return int(info.BasicLimitInformation.LimitFlags)

    def terminate(self) -> None:
        self._k.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        self._k.CloseHandle(self.handle)


def _start(argv, **kwargs) -> tuple[subprocess.Popen, "_WinJob | None"]:
    """Popen with no stdin, in its own process group (and, on Windows, its own job object)."""
    if not WINDOWS:
        kwargs["start_new_session"] = True
    # CREATE_NO_WINDOW: the child (git, gh, a gate) must not flash a window when this runs from a hook.
    flags = (subprocess.CREATE_NEW_PROCESS_GROUP | _NO_WINDOW) if WINDOWS else 0
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, creationflags=flags, **kwargs)
    job = None
    if WINDOWS:
        try:
            job = _WinJob(proc)
        except Exception:  # no job object: taskkill /T is the fallback
            job = None
        except BaseException:  # Ctrl+C while the job is made: do not leave the process running
            _kill(proc, None)
            raise
    return proc, job


def _kill(proc: subprocess.Popen, job: "_WinJob | None") -> None:
    """Kill the whole tree: the job object when there is one, else taskkill /T (Windows) or the process group."""
    if job is not None:
        job.terminate()
    else:
        _kill_tree(proc)


def _wait(proc: subprocess.Popen, job: "_WinJob | None", timeout: float, kill_always: bool) -> int | None:
    """Wait up to `timeout`; return the exit code, or None on timeout. The tree is killed on timeout, and also on
    a normal exit when `kill_always` (a check must not leave a background child running)."""
    try:
        rc: int | None = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        rc = None
    if rc is None or kill_always:
        _kill(proc, job)
        if rc is None:
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=10)
    return rc


@contextlib.contextmanager
def _owned(proc: subprocess.Popen, job: "_WinJob | None"):
    """On any exception, Ctrl+C (KeyboardInterrupt) included, kill the tree and re-raise; always close the job."""
    try:
        yield
    except BaseException:
        _kill(proc, job)
        raise
    finally:
        if job is not None:
            job.close()


class BoundedTimeout(RoadmapError):
    """run_bounded timed out (exit 3)."""


def run_bounded(argv: list[str], timeout: float, what: str, capture: bool = True) -> subprocess.CompletedProcess:
    """Run one network command (git fetch/ls-remote/push, gh, the merge chain) with no credential prompt.

    Output goes to temp files, not pipes, so a child that keeps a pipe open cannot hang the read. A timeout kills
    the tree and raises BoundedTimeout (exit 3); Ctrl+C kills the tree and re-raises.
    """
    env = _quiet_env()
    if not capture:
        proc, job = _start(argv, env=env)
        with _owned(proc, job):
            rc = _wait(proc, job, timeout, kill_always=False)
        if rc is None:
            raise BoundedTimeout(f"{what} timed out after {timeout:.0f} s", caddis_exit.NOT_RUN)
        return subprocess.CompletedProcess(argv, rc, "", "")
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc, job = _start(argv, env=env, stdout=out, stderr=err)
        with _owned(proc, job):
            rc = _wait(proc, job, timeout, kill_always=False)
        if rc is None:
            raise BoundedTimeout(f"{what} timed out after {timeout:.0f} s", caddis_exit.NOT_RUN)
        out.seek(0)
        err.seek(0)
        return subprocess.CompletedProcess(argv, rc, out.read().decode("utf-8", errors="replace"),
                                           err.read().decode("utf-8", errors="replace"))


def _drain(pipe, out, guard: threading.Lock) -> None:
    """Copy a check's output to `out`; past OUTPUT_FILE_CAP keep only the last OUTPUT_TAIL_BYTES on disk."""
    fd = pipe.fileno()
    while True:
        try:
            chunk = os.read(fd, 65536)
        except OSError:
            return
        if not chunk:
            return
        with guard:
            out.write(chunk)
            if out.tell() > OUTPUT_FILE_CAP:
                out.seek(-OUTPUT_TAIL_BYTES, os.SEEK_END)
                tail = out.read()
                out.seek(0)
                out.truncate()
                out.write(tail)


def run_check(cwd: Path, cmd: str, timeout: float) -> tuple[int | None, str]:
    """Run one command: (exit code, or None on timeout; the last 64 KB of output). It cannot hang the caller.

    The process tree is killed on every exit, not only on timeout (Ctrl+C too, which is then re-raised), and the
    output file never passes 1 MB.
    """
    guard = threading.Lock()
    with tempfile.TemporaryFile() as out:
        proc, job = _start(cmd, shell=True, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        with _owned(proc, job):
            reader = threading.Thread(target=_drain, args=(proc.stdout, out, guard), daemon=True)
            reader.start()
            rc = _wait(proc, job, timeout, kill_always=True)
        reader.join(timeout=10)
        with guard:
            size = out.seek(0, os.SEEK_END)
            out.seek(max(0, size - OUTPUT_TAIL_BYTES))
            text = out.read().decode("utf-8", errors="replace")
        return rc, text


def _failure(rc: int | None, timeout: float) -> str:
    return f"timed out after {timeout:.0f} s" if rc is None else f"exit {rc}"


def env_failure(rc: int | None, output: str) -> str | None:
    """Why a failed check could not run in the merged checkout (the environment is missing); None for a real failure
    (also for a timeout: it ran)."""
    if rc is None or rc == 0:
        return None
    if rc in SHELL_CANNOT_RUN_CODES:
        return f"exit {rc}: the shell could not start the command"
    lines = [ln for ln in (output or "").splitlines() if ln.strip()][-ENV_SCAN_LINES:]
    match = ENV_FAILURE_RE.search("\n".join(lines))
    return f"the output says `{match.group(0)}`" if match else None


def mask_output(text: str, secrets: list[str]) -> str:
    """`text` with secret values (caddis_redact), token-shaped strings, URL credentials and absolute paths masked."""
    text = caddis_redact.redact(text or "", secrets)
    for pattern, repl in OUTPUT_MASKS:
        text = pattern.sub(repl, text)
    return text


def _plain_line(text: str) -> str:
    """Text a roadmap cell holds as is: printable ASCII on one line, no HTML comment marker, and no `|` or backslash,
    so `_clean_value` escapes nothing and the stored cell is exactly this text."""
    text = "".join(ch if " " <= ch <= "~" else " " for ch in text)
    text = text.replace("\\", "/").replace("|", "/").replace("<!--", "<! --").replace("-->", "-- >")
    return " ".join(text.split())


def blocker_reason(failure: str, output: str, secrets: list[str]) -> str:
    """`exit check failing (<failure>)`, then `: ` and the last REASON_TAIL_LINES non-empty output lines on one line,
    masked (mask_output), with nothing left to escape, cut from the front so the whole cell is at most
    REASON_CELL_CHARS: the merged blocker says why. The part before `: ` is the stable identity (ROLLUP_PREFIX_RE)."""
    base = f"exit check failing ({failure})"
    lines = [ln.strip() for ln in mask_output(output, secrets).splitlines() if ln.strip()]
    tail = _plain_line(" / ".join(lines[-REASON_TAIL_LINES:]))
    room = REASON_CELL_CHARS - len(base) - len(": ")
    if len(tail) > room:
        tail = ("..." + tail[-(room - 3):].lstrip())[:room]
    return f"{base}: {tail}" if tail else base


def _log_stamp() -> str:
    """The UTC stamp in an exit-check log name; it sorts in time order (a seam for the tests)."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def keep_check_output(root: Path, slug: str, mid: str, runs: list[tuple[str, str, int | None, str]],
                      secrets: list[str]) -> Path | None:
    """Write the last OUTPUT_TAIL_BYTES of what the Exit setup and Exit check printed, masked (mask_output), to
    `<.local>/exit-check-<id>-<utc>.log` and return its path (None when it cannot be written; the caller says so).
    Only the newest KEEP_CHECK_LOGS such logs of the roadmap stay. `runs` holds (what, command, exit code or None,
    output)."""
    parts = []
    for what, cmd, rc, output in runs:
        body = output if not output or output.endswith("\n") else output + "\n"
        result = "timed out" if rc is None else f"exit {rc}"
        parts.append(f"== {what}: {cmd}\n{body}== {what} result: {result}\n")
    data = mask_output("".join(parts), secrets).encode("utf-8")[-OUTPUT_TAIL_BYTES:]
    path = local_dir(root, slug) / f"exit-check-{mid}-{_log_stamp()}.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.decode("utf-8", errors="ignore").encode("utf-8"))
    except OSError:
        return None
    logs = sorted(path.parent.glob("exit-check-*.log"), key=lambda f: (f.stem.rsplit("-", 1)[-1], f.name))
    for old in logs[:-KEEP_CHECK_LOGS]:
        with contextlib.suppress(OSError):
            old.unlink()
    return path


def _log_note(log: Path | None) -> str:
    return f"Output: {log}" if log is not None else "Output not kept (the .local folder cannot be written)."


# -- the write path ---------------------------------------------------------------------------------------------


def open_pr(root: Path, gh_repo: str, branch: str, base: str, title: str, body: str) -> int:
    """Open a PR with the REST API and return its number. `gh` takes the account from GH_TOKEN when it is set."""
    proc = run_bounded(["gh", "api", f"repos/{gh_repo}/pulls", "-f", f"title={title}", "-f", f"head={branch}",
                        "-f", f"base={base}", "-f", f"body={body}"], GH_TIMEOUT, "gh api (open the PR)")
    if proc.returncode != 0:
        raise RoadmapError(f"could not open the PR: {(proc.stderr or proc.stdout).strip()[:300]}",
                           caddis_exit.BLOCKED)
    return int(json.loads(proc.stdout)["number"])


def merge_pr(root: Path, pr: int, gh_repo: str) -> int:
    """Hand one PR to the kept merge tool; return its exit code. Its output goes to this console."""
    argv = [sys.executable, str(SCRIPTS_DIR / "caddis_merge_chain.py"), str(pr), "--repo", str(root),
            "--gh-repo", gh_repo, "--docs-only"]
    return run_bounded(argv, MERGE_CHAIN_TIMEOUT, "caddis_merge_chain.py", capture=False).returncode


def _win_open_process(pid: int) -> tuple[bool | None, int]:
    """Windows: (still running, 0) when OpenProcess works; (None, GetLastError()) when it does not."""
    import ctypes
    from ctypes import wintypes

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k.OpenProcess.restype = wintypes.HANDLE
    k.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    k.GetExitCodeProcess.restype = wintypes.BOOL
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None, ctypes.get_last_error()
    code = wintypes.DWORD()
    ok = k.GetExitCodeProcess(handle, ctypes.byref(code))
    k.CloseHandle(handle)
    return bool(ok) and code.value == 259, 0  # STILL_ACTIVE


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if WINDOWS:
        running, error = _win_open_process(pid)
        if running is None:
            return error == 5  # ERROR_ACCESS_DENIED: the process exists, this user may not open it
        return running
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class _Lock:
    """Exclusive file lock. On timeout, a stale lock is taken over; a live one refuses.

    Stale: the holder's pid is dead on this host, or the file is empty or not JSON and older than 60 s. Takeover is
    race-safe: rename the stale file to a unique name (only one contender's rename succeeds), check the renamed file
    still holds what was judged stale, then create the lock with O_EXCL; only the winner proceeds.
    """

    def __init__(self, path: Path, timeout: float | None = None):
        self.path, self.fd = path, None
        self.timeout = LOCK_TIMEOUT if timeout is None else timeout
        self.denied: PermissionError | None = None  # the last Windows "busy" refusal, reported on timeout

    def _try(self) -> bool:
        try:
            self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        except PermissionError as exc:
            # Windows refuses a create while the last holder's delete is still pending: busy, not an error.
            if not _WINDOWS:
                raise
            self.denied = exc
            return False
        os.write(self.fd, json.dumps({"pid": os.getpid(), "host": socket.gethostname(),
                                      "started_utc": _utc()}).encode())
        return True

    def _stale(self) -> bytes | None:
        """The lock file's bytes when it is stale, else None."""
        try:
            raw = self.path.read_bytes()
            age = time.time() - self.path.stat().st_mtime
        except OSError:
            return None
        try:
            holder = json.loads(raw.decode("utf-8"))
        except ValueError:  # empty or not JSON (a writer died mid-write)
            holder = None
        if not isinstance(holder, dict):
            return raw if age > LOCK_MALFORMED_STALE_S else None
        try:
            pid = int(holder.get("pid", 0))
        except (TypeError, ValueError):
            return raw if age > LOCK_MALFORMED_STALE_S else None
        if holder.get("host") == socket.gethostname() and not _pid_alive(pid):
            return raw
        return None

    def _take_over(self) -> bool:
        judged = self._stale()
        if judged is None:
            return False
        grave = self.path.with_name(f"{self.path.name}.stale-{os.getpid()}-{uuid.uuid4().hex}")
        try:
            os.rename(self.path, grave)
        except FileNotFoundError:  # another contender took it first: the lock is held (exit 3)
            return False
        except OSError:  # the holder still has it open
            return False
        try:
            try:
                content = grave.read_bytes()
            except FileNotFoundError:  # gone under us: another contender has it; held, not an error
                return False
            if content != judged:
                # A fresh lock replaced the stale one between the check and the rename: put it back.
                with contextlib.suppress(OSError):
                    os.link(grave, self.path)
                return False
        finally:
            grave.unlink(missing_ok=True)
        return self._try()

    def __enter__(self) -> "_Lock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while not self._try():
            if time.monotonic() >= deadline:
                if self._take_over():
                    print(f"took over a stale lock {self.path}", file=sys.stderr)
                    return self
                why = f" (last refusal: {self.denied})" if self.denied else ""
                raise RoadmapError(f"{self.path} is held by another write after {self.timeout:.0f} s{why}",
                                   caddis_exit.NOT_RUN)
            time.sleep(0.2)
        return self

    def __exit__(self, *_exc) -> None:
        if self.fd is not None:
            os.close(self.fd)
        self.path.unlink(missing_ok=True)


def _utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# -- runner locks (written by caddis_roadmap_run.py; read here so `next` skips a batch another runner holds) ------

RUNNER_DIR = "caddis-runner"  # in the git common dir: every worktree of the repo sees the same locks
RUNNER_LOCK_GRACE_H = 1.0  # a runner may finish its last roadmap write a little after its hour cap
MALFORMED_LOCK_STALE_H = 24.0  # a lock that is not the JSON object is stale only after this long
CLAIM_TIMEOUT = 300  # `next` plus the batch claim, under one lock; a fetch inside it can take 120 s
BATCH_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)#(\d+|\*)$")  # `<plan>#<phase>`, or `<plan>#*` (plan mode)


def runner_state_dir(root: Path) -> Path | None:
    """`<git common dir>/caddis-runner`, or None when `root` is not inside a git repo."""
    proc = subprocess.run(["git", "-C", str(root), "rev-parse", "--git-common-dir"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    common = Path(proc.stdout.strip())
    if not common.is_absolute():
        common = Path(root) / common
    return common.resolve() / RUNNER_DIR


def runner_lock_path(root: Path, kind: str, slug: str) -> Path | None:
    """The runner lock of a roadmap (`kind` roadmap) or a plan (`kind` plan); None outside a git repo."""
    base = runner_state_dir(root)
    return None if base is None else base / f"{kind}-{slug}" / "runner.lock"


def last_stop_path(root: Path, kind: str, slug: str) -> Path | None:
    """The last stop the lock-holding runner recorded (reason, exit, utc), next to its lock."""
    base = runner_state_dir(root)
    return None if base is None else base / f"{kind}-{slug}" / "last-stop.json"


def claim_lock_path(root: Path) -> Path | None:
    base = runner_state_dir(root)
    return None if base is None else base / "claim.lock"


def read_runner_lock(path: Path) -> dict | None:
    """The lock's JSON object; None when the file is missing; {} when it is empty, not JSON or not an object."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError):
        return {}
    try:
        holder = json.loads(raw)
    except ValueError:
        return {}
    return holder if isinstance(holder, dict) else {}


def _parse_utc(value) -> datetime.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=datetime.timezone.utc)


def _hours(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if 0 < value < float("inf") else None


PID_START_TOLERANCE_S = 5.0  # `started_utc` has whole seconds; the holder's own process started before it


def _filetime_utc(value: int) -> datetime.datetime:
    return datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(microseconds=value // 10)


def _win_process_start(pid: int) -> datetime.datetime | None:
    import ctypes
    from ctypes import wintypes

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k.OpenProcess.restype = wintypes.HANDLE
    k.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
    k.GetProcessTimes.restype = wintypes.BOOL
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not k.GetProcessTimes(handle, *(ctypes.byref(x) for x in times)):
            return None
        created = times[0]
        return _filetime_utc((created.dwHighDateTime << 32) | created.dwLowDateTime)
    finally:
        k.CloseHandle(handle)


def _proc_process_start(pid: int) -> datetime.datetime | None:
    """POSIX with /proc: field 22 of /proc/<pid>/stat (clock ticks after boot) plus `btime` of /proc/stat."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        ticks = int(stat.rsplit(")", 1)[1].split()[19])
        btime = next(int(line.split()[1]) for line in Path("/proc/stat").read_text(encoding="utf-8").splitlines()
                     if line.startswith("btime "))
        hz = os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, StopIteration, AttributeError):
        return None
    return datetime.datetime.fromtimestamp(btime + ticks / hz, datetime.timezone.utc)


def process_start_time(pid: int) -> datetime.datetime | None:
    """When the process now holding `pid` started, or None when it cannot be read (psutil when installed, else
    GetProcessTimes on Windows, else /proc)."""
    try:
        import psutil  # optional
        return datetime.datetime.fromtimestamp(psutil.Process(pid).create_time(), datetime.timezone.utc)
    except ImportError:
        pass
    except Exception:  # no such process, access denied: fall through to the platform reader
        pass
    try:
        return _win_process_start(pid) if WINDOWS else _proc_process_start(pid)
    except Exception:
        return None


def runner_lock_stale(path: Path, now: datetime.datetime | None = None) -> bool | None:
    """None when there is no lock. On this host: stale when its pid is not running, or the process now holding that
    pid started after `started_utc` (pid reuse after a reboot; when the start time cannot be read: live). Another
    host's lock: stale when `started_utc` is older than the `max_hours` the lock itself records (plus a 1 h grace); with
    no readable `max_hours` or `started_utc` it never ages out (the owner deletes it). A lock that is not the JSON
    object is stale only when the file is older than 24 h."""
    holder = read_runner_lock(path)
    if holder is None:
        return None
    now = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        pid = int(holder.get("pid"))
    except (TypeError, ValueError):
        pid = None
    host = holder.get("host")
    if pid is None or not isinstance(host, str):
        try:
            mtime = datetime.datetime.fromtimestamp(Path(path).stat().st_mtime, datetime.timezone.utc)
        except OSError:
            return None
        return now - mtime > datetime.timedelta(hours=MALFORMED_LOCK_STALE_H)
    started, max_hours = _parse_utc(holder.get("started_utc")), _hours(holder.get("max_hours"))
    if host.casefold() == socket.gethostname().casefold():
        if not _pid_alive(pid):
            return True
        born = process_start_time(pid) if started is not None else None
        return born is not None and born > started + datetime.timedelta(seconds=PID_START_TOLERANCE_S)
    if started is None or max_hours is None:
        return False
    return now - started > datetime.timedelta(hours=max_hours + RUNNER_LOCK_GRACE_H)


def _old_plan_locks(root: Path) -> dict[str, str]:
    """Upgrade window, read only: a plan-mode runner of the base version holds `.caddis/plans/.local/<slug>/
    runner.lock` (a plain pid, or the JSON lock). A plain pid holds the whole plan only while that pid runs AND the
    lock file is newer than that process's start (else the pid was reused, or the start cannot be read: ignored)."""
    out: dict[str, str] = {}
    try:
        locks = sorted((Path(root) / ".caddis" / "plans" / ".local").glob("*/runner.lock"))
    except OSError:
        return out
    for lock in locks:
        try:
            raw = lock.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            continue
        if raw.isdigit():
            born = process_start_time(int(raw)) if _pid_alive(int(raw)) else None
            try:
                written = datetime.datetime.fromtimestamp(lock.stat().st_mtime, datetime.timezone.utc)
            except OSError:
                written = None
            live = born is not None and written is not None and written > born
        else:
            holder = read_runner_lock(lock) or {}
            live = isinstance(holder.get("pid"), int) and runner_lock_stale(lock) is False
        if live:
            out.setdefault(f"{lock.parent.name}#*", f"plan {lock.parent.name}, old lock {lock}")
    return out


def live_runner_holders(root: Path, exclude: Path | None = None) -> dict[str, dict]:
    """Batch (`<plan>#<n>` or `<plan>#*`) -> {"kind": "lock" | "claim", "holder": "roadmap <slug>" | "plan <slug>"},
    for every live runner lock of this repo but `exclude`, every base-version plan lock that still runs, and every
    persistent claim of a phase whose PR waits for a merge."""
    out: dict[str, dict] = {}
    base = runner_state_dir(root)
    if base is None:
        return out
    try:
        locks = sorted(base.glob("*/runner.lock"))  # one folder per runner: roadmap-<slug>/, plan-<slug>/
    except OSError:
        return out
    for lock in locks:
        if exclude is not None and lock.parent.name == Path(exclude).parent.name:
            continue
        if runner_lock_stale(lock) is not False:
            continue
        batch = (read_runner_lock(lock) or {}).get("batch")
        if isinstance(batch, str) and BATCH_RE.match(batch):
            out.setdefault(batch, {"kind": "lock", "holder": lock.parent.name.replace("-", " ", 1)})
    for batch, holder in _old_plan_locks(root).items():
        out.setdefault(batch, {"kind": "lock", "holder": holder})
    # A phase whose PR waits for a merge stays held by its persistent claim (`claims/<plan>#<n>.json`).
    try:
        claims = sorted((base / "claims").glob("*.json"))
    except OSError:
        claims = []
    for claim in claims:
        record = read_runner_lock(claim) or {}
        batch = record.get("batch") or claim.stem
        if isinstance(batch, str) and BATCH_RE.match(batch):
            out.setdefault(batch, {"kind": "claim", "holder": f"roadmap {record.get('roadmap', '?')}"})
    return out


def holder_label(holder: dict | str) -> str:
    """How a reason names a holder: `<holder> (its runner lock)` or `<holder> (its claim: its PR waits for a merge)`."""
    if isinstance(holder, str):
        return holder
    what = "its claim: its PR waits for a merge" if holder.get("kind") == "claim" else "its runner lock"
    return f"{holder.get('holder')} ({what})"


def live_runner_batches(root: Path, exclude: Path | None = None) -> dict[str, str]:
    """live_runner_holders as batch -> label (see holder_label)."""
    return {batch: holder_label(h) for batch, h in live_runner_holders(root, exclude).items()}


def other_roadmap_holders(root: Path, slug: str) -> dict[str, dict]:
    """live_runner_holders without this roadmap's own runner lock (its batch is the one it is running)."""
    return live_runner_holders(root, exclude=runner_lock_path(root, "roadmap", slug))


def other_roadmap_batches(root: Path, slug: str) -> dict[str, str]:
    """live_runner_batches without this roadmap's own runner (its batch is the one it is running)."""
    own = runner_lock_path(root, "roadmap", slug)
    return live_runner_batches(root, exclude=own)


def _diff(old: str, new: str, path: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                        f"a/{path}", f"b/{path}"))


def write_change(root: Path, slug: str, mid: str, change: str, edit, dry_run: bool = False, out=print) -> int:
    """Apply `edit(snapshot) -> text` to a fresh origin copy and land it as one docs PR. Return a caddis exit code.

    `edit` runs under the lock on a fresh, valid origin copy; it raises RoadmapError to refuse (nothing written).
    """
    root = Path(root)
    path = roadmap_path(slug)
    if dry_run:
        snap = load(root, slug)
        new = edit(snap)
        diff = _diff(snap.text, new, path)
        out(f"would write:\n{diff}" if diff else "no change")
        return caddis_exit.CLEAN
    with _Lock(lock_path(root, slug)):
        snap = load(root, slug)
        new = edit(snap)
        if new == snap.text:
            out("no change")
            return caddis_exit.CLEAN
        gh_repo = gh_repo_of(root)
        if gh_repo is None:
            raise RoadmapError("origin is not a GitHub remote; cannot open a docs PR", caddis_exit.NOT_RUN)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
        branch = f"roadmap/{slug}-{mid.lower()}-{stamp}"
        title = f"docs(roadmap): {slug} {mid} {change}"
        tmp = Path(tempfile.mkdtemp(prefix="caddis-roadmap-"))
        worktree = tmp / "wt"
        pr = None
        rc = caddis_exit.BLOCKED
        merge_exit: int | str | None = None
        try:
            _git(root, "worktree", "add", "--quiet", "-b", branch, str(worktree), f"origin/{snap.branch}")
            (worktree / path).write_bytes(new.encode("utf-8"))
            _git(worktree, "add", "--", path)
            _git(worktree, "commit", "--quiet", "-m", title)
            _git(worktree, "push", "--quiet", "-u", "origin", branch)
            try:
                pr = open_pr(root, gh_repo, branch, snap.branch, title,
                             f"Roadmap change by caddis_roadmap.py: {slug} {mid} {change}.")
            except Exception:
                _git(root, "push", "--quiet", "origin", "--delete", branch, check=False)
                raise
            try:
                rc = merge_pr(root, pr, gh_repo)
            except BoundedTimeout:
                merge_exit = "timeout"
                raise
            out(f"#{pr} {title}: " + ("merged" if rc == caddis_exit.CLEAN else f"not merged (merge chain exit {rc})"))
            if rc == caddis_exit.CLEAN:
                _git(root, "push", "--quiet", "origin", "--delete", branch, check=False)
            else:
                rc = caddis_exit.NOT_RUN if rc == caddis_exit.NOT_RUN else caddis_exit.BLOCKED
        finally:
            caddis_worktree_safety.safe_remove_worktree(root, worktree, force_locked=True, env=_quiet_env())
            _git(root, "worktree", "prune", check=False)
            _git(root, "branch", "-D", branch, check=False)
            caddis_worktree_safety.remove_tree(tmp)
            _audit(root, slug, {"utc": _utc(), "roadmap": slug, "id": mid, "change": change, "branch": branch,
                                "pr": pr, "merge_exit": merge_exit if merge_exit is not None
                                else (rc if pr is not None else None)})
        return rc


def _audit(root: Path, slug: str, entry: dict) -> None:
    log = local_dir(root, slug) / "changes.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


# -- write commands ----------------------------------------------------------------------------------------------


def _known(snap: Snapshot, mid: str) -> Milestone:
    ms = snap.roadmap.get(mid)
    if ms is None:
        raise RoadmapError(f"unknown milestone id {mid}")
    return ms


def _drop_reason(reason: str | None) -> str:
    """The checked text of a `not-needed` reason: `dropped: <why>` or a `.caddis/parking-lot/<file>.md` path."""
    if reason is None or not reason.strip():
        raise RoadmapError("setting Status not-needed needs --reason \"dropped: <why>\" or "
                           "--reason .caddis/parking-lot/<file>.md")
    if "|" in reason or len(reason.splitlines()) > 1 or "\n" in reason or "\r" in reason:
        raise RoadmapError("--reason must be one line with no `|`")
    text = reason.strip()
    if text.startswith(DROPPED_PREFIX):
        if not text[len(DROPPED_PREFIX):].strip():
            raise RoadmapError("--reason `dropped:` needs the reason after it")
        return text
    if PARKING_RE.match(text):
        return text
    raise RoadmapError(f"--reason must start with `{DROPPED_PREFIX} ` or be a .caddis/parking-lot/<file>.md path, "
                       f"not `{text}`")


def add_note(text: str, item: str) -> str:
    """Append `- <item>` to the `## Notes` section (added at the end when missing). Line endings kept."""
    eol = _eol(text)
    lines = text.splitlines(keepends=True)
    bare = [line.rstrip("\r\n") for line in lines]
    front_end = _frontmatter_end(bare)
    start = next((i for i, line in enumerate(bare) if i > front_end and line.rstrip() == "## Notes"), None)
    if start is None:
        body = text if not text or text.endswith(("\n", "\r")) else text + eol
        sep = "" if not body or body.endswith(eol + eol) else eol
        return f"{body}{sep}## Notes{eol}{eol}- {item}{eol}"
    end = len(bare)
    for i in range(start + 1, len(bare)):
        match = HEADING_RE.match(bare[i])
        if match and len(match.group(1)) <= 2:
            end = i
            break
    last = max((i for i in range(start + 1, end) if bare[i].strip()), default=start)
    if not lines[last].endswith(("\n", "\r")):
        lines[last] += eol
    new = [f"- {item}{eol}"]
    if last == start or not bare[last].lstrip().startswith("- "):
        new.insert(0, eol)  # a blank line between the heading or a paragraph and the list
    lines[last + 1:last + 1] = new
    return "".join(lines)


def set_cell(root: Path, slug: str, mid: str, col: str, value: str, by_owner: bool = False,
             dry_run: bool = False, out=print, reason: str | None = None,
             today: datetime.date | None = None) -> int:
    drop = col == "Status" and value == "not-needed"
    if reason is not None and not drop:
        raise RoadmapError("--reason is only for --col Status --value not-needed")
    if col not in SETTABLE:
        raise RoadmapError(f"--col must be one of {', '.join(SETTABLE)}, not `{col}`")
    if col == "Status":
        if value == "done":
            raise RoadmapError("only `rollup` may write Status done")
        if value not in STATUSES:
            raise RoadmapError(f"Status `{value}` is not one of {', '.join(STATUSES)}")
        if value == "not-needed":
            _require_owner(by_owner, "setting Status not-needed")
            reason = _drop_reason(reason)
    if col == "Owner":
        _require_owner(by_owner, "changing Owner")

    def edit(snap: Snapshot) -> str:
        ms = _known(snap, mid)
        new = edit_cell(snap.text, mid, col, value)
        if not drop or ms.status == "not-needed":  # already dropped: no second note
            return new
        assert reason is not None
        if PARKING_RE.match(reason) and show(snap.root, snap.branch, reason) is None:
            raise RoadmapError(f"--reason {reason} is not on origin/{snap.branch}")
        new = add_note(new, f"{mid} not-needed: {reason} ({(today or _utc_today()).isoformat()})")
        errors = parse_roadmap(new).errors
        if errors:  # never land a roadmap that fails closed
            raise RoadmapError("the note would make the roadmap malformed: " + "; ".join(errors))
        return new

    return write_change(root, slug, mid, f"{col} {value or '-'}", edit, dry_run, out)


def block(root: Path, slug: str, mid: str, btype: str, reason: str, check_cmd: str = "", by_owner: bool = False,
          dry_run: bool = False, out=print) -> int:
    if btype not in BLOCKER_TYPES:
        raise RoadmapError(f"--type must be one of {', '.join(BLOCKER_TYPES)}, not `{btype}`")
    if btype == "calendar":
        if iso_date(check_cmd) is None:
            raise RoadmapError(_CALENDAR_NEEDS_DATE)
        # A calendar Check is a date that recheck compares, never a command it runs: no owner check.
    elif check_cmd.strip():
        # recheck runs this command unattended later, so only the owner may add one.
        _require_owner(by_owner, "adding a Check command")
    return write_change(root, slug, mid, f"block {btype}",
                        lambda snap: add_blocker(snap.text, mid, btype, reason, check_cmd), dry_run, out)


def unblock(root: Path, slug: str, mid: str, btype: str, reason: str, by_owner: bool = False,
            dry_run: bool = False, out=print, check_cmd: str | None = None) -> int:
    if btype not in BLOCKER_TYPES:
        raise RoadmapError(f"--type must be one of {', '.join(BLOCKER_TYPES)}, not `{btype}`")
    if btype == "owner-gate":
        _require_owner(by_owner, "clearing an owner gate")

    def edit(snap: Snapshot) -> str:
        _known(snap, mid)
        return remove_blockers(snap.text, _find_blockers(snap.roadmap, mid, btype, reason, check_cmd))

    return write_change(root, slug, mid, f"unblock {btype}", edit, dry_run, out)


def _rollup_gate(snap: Snapshot, mid: str) -> Milestone | None:
    """The milestone when rollup may proceed; None when it is already finished. Raise to refuse."""
    ms = _known(snap, mid)
    if ms.status in FINISHED:
        return None
    if not ms.phases and not ms.exit_check:
        raise RoadmapError(f"{mid} has no phase refs and no Exit check: nothing can show it is done")
    rm = snap.roadmap
    unmet = [d for d in ms.depends if rm.get(d) is None or rm.get(d).status not in FINISHED]
    if unmet:
        raise RoadmapError(f"{mid} depends on milestone(s) not done: " + ", ".join(
            f"{d} ({rm.get(d).status if rm.get(d) else 'unknown'})" for d in unmet), caddis_exit.BLOCKED)
    not_done = [ref for ref in ms.phases if snap.phases.state(ref) != "done"]
    if not_done:
        raise RoadmapError(f"{mid}: not merged on origin/{snap.branch} yet: {', '.join(not_done)}",
                           caddis_exit.BLOCKED)
    open_blocks = [b for b in snap.roadmap.blockers_of(mid) if b.type != "data-condition"]
    if open_blocks:
        raise RoadmapError(f"{mid} has open blocker(s): " + "; ".join(f"{b.type} {b.reason}" for b in open_blocks),
                           caddis_exit.BLOCKED)
    return ms


def rollup(root: Path, slug: str, mid: str, dry_run: bool = False, out=print) -> int:
    root = Path(root)
    snap = load(root, slug)
    ms = _rollup_gate(snap, mid)
    if ms is None:
        out(f"{mid} is already {_known(snap, mid).status}")
        return caddis_exit.CLEAN

    def to_status(value: str):
        def edit(fresh: Snapshot) -> str:
            # Re-check on the fresh origin copy under the lock: status, merged phases and blockers may have moved.
            if _rollup_gate(fresh, mid) is None:
                return fresh.text
            return edit_cell(fresh.text, mid, "Status", value)
        return edit

    setup = snap.roadmap.exit_setup
    if dry_run:
        if ms.exit_check:
            if setup:
                out(f"would run setup: {setup}")
            out(f"would run: {ms.exit_check}")
        return write_change(root, slug, mid, "Status done", to_status("done"), True, out)
    rc: int | None = 0
    output = ""
    log: Path | None = None
    secrets: list[str] = []
    if ms.exit_check:
        secrets = caddis_redact.load_secrets(Path.home())
        runs: list[tuple[str, str, int | None, str]] = []
        setup_rc: int | None = 0
        with merged_checkout(root, snap.branch) as cwd:
            if setup:  # installs fresh into this worktree; never a link to a shared venv or node_modules
                setup_rc, setup_output = run_check(cwd, setup, EXIT_SETUP_TIMEOUT)
                runs.append(("Exit setup", setup, setup_rc, setup_output))
            if setup_rc == 0:
                rc, output = run_check(cwd, ms.exit_check, EXIT_CHECK_TIMEOUT)
                runs.append(("Exit check", ms.exit_check, rc, output))
        if setup_rc != 0:  # the check never ran: an environment problem, never a blocker
            log = keep_check_output(root, slug, mid, runs, secrets)
            out(f"{mid}: exit check not run: the Exit setup failed "
                f"({_failure(setup_rc, EXIT_SETUP_TIMEOUT)}); nothing written. {_log_note(log)}")
            return caddis_exit.NOT_RUN
        if rc != 0:
            log = keep_check_output(root, slug, mid, runs, secrets)
            why = env_failure(rc, output)
            if why is not None:
                hint = ("check the `**Exit setup:**` line (it ran and passed, but did not install what the check "
                        "needs, or the check does not call the venv it made)" if setup else
                        "give the roadmap an `**Exit setup:**` line that installs it fresh")
                out(f"{mid}: exit check not run: the merged checkout lacks the project environment ({why}); "
                    f"nothing written. Fix: {hint}, or fix the check. {_log_note(log)}")
                return caddis_exit.NOT_RUN
    if rc == 0:
        out(f"{mid}: exit check passed" if ms.exit_check else f"{mid}: every phase merged, no exit check")
        return write_change(root, slug, mid, "Status done", to_status("done"), False, out)
    failure = _failure(rc, EXIT_CHECK_TIMEOUT)
    if any(b.type == "data-condition" for b in snap.roadmap.blockers_of(mid)):
        out(f"{mid}: exit check failing ({failure}) and a data-condition blocker is open: code-done/data-pending. "
            f"{_log_note(log)}")
        write_rc = write_change(root, slug, mid, "Status code-done/data-pending",
                                to_status("code-done/data-pending"), False, out)
        return write_rc if write_rc != caddis_exit.CLEAN else caddis_exit.BLOCKED
    # Only a short tail of the output reaches the roadmap: redacted, one line, plain ASCII. The rest stays local.
    reason = blocker_reason(failure, output, secrets)
    out(f"{mid}: {reason}. {_log_note(log)}")
    stable = f"exit check failing ({failure})"  # a rollup blocker's identity: the tail varies from run to run
    write_rc = write_change(root, slug, mid, "block external",
                            lambda fresh: add_blocker(fresh.text, mid, "external", reason, same_prefix=stable), False,
                            out)
    return write_rc if write_rc != caddis_exit.CLEAN else caddis_exit.BLOCKED


def _due_calendar(rm: Roadmap, today: datetime.date) -> list[Blocker]:
    """Calendar rows whose Check is an ISO date on or before today. A Check of `-` (or any non-date) is never due."""
    due = []
    for b in rm.blockers:
        if b.type != "calendar":
            continue
        when = iso_date(b.check)
        if when is not None and when <= today:
            due.append(b)
    return due


def recheck(root: Path, slug: str, dry_run: bool = False, out=print, today: datetime.date | None = None) -> int:
    root = Path(root)
    today = today or _utc_today()
    snap = load(root, slug)
    rows = [b for b in snap.roadmap.blockers if b.type == "data-condition" and b.check]
    due = _due_calendar(snap.roadmap, today)
    if dry_run:
        for b in rows:
            out(f"would run: {b.check}")
        for b in due:
            out(f"would clear: {b.milestone} calendar {b.reason} (date {b.check} has passed)")
        keys = {b.key for b in rows} | {b.key for b in due}
        out("if every check passes:")
        write_change(root, slug, "all", "unblock data-condition",
                     lambda fresh: remove_blockers(fresh.text, [b for b in fresh.roadmap.blockers if b.key in keys]),
                     True, out)
        return caddis_exit.CLEAN
    passed: dict[str, set] = {}
    for b in due:  # no command runs: the date in Check has passed
        passed.setdefault(b.milestone, set()).add(b.key)
    if rows:
        with merged_checkout(root, snap.branch) as cwd:
            for b in rows:
                try:
                    rc, _output = run_check(cwd, b.check, RECHECK_TIMEOUT)
                except Exception as exc:  # one bad row must not stop the others
                    detail = str(exc).splitlines()[0] if str(exc) else ""
                    out(f"{b.milestone}: check not run: {type(exc).__name__}: {detail}")
                    continue
                if rc == 0:
                    passed.setdefault(b.milestone, set()).add(b.key)
    n = 0
    for mid, keys in passed.items():
        removed: list[int] = []

        def edit(fresh: Snapshot, keys=keys, removed=removed) -> str:
            # Only rows whose milestone, type, reason AND check text match a check that passed.
            drop = [b for b in fresh.roadmap.blockers if b.key in keys]
            removed[:] = [len(drop)]
            return remove_blockers(fresh.text, drop)

        types = sorted({key[1] for key in keys})
        try:
            if write_change(root, slug, mid, "unblock " + ", ".join(types), edit, False, out) == caddis_exit.CLEAN:
                n += removed[0] if removed else 0
        except Exception as exc:  # report and go on to the next milestone
            text = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            out(f"{mid}: not cleared: {text}")
    out(f"cleared {n}")
    return caddis_exit.CLEAN if n > 0 else caddis_exit.BLOCKED


# -- CLI ---------------------------------------------------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"ERROR: {message}", file=sys.stderr)
        sys.exit(caddis_exit.ERROR)


def _repo_root(raw: str) -> Path:
    proc = subprocess.run(["git", "-C", raw, "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
    if proc.returncode != 0:
        raise RoadmapError(f"{raw} is not inside a git repo", caddis_exit.NOT_RUN)
    return Path(proc.stdout.strip())


def list_roadmaps(root: Path) -> list[str]:
    """Slugs of the roadmaps on origin's default branch: a folder under .caddis/roadmaps/ that holds roadmap.md."""
    return list_roadmaps_checked(root)[0]


def list_roadmaps_checked(root: Path) -> tuple[list[str], set[str] | None]:
    """(slugs, every folder name under .caddis/roadmaps/ on origin). The folder set is None when git could not list
    the tree: a caller that deletes by "not on origin" (the page prune) must then delete nothing."""
    branch = fetch(root)
    tree = _git(root, "ls-tree", "--name-only", f"origin/{branch}", ".caddis/roadmaps/", check=False)
    folders: set[str] | None = set() if tree.returncode == 0 else None
    slugs: list[str] = []
    for folder in tree.stdout.splitlines():
        folder = folder.strip().rstrip("/")
        if not folder:
            continue
        if folders is not None:
            folders.add(folder.rsplit("/", 1)[-1])
        if _git(root, "cat-file", "-e", f"origin/{branch}:{folder}/roadmap.md", check=False).returncode == 0:
            slugs.append(folder.rsplit("/", 1)[-1])
    return sorted(slugs), folders


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add(name: str, write: bool = False, json_out: bool = False) -> argparse.ArgumentParser:
        p = sub.add_parser(name)
        p.add_argument("--roadmap", required=True)
        p.add_argument("--root", default=".")
        if json_out:
            p.add_argument("--json", action="store_true")
        if write:
            p.add_argument("--dry-run", action="store_true", help="print the diff and commands; run and write nothing")
        return p

    p = sub.add_parser("list")
    p.add_argument("--root", default=".")
    add("status", json_out=True)
    add("next", json_out=True)
    add("check")
    p = add("set", write=True)
    p.add_argument("--id", required=True)
    p.add_argument("--col", required=True)
    p.add_argument("--value", required=True)
    p.add_argument("--by-owner", action="store_true")
    p.add_argument("--reason", default=None,
                   help="for Status not-needed: \"dropped: <why>\" or .caddis/parking-lot/<file>.md (on origin)")
    for name in ("block", "unblock"):
        p = add(name, write=True)
        p.add_argument("--id", required=True)
        p.add_argument("--type", required=True)
        p.add_argument("--reason", required=True)
        if name == "block":
            p.add_argument("--check", default="")
        else:
            p.add_argument("--check", default=None, help="the row's Check text, when several rows share a reason")
        p.add_argument("--by-owner", action="store_true")
    p = add("rollup", write=True)
    p.add_argument("--id", required=True)
    add("recheck", write=True)
    p = sub.add_parser("render")
    which = p.add_mutually_exclusive_group(required=True)
    which.add_argument("--roadmap")
    which.add_argument("--all", action="store_true", help="every roadmap on origin (used by hooks and commands)")
    p.add_argument("--root", default=".")
    p.add_argument("--out", default=None, help="the HTML file (default ~/.caddis/roadmap-pages/<repo>/<slug>.html)")
    return parser


def _dispatch(args: argparse.Namespace) -> int:
    root = _repo_root(args.root)
    if args.cmd == "list":
        slugs = list_roadmaps(root)
        for slug in slugs:
            print(slug)
        return caddis_exit.CLEAN if slugs else caddis_exit.BLOCKED
    if args.cmd == "status":
        result = status(root, args.roadmap)
        print(json.dumps(result, indent=2) if args.json else result["line"])
        return caddis_exit.CLEAN
    if args.cmd == "next":
        batch, reasons = _select(load(root, args.roadmap), other_roadmap_batches(root, args.roadmap))
        if args.json:
            print(json.dumps({"batch": batch, "skipped": [{"id": i, "reason": r} for i, r in reasons]}))
        else:
            for mid, reason in reasons:
                print(f"{mid}: {reason}")
            print(f"next: {batch['milestone']} {batch['plan']}#{batch['phase']}" if batch
                  else "BLOCKED: no milestone is ready")
        return caddis_exit.CLEAN if batch else caddis_exit.BLOCKED
    if args.cmd == "check":
        errors, warnings = check(root, args.roadmap)
        for w in warnings:
            print(f"WARNING: {w}")
        for e in errors:
            print(f"ERROR: {e}")
        print(f"{len(errors)} error(s), {len(warnings)} warning(s)")
        return caddis_exit.BLOCKED if errors else caddis_exit.CLEAN
    if args.cmd == "set":
        return set_cell(root, args.roadmap, args.id, args.col, args.value, args.by_owner, args.dry_run,
                        reason=args.reason)
    if args.cmd == "block":
        return block(root, args.roadmap, args.id, args.type, args.reason, args.check, args.by_owner, args.dry_run)
    if args.cmd == "unblock":
        return unblock(root, args.roadmap, args.id, args.type, args.reason, args.by_owner, args.dry_run,
                       check_cmd=args.check)
    if args.cmd == "rollup":
        return rollup(root, args.roadmap, args.id, args.dry_run)
    if args.cmd == "recheck":
        return recheck(root, args.roadmap, args.dry_run)
    if args.cmd == "render":
        import caddis_roadmap_page  # the page is separate; only `render` needs it
        if args.all and args.out:
            raise RoadmapError("--out works with one --roadmap, not with --all", caddis_exit.ERROR)
        slugs, on_origin = list_roadmaps_checked(root) if args.all else ([args.roadmap], None)
        failed = written = pruned = 0
        for slug in slugs:  # --all: one bad roadmap must not stop the others
            try:
                path = caddis_roadmap_page.write_page(root, slug, Path(args.out) if args.out else None,
                                                      sys.modules[__name__])
                written += 1
                print(f"[ROADMAP] page written: {path.resolve()}")
            except Exception as exc:  # --all: one roadmap must never stop the others
                if not args.all:
                    raise
                failed += 1
                print(f"[ROADMAP] {slug}: page not written: {exc}", file=sys.stderr)
        try:  # the hub is a convenience: nothing below ever fails a render or changes its exit code
            if args.all and on_origin is not None:  # a roadmap removed from origin leaves the hub too; a listing
                # that failed removes nothing, and a folder still on origin keeps its page even if its render failed
                pruned = caddis_roadmap_page.prune_folder(
                    caddis_roadmap_page.default_page_path(root, "_").parent, on_origin | set(slugs))
            if not args.out and (written or pruned):
                print(f"[ROADMAP] hub written: {caddis_roadmap_page.write_hub().resolve()}")
        except Exception as exc:
            print(f"[ROADMAP] hub not written: {exc}", file=sys.stderr)
        return caddis_exit.BLOCKED if failed else caddis_exit.CLEAN
    return caddis_exit.ERROR


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except RoadmapError as exc:
        print(f"{caddis_exit.MEANING.get(exc.code, 'error').upper()}: {exc}", file=sys.stderr)
        return exc.code
    except Exception as exc:  # an unexpected failure is an error, never "blocked"
        print(f"ERROR: unexpected {type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}",
              file=sys.stderr)
        return caddis_exit.ERROR


if __name__ == "__main__":
    sys.exit(main())
