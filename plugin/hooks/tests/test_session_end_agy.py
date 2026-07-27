"""Subprocess tests for the agy session_end hook (Stop -> <workspace>/.caddis/usage-log.jsonl).

The agy adapter parses agy's camelCase Stop payload, appends one usage-log record to the workspace's
artifact dir (write-where-the-repo-lives), stays SILENT on stdout (agy parses a Stop hook's stdout as a
`{"decision":…}` object), and never fails the turn.

Run: python -m pytest claude-harness/hooks/tests/test_session_end_agy.py -q
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent.parent / "agy" / "session_end_agy.py"


def _run(stdin: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=stdin, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )


def test_appends_usage_record_and_stays_silent(tmp_path):
    (tmp_path / ".caddis").mkdir()
    payload = json.dumps({
        "executionNum": 3, "terminationReason": "model_stop", "conversationId": "c1",
        "workspacePaths": [str(tmp_path)], "modelName": "gemini-3.6-flash",
    })
    r = _run(payload)
    assert r.returncode == 0
    assert r.stdout == ""  # no decision-shaped stdout — agy would try to parse it
    log = tmp_path / ".caddis" / "usage-log.jsonl"
    assert log.exists()
    rec = json.loads(log.read_text(encoding="utf-8").strip())
    assert rec["event"] == "session_end" and rec["agent"] == "agy"
    assert rec["conversationId"] == "c1" and rec["terminationReason"] == "model_stop"


def test_writes_where_the_repo_lives(tmp_path):
    # A repo still on .claudster gets its record there — no stray .caddis.
    (tmp_path / ".claudster").mkdir()
    _run(json.dumps({"workspacePaths": [str(tmp_path)], "conversationId": "c2"}))
    assert (tmp_path / ".claudster" / "usage-log.jsonl").exists()
    assert not (tmp_path / ".caddis").exists()


def test_never_fails_on_bad_input():
    assert _run("").returncode == 0
    assert _run("not json at all").returncode == 0
