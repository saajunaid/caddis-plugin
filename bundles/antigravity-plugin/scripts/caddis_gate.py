#!/usr/bin/env python3
"""Machine-enforced gates for the caddis implement loop.

WHY
---
Most of caddis's guarantees are sentences in markdown that a model may or may not honour
(measured: 7.0% machine-enforced at the time this landed — `scripts/enforcement_inventory.py`).
The two gates below are the ones that have actually bitten, so they become exit codes:

  lane-check      the assigned execution lane was never read, so a "cheap" lane ran nothing
  tracker-vs-git  a stray staged edit reverted four completed Tracker rows to "not started"
                  and it was caught two milestones later

DEGRADE OPEN, ALWAYS
--------------------
Every failure to *evaluate* is exit 0 with a note on stderr. A missing plan, an unparseable
Tracker, no git — none of those are gate failures, they are "this gate could not run". A gate
that hard-fails when it cannot read its inputs breaks every consumer the day it ships, and the
first thing anyone does with a gate that cries wolf is switch it off. Only a genuine, positively
identified violation is non-zero.

EXIT CODES
  0  proceed
  1  blocked           — a real violation; the caller must stop
  2  proceed-with-note — degraded/uncertain; caller proceeds but must record it
  3  wrong-lane        — this phase belongs to another lane; the launch command is on stdout
  4  malformed         — the phase's launch command cannot be spawned safely
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import caddis_frontmatter
except ModuleNotFoundError as exc:
    if exc.name != "caddis_frontmatter":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-harness" / "scripts"))
    import caddis_frontmatter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

EXIT_OK, EXIT_BLOCKED, EXIT_NOTE, EXIT_WRONG_LANE, EXIT_MALFORMED = 0, 1, 2, 3, 4

_TRUTHY = {"1", "true", "yes", "on"}


def _degrade(msg: str) -> int:
    """Could not evaluate. Never a failure — see DEGRADE OPEN above."""
    sys.stderr.write(f"[caddis-gate] cannot evaluate: {msg} — proceeding\n")
    return EXIT_OK


def is_headless(env=None) -> bool:
    e = env if env is not None else os.environ
    return str(e.get("CADDIS_HEADLESS", "")).strip().lower() in _TRUTHY


# ── plan parsing ────────────────────────────────────────────────────────────

_PHASE_HEAD = re.compile(r"^###\s+Phase\s+(\d+)\b", re.M)


def phase_block(plan_text: str, phase: int) -> str:
    """The text of one phase, from its heading to the next."""
    starts = [(int(m.group(1)), m.start()) for m in _PHASE_HEAD.finditer(plan_text)]
    for i, (num, pos) in enumerate(starts):
        if num == phase:
            end = starts[i + 1][1] if i + 1 < len(starts) else len(plan_text)
            return plan_text[pos:end]
    return ""


def phase_lane(block: str) -> str:
    m = re.search(r"^\*\*Lane:\*\*\s*(.+)$", block, re.M)
    if not m:
        return ""
    # "claude — this session | glm-headless — `cmd`" → the lane is the first token.
    return m.group(1).strip().split()[0].strip("`*")


def launch_command(block: str) -> str:
    """The literal command for a non-claude lane, if the phase names one.

    Also matches a caddis_lanes.py run command, a direct codex/agy command, and an agy command
    wrapped in the spend wrapper (`python .../caddis_spend.py run --caller X -- agy ...`).
    """
    m = re.search(
        r'`((?:claude-(?:glm|oss|deepseek)\b|' + _LANES_RUN + r'\b|' + _SPEND_RUN
        + r'\b|codex\s+exec\b|agy\b)[^`]*)`',
        block,
    )
    return m.group(1).strip() if m else ""


_LANES_RUN = r'python\s+"?\$\{CLAUDE_PLUGIN_ROOT\}/scripts/caddis_lanes\.py"?\s+run'
# Every agy lane goes through `caddis_spend.py run` (usage log, timeout, depth guard; no EUR cap). Any path that ends in
# scripts/caddis_spend.py: `${CLAUDE_PLUGIN_ROOT}/...`, an expanded plugin-cache path (the codex bundle
# rewrites the variable), or the bare repo-relative `scripts/caddis_spend.py` - which gate_lane accepts
# only in the caddis source repo, because in an app repo that path is a file the agent can write.
_SPEND_RUN = r'python3?\s+"?[^"\s`]*scripts/caddis_spend\.py"?\s+run'
_SPEND_PATH = re.compile(r'python3?\s+"?([^"\s`]*scripts/caddis_spend\.py)"?\s+run')
# Shell control characters outside the quoted prompt would chain a second, unwrapped command.
_SHELL_CHAIN = re.compile(r"[;&|`\n]|\$\(")


def _caddis_source_root(plan: Path) -> bool:
    """True when the plan lives in the caddis source repo (the only place a repo-relative wrapper is trusted)."""
    for parent in plan.resolve().parents:
        if (parent / ".git").exists():
            return (parent / "claude-harness" / "scripts" / "caddis_governor.py").is_file()
    return False


# ── gate: lane-check ────────────────────────────────────────────────────────

_QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'")


def _has_print_flag(cmd: str) -> bool:
    """True when the command carries a real -p/--print flag.

    The quoted prompt is blanked first: a prompt that merely contains the text " -p " must not
    count, or an interactive child passes the gate (R3 cross-review, 2026-09-30).
    """
    return bool(re.search(r"(?:^|\s)(?:-p|--print)(?:\s|$)", _QUOTED.sub('""', cmd)))


# agy needs `--model <id>` BEFORE -p/--print, else it runs its own default model (a downstream project, 2026-11-18: 7 of 7 lane runs
# had no --model, ran the wrong model and hit the 20m print timeout). A 3-task TDD phase needs 40m; caddis_spend kills at 60m.
MIN_AGY_PRINT_TIMEOUT_S = 40 * 60
_PRINT_TIMEOUT = re.compile(r"--print-timeout(?:\s+|=)(\d+(?:\.\d+)?)([smh]?)(?=\s|$)")


def _agy_model_problem(inner: str) -> str:
    """Why an agy command names no usable model, or "" when it does (`--model <id>` before -p/--print)."""
    blank = _QUOTED.sub('""', inner)
    model = re.search(r"(?:^|\s)--model(?:\s+|=)([^\s\-]\S*)", blank)
    if not model:
        return "has no --model <id>"
    flag = re.search(r"(?:^|\s)(?:-p|--print)(?:\s|=|$)", blank)
    if flag and flag.start() < model.start():
        return "puts --model after -p/--print (agy reads --model only before it)"
    return ""


def _agy_timeout_warning(inner: str) -> str:
    """A warning when --print-timeout is missing or under 40 minutes, else ""."""
    match = _PRINT_TIMEOUT.search(_QUOTED.sub('""', inner))
    if not match:
        return "has no --print-timeout (use 40m; a 3-task TDD phase needs it)"
    seconds = float(match.group(1)) * {"s": 1, "": 1, "m": 60, "h": 3600}[match.group(2)]
    if seconds < MIN_AGY_PRINT_TIMEOUT_S:
        return f"has --print-timeout {match.group(1)}{match.group(2)} (under 40m; a 3-task TDD phase needs 40m)"
    return ""


def gate_lane(plan: Path, phase: int) -> int:
    if not plan.is_file():
        return _degrade(f"no plan at {plan}")
    block = phase_block(plan.read_text(encoding="utf-8", errors="ignore"), phase)
    if not block:
        return _degrade(f"phase {phase} not found in {plan.name}")
    lane = phase_lane(block)
    if not lane:
        return _degrade(f"phase {phase} names no Lane:")

    # The asymmetric rule, and the reason this gate is machine-checkable at all: we cannot prove
    # which model we are, but we CAN prove whether someone placed us. A headless/runner session
    # was placed deliberately; an interactive one was not.
    if lane.startswith("claude") or is_headless():
        return EXIT_OK

    cmd = launch_command(block)
    if not cmd:
        sys.stderr.write(f"[caddis-gate] phase {phase} is lane '{lane}' but names no launch command\n")
        return EXIT_MALFORMED
    if re.match(r"agy\b", cmd):
        sys.stderr.write(
            f"[caddis-gate] phase {phase}'s agy command is not wrapped in caddis_spend.py run: {cmd}\n"
            "  agy lanes must go through caddis_spend.py run --caller <name> -- agy ... Refusing to run it.\n")
        return EXIT_MALFORMED
    inner = cmd
    if re.match(_SPEND_RUN, cmd):
        wrapped = re.match(_SPEND_RUN + r'\s+--caller\s+\S+\s+--\s+(agy\b.*)$', cmd, re.S)
        if not wrapped:
            sys.stderr.write(
                f"[caddis-gate] phase {phase}'s caddis_spend command is malformed: {cmd}\n"
                "  Expected: caddis_spend.py run --caller <name> -- agy ... Refusing to run it.\n")
            return EXIT_MALFORMED
        inner = wrapped.group(1)
        # Command substitution runs even inside double quotes (bash and PowerShell), so `$(` and
        # backticks are refused anywhere; `${` is refused after the `--` (the wrapper path may use it).
        if (_SHELL_CHAIN.search(_QUOTED.sub('""', cmd)) or "$(" in cmd or "`" in cmd
                or "${" in inner):
            sys.stderr.write(
                f"[caddis-gate] phase {phase}'s agy command chains another command: {cmd}\n"
                "  A second command after the wrapped agy would run outside caddis_spend.py run. Refusing to run it.\n")
            return EXIT_MALFORMED
        formats = re.findall(r"--output-format(?:\s+|=)(\S+)", _QUOTED.sub('""', inner))
        if formats != ["json"]:
            sys.stderr.write(
                f"[caddis-gate] phase {phase}'s agy command must have exactly one --output-format json: {cmd}\n"
                "  Without JSON output the usage log cannot read the token counts. Refusing to run it.\n")
            return EXIT_MALFORMED
        path = _SPEND_PATH.match(cmd).group(1)
        norm = path.replace("\\", "/")
        trusted = (norm == "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_spend.py"
                   or ("/plugins/cache/" in norm and (norm.startswith("/") or re.match(r"[A-Za-z]:/", norm)
                                                      or norm.startswith("${HOME}/")))
                   or (norm == "scripts/caddis_spend.py" and _caddis_source_root(plan)))
        if not trusted:
            sys.stderr.write(
                f"[caddis-gate] phase {phase}'s agy command uses an untrusted caddis_spend.py path: {cmd}\n"
                "  Use \"${CLAUDE_PLUGIN_ROOT}/scripts/caddis_spend.py\" (or the installed plugin-cache path;\n"
                "  the bare scripts/caddis_spend.py only in the caddis source repo). Refusing to run it.\n")
            return EXIT_MALFORMED
    if re.match(_LANES_RUN, cmd):
        named = re.search(r"--phase[\s=]+(\d+)", cmd)
        if not named:
            sys.stderr.write(
                f"[caddis-gate] phase {phase}'s caddis_lanes command has no --phase N: {cmd}\n"
                "  Without it the lane would run the whole plan. Refusing to run it.\n")
            return EXIT_MALFORMED
        if int(named.group(1)) != phase:
            sys.stderr.write(
                f"[caddis-gate] phase {phase}'s caddis_lanes command names --phase {named.group(1)}: {cmd}\n"
                "  The lane would run another phase's work. Refusing to run it.\n")
            return EXIT_MALFORMED
    elif re.match(r"(?:codex\s+exec|agy)\b", inner):
        if "HEADLESS RUN RULES" not in inner:
            sys.stderr.write(
                f"[caddis-gate] phase {phase}'s direct command has no HEADLESS RUN RULES: {cmd}\n"
                "  The child has no headless run rules. Refusing to run it.\n")
            return EXIT_MALFORMED
        named = re.search(r"Implement Phase (\d+) only", inner)
        if not named:
            sys.stderr.write(
                f"[caddis-gate] phase {phase}'s direct command has no phase restriction: {cmd}\n"
                "  The lane could run the wrong phase. Refusing to run it.\n")
            return EXIT_MALFORMED
        if int(named.group(1)) != phase:
            sys.stderr.write(
                f"[caddis-gate] phase {phase}'s direct command names Phase {named.group(1)}: {cmd}\n"
                "  The lane would run another phase's work. Refusing to run it.\n")
            return EXIT_MALFORMED
        if inner.startswith("agy") and not _has_print_flag(inner):
            sys.stderr.write(
                f"[caddis-gate] phase {phase}'s direct agy command has no -p/--print: {cmd}\n"
                "  The child would not run headless. Refusing to run it.\n")
            return EXIT_MALFORMED
    elif not _has_print_flag(cmd):
        sys.stderr.write(
            f"[caddis-gate] phase {phase}'s launch command has no -p/--print: {cmd}\n"
            "  Without it the child is not marked headless, reads the same Lane line, and spawns\n"
            "  again — unbounded recursion. Refusing to run it.\n")
        return EXIT_MALFORMED
    if inner.startswith("agy"):
        refusal = _agy_model_problem(inner)
        if refusal:
            sys.stderr.write(f"[caddis-gate] phase {phase}'s agy command {refusal}: {cmd}\n"
                             "  Without --model agy runs its own default model, not the routed one. Refusing to run it.\n")
            return EXIT_MALFORMED
        warning = _agy_timeout_warning(inner)
        if warning:
            sys.stderr.write(f"[caddis-gate] WARNING phase {phase}'s agy command {warning}: {cmd}\n")
    print(cmd)
    sys.stderr.write(f"[caddis-gate] phase {phase} belongs to lane '{lane}' — spawn the command above\n")
    return EXIT_WRONG_LANE


# ── gate: tracker-vs-git ────────────────────────────────────────────────────

_ROW = re.compile(r"^\|\s*(\d+(?:-\d+)?)\s*\|(.*)$", re.M)


def gate_tracker(plan: Path, cwd: Path | None = None) -> int:
    if not plan.is_file():
        return _degrade(f"no plan at {plan}")
    text = plan.read_text(encoding="utf-8", errors="ignore")
    if "## Tracker" not in text:
        return _degrade("plan has no ## Tracker")
    tracker = text.split("## Tracker", 1)[1]

    problems: list[str] = []
    for m in _ROW.finditer(tracker):
        cells = [c.strip() for c in m.group(2).split("|")]
        if len(cells) < 4:
            continue
        status, commit = cells[2].lower(), cells[3].strip("`* ")
        done = "done" in status or "✅" in status
        has_commit = commit not in ("", "—", "-", "–")
        if done and not has_commit:
            problems.append(f"phase {m.group(1)} is '{cells[2]}' with no commit recorded")
    measured = measured_violations(text, plan)
    if measured:
        _print_measured(measured)  # a block beats the note below: a phase cannot be done with no measured value
        return EXIT_BLOCKED
    if not problems:
        return EXIT_OK
    for p in problems:
        sys.stderr.write(f"[caddis-gate] tracker/git mismatch: {p}\n")
    sys.stderr.write("  A done row with no commit means the Tracker and the repo disagree. Four rows\n"
                     "  were once reverted by a stray staged edit and caught two milestones later.\n")
    return EXIT_NOTE


# ── gates: measured-check and db-plan-check (plan side of the DB review gate) ───────────────────
#
# uat-refresh Phase 3b passed with a PROD measurement ("step 0") not run, and no uat-refresh plan named a SQL
# reviewer. A phase that depends on a PROD fact says so on a `**Requires measured:** <key> - <fact>` line and is
# not done until its Tracker Notes hold `measured <key>=<value>`. A phase that touches DB code carries a
# `**DB review:**` line and a `**DB checklist:**` that answers each SQL Server load check.
#
# These two gates are exceptions to DEGRADE OPEN, by owner decision: a malformed `Requires measured:` line or a
# done row with no measured value is a positively identified violation and exits 1. A missing plan still degrades.

_PHASE_ID = re.compile(r"^###\s+Phase\s+(\d+[a-z]?)\b", re.M)
_MEASURED_LINE = re.compile(r"^\*\*Requires measured:\*\*[ 	]*(.*)$", re.M)  # [ 	]: never reads the next line
_MEASURED_KEY = re.compile(r"^[a-z0-9][a-z0-9-]*(?=\s|$)")
_MEASURED_VALUE = re.compile(r"measured\s+([a-z0-9][a-z0-9-]*)\s*=\s*([^;|]*)", re.I)
MEASURED_PLACEHOLDERS = frozenset({
    "", "?", "tbd", "todo", "n/a", "na", "-", "—", "–", "pending", "unknown", "not run", "skipped"})


def _scripts_on_path() -> None:
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)


def _phase_ids(plan_text: str) -> list[str]:
    seen: list[str] = []
    for m in _PHASE_ID.finditer(plan_text):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_HEADING_1_3 = re.compile(r"^#{1,3}\s")


def _phase_text(plan_text: str, plan: Path, pid: str) -> str:
    """The text of phase `pid`, sliced from `plan_text`: from its `### Phase <pid>` heading to the next heading of
    level 1-3 that is outside a fenced code block (a `# comment` in a fence is not a heading). `plan` is unused; it
    stays in the signature so callers keep one shape. Empty string when the plan has no such phase."""
    start = re.compile(rf"^###\s+Phase\s+{re.escape(pid)}\b", re.I)
    section: list[str] | None = None
    fence = ""
    for line in plan_text.splitlines():
        in_fence = bool(fence)
        m = _FENCE.match(line)
        if not fence and m:
            fence = m.group(1)
        elif fence and m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) \
                and not line.strip()[len(m.group(1)):].strip():
            fence = ""
        heading = not in_fence and not m and bool(_HEADING_1_3.match(line))
        if section is None:
            if heading and start.match(line):
                section = [line]
        elif heading:
            break
        else:
            section.append(line)
    return "" if section is None else "\n".join(section).rstrip() + "\n"


def required_measurements(section: str) -> tuple[list[str], list[str]]:
    """(keys, malformed_lines) from the `**Requires measured:**` lines of one phase."""
    keys: list[str] = []
    bad: list[str] = []
    for m in _MEASURED_LINE.finditer(section):
        key = _MEASURED_KEY.match(m.group(1).strip())
        if key:
            keys.append(key.group(0))
        else:
            bad.append(m.group(0).strip())
    return keys, bad


def measured_values(row: str) -> dict[str, str]:
    """Every `measured <key>=<value>` pair in a Tracker row; the value ends at `;` or `|`."""
    return {m.group(1).lower(): m.group(2).strip() for m in _MEASURED_VALUE.finditer(row)}


def _tracker_rows(plan_text: str) -> dict[str, tuple[str, str]] | None:
    """phase id -> (status cell, whole row line) from the `## Tracker` table. None when the table has no Status
    column: no phase can then be read as done, and the caller must not treat that as "nothing is done"."""
    try:
        import caddis_rows
        import caddis_todo
    except ModuleNotFoundError:
        _scripts_on_path()
        import caddis_rows
        import caddis_todo
    table = caddis_todo.tracker_table(plan_text)
    if table is None:
        # tracker_table is also None for a Tracker table it cannot read (no Status column, an odd Phase header).
        # That plan has rows we cannot read, which is not the same as a plan with no Tracker table.
        heading = re.search(r"^##\s+(?:\d+[.)]?\s+)?Tracker\b.*$", plan_text, re.M | re.I)
        section = plan_text[heading.end():].split("\n## ", 1)[0] if heading else ""
        return None if re.search(r"^\s*\|", section, re.M) else {}
    columns, lines = table
    at = columns.index("status")
    rows: dict[str, tuple[str, str]] = {}
    for line in lines:
        if not line.lstrip().startswith("|"):
            continue
        cells = caddis_rows.split_cells(line)
        if len(cells) <= at:
            continue
        pid = re.sub(r"^(?:phase|p)\s*", "", cells[0].replace("`", "").replace("*", "").strip(), flags=re.I).lower()
        if pid and pid not in rows:
            rows[pid] = (cells[at], line)
    return rows


def measured_violations(plan_text: str, plan: Path) -> list[str]:
    """Violations: a malformed `Requires measured:` line (always), and each required key with no real value in the
    Tracker row of a done phase."""
    try:
        import caddis_status
    except ModuleNotFoundError:
        _scripts_on_path()
        import caddis_status
    rows = _tracker_rows(plan_text)
    problems: list[str] = []
    for pid in _phase_ids(plan_text):
        keys, bad = required_measurements(_phase_text(plan_text, plan, pid))
        problems += [f"phase {pid}: malformed Requires measured line: {b}" for b in bad]
        if rows is None:
            if keys:
                problems.append(f"phase {pid}: the Tracker table has no readable Phase and Status columns, so measured "
                                f"{', '.join(keys)} cannot be checked")
            continue
        row = rows.get(pid.lower())
        if not keys or row is None or not caddis_status.is_done(row[0]):
            continue
        values = measured_values(row[1])
        for key in keys:
            value = values.get(key)
            if value is None or value.lower() in MEASURED_PLACEHOLDERS or value.startswith("<"):
                problems.append(f"phase {pid}: done without measured {key}")
    return problems


def _print_measured(problems: list[str]) -> None:
    for p in problems:
        sys.stderr.write(f"[caddis-gate] measured-check: {p}\n")
    sys.stderr.write('  Put "measured <key>=<value>" in the phase\'s Tracker Notes, or set the row to blocked.\n')


def gate_measured(plan: Path) -> int:
    if not plan.is_file():
        return _degrade(f"no plan at {plan}")
    problems = measured_violations(plan.read_text(encoding="utf-8", errors="ignore"), plan)
    if problems:
        _print_measured(problems)
        return EXIT_BLOCKED
    print("MEASURED: ok")
    return EXIT_OK


DB_CHECKLIST_KEYS = (
    "stats", "index-options", "fragmentation", "log-volume", "tempdb", "locks", "lost-objects", "dependents",
    "source-read", "run-lock")


def db_review_value(section: str) -> str | None:
    """The text after `**DB review:**` on its first line, stripped; None when the phase has no such line."""
    m = re.search(r"^\*\*DB review:\*\*[ \t]*(.*)$", section, re.M)
    return m.group(1).strip() if m else None


def _opt_out_reason(value: str) -> str | None:
    """None when `value` is not a `none ...` opt-out; else the reason text (may be empty)."""
    if not value.lower().startswith("none"):
        return None
    return value[4:].strip(" -—–:\t")


def is_db_phase(section: str) -> tuple[bool, list[str]]:
    """(is a DB phase, reasons). `**DB review:** none - <reason>` (3+ characters) is an explicit opt-out."""
    value = db_review_value(section)
    if value is not None:
        reason = _opt_out_reason(value)
        if reason is not None and len(reason) >= 3:
            return False, []
    reasons: list[str] = []
    if value is not None:
        reasons.append("DB review line")
    for token in re.findall(r"`([^`\n]+)`", section):
        norm = token.strip().replace("\\", "/").lower()
        if norm.endswith(".sql") or ("/" in norm and any(seg in DB_PATH_SEGMENTS for seg in norm.split("/"))):
            reasons.append(f"path {token.strip()}")
    for label, rx in DB_CONTENT_TRIGGERS:
        if rx.search(section):
            reasons.append(f"keyword {label}")
    return bool(reasons), reasons


_NAME_SEP = re.compile(r" - |—|–")


def _reviewer_tokens(value: str) -> list[str]:
    """Raw tokens after the first `—`, `–` or ` - ` of a `**DB review:**` value; backticks stripped. None for `none`."""
    if value.lower().startswith("none"):  # an opt-out names no reviewer; its reason text is prose
        return []
    m = _NAME_SEP.search(value)
    if m is None:
        return []
    tokens = (t.strip("`") for t in re.split(r"[,\s]+", value[m.end():]))
    return [t for t in tokens if t]


def _is_reviewer(token: str, known: "set[str] | frozenset[str] | tuple[str, ...]") -> bool:
    """An agent name that has a `-` (every shipped reviewer does) or is a configured reviewer. Filler words such as
    `and` or `on` are neither, so prose after the name list never becomes a required reviewer."""
    return bool(_AGENT_NAME.match(token)) and ("-" in token or token in known)


def db_reviewer_names(value: str, known: "set[str] | frozenset[str] | tuple[str, ...]" = ()) -> list[str]:
    """Reviewer names after the first `—`, `–` or ` - ` of a `**DB review:**` value."""
    return [t for t in _reviewer_tokens(value) if _is_reviewer(t, known)]


def db_unknown_reviewer_tokens(value: str, known: "set[str] | frozenset[str] | tuple[str, ...]" = ()) -> list[str]:
    """Tokens after the separator that are not reviewer names: db-plan-check fails on these."""
    return [t for t in _reviewer_tokens(value) if not _is_reviewer(t, known)]


def phase_high_reasons(reasons: list[str]) -> list[str]:
    """The `is_db_phase` reasons that name HIGH-risk DB work: any DB path, and any keyword not on `DB_LOW_LABELS`."""
    return [r for r in reasons
            if r.startswith("path ") or (r.startswith("keyword ") and r[len("keyword "):] not in DB_LOW_LABELS)]


def phase_declared_low(value: str, known: "set[str] | frozenset[str] | tuple[str, ...]" = ()) -> bool:
    """True for a low-risk `**DB review:** diff - <reviewer>` value: it starts with `diff`, says no `design`, and
    names a reviewer. `diff only` (no reviewer) is not a declaration."""
    if value.lower().startswith("none") or re.search(r"\bdesign\b", value, re.I):
        return False
    return bool(re.match(r"diff\b", value, re.I)) and bool(db_reviewer_names(value, known))


def _checklist_unanswered(section: str) -> list[str]:
    """The `DB_CHECKLIST_KEYS` with no answer in the lines after the `**DB checklist:**` line."""
    m = re.search(r"^\*\*DB checklist:\*\*.*$", section, re.M)
    after = section[m.end():] if m else ""
    missing: list[str] = []
    for key in DB_CHECKLIST_KEYS:
        found = re.search(rf"^[ \t]*-[ \t]*{re.escape(key)}:[ \t]*(.*)$", after, re.M)
        answer = found.group(1).strip().lower() if found else ""
        if answer in ("", "?", "tbd", "todo") or answer.startswith("<"):
            missing.append(key)
        elif answer.startswith("n/a") and len(answer[3:].strip(" -—–:\t")) < 3:
            missing.append(key)
    return missing


def _db_plan_scan(plan_text: str, plan: Path, known: frozenset[str] | None = None) -> tuple[list[str], int]:
    known = known if known is not None else frozenset({DB_REVIEWER_DEFAULT})
    problems: list[str] = []
    db_phases = 0
    for pid in _phase_ids(plan_text):
        section = _phase_text(plan_text, plan, pid)
        value = db_review_value(section)
        if value is not None:
            reason = _opt_out_reason(value)
            if reason is not None and len(reason) < 3:
                problems.append(f"phase {pid}: DB review opt-out needs a reason")
                continue
        is_db, reasons = is_db_phase(section)
        if not is_db:
            continue
        db_phases += 1
        if value is not None and phase_declared_low(value, known):
            # Low-risk phase: one diff review, no design review and so no load checklist. Only when the phase text
            # names no HIGH-risk DB work; the diff stage re-checks the real diff (fail closed).
            problems += [f"phase {pid}: DB review names unknown reviewer '{t}' (list agent names, comma separated)"
                         for t in db_unknown_reviewer_tokens(value, known)]
            high = phase_high_reasons(reasons)
            if high:
                problems.append(f"phase {pid}: DB review says diff only (low-risk) but the phase names "
                                f"high-risk DB work ({', '.join(high)}); use design + diff")
            continue
        if value is None:
            problems.append(f"phase {pid}: DB phase ({', '.join(reasons)}) has no **DB review:** line")
        elif not (re.search(r"\bdesign\b", value, re.I) and re.search(r"\bdiff\b", value, re.I)):
            problems.append(f"phase {pid}: DB review must say design + diff")
        if value is not None:
            problems += [f"phase {pid}: DB review names unknown reviewer '{t}' (list agent names, comma separated)"
                         for t in db_unknown_reviewer_tokens(value, known)]
        if re.search(r"^\*\*DB checklist:\*\*", section, re.M) is None:
            problems.append(f"phase {pid}: DB phase has no **DB checklist:**")
        else:
            problems += [f"phase {pid}: DB checklist {key} is not answered" for key in _checklist_unanswered(section)]
    return problems, db_phases


def db_plan_violations(plan_text: str, plan: Path) -> list[str]:
    return _db_plan_scan(plan_text, plan)[0]


def gate_db_plan(plan: Path) -> int:
    if not plan.is_file():
        return _degrade(f"no plan at {plan}")
    reviewer, etl_reviewer = db_review_config(Path("."))
    known = frozenset({reviewer} | ({etl_reviewer} if etl_reviewer else set()))
    plan_text = plan.read_text(encoding="utf-8", errors="ignore")
    if not _phase_ids(plan_text):
        # A spec with no `### Phase N` sections gave a vacuous pass (uat-refresh spec: "ok (0 DB phase(s))"). When its
        # text names DB code, nothing can be checked: fail. A spec with no DB code, or an explicit opt-out, passes.
        is_db, reasons = is_db_phase(plan_text)
        if is_db:
            print("DB-PLAN: no phase sections; cannot check DB review lines")
            sys.stderr.write(f"[caddis-gate] db-plan-check: the plan has no '### Phase N' sections but names DB code "
                             f"({', '.join(reasons)}); add phase sections with **DB review:** lines, or put "
                             f"**DB review:** none - <reason> in the plan\n")
            return EXIT_BLOCKED
    problems, db_phases = _db_plan_scan(plan_text, plan, known)
    if problems:
        for p in problems:
            sys.stderr.write(f"[caddis-gate] db-plan-check: {p}\n")
        return EXIT_BLOCKED
    print(f"DB-PLAN: ok ({db_phases} DB phase(s))")
    return EXIT_OK


# ── gate: db-review (a phase or PR with DB code needs its DB reviews) ────────────────────────────
#
# Two stages, both recorded as one-line evidence in `.caddis/reviews/`:
#   DB-DESIGN p<N> <reviewer> <verdict> blocking=<n> phase=<hash12>        the phase text, before coding
#   DB-DIFF <reviewer> <verdict> blocking=<n> files=<path>@<blob12>,...    the changed DB files, before merge
# Evidence is tied to CONTENT, not to a commit: a git blob id per DB file and a text hash per phase. A rebase that
# keeps the content keeps the evidence; any later edit to a DB file or to the phase text makes the gate fail again.
#
# This is the one gate here that FAILS CLOSED when it cannot read its input. House rule is degrade open (`_degrade`),
# but a diff we cannot read may hold the DB change nobody reviewed, and that is the exact miss this gate exists for.
# Trust limit: the lines are written by the orchestrator from the reviewer's return block. A model can forge them,
# as it can forge a Tracker cell. The gate makes the review happen and makes a stale review visible; it does not
# prove the review was good. The full return block sits beside each line so a human can check it.

_DB_DIFF_LINE = re.compile(
    r"^(?:[-*]\s+)?DB-DIFF\s+(?P<reviewer>[a-z0-9][a-z0-9-]*)\s+(?P<verdict>approved|changes-suggested)\s+"
    r"blocking=(?P<blocking>\d+)\s+files=(?P<files>\S(?:.*?\S)?)[^\S\n]*$", re.M)  # to line end: a path may hold a space
_DB_DESIGN_LINE = re.compile(
    r"^(?:[-*]\s+)?DB-DESIGN\s+p(?P<phase>\d+[a-z]?)\s+(?P<reviewer>[a-z0-9][a-z0-9-]*)\s+"
    r"(?P<verdict>approved|changes-suggested)\s+blocking=(?P<blocking>\d+)\s+phase=(?P<hash>[0-9a-f]{12})\s*$", re.M)


@dataclass(frozen=True)
class DiffReview:
    reviewer: str
    blocking: int
    files: frozenset[str]  # each "path@blob12"


@dataclass(frozen=True)
class DesignReview:
    phase: str
    reviewer: str
    blocking: int
    phase_hash: str


def parse_evidence(text: str) -> tuple[list[DiffReview], list[DesignReview]]:
    """Every well-formed DB-DIFF and DB-DESIGN line in `text`. A malformed line is ignored, so it never counts."""
    diffs = [DiffReview(m["reviewer"], int(m["blocking"]), frozenset(f for f in m["files"].split(",") if f))
             for m in _DB_DIFF_LINE.finditer(text)]
    designs = [DesignReview(m["phase"], m["reviewer"], int(m["blocking"]), m["hash"])
               for m in _DB_DESIGN_LINE.finditer(text)]
    return diffs, designs


def phase_hash(plan: Path, phase: int | str) -> str:
    """sha256 (12 hex) of the phase text without its heading line, so a status mark in the heading does not change it.
    Raises ValueError when the plan has no such phase."""
    plan_text = Path(plan).read_text(encoding="utf-8")
    section = _phase_text(plan_text, Path(plan), str(phase))
    if not section.strip():
        raise ValueError(f"no phase {phase} in {plan}")
    body = "\n".join(line.rstrip() for line in section.splitlines()[1:]).strip()
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


def _range_right(rng: str | None) -> str | None:
    """The state a range ends at: None for no range or a single rev (the working tree), else the right-hand rev."""
    if not rng:
        return None
    for sep in ("...", ".."):
        if sep in rng:
            return rng.split(sep, 1)[1] or "HEAD"
    return None


def file_blob(repo_root: Path, right: str | None, path: str) -> str:
    """First 12 hex of the git blob of `path` at `right` (a rev), or of the working-tree file when `right` is None.
    `deleted` when the file is absent there."""
    if right is None:
        if not (Path(repo_root) / path).is_file():
            return "deleted"
        res = subprocess.run(["git", "-C", str(repo_root), "hash-object", "--", path],
                             capture_output=True, text=True, timeout=30)
        if res.returncode != 0 or not res.stdout.strip():
            raise RuntimeError(f"git hash-object {path} exited {res.returncode}")
        return res.stdout.strip()[:12]
    res = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "--verify", "--quiet", f"{right}:{path}"],
                         capture_output=True, text=True, timeout=30)
    return res.stdout.strip()[:12] if res.returncode == 0 and res.stdout.strip() else "deleted"


def evidence_files(repo_root: Path, plan: Path | None, changed_paths: list[str], explicit: Path | None) -> list[Path]:
    """The existing evidence files to read: `explicit`; else `.caddis/reviews/<plan-stem>-db.md` for a plan; else every
    changed `.caddis/reviews/*.md` plus `.caddis/reviews/db-<branch>.md`."""
    reviews = Path(repo_root) / ".caddis" / "reviews"
    if explicit is not None:
        candidates = [Path(explicit)]
    elif plan is not None:
        candidates = [reviews / f"{Path(plan).stem}-db.md"]
    else:
        candidates = [Path(repo_root) / p for p in changed_paths
                      if p.replace("\\", "/").startswith(".caddis/reviews/") and p.endswith(".md")]
        res = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"],
                             capture_output=True, text=True, timeout=30)
        branch = res.stdout.strip() if res.returncode == 0 else ""
        if branch and branch != "HEAD":
            candidates.append(reviews / f"db-{branch.replace('/', '-')}.md")
    return [c for c in dict.fromkeys(candidates) if c.is_file()]


def required_diff_reviews(
    repo_root: Path,
    rng: str | None,
    hits: list[DbHit],
    reviewer: str,
    etl_reviewer: str | None,
    extra: set[str],
) -> dict[str, set[str]]:
    """`path@blob12` -> the reviewers that must have reviewed that exact file content, one key per non-test hit path."""
    right = _range_right(rng)
    required: dict[str, set[str]] = {}
    for path in sorted({h.path for h in hits if not h.is_test}):
        names = {reviewer} | set(extra)
        if etl_reviewer and is_etl_file(path, {h.label for h in hits if h.path == path}):
            names.add(etl_reviewer)
        required[f"{path}@{file_blob(repo_root, right, path)}"] = names
    return required


def _read_evidence(paths: list[Path]) -> tuple[list[DiffReview], list[DesignReview]]:
    diffs: list[DiffReview] = []
    designs: list[DesignReview] = []
    for path in paths:
        d, g = parse_evidence(path.read_text(encoding="utf-8", errors="replace"))
        diffs += d
        designs += g
    return diffs, designs


def _last_is_clean(blocking_counts: list[int]) -> bool:
    """True when there is an entry and the LAST one (file order, then line order) has no blocking finding: a later
    review of the same content overrides an earlier one, in either direction."""
    return bool(blocking_counts) and blocking_counts[-1] == 0


def _design_status(
    plan: Path, phase: str, evidence_paths: list[Path], reviewer: str, force: bool = False,
    known: frozenset[str] = frozenset(),
) -> tuple[list[str], list[str], str]:
    """(message lines, reviewers still missing, phase hash). Empty lines mean the design is reviewed (or not required).

    `force` is for a diff that has DB code under a phase that did not say so: the design review is then required
    from `reviewer`, and the lines start with the reason."""
    section = _phase_text(Path(plan).read_text(encoding="utf-8"), Path(plan), phase)
    is_db, _ = is_db_phase(section)
    if not is_db and not force:
        return [], [], ""
    required = {reviewer} | set(db_reviewer_names(db_review_value(section) or "", known | {reviewer}))
    current = phase_hash(plan, phase)
    _, designs = _read_evidence(evidence_paths)
    missing = sorted(r for r in required if not _last_is_clean(
        [d.blocking for d in designs if d.phase == phase and d.reviewer == r and d.phase_hash == current]))
    if not missing:
        return [], [], current
    lines = [f"missing design review: {r} on phase {phase} (phase={current})" for r in missing]
    if not is_db:
        lines.insert(0, f"phase {phase} has DB code but no **DB review:** line; review the phase text now")
    return lines, missing, current


def _design_missing(plan: Path, phase: str, evidence_paths: list[Path], reviewer: str) -> list[str]:
    return _design_status(plan, phase, evidence_paths, reviewer)[0]


# What each checklist key asks a reviewer. In the blind reviewer benchmark no reviewer found a missing statistics
# update unprompted, and most missed MAXDOP and sp_refreshview, so every DB review brief MUST carry these.
DB_CHECKLIST_BRIEF: dict[str, str] = {
    "stats": "statistics updated after the load (UPDATE STATISTICS or sp_updatestats on every table loaded)",
    "index-options": "index builds and rebuilds use SORT_IN_TEMPDB, MAXDOP and ONLINE/RESUMABLE where the edition allows",
    "fragmentation": "fragmented indexes are reorganised or rebuilt after the load",
    "log-volume": "transaction log volume and recovery model for the rows loaded; batch size",
    "tempdb": "tempdb use by sorts, spills and temp tables",
    "locks": "lock escalation, blocking and LOCK_TIMEOUT for the readers of the target tables",
    "lost-objects": "indexes, constraints, triggers, defaults and permissions lost by a drop or rename swap",
    "dependents": "dependent views and procedures: sp_refreshview after a drop or rename swap",
    "source-read": "how the source is read: consistency, isolation, partial reads",
    "run-lock": "a run lock (sp_getapplock) so two runs cannot overlap",
}


def db_review_brief() -> str:
    """The SQL Server load checklist every DB review brief must carry, design review and diff review alike."""
    assert tuple(DB_CHECKLIST_BRIEF) == DB_CHECKLIST_KEYS
    lines = ["Check each item against SQL Server behaviour for this change. A missing or wrong step is blocking:"]
    lines += [f"- {key}: {text}" for key, text in DB_CHECKLIST_BRIEF.items()]
    lines.append("- large DELETE+INSERT: nonclustered indexes are disabled before and rebuilt after the load")
    return "\n".join(lines)


def _db_blocked(lines: list[str], triggers: list[str], searched: list[Path], records: list[str]) -> int:
    print("DB-REVIEW: BLOCKED")
    sys.stderr.write("[caddis-gate] db-review: a DB review is missing\n")
    for line in lines:
        sys.stderr.write(f"  {line}\n")
    if triggers:
        sys.stderr.write(f"  triggers: {', '.join(triggers)}\n")
    sys.stderr.write(f"  evidence searched: {', '.join(p.as_posix() for p in searched) or 'none found'}\n")
    for record in records:
        sys.stderr.write(f"  after the review, record: {record}\n")
    sys.stderr.write("  put this checklist in every reviewer brief (also: db-review --print-brief):\n")
    for line in db_review_brief().splitlines():
        sys.stderr.write(f"    {line}\n")
    return EXIT_BLOCKED


def _design_needed(section: str, risk: str | None, known: "frozenset[str]" = frozenset()) -> bool:
    """Whether the phase text needs a design review. `risk` is the diff's risk (None when no diff was read).
    HIGH diff: always (the plan may have missed the DB code). LOW diff: only when the phase text itself names HIGH
    work. No diff: a DB phase, unless it declares `diff - <reviewer>` and its text names no HIGH work."""
    is_db, reasons = is_db_phase(section)
    if risk == "high":
        return True
    high_text = bool(phase_high_reasons(reasons))
    if risk == "low":
        return is_db and high_text
    declared_low = phase_declared_low(db_review_value(section) or "", known)
    return is_db and (high_text or not declared_low)


def _diff_risk(repo_root: Path, rng: str) -> str | None:
    """The risk of the DB code in an explicit range; an unreadable diff raises (the caller fails closed)."""
    changed = parse_diff_lines(_diff_text(rng, repo_root))
    return db_risk(db_triggers(list(changed), changed), changed)  # path rules need the paths


def _usage(msg: str) -> int:
    sys.stderr.write(f"[caddis-gate] db-review: {msg}\n")
    return EXIT_MALFORMED


DB_PHASE_CODE_LABEL = "db-phase-code"  # a code file of a declared DB phase whose diff no hit rule matched


def _phase_code_file(path: str) -> bool:
    """A changed file the diff review of a DB phase must cover: code, not a test, not docs/.caddis, not the gate."""
    norm = path.replace("\\", "/").lower()
    return (norm.endswith(DB_CODE_EXTS) and not is_test_file(path) and not is_tier0_file(path)
            and norm.removeprefix("./") not in DB_GATE_SELF_PATHS)


def gate_db_review(
    repo_root: Path,
    rng: str | None = None,
    plan: Path | None = None,
    phase: str | None = None,
    stage: str = "diff",
    evidence: Path | None = None,
    print_files: bool = False,
    print_hash: bool = False,
    print_brief: bool = False,
) -> int:
    """Exit 1 unless every current DB file has a clean review from every required reviewer (stage `diff`), and, with
    a plan and phase, the current phase text has a design review. Stage `design` checks the phase text alone.
    Any failure to read the diff or the named plan exits 1: see the block comment above."""
    if print_brief:
        print(db_review_brief())
        return EXIT_OK
    if stage not in ("diff", "design"):
        return _usage(f"unknown --stage '{stage}' (use diff or design)")
    if (plan is None) != (phase is None):
        return _usage("--plan and --phase go together")
    if (stage == "design" or print_hash) and plan is None:
        return _usage("--stage design and --print-hash need --plan and --phase")
    phase = str(phase).strip() if phase is not None else None
    try:
        return _db_review(Path(repo_root), rng, plan, phase, stage, evidence, print_files, print_hash)
    except Exception as exc:  # noqa: BLE001 - fail closed: an unreadable input may hide the unreviewed change
        sys.stderr.write(f"[caddis-gate] db-review: cannot evaluate ({type(exc).__name__}: {exc}); "
                         "a DB review is required\n")
        print("DB-REVIEW: BLOCKED")
        return EXIT_BLOCKED


def _db_review(repo_root, rng, plan, phase, stage, evidence, print_files, print_hash) -> int:
    reviewer, etl_reviewer = db_review_config(repo_root)
    known = frozenset({reviewer} | ({etl_reviewer} if etl_reviewer else set()))
    section = None
    if plan is not None and (stage == "design" or print_hash):
        section = _phase_text(Path(plan).read_text(encoding="utf-8"), Path(plan), phase)  # unreadable plan: raises
        if not section.strip():
            raise ValueError(f"no phase {phase} in {plan}")
    if print_hash:
        print(f"PHASE-HASH: {phase_hash(plan, phase)}")
        return EXIT_OK

    if stage == "design":
        if not is_db_phase(section)[0]:
            print("DB-REVIEW: not a DB phase")
            return EXIT_OK
        # With an explicit range the diff's risk counts; before coding there is no diff and the phase text decides.
        if not _design_needed(section, _diff_risk(repo_root, rng) if rng else None, known):
            print("DB-REVIEW: not required (low-risk DB change)")
            return EXIT_OK
        paths = evidence_files(repo_root, plan, [], evidence)
        lines, missing, current = _design_status(plan, phase, paths, reviewer, force=True, known=known)
        if lines:
            records = [f"DB-DESIGN p{phase} {r} <approved|changes-suggested> blocking=0 phase={current}"
                       for r in missing]
            return _db_blocked(lines, [], paths, records)
        print("DB-REVIEW: PASS")
        return EXIT_OK

    # stage diff. No range means the working tree against HEAD (staged and unstaged), never the unstaged part only.
    diff_rng = rng or "HEAD"
    try:
        files = _numstat(diff_rng, repo_root)
        changed = parse_diff_lines(_diff_text(diff_rng, repo_root))
    except Exception as exc:  # noqa: BLE001 - fail closed
        sys.stderr.write(f"[caddis-gate] db-review: cannot read the diff ({exc}); a DB review is required\n")
        print("DB-REVIEW: BLOCKED")
        return EXIT_BLOCKED
    changed_paths = [p for p, _ in files]
    hits = db_triggers(changed_paths, changed)
    real = [h for h in hits if not h.is_test]
    extra: set[str] = set()
    if plan is not None:
        # A named plan and phase are validated even when the diff has no DB hits: the hit rules can miss DB code.
        section = _phase_text(Path(plan).read_text(encoding="utf-8"), Path(plan), phase)  # unreadable plan: raises
        if not section.strip():
            raise ValueError(f"no phase {phase} in {plan}")
        extra = set(db_reviewer_names(db_review_value(section) or "", known))
    risk = db_risk(hits, changed)  # None without a non-test hit
    if not real and section is not None and is_db_phase(section)[0]:
        # The phase says it is DB work but no hit rule fired (SQL built in a helper, `EXEC` by name): the rules
        # missed it. Each changed non-test code file gets the diff review; the phase text sets the risk.
        real = [DbHit(DB_PHASE_CODE_LABEL, p, False) for p in changed_paths if _phase_code_file(p)]
        hits = hits + real
        if real:
            risk = "high" if _design_needed(section, None, known) else "low"
    if not real:
        if not print_files and section is not None and _design_needed(section, None, known):
            paths = evidence_files(repo_root, plan, changed_paths, evidence)
            lines, missing, current = _design_status(plan, phase, paths, reviewer, force=True, known=known)
            if lines:
                records = [f"DB-DESIGN p{phase} {r} <approved|changes-suggested> blocking=0 phase={current}"
                           for r in missing]
                return _db_blocked(lines, [], paths, records)
            print("DB-REVIEW: PASS")
            return EXIT_OK
        print("DB-REVIEW: not required - tests-only diff" if hits else "DB-REVIEW: not required")
        return EXIT_OK
    # A LOW diff needs sql-expert alone: the opt-in ETL reviewer is added for HIGH diffs only.
    required = required_diff_reviews(repo_root, diff_rng, hits, reviewer, None if risk == "low" else etl_reviewer, extra)
    if print_files:
        print(f"FILES: {','.join(sorted(required))}")
        return EXIT_OK

    paths = evidence_files(repo_root, plan, changed_paths, evidence)
    diff_reviews, _ = _read_evidence(paths)
    lines: list[str] = []
    needed_by: dict[str, list[str]] = {}
    for key in sorted(required):
        for r in sorted(required[key]):
            if not _last_is_clean([d.blocking for d in diff_reviews if d.reviewer == r and key in d.files]):
                lines.append(f"missing: {r} on {key}")
                needed_by.setdefault(r, []).append(key)
    records = [f"DB-DIFF {r} <approved|changes-suggested> blocking=0 files={','.join(keys)}"
               for r, keys in sorted(needed_by.items())]
    if plan is not None and _design_needed(section, risk, known):
        design_lines, design_missing, current = _design_status(plan, phase, paths, reviewer, force=True, known=known)
        lines += design_lines
        records += [f"DB-DESIGN p{phase} {r} <approved|changes-suggested> blocking=0 phase={current}"
                    for r in design_missing]
    if lines:
        return _db_blocked(lines, [f"{h.label} ({h.path})" for h in real], paths, records)
    print("DB-REVIEW: PASS")
    return EXIT_OK


def gate_parking_lot(repo_root: Path) -> int:
    """Every future-work item conforms to the one-register contract, or the push stops.

    caddis had the parking-lot convention for months and it drifted anyway: on 2026-08-14 the
    directory held four different `type:` values (`issue`, `proposal`, `plan`, `parking-lot`), four
    different `status:` spellings, and one 89 KB file that was a second register wearing an item's
    clothes. None of that was caught, because nothing was looking.

    Docs alone were already tried. Parking-lot item 002 is the record of an agent that filed a hub
    artifact in the wrong directory while the correct path sat unread on line 188 of the command it
    skipped. The lesson generalises: a convention nothing can fail is a convention that decays.

    Degrades open like every gate here — no `.caddis/`, no directory, an unreadable file: exit 0.
    Only a positively identified violation blocks.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import caddis_tidy
    except Exception as exc:
        return _degrade(f"caddis_tidy unavailable: {type(exc).__name__}")

    d = repo_root / ".caddis" / caddis_tidy.PARKING_LOT_DIR
    if not d.is_dir():
        return _degrade(f"no parking-lot at {d}")
    report = caddis_tidy.tidy(repo_root, apply=False, kinds=(caddis_tidy.PARKING_LOT_DIR,))
    if not report.violations:
        return EXIT_OK
    sys.stderr.write(
        f"[caddis-gate] {len(report.violations)} parking-lot violation(s) — future work must be "
        "one item per file, under one contract:\n")
    for path, msg in report.violations:
        try:
            shown = path.relative_to(repo_root)
        except ValueError:
            shown = path
        sys.stderr.write(f"    {shown}: {msg}\n")
    sys.stderr.write(
        "  Fix them, or run `/caddis:park` to file the item correctly. The contract is in\n"
        "  .caddis/parking-lot/README.md.\n")
    return EXIT_BLOCKED


