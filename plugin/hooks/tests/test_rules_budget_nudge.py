"""Subprocess tests for rules_budget_nudge.py (PostToolUse re-warn — register 0e).

The hook runs top-level code and exits, so it's invoked as a subprocess (same convention
as test_hook_paths.py), never imported.

Run: python -m pytest claude-harness/hooks/tests/test_rules_budget_nudge.py -q
"""
import json
import subprocess
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent
NUDGE = HOOKS_DIR / "rules_budget_nudge.py"
BUDGET = 200  # mirrors claudster_doctor.AGENTS_MD_BUDGET


def _run(cwd: Path, stdin: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(NUDGE)],
        cwd=str(cwd),
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )


def _payload(tool_name: str, file_path: str, cwd: str | None = None) -> str:
    body = {"tool_name": tool_name, "tool_input": {"file_path": file_path}}
    if cwd is not None:
        body["cwd"] = cwd
    return json.dumps(body)


def _write_oversize(path: Path, lines: int = BUDGET + 5) -> None:
    path.write_text("\n".join(f"l{i}" for i in range(lines)), encoding="utf-8")


def test_fires_on_edit_to_already_oversize_agents_md(tmp_path):
    agents = tmp_path / "AGENTS.md"
    _write_oversize(agents)
    r = _run(tmp_path, _payload("Edit", str(agents), cwd=str(tmp_path)))
    assert r.returncode == 0
    assert "[caddis]" in r.stdout
    assert "over budget" in r.stdout
    assert "AGENTS.md" in r.stdout


def test_fires_on_write_and_multiedit_too(tmp_path):
    agents = tmp_path / "AGENTS.md"
    _write_oversize(agents)
    for tool in ("Write", "MultiEdit"):
        r = _run(tmp_path, _payload(tool, str(agents), cwd=str(tmp_path)))
        assert "over budget" in r.stdout, f"{tool} should have fired"


def test_silent_when_under_budget(tmp_path):
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# lean\nThe Laws.\n", encoding="utf-8")
    r = _run(tmp_path, _payload("Edit", str(agents), cwd=str(tmp_path)))
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_silent_for_unrelated_file(tmp_path):
    other = tmp_path / "README.md"
    _write_oversize(other)
    r = _run(tmp_path, _payload("Edit", str(other), cwd=str(tmp_path)))
    assert r.stdout.strip() == ""


def test_silent_for_unrelated_tool(tmp_path):
    agents = tmp_path / "AGENTS.md"
    _write_oversize(agents)
    r = _run(tmp_path, _payload("Bash", str(agents), cwd=str(tmp_path)))
    assert r.stdout.strip() == ""


def test_malformed_json_is_silently_ignored(tmp_path):
    r = _run(tmp_path, "{oops")
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_missing_file_path_is_silently_ignored(tmp_path):
    r = _run(tmp_path, json.dumps({"tool_name": "Edit", "tool_input": {}}))
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_severity_differs_for_barely_vs_way_over(tmp_path):
    barely = tmp_path / "barely" / "AGENTS.md"
    way = tmp_path / "way" / "AGENTS.md"
    barely.parent.mkdir()
    way.parent.mkdir()
    _write_oversize(barely, lines=BUDGET + 1)
    _write_oversize(way, lines=BUDGET * 5)
    r_barely = _run(tmp_path, _payload("Edit", str(barely), cwd=str(tmp_path)))
    r_way = _run(tmp_path, _payload("Edit", str(way), cwd=str(tmp_path)))
    assert r_barely.stdout != r_way.stdout
    assert "slightly" in r_barely.stdout
    assert "way" in r_way.stdout


def test_message_shows_path_relative_to_session_cwd(tmp_path):
    """Uses payload cwd (the session root), not the hook process's own cwd."""
    sub = tmp_path / "src"
    sub.mkdir()
    agents = sub / "AGENTS.md"
    _write_oversize(agents)
    r = _run(tmp_path, _payload("Edit", str(agents), cwd=str(tmp_path)))
    assert "src/AGENTS.md" in r.stdout.replace("\\", "/")
