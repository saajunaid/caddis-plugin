"""Programme lineage step: check, publish and freshness of an app's data lineage document.

`check` (part 13a): every table of the programme contract is in section 3 (the matrix) of the lineage document, and the
section 5 graph version is higher than at the base. `publish` (part 13c): copy the document to the docs folder the lineage
monitor reads (`--hla-dir` or HLA_DOCS_DIR), run the monitor's importer (`import_lineage.py` in its scripts folder) on the copy, and read the
monitor's snapshot back (its `as_of` equals the new version and every contract table is imported). `freshness` (part
13d): every contract table has a freshness signal, `source_coverage <key>` or `probe <name>`.
Exit codes: 0 clean, 1 a check failed, 3 a folder is not configured, 4 bad input.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys

try:
    import caddis_exit
except ModuleNotFoundError as exc:
    if exc.name != "caddis_exit":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-harness" / "scripts"))
    import caddis_exit


class ContractParseError(Exception):
    """Raised when the contract markdown file cannot be read or parsed."""


@dataclass
class ContractTable:
    name: str
    freshness_signal: str | None


def parse_contract_tables(contract_path: Path) -> tuple[list[ContractTable], bool]:
    """Parse contract tables from a contract markdown file.

    Returns a list of ContractTable objects and a boolean indicating whether the
    'Freshness signal' column was present in the header.
    """
    try:
        text = contract_path.read_text(encoding="utf-8")
    except Exception as exc:
        print(f"failed to read contract file {contract_path}: {exc}", file=sys.stderr)
        raise ContractParseError() from exc

    lines = text.splitlines()
    in_section = False
    section_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if re.match(r"^##\s+Tables\b", stripped):
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if in_section:
            section_lines.append(line)

    if not in_section:
        print(f"no '## Tables' section found in contract {contract_path}", file=sys.stderr)
        raise ContractParseError()

    header_idx = -1
    table_col_idx = -1
    freshness_col_idx = -1
    for idx, line in enumerate(section_lines):
        line_s = line.strip()
        if line_s.startswith("|"):
            cells = [c.strip() for c in line_s.strip("|").split("|")]
            for c_idx, cell in enumerate(cells):
                if cell == "Table":
                    table_col_idx = c_idx
                elif cell == "Freshness signal":
                    freshness_col_idx = c_idx
            if table_col_idx != -1:
                header_idx = idx
                break

    if header_idx == -1 or table_col_idx == -1:
        print(f"no header row with 'Table' column in contract {contract_path}", file=sys.stderr)
        raise ContractParseError()

    has_freshness_col = freshness_col_idx != -1
    tables: list[ContractTable] = []
    for line in section_lines[header_idx + 1:]:
        line_s = line.strip()
        if not line_s.startswith("|"):
            continue
        raw_cells = [c.strip() for c in line_s.strip("|").split("|")]
        if all(re.match(r"^:?-+:?$", c) for c in raw_cells if c):
            continue
        if table_col_idx < len(raw_cells):
            tbl_cell = raw_cells[table_col_idx].strip("`").strip()
            if not tbl_cell:
                continue
            sig_val: str | None = None
            if has_freshness_col:
                if freshness_col_idx < len(raw_cells):
                    sig_val = raw_cells[freshness_col_idx]
                else:
                    sig_val = ""
            tables.append(ContractTable(name=tbl_cell, freshness_signal=sig_val))

    if not tables:
        print(f"no data rows found in '## Tables' section of {contract_path}", file=sys.stderr)
        raise ContractParseError()

    return tables, has_freshness_col


def get_section_3_rows(doc_text: str) -> list[str]:
    """Return lines starting with '|' between heading matching '^## 3\\.' and next '^## '."""
    lines = doc_text.splitlines()
    in_section_3 = False
    rows: list[str] = []
    for line in lines:
        stripped = line.strip()
        if re.match(r"^## 3\.", stripped):
            in_section_3 = True
            continue
        if in_section_3 and stripped.startswith("## "):
            break
        if in_section_3 and stripped.startswith("|"):
            rows.append(stripped)
    return rows


def is_table_in_section_3(table_name: str, section_3_rows: list[str]) -> bool:
    """Return True if table_name appears as a whole name in any section 3 row."""
    pattern = re.compile(r"(?<![\w.])" + re.escape(table_name) + r"(?![\w.])")
    return any(pattern.search(row) for row in section_3_rows)


def extract_section_5_version(doc_text: str) -> str | None:
    """Return the first version string after heading matching '^## 5\\.'."""
    lines = doc_text.splitlines()
    start_idx = -1
    for idx, line in enumerate(lines):
        if re.match(r"^## 5\.", line.strip()):
            start_idx = idx
            break
    if start_idx == -1:
        return None
    rest = "\n".join(lines[start_idx:])
    m = re.search(r'"version"\s*:\s*"(\d{4}-\d{2}-\d{2})"', rest)
    if m:
        return m.group(1)
    return None


def cmd_check(args: argparse.Namespace) -> int:
    """Run check subcommand."""
    try:
        doc_text = args.doc.read_text(encoding="utf-8")
    except Exception as exc:
        print(f"failed to read doc {args.doc}: {exc}", file=sys.stderr)
        return caddis_exit.ERROR

    try:
        tables, _ = parse_contract_tables(args.contract)
    except ContractParseError:
        return caddis_exit.ERROR

    failure = False
    section_3_rows = get_section_3_rows(doc_text)
    for table in tables:
        if not is_table_in_section_3(table.name, section_3_rows):
            print(f"MISSING {table.name}")
            failure = True

    new_version = extract_section_5_version(doc_text)
    if new_version is None:
        print(f"no section 5 version in {args.doc}")
        failure = True
    else:
        base_version: str | None = None
        is_new_at_ref = False
        if args.base_doc is not None:
            try:
                base_text = args.base_doc.read_text(encoding="utf-8")
                base_version = extract_section_5_version(base_text)
            except Exception as exc:
                print(f"failed to read base doc {args.base_doc}: {exc}", file=sys.stderr)
                return caddis_exit.ERROR
        else:
            doc_path = args.doc.resolve()
            doc_folder = doc_path.parent
            proc_top = subprocess.run(
                ["git", "-C", str(doc_folder), "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if proc_top.returncode != 0:
                print(f"git rev-parse failed for {doc_folder}: {proc_top.stderr.strip()}", file=sys.stderr)
                return caddis_exit.ERROR
            top_dir = Path(proc_top.stdout.strip()).resolve()
            try:
                relpath = doc_path.relative_to(top_dir).as_posix()
            except ValueError:
                print(f"doc {doc_path} is not under git toplevel {top_dir}", file=sys.stderr)
                return caddis_exit.ERROR

            proc_show = subprocess.run(
                ["git", "-C", str(top_dir), "show", f"{args.base_ref}:{relpath}"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if proc_show.returncode != 0:
                base_version = None
                is_new_at_ref = True
            else:
                base_version = extract_section_5_version(proc_show.stdout)

        if base_version is None:
            if is_new_at_ref:
                print(f"version {new_version} (new at {args.base_ref})")
            elif args.base_doc is not None:
                print(f"version {new_version} (new at {args.base_doc})")
            else:
                print(f"version {new_version}")
        else:
            if new_version <= base_version:
                print(f"version not raised: {base_version} -> {new_version}")
                failure = True
            else:
                print(f"version {base_version} -> {new_version}")

    if failure:
        return caddis_exit.BLOCKED

    print(f"check ok: {len(tables)} tables in section 3")
    return caddis_exit.CLEAN


def cmd_freshness(args: argparse.Namespace) -> int:
    """Run freshness subcommand."""
    try:
        tables, has_freshness_col = parse_contract_tables(args.contract)
    except ContractParseError:
        return caddis_exit.ERROR

    if not has_freshness_col:
        print(f"contract {args.contract} is missing 'Freshness signal' column", file=sys.stderr)
        return caddis_exit.ERROR

    failure = False
    for table in tables:
        sig = (table.freshness_signal or "").replace("`", "").strip()
        if not re.match(r"^(?:source_coverage|probe) \S+$", sig):
            print(f"NO FRESHNESS {table.name}")
            failure = True

    if failure:
        return caddis_exit.BLOCKED

    print(f"freshness ok: {len(tables)} tables")
    return caddis_exit.CLEAN


def cmd_publish(args: argparse.Namespace) -> int:
    """Run publish subcommand."""
    hla_dir_val = args.hla_dir if args.hla_dir else os.environ.get("HLA_DOCS_DIR")
    if not hla_dir_val:
        print("HLA_DOCS_DIR is unset or not provided", file=sys.stderr)
        return caddis_exit.NOT_RUN

    hla_path = Path(hla_dir_val)
    if not hla_path.is_dir():
        print(f"HLA_DOCS_DIR '{hla_dir_val}' is not an existing directory", file=sys.stderr)
        return caddis_exit.NOT_RUN

    monitor_val = args.monitor_dir if args.monitor_dir else os.environ.get("LINEAGE_MONITOR_DIR")
    if not monitor_val:
        print("LINEAGE_MONITOR_DIR is unset or not provided", file=sys.stderr)
        return caddis_exit.NOT_RUN

    ws_path = Path(monitor_val)
    if not ws_path.is_dir():
        print(f"LINEAGE_MONITOR_DIR '{monitor_val}' is not an existing directory", file=sys.stderr)
        return caddis_exit.NOT_RUN

    importer_script = ws_path / "scripts" / "import_lineage.py"
    if not importer_script.is_file():
        print(f"the lineage monitor importer script not found at {importer_script}", file=sys.stderr)
        return caddis_exit.NOT_RUN

    try:
        doc_text = args.doc.read_text(encoding="utf-8")
    except Exception as exc:
        print(f"failed to read doc {args.doc}: {exc}", file=sys.stderr)
        return caddis_exit.ERROR

    version = extract_section_5_version(doc_text)
    if version is None:
        print(f"no section 5 version in {args.doc}")
        return caddis_exit.BLOCKED

    try:
        tables, _ = parse_contract_tables(args.contract)
    except ContractParseError:
        return caddis_exit.ERROR

    app_dir = hla_path / args.app
    app_dir.mkdir(parents=True, exist_ok=True)
    copied = app_dir / f"{args.app}-data-lineage.md"
    try:
        doc_bytes = args.doc.read_bytes()
        copied.write_bytes(doc_bytes)
        read_bytes = copied.read_bytes()
        if read_bytes != doc_bytes:
            print(f"copy failed: bytes differ for {copied}", file=sys.stderr)
            return caddis_exit.ERROR
    except Exception as exc:
        print(f"failed to copy doc to {copied}: {exc}", file=sys.stderr)
        return caddis_exit.ERROR

    py_win = ws_path / ".venv" / "Scripts" / "python.exe"
    py_nix = ws_path / ".venv" / "bin" / "python"
    if py_win.is_file():
        python_bin = str(py_win)
    elif py_nix.is_file():
        python_bin = str(py_nix)
    else:
        python_bin = sys.executable

    cmd = [python_bin, str(importer_script), str(copied), "--app", args.app]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ws_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        print("the lineage monitor importer timed out after 300 s", file=sys.stderr)
        return caddis_exit.BLOCKED
    except Exception as exc:
        print(f"failed to run the lineage monitor importer: {exc}", file=sys.stderr)
        return caddis_exit.ERROR

    if proc.stdout:
        sys.stdout.write(proc.stdout)
        if not proc.stdout.endswith("\n"):
            sys.stdout.write("\n")

    if proc.returncode != 0:
        if proc.stderr:
            sys.stderr.write(proc.stderr)
            if not proc.stderr.endswith("\n"):
                sys.stderr.write("\n")
        return caddis_exit.BLOCKED

    # The monitor writes `config/lineage-snapshot-<app>.json`, except for its first app, whose snapshot is the
    # unsuffixed file; that file counts only when its `app` field names this app.
    snapshot_data = None
    for snapshot_path in (ws_path / "config" / f"lineage-snapshot-{args.app}.json",
                          ws_path / "config" / "lineage-snapshot.json"):
        if not snapshot_path.is_file():
            continue
        try:
            candidate = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"the lineage monitor snapshot {snapshot_path} is not valid JSON: {exc}")
            return caddis_exit.BLOCKED
        if isinstance(candidate, dict) and candidate.get("app") == args.app:
            snapshot_data = candidate
            break
    if snapshot_data is None:
        print(f"no lineage monitor snapshot for app {args.app} under {ws_path / 'config'}")
        return caddis_exit.BLOCKED

    snapshot_as_of = snapshot_data.get("as_of")
    if snapshot_as_of != version:
        print(f"snapshot as_of {snapshot_as_of}, expected {version}")
        return caddis_exit.BLOCKED

    imported_names: set[str] = set()
    elements = snapshot_data.get("elements")
    if isinstance(elements, list):
        for elem in elements:
            if isinstance(elem, dict):
                datasets = elem.get("datasets")
                if isinstance(datasets, list):
                    for ds in datasets:
                        if isinstance(ds, dict) and "name" in ds:
                            imported_names.add(ds["name"])

    missing_from_snapshot = False
    for table in tables:
        if table.name not in imported_names:
            print(f"NOT IMPORTED {table.name}")
            missing_from_snapshot = True

    if missing_from_snapshot:
        return caddis_exit.BLOCKED

    print(f"published {args.app} version {version}: {copied}; {len(tables)} tables imported")
    return caddis_exit.CLEAN


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for caddis_lineage_publish."""
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(description="Publish and check data lineage documentation.")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # Subcommand: check
    p_check = subparsers.add_parser("check", help="Check lineage doc against contract tables and version.")
    p_check.add_argument("--app", required=True, help="Application name")
    p_check.add_argument("--doc", required=True, type=Path, help="Path to lineage doc")
    p_check.add_argument("--contract", required=True, type=Path, help="Path to contract markdown")
    p_check.add_argument("--base-doc", type=Path, default=None, help="Path to base doc for version comparison")
    p_check.add_argument("--base-ref", default="origin/main", help="Git ref for base doc (default: origin/main)")

    # Subcommand: freshness
    p_freshness = subparsers.add_parser("freshness", help="Verify freshness signals for contract tables.")
    p_freshness.add_argument("--app", required=True, help="Application name")
    p_freshness.add_argument("--contract", required=True, type=Path, help="Path to contract markdown")

    # Subcommand: publish
    p_publish = subparsers.add_parser("publish", help="Publish lineage doc to HLA docs and trigger import.")
    p_publish.add_argument("--app", required=True, help="Application name")
    p_publish.add_argument("--doc", required=True, type=Path, help="Path to lineage doc")
    p_publish.add_argument("--contract", required=True, type=Path, help="Path to contract markdown")
    p_publish.add_argument("--hla-dir", type=Path, default=None, help="Path to HLA docs directory")
    p_publish.add_argument("--monitor-dir", type=Path, default=None, help="lineage monitor repository (default: env LINEAGE_MONITOR_DIR)")

    args = parser.parse_args(argv)

    if args.subcommand == "check":
        return cmd_check(args)
    if args.subcommand == "freshness":
        return cmd_freshness(args)
    if args.subcommand == "publish":
        return cmd_publish(args)

    return caddis_exit.ERROR


if __name__ == "__main__":
    sys.exit(main())
