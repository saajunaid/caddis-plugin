"""Split a markdown table line into cells (caddis_roadmap reads its tables with this).

The `set` and `archive-done` sub-commands edited `.caddis/open-work.md`. They are retired with the
3-store model (owner decision, 21 Oct 2026): caddis no longer reads or writes open-work.md. Running the
script prints one line and changes nothing, so an older /handoff that still calls `set` does not fail.
"""

from __future__ import annotations

import re
import sys

RETIRED = "caddis_rows: set and archive-done are retired (3-store model); nothing changed"


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


def main(argv: list[str] | None = None) -> int:
    print(RETIRED)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
