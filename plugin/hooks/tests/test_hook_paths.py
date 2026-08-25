"""Subprocess tests for caddis hook path resolution (.caddis + legacy fallback).

The hooks run top-level code and call sys.exit() on import, so they CANNOT be
imported — each test invokes the hook as a subprocess with a crafted stdin payload
and a tmp_path cwd, then asserts on stdout / written files.

Run: python -m pytest claude-harness/hooks/tests/test_hook_paths.py -q
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent
INJECT = HOOKS_DIR / "inject_relay.py"
SESSION_END = HOOKS_DIR / "session_end.py"

# The relay is suppressed for headless sessions, so these must be scrubbed by default or the
# whole file fails whenever the suite is run FROM a docket-spawned session — which is exactly
# when it most needs to pass.
_HEADLESS_MARKERS = ("CADDIS_HEADLESS", "DOCKET_PLAN", "DOCKET_BRANCH")

# The relay is wrapped in an explicit "this is state, not a task" frame; tests key off the
# opening marker rather than the sentence, so wording can be tuned without breaking them.
RELAY_MARKER = "=== session-context: relay.md"


def _run(script: Path, cwd: Path, stdin: str, env: dict | None = None) -> subprocess.CompletedProcess:
    child_env = {k: v for k, v in os.environ.items() if k not in _HEADLESS_MARKERS}
    child_env.update(env or {})
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=str(cwd),
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",  # hooks reconfigure stdout to utf-8; decode to match (Windows default is cp1252)
        timeout=30,
        env=child_env,
    )


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True)


# ── inject_relay: relay resolution ──────────────────────────────────────────

def test_inject_reads_new_relay(tmp_path):
    (tmp_path / ".caddis").mkdir()
    (tmp_path / ".caddis" / "relay.md").write_text("# Relay — NEW", encoding="utf-8")
    r = _run(INJECT, tmp_path, "{}")
    assert "# Relay — NEW" in r.stdout


def test_inject_anchors_to_session_cwd_not_process_cwd(tmp_path):
    """The relay resolves from the session's repo (payload cwd), not the launch cwd."""
    session_repo = tmp_path / "session_repo"
    launch_repo = tmp_path / "launch_repo"
    (session_repo / ".caddis").mkdir(parents=True)
    (session_repo / ".caddis" / "relay.md").write_text("# Relay — SESSION REPO", encoding="utf-8")
    launch_repo.mkdir()
    (launch_repo / ".caddis").mkdir()
    (launch_repo / ".caddis" / "relay.md").write_text("# Relay — LAUNCH REPO", encoding="utf-8")
    payload = json.dumps({"cwd": str(session_repo)})
    r = _run(INJECT, launch_repo, payload)
    assert "# Relay — SESSION REPO" in r.stdout
    assert "LAUNCH REPO" not in r.stdout


def test_inject_falls_back_to_legacy_root_relay(tmp_path):
    (tmp_path / "relay.md").write_text("# Relay — LEGACY", encoding="utf-8")
    r = _run(INJECT, tmp_path, "{}")
    assert "# Relay — LEGACY" in r.stdout


def test_inject_prefers_new_over_legacy(tmp_path):
    (tmp_path / ".caddis").mkdir()
    (tmp_path / ".caddis" / "relay.md").write_text("RELAY-NEW-CONTENT", encoding="utf-8")
    (tmp_path / "relay.md").write_text("RELAY-OLD-CONTENT", encoding="utf-8")
    r = _run(INJECT, tmp_path, "{}")
    assert "RELAY-NEW-CONTENT" in r.stdout
    assert "RELAY-OLD-CONTENT" not in r.stdout


# ── inject_relay: the relay is framed as state, and skipped when headless ───
# Measured on a glm-headless docket (2026-08-03): the relay arrives before the user's prompt,
# used to be headed "read before acting", and was EXECUTED first — the session committed the
# previous session's leftover next step, then started its own task. An explicit "ignore the
# relay" line in the prompt did not change the ordering, so the injection itself has to say
# what it is, and a run with no human to misread it should not get one at all.

def test_relay_is_framed_as_background_state_not_a_task(tmp_path):
    (tmp_path / ".caddis").mkdir()
    (tmp_path / ".caddis" / "relay.md").write_text(
        "# Relay\n## Next step (exact)\nDelete the old table.", encoding="utf-8")
    out = _run(INJECT, tmp_path, "{}").stdout
    assert RELAY_MARKER in out
    assert "NOT A TASK" in out, "the frame must say the relay is not the session's task"
    assert "read before acting" not in out, \
        "the old header was an imperative — that phrasing is the bug, not a label"
    assert "=== end session-context ===" in out, "the frame must close, so the body is bounded"
    assert "Delete the old table." in out, "framing must not cost the relay's content"