def gate_vendor_drift(repo_root: Path) -> int:
    """A vendored `.github/tools/*.py` that no longer matches the caddis copy it came from.

    This gate exists because of a FALSE PASS, not a crash. On 2026-08-10 `/caddis:cross-review`
    returned CLEAN on a database write path that was never reviewed. The tool was fixed on
    2026-08-01; the repo was running its own vendored copy from before that, because the command
    resolves `.github/tools/` FIRST and nothing compared the two files.

    The general shape is the dangerous part: a vendored copy makes every caddis fix conditional on
    a file nobody remembers copying. It fails in the safe-looking direction, which is why it went
    unnoticed for nine days.

    Degrades open: no CLAUDE_PLUGIN_ROOT (nothing to compare), no vendored dir, or the caddis
    authoring repo itself -> exit 0.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import claudster_doctor
    except Exception as exc:
        return _degrade(f"claudster_doctor unavailable: {type(exc).__name__}")

    if not os.environ.get("CLAUDE_PLUGIN_ROOT"):
        return _degrade("CLAUDE_PLUGIN_ROOT unset — nothing to compare the vendored copies against")
    drift = claudster_doctor.vendored_drift(repo_root)
    if not drift:
        return EXIT_OK
    sys.stderr.write(
        f"[caddis-gate] {len(drift)} vendored script(s) differ from the caddis copy:\n")
    for line in drift:
        sys.stderr.write(f"    {line}\n")
    sys.stderr.write(
        "  The vendored copy WINS at run time, so a caddis fix you already paid for may never\n"
        "  reach you. Delete the vendored copy to use the shipped one, or diff them and keep the\n"
        "  local change deliberately.\n")
    return EXIT_BLOCKED


# A backticked path in a handover. Placeholders (`<feature>`, `{slug}`, globs) are excluded here
# rather than filtered later, because a gate that reports `\.caddis/plans/<feature>.md` as missing
# teaches the reader to skim its output, and a skimmed gate catches nothing.
_DOC_PATH = re.compile(r"`([^`\s<>{}*?]+?\.(?:md|py|ts|tsx|json|ya?ml|sh|ps1|html|toml|sql))`")


def gate_handover_check(doc: Path, repo_root: Path, max_chars: int | None = None) -> int:
    """Every file a handover names must exist. Nothing else in a handover is machine-checkable.

    A succession prompt is written from memory, so it names files the writer BELIEVES are there.
    Bringing one Hub to a usable state took nine corrective round trips and the user caught six of
    them; one was "which prompt exists — the legacy one or the contract-shaped one?", which is this
    check exactly (`.caddis/parking-lot/004-handover-is-recalled-not-generated.md`).

    SCOPE, STATED HONESTLY. The parking-lot note asks for four checks. Two are mechanical and are
    implemented here: paths exist, and generated artefacts are not older than their generators. The
    other two — "do the numbers match the live system" and "is a settled claim contradicted by a
    later withdrawal" — need conventions that do not exist yet, and a gate that pretends to check
    them would be worse than one that says it does not.

    Degrades open on a missing/unreadable doc. Blocks on a path the doc claims and the repo does
    not have, and -- only when the caller passes ``max_chars`` -- on a doc longer than that. The
    cap is opt-in: /handoff caps a workstream relay at 4,000 characters, but a /spawn-session
    handover may embed a full inventory verbatim and would not fit.
    """
    if not doc.is_file():
        return _degrade(f"no handover doc at {doc}")
    try:
        text = doc.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return _degrade(f"cannot read {doc}: {type(exc).__name__}")

    if max_chars is not None and len(text) > max_chars:
        sys.stderr.write(
            f"[caddis-gate] handover doc {doc.name} exceeds {max_chars:,} characters ({len(text)} chars)\n"
        )
        return EXIT_BLOCKED

    # `/handoff` Step 3c saves the open tasks beside the relay. A tasks file the resume prompt
    # never names is a task list the next session never reloads.
    tasks_file = doc.with_name(doc.stem + ".tasks.md")
    if tasks_file.is_file() and tasks_file.name not in text:
        sys.stderr.write(f"handover-check: the resume prompt does not load {tasks_file.name}\n")
        return EXIT_BLOCKED

    done_bullets = 0
    in_done = in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):  # a heading or bullet inside a code block is text, not structure
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if stripped.startswith("## Done"):
            in_done = True
            continue
        if in_done:
            if re.match(r"#{1,2} ", stripped):  # the next ## (or #) section ends Done; a ### stays inside it
                in_done = False
                continue
            if line.lstrip().startswith(("- ", "* ")):
                done_bullets += 1
    if done_bullets > 8:
        sys.stderr.write(f"handover-check: Done has {done_bullets} bullets; the cap is 8\n")
        return EXIT_BLOCKED

    missing: list[str] = []
    try:
        # One rule for both gates: `caddis_spawn.check_document` already treats a bare filename
        # that matches no tracked file as a note (probably another repository's file), and one
        # that matches tracked files as a block that names the full path. Two gates giving
        # different answers to the same question is the defect this replaces.
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        import caddis_spawn
        findings = caddis_spawn.check_document(text, repo_root)
        missing = sorted(set(findings.missing_paths))
        for name in findings.unresolved_names:
            sys.stderr.write(
                f"[caddis-gate] note: `{name}` is a bare filename that matches no tracked file here; "
                "not checked\n")
    except Exception as exc:
        # Degrade to the plain existence rule, but say why: a bug inside the shared helper must
        # not hide behind the fallback (an ImportError is the expected, quiet case).
        if not isinstance(exc, ImportError):
            sys.stderr.write(
                f"[caddis-gate] note: shared path check failed ({type(exc).__name__}: {exc}); "
                "using the plain existence rule\n")
        missing = []
        for raw in sorted(set(_DOC_PATH.findall(text))):
            # A backtick often wraps a whole command; the path is the token that looks like one.
            cand = next((tok for tok in raw.split() if "/" in tok or tok.endswith(".md")), raw)
            cand = cand.strip("(),;:'\"")
            if cand.startswith(("http://", "https://", "~", "$")) or ".." in cand:
                continue
            if not (repo_root / cand).exists():
                missing.append(cand)

    stale: list[dict] = []
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import caddis_inventory
        stale = caddis_inventory.stale_artifacts(repo_root)
    except Exception:
        pass  # advisory half — never let it decide the exit code

    for s in stale:
        sys.stderr.write(
            f"[caddis-gate] note: {s['artifact']} was committed before {s['generator']} last "
            "changed — rebuild it before quoting it\n")

    if not missing:
        return EXIT_OK
    sys.stderr.write(
        f"[caddis-gate] the handover names {len(missing)} path(s) that do not exist:\n")
    for m in missing:
        sys.stderr.write(f"    {m}\n")
    sys.stderr.write(
        "  The incoming session cannot know these are wrong — it has no other source for them.\n"
        "  Fix the paths, or generate the inventory with `python scripts/caddis_inventory.py`\n"
        "  instead of writing it from memory.\n")
    return EXIT_BLOCKED


# ── cross-review trigger ────────────────────────────────────────────────────────────────────
# serve-sight shipped FOUR production releases in one day, sixteen fixes across SQL, caches,
# refresh jobs and React. `/caddis:cross-review` ran ZERO times. Not because it was broken:
# `oss_review.py --check-config` reported it ready with two providers keyed. Nothing called it.
#
# Measured there: 4 of 39 plan files mention cross-review, and all four are /feature-plan outputs,
# because that command writes the line into the plan template it emits. So planned feature work
# got reviewed and a bug batch did not — REVIEW COVERAGE INVERSELY CORRELATED WITH URGENCY.
#
# Two of that day's sixteen fixes were diff-visible defects: a cache whose docstring said "cached
# for the instance's life" while a FastAPI dependency rebuilt the object per request, so the cache
# was never once read (5.03s per call, and the docstring described the bug while reading as a
# design note); and two endpoints with no cache at all on a page with a 1s standard.
#
# Every rule below is checkable from `git diff --name-only` plus a line count. NO JUDGEMENT — that
# is the point, because judgement is exactly what failed. Prose in a command would be one more
# thing to remember, and 008 section 2 is this repo's record of a rule that lived only in a
# document and lost to the artefact.
REVIEW_BIG_DIFF_LINES = 400

# (label, why, path-segment needles). Matched against lowercased POSIX path segments and the file
# stem, never a bare substring of the whole path — `services` must be a directory or a filename
# part, so `deprecated_services_notes.md` matches and `microservices-README` in a docs tree does
# not sneak in through a parent directory nobody meant.
REVIEW_TRIGGERS = [
    ("sql", "where a wrong number is born — presence is not correctness",
     ("sql", "queries", "query", "repositories", "repository", "migrations", "migration")),
    ("services", "the layer the 2026-08-31 cache defects lived in, with no SQL in the diff",
     ("services", "service")),
    ("caching", "hit twice in one day at serve-sight",
     ("cache", "caches", "caching", "refresh", "memo", "memoize")),
    ("auth", "a mistake here is a breach, not a bug",
     ("auth", "rbac", "permission", "permissions", "role", "roles", "authz", "authn")),
]


def _changed(repo_root: Path, rev_range: str | None) -> tuple[list[str], int]:
    """(paths, changed-line-count) for the working tree, or for an explicit range."""
    args = ["git", "-C", str(repo_root), "diff", "--numstat"]
    if rev_range:
        args.append(rev_range)
    out = subprocess.run(args, capture_output=True, text=True, timeout=30).stdout
    paths, lines = [], 0
    for row in out.splitlines():
        parts = row.split("	")
        if len(parts) != 3:
            continue
        add, dele, path = parts
        paths.append(path.strip())
        for n in (add, dele):
            if n.isdigit():
                lines += int(n)
    return paths, lines


def review_triggers(paths: list[str], changed_lines: int) -> list[tuple[str, str, list[str]]]:
    """[(label, why, matching paths)] — empty means the diff does not warrant a second opinion."""
    fired: list[tuple[str, str, list[str]]] = []
    for label, why, needles in REVIEW_TRIGGERS:
        hits = []
        for p in paths:
            segs = [seg.lower() for seg in p.replace("\\", "/").split("/")]
            stem = segs[-1].rsplit(".", 1)[0] if segs else ""
            parts = set(segs[:-1]) | set(stem.replace("-", "_").split("_")) | {stem}
            # `.sql` belongs to the sql rule ONLY. Left in the shared condition it made every
            # trigger fire on any .sql file, so one migration reported sql+services+caching+auth
            # and the reason column became noise.
            if parts & set(needles) or (label == "sql" and segs[-1].endswith(".sql")):
                hits.append(p)
        if hits:
            fired.append((label, why, sorted(hits)))
    if changed_lines > REVIEW_BIG_DIFF_LINES:
        fired.append(("size", f"{changed_lines} changed lines — size alone stops being reviewable",
                      []))
    return fired


# ── DB triggers: SQL or DB code in a diff needs a DB review (db-review-gate) ────────────────────
#
# The DBA's first look at uat-refresh 0.3.0 found five standard SQL Server load gaps that no agent
# review raised, because no plan named a SQL reviewer. `review-tier` reads the diff CONTENT for DB
# code and prints a `DB:` line that names the reviewer and the triggers. No judgement: a path rule
# or a regex either fires or it does not. Over-firing is the main risk (people learn to ignore the
# line), so: code extensions only, markdown and docs never, test files marked and never required.

DB_CODE_EXTS: tuple[str, ...] = (
    ".py", ".sql", ".ps1", ".psm1", ".sh", ".cs", ".java", ".js", ".ts", ".go", ".rb", ".kt", ".scala")
DB_PATH_SEGMENTS = frozenset({"alembic", "migrations", "migration"})
DB_MULTILINE_LABELS = frozenset({"update"})  # matched on the joined changed lines: `UPDATE t` then `SET a = 1`

# (label, pattern), in output order. `merge` is case-sensitive on purpose: prose "merge into main"
# and identifiers like MERGE_LOCK must not fire; uppercase SQL `MERGE INTO dbo.T` must.
DB_CONTENT_TRIGGERS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("create-alter-drop", re.compile(
        r"\b(?:CREATE|ALTER|DROP)\s+(?:UNIQUE\s+)?(?:(?:NON)?CLUSTERED\s+)?(?:INDEX|TABLE)\b", re.IGNORECASE)),
    ("insert-into", re.compile(r"\bINSERT\s+INTO\b", re.IGNORECASE)),
    ("delete-from", re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE)),
    # `UPDATE <target> SET` (a TOP or table-hint form too), so prose "update the docs" and `x.update(` do not fire.
    ("update", re.compile(
        r"\bUPDATE\s+(?:TOP\s*\(\s*\d+\s*\)\s+)?[\w\[\].#@]+(?:\s+WITH\s*\([^)]*\)|\s+(?:AS\s+)?\w+)?\s+SET\b",
        re.IGNORECASE)),
    ("merge", re.compile(
        r"\bMERGE\s+(?:TOP\s*\(\s*\d+\s*\)\s+)?(?:INTO\s+[\[A-Za-z_#@]|\[|[A-Za-z_]\w*\.[\w\[\]]+"
        r"|[A-Za-z_]\w*\s+(?:AS\s+)?\w+\s+USING\b)")),
    ("sp-rename", re.compile(r"\bsp_rename\b", re.IGNORECASE)),
    ("openjson", re.compile(r"\bOPENJSON\b", re.IGNORECASE)),
    ("bulk-insert", re.compile(r"\bBULK\s+INSERT\b", re.IGNORECASE)),
    ("truncate-table", re.compile(r"\bTRUNCATE\s+TABLE\b", re.IGNORECASE)),
    ("executemany", re.compile(r"\.executemany\s*\(", re.IGNORECASE)),
    ("cursor-execute", re.compile(
        r"\b(?:cursor|cur|conn|connection|session|engine|db|tx|txn)\w*(?:\(\))?\.execute\s*\(", re.IGNORECASE)),
    ("sqlalchemy-text", re.compile(
        r"\b(?:sa|sqlalchemy)\.text\s*\(|\btext\s*\(\s*[rRuUbBfF]{0,2}(?:\"\"\"|'''|\"|')\s*"
        r"(?:SELECT|INSERT|UPDATE|DELETE|MERGE|WITH|EXEC|EXECUTE|CREATE|ALTER|DROP|TRUNCATE)\b", re.IGNORECASE)),
)


@dataclass(frozen=True)
class DbHit:
    label: str
    path: str
    is_test: bool


def parse_diff_lines(diff_text: str) -> dict[str, list[str]]:
    """path -> changed lines (text after the leading `+`/`-`), from `git diff -U0 --no-renames` output.

    The path is the `+++ b/<p>` path, or the `--- a/<p>` path when the file was deleted. File header lines
    are read only before the first `@@` of a file, so a removed SQL comment `-- x` (shown as `--- x`) stays content."""
    out: dict[str, list[str]] = {}
    old_path: str | None = None
    current: str | None = None
    in_hunk = False

    def _clean(raw: str, prefix: str) -> str:
        raw = raw.rstrip("\t").strip()
        if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
            raw = raw[1:-1]
        return raw[len(prefix):] if raw.startswith(prefix) else raw

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            old_path, current, in_hunk = None, None, False
            continue
        if line.startswith("@@"):
            in_hunk = True
            continue
        if not in_hunk:
            if line.startswith("--- "):
                old_path = None if line[4:].strip() == "/dev/null" else _clean(line[4:], "a/")
            elif line.startswith("+++ "):
                target = line[4:].strip()
                current = old_path if target == "/dev/null" else _clean(line[4:], "b/")
                if current is not None:
                    out.setdefault(current, [])
            continue
        if current is None or not line or line[0] not in "+-":
            continue
        out[current].append(line[1:])
    return out


# The gate's own source names every trigger keyword in its pattern table, comments and tests. It is a tool, not DB
# code, so its content is exempt (path rules still apply). Reviewed by hand; the exemption is this one path.
DB_GATE_SELF_PATHS = frozenset({"scripts/caddis_gate.py"})


def db_triggers(paths: list[str], changed: dict[str, list[str]]) -> list[DbHit]:
    """DB hits for a diff: path rules on `paths`, content rules on the changed lines of code files.

    One hit per (label, path). Order: by path, then `sql-file`, `migration-path`, then `DB_CONTENT_TRIGGERS` order.
    A non-test file under docs/ or .caddis/ (tier 0) is skipped; a test file is kept and marked `is_test`."""
    hits: list[DbHit] = []
    for path in sorted(set(paths) | set(changed)):
        if is_tier0_file(path) and not is_test_file(path):
            continue
        norm = path.replace("\\", "/").lower()
        segs = norm.split("/")
        is_test = is_test_file(path)
        if norm.endswith(".sql"):
            hits.append(DbHit("sql-file", path, is_test))
        if any(seg in DB_PATH_SEGMENTS for seg in segs[:-1]):
            hits.append(DbHit("migration-path", path, is_test))
        if norm.endswith(DB_CODE_EXTS) and norm.removeprefix("./") not in DB_GATE_SELF_PATHS:
            lines = changed.get(path, [])
            joined = "\n".join(lines)
            for label, rx in DB_CONTENT_TRIGGERS:
                if any(rx.search(ln) for ln in lines) or (label in DB_MULTILINE_LABELS and rx.search(joined)):
                    hits.append(DbHit(label, path, is_test))
    return hits


# ── DB risk tiers (db-review-gate Phase 7) ──────────────────────────────────────────────────────
#
# Not every DB change is critical. A read-only SELECT in an endpoint does not need the review of a table swap
# (measured 18 Nov: one sql-expert review of the 4 uat-refresh files took 609 s). Two tiers:
#   HIGH  today's rule: tier 2, sql-expert at design AND diff. DDL, renames, deletes, merges, bulk loads, JSON
#         shredding, batch writes, migrations and .sql files.
#   LOW   one sql-expert DIFF review, no design review, no tier bump: ONLY a read-only SELECT, written as a plain
#         string literal and passed directly inside a visible execute( / executemany( / text( call on a changed
#         line. Every write (INSERT, UPDATE, ...) is HIGH, single or not.
# Fail closed: anything else is HIGH: a label on neither list, a SQL string not passed in a visible call, an f-string,
# concatenation, `%` or `.format`, a variable, an unclosed literal, and any mix. These lists are initial values:
# the feedback loop (.caddis/kb/db-review-feedback.md) moves a label when real PRs say so.

DB_HIGH_LABELS = frozenset({
    "create-alter-drop", "sp-rename", "insert-into", "delete-from", "update", "merge", "bulk-insert",
    "openjson", "truncate-table", "executemany", "sql-file", "migration-path"})
DB_LOW_LABELS = frozenset({"cursor-execute", "sqlalchemy-text"})

# Every call that can carry SQL. The argument must be a plain string literal (or a nested text( call).
_CALL = re.compile(
    r"\b(?:cursor|cur|conn|connection|session|engine|db|tx|txn)\w*(?:\(\))?\.(?:execute|executemany)\s*\("
    r"|\b(?:sa\.|sqlalchemy\.)?text\s*\(", re.IGNORECASE)
_TEXT_NEXT = re.compile(r"\s*(?:sa\.|sqlalchemy\.)?text\s*\(", re.IGNORECASE)
_STR_OPEN = re.compile(r"""\s*[rRuU]{0,2}(\"\"\"|\'\'\'|\"|\')""")  # no f- or b-prefix: those are not plain
# A word that makes a statement more than a read. `;` may only end the statement.
_NOT_A_READ = re.compile(
    r"\b(?:INTO|INSERT|UPDATE|DELETE|MERGE|EXEC|EXECUTE|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE|BACKUP|RESTORE|DBCC"
    r"|OPENJSON|OPENROWSET|OPENQUERY|XP_\w+|SP_\w+)\b", re.IGNORECASE)
