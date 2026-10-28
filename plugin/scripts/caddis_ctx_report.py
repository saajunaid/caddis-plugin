#!/usr/bin/env python3
"""Report Claude Code session context token sizes from transcript JSONL files."""
from __future__ import annotations

import argparse
import json
import os
import statistics
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


WARN_TOKENS = 200_000
STOP_TOKENS = 280_000


def _is_checkpoint_call(rec: dict) -> bool:
    """True when rec is a main-thread assistant tool call that runs ``caddis_handoff.py checkpoint``.

    Only a shell ``command`` input counts: the hook text, a Read of a plan and a Write of a plan also
    hold the command string.
    """
    msg = rec.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(content, list):
        return False
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "tool_use":
            continue
        inp = item.get("input")
        command = inp.get("command") if isinstance(inp, dict) else None
        if isinstance(command, str) and "caddis_handoff.py" in command and "checkpoint" in command:
            return True
    return False


def obey_events(path: Path | str) -> tuple[list[int], list[int]]:
    """Return (series, checkpoint_positions) for the main thread.

    A checkpoint position is the number of usage records seen before that checkpoint call.
    Sidechain records never count.
    """
    series: list[int] = []
    checkpoints: list[int] = []
    seen_ids: set[str] = set()
    try:
        with Path(path).open(encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if "caddis_handoff.py" not in line and '"usage"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if not isinstance(rec, dict) or rec.get("isSidechain"):
                    continue
                if "caddis_handoff.py" in line and _is_checkpoint_call(rec):
                    checkpoints.append(len(series))
                msg = rec.get("message")
                usage = msg.get("usage") if isinstance(msg, dict) else None
                if not isinstance(usage, dict) or context_tokens(usage) == 0:
                    continue
                msg_id = msg.get("id")
                if msg_id is not None:
                    if msg_id in seen_ids:
                        continue
                    seen_ids.add(msg_id)
                series.append(context_tokens(usage))
    except OSError:
        return [], []
    return series, checkpoints


def obey_summary(sessions: Sequence[tuple[list[int], list[int]]]) -> dict[str, int]:
    """Count how sessions that crossed the warn line acted on it."""
    crossed = ran = passed = 0
    calls_to_checkpoint: list[int] = []
    for series, checkpoints in sessions:
        first_warn = next((i for i, n in enumerate(series) if n >= WARN_TOKENS), None)
        if first_warn is None:
            continue
        crossed += 1
        after = [c for c in checkpoints if c > first_warn]
        limit = after[0] if after else len(series)
        if after:
            ran += 1
            calls_to_checkpoint.append(after[0] - first_warn)
        if any(n >= STOP_TOKENS for n in series[:limit]):
            passed += 1
    return {
        "crossed_warn": crossed,
        "ran_checkpoint": ran,
        "median_calls_to_checkpoint": int(statistics.median(calls_to_checkpoint)) if calls_to_checkpoint else 0,
        "passed_280k_without_checkpoint": passed,
    }


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
    parser.add_argument("mode", choices=("peak", "first", "resume", "calls", "obey"))
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
        print(f"over_280k: {sum(1 for x in peaks if x > 280_000)}")
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

    if args.mode == "calls":
        sessions = 0
        calls: list[int] = []
        for f in files:
            series = session_series(f)
            if series:
                sessions += 1
                calls.extend(series)
        print(f"sessions: {sessions}")
        print(f"calls: {len(calls)}")
        print(f"mean_context: {round(statistics.fmean(calls)) if calls else 0}")
        print(f"median_context: {int(statistics.median(calls)) if calls else 0}")
        print(f"calls_over_200k: {sum(1 for x in calls if x > WARN_TOKENS)}")
        print(f"calls_over_280k: {sum(1 for x in calls if x > STOP_TOKENS)}")
        return 0

    if args.mode == "obey":
        for key, value in obey_summary([obey_events(f) for f in files]).items():
            print(f"{key}: {value}")
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
