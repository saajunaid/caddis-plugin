from __future__ import annotations

import re
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
POOL_SYNC_PATH = REPO_ROOT / ".github" / "tools" / "pool-sync" / "pool_sync.py"


def _fresh_candidate_date() -> str:
    """A candidate date that is recent enough to stay under the 14-day
    auto-discard threshold in pool_sync._is_stale_pending_candidate, no
    matter when the test suite runs."""
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


def _run_python(
    script: Path,
    *args: str,
    cwd: Path | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        input=input_text,
        check=False,
    )


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


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _base_manifest() -> str:
    return (
        "version: 1\n"
        "private_patterns_from: .github/tools/pool-validator/denylist-exceptions.txt\n"
        "\n"
        "tiers:\n"
        "  managed:\n"
        "    directories:\n"
        "      - instructions\n"
        "      - skills\n"
        "      - tools\n"
        "    files:\n"
        "      - runtime-targets.json\n"
        "  owned:\n"
        "    directories:\n"
        "      - agent-docs\n"
        "      - handoffs\n"
        "    files:\n"
        "      - pool.manifest.yml\n"
        "      - .pool-version\n"
        "      - .junai-profile\n"
        "  managed_region:\n"
        "    files:\n"
        "      - copilot-instructions.md\n"
        "  local_private:\n"
        "    files: []\n"
        "\n"
        "private:\n"
        "  paths:\n"
        "    - skills/vmie/**\n"
        "\n"
        "profiles:\n"
        "  full:\n"
        "    skill_globs:\n"
        "      - \"**\"\n"
        "  frontend-dashboard:\n"
        "    skill_globs:\n"
        "      - frontend/**\n"
        "\n"
        "managed_regions:\n"
        "  copilot-instructions.md:\n"
        "    start_marker: \"<!-- junai:start -->\"\n"
        "    end_marker: \"<!-- junai:end -->\"\n"
    )


def _init_pool_repo(tmp_path: Path) -> tuple[Path, str]:
    pool_root = tmp_path / "pool"
    pool_root.mkdir()
    _git(pool_root, "init")
    _git(pool_root, "config", "user.email", "pool@example.com")
    _git(pool_root, "config", "user.name", "Pool Test")

    _write(pool_root / ".github" / "pool.manifest.yml", _base_manifest())
    _write(pool_root / ".github" / "tools" / "pool-validator" / "denylist-exceptions.txt", "")
    _write(pool_root / "validate_pool.py", "from pathlib import Path\nPath('validate_pool.log').write_text('validated\\n', encoding='utf-8')\n")
    _write(pool_root / ".github" / "runtime-targets.json", "{\n  \"targets\": []\n}\n")
    _write(pool_root / ".github" / "instructions" / "pool-newer.instructions.md", "base pool newer\n")
    _write(pool_root / ".github" / "instructions" / "project-newer.instructions.md", "base project newer\n")
    _write(pool_root / ".github" / "instructions" / "both-changed.instructions.md", "base both changed\n")
    _write(pool_root / ".github" / "instructions" / "same.instructions.md", "same content\n")
    _write(
        pool_root / ".github" / "copilot-instructions.md",
        "user outside base\n<!-- junai:start -->\nbase managed region\n<!-- junai:end -->\n",
    )
    _write(
        pool_root / ".github" / "skills" / "frontend" / "react-dev" / "SKILL.md",
        "---\nname: react-dev\ndescription: React skill\n---\n",
    )
    _write(
        pool_root / ".github" / "skills" / "cloud" / "aws-cdk-development" / "SKILL.md",
        "---\nname: aws-cdk-development\ndescription: Cloud skill\n---\n",
    )
    _write(
        pool_root / ".github" / "skills" / "vmie" / "secret" / "SKILL.md",
        "---\nname: secret\ndescription: Private skill\n---\n",
    )
    _git(pool_root, "add", ".")
    _git(pool_root, "commit", "-m", "base pool state")
    base_sha = _git(pool_root, "rev-parse", "HEAD")

    _write(pool_root / ".github" / "instructions" / "pool-newer.instructions.md", "current pool newer\n")
    _write(pool_root / ".github" / "instructions" / "both-changed.instructions.md", "current pool changed too\n")
    _write(pool_root / ".github" / "instructions" / "pool-only.instructions.md", "only in pool current\n")
    _write(
        pool_root / ".github" / "copilot-instructions.md",
        "outside content changed\n<!-- junai:start -->\nbase managed region\n<!-- junai:end -->\n",
    )
    _git(pool_root, "add", ".")
    _git(pool_root, "commit", "-m", "current pool state")
    return pool_root, base_sha