def test_relay_suppressed_for_a_headless_session(tmp_path):
    (tmp_path / ".caddis").mkdir()
    (tmp_path / ".caddis" / "relay.md").write_text("RELAY-BODY", encoding="utf-8")
    out = _run(INJECT, tmp_path, "{}", env={"CADDIS_HEADLESS": "1"}).stdout
    assert "RELAY-BODY" not in out, "a headless run is given its task explicitly — no resume pointer"
    assert RELAY_MARKER not in out


def test_relay_suppressed_for_a_docket_runner_session(tmp_path):
    """The docket runner spawns implement lanes with no human present (implement.md's own contract)."""
    (tmp_path / ".caddis").mkdir()
    (tmp_path / ".caddis" / "relay.md").write_text("RELAY-BODY", encoding="utf-8")
    for marker in ("DOCKET_PLAN", "DOCKET_BRANCH"):
        out = _run(INJECT, tmp_path, "{}", env={marker: "x"}).stdout
        assert "RELAY-BODY" not in out, f"{marker} marks a runner-spawned session"


def test_headless_flag_is_only_honoured_when_truthy(tmp_path):
    """An empty or 'false' value must not suppress — a stray export should not silently
    disable the resume pointer for every interactive session on the machine."""
    (tmp_path / ".caddis").mkdir()
    (tmp_path / ".caddis" / "relay.md").write_text("RELAY-BODY", encoding="utf-8")
    for value in ("", "0", "false", "no"):
        out = _run(INJECT, tmp_path, "{}", env={"CADDIS_HEADLESS": value}).stdout
        assert "RELAY-BODY" in out, f"CADDIS_HEADLESS={value!r} must not count as headless"


def test_headless_suppresses_only_the_relay(tmp_path):
    """The other SessionStart signals are labels, not instructions — they are not the bug,
    and dropping them would quietly cost a headless run its DOC-MAP pointer."""
    (tmp_path / ".caddis" / "kb").mkdir(parents=True)
    (tmp_path / ".caddis" / "kb" / "DOC-MAP.md").write_text("# Doc map", encoding="utf-8")
    (tmp_path / ".caddis" / "relay.md").write_text("RELAY-BODY", encoding="utf-8")
    out = _run(INJECT, tmp_path, "{}", env={"CADDIS_HEADLESS": "1"}).stdout
    assert "RELAY-BODY" not in out
    assert "DOC-MAP" in out


# ── inject_relay: workstream stack (digression tracker, Phase 1) ────────────
_PARKED = "⛏ Parked workstream:"


def _write_workstreams(tmp_path, stack, version=1) -> None:
    (tmp_path / ".caddis").mkdir(exist_ok=True)
    (tmp_path / ".caddis" / "workstreams.json").write_text(
        json.dumps({"version": version, "stack": stack}), encoding="utf-8"
    )


def _frame(plan, phase="Phase 1", reason="blocked", repo=None,
           pushed="2026-07-10T14:00:00Z", pointer="do the next thing"):
    return {"plan": plan, "phase": phase, "resumePointer": pointer,
            "reason": reason, "repo": repo, "pushedAt": pushed}


def test_injects_parked_frame_line(tmp_path):
    _write_workstreams(tmp_path, [_frame(".caddis/plans/ucip.md", phase="Phase 2 — ingestion",
                                         reason="blocked on the Windows-auth sidecar")])
    r = _run(INJECT, tmp_path, "{}")
    assert _PARKED in r.stdout
    assert ".caddis/plans/ucip.md" in r.stdout
    assert "Phase 2 — ingestion" in r.stdout
    assert "blocked on the Windows-auth sidecar" in r.stdout
    assert "2026-07-10" in r.stdout            # date part of pushedAt
    assert "/resume" in r.stdout


def test_parked_line_precedes_relay(tmp_path):
    """Improvement #3: the parked line is emitted BEFORE the relay marker (surface-it-first)."""
    _write_workstreams(tmp_path, [_frame(".caddis/plans/ucip.md")])
    (tmp_path / ".caddis" / "relay.md").write_text("# Relay — CURRENT", encoding="utf-8")
    r = _run(INJECT, tmp_path, "{}")
    assert _PARKED in r.stdout
    assert RELAY_MARKER in r.stdout
    assert r.stdout.index(_PARKED) < r.stdout.index(RELAY_MARKER)


def test_multiple_frames_listed_lifo(tmp_path):
    """Top-of-stack (most recently parked) first; a total count line when N > 1."""
    _write_workstreams(tmp_path, [
        _frame(".caddis/plans/older.md"),   # pushed first → deepest
        _frame(".caddis/plans/newer.md"),   # pushed last → top of stack
    ])
    r = _run(INJECT, tmp_path, "{}")
    assert r.stdout.index("newer.md") < r.stdout.index("older.md")
    assert "(2 parked total)" in r.stdout


