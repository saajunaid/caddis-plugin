"""Generate human-readable gap reports from gap_register.json."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate gap report markdown.")
    parser.add_argument("--gaps", type=Path, required=True, help="gap_register.json")
    parser.add_argument("--output", type=Path, required=True, help="gap report markdown path")
    parser.add_argument("--ui-gap-brief", type=Path, help="Optional ui_gap_brief.md path")
    args = parser.parse_args()

    register = json.loads(args.gaps.read_text(encoding="utf-8-sig"))
    gaps = register.get("gaps", [])
    counts = Counter(gap.get("gap_type", "unknown") for gap in gaps)

    lines = [
        "# Data Contract Gap Report",
        "",
        f"Generated: {date.today().isoformat()}",
        "",
        "## Summary",
        "",
    ]
    if counts:
        for key, count in sorted(counts.items()):
            lines.append(f"- `{key}`: {count}")
    else:
        lines.append("- No gaps found.")

    lines.extend(["", "## Gaps", ""])
    for gap in gaps:
        label = gap.get("ui_name") or gap.get("requirement") or gap.get("requirement_id") or "Unnamed"
        lines.extend(
            [
                f"### {label}",
                "",
                f"- Status: `{gap.get('status', 'unknown')}`",
                f"- Gap type: `{gap.get('gap_type', 'unknown')}`",
                f"- Candidate source field: `{gap.get('source_field_candidate', '')}`",
                f"- Notes: {gap.get('notes', '')}",
                "",
            ]
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    if args.ui_gap_brief:
        required = [gap for gap in gaps if gap.get("gap_type") == "required-unplaced"]
        brief = [
            "# UI Gap Brief",
            "",
            "Use this brief to place required data that is not present in the mockup/final UI.",
            "",
        ]
        for gap in required:
            brief.extend(
                [
                    f"## {gap.get('requirement_id', 'Requirement')}",
                    "",
                    f"- Requirement: {gap.get('requirement', '')}",
                    "- Proposed placement: TBD by product/design.",
                    "- Component type: TBD.",
                    "- DisplayDTO fields: TBD.",
                    "- Acceptance criteria: Field is visible in the agreed UI location and has source-to-screen lineage.",
                    "",
                ]
            )
        args.ui_gap_brief.parent.mkdir(parents=True, exist_ok=True)
        args.ui_gap_brief.write_text("\n".join(brief).rstrip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
