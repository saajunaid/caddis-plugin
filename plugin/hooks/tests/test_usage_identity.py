"""Identity-logging tests for session_end.py (Stop → .caddis/usage-log.jsonl).

V15: usage-log.jsonl carried token accounting only — no skill/command identity — so the
pruning question (Phase 12) was unanswerable from evidence. Phase 11 records which skills
and commands actually fire, at the Stop hook (where the per-session record is born and the
transcript is already read). Fail-open, privacy-safe: names only, never arguments.

Run: python -m pytest claude-harness/hooks/tests/test_usage_identity.py -q
"""
import json
import subprocess
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent
SESSION_END = HOOKS_DIR / "session_end.py"


def _assistant(skill: str | None = None, model: str = "claude-sonnet-5") -> dict:
    """An assistant transcript event. Carries a Skill tool_use when `skill` is given and
    always carries a usage block so the token summary is non-None (the realistic path)."""
    content = [{"type": "text", "text": "ok"}]
    if skill:
        content.append({"type": "tool_use", "name": "Skill", "input": {"skill": skill}})
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "model": model,
            "content": content,
            "usage": {"input_tokens": 12, "output_tokens": 8},
        },
    }


def _user_command(command_name: str) -> dict:
    """A user transcript event carrying a slash-command invocation marker.

    Real transcripts embed `<command-name>/plugin:cmd</command-name>` in the user-message
    text (confirmed across the fleet 2026-08-05). This is the structured, reliable signal
    for a command invocation — no arguments are recorded.
    """
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "text",
                         "text": f"<command-name>{command_name}</command-name>\n"
                                 f"<command-message>{command_name.lstrip('/')}</command-message>"}],
        },
    }


def _write_transcript(path: Path, events: list[dict]) -> Path:
    with open(path, "w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")
    return path


def _run(cwd: Path, transcript: Path, session_id: str = "s-identity") -> subprocess.CompletedProcess:
    payload = json.dumps({
        "cwd": str(cwd),
        "session_id": session_id,
        "transcript_path": str(transcript),
    })
    return subprocess.run(
        [sys.executable, str(SESSION_END)],
        input=payload, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )


def _last_record(tmp_path: Path) -> dict:
    log = tmp_path / ".caddis" / "usage-log.jsonl"
    assert log.exists(), f"no usage-log written at {log}"
    lines = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return json.loads(lines[-1])


# ── the exit gate, verbatim: a session using 3 known skills → the log names exactly those 3 ─

def test_exit_gate_three_known_skills(tmp_path):
    transcript = _write_transcript(tmp_path / "t.jsonl", [
        _user_command("/caddis:feature-plan"),
        _assistant("caddis:tdd"),
        _assistant("caddis:handoff"),
        _assistant("caddis:prd"),
        # a repeat must not duplicate — names are a set
        _assistant("caddis:tdd"),
    ])
    r = _run(tmp_path, transcript)
    assert r.returncode == 0, r.stderr
    rec = _last_record(tmp_path)
    assert rec["skills"] == ["caddis:handoff", "caddis:prd", "caddis:tdd"], rec
    assert rec["commands"] == ["caddis:feature-plan"], rec


def test_records_command_identity(tmp_path):
    transcript = _write_transcript(tmp_path / "t.jsonl", [
        _user_command("/caddis:implement"),
        _user_command("/caddis:ship"),
        _assistant(),  # usage only, no skill
    ])
    r = _run(tmp_path, transcript)
    assert r.returncode == 0, r.stderr
    rec = _last_record(tmp_path)
    assert rec["skills"] == [], rec
    assert rec["commands"] == ["caddis:implement", "caddis:ship"], rec


def test_identity_recorded_even_without_usage(tmp_path):
    """Robustness for V15: identity must be captured even when the token parse yields nothing
    (a session whose assistant messages carry no usage block). The record still lands."""
    no_usage_assistant = {
        "type": "assistant",
        "message": {"role": "assistant", "model": "claude-sonnet-5",
                    "content": [{"type": "tool_use", "name": "Skill",
                                 "input": {"skill": "caddis:kb"}}]},
    }
    transcript = _write_transcript(tmp_path / "t.jsonl", [
        _user_command("/caddis:kb"),
        no_usage_assistant,
    ])
    r = _run(tmp_path, transcript)
    assert r.returncode == 0, r.stderr
    rec = _last_record(tmp_path)
    assert rec["skills"] == ["caddis:kb"], rec
    assert rec["commands"] == ["caddis:kb"], rec


def test_no_arguments_recorded(tmp_path):
    """Privacy bar: a Skill tool_use carries arguments (e.g. a prompt) that must NEVER reach
    the log — only the skill name. A command's args text likewise stays out."""
    skill_with_args = {
        "type": "assistant",
        "message": {"role": "assistant", "model": "claude-sonnet-5",
                    "content": [{"type": "tool_use", "name": "Skill",
                                 "input": {"skill": "caddis:tdd", "args": "SECRET ARGUMENTS 123"}}],
                    "usage": {"input_tokens": 1, "output_tokens": 1}},
    }
    transcript = _write_transcript(tmp_path / "t.jsonl", [skill_with_args])
    r = _run(tmp_path, transcript)
    assert r.returncode == 0, r.stderr
    rec = _last_record(tmp_path)
    text = json.dumps(rec)
    assert rec["skills"] == ["caddis:tdd"], rec
    assert "SECRET" not in text and "123" not in text, "arguments leaked into the log: " + text


def test_never_fails_on_bad_input(tmp_path):
    # empty / non-json stdin must not crash the Stop hook
    for bad in ("", "not json at all"):
        r = subprocess.run(
            [sys.executable, str(SESSION_END)],
            input=bad, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        assert r.returncode == 0, (bad, r.stderr)
