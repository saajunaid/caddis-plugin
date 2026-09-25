from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
EXTRACT_PATH = REPO_ROOT / ".github" / "tools" / "pool-sync" / "extract_nuggets.ps1"


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _run_extract(repo_root: Path, version: str, *, max_pending: int | None = None) -> subprocess.CompletedProcess[str]:
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(EXTRACT_PATH),
        "-Version",
        version,
        "-RepoRoot",
        str(repo_root),
    ]
    if max_pending is not None:
        cmd.extend(["-MaxPending", str(max_pending)])
    return subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _commit_file(repo_root: Path, relative_path: str, content: str, message: str) -> str:
    path = repo_root / relative_path
    _write(path, content)
    _git(repo_root, "add", relative_path)
    _git(repo_root, "commit", "-m", message)
    return _git(repo_root, "rev-parse", "--short", "HEAD")


def _init_release_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "release-repo"
    repo_root.mkdir()
    _git(repo_root, "init")
    _git(repo_root, "config", "user.email", "nuggets@example.com")
    _git(repo_root, "config", "user.name", "Nugget Test")
    _commit_file(repo_root, "README.md", "base\n", "chore: initial baseline")
    _git(repo_root, "tag", "v2026.05.20.1")
    return repo_root


@pytest.mark.skipif(sys.platform != "win32", reason="powershell.exe is Windows-only")
def test_extract_nuggets_writes_only_inbox_and_filters_supported_commit_types(tmp_path: Path) -> None:
    repo_root = _init_release_repo(tmp_path)
    _commit_file(repo_root, "feature.txt", "feat one\n", "feat: add release summary view")
    _commit_file(repo_root, "docs.txt", "docs\n", "docs: refresh operator notes")
    _commit_file(repo_root, "fix.txt", "fix one\n", "fix: preserve handoff state")
    _commit_file(repo_root, "fix2.txt", "fix two\n", "fix: preserve handoff state")
    _commit_file(repo_root, "perf.txt", "perf\n", "perf: reduce pool diff latency")
    _commit_file(repo_root, "refactor.txt", "refactor\n", "refactor: split pool deploy helper")
    _commit_file(repo_root, "chore.txt", "chore\n", "chore: clean local comments")

    result = _run_extract(repo_root, "v2026.05.21.1")

    assert result.returncode == 0, result.stderr
    inbox_path = repo_root / ".github" / "agent-docs" / "nuggets-inbox.md"
    inbox_text = inbox_path.read_text(encoding="utf-8")

    assert inbox_text.count("## CANDIDATE ") == 4
    assert "- source: ci-release-capture" in inbox_text
    assert "- raw: feat: add release summary view" in inbox_text
    assert "- raw: fix: preserve handoff state" in inbox_text
    assert "- raw: perf: reduce pool diff latency" in inbox_text
    assert "- raw: refactor: split pool deploy helper" in inbox_text
    assert "docs: refresh operator notes" not in inbox_text
    assert "chore: clean local comments" not in inbox_text
    assert inbox_text.count("- raw: fix: preserve handoff state") == 1
    assert ", " in inbox_text.split("- raw: fix: preserve handoff state", 1)[0]

    status_lines = [
        line.strip()
        for line in _git(repo_root, "status", "--short", "--untracked-files=all").splitlines()
        if line.strip()
    ]
    assert status_lines == ['?? .github/agent-docs/nuggets-inbox.md']


@pytest.mark.skipif(sys.platform != "win32", reason="powershell.exe is Windows-only")
def test_extract_nuggets_rerun_does_not_duplicate_existing_candidates(tmp_path: Path) -> None:
    repo_root = _init_release_repo(tmp_path)
    _commit_file(repo_root, "feature.txt", "feat one\n", "feat: add release summary view")

    first = _run_extract(repo_root, "v2026.05.21.1")
    second = _run_extract(repo_root, "v2026.05.21.1")

    assert first.returncode == 0
    assert second.returncode == 0
    assert "Nothing appended." in second.stdout

    inbox_text = (repo_root / ".github" / "agent-docs" / "nuggets-inbox.md").read_text(encoding="utf-8")
    assert inbox_text.count("## CANDIDATE ") == 1
    assert inbox_text.count("- raw: feat: add release summary view") == 1


@pytest.mark.skipif(sys.platform != "win32", reason="powershell.exe is Windows-only")
def test_extract_nuggets_honors_pending_cap(tmp_path: Path) -> None:
    repo_root = _init_release_repo(tmp_path)
    _commit_file(repo_root, "feature.txt", "feat one\n", "feat: add release summary view")

    pending_blocks = []
    for index in range(15):
        pending_blocks.append(
            "\n".join(
                [
                    f"## CANDIDATE 2026-05-{index + 1:02d} · v2026.05.{index + 1:02d}.1",
                    f"- fingerprint: fp{index:02d}",
                    "- source: ci-release-capture",
                    "- shape: project-local",
                    "- category: (unrouted - set at review)",
                    "- suggested-route: keep-local",
                    "- proposed-target: (unrouted - set at review)",
                    f"- from-commits: sha{index:02d}",
                    f"- raw: feat: existing candidate {index}",
                    f"- nugget: feat: existing candidate {index}",
                    "- status: pending",
                    "",
                ]
            )
        )
    inbox_text = (
        "# Nugget Inbox\n\n"
        "> Existing pending items.\n\n"
        + "".join(pending_blocks)
    )
    _write(repo_root / ".github" / "agent-docs" / "nuggets-inbox.md", inbox_text)

    result = _run_extract(repo_root, "v2026.05.21.1")

    assert result.returncode == 0, result.stderr
    assert "Inbox full (15 pending >= 15)" in result.stdout
    updated_text = (repo_root / ".github" / "agent-docs" / "nuggets-inbox.md").read_text(encoding="utf-8")
    assert updated_text == inbox_text