_SQL_VERBS = r"SELECT|INSERT|UPDATE|DELETE|MERGE|EXEC|EXECUTE|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE|BACKUP|RESTORE|DBCC"
# SQL left in the changed lines once the validated literals are removed: a SQL string that is not passed in a visible
# call, or a bare SQL line (the rest of a multiline string whose opening is not in the diff).
_LOOSE_SQL = (
    re.compile(rf"""[rRuUbBfF]{{0,2}}[\"\']{{1,3}}\s*(?:{_SQL_VERBS}|WITH\s+\w+\s+AS\s*\()\b""", re.IGNORECASE),
    re.compile(rf"(?im)^\s*(?:{_SQL_VERBS})\s+\S"),
)


def _read_literal(text: str, pos: int) -> tuple[str, int, int] | None:
    """The plain string literal that starts at `pos` (after whitespace) and the call's argument ends right after:
    `(content, start, end)`, else None. None for an f-string, a variable, concatenation, `%`, `.format`, adjacent
    literals and a literal that is not closed in the changed text."""
    m = _STR_OPEN.match(text, pos)
    if m is None:
        return None
    delim, i = m.group(1), m.end()
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text.startswith(delim, i):
            end = i + len(delim)
            rest = text[end:].lstrip()
            if rest[:1] not in (")", ","):
                return None
            return text[m.end():i], pos, end
        if len(delim) == 1 and text[i] == "\n":
            return None
        i += 1
    return None


