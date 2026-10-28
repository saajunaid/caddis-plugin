"""UserPromptSubmit + PostToolUse — advise the session when context crosses 200k or 280k tokens.

Reads the latest main-thread usage from the session transcript (via scripts/caddis_ctx_report.py)
and emits a [caddis] advisory when the context level rises to warn (>= 200,000) or force (>= 280,000),
and on every UserPromptSubmit while at force. The text names one exact command: the checkpoint
(`caddis_handoff.py checkpoint --session-id <id>`), or the full handoff when that script is not
installed. A headless session (CADDIS_HEADLESS truthy) gets no warn text and a BLOCKED force text,
because headless sessions never checkpoint. Never blocks a tool and always exits 0.
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
_TRUTHY = {"1", "true", "yes", "on"}


def _headless() -> bool:
    return str(os.environ.get("CADDIS_HEADLESS", "")).strip().lower() in _TRUTHY


def _checkpoint_script() -> str | None:
    """First existing caddis_handoff.py: <hooks>/../scripts (plugin), then <hooks>/../../scripts (source tree)."""
    for folder in (
        os.path.join(os.path.dirname(_HOOKS_DIR), "scripts"),
        os.path.join(os.path.dirname(os.path.dirname(_HOOKS_DIR)), "scripts"),
    ):
        path = os.path.join(folder, "caddis_handoff.py")
        if os.path.isfile(path):
            return path
    return None


def _message(level: str, n: int, warn: int, force: int, session_id: str) -> str | None:
    if level == "force":
        first = f"[caddis] Context is {n:,} tokens (stop line {force:,}). "
        if _headless():
            return (
                first + "Headless: start no new card. Commit only finished cards. "
                f"End with BLOCKED context {n:,} and your state (cards done, commits, next card). "
                "Do not write a handoff."
            )
        script = _checkpoint_script()
        if script is None:
            return first + "Write the handoff (/caddis:handoff), then ask for /clear."
        return (
            first + "Start no new card. When no agent or background command runs, run the checkpoint now: "
            f'python "{script}" checkpoint --session-id {session_id}. Then ask for /clear.'
        )
    if _headless():
        return None
    first = f"[caddis] Context is {n:,} tokens (warn at {warn:,}). "
    script = _checkpoint_script()
    if script is None:
        return first + "Write the handoff (/caddis:handoff), then ask for /clear."
    return (
        first + f'At the next card end, run the checkpoint: python "{script}" checkpoint --session-id {session_id}. '
        "If 1 card or less is left in the phase, finish the phase and run /caddis:handoff instead."
    )


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
        FORCE = int(os.environ.get("CADDIS_CTX_FORCE", 280000))

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

        msg = _message(level, n, WARN, FORCE, session_id)
        if not msg:
            return

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
