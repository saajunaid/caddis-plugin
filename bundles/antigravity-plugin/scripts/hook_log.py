"""Throttled error ledger for caddis hooks — so a broken hook is not a silent one.

The problem
-----------
caddis hooks fail open, which is right: a SessionStart hook that raises would break
the session, and a PreToolUse hook that raises would break the tool call. The way
they fail open is ``except Exception: pass``, which is wrong: a hook that is broken
and a hook that had nothing to say produce the identical result — nothing.

There were 20 such swallows across 6 hook files. Each one guards a named feature.
When ``dream_memory``'s surface stops printing, nobody learns that it stopped; they
learn that they have not seen it lately, months later, if at all.

The fix keeps fail-open and adds a record. ``record()`` never raises, never prints,
and never blocks — if the ledger itself cannot be written, that is swallowed too.

Throttle
--------
One line per ``(hook, feature, error type)`` per day. A hook that fails on every
single tool call writes one line, not thousands. The ledger is a signal, not a trace.

Surfacing
---------
``summarise()`` returns a one-line summary of the last N days, or "" when clean.
``inject_relay.py`` prints it at SessionStart. That is the only place a user is
told; there is no second channel to ignore.
"""
from __future__ import annotations

import json
import os
import time

_ARTIFACT_DIR = ".caddis"
_LEDGER_NAME = "hook-errors.jsonl"
_MAX_LINES = 400  # ring-buffer cap; the ledger must never grow without bound


def _ledger_path(root: str | None) -> str | None:
    try:
        base = root or os.getcwd()
        d = os.path.join(base, _ARTIFACT_DIR)
        if not os.path.isdir(d):
            return None  # not a caddis project — nothing to write into, and that is fine
        return os.path.join(d, _LEDGER_NAME)
    except Exception:
        return None


def record(hook: str, feature: str, exc: BaseException, root: str | None = None) -> None:
    """Note that ``feature`` inside ``hook`` failed. Never raises, never prints.

    ``feature`` is the thing the user loses — "parked-stack surface", "relay read" —
    not the function name. The ledger is read by a human deciding whether to care.
    """
    try:
        path = _ledger_path(root)
        if path is None:
            return

        etype = type(exc).__name__
        # Truncate: an exception message can carry a path, a command, or a chunk of
        # file content. One line of context is enough to act on.
        emsg = str(exc)[:200]
        today = time.strftime("%Y-%m-%d")
        key = f"{hook}|{feature}|{etype}"

        lines: list[str] = []
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    lines = fh.read().splitlines()
            except Exception:
                lines = []

        for line in reversed(lines[-120:]):  # today's entries are at the tail
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("key") == key and str(rec.get("ts", ""))[:10] == today:
                return  # already recorded today — throttled

        lines.append(json.dumps({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "key": key,
            "hook": hook,
            "feature": feature,
            "error": etype,
            "message": emsg,
        }, ensure_ascii=False))

        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines[-_MAX_LINES:]) + "\n")
    except Exception:
        return  # the ledger must never be the thing that breaks a hook


def summarise(root: str | None = None, days: int = 7) -> str:
    """One line naming what has been failing, or "" when there is nothing to say."""
    try:
        path = _ledger_path(root)
        if path is None or not os.path.isfile(path):
            return ""

        cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))
        counts: dict[str, int] = {}
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if str(rec.get("ts", ""))[:10] < cutoff:
                    continue
                label = f"{rec.get('hook', '?')}/{rec.get('feature', '?')}"
                counts[label] = counts.get(label, 0) + 1

        if not counts:
            return ""
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        shown = ", ".join(f"{k} x{v}" for k, v in ranked[:4])
        more = f" (+{len(ranked) - 4} more)" if len(ranked) > 4 else ""
        return (f"[caddis] hook errors in the last {days} days: {shown}{more} — "
                f"see {_ARTIFACT_DIR}/{_LEDGER_NAME}")
    except Exception:
        return ""


def main() -> int:
    """``python hook_log.py [root]`` prints the ledger, newest last. For eyeballing."""
    import sys
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    path = _ledger_path(root)
    if path is None or not os.path.isfile(path):
        print(f"no hook-error ledger at {root}/{_ARTIFACT_DIR}/{_LEDGER_NAME} — nothing has failed")
        return 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            print(f"{rec.get('ts', '?'):<20} {rec.get('hook', '?')}/{rec.get('feature', '?'):<28} "
                  f"{rec.get('error', '?')}: {rec.get('message', '')}")
    summary = summarise(root)
    if summary:
        print("\n" + summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
