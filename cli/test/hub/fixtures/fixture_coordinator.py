"""Fixture coordinator for the hub H3 gate test (ruling R43).

It runs the REAL `caddis_coordinate.py` intake on the hub folder named by `CADDIS_HUB_HOME`. The live head of each PR
comes from the command line, so the test never calls `gh`.

Usage: fixture_coordinator.py <scripts folder> <repo id> '<json map of pr to head sha>'
Prints this cycle's intake results as one JSON line.
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path


def main() -> int:
    scripts, rid, heads_json = sys.argv[1], sys.argv[2], sys.argv[3]
    sys.path.insert(0, str(Path(scripts).resolve()))
    import caddis_coordinate as coord  # noqa: PLC0415 - the path is known only at run time

    heads = {int(pr): sha for pr, sha in json.loads(heads_json).items()}
    now = datetime.datetime.now(datetime.timezone.utc)
    results = coord.intake(rid, now, lambda pr: heads.get(pr))
    print(json.dumps(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
