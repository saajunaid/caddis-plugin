#!/usr/bin/env python3
"""caddis `session_end` hook for agy (Antigravity) — Stop event.

Ports claude-harness/hooks/session_end.py to agy's contract. On Stop, appends ONE session-end record to
the workspace's usage log (`<workspace>/.caddis/usage-log.jsonl`). Self-contained (the agy bundle does not
ship claudster_config.py), stdlib-only, and fully defensive:
a Stop hook must never fail the turn, and must not print a non-JSON line to stdout (agy parses Stop-hook
stdout as a `{"decision":…}` object — a stray string trips its "unsupported hook decision" path). So this
does a pure side effect and prints NOTHING: empty stdout is agy's "no decision", while
`{"decision": "continue"}` would stop the session from ending.

Headless runs (CADDIS_HEADLESS, DOCKET_PLAN or DOCKET_BRANCH set and non-empty) are skipped, as in
the Claude Stop hook, so review and lane runs leave no files. The record is one append with no
transcript read, so it stays here rather than moving to /handoff (Phase 13).

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



def _hook_note(feature, exc, root=None):
    """Record a swallowed failure in the caddis hook ledger. Never raises, never prints.

    agy hooks ship FLAT at the plugin root while hook_log.py ships under scripts/, and in
    the source repo this file sits in claude-harness/agy/ with hook_log.py one level up in
    claude-harness/scripts/. Try both layouts.
    """
    try:
        _here = os.path.dirname(os.path.abspath(__file__))
        for _cand in (os.path.join(_here, "scripts"),
                      os.path.join(os.path.dirname(_here), "scripts")):
            if os.path.isdir(_cand) and _cand not in sys.path:
                sys.path.insert(0, _cand)
        import hook_log as _hl  # noqa: E402
        _hl.record(os.path.basename(__file__).replace(".py", ""), feature, exc, root)
    except Exception:
        pass


def _workspace_roots(data):
    """Every workspace root in the payload, as a list. Empty when the payload has none.

    agy sends `workspacePaths` as a LIST. All three caddis agy hooks used to read
    `workspacePaths[0]` and treat it as "the workspace" — silently, with no signal that a
    choice had been made. In a single-root workspace that is correct and the behaviour here
    is unchanged. In a MULTI-root workspace it is a coin toss: the hook acts on the first
    root regardless of which one the session is actually working in.

    Nothing on this machine is multi-root today, so this has never fired. It is a live trap
    for exactly the multi-repo workspaces the leakage investigation was about, which is why
    each caller below now handles the list rather than assuming its first element.
    """
    roots = data.get("workspacePaths") if isinstance(data, dict) else None
    if not isinstance(roots, list):
        return []
    return [str(r) for r in roots if isinstance(r, (str, bytes)) and str(r).strip()]

_HEADLESS_MARKERS = ("CADDIS_HEADLESS", "DOCKET_PLAN", "DOCKET_BRANCH")


def _headless() -> bool:
    """True when any marker is set to a non-empty value. `CADDIS_HEADLESS=` is not headless."""
    return any(str(os.environ.get(name, "")).strip() for name in _HEADLESS_MARKERS)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    if _headless():
        return
    try:
        roots = _workspace_roots(data) or [os.getcwd()]
        # Write the record to every root that ALREADY has a .caddis dir, rather than to
        # whichever root happened to be first. A multi-root session's usage belongs to each
        # repo that participates in it, and creating .caddis in a repo that never opted in
        # would be caddis littering someone else's tree.
        targets = [_artifact_root(r) for r in roots if os.path.isdir(_artifact_root(r))]
        if not targets:
            targets = [_artifact_root(roots[0])]  # single-root default: unchanged behaviour
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": "session_end",
            "agent": "agy",
            "conversationId": data.get("conversationId"),
            "executionNum": data.get("executionNum"),
            "terminationReason": data.get("terminationReason"),
            "model": data.get("modelName"),
        }
        for art in targets:
            os.makedirs(art, exist_ok=True)
            with open(os.path.join(art, "usage-log.jsonl"), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
    except Exception as _exc:
        _hook_note("agy usage-log write", _exc)  # never fail the turn
    # No stdout: agy interprets a Stop hook's stdout as a decision object.


if __name__ == "__main__":
    main()
