"""Session-state files are scoped PER SESSION, not one shared name.

Why this file exists: two Claude sessions routinely share one working tree on this fleet, and
`.caddis/session-state.md` was a single unqualified path rewritten by the Stop hook at the end
of EVERY turn. Whichever session stopped last won, silently, and the next SessionStart then
surfaced a peer's state under the heading "WHERE THE LAST TURN LEFT OFF". The session id was
already rendered INTO the file; only the filename was unqualified.

The hooks run top-level code and call sys.exit() on import, so each test invokes the hook as a
subprocess, matching test_hook_paths.py.

Run: python -m pytest claude-harness/hooks/tests/test_session_state_scoping.py -q
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent
INJECT = HOOKS_DIR / "inject_relay.py"
SESSION_END = HOOKS_DIR / "session_end.py"

_HEADLESS_MARKERS = ("CADDIS_HEADLESS", "DOCKET_PLAN", "DOCKET_BRANCH")
STATE_MARKER = "=== session-state: WHERE THE LAST TURN LEFT OFF ==="


def _run(script: Path, cwd: Path, stdin: str) -> subprocess.CompletedProcess:
    child_env = {k: v for k, v in os.environ.items() if k not in _HEADLESS_MARKERS}
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=str(cwd), input=stdin, capture_output=True, text=True,
        encoding="utf-8", timeout=30, env=child_env,
    )


def _transcript(tmp_path: Path, asked: str) -> str:
    """Smallest transcript that renders more than the 8 lines write_state requires."""
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join([
        json.dumps({"type": "user", "message": {"role": "user", "content": asked}}),
        json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "TaskCreate",
             "input": {"subject": "Scope the state file"}}]}}),
        json.dumps({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1",
             "content": "Task #1 created successfully: Scope the state file"}]}}),
    ]) + "\n", encoding="utf-8")
    return str(path)


def _stop(tmp_path: Path, session_id: str, asked: str = "do the thing"):
    return _run(SESSION_END, tmp_path, json.dumps({
        "cwd": str(tmp_path),
        "session_id": session_id,
        "transcript_path": _transcript(tmp_path, asked),
    }))


# ── the write side ───────────────────────────────────────────────────────────

def test_writes_one_file_per_session_id(tmp_path):
    (tmp_path / ".caddis").mkdir()
    _stop(tmp_path, "aaaa1111")
    assert (tmp_path / ".caddis" / "session-state" / "aaaa1111.md").is_file()


def test_two_sessions_do_not_overwrite_each_other(tmp_path):
    """THE regression this change exists for. Under the flat name the second write won."""
    (tmp_path / ".caddis").mkdir()
    _stop(tmp_path, "session-one", asked="first session question")
    _stop(tmp_path, "session-two", asked="second session question")

    state_dir = tmp_path / ".caddis" / "session-state"
    assert sorted(p.name for p in state_dir.glob("*.md")) == ["session-one.md", "session-two.md"]
    assert "first session question" in (state_dir / "session-one.md").read_text(encoding="utf-8")
    assert "second session question" in (state_dir / "session-two.md").read_text(encoding="utf-8")


def test_falls_back_to_the_flat_name_without_a_session_id(tmp_path):
    """Non-Claude payloads carry no session_id; they keep the pre-2026-09-08 layout."""
    (tmp_path / ".caddis").mkdir()
    _stop(tmp_path, "")
    assert (tmp_path / ".caddis" / "session-state.md").is_file()
    assert not (tmp_path / ".caddis" / "session-state").exists()


def test_session_id_is_slugified_into_a_safe_filename(tmp_path):
    """A payload id is untrusted input and lands in a path — no separators may survive."""
    (tmp_path / ".caddis").mkdir()
    _stop(tmp_path, "../../escape/attempt")
    written = list((tmp_path / ".caddis" / "session-state").glob("*.md"))
    assert len(written) == 1
    assert written[0].name == "escapeattempt.md"


def test_prunes_to_the_newest_eight(tmp_path):
    (tmp_path / ".caddis").mkdir()
    state_dir = tmp_path / ".caddis" / "session-state"
    state_dir.mkdir()
    for i in range(12):
        stale = state_dir / f"old{i:02d}.md"
        stale.write_text("stale\n", encoding="utf-8")
        os.utime(stale, (1_600_000_000 + i, 1_600_000_000 + i))
    _stop(tmp_path, "newest")

    remaining = sorted(p.name for p in state_dir.glob("*.md"))
    assert len(remaining) == 8
    assert "newest.md" in remaining
    assert "old00.md" not in remaining  # oldest went first
    assert "old11.md" in remaining      # newest of the stale ones survived


# ── the read side ────────────────────────────────────────────────────────────

def test_inject_prefers_the_newest_per_session_file(tmp_path):
    state_dir = tmp_path / ".caddis" / "session-state"
    state_dir.mkdir(parents=True)
    (state_dir / "older.md").write_text("**Updated:** x\n\nOLDER STATE\n", encoding="utf-8")
    time.sleep(0.01)
    (state_dir / "newer.md").write_text("**Updated:** y\n\nNEWER STATE\n", encoding="utf-8")
    os.utime(state_dir / "older.md", (1_600_000_000, 1_600_000_000))

    out = _run(INJECT, tmp_path, "{}").stdout
    assert STATE_MARKER in out
    assert "NEWER STATE" in out
    assert "OLDER STATE" not in out


def test_inject_still_reads_the_legacy_flat_file(tmp_path):
    """Back-compat: a repo that has not stopped a session since the change has only the old file."""
    (tmp_path / ".caddis").mkdir()
    (tmp_path / ".caddis" / "session-state.md").write_text(
        "**Updated:** z\n\nLEGACY STATE\n", encoding="utf-8")
    out = _run(INJECT, tmp_path, "{}").stdout
    assert STATE_MARKER in out and "LEGACY STATE" in out


def test_inject_ignores_the_atomic_write_scratch_files(tmp_path):
    """write_state leaves .session-state-*.tmp on a crash; picking one up would surface junk."""
    state_dir = tmp_path / ".caddis" / "session-state"
    state_dir.mkdir(parents=True)
    (state_dir / "real.md").write_text("**Updated:** a\n\nREAL STATE\n", encoding="utf-8")
    scratch = state_dir / ".session-state-abc.tmp"
    scratch.write_text("**Updated:** b\n\nTRUNCATED JUNK\n", encoding="utf-8")
    os.utime(scratch, (2_000_000_000, 2_000_000_000))  # newest by far

    out = _run(INJECT, tmp_path, "{}").stdout
    assert "REAL STATE" in out
    assert "TRUNCATED JUNK" not in out


def test_inject_says_the_state_may_belong_to_a_parallel_session(tmp_path):
    """The file may be a live peer's. The filesystem cannot tell; say so rather than imply
    continuity with the reader's own work."""
    state_dir = tmp_path / ".caddis" / "session-state"
    state_dir.mkdir(parents=True)
    (state_dir / "peer.md").write_text("**Updated:** a\n\nPEER STATE\n", encoding="utf-8")
    out = _run(INJECT, tmp_path, "{}").stdout
    assert "PARALLEL session" in out


