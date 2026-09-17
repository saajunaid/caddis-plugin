#!/usr/bin/env python3
"""Multi-Model Review & Runner (MMR) for Caddis.

Executes ad-hoc tasks across model lanes (GLM -> Codex -> Claude) in an isolated
sandbox with automatic rate-limit failover, test gates, cross-vendor review,
and immediate worktree cleanup. Also performs direct diff reviews.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_CONFIG = 3


def repo_root(start: Path | None = None) -> Path:
    anchor = Path.cwd() if start is None else start.resolve()
    try:
        raw = subprocess.check_output(
            ["git", "-C", str(anchor), "rev-parse", "--show-toplevel"],
            text=True,
            encoding="utf-8",
            errors="replace",
        ).strip()
        return Path(raw).resolve()
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f"[mmr] error: {anchor} is not inside a git repository\n")
        sys.exit(EXIT_CONFIG)


def git_output(repo: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if res.returncode != 0:
        return ""
    return res.stdout.strip()


def check_dirty(repo: Path) -> list[str]:
    output = git_output(repo, "status", "--porcelain")
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    dirty_files: list[str] = []
    for line in lines:
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            dirty_files.append(parts[1])
    return dirty_files


def check_keys(repo: Path, keys_file: Path | None = None) -> dict[str, bool]:
    kfile = keys_file if keys_file is not None else Path.home() / ".caddis" / "keys.env"
    file_env: dict[str, str] = {}
    if kfile.is_file():
        try:
            for line in kfile.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    file_env[k.strip()] = v.strip()
        except OSError:
            pass

    def has_key(var: str) -> bool:
        return bool(os.environ.get(var) or file_env.get(var))

    return {
        "deepseek": has_key("DEEPSEEK_API_KEY") or has_key("REVIEW_API_KEY"),
        "glm": has_key("GLM_API_KEY"),
        "openai": has_key("OPENAI_API_KEY") or has_key("CODEX_API_KEY"),
        "anthropic": has_key("ANTHROPIC_API_KEY"),
    }


def find_lanes_script(repo: Path) -> Path:
    sibling = Path(__file__).resolve().with_name("caddis_lanes.py")
    if sibling.is_file():
        return sibling
    in_repo = repo / "scripts" / "caddis_lanes.py"
    if in_repo.is_file():
        return in_repo
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        candidate = Path(plugin_root) / "scripts" / "caddis_lanes.py"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("caddis_lanes.py not found")


def slugify_prompt(prompt: str) -> str:
    first_line = prompt.strip().splitlines()[0] if prompt.strip() else "task"
    cleaned = re.sub(r"[^\w\s-]", "", first_line).strip().lower()
    words = cleaned.split()[:5]
    slug = "-".join(words)[:50].rstrip("-")
    if not slug:
        slug = "task"
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"{date_str}-{slug}"


def synthesize_plan(
    repo: Path,
    prompt: str,
    task_type: str,
) -> tuple[Path, str, str]:
    slug = slugify_prompt(prompt)
    first_line = prompt.strip().splitlines()[0] if prompt.strip() else "Ad-hoc task"
    title = first_line[:60].strip()

    adhoc_dir = repo / ".caddis" / "orchestrator" / "adhoc"
    adhoc_dir.mkdir(parents=True, exist_ok=True)

    plan_path = adhoc_dir / f"{slug}.md"
    plan_content = f"""# Ad-hoc Task: {title}

### Phase 1 — {title}
**Lane:** auto (via caddis_lanes)
**Type:** {task_type}

**Task:**
{prompt.strip()}

**Constraints:**
- Do NOT install or introduce new third-party dependencies. Use existing repository packages and standard library only.
- Follow TDD: write or update test assertions first, then implement.
- Leave all changes in the working directory. Do NOT run git commit, push, or merge.

