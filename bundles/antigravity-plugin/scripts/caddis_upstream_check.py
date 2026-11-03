#!/usr/bin/env python3
"""caddis_upstream_check - say when an upstream skill that caddis borrowed ideas from has changed.

Why: caddis owns the routing-critical skills and commands that it adapted from obra/superpowers
(writing-plans, subagent-driven-development, brainstorming, using-git-worktrees; MIT). The other superpowers
skills are used straight from the plugin. `.github/upstream-sources.json` records, per borrowed file, the upstream version and the
sha256 of the file we read. This script compares that record with upstream, so caddis does not fall
behind without anyone seeing it. /caddis:usage-review runs the local mode. The weekly workflow
`.github/workflows/upstream-drift.yml` runs `--remote` and opens one issue when anything drifts.

Two modes:
    local (default)  compare with the copies installed in the Claude Code plugin cache
                     (`~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/<path>`). It is blind
                     when the upstream plugin is turned off or not installed.
    --remote         ask GitHub instead: take the latest release tag of each `upstream` repo (the
                     newest tag when there is no release), fetch the file at that tag from
                     raw.githubusercontent.com and hash it. Needs the network. Set GITHUB_TOKEN to
                     avoid the anonymous API rate limit. Stdlib `urllib` only.

One line per source:
    UP-TO-DATE <id> <version>
    DRIFT <id> recorded <v> installed <new> (sha differs): review the upstream diff and port what fits, ...
    DRIFT <id> recorded <v> upstream <tag> (sha differs): ...                  (--remote)
    DRIFT <id> recorded <v> upstream <tag> (file not found at that tag): ...   (--remote)
    NOT-INSTALLED <id>                                                         (local only)
    UNREACHABLE <id> <reason>                          (--remote: network or API error)
`NO-SOURCES <path>` means there is no record (any repo other than the caddis source repo).

Advisory: the exit code is 0 unless `--fail-on-drift` is set and some line is DRIFT (then 1).
This script never copies upstream text. The caddis files are adapted, so a copy would undo the
adaptation: a human reads the diff and ports what fits.

Usage:
    python caddis_upstream_check.py [--sources <json>] [--cache-root <dir>] [--json]
                                    [--remote] [--fail-on-drift]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

SOURCES_REL = Path(".github") / "upstream-sources.json"
DRIFT_ADVICE = "review the upstream diff and port what fits, then update .github/upstream-sources.json"
API_ROOT = "https://api.github.com"
RAW_ROOT = "https://raw.githubusercontent.com"
TIMEOUT_SECONDS = 20


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


# ---- remote mode ------------------------------------------------------------------------------------

class FetchError(Exception):
    """A network or HTTP failure. `status` is the HTTP status code, or None for a network error."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def fetch(url: str, token: str | None = None) -> bytes:
    """GET a URL and return the body. Raise FetchError on any failure. Tests replace this function."""
    headers = {"User-Agent": "caddis-upstream-check", "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=TIMEOUT_SECONDS) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} for {url}", exc.code) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise FetchError(f"{exc} for {url}") from exc


def latest_tag(upstream: str, token: str | None = None) -> str | None:
    """The latest release tag of `owner/repo`; when it has no release, the newest tag; else None."""
    try:
        release = json.loads(fetch(f"{API_ROOT}/repos/{upstream}/releases/latest", token))
        if release.get("tag_name"):
            return str(release["tag_name"])
    except FetchError as exc:
        if exc.status != 404:
            raise
    tags = json.loads(fetch(f"{API_ROOT}/repos/{upstream}/tags?per_page=100", token))
    names = [str(tag["name"]) for tag in tags if isinstance(tag, dict) and tag.get("name")]
    return max(names, key=lambda name: _version_key(name.lstrip("v"))) if names else None


def check_source_remote(src: dict, tags: dict[str, str | None], token: str | None = None) -> dict:
    """Compare one record with the file at the latest upstream tag. `tags` caches one lookup per repo."""
    sid, recorded, upstream = src["id"], src["version"], src["upstream"]
    row = {"id": sid, "status": "UNREACHABLE", "recorded_version": recorded, "installed_version": None,
           "upstream_tag": None, "line": ""}

    def done(status: str, line: str) -> dict:
        row.update(status=status, line=line)
        return row

    try:
        if upstream not in tags:
            tags[upstream] = latest_tag(upstream, token)
        tag = tags[upstream]
        if tag is None:
            return done("UNREACHABLE", f"UNREACHABLE {sid} {upstream} has no releases and no tags")
        row["upstream_tag"] = tag
        try:
            body = fetch(f"{RAW_ROOT}/{upstream}/{tag}/{src['path']}", token)
        except FetchError as exc:
            if exc.status == 404:
                return done("DRIFT", f"DRIFT {sid} recorded {recorded} upstream {tag} "
                                     f"(file not found at that tag): {DRIFT_ADVICE}")
            raise
    except (FetchError, ValueError, KeyError, TypeError) as exc:
        return done("UNREACHABLE", f"UNREACHABLE {sid} {exc}")
    if hashlib.sha256(body).hexdigest() == src["sha256"]:
        return done("UP-TO-DATE", f"UP-TO-DATE {sid} {recorded}")
    return done("DRIFT", f"DRIFT {sid} recorded {recorded} upstream {tag} (sha differs): {DRIFT_ADVICE}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compare borrowed upstream skills with the installed copies.")
    ap.add_argument("--sources", type=Path, default=None, help="path to upstream-sources.json")
    ap.add_argument("--cache-root", type=Path, default=None, help="the Claude Code plugin cache folder")
    ap.add_argument("--json", action="store_true", help="print the rows as a JSON list")
    ap.add_argument("--remote", action="store_true",
                    help="ask GitHub for the latest release of each upstream repo instead of reading the plugin cache")
    ap.add_argument("--fail-on-drift", action="store_true", help="exit 1 when any source shows DRIFT")
    args = ap.parse_args(argv)
    sources = args.sources or default_sources()
    cache_root = args.cache_root or default_cache_root()
    if not sources.is_file():
        print(f"NO-SOURCES {sources}")
        return 0
    try:
        data = json.loads(sources.read_text(encoding="utf-8"))
        if args.remote:
            token, tags = os.environ.get("GITHUB_TOKEN") or None, {}
            rows = [check_source_remote(src, tags, token) for src in data.get("sources", [])]
        else:
            rows = [check_source(src, cache_root) for src in data.get("sources", [])]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"NO-SOURCES {sources} (unreadable: {exc})")
        return 0
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            print(row["line"])
    return 1 if args.fail_on_drift and any(row["status"] == "DRIFT" for row in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
