"""Subprocess tests for caddis hook path resolution (.caddis + legacy fallback).

The hooks run top-level code and call sys.exit() on import, so they CANNOT be
imported — each test invokes the hook as a subprocess with a crafted stdin payload
and a tmp_path cwd, then asserts on stdout / written files.

Run: python -m pytest claude-harness/hooks/tests/test_hook_paths.py -q
"""
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent
INJECT = HOOKS_DIR / "inject_relay.py"
SESSION_END = HOOKS_DIR / "session_end.py"


def _run(script: Path, cwd: Path, stdin: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=str(cwd),
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",  # hooks reconfigure stdout to utf-8; decode to match (Windows default is cp1252)
        timeout=30,
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
    assert "=== relay.md" in r.stdout
    assert r.stdout.index(_PARKED) < r.stdout.index("=== relay.md")


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


def test_inject_surfaces_memory_facts_when_present(tmp_path):
    (tmp_path / ".caddis").mkdir()
    (tmp_path / ".caddis" / "memory.jsonl").write_text(
        "\n".join([
            _fact_line("failure-mode", "npm build", "`npm run build` fails cold — run vite first", hits=4),
            _fact_line("rejected-approach", "poll api", "don't poll the API — use the SSE stream", hits=2),
        ]) + "\n",
        encoding="utf-8",
    )
    r = _run(INJECT, tmp_path, "{}")
    assert "[memory] reinforced facts for this repo" in r.stdout
    assert "npm run build" in r.stdout
    assert "⚠" in r.stdout  # weighted kinds get the warning mark


def test_inject_memory_respects_surface_limit_config(tmp_path):
    """A [dream_memory] surface_limit override caps how many facts SessionStart prints."""
    (tmp_path / ".caddis").mkdir()
    (tmp_path / ".caddis" / "memory.jsonl").write_text(
        "\n".join(_fact_line("repo-fact", f"k{i}", f"fact number {i}", hits=i + 1) for i in range(5)) + "\n",
        encoding="utf-8",
    )
    (tmp_path / ".caddis" / "config.toml").write_text("[dream_memory]\nsurface_limit = 2\n", encoding="utf-8")
    r = _run(INJECT, tmp_path, "{}")
    # Count surfaced fact lines (the indented "  ... repo-fact:" bullets), not the header.
    surfaced = [ln for ln in r.stdout.splitlines() if "repo-fact:" in ln]
    assert len(surfaced) == 2


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


def test_inject_memory_anchors_to_repo_root_in_subdir(tmp_path):
    """Facts surface for a session launched from a subfolder (root-anchored, like relay)."""
    _git_init(tmp_path)
    (tmp_path / ".caddis").mkdir()
    (tmp_path / ".caddis" / "memory.jsonl").write_text(
        _fact_line("failure-mode", "k", "root-anchored fact", hits=3) + "\n", encoding="utf-8",
    )
    sub = tmp_path / "src"
    sub.mkdir()
    r = _run(INJECT, sub, "{}")
    assert "root-anchored fact" in r.stdout


# ── session_end: usage-log write → .caddis, never .claude ────────────────

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


def test_session_end_captures_failure_to_memory_store(tmp_path):
    transcript = tmp_path / "transcript.jsonl"
    _transcript_with_failed_bash(transcript, "pytest tests/test_api.py", "ImportError: no module 'app'")
    payload = json.dumps({"transcript_path": str(transcript), "session_id": "t"})
    _run(SESSION_END, tmp_path, payload)
    store = tmp_path / ".caddis" / "memory.jsonl"
    assert store.is_file()
    facts = [json.loads(l) for l in store.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(f["kind"] == "failure-mode" and "pytest" in f["summary"] for f in facts)


def test_session_end_anchors_store_to_session_cwd_not_process_cwd(tmp_path):
    """Facts land in the session's repo (payload cwd), not the hook process's launch cwd.

    Launching a session in one repo while it operates in another must not leak the
    second repo's facts into the first's Dream Memory store.
    """
    session_repo = tmp_path / "session_repo"   # where the work actually happened
    launch_repo = tmp_path / "launch_repo"      # the hook process's cwd
    session_repo.mkdir()
    launch_repo.mkdir()
    transcript = tmp_path / "transcript.jsonl"
    _transcript_with_failed_bash(transcript, "pytest tests/test_api.py", "ImportError: no module 'app'")
    payload = json.dumps(
        {"transcript_path": str(transcript), "session_id": "t", "cwd": str(session_repo)}
    )
    # Run the hook with its process cwd in launch_repo, but the session cwd is session_repo.
    _run(SESSION_END, launch_repo, payload)
    assert (session_repo / ".caddis" / "memory.jsonl").is_file()
    assert not (launch_repo / ".caddis" / "memory.jsonl").exists()
    # The usage log follows the same anchor.
    assert not (launch_repo / ".caddis" / "usage-log.jsonl").exists()


def test_session_end_capture_redacts_secret_in_store(tmp_path):
    """A token in a failing command must never land in the persisted store (privacy end-to-end)."""
    transcript = tmp_path / "transcript.jsonl"
    _transcript_with_failed_bash(transcript, "deploy --token ghp_0123456789abcdefABCDEF", "auth failed")
    payload = json.dumps({"transcript_path": str(transcript), "session_id": "t"})
    _run(SESSION_END, tmp_path, payload)
    store = tmp_path / ".caddis" / "memory.jsonl"
    assert store.is_file()
    assert "ghp_" not in store.read_text(encoding="utf-8")


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


def test_session_end_consolidates_existing_store_without_new_candidates(tmp_path):
    """The knowledge-transfer path: facts appended out-of-band (duplicate fingerprint) are
    consolidated on the next Stop even when the transcript yields no Bash candidates."""
    store = tmp_path / ".caddis" / "memory.jsonl"
    store.parent.mkdir(parents=True)
    dup = json.dumps({
        "kind": "rejected-approach", "key": "poll-api", "summary": "use SSE not polling",
        "hitCount": 1, "firstSeen": "2026-07-01T09:00:00Z", "lastSeen": "2026-07-01T09:00:00Z",
        "source": "knowledge-transfer",
    })
    store.write_text(dup + "\n" + dup + "\n", encoding="utf-8")  # two identical lines
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(  # usage only, no Bash tool calls → no capture candidates
        json.dumps({"message": {"model": "claude-sonnet-4-6",
                                "usage": {"input_tokens": 10, "output_tokens": 5}}}) + "\n",
        encoding="utf-8",
    )
    payload = json.dumps({"transcript_path": str(transcript), "session_id": "t"})
    _run(SESSION_END, tmp_path, payload)
    facts = [json.loads(l) for l in store.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(facts) == 1  # the two identical lines merged
    assert facts[0]["hitCount"] == 2  # reinforced


def test_session_end_capture_anchors_store_to_repo_root(tmp_path):
    """Capture writes the store at the git root even when the Stop fires from a subfolder."""
    _git_init(tmp_path)
    sub = tmp_path / "backend"
    sub.mkdir()
    transcript = tmp_path / "transcript.jsonl"
    _transcript_with_failed_bash(transcript, "npm run build", "build error")
    payload = json.dumps({"transcript_path": str(transcript), "session_id": "t"})
    _run(SESSION_END, sub, payload)
    assert (tmp_path / ".caddis" / "memory.jsonl").is_file()
    assert not (sub / ".caddis" / "memory.jsonl").exists()


# ── repo-root anchoring: state lands at the git root, never the launch subdir ──

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
