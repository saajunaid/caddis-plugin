"""Stop hook: write this session's state file, and nothing else.

The same script also runs on `SessionEnd` (hooks.json). There it writes only an `<id>.ended`
marker next to the state file, so the SessionStart live-peer warning does not call a session that
was just closed or cleared (`/clear` starts a NEW session id) a live peer.

`Stop` fires at the end of EVERY assistant turn in EVERY session, so whatever runs here is a
per-turn tax. Since Phase 13 (2026-09-27) it has one job: render
`.caddis/session-state/<session-id>.md` from the tail of the transcript (see session_state.py).

Moved to `/handoff`, which runs once per session instead of once per turn:
  - the token/skill usage record (`session_state.py usage`) — it used to parse the whole
    transcript twice more and append a duplicate cumulative record every turn;
  - pruning the state folder (`session_state.py prune`);
  - the relay / knowledge-transfer reminder, which /handoff's own Step 1 already states.

Rules this file keeps:
  - Headless runs (CADDIS_HEADLESS, DOCKET_PLAN or DOCKET_BRANCH set and non-empty) are
    skipped entirely, so review and lane runs leave no state files.
  - No subprocess: the repo root is found by walking up to the nearest `.git`.
  - Fail-open: nothing here may raise or exit non-zero, and it prints nothing.

Cross-platform (pure Python, stdlib only).
"""
import json
import os
import sys
from datetime import datetime, timezone

# Shared artifact-dir resolution (scripts/claudster_config.py) with an inline fallback — a Stop
# hook must never die on an import problem.
try:
    _CFG_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
    if _CFG_SCRIPTS not in sys.path:
        sys.path.insert(0, _CFG_SCRIPTS)
    from claudster_config import artifact_root  # noqa: E402
except Exception:  # pragma: no cover — defensive
    def artifact_root(root):
        return os.path.join(str(root), ".caddis")

# Session-state capture. Optional by construction: if the module is missing or fails to
# import, the hook does nothing. A recovery aid that could break a turn would cost more than
# the sessions it saves.
try:
    from session_state import (  # noqa: E402
        extract_state, find_repo_root, read_carry, render, write_state,
    )
except Exception:  # pragma: no cover — defensive
    extract_state = None

_HEADLESS_MARKERS = ("CADDIS_HEADLESS", "DOCKET_PLAN", "DOCKET_BRANCH")


def _headless() -> bool:
    """True when any marker is set to a non-empty value. `CADDIS_HEADLESS=` is not headless."""
    return any(str(os.environ.get(name, "")).strip() for name in _HEADLESS_MARKERS)


def _read_input() -> dict:
    try:
        data = json.load(sys.stdin)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def main() -> None:
    data = _read_input()
    if _headless() or extract_state is None:
        return
    try:
        # Anchor to the repo the SESSION is operating in — the payload's cwd — not the hook
        # process's launch cwd. Mirrors guard.py.
        # The root is the nearest folder holding `.git` (a FILE in a worktree), found without
        # the `git rev-parse` subprocess this used to run every turn.
        root = find_repo_root(str(data.get("cwd") or os.getcwd()))
        # ONE FILE PER SESSION, not one shared name: two sessions routinely share a working
        # tree, and a flat name let whichever stopped last overwrite the other. Falls back to
        # the flat name when the payload carries no session id (the layout inject_relay.py
        # still reads). The flat file is shared, so it never seeds a carry.
        art_dir = str(artifact_root(root))
        sid = str(data.get("session_id", "") or "").strip()
        slug = "".join(c for c in sid if c.isalnum() or c in "-_")[:64]
        if str(data.get("hook_event_name", "") or "") == "SessionEnd":
            if slug and os.path.isdir(os.path.join(art_dir, "session-state")):
                with open(os.path.join(art_dir, "session-state", slug + ".ended"), "w",
                          encoding="utf-8") as marker:
                    marker.write(str(data.get("reason", "") or "ended") + "\n")
            return
        if slug:
            target = os.path.join(art_dir, "session-state", slug + ".md")
            carry = read_carry(target)
        else:
            target = os.path.join(art_dir, "session-state.md")
            carry = None
        state = extract_state(str(data.get("transcript_path", "") or ""), carry=carry)
        text = render(state, {
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "session": sid,
            "branch": state.get("branch", ""),
            "root": root,
        })
        write_state(target, text)
    except Exception:
        pass  # never let a recovery aid break the turn it is trying to protect


if __name__ == "__main__":
    main()
    sys.exit(0)