def _call_tail(text: str, pos: int) -> int | None:
    """From the end of a call's string literal: the index just after the call's closing `)`, or None. Only `)`, or
    `, <bind literal>` then `)`, is allowed: a bind literal is one balanced `(...)`, `{...}` or `[...]`."""
    n = len(text)
    i = pos
    while i < n and text[i].isspace():
        i += 1
    if i < n and text[i] == ")":
        return i + 1
    if i >= n or text[i] != ",":
        return None
    i += 1
    while i < n and text[i].isspace():
        i += 1
    if i < n and text[i] in "([{":
        pairs, stack = {"(": ")", "[": "]", "{": "}"}, []
        while i < n:
            ch = text[i]
            if ch in pairs:
                stack.append(pairs[ch])
            elif ch in ")]}":
                if not stack or stack.pop() != ch:
                    return None
                if not stack:
                    i += 1
                    break
            i += 1
        else:
            return None
        while i < n and text[i].isspace():
            i += 1
        if i < n and text[i] == ",":
            i += 1
            while i < n and text[i].isspace():
                i += 1
    if i < n and text[i] == ")":
        return i + 1
    return None


def _tail_ok(text: str, i: int) -> bool:
    """What follows a call's closing `)`: end of line, another `)` or `,`, a `#` comment, or a method chain such as `.fetchall()`.
    Anything else (`if`, `or`, `+`) can pick another statement, so the call is not LOW."""
    n = len(text)
    while i < n and text[i] in " \t":
        i += 1
    return i >= n or text[i] in "\r\n),.#"