def test_absent_file_injects_nothing(tmp_path):
    r = _run(INJECT, tmp_path, "{}")
    assert _PARKED not in r.stdout


def test_malformed_json_is_silently_ignored(tmp_path):
    (tmp_path / ".caddis").mkdir()
    (tmp_path / ".caddis" / "workstreams.json").write_text("{oops", encoding="utf-8")
    r = _run(INJECT, tmp_path, "{}")
    assert r.returncode == 0
    assert _PARKED not in r.stdout


def test_empty_stack_injects_nothing(tmp_path):
    _write_workstreams(tmp_path, [])
    r = _run(INJECT, tmp_path, "{}")
    assert _PARKED not in r.stdout


def test_wrong_version_injects_nothing(tmp_path):
    _write_workstreams(tmp_path, [_frame(".caddis/plans/ucip.md")], version=99)
    r = _run(INJECT, tmp_path, "{}")
    assert _PARKED not in r.stdout


def test_cross_repo_frame_shows_repo_path(tmp_path):
    _write_workstreams(tmp_path, [
        _frame("plans/serve-sight.md", repo="E:/Projects/serve-sight"),
    ])
    r = _run(INJECT, tmp_path, "{}")
    assert _PARKED in r.stdout
    assert "E:/Projects/serve-sight" in r.stdout


# ── inject_relay: usage-review nudge stamp (new + legacy fallback) ───────────

def test_inject_nudge_reads_new_stamp(tmp_path):
    (tmp_path / ".caddis").mkdir()
    (tmp_path / ".caddis" / ".last-usage-review").write_text(_iso_days_ago(10), encoding="utf-8")
    r = _run(INJECT, tmp_path, "{}")
    assert "[USAGE-REVIEW]" in r.stdout


def test_inject_nudge_reads_legacy_stamp(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / ".last-usage-review").write_text(_iso_days_ago(10), encoding="utf-8")
    r = _run(INJECT, tmp_path, "{}")
    assert "[USAGE-REVIEW]" in r.stdout


# ── inject_relay: DOC-MAP reference-index pointer (Phase 4) ─────────────────

def test_inject_emits_docmap_pointer_when_present(tmp_path):
    (tmp_path / ".caddis" / "kb").mkdir(parents=True)
    (tmp_path / ".caddis" / "kb" / "DOC-MAP.md").write_text("# Doc map", encoding="utf-8")
    r = _run(INJECT, tmp_path, "{}")
    assert "DOC-MAP" in r.stdout
    assert ".caddis/kb/DOC-MAP.md" in r.stdout


def test_inject_no_docmap_pointer_when_absent(tmp_path):
    r = _run(INJECT, tmp_path, "{}")
    assert "DOC-MAP" not in r.stdout


def test_inject_docmap_pointer_anchors_to_repo_root_in_subdir(tmp_path):
    """The pointer fires for a session launched from a subfolder (root-anchored)."""
    _git_init(tmp_path)
    (tmp_path / ".caddis" / "kb").mkdir(parents=True)
    (tmp_path / ".caddis" / "kb" / "DOC-MAP.md").write_text("# Doc map", encoding="utf-8")
    sub = tmp_path / "src"
    sub.mkdir()
    r = _run(INJECT, sub, "{}")
    assert "DOC-MAP" in r.stdout


# ── inject_relay: Dream Memory surfacing (Phase 5c) ─────────────────────────

def _fact_line(kind: str, key: str, summary: str, hits: int = 1) -> str:
    return json.dumps({
        "kind": kind, "key": key, "summary": summary, "hitCount": hits,
        "firstSeen": "2026-07-01T09:00:00Z", "lastSeen": _iso_days_ago(0), "source": "auto",
    })




def test_inject_no_memory_block_when_store_absent(tmp_path):
    r = _run(INJECT, tmp_path, "{}")
    assert "[memory]" not in r.stdout


def test_inject_memory_survives_malformed_store(tmp_path):
    """A hand-broken store must not crash the hook (fail-open) — no [memory] block, clean exit."""
    (tmp_path / ".caddis").mkdir()
    (tmp_path / ".caddis" / "memory.jsonl").write_text("{not json\n\n{\"kind\":\"bad\"}\n", encoding="utf-8")
    r = _run(INJECT, tmp_path, "{}")
    assert r.returncode == 0
    assert "[memory]" not in r.stdout  # nothing valid to surface