def _init_project(tmp_path: Path, base_sha: str) -> Path:
    project_root = tmp_path / "project"
    _write(
        project_root / ".github" / ".pool-version",
        json.dumps({"pool_sha": base_sha, "profile": "frontend-dashboard"}, indent=2) + "\n",
    )
    _write(project_root / ".github" / ".junai-profile", "frontend-dashboard\n")
    _write(project_root / ".github" / "instructions" / "pool-newer.instructions.md", "base pool newer\n")
    _write(project_root / ".github" / "instructions" / "project-newer.instructions.md", "project local change\n")
    _write(project_root / ".github" / "instructions" / "both-changed.instructions.md", "project changed too\n")
    _write(project_root / ".github" / "instructions" / "same.instructions.md", "same content\n")
    _write(project_root / ".github" / "instructions" / "project-only.instructions.md", "local only file\n")
    _write(
        project_root / ".github" / "copilot-instructions.md",
        "user changed outside\n<!-- junai:start -->\nbase managed region\n<!-- junai:end -->\n",
    )
    _write(project_root / ".github" / "agent-docs" / "nuggets-inbox.md", "pending nugget\n")
    return project_root


def _git_message(cwd: Path, *args: str) -> str:
    return _git(cwd, "log", "-1", "--format=%B", *args)


def _candidate_block(
    *,
    date: str,
    version: str,
    fingerprint: str,
    raw: str,
    shape: str = "project-local",
    suggested_route: str = "keep-local",
    proposed_target: str = "(unrouted - set at review)",
    commits: str = "abc1234",
    status: str = "pending",
) -> str:
    return (
        f"## CANDIDATE {date} - {version}\n"
        f"- fingerprint: {fingerprint}\n"
        "- source: ci-release-capture\n"
        f"- shape: {shape}\n"
        "- category: (unrouted - set at review)\n"
        f"- suggested-route: {suggested_route}\n"
        f"- proposed-target: {proposed_target}\n"
        f"- from-commits: {commits}\n"
        f"- raw: {raw}\n"
        f"- nugget: {raw}\n"
        f"- status: {status}\n\n"
    )


def _write_inbox(project_root: Path, *blocks: str) -> None:
    _write(
        project_root / ".github" / "agent-docs" / "nuggets-inbox.md",
        "# Nugget Inbox\n\n> Review candidates.\n\n" + "".join(blocks),
    )


