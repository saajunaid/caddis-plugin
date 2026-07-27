"""Subprocess tests for the agy guard hook (PreToolUse -> {"decision": "deny"|"force_ask"}).

The agy adapter parses agy's camelCase toolCall payload, runs the SAME classifiers as the Claude Code
guard, and emits agy's decision envelope. The load-bearing property is FAIL-OPEN: any malformed input,
unknown shape, or internal error must produce silence + exit 0, never a crash and never a malformed
decision (agy may fail-closed on a hook error, which would brick the agent).

Run: python -m pytest claude-harness/hooks/tests/test_guard_agy.py -q
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent.parent / "agy" / "guard_agy.py"


def _clean_env() -> dict:
    # Strip the kill switch (both names of the env pair) so the guard's default (enabled) behaviour
    # is deterministic regardless of the ambient environment — this machine sets the legacy name
    # globally, which would silently turn every deny below into a pass.
    e = dict(os.environ)
    e.pop("CADDIS_GUARD_DISABLED", None)
    e.pop("CLAUDSTER_GUARD_DISABLED", None)
    return e


def _run(stdin: str, cwd=None, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=stdin, capture_output=True, text=True, encoding="utf-8", timeout=30,
        cwd=str(cwd) if cwd else None, env=env or _clean_env(),
    )


def _payload(command, ws=None, name="run_command"):
    data = {"toolCall": {"name": name, "args": {"CommandLine": command}}, "stepIdx": 1,
            "conversationId": "c1", "modelName": "gemini-3.6-flash"}
    if ws is not None:
        data["workspacePaths"] = [str(ws)]
    return json.dumps(data)


def _decision(result: subprocess.CompletedProcess):
    """The parsed decision object, or None when the hook stayed silent (= allow)."""
    out = result.stdout.strip()
    return json.loads(out) if out else None


# ── deny tier ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("command", [
    "rm -rf /",
    'rm "-rf" "/"',            # quote evasion
    "rm -rf ~",
    "rm -rf $HOME",
    ":(){ :|:& };:",           # fork bomb
    "mkfs.ext4 /dev/sda1",
    "dd if=/dev/zero of=/dev/sda",
    "Remove-Item -Recurse -Force C:\\",
])
def test_destructive_command_is_denied(command, tmp_path):
    r = _run(_payload(command, tmp_path))
    assert r.returncode == 0
    d = _decision(r)
    assert d is not None, f"expected a decision for: {command}"
    assert d["decision"] == "deny"
    assert d["reason"].startswith("[caddis guard] ")


def test_ask_tier_uses_agy_force_ask(tmp_path):
    d = _decision(_run(_payload("rm -rf ./build", tmp_path)))
    assert d["decision"] == "force_ask"
    assert "recursive force-delete" in d["reason"]


def test_git_force_push_asks(tmp_path):
    assert _decision(_run(_payload("git push --force origin main", tmp_path)))["decision"] == "force_ask"


# ── deny-only mode: keep deny (silent block), suppress force_ask (no prompt/interruption) ─────
def test_deny_only_silences_ask(tmp_path):
    env = {**_clean_env(), "CADDIS_GUARD_MODE": "deny-only"}
    r = _run(_payload("git push --force origin main", tmp_path), env=env)
    assert r.returncode == 0
    assert _decision(r) is None  # ask-tier → silence, agy is never prompted


def test_deny_only_keeps_deny(tmp_path):
    env = {**_clean_env(), "CADDIS_GUARD_MODE": "deny-only"}
    assert _decision(_run(_payload("rm -rf /", tmp_path), env=env))["decision"] == "deny"


# ── allow tier: silence, never {"decision":"allow"} ──────────────────────────
@pytest.mark.parametrize("command", [
    "npm test",
    "git status",
    "python -m pytest -q",
    "rm ./tmp.txt",
    "ls -la",
])
def test_safe_command_emits_nothing(command, tmp_path):
    r = _run(_payload(command, tmp_path))
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_unknown_tool_is_not_classified(tmp_path):
    # A read-only/unknown tool never reaches the shell classifier, even with a scary-looking arg.
    r = _run(_payload("rm -rf /", tmp_path, name="view_file"))
    assert r.returncode == 0 and r.stdout.strip() == ""


# ── fail-open: the safety property ───────────────────────────────────────────
@pytest.mark.parametrize("stdin", [
    "",
    "not json at all",
    "[]",                                        # not an object
    '{"toolCall": "a string"}',                  # toolCall wrong type
    '{"toolCall": {"name": "run_command"}}',     # no args
    '{"toolCall": {"name": "run_command", "args": []}}',   # args wrong type
    '{"toolCall": {"args": {"CommandLine": "rm -rf /"}}}',  # no tool name
    '{"stepIdx": 3}',                            # no toolCall at all
    '{"toolCall": {"name": "run_command", "args": {"CommandLine": "npm test"}}, "workspacePaths": []}',
    '{"toolCall": {"name": "run_command", "args": {"CommandLine": "npm test"}}, "workspacePaths": "nope"}',
])
def test_malformed_input_fails_open(stdin):
    r = _run(stdin)
    assert r.returncode == 0, f"must never exit non-zero: {stdin!r}"
    assert r.stdout.strip() == "", f"must stay silent on malformed input: {stdin!r}"


def test_missing_workspace_still_classifies_without_crashing(tmp_path):
    # No workspacePaths -> falls back to cwd for config lookup; classification still runs.
    r = _run(_payload("rm -rf /"), cwd=tmp_path)
    assert r.returncode == 0
    assert _decision(r)["decision"] == "deny"


def test_stdout_is_a_single_wellformed_object(tmp_path):
    r = _run(_payload("rm -rf /", tmp_path))
    json.loads(r.stdout)  # exactly one object, no trailing noise — raises if malformed
    assert r.stdout.count("{") == r.stdout.count("}")


# ── per-repo config: escape hatch + kill switch (dual-path artifact dir) ─────
def test_allow_list_downgrades_ask_to_allow(tmp_path):
    (tmp_path / ".caddis").mkdir()
    (tmp_path / ".caddis" / "config.toml").write_text('[guard]\nallow = ["./build"]\n', encoding="utf-8")
    r = _run(_payload("rm -rf ./build", tmp_path))
    assert r.stdout.strip() == ""


def test_allow_list_cannot_override_deny(tmp_path):
    (tmp_path / ".caddis").mkdir()
    (tmp_path / ".caddis" / "config.toml").write_text('[guard]\nallow = ["rm -rf /"]\n', encoding="utf-8")
    assert _decision(_run(_payload("rm -rf /", tmp_path)))["decision"] == "deny"


def test_env_kill_switch_disables_every_tier(tmp_path):
    # Pins the legacy name on purpose (the one-version fallback contract).
    env = {**_clean_env(), "CLAUDSTER_GUARD_DISABLED": "1"}
    r = _run(_payload("rm -rf /", tmp_path), env=env)
    assert r.returncode == 0 and r.stdout.strip() == ""


def test_kill_switch_disables_every_tier(tmp_path):
    # Legacy .claudster config dir is still honoured on read.
    (tmp_path / ".claudster").mkdir()
    (tmp_path / ".claudster" / "config.toml").write_text('[guard]\nenabled = false\n', encoding="utf-8")
    r = _run(_payload("rm -rf /", tmp_path))
    assert r.returncode == 0 and r.stdout.strip() == ""


def test_broken_config_does_not_disable_the_guard(tmp_path):
    (tmp_path / ".caddis").mkdir()
    (tmp_path / ".caddis" / "config.toml").write_text("[guard\nthis is not toml", encoding="utf-8")
    assert _decision(_run(_payload("rm -rf /", tmp_path)))["decision"] == "deny"


# ── write tier (heuristic until agy's file-edit tool name is live-checked) ───
def test_write_to_secret_file_is_denied(tmp_path):
    data = json.dumps({"toolCall": {"name": "edit_file", "args": {"FilePath": "app/.env"}},
                       "workspacePaths": [str(tmp_path)]})
    assert _decision(_run(data))["decision"] == "deny"


def test_write_to_ordinary_file_is_silent(tmp_path):
    data = json.dumps({"toolCall": {"name": "edit_file", "args": {"FilePath": "src/app.py"}},
                       "workspacePaths": [str(tmp_path)]})
    assert _run(data).stdout.strip() == ""
