"""Subprocess tests for the SessionStart freshness hook.

Ported into caddis 2026-09-12 from a personal hook on one machine, so agy and every other
machine get it, and so something finally tests it. The properties that matter are the ones
that make it safe rather than annoying: it only prints, it fails open, and it is silent
when there is nothing to say.

Run: python -m pytest claude-harness/hooks/tests/test_repo_freshness.py -q
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "repo_freshness.py"


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=30)
    return (r.stdout or "").strip()


def _run(cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(HOOK)], cwd=str(cwd),
                          input=json.dumps({"cwd": str(cwd)}), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60)


def _clone(tmp_path: Path) -> tuple[Path, Path]:
    """(clone, origin) — a real remote, so fetch and rev-list mean something."""
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", "--bare", str(origin)],
                   check=True, capture_output=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(seed)],
                   check=True, capture_output=True)
    (seed / "a.txt").write_text("one\n", encoding="utf-8")
    _git(seed, "add", "a.txt")
    _git(seed, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "seed")
    _git(seed, "remote", "add", "origin", str(origin))
    _git(seed, "push", "-q", "-u", "origin", "main")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True, capture_output=True)
    return clone, origin


def _advance_origin(tmp_path: Path, origin: Path) -> None:
    """One more commit on the remote's main, so a clone becomes behind."""
    work = tmp_path / "pusher"
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, capture_output=True)
    (work / "b.txt").write_text("two\n", encoding="utf-8")
    _git(work, "add", "b.txt")
    _git(work, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "more")
    _git(work, "push", "-q", "origin", "main")


def _unstamp(repo: Path) -> None:
    """Drop the throttle stamp, so the next run really fetches."""
    stamp = repo / ".git" / "caddis-freshness-stamp"
    if stamp.exists():
        stamp.unlink()


def test_silent_when_clean_and_level(tmp_path):
    clone, _ = _clone(tmp_path)
    r = _run(clone)
    assert r.returncode == 0
    assert r.stdout.strip() == "", "a quiet repo must print nothing, or the output stops being read"


def test_reports_behind_and_offers_a_fresh_branch(tmp_path):
    clone, origin = _clone(tmp_path)
    _advance_origin(tmp_path, origin)
    _unstamp(clone)
    out = _run(clone).stdout
    assert "1 behind origin/main" in out
    assert "git checkout -b <type>/<name> origin/main" in out


def test_uncommitted_work_is_flagged_and_no_branch_is_suggested(tmp_path):
    """Suggesting a branch switch to someone holding uncommitted work in a shared checkout is
    how the branch-switch hazard gets triggered."""
    clone, origin = _clone(tmp_path)
    _advance_origin(tmp_path, origin)
    _unstamp(clone)
    (clone / "mine.txt").write_text("work in progress\n", encoding="utf-8")
    out = _run(clone).stdout
    assert "1 uncommitted" in out
    assert "They may not be yours" in out
    assert "checkout -b" not in out


def test_unpushed_commits_are_named_not_overwritten(tmp_path):
    clone, _ = _clone(tmp_path)
    (clone / "c.txt").write_text("local\n", encoding="utf-8")
    _git(clone, "add", "c.txt")
    _git(clone, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "local only")
    out = _run(clone).stdout
    assert "1 local commit(s) are not on origin/main" in out
    assert "git log --oneline origin/main..HEAD" in out


def test_it_never_changes_the_tree(tmp_path):
    """It only prints. The whole reason it does not act is that these checkouts are shared."""
    clone, origin = _clone(tmp_path)
    _advance_origin(tmp_path, origin)
    _unstamp(clone)
    (clone / "mine.txt").write_text("work in progress\n", encoding="utf-8")
    before = (_git(clone, "rev-parse", "HEAD"), _git(clone, "status", "--porcelain"),
              _git(clone, "branch", "--show-current"))
    _run(clone)
    after = (_git(clone, "rev-parse", "HEAD"), _git(clone, "status", "--porcelain"),
             _git(clone, "branch", "--show-current"))
    assert before == after


def test_outside_a_repository_it_says_nothing_and_exits_zero(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    r = _run(plain)
    assert (r.returncode, r.stdout.strip()) == (0, "")


def test_a_detached_head_says_nothing(tmp_path):
    clone, _ = _clone(tmp_path)
    _git(clone, "checkout", "-q", "--detach", "HEAD")
    assert _run(clone).stdout.strip() == ""


def test_an_unreachable_remote_reports_and_still_exits_zero(tmp_path):
    """A fetch that cannot work must not stall or fail the session — it degrades to a note."""
    clone, _ = _clone(tmp_path)
    _unstamp(clone)
    _git(clone, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    r = _run(clone)
    assert r.returncode == 0
    assert "could not fetch origin" in r.stdout


def test_the_fetch_is_throttled_between_quick_restarts(tmp_path):
    """A stamp in .git/ means a restart minutes later reuses the last fetch. Proven by breaking
    the remote AFTER the first run: a second fetch would report it, and does not."""
    clone, _ = _clone(tmp_path)
    _unstamp(clone)
    _run(clone)
    assert (clone / ".git" / "caddis-freshness-stamp").exists()
    _git(clone, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    assert "could not fetch" not in _run(clone).stdout


def test_the_stamp_is_inside_git_so_it_is_never_committed(tmp_path):
    clone, _ = _clone(tmp_path)
    _unstamp(clone)
    _run(clone)
    assert _git(clone, "status", "--porcelain") == "", "the stamp must not appear as a change"


def test_a_repo_with_no_remote_is_silent(tmp_path):
    """Nothing to be behind, so fetching would fail every time and the note would be noise."""
    local = tmp_path / "local"
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(local)],
                   check=True, capture_output=True)
    (local / "a.txt").write_text("one\n", encoding="utf-8")
    _git(local, "add", "a.txt")
    _git(local, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "seed")
    r = _run(local)
    assert (r.returncode, r.stdout.strip()) == (0, "")


def test_a_dirty_repo_with_no_remote_still_warns(tmp_path):
    local = tmp_path / "local2"
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(local)],
                   check=True, capture_output=True)
    (local / "a.txt").write_text("one\n", encoding="utf-8")
    _git(local, "add", "a.txt")
    _git(local, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "seed")
    (local / "wip.txt").write_text("mine\n", encoding="utf-8")
    out = _run(local).stdout
    assert "uncommitted changes" in out
    assert "could not fetch" not in out


def test_agy_ships_and_uses_the_same_implementation(tmp_path):
    """agy has no SessionStart, so its first-invocation hook carries the report — imported,
    not duplicated. The manifest must ship the file beside it in the bundle."""
    repo = Path(__file__).resolve().parents[3]
    manifest = json.loads((repo / ".github" / "runtime-targets.json").read_text(encoding="utf-8"))
    agy = next(t for t in manifest["targets"] if t.get("name") == "antigravity-plugin")
    assert any(f.get("source") == "hooks/repo_freshness.py" for f in agy["files"])
    warm = (repo / "claude-harness" / "agy" / "warm_start_agy.py").read_text(encoding="utf-8")
    assert "import repo_freshness" in warm
    assert "freshness_lines" in warm


def test_it_is_registered_as_a_session_start_hook():
    hooks = json.loads((HOOK.parent / "hooks.json").read_text(encoding="utf-8"))
    starts = [h["command"] for entry in hooks["hooks"]["SessionStart"] for h in entry["hooks"]]
    assert any("repo_freshness.py" in c for c in starts)
