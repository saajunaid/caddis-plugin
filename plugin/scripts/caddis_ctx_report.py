#!/usr/bin/env python3
"""Report Claude Code session context token sizes from transcript JSONL files."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Sequence


def context_tokens(usage: dict) -> int:
    """Return total input context tokens from a usage dictionary."""
    if not isinstance(usage, dict):
        return 0
    return int(
        (usage.get("input_tokens") or 0)
        + (usage.get("cache_read_input_tokens") or 0)
        + (usage.get("cache_creation_input_tokens") or 0)
    )


def last_context(path: Path | str, tail_bytes: int = 262_144) -> int | None:
    """Read the last tail_bytes of path and return the latest main-thread context size."""
    p = Path(path)
    try:
        size = p.stat().st_size
        with p.open("rb") as fh:
            fh.seek(max(0, size - tail_bytes))
            # Split on newline only: splitlines() also splits on U+2028, which JSON strings may hold raw.
            lines = fh.read().decode("utf-8", errors="ignore").split("\n")
    except OSError:
        return None

    for line in reversed(lines):
        if '"usage"' not in line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if not isinstance(rec, dict) or rec.get("isSidechain"):
            continue
        msg = rec.get("message")
        usage = msg.get("usage") if isinstance(msg, dict) else None
        # A synthetic record (an API error, for example) has all-zero usage: it says nothing about size.
        if isinstance(usage, dict) and context_tokens(usage) > 0:
            return context_tokens(usage)
    return None


def _has_true_sidechain(line: str) -> bool:
    return '"isSidechain":true' in line or '"isSidechain": true' in line


def session_series(path: Path | str) -> list[int]:
    """Return context size per distinct message.id in file order for the main thread."""
    p = Path(path)
    series: list[int] = []
    seen_ids: set[str] = set()
    try:
        with p.open(encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if '"usage"' not in line and not _has_true_sidechain(line):
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if not isinstance(rec, dict):
                    continue
                if rec.get("isSidechain"):
                    break
                msg = rec.get("message")
                if not isinstance(msg, dict):
                    continue
                usage = msg.get("usage")
                if not isinstance(usage, dict) or context_tokens(usage) == 0:
                    continue
                msg_id = msg.get("id")
                if msg_id is not None:
                    if msg_id in seen_ids:
                        continue
                    seen_ids.add(msg_id)
                series.append(context_tokens(usage))
    except OSError:
        return []
    return series


def _has_relay_before_first_usage(path: Path) -> bool:
    """Return True if path contains 'Workstream index' or 'relay.md' before the first usage line."""
    found = False
    try:
        with path.open(encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if '"usage"' in line or _has_true_sidechain(line):
                    try:
                        rec = json.loads(line)
                    except Exception:
                        rec = None
                    if isinstance(rec, dict):
                        if rec.get("isSidechain"):
                            return False
                        msg = rec.get("message")
                        if isinstance(msg, dict) and isinstance(msg.get("usage"), dict):
                            return found
                if "Workstream index" in line or "relay.md" in line:
                    found = True
    except OSError:
        return False
    return False


def _percentile(values: Sequence[int], p: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[int(p * (len(ordered) - 1))]


def _iter_transcripts(root: Path, days: float) -> list[Path]:
    if not root.exists():
        return []
    cutoff = time.time() - days * 86400
    candidates = [*root.glob("*.jsonl"), *root.glob("*/*.jsonl")]
    result: list[Path] = []
    for path in candidates:
        try:
            if path.is_file() and path.stat().st_mtime >= cutoff:
                result.append(path)
        except OSError:
            continue
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report Claude Code session context sizes.")
    parser.add_argument("mode", choices=("peak", "first", "resume"))
    parser.add_argument("--days", type=float, default=14.0)
    parser.add_argument(
        "--root",
        default=os.path.join(os.path.expanduser("~"), ".claude", "projects"),
    )
    args = parser.parse_args(argv)
    root = Path(os.path.expanduser(args.root))
    files = _iter_transcripts(root, args.days)

    if args.mode == "peak":
        peaks: list[int] = []
        for f in files:
            series = session_series(f)
            if series:
                peaks.append(max(series))
        peaks.sort()
        print(f"sessions: {len(peaks)}")
        print(f"median: {_percentile(peaks, 0.5)}")
        print(f"p75: {_percentile(peaks, 0.75)}")
        print(f"p90: {_percentile(peaks, 0.9)}")
        print(f"max: {peaks[-1] if peaks else 0}")
        print(f"over_350k: {sum(1 for x in peaks if x > 350_000)}")
        print(f"over_500k: {sum(1 for x in peaks if x > 500_000)}")
        return 0

    if args.mode == "first":
        firsts: list[int] = []
        for f in files:
            series = session_series(f)
            if series:
                firsts.append(series[0])
        firsts.sort()
        print(f"sessions: {len(firsts)}")
        print(f"median: {_percentile(firsts, 0.5)}")
        print(f"p90: {_percentile(firsts, 0.9)}")
        return 0

    resumed_series: list[list[int]] = []
    for f in files:
        if not _has_relay_before_first_usage(f):
            continue
        series = session_series(f)
        if series:
            resumed_series.append(series)

    for call_num in (1, 5, 10):
        vals = [s[call_num - 1] for s in resumed_series if len(s) >= call_num]
        vals.sort()
        print(f"call_{call_num}_sessions: {len(vals)}")
        print(f"call_{call_num}_median: {_percentile(vals, 0.5)}")
        print(f"call_{call_num}_p90: {_percentile(vals, 0.9)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
