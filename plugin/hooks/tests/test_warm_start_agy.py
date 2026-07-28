"""Subprocess tests for the agy warm-start hook (PreInvocation -> {"injectSteps":[…]}).

agy has no SessionStart, so the adapter fires on PreInvocation and acts ONLY on invocationNum == 1.
It reads the workspace relay (.caddis, per-branch preferred), trims it, and injects it as an
ephemeralMessage. Everything else — later invocations, no relay, bad input — must emit nothing and
exit 0.

Run: python -m pytest claude-harness/hooks/tests/test_warm_start_agy.py -q
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent.parent / "agy" / "warm_start_agy.py"


def _run(stdin: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=stdin, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )


def _payload(ws, invocation=1):
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
    assert msg.startswith("=== relay.md")


def test_legacy_artifact_dir_no_longer_read(tmp_path):
    # Phase F dropped the .claudster/ read-fallback — a relay living ONLY there is invisible.
    (tmp_path / ".claudster").mkdir()
    (tmp_path / ".claudster" / "relay.md").write_text("legacy relay body", encoding="utf-8")
    assert _run(_payload(tmp_path)).stdout.strip() == ""


def test_later_invocation_injects_nothing(tmp_path):
    (tmp_path / ".caddis").mkdir()
    (tmp_path / ".caddis" / "relay.md").write_text("# Relay\nbody", encoding="utf-8")
    r = _run(_payload(tmp_path, invocation=2))
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
    '{"invocationNum": "one"}',
    '{"invocationNum": 1}',                              # no workspacePaths
    '{"invocationNum": 1, "workspacePaths": []}',
    '{"invocationNum": 1, "workspacePaths": "nope"}',
    '{"initialNumSteps": 2}',                            # no invocationNum
])
def test_malformed_input_fails_open(stdin):
    r = _run(stdin)
    assert r.returncode == 0, f"must never exit non-zero: {stdin!r}"
    assert r.stdout.strip() == "", f"must stay silent: {stdin!r}"
