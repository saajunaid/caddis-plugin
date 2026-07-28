#!/usr/bin/env python3
"""caddis `session_end` hook for agy (Antigravity) — Stop event.

Ports claude-harness/hooks/session_end.py to agy's contract. On Stop, appends ONE session-end record to
the workspace's usage log (`<workspace>/.caddis/usage-log.jsonl`). Self-contained (the agy bundle does not
ship claudster_config.py), stdlib-only, and fully defensive:
a Stop hook must never fail the turn, and must not print a non-JSON line to stdout (agy parses Stop-hook
stdout as a `{"decision":…}` object — a stray string trips its "unsupported hook decision" path). So this
does a pure side effect and prints NOTHING.

agy Stop stdin (camelCase protojson):
  {"executionNum":N, "terminationReason":"model_stop|max_steps_exceeded|error", "error":"",
   "fullyIdle":true, "conversationId":"…", "workspacePaths":["…"], "transcriptPath":"…", "modelName":"…"}
"""
import json
import os
import sys
from datetime import datetime, timezone


def _artifact_root(root: str) -> str:
    return os.path.join(str(root), ".caddis")


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    try:
        workspaces = data.get("workspacePaths") or []
        workspace = workspaces[0] if workspaces else os.getcwd()
        art = _artifact_root(workspace)
        os.makedirs(art, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": "session_end",
            "agent": "agy",
            "conversationId": data.get("conversationId"),
            "executionNum": data.get("executionNum"),
            "terminationReason": data.get("terminationReason"),
            "model": data.get("modelName"),
        }
        with open(os.path.join(art, "usage-log.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:
        pass  # never fail the turn
    # No stdout: agy interprets a Stop hook's stdout as a decision object.


if __name__ == "__main__":
    main()