def test_pool_status_json_is_valid_when_stamp_missing(tmp_path: Path) -> None:
    pool_root, _ = _init_pool_repo(tmp_path)
    project_root = tmp_path / "project-no-stamp"
    _write(project_root / ".github" / "instructions" / "project-newer.instructions.md", "changed without stamp\n")

    result = _run_python(
        POOL_SYNC_PATH,
        "--pool-root",
        str(pool_root),
        "status",
        "--project",
        str(project_root),
        "--json",
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["stamp_present"] is False
    assert payload["stamp"] is None


def test_pool_diff_json_classifies_drift_and_skips_owned_and_profile_excluded_paths(tmp_path: Path) -> None:
    pool_root, base_sha = _init_pool_repo(tmp_path)
    project_root = _init_project(tmp_path, base_sha)

    result = _run_python(
        POOL_SYNC_PATH,
        "--pool-root",
        str(pool_root),
        "diff",
        "--project",
        str(project_root),
        "--json",
    )
    assert result.returncode == 0

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    entries = {entry["path"]: entry["status"] for entry in payload["entries"]}

    assert entries["instructions/pool-newer.instructions.md"] == "pool-newer"
    assert entries["instructions/project-newer.instructions.md"] == "project-newer"
    assert entries["instructions/both-changed.instructions.md"] == "both-changed"
    assert entries["instructions/project-only.instructions.md"] == "project-only"
    assert entries["instructions/pool-only.instructions.md"] == "pool-only"
    assert entries["skills/frontend/react-dev/SKILL.md"] == "pool-only"

    assert "copilot-instructions.md" not in entries
    assert "agent-docs/nuggets-inbox.md" not in entries
    assert "skills/cloud/aws-cdk-development/SKILL.md" not in entries
    assert "skills/vmie/secret/SKILL.md" not in entries


def test_pool_diff_reports_project_newer_without_stamp_when_project_copy_is_edited(tmp_path: Path) -> None:
    pool_root, _ = _init_pool_repo(tmp_path)
    project_root = tmp_path / "project-edited"
    _write(project_root / ".github" / "instructions" / "project-newer.instructions.md", "edited without stamp\n")

    result = _run_python(
        POOL_SYNC_PATH,
        "--pool-root",
        str(pool_root),
        "diff",
        "--project",
        str(project_root),
        "--json",
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    entries = {entry["path"]: entry["status"] for entry in payload["entries"]}
    assert entries["instructions/project-newer.instructions.md"] == "project-newer"


def test_pool_deploy_writes_stamp_preserves_owned_dirs_and_filters_profile_skills(tmp_path: Path) -> None:
    pool_root, _ = _init_pool_repo(tmp_path)
    project_root = tmp_path / "deploy-project"
    _write(project_root / ".github" / ".junai-profile", "frontend-dashboard\n")
    _write(project_root / ".github" / "agent-docs" / "nuggets-inbox.md", "keep me\n")
    _write(project_root / ".github" / "handoffs" / "note.md", "keep me too\n")
    _write(
        project_root / ".github" / "copilot-instructions.md",
        "project intro\n<!-- junai:start -->\nold region\n<!-- junai:end -->\nproject outro\n",
    )

    deploy_result = _run_python(
        POOL_SYNC_PATH,
        "--pool-root",
        str(pool_root),
        "deploy",
        "--project",
        str(project_root),
        "--json",
    )
    assert deploy_result.returncode == 0
    payload = json.loads(deploy_result.stdout)
    assert payload["ok"] is True
    assert payload["profile"] == "frontend-dashboard"

    stamp = json.loads((project_root / ".github" / ".pool-version").read_text(encoding="utf-8"))
    assert stamp["pool_sha"] == _git(pool_root, "rev-parse", "HEAD")
    assert stamp["profile"] == "frontend-dashboard"
    assert "deployed_at" in stamp

    assert (project_root / ".github" / "agent-docs" / "nuggets-inbox.md").read_text(encoding="utf-8") == "keep me\n"
    assert (project_root / ".github" / "handoffs" / "note.md").read_text(encoding="utf-8") == "keep me too\n"

    assert (project_root / ".github" / "skills" / "frontend" / "react-dev" / "SKILL.md").exists()
    assert not (project_root / ".github" / "skills" / "cloud" / "aws-cdk-development" / "SKILL.md").exists()
    assert not (project_root / ".github" / "skills" / "vmie" / "secret" / "SKILL.md").exists()

    registry_text = (project_root / ".github" / "skills" / "_registry.md").read_text(encoding="utf-8")
    assert "frontend/react-dev/" in registry_text
    assert "cloud/aws-cdk-development/" not in registry_text

    copilot_text = (project_root / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
    assert "project intro" in copilot_text
    assert "project outro" in copilot_text
    assert "base managed region" in copilot_text
    assert "old region" not in copilot_text

    diff_result = _run_python(
        POOL_SYNC_PATH,
        "--pool-root",
        str(pool_root),
        "diff",
        "--project",
        str(project_root),
        "--json",
    )
    assert diff_result.returncode == 0
    diff_payload = json.loads(diff_result.stdout)
    diff_entries = {entry["path"]: entry["status"] for entry in diff_payload["entries"]}
    assert "skills/cloud/aws-cdk-development/SKILL.md" not in diff_entries


def test_pool_promote_dry_run_writes_nothing(tmp_path: Path) -> None:
    pool_root, base_sha = _init_pool_repo(tmp_path)
    project_root = _init_project(tmp_path, base_sha)
    head_before = _git(pool_root, "rev-parse", "HEAD")
    branch_before = _git(pool_root, "branch", "--show-current")
    pool_file_before = (pool_root / ".github" / "instructions" / "project-newer.instructions.md").read_text(encoding="utf-8")

    result = _run_python(
        POOL_SYNC_PATH,
        "--pool-root",
        str(pool_root),
        "promote",
        "--project",
        str(project_root),
        "--dry-run",
        "--select-path",
        "instructions/project-newer.instructions.md",
    )

    assert result.returncode == 0
    assert "Dry run: would promote 1 path(s)." in result.stdout
    assert _git(pool_root, "rev-parse", "HEAD") == head_before
    assert _git(pool_root, "branch", "--show-current") == branch_before
    assert (pool_root / ".github" / "instructions" / "project-newer.instructions.md").read_text(encoding="utf-8") == pool_file_before
    assert not (pool_root / "validate_pool.log").exists()


def test_pool_promote_creates_branch_and_commit_with_provenance(tmp_path: Path) -> None:
    pool_root, base_sha = _init_pool_repo(tmp_path)
    project_root = _init_project(tmp_path, base_sha)

    result = _run_python(
        POOL_SYNC_PATH,
        "--pool-root",
        str(pool_root),
        "promote",
        "--project",
        str(project_root),
        "--reason",
        "Promote reusable local instruction delta",
        "--select-path",
        "instructions/project-newer.instructions.md",
        "--select-path",
        "instructions/project-only.instructions.md",
    )

    assert result.returncode == 0
    current_branch = _git(pool_root, "branch", "--show-current")
    assert re.fullmatch(r"promote/project-\d{8}", current_branch)
    assert f"Branch:  {current_branch}" in result.stdout

    assert (pool_root / ".github" / "instructions" / "project-newer.instructions.md").read_text(encoding="utf-8") == "project local change\n"
    assert (pool_root / ".github" / "instructions" / "project-only.instructions.md").read_text(encoding="utf-8") == "local only file\n"
    assert (pool_root / "validate_pool.log").read_text(encoding="utf-8") == "validated\n"

    commit_message = _git_message(pool_root)
    assert commit_message.startswith("chore(pool): sync reusable changes from project")
    assert f"Source-Project: {project_root.resolve()}" in commit_message
    assert f"Source-Pool-SHA: {base_sha}" in commit_message
    assert "Reason: Promote reusable local instruction delta" in commit_message
    assert "- instructions/project-newer.instructions.md" in commit_message
    assert "- instructions/project-only.instructions.md" in commit_message


def test_pool_promote_managed_region_only_updates_marker_content(tmp_path: Path) -> None:
    pool_root, base_sha = _init_pool_repo(tmp_path)
    project_root = _init_project(tmp_path, base_sha)
    _write(
        project_root / ".github" / "copilot-instructions.md",
        "project outside stays local\n<!-- junai:start -->\nproject managed region\n<!-- junai:end -->\n",
    )

    result = _run_python(
        POOL_SYNC_PATH,
        "--pool-root",
        str(pool_root),
        "promote",
        "--project",
        str(project_root),
        "--select-path",
        "copilot-instructions.md",
    )

    assert result.returncode == 0
    promoted_text = (pool_root / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
    assert "outside content changed" in promoted_text
    assert "project outside stays local" not in promoted_text
    assert "project managed region" in promoted_text
    assert "base managed region" not in promoted_text


def test_pool_promote_refuses_owned_and_private_paths(tmp_path: Path) -> None:
    pool_root, base_sha = _init_pool_repo(tmp_path)
    project_root = _init_project(tmp_path, base_sha)

    result = _run_python(
        POOL_SYNC_PATH,
        "--pool-root",
        str(pool_root),
        "promote",
        "--project",
        str(project_root),
        "--dry-run",
        "--select-path",
        "agent-docs/nuggets-inbox.md",
        "--select-path",
        "skills/vmie/secret/SKILL.md",
    )

    assert result.returncode == 1
    assert "Refused: agent-docs/nuggets-inbox.md (owned content cannot be promoted)" in result.stdout
    assert "Refused: skills/vmie/secret/SKILL.md (private content cannot be promoted)" in result.stdout
    assert "No managed project changes were selected for promotion." in result.stdout


def test_pool_nuggets_review_auto_discards_stale_pending_entries(tmp_path: Path) -> None:
    pool_root, base_sha = _init_pool_repo(tmp_path)
    project_root = _init_project(tmp_path, base_sha)
    _write_inbox(
        project_root,
        _candidate_block(
            date="2024-01-01",
            version="v2024.01.01.1",
            fingerprint="stale001",
            raw="fix: stale candidate",
        ),
    )

    result = _run_python(
        POOL_SYNC_PATH,
        "--pool-root",
        str(pool_root),
        "nuggets",
        "review",
        "--project",
        str(project_root),
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["reviewed_count"] == 1
    assert payload["reviewed"][0]["action"] == "discard"
    assert payload["reviewed"][0]["auto_discarded"] is True

    inbox_text = (project_root / ".github" / "agent-docs" / "nuggets-inbox.md").read_text(encoding="utf-8")
    assert "- status: discarded" in inbox_text
    assert "- reviewed-at:" in inbox_text


def test_pool_nuggets_review_keep_local_writes_inside_project_github(tmp_path: Path) -> None:
    pool_root, base_sha = _init_pool_repo(tmp_path)
    project_root = _init_project(tmp_path, base_sha)
    _write(project_root / ".github" / "instructions" / "handoff-state.instructions.md", "base handoff guidance\n")
    _write_inbox(
        project_root,
        _candidate_block(
            date=_fresh_candidate_date(),
            version="v2026.05.20.1",
            fingerprint="keep001",
            raw="fix: preserve handoff state on release retries",
        ),
    )
    pool_head_before = _git(pool_root, "rev-parse", "HEAD")
    branch_before = _git(pool_root, "branch", "--show-current")

    result = _run_python(
        POOL_SYNC_PATH,
        "--pool-root",
        str(pool_root),
        "nuggets",
        "review",
        "--project",
        str(project_root),
        input_text="Preserve handoff state across release retries.\nk\n",
    )

    assert result.returncode == 0, result.stderr
    assert _git(pool_root, "rev-parse", "HEAD") == pool_head_before
    assert _git(pool_root, "branch", "--show-current") == branch_before

    target_text = (project_root / ".github" / "instructions" / "handoff-state.instructions.md").read_text(encoding="utf-8")
    assert "Preserve handoff state across release retries." in target_text
    inbox_text = (project_root / ".github" / "agent-docs" / "nuggets-inbox.md").read_text(encoding="utf-8")
    assert "- status: kept-local" in inbox_text
    assert "- final-target: instructions/handoff-state.instructions.md" in inbox_text


def test_pool_nuggets_review_promotes_to_pool_branch(tmp_path: Path) -> None:
    pool_root, base_sha = _init_pool_repo(tmp_path)
    project_root = _init_project(tmp_path, base_sha)
    _write(pool_root / ".github" / "instructions" / "release-rules.instructions.md", "base release rules\n")
    _write(project_root / ".github" / "instructions" / "release-rules.instructions.md", "base release rules\n")
    _write_inbox(
        project_root,
        _candidate_block(
            date=_fresh_candidate_date(),
            version="v2026.05.20.1",
            fingerprint="promote001",
            raw="perf: tighten release rules for reviewed promotions",
            shape="rule-shaped",
            suggested_route="promote-to-pool",
            proposed_target="instructions/release-rules.instructions.md",
        ),
    )

    result = _run_python(
        POOL_SYNC_PATH,
        "--pool-root",
        str(pool_root),
        "nuggets",
        "review",
        "--project",
        str(project_root),
        input_text="Tighten release rules after reviewed promotions.\np\n",
    )

    assert result.returncode == 0, result.stderr
    current_branch = _git(pool_root, "branch", "--show-current")
    assert re.fullmatch(r"promote/project-\d{8}", current_branch)
    promoted_text = (pool_root / ".github" / "instructions" / "release-rules.instructions.md").read_text(encoding="utf-8")
    assert "Tighten release rules after reviewed promotions." in promoted_text

    inbox_text = (project_root / ".github" / "agent-docs" / "nuggets-inbox.md").read_text(encoding="utf-8")
    assert "- status: promoted-to-pool" in inbox_text
    assert "- final-target: instructions/release-rules.instructions.md" in inbox_text
    assert "agent-docs/nuggets-inbox.md" not in _git_message(pool_root)


def test_pool_nuggets_review_hides_handled_candidates_on_next_run(tmp_path: Path) -> None:
    pool_root, base_sha = _init_pool_repo(tmp_path)
    project_root = _init_project(tmp_path, base_sha)
    _write_inbox(
        project_root,
        _candidate_block(
            date="2026-05-20",
            version="v2026.05.20.1",
            fingerprint="hide001",
            raw="feat: local note for review",
        ),
    )

    first = _run_python(
        POOL_SYNC_PATH,
        "--pool-root",
        str(pool_root),
        "nuggets",
        "review",
        "--project",
        str(project_root),
        input_text="Keep this note local.\nd\n",
    )
    second = _run_python(
        POOL_SYNC_PATH,
        "--pool-root",
        str(pool_root),
        "nuggets",
        "review",
        "--project",
        str(project_root),
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert "No pending nugget candidates." in second.stdout


def test_pool_nuggets_review_dry_run_writes_nothing_and_returns_json_summary(tmp_path: Path) -> None:
    pool_root, base_sha = _init_pool_repo(tmp_path)
    project_root = _init_project(tmp_path, base_sha)
    _write(project_root / ".github" / "instructions" / "release-rules.instructions.md", "base release rules\n")
    _write_inbox(
        project_root,
        _candidate_block(
            date=_fresh_candidate_date(),
            version="v2026.05.20.1",
            fingerprint="dry001",
            raw="perf: tighten release rules for reviewed promotions",
            shape="rule-shaped",
            suggested_route="promote-to-pool",
            proposed_target="instructions/release-rules.instructions.md",
        ),
    )
    head_before = _git(pool_root, "rev-parse", "HEAD")
    branch_before = _git(pool_root, "branch", "--show-current")
    inbox_before = (project_root / ".github" / "agent-docs" / "nuggets-inbox.md").read_text(encoding="utf-8")
    project_target_before = (project_root / ".github" / "instructions" / "release-rules.instructions.md").read_text(encoding="utf-8")

    result = _run_python(
        POOL_SYNC_PATH,
        "--pool-root",
        str(pool_root),
        "nuggets",
        "review",
        "--project",
        str(project_root),
        "--dry-run",
        "--json",
        input_text="Tighten release rules after reviewed promotions.\np\n",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["reviewed_count"] == 1
    assert payload["reviewed"][0]["action"] == "promote-to-pool"
    assert payload["reviewed"][0]["target_path"] == "instructions/release-rules.instructions.md"
    assert _git(pool_root, "rev-parse", "HEAD") == head_before
    assert _git(pool_root, "branch", "--show-current") == branch_before
    assert (project_root / ".github" / "agent-docs" / "nuggets-inbox.md").read_text(encoding="utf-8") == inbox_before
    assert (project_root / ".github" / "instructions" / "release-rules.instructions.md").read_text(encoding="utf-8") == project_target_before
