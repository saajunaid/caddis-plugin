"""UserPromptSubmit + PostToolUse — advise the session when context crosses 200k or 350k tokens.

Reads the latest main-thread usage from the session transcript (via scripts/caddis_ctx_report.py)
and emits a [caddis] advisory when the context level rises to warn (>= 200,000) or force (>= 350,000),
and on every UserPromptSubmit while at force. Never blocks a tool and always exits 0.
"""
import json
import os
import sys

_HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
for _cand in (
    os.path.join(os.path.dirname(_HOOKS_DIR), "scripts"),
    os.path.join(os.path.dirname(os.path.dirname(_HOOKS_DIR)), "scripts"),
):
    if os.path.isdir(_cand) and _cand not in sys.path:
        sys.path.insert(0, _cand)

_reconfig = getattr(sys.stdout, "reconfigure", None)
if _reconfig:
    try:
        _reconfig(encoding="utf-8")
    except Exception:
        pass

try:
    from caddis_ctx_report import last_context
except Exception:
    sys.exit(0)

_LEVEL_RANK = {"ok": 0, "warn": 1, "force": 2}


def main() -> None:
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            return
        session_id = str(data.get("session_id") or "").strip()
        transcript_path = str(data.get("transcript_path") or "").strip()
        hook_event_name = str(data.get("hook_event_name") or "").strip()
        if not session_id or not transcript_path or not hook_event_name:
            return
        if "/" in session_id or "\\" in session_id or session_id in (".", ".."):
            return

        WARN = int(os.environ.get("CADDIS_CTX_WARN", 200000))
        FORCE = int(os.environ.get("CADDIS_CTX_FORCE", 350000))

        n = last_context(transcript_path)
        if n is None:
            return

        if n >= FORCE:
            level = "force"
        elif n >= WARN:
            level = "warn"
        else:
            level = "ok"

        sessions_dir = os.path.join(os.path.expanduser("~"), ".caddis", "sessions")
        state_file = os.path.join(sessions_dir, f"{session_id}.ctxlevel")

        stored_level = "ok"
        try:
            with open(state_file, encoding="utf-8") as fh:
                raw = fh.read().strip()
            if raw in _LEVEL_RANK:
                stored_level = raw
        except OSError:
            pass

        try:
            os.makedirs(sessions_dir, exist_ok=True)
            with open(state_file, "w", encoding="utf-8") as fh:
                fh.write(level)
        except OSError:
            pass

        should_emit = (
            _LEVEL_RANK[level] > _LEVEL_RANK[stored_level]
            or (level == "force" and hook_event_name == "UserPromptSubmit")
        )
        if not should_emit:
            return

        if level == "force":
            msg = (
                f"[caddis] Context is {n:,} tokens (limit {FORCE:,}). "
                "Start no new work. Write the handoff now, then /clear and resume from the relay."
            )
        else:
            msg = (
                f"[caddis] Context is {n:,} tokens (warn at {WARN:,}). "
                "Finish the current step. At the next phase end, write the handoff and restart with /clear."
            )

        out = {
            "systemMessage": msg,
            "hookSpecificOutput": {
                "hookEventName": hook_event_name,
                "additionalContext": msg,
            },
        }
        print(json.dumps(out), flush=True)
    except Exception:
        pass


if __name__ == "__main__":
    main()
    sys.exit(0)
