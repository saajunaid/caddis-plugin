"""Growth control: size budgets and archive rules for handoff-grown files."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
from typing import NamedTuple

try:
    import caddis_exit
except ModuleNotFoundError as exc:
    if exc.name != "caddis_exit":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-harness" / "scripts"))
    import caddis_exit


class Budget(NamedTuple):
    glob: str
    unit: str
    limit: int
    rule: str


class Over(NamedTuple):
    path: str
    unit: str
    value: int
    limit: int
    rule: str


BUDGETS: tuple[Budget, ...] = (
    Budget(
        ".caddis/relay/*.md",
        "chars",
        4000,
        "rewrite: current state only, git keeps history",
    ),
    Budget(
        ".caddis/relay/*.tasks.md",
        "table rows",
        40,
        "done rows are never written (Phase 1)",
    ),
    Budget(
        ".caddis/relay.md",
        "lines",
        60,
        "rendered by render-index; drop relays with status closed",
    ),
    Budget(
        "DECISIONS.md, .caddis/DECISIONS.md, .caddis/decisions/DECISIONS.md",  # the last is the fleet's real path
        "History table rows",
        30,
        "move older rows to DECISIONS-archive.md beside it",
    ),
    Budget(
        ".caddis/usage-log.jsonl",
        "bytes",
        5000000,
        "rotate to usage-log-<YYYYMM>.jsonl",
    ),
    Budget(
        ".caddis/session-state/*.md",
        "files",
        8,
        "session_state.py prune (not in a shared checkout)",
    ),
    Budget(
        ".caddis/kb/*.md",
        "lines per file",
        300,
        "split, or move closed parts to .caddis/kb/done/",
    ),
)


class _ParsedTable(NamedTuple):
    heading: str | None
    columns: list[str]
    data_rows: list[list[str]]


def _split_cells(line: str) -> list[str]:
    s = line.strip()
    if not s:
        return []
    parts = re.split(r"(?<!\\)\|", s)
    if parts and parts[0] == "":
        parts.pop(0)
    if parts and parts[-1] == "":
        parts.pop(-1)
    return [p.strip() for p in parts]


def _is_separator(line: str) -> bool:
    cells = _split_cells(line)
    if not cells:
        return False
    for cell in cells:
        c = cell.strip()
        if not c or any(ch not in "-: " for ch in c) or "-" not in c:
            return False
    return True


def _parse_tables(text: str) -> tuple[list[_ParsedTable], int]:
    lines = text.splitlines()
    tables: list[_ParsedTable] = []
    loose_rows = 0
    n = len(lines)
    i = 0
    while i < n:
        if lines[i].lstrip().startswith("|"):
            run_start = i
            while i < n and lines[i].lstrip().startswith("|"):
                i += 1
            run = lines[run_start:i]
            if len(run) >= 2 and _is_separator(run[1]):
                heading: str | None = None
                for k in range(run_start - 1, -1, -1):
                    s = lines[k].strip()
                    if s.startswith("#"):
                        heading = s.lstrip("#").strip()
                        break
                columns = _split_cells(run[0])
                data_rows = [_split_cells(r) for r in run[2:] if not _is_separator(r)]
                tables.append(_ParsedTable(heading=heading, columns=columns, data_rows=data_rows))
            else:
                for r in run:
                    if not _is_separator(r) and not r.lstrip().startswith(("| Old #", "| # |")):
                        loose_rows += 1
        else:
            i += 1
    return tables, loose_rows


def _count_table_rows(text: str) -> int:
    tables, loose_rows = _parse_tables(text)
    return sum(len(t.data_rows) for t in tables) + loose_rows


def _count_history_rows(text: str) -> int:
    tables, loose_rows = _parse_tables(text)
    history_tables = [t for t in tables if t.heading and "history" in t.heading.lower()]
    if history_tables:
        return sum(len(t.data_rows) for t in history_tables)
    return sum(len(t.data_rows) for t in tables) + loose_rows


def _measure_file(path: Path, unit: str) -> int:
    if unit == "bytes":
        return path.stat().st_size
    text = path.read_text(encoding="utf-8", errors="ignore")
    if unit == "chars":
        return len(text)
    if unit == "table rows":
        return _count_table_rows(text)
    if unit in ("lines", "lines per file"):
        return len(text.splitlines())
    if unit == "History table rows":
        return _count_history_rows(text)
    raise ValueError(f"unknown budget unit: {unit}")


def check(root: Path) -> list[Over]:
    """Return every file under ``root`` that exceeds its configured size budget."""
    root = Path(root)
    overs: list[Over] = []

    for budget in BUDGETS:
        if budget.unit == "files":
            files = [p for p in sorted(root.glob(budget.glob)) if p.is_file()]
            value = len(files)
            if value > budget.limit:
                overs.append(Over(budget.glob, budget.unit, value, budget.limit, budget.rule))
            continue

        patterns = [g.strip() for g in budget.glob.split(",")]
        for pattern in patterns:
            if "*" in pattern:
                candidates = [p for p in sorted(root.glob(pattern)) if p.is_file()]
            else:
                candidate = root / pattern
                candidates = [candidate] if candidate.is_file() else []

            for p in candidates:
                if pattern == ".caddis/relay/*.md" and p.name.endswith(".tasks.md"):
                    continue
                rel = p.relative_to(root).as_posix()
                value = _measure_file(p, budget.unit)
                if value > budget.limit:
                    overs.append(Over(rel, budget.unit, value, budget.limit, budget.rule))

    return overs


def main(argv: list[str] | None = None) -> int:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        prog="caddis_budget.py",
        description="Check handoff-grown files against their size budgets.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_check = sub.add_parser("check", help="Check files under --root against BUDGETS.")
    p_check.add_argument("--root", type=Path, default=Path("."), help="Repository root.")
    p_check.add_argument(
        "--report",
        action="store_true",
        help="Report files over budget but always exit 0.",
    )

    args = parser.parse_args(argv)
    try:
        overs = check(args.root)
    except OSError as exc:  # a locked or unreadable file (Windows): --report still never fails the caller
        print(f"[BUDGET] could not read every file: {exc}")
        return caddis_exit.CLEAN if args.report else caddis_exit.NOT_RUN
    if not overs:
        print("[BUDGET] all within budget")
        return caddis_exit.CLEAN

    for over in overs:
        print(f"OVER {over.path}: {over.value} {over.unit} > {over.limit}; fix: {over.rule}")
    if args.report:
        return caddis_exit.CLEAN
    return caddis_exit.BLOCKED


if __name__ == "__main__":
    raise SystemExit(main())