def _is_plain_read(content: str) -> bool:
    """True for one SELECT statement: no INTO, no write or DDL word, and `;` only at the very end."""
    body = content.strip()
    if not re.match(r"\(*\s*SELECT\b", body, re.IGNORECASE):
        return False
    if ";" in body.rstrip().rstrip(";"):
        return False
    return not _NOT_A_READ.search(body)


def _file_is_low(labels: set[str], lines: list[str]) -> bool:
    """True when every DB hit in a file is a read-only SELECT literal passed directly in a visible call.
    Each call is judged on its own literal, so a SELECT in one call never vouches for another."""
    if not set(labels) <= DB_LOW_LABELS:
        return False
    text = "\n".join(lines)  # comments are NOT stripped: a `#` inside SQL text is plain text, never a cut
    spans: list[tuple[int, int]] = []
    seen_call = False
    consumed = 0
    for m in _CALL.finditer(text):
        if m.start() < consumed:
            continue  # the nested text( of an execute(text("...")) call, already judged with its outer call
        nested = _TEXT_NEXT.match(text, m.end()) if "execute" in m.group(0).lower() else None
        lit = _read_literal(text, nested.end() if nested else m.end())
        if lit is None or not _is_plain_read(lit[0]):
            return False
        end = _call_tail(text, lit[2])  # the whole argument list: this one literal, plus a bind literal at most
        if end is not None and nested:
            end = _call_tail(text, end)  # execute(text(<literal>) ...): the outer call's list too
        if end is None or not _tail_ok(text, end):
            return False
        consumed = end
        spans.append((lit[1], lit[2]))
        seen_call = True
    if not seen_call:
        return False
    rest = text
    for a, b in reversed(spans):
        rest = rest[:a] + " " + rest[b:]
    return not any(rx.search(rest) for rx in _LOOSE_SQL)


