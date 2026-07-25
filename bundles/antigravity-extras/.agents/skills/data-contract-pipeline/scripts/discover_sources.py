"""Discover source schemas from files or a SQL Server connection string.

The script emits a normalized source_manifest.json. DB discovery uses pyodbc
when available and metadata-only queries by default.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def infer_value_type(value: Any) -> str:
    if value is None or value == "":
        return "null-or-empty"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    text = str(value).strip()
    for caster, name in ((int, "int"), (float, "float")):
        try:
            caster(text.replace(",", ""))
            return name
        except ValueError:
            pass
    return "str"


def discover_json(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    sample = data[0] if isinstance(data, list) and data else data
    fields = []
    if isinstance(sample, dict):
        fields = [
            {"path": key, "type": infer_value_type(value), "example": str(value)[:120]}
            for key, value in sample.items()
        ]
    return {"source": str(path), "kind": "json", "fields": fields}


def discover_csv(path: Path) -> dict[str, object]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        first = next(reader, {})
    fields = [
        {"path": key, "type": infer_value_type(value), "example": str(value)[:120]}
        for key, value in first.items()
    ]
    return {"source": str(path), "kind": "csv", "fields": fields}


def discover_text(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return {
        "source": str(path),
        "kind": path.suffix.lower().lstrip(".") or "text",
        "line_count": len(text.splitlines()),
        "fields": [],
    }


def discover_file(path: Path) -> dict[str, object]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return discover_json(path)
    if suffix in {".csv", ".tsv"}:
        return discover_csv(path)
    return discover_text(path)


def discover_db(connection_string: str, schema: str | None) -> dict[str, object]:
    try:
        import pyodbc  # type: ignore
    except ModuleNotFoundError:
        return {
            "kind": "db",
            "status": "blocked",
            "reason": "pyodbc is not installed",
            "objects": [],
        }

    objects: list[dict[str, object]] = []
    with pyodbc.connect(connection_string, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
            FROM INFORMATION_SCHEMA.TABLES
            WHERE (? IS NULL OR TABLE_SCHEMA = ?)
            ORDER BY TABLE_SCHEMA, TABLE_NAME
            """,
            schema,
            schema,
        )
        rows = cursor.fetchall()
        for row in rows:
            table_schema, table_name, table_type = row
            cursor.execute(
                """
                SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
                ORDER BY ORDINAL_POSITION
                """,
                table_schema,
                table_name,
            )
            columns = [
                {"name": c.COLUMN_NAME, "type": c.DATA_TYPE, "nullable": c.IS_NULLABLE}
                for c in cursor.fetchall()
            ]
            objects.append(
                {
                    "schema": table_schema,
                    "name": table_name,
                    "type": table_type,
                    "columns": columns,
                }
            )
    return {"kind": "db", "status": "discovered", "objects": objects}


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover data sources and emit source_manifest.json.")
    parser.add_argument("--source", type=Path, action="append", help="Source file or directory")
    parser.add_argument("--connection-string", help="ODBC connection string for DB metadata discovery")
    parser.add_argument("--schema", help="Optional DB schema filter")
    parser.add_argument("--output", type=Path, required=True, help="Output source_manifest.json path")
    args = parser.parse_args()

    sources: list[dict[str, object]] = []
    for source in args.source or []:
        if source.is_dir():
            for path in source.rglob("*"):
                if path.is_file():
                    sources.append(discover_file(path))
        elif source.exists():
            sources.append(discover_file(source))
        else:
            sources.append({"source": str(source), "status": "missing", "fields": []})

    if args.connection_string:
        sources.append(discover_db(args.connection_string, args.schema))

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
