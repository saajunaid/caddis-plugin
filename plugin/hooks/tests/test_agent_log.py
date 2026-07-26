"""Subprocess tests for agent_log.py (SubagentStop → .caddis/agent-log.jsonl).

The agent-eval runbook's Signal 1 (verdict distribution per subagent) needs an
always-on dispatch log. The hook must: append one JSONL line per SubagentStop,
extract the agent name + a verdict from the subagent transcript when available,
anchor to the SESSION repo (payload cwd, not process cwd), and never fail a turn.

Run: python -m pytest claude-harness/hooks/tests/test_agent_log.py -q
"""
import json
import subprocess
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent
AGENT_LOG = HOOKS_DIR / "agent_log.py"


def _run(cwd: Path, stdin: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(AGENT_LOG)],
        cwd=str(cwd),
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True)


def _transcript(path: Path, final_text: str) -> str:
    """Write a minimal subagent transcript JSONL whose last assistant message is final_text."""
    lines = [
        {"type": "user", "message": {"role": "user", "content": "do the task"}},
        {"message": {"role": "assistant", "content": [{"type": "text", "text": "working on it"}]}},
        {"message": {"role": "assistant", "content": [{"type": "text", "text": final_text}]}},
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    return str(path)


def _log_lines(root: Path) -> list[dict]:
    log = root / ".caddis" / "agent-log.jsonl"
    assert log.is_file(), "agent-log.jsonl not written"
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_appends_entry_with_agent_and_yaml_verdict(tmp_path):
    _git_init(tmp_path)
    tp = _transcript(tmp_path / "t.jsonl", "review:\n  verdict: changes-requested\n  blocking: []")
    payload = {"hook_event_name": "SubagentStop", "cwd": str(tmp_path),
               "agent_type": "code-reviewer", "agent_transcript_path": tp, "session_id": "s1"}
    r = _run(tmp_path, json.dumps(payload))
    assert r.returncode == 0, r.stderr
    rows = _log_lines(tmp_path)
    assert rows[-1]["agent"] == "code-reviewer"
    assert rows[-1]["verdict"] == "changes-requested"
    assert rows[-1]["ts"]


def test_review_marker_final_line_wins(tmp_path):
    _git_init(tmp_path)
    tp = _transcript(tmp_path / "t.jsonl", "All good.\n\nREVIEW: CLEAN")
    payload = {"hook_event_name": "SubagentStop", "cwd": str(tmp_path),
               "subagent_type": "cross-review", "agent_transcript_path": tp}
    assert _run(tmp_path, json.dumps(payload)).returncode == 0
    assert _log_lines(tmp_path)[-1]["verdict"] == "clean"


def test_no_transcript_still_logs_dispatch(tmp_path):
    _git_init(tmp_path)
    payload = {"hook_event_name": "SubagentStop", "cwd": str(tmp_path)}
    r = _run(tmp_path, json.dumps(payload))
    assert r.returncode == 0, r.stderr
    row = _log_lines(tmp_path)[-1]
    assert row["agent"] == "unknown"
    assert row["verdict"] == "none"


def test_garbage_stdin_never_fails(tmp_path):
    r = _run(tmp_path, "not json {{{")
    assert r.returncode == 0, r.stderr


def test_anchors_to_session_cwd_not_process_cwd(tmp_path):
    repo = tmp_path / "session-repo"
    elsewhere = tmp_path / "elsewhere"
    repo.mkdir(); elsewhere.mkdir()
    _git_init(repo)
    payload = {"hook_event_name": "SubagentStop", "cwd": str(repo), "agent_type": "tester"}
    r = _run(elsewhere, json.dumps(payload))  # process cwd is NOT the session repo
    assert r.returncode == 0, r.stderr
    assert _log_lines(repo)[-1]["agent"] == "tester"
    assert not (elsewhere / ".caddis" / "agent-log.jsonl").exists()


def test_appends_not_overwrites(tmp_path):
    _git_init(tmp_path)
    payload = json.dumps({"hook_event_name": "SubagentStop", "cwd": str(tmp_path), "agent_type": "debug"})
    _run(tmp_path, payload)
    _run(tmp_path, payload)
    assert len(_log_lines(tmp_path)) == 2
