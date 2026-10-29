"""UserPromptSubmit + PostToolUse — advise the session when context crosses 200k or 280k tokens.

Reads the latest main-thread usage from the session transcript (via scripts/caddis_ctx_report.py)
and emits a [caddis] advisory when the context level rises to warn (>= 200,000) or force (>= 280,000),
and on every UserPromptSubmit while at force. The text names one exact command: the checkpoint
(`caddis_handoff.py checkpoint --session-id <id>`), or the full handoff when that script is not
installed. A headless session (CADDIS_HEADLESS truthy) gets no warn text and a BLOCKED force text,
because headless sessions never checkpoint. An unattended session (~/.caddis/UNATTENDED under 16h old
or CADDIS_UNATTENDED truthy) is told to checkpoint and keep working, up to CADDIS_UNATTENDED_MAX_FORCE
(default 6) stop lines per session. Never blocks a tool and always exits 0.
"""
import json
import os
import sys
import time

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


def _unattended() -> bool:
    if _headless():
        return False
    if str(os.environ.get("CADDIS_UNATTENDED", "")).strip().lower() in _TRUTHY:
        return True
    marker = os.path.join(os.path.expanduser("~"), ".caddis", "UNATTENDED")
    try:
        return os.path.isfile(marker) and (time.time() - os.path.getmtime(marker) < 16 * 3600)
    except OSError:
        return False


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


def _message(
    level: str,
    n: int,
    warn: int,
    force: int,
    session_id: str,
    unattended: bool = False,
    unattended_count: int = 0,
    unattended_max: int = 6,
) -> str | None:
    if level == "force":
        first = f"[caddis] Context is {n:,} tokens (stop line {force:,}). "
        if _headless():
            return (
                first + "Headless: start no new card. Commit only finished cards. "
                f"Write BLOCKED context {n} and your state (cards done, commits, next card) "
                "where your prompt asks for the end status; a runner relay ends with the line "
                f"STATUS: BLOCKED context {n}. Do not run the checkpoint."
            )
        if unattended:
            if unattended_count > unattended_max:
                return (
                    first + f"Unattended limit: stop line {unattended_count} of {unattended_max} in this session. "
                    "Finish the current card, run /caddis:handoff, send a push notification with the next step, then stop."
                )
            script = _checkpoint_script()
            if script is None:
                return (
                    first + "Write the relay with /caddis:handoff, then keep working on the plan. "
                    "Do not stop and do not ask for /clear."
                )
            return (
                first + "Unattended: when no agent or background command runs, run the checkpoint now: "
                f'python "{script}" checkpoint --session-id {session_id}. '
                "Then keep working on the plan. Auto-compact will shorten the context and bring the relay back. "
                "Do not stop and do not ask for /clear."
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
    if unattended:
        if script is None:
            return (
                first + "Write the relay with /caddis:handoff, then keep working on the plan. "
                "Do not stop and do not ask for /clear."
            )
        return (
            first + f'Unattended: at the next card end, run the checkpoint: python "{script}" checkpoint --session-id {session_id}. '
            "Then keep working on the plan. Do not stop and do not ask for /clear."
        )
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

        risen = _LEVEL_RANK[level] > _LEVEL_RANK[stored_level]
        should_emit = (
            risen
            or (level == "force" and hook_event_name == "UserPromptSubmit")
        )
        if not should_emit:
            return

        unattended = _unattended()
        unattended_max = int(os.environ.get("CADDIS_UNATTENDED_MAX_FORCE", 6))
        unattended_count = 0
        if unattended and level == "force":
            count_file = os.path.join(sessions_dir, f"{session_id}.unattended")
            try:
                with open(count_file, encoding="utf-8") as fh:
                    unattended_count = int(fh.read().strip())
            except (OSError, ValueError):
                unattended_count = 0
            if risen:
                unattended_count += 1
                try:
                    os.makedirs(sessions_dir, exist_ok=True)
                    with open(count_file, "w", encoding="utf-8") as fh:
                        fh.write(str(unattended_count))
                except OSError:
                    pass

        msg = _message(
            level,
            n,
            WARN,
            FORCE,
            session_id,
            unattended=unattended,
            unattended_count=unattended_count,
            unattended_max=unattended_max,
        )
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