def db_risk(hits: list[DbHit], changed: dict[str, list[str]]) -> str | None:
    """`"low"`, `"high"`, or None when the diff has no non-test DB hit. LOW only when every non-test file is a
    read-only SELECT literal in a visible call; anything else is HIGH."""
    real = [h for h in hits if not h.is_test]
    if not real:
        return None
    for path in sorted({h.path for h in real}):
        if not _file_is_low({h.label for h in real if h.path == path}, changed.get(path, [])):
            return "high"
    return "low"


def db_tier_bump(repo_root: Path) -> bool:
    """`[db_review] tier_bump` (default true). False keeps the diff's normal tier for HIGH DB code too; the DB
    reviews stay required either way."""
    try:
        raw = _load_repo_config(repo_root, "db_review").get("tier_bump", True)
    except Exception:  # noqa: BLE001 - config is optional; the default stands
        return True
    if isinstance(raw, bool):
        return raw
    sys.stderr.write(f"[caddis-gate] note: [db_review] tier_bump '{raw}' is not true or false; using true\n")
    return True


DB_REVIEWER_DEFAULT = "sql-expert"
DB_ETL_REVIEWER_DEFAULT: str | None = None  # off by default: sql-expert alone reviews every DB hit (owner, 17 Nov)
DB_ETL_NEEDLES = frozenset({
    "etl", "elt", "pipeline", "pipelines", "ingest", "ingestion", "loader", "loaders", "load", "extract",
    "transform", "refresh", "sync", "dag", "dags", "warehouse"})
