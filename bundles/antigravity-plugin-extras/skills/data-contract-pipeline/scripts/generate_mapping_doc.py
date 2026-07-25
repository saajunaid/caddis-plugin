"""
Generate Mapping Doc — Produces a human-readable field mapping document
from Pydantic ingestion model + display DTO + optional TypeScript types.

Usage:
    python scripts/generate_mapping_doc.py \
        --ingestion src.models.ingestion.nps_monthly:NpsMonthlyPayload \
        --dto src.models.responses.nps_monthly:NpsMonthlyResponse \
        --ts-types frontend/src/types/nps-monthly.ts \
        --output docs/mapping/nps-monthly-mapping.md

    # Check mode — exit 1 if existing doc is stale
    python scripts/generate_mapping_doc.py \
        --ingestion src.models.ingestion.nps_monthly:NpsMonthlyPayload \
        --dto src.models.responses.nps_monthly:NpsMonthlyResponse \
        --check docs/mapping/nps-monthly-mapping.md

Part of the data-contract-pipeline skill.
"""

from __future__ import annotations

import argparse
import importlib
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, get_type_hints


def load_class(dotted_path: str) -> type:
    """Import a class from 'module.path:ClassName' or 'module.path.ClassName'."""
    if ":" in dotted_path:
        module_path, class_name = dotted_path.rsplit(":", 1)
    else:
        module_path, _, class_name = dotted_path.rpartition(".")
    if not module_path:
        raise ValueError(
            f"Invalid class path: {dotted_path}. "
            f"Expected: module.path:ClassName or module.path.ClassName"
        )
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name, None)
    if cls is None:
        raise AttributeError(f"{class_name} not found in {module_path}")
    return cls


def get_field_info(model_cls: type) -> list[dict[str, str]]:
    """Extract field name, alias, and type string from a Pydantic model."""
    hints = get_type_hints(model_cls, include_extras=True)
    rows: list[dict[str, str]] = []
    for name, field in model_cls.model_fields.items():
        alias = field.alias or name
        type_str = _type_repr(hints.get(name, Any))
        rows.append({
            "field_name": name,
            "alias": alias,
            "type": type_str,
        })
    return rows


def _type_repr(tp: Any) -> str:
    """Compact string repr of a type annotation."""
    origin = getattr(tp, "__origin__", None)
    args = getattr(tp, "__args__", None)
    if origin is not None and args:
        origin_name = getattr(origin, "__name__", str(origin))
        arg_strs = ", ".join(_type_repr(a) for a in args)
        return f"{origin_name}[{arg_strs}]"
    if hasattr(tp, "__name__"):
        return tp.__name__
    return str(tp)


def parse_ts_interface(ts_path: Path) -> dict[str, str]:
    """Extract property names and types from a TypeScript interface file.

    Returns {propertyName: tsType}.
    """
    if not ts_path.exists():
        return {}
    text = ts_path.read_text(encoding="utf-8")
    props: dict[str, str] = {}
    # Match:  propertyName: type;  or  propertyName?: type;
    for match in re.finditer(
        r"^\s+(\w+)\??:\s*(.+?);", text, re.MULTILINE,
    ):
        props[match.group(1)] = match.group(2).strip()
    return props


