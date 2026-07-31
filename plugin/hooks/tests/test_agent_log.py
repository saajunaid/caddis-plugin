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


def test_bolded_verdict_line_still_recognized(tmp_path):
    # Regression case found live 2026-07-30: the tester agent phrased its verdict as
    # "**Verdict: changes-requested**" (bolded prose, capital V) instead of a plain yaml-style
    # `verdict:` line -- the original regex required the line to start with exactly "verdict:"
    # and silently logged "none" for a real, correct verdict.
    _git_init(tmp_path)
    tp = _transcript(tmp_path / "t.jsonl", "## Findings\n\n**Verdict: changes-requested**\n\nSome prose.")
    payload = {"hook_event_name": "SubagentStop", "cwd": str(tmp_path),
               "agent_type": "tester", "agent_transcript_path": tp}
    assert _run(tmp_path, json.dumps(payload)).returncode == 0
    assert _log_lines(tmp_path)[-1]["verdict"] == "changes-requested"


def test_midsentence_verdict_mention_does_not_false_positive(tmp_path):
    # A verdict word appearing mid-sentence, not as the start of its own line, must not be
    # treated as a declaration -- the fix widens what counts as the LABEL (markdown emphasis)
    # without widening WHERE it can appear (still anchored to line-start via re.M).
    _git_init(tmp_path)
    tp = _transcript(tmp_path / "t.jsonl", "This depends on the verdict: reached earlier in the review.")
    payload = {"hook_event_name": "SubagentStop", "cwd": str(tmp_path),
               "agent_type": "tester", "agent_transcript_path": tp}
    assert _run(tmp_path, json.dumps(payload)).returncode == 0
    assert _log_lines(tmp_path)[-1]["verdict"] == "none"


def test_review_marker_final_line_wins(tmp_path):
    _git_init(tmp_path)
    tp = _transcript(tmp_path / "t.jsonl", "All good.\n\nREVIEW: CLEAN")
    payload = {"hook_event_name": "SubagentStop", "cwd": str(tmp_path),
               "subagent_type": "cross-review", "agent_transcript_path": tp}
    assert _run(tmp_path, json.dumps(payload)).returncode == 0
    assert _log_lines(tmp_path)[-1]["verdict"] == "clean"


def test_missing_agent_type_recovered_from_meta_json_sidecar(tmp_path):
    # Regression case found live 2026-07-30: SubagentStop's payload sometimes omits
    # agent_type/subagent_type/agent_name entirely, and the code used to fall straight to
    # the meaningless agent_id hash. The subagent's own <transcript>.meta.json sidecar
    # reliably carries agentType -- confirmed against real Claude Code output.
    _git_init(tmp_path)
    tp = _transcript(tmp_path / "agent-abc123.jsonl", "done")
    (tmp_path / "agent-abc123.meta.json").write_text(
        json.dumps({"agentType": "caddis:codebase-audit", "description": "x"}), encoding="utf-8"
    )
    payload = {
        "hook_event_name": "SubagentStop", "cwd": str(tmp_path),
        "agent_id": "abc123", "agent_transcript_path": tp,
    }
    r = _run(tmp_path, json.dumps(payload))
    assert r.returncode == 0, r.stderr
    assert _log_lines(tmp_path)[-1]["agent"] == "caddis:codebase-audit"


def test_no_meta_sidecar_falls_back_to_agent_id(tmp_path):
    # No agent_type in the payload AND no .meta.json sidecar on disk -- still logs
    # *something* (the raw id) rather than silently dropping the dispatch.
    _git_init(tmp_path)
    tp = _transcript(tmp_path / "agent-nometas.jsonl", "done")
    payload = {
        "hook_event_name": "SubagentStop", "cwd": str(tmp_path),
        "agent_id": "nometas", "agent_transcript_path": tp,
    }
    r = _run(tmp_path, json.dumps(payload))
    assert r.returncode == 0, r.stderr
    assert _log_lines(tmp_path)[-1]["agent"] == "nometas"


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