# ── live-peer warning (shared-checkout-collision item 1) ─────────────────────
# Three sessions worked in one shared tree on 2026-09-06; two discovered it by watching the
# branch change underneath them. The per-session state directory above is already the registry
# that makes this detectable without a model tool.

PEER_MARKER = "=== ANOTHER SESSION IS LIVE IN THIS CHECKOUT ==="


def _peer_file(repo: Path, sid: str, age_s: int = 0) -> Path:
    d = repo / ".caddis" / "session-state"
    d.mkdir(parents=True, exist_ok=True)
    p = d / (sid + ".md")
    p.write_text("**Updated:** x" + chr(10) + chr(10) + "PEER WORK" + chr(10), encoding="utf-8")
    if age_s:
        stamp = time.time() - age_s
        os.utime(p, (stamp, stamp))
    return p


def test_a_live_peer_is_announced(tmp_path):
    """THE regression that matters: this is a top-level hook block, and an earlier revision
    defined the helper BELOW its call site — NameError, swallowed by the fail-open handler, hook
    silently printed nothing. A unit test of the helper would have passed."""
    _peer_file(tmp_path, "peer-abc")
    out = _run(INJECT, tmp_path, json.dumps({"cwd": str(tmp_path), "session_id": "mine-123"}))
    assert PEER_MARKER in out.stdout
    assert "peer-abc" in out.stdout


def test_the_warning_names_the_operations_that_destroy_a_peers_work(tmp_path):
    _peer_file(tmp_path, "peer-abc")
    out = _run(INJECT, tmp_path, json.dumps({"cwd": str(tmp_path), "session_id": "mine"})).stdout
    for op in ("checkout", "stash", "reset", "rebase", "clean"):
        assert op in out, op
    assert "worktree" in out, "the mitigation was rediscovered three times; state it"


def test_your_own_state_file_is_not_a_peer(tmp_path):
    """`claude --continue` resumes the same session id. Warning about yourself trains the reader
    to ignore the warning."""
    _peer_file(tmp_path, "same-id")
    out = _run(INJECT, tmp_path, json.dumps({"cwd": str(tmp_path), "session_id": "same-id"}))
    assert PEER_MARKER not in out.stdout


def test_a_stale_session_is_not_a_live_peer(tmp_path):
    _peer_file(tmp_path, "long-gone", age_s=4000)
    out = _run(INJECT, tmp_path, json.dumps({"cwd": str(tmp_path), "session_id": "mine"}))
    assert PEER_MARKER not in out.stdout


def test_no_peers_means_no_noise(tmp_path):
    (tmp_path / ".caddis").mkdir()
    out = _run(INJECT, tmp_path, json.dumps({"cwd": str(tmp_path), "session_id": "mine"}))
    assert PEER_MARKER not in out.stdout


def test_the_warning_comes_before_the_session_state(tmp_path):
    """A fresh session's instinct on seeing a dirty tree is to tidy it. The warning has to land
    before anything that describes work in progress."""
    _peer_file(tmp_path, "peer-abc")
    out = _run(INJECT, tmp_path, json.dumps({"cwd": str(tmp_path), "session_id": "mine"})).stdout
    assert out.index(PEER_MARKER) < out.index(STATE_MARKER)
