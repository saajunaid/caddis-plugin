"""Validate that production UI fields have source-to-screen lineage."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REQUIRED_KEYS = (
    "ui_component",
    "ui_label",
    "frontend_field",
    "api_field",
    "display_dto_field",
    "source",
    "source_field",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate lineage_manifest.json coverage.")
    parser.add_argument("--lineage", type=Path, required=True, help="lineage_manifest.json")
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Return success for partial/evolving contracts.",
    )
    args = parser.parse_args()

    manifest = json.loads(args.lineage.read_text(encoding="utf-8-sig"))
    findings: list[str] = []
    for idx, item in enumerate(manifest.get("lineage", []), start=1):
        status = item.get("status", "contract-backed")
        if status in {"deferred", "mockup-only", "source-capability-only"}:
            continue
        missing = [key for key in REQUIRED_KEYS if not item.get(key)]
        if missing:
            findings.append(f"L{idx}: missing {', '.join(missing)}")

    if findings:
        for finding in findings:
            print(finding)
        sys.exit(0 if args.allow_partial else 1)
    print("Lineage validation passed.")


if __name__ == "__main__":
    main()
