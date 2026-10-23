#!/usr/bin/env python3
"""caddis_upstream_check - say when an upstream skill that caddis borrowed ideas from has changed.

Why: /caddis:feature-plan and /caddis:implement adapt ideas from obra/superpowers (writing-plans 7.0.0,
subagent-driven-development 7.0.0, MIT). `.github/upstream-sources.json` records, per borrowed file, the
upstream version and the sha256 of the file we read. This script compares that record with the copies
installed in the Claude Code plugin cache (`~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/<path>`),
so caddis does not fall behind upstream without anyone seeing it. /caddis:usage-review runs it.

One line per source:
    UP-TO-DATE <id> <version>
    DRIFT <id> recorded <v> installed <v'> (sha differs): review the upstream diff and port what fits, ...
    NOT-INSTALLED <id>
`NO-SOURCES <path>` means there is no record (any repo other than the caddis source repo).

Advisory only: the exit code is always 0. Stdlib only.

Usage:
    python caddis_upstream_check.py [--sources <json>] [--cache-root <dir>] [--json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

SOURCES_REL = Path(".github") / "upstream-sources.json"
DRIFT_ADVICE = "review the upstream diff and port what fits, then update .github/upstream-sources.json"


def default_sources() -> Path:
    """The record in the current repo; else the one next to this script in a source checkout."""
    here = Path.cwd() / SOURCES_REL
    if here.is_file():
        return here
    return Path(__file__).resolve().parents[1] / SOURCES_REL


def default_cache_root() -> Path:
    return Path.home() / ".claude" / "plugins" / "cache"


def _version_key(version: str) -> tuple:
    """Numeric parts compare as numbers (7.10.0 > 7.9.0); a non-numeric part sorts before any number."""
    return tuple((1, int(p)) if p.isdigit() else (0, p) for p in version.split("."))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def installed_copies(cache_root: Path, plugin: str, rel_path: str) -> list[tuple[str, Path]]:
    """(version, file) for every installed copy, newest version last."""
    if not cache_root.is_dir():
        return []
    found = [(f.parents[len(Path(rel_path).parts) - 1].name, f)
             for f in cache_root.glob(f"*/{plugin}/*/{rel_path}") if f.is_file()]
    return sorted(found, key=lambda vf: _version_key(vf[0]))


def check_source(src: dict, cache_root: Path) -> dict:
    sid, recorded = src["id"], src["version"]
    plugin = sid.split(":", 1)[0]
    copies = installed_copies(cache_root, plugin, src["path"])
    row = {"id": sid, "status": "NOT-INSTALLED", "recorded_version": recorded, "installed_version": None,
           "line": f"NOT-INSTALLED {sid}"}
    if not copies:
        return row
    version, newest = copies[-1]
    row["installed_version"] = version
    if _sha256(newest) == src["sha256"]:
        row.update(status="UP-TO-DATE", line=f"UP-TO-DATE {sid} {recorded}")
    else:
        row.update(status="DRIFT",
                   line=f"DRIFT {sid} recorded {recorded} installed {version} (sha differs): {DRIFT_ADVICE}")
    return row


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compare borrowed upstream skills with the installed copies.")
    ap.add_argument("--sources", type=Path, default=None, help="path to upstream-sources.json")
    ap.add_argument("--cache-root", type=Path, default=None, help="the Claude Code plugin cache folder")
    ap.add_argument("--json", action="store_true", help="print the rows as a JSON list")
    args = ap.parse_args(argv)
    sources = args.sources or default_sources()
    cache_root = args.cache_root or default_cache_root()
    if not sources.is_file():
        print(f"NO-SOURCES {sources}")
        return 0
    try:
        data = json.loads(sources.read_text(encoding="utf-8"))
        rows = [check_source(src, cache_root) for src in data.get("sources", [])]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"NO-SOURCES {sources} (unreadable: {exc})")
        return 0
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            print(row["line"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
