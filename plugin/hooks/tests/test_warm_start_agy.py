"""Subprocess tests for the agy warm-start hook (PreInvocation -> {"injectSteps":[…]}).

agy has no SessionStart, so the adapter fires on PreInvocation and acts ONLY on invocationNum == 0
(agy's first invocation is 0-indexed, confirmed via a live-fire session against the real `agy` binary
2026-07-30 — the original assumption of invocationNum == 1 was WRONG and silently dropped every
warm-start injection; see .caddis/plans/agy-hooks-port.md step 5). It reads the workspace relay
(.caddis, per-branch preferred), trims it, and injects it as an ephemeralMessage. Everything else —
later invocations, no relay, bad input — must emit nothing and exit 0.

Run: python -m pytest claude-harness/hooks/tests/test_warm_start_agy.py -q
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent.parent / "agy" / "warm_start_agy.py"


_HEADLESS_MARKERS = ("CADDIS_HEADLESS", "DOCKET_PLAN", "DOCKET_BRANCH")
RELAY_MARKER = "=== session-context: relay.md"


def _run(stdin: str, env: dict | None = None) -> subprocess.CompletedProcess:
    # Scrubbed by default: the relay is suppressed for headless sessions, and this suite must
    # pass when run FROM one.
    child_env = {k: v for k, v in os.environ.items() if k not in _HEADLESS_MARKERS}
    child_env.update(env or {})
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=stdin, capture_output=True, text=True, encoding="utf-8", timeout=30,
        env=child_env,
    )


def _payload(ws, invocation=0):
    return json.dumps({"invocationNum": invocation, "initialNumSteps": 2,
                       "conversationId": "c1", "workspacePaths": [str(ws)]})


def _message(result: subprocess.CompletedProcess):
    out = result.stdout.strip()
    if not out:
        return None
    return json.loads(out)["injectSteps"][0]["ephemeralMessage"]


def test_first_invocation_injects_the_relay(tmp_path):
    (tmp_path / ".caddis").mkdir()
    (tmp_path / ".caddis" / "relay.md").write_text("# Relay\nNext step: ship the thing.", encoding="utf-8")
    r = _run(_payload(tmp_path))
    assert r.returncode == 0
    msg = _message(r)
    assert "ship the thing" in msg
    assert msg.startswith(RELAY_MARKER)


def test_relay_is_framed_as_background_state_not_a_task(tmp_path):
    """Same frame as the Claude Code hook: injected before the prompt, the relay was being
    executed as the session's first task. It has to announce that it is state."""
    (tmp_path / ".caddis").mkdir()
    (tmp_path / ".caddis" / "relay.md").write_text(
        "# Relay\n## Next step (exact)\nDelete the old table.", encoding="utf-8")
    msg = _message(_run(_payload(tmp_path)))
    assert "NOT A TASK" in msg
    assert "read before acting" not in msg
    assert msg.rstrip().endswith("=== end session-context ===")
    assert "Delete the old table." in msg


def test_headless_session_gets_no_relay(tmp_path):
    (tmp_path / ".caddis").mkdir()
    (tmp_path / ".caddis" / "relay.md").write_text("RELAY-BODY", encoding="utf-8")
    assert _run(_payload(tmp_path), env={"CADDIS_HEADLESS": "1"}).stdout.strip() == ""


def test_legacy_artifact_dir_no_longer_read(tmp_path):
    # Phase F dropped the .claudster/ read-fallback — a relay living ONLY there is invisible.
    (tmp_path / ".claudster").mkdir()
    (tmp_path / ".claudster" / "relay.md").write_text("legacy relay body", encoding="utf-8")
    assert _run(_payload(tmp_path)).stdout.strip() == ""


def test_later_invocation_injects_nothing(tmp_path):
    # invocation=1 here is the SECOND turn (agy's first is 0) -- also the exact regression case
    # for the live-fire bug found 2026-07-30 (the original code checked invocationNum == 1).
    (tmp_path / ".caddis").mkdir()
    (tmp_path / ".caddis" / "relay.md").write_text("# Relay\nbody", encoding="utf-8")
    r = _run(_payload(tmp_path, invocation=1))
    assert r.returncode == 0 and r.stdout.strip() == ""


def test_no_relay_injects_nothing(tmp_path):
    (tmp_path / ".caddis").mkdir()
    r = _run(_payload(tmp_path))
    assert r.returncode == 0 and r.stdout.strip() == ""


def test_empty_relay_injects_nothing(tmp_path):
    (tmp_path / ".caddis").mkdir()
    (tmp_path / ".caddis" / "relay.md").write_text("   \n\n", encoding="utf-8")
    assert _run(_payload(tmp_path)).stdout.strip() == ""


def test_long_relay_is_trimmed(tmp_path):
    (tmp_path / ".caddis").mkdir()
    body = ["# Relay", "", "## Done"] + [f"- bullet {i}" for i in range(200)]
    body += ["", "## Next step", "do the next thing", "", "## Read first on resume", "- the plan"]
    (tmp_path / ".caddis" / "relay.md").write_text("\n".join(body), encoding="utf-8")
    msg = _message(_run(_payload(tmp_path)))
    assert "bullets omitted" in msg
    assert "do the next thing" in msg and "- the plan" in msg  # the sections that matter survive
    assert "bullet 150" not in msg


@pytest.mark.parametrize("stdin", [
    "",
    "not json at all",
    "[]",
    '{"invocationNum": "zero"}',
    '{"invocationNum": 0}',                              # no workspacePaths
    '{"invocationNum": 0, "workspacePaths": []}',
    '{"invocationNum": 0, "workspacePaths": "nope"}',
    '{"initialNumSteps": 2}',                            # no invocationNum
])
def test_malformed_input_fails_open(stdin):
    r = _run(stdin)
    assert r.returncode == 0, f"must never exit non-zero: {stdin!r}"
    assert r.stdout.strip() == "", f"must stay silent: {stdin!r}"
