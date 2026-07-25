"""
Drift Check — Compares Pydantic DTO fields against a golden sample payload.

Detects:
  D1 — Payload key not in ingestion model
  D2 — Ingestion field not in display DTO
  D3 — DTO uses extra="ignore"
  D8 — Golden sample missing

Usage:
    python scripts/drift_check.py \
        --payload tests/fixtures/payloads/my_source/sample.json \
        --ingestion src.models.ingestion.my_source.MyPayload \
        --dto src.models.responses.my_source.MyResponse

Part of the data-contract-pipeline skill.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any


def load_class(dotted_path: str) -> type:
    """
    Import a class from a dotted module path.

    Example: 'src.models.responses.nps.NpsResponse' → <class NpsResponse>
    """
    module_path, _, class_name = dotted_path.rpartition(".")
    if not module_path:
        raise ValueError(
            f"Invalid class path: {dotted_path}. "
            f"Expected format: module.path.ClassName"
        )
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name, None)
    if cls is None:
        raise AttributeError(f"{class_name} not found in {module_path}")
    return cls


def get_field_aliases(model_cls: type) -> set[str]:
    """Get all field aliases (or names if no alias) from a Pydantic model."""
    return {
        info.alias or name
        for name, info in model_cls.model_fields.items()
    }


def check_d1(payload_keys: set[str], ingestion_aliases: set[str]) -> list[str]:
    """D1: Payload keys not covered by ingestion model."""
    uncovered = payload_keys - ingestion_aliases
    return [f"D1: Payload key '{k}' not in ingestion model" for k in sorted(uncovered)]


def check_d2(ingestion_aliases: set[str], dto_aliases: set[str]) -> list[str]:
    """D2: Ingestion fields not mapped to display DTO."""
    unmapped = ingestion_aliases - dto_aliases
    return [f"D2: Ingestion field '{k}' not in display DTO" for k in sorted(unmapped)]


def check_d3(dto_cls: type) -> list[str]:
    """D3: Display DTO uses extra='ignore' (silent field drops)."""
    extra = dto_cls.model_config.get("extra", "ignore")
    if extra == "ignore":
        return [
            f"D3: Display DTO uses extra='ignore' — "
            f"fields will be silently dropped. Use 'forbid' or 'allow'."
        ]
    return []


def check_d8(payload_path: Path) -> list[str]:
    """D8: Golden sample file missing."""
    if not payload_path.exists():
        return [f"D8: Golden sample not found: {payload_path}"]
    return []


def run_drift_check(
    payload_path: Path,
    ingestion_cls: type,
    dto_cls: type,
) -> list[str]:
    """
    Run all applicable drift checks.

    Returns a list of drift findings (empty = clean).
    """
    findings: list[str] = []

    # D8 — Golden sample exists
    findings.extend(check_d8(payload_path))
    if findings:
        return findings  # Can't continue without the sample

    # Load payload
    data = json.loads(payload_path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        data = data[0] if data else {}
    payload_keys = set(data.keys())

    # Get field aliases
    ingestion_aliases = get_field_aliases(ingestion_cls)
    dto_aliases = get_field_aliases(dto_cls)

    # D1 — Payload keys covered by ingestion model
    findings.extend(check_d1(payload_keys, ingestion_aliases))

    # D3 — DTO extra config
    findings.extend(check_d3(dto_cls))

    # D2 — Ingestion fields mapped to DTO
    findings.extend(check_d2(ingestion_aliases, dto_aliases))

    return findings


def main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Check for data contract drift between payload, models, and DTOs"
    )
    parser.add_argument(
        "--payload",
        type=Path,
        required=True,
        help="Path to golden sample JSON file",
    )
    parser.add_argument(
        "--ingestion",
        type=str,
        required=True,
        help="Dotted path to ingestion model class (e.g., src.models.ingestion.nps.NpsPayload)",
    )
    parser.add_argument(
        "--dto",
        type=str,
        required=True,
        help="Dotted path to display DTO class (e.g., src.models.responses.nps.NpsResponse)",
    )
    args = parser.parse_args()

    try:
        ingestion_cls = load_class(args.ingestion)
        dto_cls = load_class(args.dto)
    except (ValueError, AttributeError, ModuleNotFoundError) as e:
        print(f"Error loading model: {e}", file=sys.stderr)
        sys.exit(1)

    findings = run_drift_check(args.payload, ingestion_cls, dto_cls)

    if not findings:
        print("✅ No drift detected.")
        sys.exit(0)
    else:
        print(f"❌ {len(findings)} drift finding(s):\n")
        for finding in findings:
            print(f"  {finding}")
        sys.exit(1)


if __name__ == "__main__":
    main()