**Done when:**
Task requirements are met, existing tests pass, and new test assertions verify the implementation.
"""
    plan_path.write_text(plan_content, encoding="utf-8")
    return plan_path, slug, title


def adhoc_latest_path(repo: Path) -> Path:
    return repo / ".caddis" / "orchestrator" / "adhoc" / "latest.json"


def read_latest(repo: Path) -> dict | None:
    path = adhoc_latest_path(repo)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def run_adhoc(
    repo: Path,
    prompt: str,
    task_type: str = "backend",
    lane: str | None = None,
    allow_load: bool = False,
) -> int:
    dirty = check_dirty(repo)
    head_sha = git_output(repo, "rev-parse", "HEAD")
    if dirty:
        print(f"[mmr] Notice: Working tree has {len(dirty)} uncommitted changes.")
        print(f"[mmr] Sandbox branched from HEAD ({head_sha[:7]}). Uncommitted files remain untouched.")
        for d in dirty:
            if d.lower() in prompt.lower():
                print(f"[mmr] Warning: '{d}' has local uncommitted changes. Sandbox runs against committed HEAD.")

    keys = check_keys(repo)
    if not keys.get("glm") and not keys.get("openai") and not lane:
        print("[mmr] Note: Secondary vendor keys (GLM/Codex) not detected in ~/.caddis/keys.env.")
        print("[mmr] Running on available lanes. Run 'caddis keys' to enable cheap background lanes.")

    plan_path, slug, title = synthesize_plan(repo, prompt, task_type)
    plan_rel = plan_path.relative_to(repo).as_posix()

    try:
        lanes_script = find_lanes_script(repo)
    except FileNotFoundError as exc:
        sys.stderr.write(f"[mmr] error: {exc}\n")
        return EXIT_CONFIG

    cmd = [
        sys.executable,
        str(lanes_script),
        "run",
        "--plan",
        plan_rel,
        "--phase",
        "1",
        "--type",
        task_type,
    ]
    if lane:
        cmd.extend(["--lane", lane])
    if allow_load:
        cmd.append("--allow-load")

    print(f"[mmr] Starting isolated task run: {title}")
    res = subprocess.run(cmd, cwd=repo)

    packet_path = (
        repo
        / ".caddis"
        / "orchestrator"
        / "lane-runs"
        / slug
        / "phase-01.attempt-1.json"
    )
    if not packet_path.is_file():
        sys.stderr.write(f"[mmr] error: lane run packet not generated at {packet_path}\n")
        return res.returncode or EXIT_FAIL

    try:
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"[mmr] error: failed to read packet: {exc}\n")
        return EXIT_FAIL

    worktree_str = packet.get("worktree")
    changed_files = packet.get("changed_files", [])
    gates_passed = packet.get("gates_passed", False)
    review_info = packet.get("review", {})
    review_status = review_info.get("status", "MISSING")
    assigned_lane = packet.get("lane", "")
    assigned_model = packet.get("model", "")
    adhoc_branch = f"lane/adhoc-{slug}"
    commit_sha = packet.get("base_sha", head_sha)

    # Teardown worktree immediately to prevent leaks
    if worktree_str:
        wt_path = Path(worktree_str)
        if wt_path.exists():
            if changed_files:
                try:
                    subprocess.run(
                        ["git", "-C", str(wt_path), "add", "--", *changed_files],
                        check=True,
                        capture_output=True,
                    )
                    commit_res = subprocess.run(
                        ["git", "-C", str(wt_path), "commit", "-m", f"adhoc({slug}): {title}"],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                    )
                    if commit_res.returncode == 0:
                        commit_sha = git_output(wt_path, "rev-parse", "HEAD")
                except Exception as exc:
                    print(f"[mmr] notice: commit in worktree skipped: {exc}")

            # Point adhoc_branch to the result commit
            subprocess.run(
                ["git", "-C", str(repo), "branch", "-f", adhoc_branch, commit_sha],
                capture_output=True,
            )

            # Cleanly remove the worktree
            subprocess.run(
                ["git", "-C", str(repo), "worktree", "remove", "--force", str(wt_path)],
                capture_output=True,
            )
            subprocess.run(["git", "-C", str(repo), "worktree", "prune"], capture_output=True)

            # Clean up the phase-specific attempt branch
            attempt_branch = packet.get("branch")
            if attempt_branch and attempt_branch != adhoc_branch:
                subprocess.run(
                    ["git", "-C", str(repo), "branch", "-D", attempt_branch],
                    capture_output=True,
                )

    diff_stat = git_output(repo, "diff", "--shortstat", packet.get("base_sha", head_sha), adhoc_branch)
    diff_names = git_output(repo, "diff", "--name-only", packet.get("base_sha", head_sha), adhoc_branch).splitlines()

    # Check for dependency file modifications
    dep_files = {"package.json", "requirements.txt", "pyproject.toml", "Cargo.toml", "go.mod", "pom.xml"}
    modified_deps = [f for f in diff_names if Path(f).name in dep_files]

    # Save state to latest.json
    state = {
        "slug": slug,
        "title": title,
        "task": prompt,
        "task_type": task_type,
        "branch": adhoc_branch,
        "base_sha": packet.get("base_sha", head_sha),
        "commit_sha": commit_sha,
        "changed_files": diff_names,
        "lane": assigned_lane,
        "model": assigned_model,
        "gates_passed": gates_passed,
        "review_status": review_status,
        "diff_stat": diff_stat.strip(),
        "modified_deps": modified_deps,
        "plan_path": plan_rel,
        "created": datetime.now(timezone.utc).isoformat(),
    }
    adhoc_latest_path(repo).write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    # Render Verdict Card
    is_success = gates_passed and review_status == "CLEAN" and not modified_deps
    status_label = "PASS" if is_success else "FAIL"

    card = [
        "┌────────────────────────────────────────────────────────┐",
        f"│ MMR VERDICT: {status_label:<42}│",
        f"│ Task: {title[:48]:<49}│",
        f"│ Branch: {adhoc_branch:<47}│",
        f"│ Model: {assigned_lane or 'auto'} ({assigned_model or 'default'}){' ' * max(0, 39 - len(assigned_lane or '') - len(assigned_model or ''))}│",
        f"│ Diff: {(diff_stat or 'no changes')[:48]:<49}│",
        f"│ Gates: {'PASS' if gates_passed else 'FAILED':<48}│",
        f"│ Review: {review_status:<47}│",
    ]
    if modified_deps:
        card.append(f"│ WARN: New dependencies added ({', '.join(modified_deps)}){' ' * max(0, 16 - len(','.join(modified_deps)))}│")
    card.extend(
        [
            "│                                                        │",
            "│ Actions:                                               │",
            "│   /mmr keep   Keep branch; offers /ship-pr             │",
            "│   /mmr drop   Discard branch and delete task files     │",
            "└────────────────────────────────────────────────────────┘",
        ]
    )
    print("\n" + "\n".join(card) + "\n")
    return EXIT_OK if is_success else EXIT_FAIL


def keep_adhoc(repo: Path) -> int:
    state = read_latest(repo)
    if state is None:
        print("[mmr] No active task found to keep. Run /mmr \"<task>\" first.")
        return EXIT_USAGE

    branch = state.get("branch", "")
    if not branch:
        print("[mmr] Active task record has no branch.")
        return EXIT_USAGE

    branch_sha = git_output(repo, "rev-parse", "--verify", branch)
    if not branch_sha:
        print(f"[mmr] Branch '{branch}' does not exist.")
        return EXIT_FAIL

    current_branch = git_output(repo, "branch", "--show-current")
    if current_branch in ("main", "master"):
        print(f"[mmr] Kept branch: {branch}")
        print(f"[mmr] Direct merge into '{current_branch}' is disabled to protect trunk.")
        print("Recommended next step: Run /ship-pr to open a pull request and verify CI.")
        return EXIT_OK

    dirty = check_dirty(repo)
    if dirty:
        print(f"[mmr] Kept branch: {branch}")
        print(f"[mmr] Working tree has {len(dirty)} uncommitted files. Branch was not merged automatically.")
        print(f"To merge when clean: git merge --squash {branch}")
        return EXIT_OK

    print(f"[mmr] Kept branch: {branch}")
    print(f"To squash onto current branch: git merge --squash {branch}")
    print("Or run /ship-pr to open a pull request.")
    return EXIT_OK


def drop_adhoc(repo: Path) -> int:
    state = read_latest(repo)
    if state is None:
        print("[mmr] No active task found to drop.")
        return EXIT_USAGE

    branch = state.get("branch", "")
    slug = state.get("slug", "")
    title = state.get("title", slug)

    if branch:
        subprocess.run(["git", "-C", str(repo), "branch", "-D", branch], capture_output=True)

    plan_path = state.get("plan_path")
    if plan_path:
        full_plan = repo / plan_path
        if full_plan.is_file():
            full_plan.unlink(missing_ok=True)

    run_dir = repo / ".caddis" / "orchestrator" / "lane-runs" / slug
    if run_dir.is_dir():
        shutil.rmtree(run_dir, ignore_errors=True)

    latest_file = adhoc_latest_path(repo)
    if latest_file.is_file():
        latest_file.unlink(missing_ok=True)

    print(f"[mmr] Dropped task '{title}'.")
    print(f"[mmr] Branch '{branch}' deleted. Workspace is clean and untouched.")
    return EXIT_OK


def status_adhoc(repo: Path) -> int:
    keys = check_keys(repo)
    print("=== Multi-Model Review & Runner (MMR) Status ===")
    print("Lane Providers:")
    print(f"  Anthropic / Claude : {'Ready' if keys.get('anthropic') else 'Default'}")
    print(f"  DeepSeek (Review)  : {'Ready' if keys.get('deepseek') else 'Not configured'}")
    print(f"  GLM-4 / GLM-5      : {'Ready' if keys.get('glm') else 'Not configured'}")
    print(f"  OpenAI / Codex     : {'Ready' if keys.get('openai') else 'Not configured'}")

    state = read_latest(repo)
    if state:
        print("\nActive Task:")
        print(f"  Title   : {state.get('title')}")
        print(f"  Branch  : {state.get('branch')}")
        print(f"  Model   : {state.get('lane')} ({state.get('model')})")
        print(f"  Gates   : {'PASS' if state.get('gates_passed') else 'FAILED'}")
        print(f"  Review  : {state.get('review_status')}")
        print(f"  Diff    : {state.get('diff_stat') or 'none'}")
    else:
        print("\nActive Task: None")

    branches_output = git_output(repo, "branch", "--list", "lane/adhoc-*")
    adhoc_branches = [b.strip().lstrip("* ") for b in branches_output.splitlines() if b.strip()]
    if adhoc_branches:
        print(f"\nUnmerged Ad-hoc Branches ({len(adhoc_branches)}):")
        for b in adhoc_branches:
            print(f"  - {b}")

    return EXIT_OK


def review_diff(repo: Path, git_range: str | None = None) -> int:
    # Resolve oss_review.py
    candidates = [
        repo / "scripts" / "oss_review.py",
        repo / ".github" / "tools" / "oss_review.py",
        Path(__file__).resolve().parent / "oss_review.py",
        Path(__file__).resolve().parents[1] / ".github" / "tools" / "oss_review.py",
    ]
    tool = next((c for c in candidates if c.is_file()), None)
    if tool is None:
        sys.stderr.write("[mmr] error: oss_review.py not found in repo or tools\n")
        return EXIT_CONFIG

    cmd = [sys.executable, str(tool), "--cwd", str(repo)]
    if git_range:
        cmd.extend(["--range", git_range])

    print(f"[mmr] Running Multi-Model Review with {tool.name}...")
    res = subprocess.run(cmd)
    return res.returncode


def main(argv: list[str] | None = None) -> int:
    args_list = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(
        description="Multi-Model Review & Runner (MMR)",
        add_help=True,
    )
    subparsers = parser.add_subparsers(dest="subcommand")

    # run subcommand
    run_parser = subparsers.add_parser("run", help="Run an ad-hoc task across model lanes")
    run_parser.add_argument("prompt", type=str, help="Task prompt or description")
    run_parser.add_argument(
        "--type",
        choices=["backend", "tests", "docs", "ui", "hard"],
        default="backend",
        help="Task type for chain resolution (default: backend)",
    )
    run_parser.add_argument("--lane", type=str, default=None, help="Start chain at specific lane")
    run_parser.add_argument("--allow-load", action="store_true", help="Allow load/stress wording")

    # keep subcommand
    subparsers.add_parser("keep", help="Keep the last ad-hoc branch")

    # drop subcommand
    subparsers.add_parser("drop", help="Discard the last ad-hoc task and clean up")

    # status subcommand
    subparsers.add_parser("status", help="Show lane readiness and active task status")

    # review subcommand
    review_parser = subparsers.add_parser("review", help="Run multi-model review on a git diff")
    review_parser.add_argument("--range", type=str, default=None, help="Git range (e.g. origin/main..HEAD)")

    # Direct shorthand: if first argument is not a known subcommand and not a flag, treat as 'run'
    if args_list and args_list[0] not in ("run", "keep", "drop", "status", "review", "-h", "--help"):
        args_list = ["run", *args_list]

    if not args_list:
        # Default with no arguments: review the current diff
        args_list = ["review"]

    parsed = parser.parse_args(args_list)
    repo = repo_root()

    if parsed.subcommand == "run":
        return run_adhoc(
            repo,
            parsed.prompt,
            task_type=parsed.type,
            lane=parsed.lane,
            allow_load=parsed.allow_load,
        )
    elif parsed.subcommand == "keep":
        return keep_adhoc(repo)
    elif parsed.subcommand == "drop":
        return drop_adhoc(repo)
    elif parsed.subcommand == "status":
        return status_adhoc(repo)
    elif parsed.subcommand == "review":
        return review_diff(repo, git_range=parsed.range)

    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