def test_session_end_writes_new_usage_log(tmp_path):
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps({"message": {"model": "claude-sonnet-4-6",
                                "usage": {"input_tokens": 10, "output_tokens": 5}}}) + "\n",
        encoding="utf-8",
    )
    payload = json.dumps({"transcript_path": str(transcript), "session_id": "t"})
    _run(SESSION_END, tmp_path, payload)
    new_log = tmp_path / ".caddis" / "usage-log.jsonl"
    old_log = tmp_path / ".claude" / "usage-log.jsonl"
    assert new_log.is_file()
    lines = [l for l in new_log.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1
    assert not old_log.exists()


def _cost_for_model(tmp_path: Path, model: str) -> float:
    """Run session_end over a 1M-input / 0-output transcript for `model`; return est cost.

    With output=0 and no cache, est_cost_usd == the model's per-Mtok INPUT rate, so
    the value directly exposes which pricing tier the model resolved to.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps({"message": {"model": model,
                                "usage": {"input_tokens": 1_000_000, "output_tokens": 0}}}) + "\n",
        encoding="utf-8",
    )
    payload = json.dumps({"transcript_path": str(transcript), "session_id": "t"})
    _run(SESSION_END, tmp_path, payload)
    log = tmp_path / ".caddis" / "usage-log.jsonl"
    rec = json.loads([l for l in log.read_text(encoding="utf-8").splitlines() if l.strip()][-1])
    return rec["est_cost_usd"]


def test_oss_models_do_not_bill_as_sonnet(tmp_path):
    sonnet_rate = _cost_for_model(tmp_path / "s", "claude-sonnet-4-6")
    assert sonnet_rate == 3.0  # baseline: Anthropic sonnet input rate

    # GLM / DeepSeek / Qwen must resolve to their own (cheaper) tiers, not sonnet.
    glm = _cost_for_model(tmp_path / "glm", "glm-4.6")
    deepseek = _cost_for_model(tmp_path / "ds", "deepseek-chat")
    qwen = _cost_for_model(tmp_path / "qw", "qwen2.5-coder-32b")
    for label, cost in (("glm", glm), ("deepseek", deepseek), ("qwen", qwen)):
        assert cost < sonnet_rate, f"{label} billed at sonnet rate ({cost})"
        assert cost > 0, f"{label} should have a non-zero API rate"


def test_local_models_bill_zero(tmp_path):
    # Self-hosted / ollama models have no per-token API cost.
    assert _cost_for_model(tmp_path / "l1", "llama3.1:8b") == 0.0
    assert _cost_for_model(tmp_path / "l2", "ollama/mistral") == 0.0


# ── session_end: Dream Memory capture (Phase 5b) ────────────────────────────

def _transcript_with_failed_bash(path: Path, command: str, output: str) -> None:
    """Write a minimal transcript: a usage record + a Bash tool_use and a failed tool_result."""
    lines = [
        json.dumps({"message": {"model": "claude-sonnet-4-6",
                                "usage": {"input_tokens": 10, "output_tokens": 5}}}),
        json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "tc1", "name": "Bash", "input": {"command": command}}]}}),
        json.dumps({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tc1", "content": output, "is_error": True}]}}),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")








def test_session_end_no_store_when_no_signals(tmp_path):
    """A transcript with only a successful/usage record writes no memory store (no noise)."""
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps({"message": {"model": "claude-sonnet-4-6",
                                "usage": {"input_tokens": 10, "output_tokens": 5}}}) + "\n",
        encoding="utf-8",
    )
    payload = json.dumps({"transcript_path": str(transcript), "session_id": "t"})
    _run(SESSION_END, tmp_path, payload)
    assert not (tmp_path / ".caddis" / "memory.jsonl").exists()





def test_session_end_anchors_log_to_repo_root(tmp_path):
    """A session launched from a subfolder must append to the repo-root log,
    not scatter a .caddis/ into the subfolder (a real bug seen in the wild)."""
    _git_init(tmp_path)
    sub = tmp_path / "frontend"
    sub.mkdir()
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps({"message": {"model": "claude-sonnet-4-6",
                                "usage": {"input_tokens": 10, "output_tokens": 5}}}) + "\n",
        encoding="utf-8",
    )
    payload = json.dumps({"transcript_path": str(transcript), "session_id": "t"})
    _run(SESSION_END, sub, payload)  # launched from the subdir
    assert (tmp_path / ".caddis" / "usage-log.jsonl").is_file(), "log must land at repo root"
    assert not (sub / ".caddis").exists(), "must NOT scatter .caddis into the subdir"


def test_inject_reads_relay_from_repo_root_in_subdir(tmp_path):
    """relay.md at the repo root is found even when the session runs from a subfolder."""
    _git_init(tmp_path)
    (tmp_path / ".caddis").mkdir()
    (tmp_path / ".caddis" / "relay.md").write_text("# Relay — ROOT-ANCHORED", encoding="utf-8")
    sub = tmp_path / "src"
    sub.mkdir()
    r = _run(INJECT, sub, "{}")  # launched from the subdir
    assert "# Relay — ROOT-ANCHORED" in r.stdout
