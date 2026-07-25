"""
TypeScript ↔ DTO Comparator

Compares TypeScript interface properties against Python Pydantic DTO aliases
to detect D4 (alias mismatch) and D5 (type mismatch) drift.

Usage:
    python scripts/ts_dto_compare.py \
        --ts frontend/src/types/my-source.ts \
        --dto src.models.responses.my_source.MyResponse

Part of the data-contract-pipeline skill.
"""

from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path


# Python → TypeScript type mapping
PYTHON_TO_TS_TYPE: dict[str, str] = {
    "str": "string",
    "int": "number",
    "float": "number",
    "bool": "boolean",
    "list": "Array",
    "dict": "Record",
    "None": "null",
    "Any": "any",
}


def load_class(dotted_path: str) -> type:
    """Import a class from a dotted module path."""
    module_path, _, class_name = dotted_path.rpartition(".")
    if not module_path:
        raise ValueError(f"Invalid class path: {dotted_path}")
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name, None)
    if cls is None:
        raise AttributeError(f"{class_name} not found in {module_path}")
    return cls


def extract_ts_properties(ts_source: str) -> dict[str, str]:
    """
    Extract property names and types from a TypeScript interface.

    Returns dict of {property_name: type_string}.
    Handles basic types — not deep generics or union types.
    """
    properties: dict[str, str] = {}

    # Match: propertyName: type; or propertyName?: type;
    pattern = re.compile(
        r"^\s*(\w+)\s*\??\s*:\s*(.+?)\s*;",
        re.MULTILINE,
    )

    for match in pattern.finditer(ts_source):
        prop_name = match.group(1)
        prop_type = match.group(2).strip()
        properties[prop_name] = prop_type

    return properties


def get_dto_aliases_and_types(dto_cls: type) -> dict[str, str]:
    """
    Get DTO field aliases and their simplified type names.

    Returns dict of {alias: simplified_python_type}.
    """
    result: dict[str, str] = {}
    for name, info in dto_cls.model_fields.items():
        alias = info.alias or name
        # Get the annotation type and simplify
        annotation = info.annotation
        type_name = getattr(annotation, "__name__", str(annotation))
        result[alias] = type_name
    return result


def python_type_to_ts(python_type: str) -> str:
    """Convert a simplified Python type string to expected TypeScript type."""
    # Handle Optional/union types
    python_type = python_type.replace("NoneType", "None")

    # Direct mapping
    if python_type in PYTHON_TO_TS_TYPE:
        return PYTHON_TO_TS_TYPE[python_type]

    # Handle list[T]
    list_match = re.match(r"list\[(.+)]", python_type)
    if list_match:
        inner = python_type_to_ts(list_match.group(1))
        return f"{inner}[]"

    # Handle dict[str, T]
    dict_match = re.match(r"dict\[str,\s*(.+)]", python_type)
    if dict_match:
        inner = python_type_to_ts(dict_match.group(1))
        return f"Record<string, {inner}>"

    return python_type


def compare(
    ts_properties: dict[str, str],
    dto_fields: dict[str, str],
) -> list[str]:
    """
    Compare TypeScript properties against DTO aliases.

    Returns list of drift findings.
    """
    findings: list[str] = []

    ts_names = set(ts_properties.keys())
    dto_names = set(dto_fields.keys())

    # D4 — Alias mismatch: DTO field not in TypeScript
    for name in sorted(dto_names - ts_names):
        findings.append(
            f"D4: DTO alias '{name}' not found in TypeScript interface"
        )

    # D4 — Alias mismatch: TypeScript property not in DTO
    for name in sorted(ts_names - dto_names):
        findings.append(
            f"D4: TypeScript property '{name}' not found in DTO aliases"
        )

    # D5 — Type mismatch (for shared properties)
    for name in sorted(ts_names & dto_names):
        expected_ts = python_type_to_ts(dto_fields[name])
        actual_ts = ts_properties[name]

        # Normalize for comparison (strip whitespace, lowercase basic types)
        norm_expected = expected_ts.lower().strip()
        norm_actual = actual_ts.lower().strip()

        if norm_expected != norm_actual:
            findings.append(
                f"D5: Type mismatch for '{name}': "
                f"DTO expects '{expected_ts}', TS has '{actual_ts}'"
            )

    return findings


def main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Compare TypeScript interface properties against Python DTO aliases"
    )
    parser.add_argument(
        "--ts",
        type=Path,
        required=True,
        help="Path to TypeScript types file",
    )
    parser.add_argument(
        "--dto",
        type=str,
        required=True,
        help="Dotted path to DTO class (e.g., src.models.responses.nps.NpsResponse)",
    )
    args = parser.parse_args()

    # Load TypeScript source
    if not args.ts.exists():
        print(f"Error: TypeScript file not found: {args.ts}", file=sys.stderr)
        sys.exit(1)

    ts_source = args.ts.read_text(encoding="utf-8")
    ts_properties = extract_ts_properties(ts_source)

    if not ts_properties:
        print(
            f"Warning: No properties found in {args.ts}. "
            f"Is the interface defined with standard syntax?",
            file=sys.stderr,
        )

    # Load DTO
    try:
        dto_cls = load_class(args.dto)
    except (ValueError, AttributeError, ModuleNotFoundError) as e:
        print(f"Error loading DTO: {e}", file=sys.stderr)
        sys.exit(1)

    dto_fields = get_dto_aliases_and_types(dto_cls)

    # Compare
    findings = compare(ts_properties, dto_fields)

    if not findings:
        print(f"✅ No drift detected ({len(ts_properties)} properties matched).")
        sys.exit(0)
    else:
        print(f"❌ {len(findings)} drift finding(s):\n")
        for finding in findings:
            print(f"  {finding}")
        sys.exit(1)


if __name__ == "__main__":
    main()