DB_ETL_LABELS = frozenset({"bulk-insert", "executemany", "openjson"})
_AGENT_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _diff_text(rng: str | None = None, repo_root: Path = Path(".")) -> str:
    """`git diff -U0 --no-renames` text for an explicit range or the working tree.

    `--no-renames` lists a moved file as a delete plus an add, so DB code moved into tests/ still shows as removed
    lines at its old path. A failed `git diff` raises RuntimeError: the caller must not read it as an empty diff."""
    args = ["git", "-C", str(repo_root), "-c", "core.quotepath=false", "diff", "--no-color", "--no-ext-diff",
            "--no-renames", "--src-prefix=a/", "--dst-prefix=b/", "-U0"]
    if rng:
        args.append(rng)
    res = subprocess.run(args, capture_output=True, timeout=30)
    if res.returncode != 0:
        reason = res.stderr.decode("utf-8", errors="replace").strip().splitlines()
        raise RuntimeError(f"git diff -U0 exited {res.returncode}: {reason[0] if reason else 'no message'}")
    return res.stdout.decode("utf-8", errors="replace")


def _load_repo_config(repo_root: Path, section: str) -> dict:
    try:
        import claudster_config
    except ModuleNotFoundError as exc:
        if exc.name != "claudster_config":
            raise
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-harness" / "scripts"))
        import claudster_config
    return claudster_config.load_config(repo_root, section)


def db_review_config(repo_root: Path) -> tuple[str, str | None]:
    """(reviewer, etl_reviewer) from `[db_review]` in `.caddis/config.toml`.

    A value that is not an agent name gives the default and one stderr note. `etl_reviewer` is off (None) by
    default and when set to "none"; set it to an agent name to add a second reviewer on load/ETL files."""
    try:
        cfg = _load_repo_config(repo_root, "db_review")
    except Exception:  # noqa: BLE001 - config is optional; the defaults stand
        cfg = {}

    def pick(key: str, default: str | None, allow_none: bool) -> str | None:
        raw = cfg.get(key)
        if not isinstance(raw, str) or not raw.strip():
            return default
        value = raw.strip()
        if allow_none and value.lower() == "none":
            return None
        if _AGENT_NAME.match(value):
            return value
        sys.stderr.write(f"[caddis-gate] note: [db_review] {key} '{value}' is not an agent name; using {default or 'none'}\n")
        return default

    reviewer = pick("reviewer", DB_REVIEWER_DEFAULT, False) or DB_REVIEWER_DEFAULT
    return reviewer, pick("etl_reviewer", DB_ETL_REVIEWER_DEFAULT, True)


def is_etl_file(path: str, labels: set[str]) -> bool:
    """True for a load/ETL file: an ETL label fired on it, or a folder name or the file stem names an ETL word."""
    if set(labels) & DB_ETL_LABELS:
        return True
    segs = path.replace("\\", "/").lower().split("/")
    stem = segs[-1].rsplit(".", 1)[0]
    words: set[str] = set()
    for part in [*segs[:-1], stem]:
        words.update(w for w in re.split(r"[-_]", part) if w)
    return bool(words & DB_ETL_NEEDLES)


def db_reviewers(hits: list[DbHit], reviewer: str, etl_reviewer: str | None, risk: str = "high") -> list[str]:
    """The DB reviewers a diff needs: none for tests-only hits; `reviewer`, plus `etl_reviewer` on a load/ETL file.
    A LOW diff gets `reviewer` alone."""
    real = [h for h in hits if not h.is_test]
    if not real:
        return []
    names = [reviewer]
    if risk != "low" and etl_reviewer and etl_reviewer != reviewer:
        for path in sorted({h.path for h in real}):
            if is_etl_file(path, {h.label for h in real if h.path == path}):
                names.append(etl_reviewer)
                break
    return names


def db_line(hits: list[DbHit], reviewers: list[str], risk: str = "high") -> str:
    """The `DB:` line of `review-tier`: reviewers, the risk (`high`, or `low, diff only`) and the triggers."""
    if not hits:
        return "DB: none"
    real = [h for h in hits if not h.is_test]
    if not real:
        return f"DB: none - tests-only diff ({len({h.path for h in hits})} test file(s) with DB code)"
    shown = [f"{h.label} ({h.path})" for h in real[:6]]
    extra = f", ... (+{len(real) - 6} more)" if len(real) > 6 else ""
    tag = "low, diff only" if risk == "low" else "high"
    return f"DB: {', '.join(reviewers)} ({tag}) - triggers: {', '.join(shown)}{extra}"


def merge_area(area: list[str], db: list[str]) -> list[str]:
    """Area reviewer order: `security-analyst`, other area names, DB reviewers not yet named, `ui-design-reviewer`."""
    first = [n for n in area if n == "security-analyst"]
    last = [n for n in area if n == "ui-design-reviewer"]
    middle = [n for n in area if n not in ("security-analyst", "ui-design-reviewer")]
    merged = first + middle
    merged += [n for n in db if n not in merged and n not in last]
    return merged + last


def gate_review_trigger(repo_root: Path, rev_range: str | None = None) -> int:
    """EXIT_NOTE when the diff warrants cross-review, EXIT_OK when it does not.

    NOTE, never BLOCKED. This decides when to ASK for a second opinion; it is not itself a verdict
    and must not stop a ship. The honest limit, from the item that raised it: a trigger does not
    make the review good, it makes it happen — and on the measured evidence that was the binding
    constraint, with a configured, capable tool idle through sixteen chances to use it.
    """
    paths, changed = _changed(repo_root, rev_range)
    if not paths:
        print("[gate] review-trigger: empty diff — nothing to review")
        return EXIT_OK
    fired = review_triggers(paths, changed)
    if not fired:
        print(f"[gate] review-trigger: {len(paths)} file(s), {changed} line(s) — no trigger")
        return EXIT_OK
    print(f"[gate] review-trigger: RUN CROSS-REVIEW — {len(paths)} file(s), {changed} line(s)")
    for label, why, hits in fired:
        shown = ", ".join(hits[:4]) + (", ..." if len(hits) > 4 else "")
        print(f"    {label}: {why}" + (f"{chr(10)}      {shown}" if hits else ""))
    print("    /caddis:cross-review   (or: python .github/tools/oss_review.py)")
    return EXIT_NOTE


TIER_REVIEWERS = {
    "0": 0,
    "1-small": 0,
    "1": 1,
    "2": 1,
}


def is_test_file(path: str) -> bool:
    norm = path.replace("\\", "/").lower()
    if norm.startswith("./"):
        norm = norm[2:]
    segs = norm.split("/")
    filename = segs[-1]
    if any(s in ("tests", "test") for s in segs[:-1]):
        return True
    if filename.startswith("test_") and filename.endswith(".py"):
        return True
    if filename.endswith("_test.py"):
        return True
    for ext in (".test.ts", ".test.tsx", ".test.js", ".test.jsx"):
        if filename.endswith(ext):
            return True
    return False


_STEERING_FILENAMES = {"conftest.py", "pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini"}


def is_review_steering_file(path: str) -> bool:
    """True for config that steers reviews, merges or tests: never tier 0, and never a 0-reviewer "1-small".

    `.caddis/*.toml` (review/implement routing, merge-chain checks), any `conftest.py`, the pytest and
    packaging config, and `.github/workflows/**`. A fix diff that changes these can turn a gate off, so it is reviewed.
    """
    norm = path.replace("\\", "/").lower().removeprefix("./")
    if norm.startswith(".caddis/") and norm.endswith(".toml"):
        return True
    if norm.startswith(".github/workflows/"):
        return True
    return norm.rsplit("/", 1)[-1] in _STEERING_FILENAMES


def is_tier0_file(path: str) -> bool:
    if is_review_steering_file(path):
        return False
    norm = path.replace("\\", "/").lower()
    if norm.startswith("./"):
        norm = norm[2:]
    if norm.startswith("docs/") or norm.startswith(".caddis/"):
        return True
    if "/" not in norm:
        stem = norm.rsplit(".", 1)[0]
        ext = norm.rsplit(".", 1)[1] if "." in norm else ""
        if ext == "md" and (stem.startswith("readme") or stem.startswith("changelog")):
            return True
    if is_test_file(norm):
        return True
    return False