def build_mapping_table(
    ingestion_fields: list[dict[str, str]],
    dto_fields: list[dict[str, str]],
    ts_props: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Build the field mapping rows and dropped field rows.

    Returns (mapping_rows, dropped_rows) as lists of markdown table lines.
    """
    dto_by_alias: dict[str, dict[str, str]] = {
        f["alias"]: f for f in dto_fields
    }
    dto_by_name: dict[str, dict[str, str]] = {
        f["field_name"]: f for f in dto_fields
    }

    mapping_rows: list[str] = []
    covered_aliases: set[str] = set()

    for ing in ingestion_fields:
        json_key = ing["alias"]
        py_field = ing["field_name"]
        py_type = ing["type"]

        # Find matching DTO field by alias or name
        dto = dto_by_alias.get(json_key) or dto_by_name.get(py_field)
        if dto:
            dto_alias = dto["alias"]
            covered_aliases.add(dto_alias)
            ts_prop = ts_props.get(dto_alias, "—")
            mapping_rows.append(
                f"| `{json_key}` | `{py_field}` | `{dto_alias}` "
                f"| `{ts_prop}` | `{py_type}` | |"
            )
        else:
            mapping_rows.append(
                f"| `{json_key}` | `{py_field}` | — | — "
                f"| `{py_type}` | **Not in DTO** |"
            )

    # Dropped fields: in ingestion but not in DTO
    dropped_rows: list[str] = []
    for ing in ingestion_fields:
        json_key = ing["alias"]
        py_field = ing["field_name"]
        dto = dto_by_alias.get(json_key) or dto_by_name.get(py_field)
        if not dto:
            dropped_rows.append(
                f"| `{json_key}` | Not mapped to display DTO |"
            )

    return mapping_rows, dropped_rows


def generate_doc(
    ingestion_cls: type,
    dto_cls: type,
    ts_path: Path | None = None,
) -> str:
    """Generate the full mapping document as a markdown string."""
    source_name = ingestion_cls.__name__.replace("Payload", "")
    ing_fields = get_field_info(ingestion_cls)
    dto_fields = get_field_info(dto_cls)
    ts_props = parse_ts_interface(ts_path) if ts_path else {}

    mapping_rows, dropped_rows = build_mapping_table(
        ing_fields, dto_fields, ts_props,
    )

    field_table = "\n".join(mapping_rows) if mapping_rows else "| _(no fields)_ | | | | | |"
    dropped_table = "\n".join(dropped_rows) if dropped_rows else "| _(none)_ | |"

    ing_module = ingestion_cls.__module__
    dto_module = dto_cls.__module__
    today = date.today().isoformat()

    return f"""# {source_name} — UI ↔ JSON Data Mapping

> **Auto-generated reference** — do not hand-edit.
> Regenerate with: `python scripts/generate_mapping_doc.py`
> Source of truth: contract tests + Pydantic models

---

## Data Source

| Property | Value |
|----------|-------|
| Ingestion Model | `{ing_module}.{ingestion_cls.__name__}` |
| Display DTO | `{dto_module}.{dto_cls.__name__}` |
| TS Types | `{ts_path or '—'}` |

---

## Field Mapping

| JSON Key | Python Field | DTO Alias | TypeScript Property | Type | Notes |
|----------|-------------|-----------|--------------------:|------|-------|
{field_table}

---

## Intentionally Dropped Fields

Fields present in the source but NOT exposed to the frontend:

| JSON Key | Reason |
|----------|--------|
{dropped_table}

---

## Changelog

| Date | Change |
|------|--------|
| {today} | Auto-generated from models |
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate or check a field mapping doc from Pydantic models"
    )
    parser.add_argument(
        "--ingestion", required=True,
        help="Dotted path to ingestion model (module.path:ClassName)",
    )
    parser.add_argument(
        "--dto", required=True,
        help="Dotted path to display DTO (module.path:ClassName)",
    )
    parser.add_argument(
        "--ts-types", type=Path, default=None,
        help="Path to TypeScript interface file (optional)",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Write mapping doc to this file (generate mode)",
    )
    parser.add_argument(
        "--check", type=Path, default=None,
        help="Compare existing doc against models (check mode, exit 1 if stale)",
    )
    args = parser.parse_args()

    if not args.output and not args.check:
        parser.error("Provide --output (generate) or --check (validate)")

    try:
        ingestion_cls = load_class(args.ingestion)
        dto_cls = load_class(args.dto)
    except (ValueError, AttributeError, ModuleNotFoundError) as e:
        print(f"Error loading model: {e}", file=sys.stderr)
        sys.exit(1)

    doc = generate_doc(ingestion_cls, dto_cls, args.ts_types)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(doc, encoding="utf-8")
        print(f"✅ Mapping doc written to {args.output}")
        sys.exit(0)

    if args.check:
        if not args.check.exists():
            print(f"❌ Mapping doc not found: {args.check}", file=sys.stderr)
            sys.exit(1)

        existing = args.check.read_text(encoding="utf-8")
        # Compare the Field Mapping table sections only (ignore dates/changelog)
        new_table = _extract_table(doc)
        old_table = _extract_table(existing)

        if new_table == old_table:
            print("✅ Mapping doc is current.")
            sys.exit(0)
        else:
            print("❌ Mapping doc is STALE — regenerate it.")
            print(f"  Expected {len(new_table)} lines, found {len(old_table)} lines.")
            sys.exit(1)


def _extract_table(text: str) -> list[str]:
    """Extract the Field Mapping table rows for comparison."""
    lines: list[str] = []
    in_section = False
    for line in text.splitlines():
        if "## Field Mapping" in line:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section and line.startswith("|") and "JSON Key" not in line and "---" not in line:
            lines.append(line.strip())
    return lines


if __name__ == "__main__":
    main()
