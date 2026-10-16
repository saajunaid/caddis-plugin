"""Set open-work table cells by row id and column name; archive done rows."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
import tempfile

try:
    import caddis_exit
except ModuleNotFoundError as exc:
    if exc.name != "caddis_exit":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-harness" / "scripts"))
    import caddis_exit


@dataclass
class Table:
    heading: str | None
    header_line_idx: int
    separator_line_idx: int
    data_line_indices: list[int]
    columns: list[str]
    id_col_idx: int | None


def split_cells(line: str) -> list[str]:
    """Return stripped cells of one markdown table line, splitting on unescaped pipes."""
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
    cells = split_cells(line)
    if not cells:
        return False
    for cell in cells:
        c = cell.strip()
        if not c:
            return False
        if any(ch not in "-: " for ch in c):
            return False
        if "-" not in c:
            return False
    return True


def find_tables(lines: list[str]) -> list[Table]:
    tables: list[Table] = []
    n = len(lines)
    i = 0
    while i < n:
        if lines[i].startswith("|"):
            run_start = i
            while i < n and lines[i].startswith("|"):
                i += 1
            run_end = i
            run_lines = lines[run_start:run_end]
            if len(run_lines) >= 2 and _is_separator(run_lines[1]):
                header_idx = run_start
                sep_idx = run_start + 1
                data_indices = list(range(run_start + 2, run_end))
                columns = split_cells(lines[header_idx])

                heading = None
                for k in range(run_start - 1, -1, -1):
                    s = lines[k].strip()
                    if s.startswith("#"):
                        heading = s.lstrip("#").strip()
                        break

                id_col_idx = None
                for col_idx, col in enumerate(columns):
                    if col.lower() == "id":
                        id_col_idx = col_idx
                        break

                tables.append(
                    Table(
                        heading=heading,
                        header_line_idx=header_idx,
                        separator_line_idx=sep_idx,
                        data_line_indices=data_indices,
                        columns=columns,
                        id_col_idx=id_col_idx,
                    )
                )
        else:
            i += 1
    return tables


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    target = target.resolve()
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False
        ) as f:
            temp_path = Path(f.name)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, target)
        temp_path = None
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def _norm_id(cell: str) -> str:
    return cell.replace("**", "").replace("__", "").replace("`", "").strip()


def handle_set(args: argparse.Namespace) -> int:
    if not args.id and not args.from_file:
        print("caddis-rows: either --id or --from is required", file=sys.stderr)
        return caddis_exit.ERROR
    if args.id and not args.col:
        print("caddis-rows: --id requires at least one --col", file=sys.stderr)
        return caddis_exit.ERROR
    if args.id and args.from_file:
        print("caddis-rows: cannot specify both --id and --from", file=sys.stderr)
        return caddis_exit.ERROR

    change_specs: list[dict] = []
    if args.id:
        cols_dict: dict[str, str] = {}
        for c in args.col:
            if "=" not in c:
                print(f"caddis-rows: invalid --col format '{c}', expected NAME=VALUE", file=sys.stderr)
                return caddis_exit.ERROR
            name, val = c.split("=", 1)
            name = name.strip()
            cols_dict[name] = val
        change_specs.append({"id": args.id, "table": args.table, "cols": cols_dict})
    else:
        from_path = Path(args.from_file)
        if from_path.is_file():
            try:
                content = from_path.read_text(encoding="utf-8")
                loaded = json.loads(content)
            except (OSError, json.JSONDecodeError) as exc:
                print(f"caddis-rows: failed to read --from file: {exc}", file=sys.stderr)
                return caddis_exit.ERROR
        else:
            try:
                loaded = json.loads(args.from_file)
            except json.JSONDecodeError as exc:
                print(f"caddis-rows: invalid JSON in --from: {exc}", file=sys.stderr)
                return caddis_exit.ERROR

        if not isinstance(loaded, list):
            print("caddis-rows: --from JSON must be a list of change objects", file=sys.stderr)
            return caddis_exit.ERROR

        for item in loaded:
            if not isinstance(item, dict) or "id" not in item or "cols" not in item or not isinstance(item["cols"], dict):
                print(f"caddis-rows: invalid item in --from: {item}", file=sys.stderr)
                return caddis_exit.ERROR
            tbl = item.get("table") or args.table
            change_specs.append({"id": item["id"], "table": tbl, "cols": dict(item["cols"])})

    for spec in change_specs:
        for val in spec["cols"].values():
            val_str = str(val)
            if "\n" in val_str or "\r" in val_str:
                print("caddis-rows: value contains newline characters", file=sys.stderr)
                return caddis_exit.ERROR

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"caddis-rows: file not found: {file_path}", file=sys.stderr)
        return caddis_exit.BLOCKED

    raw = file_path.read_bytes()
    text = raw.decode("utf-8")
    crlf = "\r\n" in text
    newline = "\r\n" if crlf else "\n"
    ends_with_newline = text.endswith(newline)
    if ends_with_newline:
        content = text[:-len(newline)]
    else:
        content = text
    lines = content.split(newline) if content else []

    tables = find_tables(lines)

    # Validate all changes
    validated_changes: list[dict] = []
    for spec in change_specs:
        item_id = spec["id"]
        table_filter = spec.get("table")
        cols = spec["cols"]

        candidate_tables = [t for t in tables if t.id_col_idx is not None]
        if not candidate_tables:
            print(
                f"caddis-rows: {file_path}: no table has a column named ID; an open-work table needs | ID | ... | Status |",
                file=sys.stderr,
            )
            return caddis_exit.BLOCKED
        if table_filter is not None:
            candidate_tables = [t for t in candidate_tables if t.heading == table_filter]

        candidates: list[tuple[Table, int, list[str]]] = []
        for t in candidate_tables:
            for line_idx in t.data_line_indices:
                cells = split_cells(lines[line_idx])
                if len(cells) > t.id_col_idx and _norm_id(cells[t.id_col_idx]) == _norm_id(item_id):
                    candidates.append((t, line_idx, cells))

        if len(candidates) == 0:
            print(f"caddis-rows: row id '{item_id}' not found", file=sys.stderr)
            return caddis_exit.BLOCKED

        if len(candidates) > 1:
            headings = [c[0].heading for c in candidates]
            print(f"caddis-rows: row id '{item_id}' found in multiple tables: {headings}", file=sys.stderr)
            return caddis_exit.BLOCKED

        cand_table, cand_line_idx, cand_cells = candidates[0]

        col_lookup = {col.lower(): idx for idx, col in enumerate(cand_table.columns)}
        for col_name in cols:
            if col_name.lower() not in col_lookup:
                print(f"caddis-rows: column '{col_name}' not found in table '{cand_table.heading}'", file=sys.stderr)
                return caddis_exit.BLOCKED

        validated_changes.append({
            "id": item_id,
            "table": cand_table,
            "line_idx": cand_line_idx,
            "cols": cols,
        })

    # Apply changes
    row_cells: dict[int, list[str]] = {}
    original_cells: dict[int, list[str]] = {}
    applied_notifications: list[str] = []

    for v in validated_changes:
        cand_table: Table = v["table"]
        line_idx: int = v["line_idx"]
        cols: dict[str, str] = v["cols"]
        item_id: str = v["id"]

        if line_idx not in row_cells:
            cells = split_cells(lines[line_idx])
            if len(cells) < len(cand_table.columns):
                cells.extend([""] * (len(cand_table.columns) - len(cells)))
            row_cells[line_idx] = cells
            original_cells[line_idx] = list(cells)

        current_cells = row_cells[line_idx]
        col_lookup = {col.lower(): idx for idx, col in enumerate(cand_table.columns)}

        for col_name, raw_val in cols.items():
            col_idx = col_lookup[col_name.lower()]
            canonical_col_name = cand_table.columns[col_idx]
            escaped_val = re.sub(r"(?<!\\)\|", r"\|", str(raw_val))
            if current_cells[col_idx] != escaped_val:
                current_cells[col_idx] = escaped_val
                applied_notifications.append(f"set {item_id} {canonical_col_name}={raw_val}")

    any_changed = False
    for line_idx, cells in row_cells.items():
        if cells != original_cells[line_idx]:
            lines[line_idx] = "| " + " | ".join(cells) + " |"
            any_changed = True

    if any_changed:
        output_text = newline.join(lines)
        if ends_with_newline and lines:
            output_text += newline
        _atomic_write_bytes(file_path, output_text.encode("utf-8"))

    for note in applied_notifications:
        print(note)

    return caddis_exit.CLEAN


def handle_archive_done(args: argparse.Namespace) -> int:
    file_path = Path(args.file)
    if not file_path.exists():
        print(f"caddis-rows: file not found: {file_path}", file=sys.stderr)
        return caddis_exit.BLOCKED

    raw = file_path.read_bytes()
    text = raw.decode("utf-8")
    crlf = "\r\n" in text
    newline = "\r\n" if crlf else "\n"
    ends_with_newline = text.endswith(newline)
    if ends_with_newline:
        content = text[:-len(newline)]
    else:
        content = text
    lines = content.split(newline) if content else []

    tables = find_tables(lines)
    open_heading = args.open
    closed_heading = args.closed

    open_table = None
    closed_table = None
    for t in tables:
        if t.heading == open_heading and open_table is None:
            open_table = t
        if t.heading == closed_heading and closed_table is None:
            closed_table = t

    if open_table is None:
        print(f"caddis-rows: open table '{open_heading}' not found", file=sys.stderr)
        return caddis_exit.BLOCKED

    if closed_table is None:
        print(f"caddis-rows: closed table '{closed_heading}' not found", file=sys.stderr)
        return caddis_exit.BLOCKED

    if open_table is closed_table:
        print("caddis-rows: open table and closed table must be distinct", file=sys.stderr)
        return caddis_exit.BLOCKED

    open_col_map = {c.lower(): idx for idx, c in enumerate(open_table.columns)}
    if "status" not in open_col_map:
        print(f"caddis-rows: open table '{open_heading}' has no Status column", file=sys.stderr)
        return caddis_exit.BLOCKED

    status_idx = open_col_map["status"]
    archivable_pattern = re.compile(r"^(done|not-needed)\b")

    archivable_indices: list[int] = []
    archived_ids: list[str] = []

    for line_idx in open_table.data_line_indices:
        cells = split_cells(lines[line_idx])
        status_val = cells[status_idx].strip().lower() if len(cells) > status_idx else ""
        if archivable_pattern.search(status_val):
            archivable_indices.append(line_idx)
            row_id = (
                cells[open_table.id_col_idx]
                if (open_table.id_col_idx is not None and len(cells) > open_table.id_col_idx)
                else ""
            )
            archived_ids.append(row_id)

    if not archivable_indices:
        return caddis_exit.CLEAN

    same_headers = (open_table.columns == closed_table.columns)
    new_closed_lines: list[str] = []

    if same_headers:
        for idx in archivable_indices:
            new_closed_lines.append(lines[idx])
    else:
        closed_col_map = {c.lower(): idx for idx, c in enumerate(closed_table.columns)}
        dropped = [col for col in open_table.columns if col.lower() not in closed_col_map]
        if dropped:
            print(f"dropped columns: {', '.join(dropped)}")

        for idx in archivable_indices:
            cells = split_cells(lines[idx])
            open_vals = {
                col.lower(): (cells[i] if i < len(cells) else "")
                for i, col in enumerate(open_table.columns)
            }
            row_cells = []
            for col in closed_table.columns:
                val = open_vals.get(col.lower())
                if val is None or val == "":
                    val = "-"
                row_cells.append(val)
            new_closed_lines.append("| " + " | ".join(row_cells) + " |")

    archivable_set = set(archivable_indices)
    insert_after_idx = (
        closed_table.data_line_indices[-1]
        if closed_table.data_line_indices
        else closed_table.separator_line_idx
    )

    result_lines: list[str] = []
    for idx, line in enumerate(lines):
        if idx not in archivable_set:
            result_lines.append(line)
        if idx == insert_after_idx:
            result_lines.extend(new_closed_lines)

    output_text = newline.join(result_lines)
    if ends_with_newline and result_lines:
        output_text += newline
    _atomic_write_bytes(file_path, output_text.encode("utf-8"))

    for rid in archived_ids:
        print(f"archived {rid}")

    return caddis_exit.CLEAN


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

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(prog="caddis_rows", exit_on_error=False)
    subparsers = parser.add_subparsers(dest="subcommand")

    set_parser = subparsers.add_parser("set", exit_on_error=False)
    set_parser.add_argument("--file", required=True)
    set_parser.add_argument("--id")
    set_parser.add_argument("--col", action="append", default=[])
    set_parser.add_argument("--from", dest="from_file")
    set_parser.add_argument("--table")

    archive_parser = subparsers.add_parser("archive-done", exit_on_error=False)
    archive_parser.add_argument("--file", required=True)
    archive_parser.add_argument("--open", default="Open")
    archive_parser.add_argument("--closed", default="Closed")

    try:
        args = parser.parse_args(argv)
    except (argparse.ArgumentError, argparse.ArgumentTypeError) as exc:
        print(f"caddis-rows: {exc}", file=sys.stderr)
        return caddis_exit.ERROR
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 0
        return caddis_exit.ERROR if code != 0 else 0

    if not args.subcommand:
        print("caddis-rows: subcommand required (set, archive-done)", file=sys.stderr)
        return caddis_exit.ERROR

    try:
        if args.subcommand == "set":
            return handle_set(args)
        elif args.subcommand == "archive-done":
            return handle_archive_done(args)
        else:
            print(f"caddis-rows: unknown subcommand '{args.subcommand}'", file=sys.stderr)
            return caddis_exit.ERROR
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"caddis-rows: {exc}", file=sys.stderr)
        return caddis_exit.BLOCKED


if __name__ == "__main__":
    raise SystemExit(main())