BINARY_LINES = 41  # a binary change has no line count: count it above the 40-line small limit, never "1-small"


def _rename_paths(path: str) -> list[str]:
    """Both sides of a `--numstat` rename path (`old => new` or `pre/{old => new}/post`); [path] when not a rename."""
    if " => " not in path:
        return [path]
    if "{" in path and "}" in path:
        prefix, rest = path.split("{", 1)
        inner, suffix = rest.split("}", 1)
        old, new = inner.split(" => ", 1)
        return [f"{prefix}{side}{suffix}".replace("//", "/").lstrip("/") for side in (old, new)]
    old, new = path.split(" => ", 1)
    return [old, new]


def _numstat(rng: str | None = None, repo_root: Path = Path(".")) -> list[tuple[str, int]]:
    """(path, changed-lines) per file for an explicit range or the working tree.

    A rename lists BOTH the old and the new path, so moving code into `docs/` or `tests/` is not tier 0. A binary
    change counts `BINARY_LINES`. A failed `git diff` raises RuntimeError: the caller must not read it as an empty
    diff (tier 0)."""
    args = ["git", "-C", str(repo_root), "diff", "--numstat"]
    if rng:
        args.append(rng)
    res = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if res.returncode != 0:
        reason = (res.stderr or "").strip().splitlines()
        raise RuntimeError(f"git diff --numstat exited {res.returncode}: {reason[0] if reason else 'no message'}")
    return _parse_numstat(res.stdout)


def _parse_numstat(stdout: str) -> list[tuple[str, int]]:
    """(path, changed-lines) per file from `git diff --numstat` output; see `_numstat`."""
    files: list[tuple[str, int]] = []
    for row in stdout.splitlines():
        parts = row.split("\t")
        if len(parts) != 3:
            continue
        add, dele, path = parts
        if add == "-" or dele == "-":
            line_count = BINARY_LINES
        else:
            line_count = (int(add) if add.isdigit() else 0) + (int(dele) if dele.isdigit() else 0)
        paths = _rename_paths(path.strip())
        if len(paths) == 2:
            # A rename moves code out of its old path; a pure rename has 0 changed lines, so without this a move
            # into tests/ would read as a small, covered change (tier 1-small, no review). The old path counts as large.
            files.append((paths[0], max(line_count, BINARY_LINES)))
            files.append((paths[1], max(line_count, BINARY_LINES)))  # tests/x.py -> x.py moves test code into production
        else:
            for p in paths:
                files.append((p, line_count))
    return files


def review_tier(files: list[tuple[str, int]], plan_risk: str = "normal") -> str:
    """Return '0', '1-small', '1' or '2' by the model routing review budget."""
    non_tier0 = [(p, lines) for p, lines in files if not is_tier0_file(p)]
    if not non_tier0:
        return "0"
    if str(plan_risk).strip().lower() == "high":
        return "2"
    non_tier0_paths = [p for p, _ in non_tier0]
    non_tier0_lines = sum(lines for _, lines in non_tier0)
    if review_triggers(non_tier0_paths, non_tier0_lines):
        return "2"
    if any(is_review_steering_file(p) for p in non_tier0_paths):
        return "1"
    has_test = any(is_test_file(p) for p, _ in files)
    if non_tier0_lines <= 40 and has_test:
        return "1-small"
    return "1"


def area_reviewers(files: list[tuple[str, int]], phase_type: str | None = None) -> list[str]:
    """Area reviewers for a diff: `security-analyst` when the auth trigger fires on a non-tier-0 path,
    `ui-design-reviewer` when the plan phase's Type is `ui`. Never both for the wrong reason: docs and tests are tier 0."""
    non_tier0 = [(p, lines) for p, lines in files if not is_tier0_file(p)]
    names = []
    fired = review_triggers([p for p, _ in non_tier0], 0)
    if any(label == "auth" for label, _, _ in fired):
        names.append("security-analyst")
    if (phase_type or "").strip().lower() == "ui":
        names.append("ui-design-reviewer")
    return names


def gate_review_tier(
    repo_root: Path,
    rev_range: str | None = None,
    plan: Path | str | None = None,
    phase: int | str | None = None,
) -> int:
    """Print the tier, reviewer count and area reviewers for the diff and plan phase."""
    risk = "normal"
    ptype = None
    if plan and phase is None:
        risk = "high"  # fail closed: a plan without a phase cannot give a risk
    elif plan and phase is not None:
        try:
            try:
                import caddis_review
            except ModuleNotFoundError:
                sys.path.insert(0, str(Path(__file__).resolve().parent))
                import caddis_review
            risk = caddis_review.phase_risk(Path(plan), phase)
            ptype = caddis_review.phase_type(Path(plan), phase)
        except Exception:
            # Fail closed: a plan risk we cannot read counts as high (tier 2).
            risk = "high"
    try:
        files = _numstat(rev_range, repo_root)
    except Exception as exc:  # noqa: BLE001 - a diff we cannot read is reviewed in full, never skipped
        sys.stderr.write(f"caddis-gate: review-tier could not read the diff ({exc}); counting it as tier 2\n")
        print("TIER: 2")
        print("REVIEWERS: 1")
        print("AREA: none")
        print("DB: unknown - diff unreadable")
        return EXIT_OK
    tier = review_tier(files, plan_risk=risk)
    area = area_reviewers(files, ptype)
    try:
        # No range: the working tree against HEAD (staged and unstaged), the same read as `db-review`.
        changed = parse_diff_lines(_diff_text(rev_range or "HEAD", repo_root))
        hits = db_triggers([p for p, _ in files], changed)
    except Exception as exc:  # noqa: BLE001 - content we cannot read is reported, never read as "no DB code"
        sys.stderr.write(f"caddis-gate: review-tier could not read the diff content ({exc})\n")
        hits, db_names, db_text = [], [], "DB: unknown - diff unreadable"
        tier = "2"  # fail closed, like an unreadable numstat: a diff we cannot read is reviewed in full
    else:
        risk = db_risk(hits, changed) or "high"
        db_names = db_reviewers(hits, *db_review_config(repo_root), risk=risk)
        db_text = db_line(hits, db_names, risk)
        if db_names and risk == "high" and db_tier_bump(repo_root):
            tier = "2"  # high-risk DB code is a trigger on its own: a wrong number or a lost index is born here
    reviewers = TIER_REVIEWERS.get(tier, 1)
    print(f"TIER: {tier}")
    print(f"REVIEWERS: {reviewers}")
    print(f"AREA: {', '.join(merge_area(area, db_names)) or 'none'}")
    print(db_text)
    return EXIT_OK


def _caddis_markdown(root: Path) -> list[Path]:
    """The .caddis/**/*.md files a clean checkout of `root` would hold: tracked or untracked, never gitignored.

    CI checks a clean checkout, so a local ignored file (a relay under .caddis/relay/) must not fail the gate here.
    Outside a git repo (or with no git) this falls back to walking the folder."""
    try:
        r = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", ".caddis"],
            cwd=str(root), capture_output=True, stdin=subprocess.DEVNULL, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        r = None
    if r is None or r.returncode != 0:
        return sorted((root / ".caddis").rglob("*.md"))
    names = {n for n in r.stdout.decode("utf-8", errors="surrogateescape").split("\0") if n.endswith(".md")}
    return sorted(p for p in (root / n for n in names) if p.is_file())  # a tracked file deleted locally is skipped


def gate_docs_check(root: Path) -> int:
    """Report every typed .caddis Markdown document with an invalid header. Gitignored files are not judged."""
    failures = 0
    for path in _caddis_markdown(root):
        relative = path.relative_to(root).as_posix()
        if not caddis_frontmatter.doc_in_scope(relative, root):
            continue
        error = caddis_frontmatter.validate(
            path.read_text(encoding="utf-8"), caddis_frontmatter.ALLOWED_TYPES
        )
        if error:
            print(f"{relative}: {error}")
            failures += 1
    return EXIT_BLOCKED if failures else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="caddis machine gates")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("lane-check",):
        s = sub.add_parser(name)
        s.add_argument("--plan", required=True)
        s.add_argument("--phase", type=int, required=True)
    t = sub.add_parser("tracker-vs-git")
    t.add_argument("--plan", required=True)
    mc = sub.add_parser("measured-check")
    mc.add_argument("--plan", required=True)
    dp = sub.add_parser("db-plan-check")
    dp.add_argument("--plan", required=True)
    dr = sub.add_parser("db-review")
    dr.add_argument("--repo-root", default=".")
    dr.add_argument("--range", dest="rev_range", default=None,
                    help="revision range, e.g. origin/main...HEAD (default: the working tree against HEAD)")
    dr.add_argument("--plan", default=None, help="path to plan markdown (needs --phase)")
    dr.add_argument("--phase", default=None, help="phase number, e.g. 3 or 3b")
    dr.add_argument("--stage", default="diff", help="diff (default) or design")
    dr.add_argument("--evidence", default=None, help="evidence file (default: by plan, or by branch)")
    dr.add_argument("--print-files", action="store_true", help="print the DB files and blob ids to record")
    dr.add_argument("--print-hash", action="store_true", help="print the phase text hash to record")
    dr.add_argument("--print-brief", action="store_true", help="print the SQL Server checklist for a reviewer brief")
    pl = sub.add_parser("parking-lot")
    pl.add_argument("--repo-root", default=".")
    rt = sub.add_parser("review-trigger")
    rt.add_argument("--repo-root", default=".")
    rt.add_argument("--range", dest="rev_range", default=None,
                    help="revision range, e.g. origin/main...HEAD (default: the working tree)")
    rw = sub.add_parser("review-tier")
    rw.add_argument("--repo-root", default=".")
    rw.add_argument("--range", dest="rev_range", default=None,
                    help="revision range, e.g. origin/main...HEAD (default: the working tree)")
    rw.add_argument("--plan", default=None, help="path to plan markdown")
    rw.add_argument("--phase", default=None, help="phase number or heading")
    vd = sub.add_parser("vendor-drift")
    vd.add_argument("--repo-root", default=".")
    hc = sub.add_parser("handover-check")
    hc.add_argument("--doc", required=True)
    hc.add_argument("--repo-root", default=".")
    hc.add_argument("--max-chars", type=int, default=None,
                    help="block a doc longer than this (relays: 4000); default: no cap")
    dc = sub.add_parser("docs-check")
    dc.add_argument("--root", default=".")
    a = ap.parse_args(argv)

    plan = Path(getattr(a, "plan", "") or ".")
    if a.cmd == "docs-check":
        try:
            return gate_docs_check(Path(a.root).resolve())
        except Exception as exc:
            sys.stderr.write(f"[caddis-gate] docs-check cannot evaluate: {type(exc).__name__}: {exc}\n")
            return EXIT_BLOCKED  # CI must not pass without completing the scan.
    try:
        if a.cmd == "lane-check":
            return gate_lane(plan, a.phase)
        if a.cmd == "measured-check":
            return gate_measured(plan)
        if a.cmd == "db-plan-check":
            return gate_db_plan(plan)
        if a.cmd == "db-review":
            return gate_db_review(
                Path(a.repo_root).resolve(), a.rev_range, Path(a.plan) if a.plan else None, a.phase, a.stage,
                Path(a.evidence) if a.evidence else None, a.print_files, a.print_hash, a.print_brief)
        if a.cmd == "parking-lot":
            return gate_parking_lot(Path(a.repo_root).resolve())
        if a.cmd == "review-trigger":
            return gate_review_trigger(Path(a.repo_root).resolve(), a.rev_range)
        if a.cmd == "review-tier":
            return gate_review_tier(
                Path(a.repo_root).resolve(),
                a.rev_range,
                getattr(a, "plan", None),
                getattr(a, "phase", None),
            )
        if a.cmd == "vendor-drift":
            return gate_vendor_drift(Path(a.repo_root).resolve())
        if a.cmd == "handover-check":
            return gate_handover_check(Path(a.doc), Path(a.repo_root).resolve(), a.max_chars)
        return gate_tracker(plan)
    except Exception as exc:  # pragma: no cover — a gate must never crash the caller
        return _degrade(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
