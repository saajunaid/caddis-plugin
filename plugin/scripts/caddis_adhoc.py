#!/usr/bin/env python3
"""Multi-Model Review & Runner (MMR) for Caddis.

Executes ad-hoc tasks across model lanes (GLM -> Codex -> Claude) in an isolated
sandbox with automatic rate-limit failover, test gates, cross-vendor review,
and verified worktree cleanup. Also performs direct diff reviews.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import caddis_exit
except ModuleNotFoundError as exc:
    if exc.name != "caddis_exit":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-harness" / "scripts"))
    import caddis_exit

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

EXIT_OK = caddis_exit.CLEAN
EXIT_FAIL = caddis_exit.BLOCKED
EXIT_USAGE = caddis_exit.ERROR
EXIT_CONFIG = caddis_exit.NOT_RUN
EXCLUDED_PREFIXES = (".caddis/orchestrator/",)


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


# Tool caches every gate run regenerates. They are the only ignored files a worktree may be
# removed with: any other ignored file (a local config, a generated .env) may be someone's work.
_DISPOSABLE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"}
_DISPOSABLE_SUFFIXES = (".pyc", ".pyo")
_DISPOSABLE_NAMES = {".coverage"}  # plus .coverage.* (parallel mode), checked below
# node_modules is not a cache but a dependency tree a gate reinstalls; nobody's work lives in it.


def _work_left(porcelain_z: bytes) -> bool:
    """True if `git status --porcelain=v1 -z --ignored` shows anything but tool-cache litter."""
    for entry in porcelain_z.split(b"\0"):
        if not entry:
            continue
        code, path = entry[:2], entry[3:].decode("utf-8", errors="replace").rstrip("/")
        if code != b"!!":
            return True                       # modified, staged or untracked: real work
        parts = path.split("/")
        if (_DISPOSABLE_DIRS.intersection(parts) or path.endswith(_DISPOSABLE_SUFFIXES)
                or parts[-1] in _DISPOSABLE_NAMES or parts[-1].startswith(".coverage.")):
            continue
        return True                           # an ignored file that is not a known cache
    return False


def packet_changed_files(value: object) -> list[str]:
    """Decode the C-style path quoting used by git status --porcelain."""
    if not isinstance(value, list) or not all(isinstance(name, str) for name in value):
        return []
    files = []
    for name in value:
        if name.startswith('"') and name.endswith('"'):
            try:
                # git escapes non-ASCII as UTF-8 octal bytes ("caf\303\251"); decode them as
                # bytes, or a str literal turns each byte into its own code point (mojibake).
                name = ast.literal_eval("b" + name).decode("utf-8")
            except (SyntaxError, ValueError, UnicodeDecodeError):
                return []
        files.append(name)
    return files


def lane_worktrees(repo: Path, *, lane_only: bool = True) -> set[Path]:
    """Return registered paths, optionally limited to branches under lane/."""
    paths: set[Path] = set()
    for entry in git_output(repo, "worktree", "list", "--porcelain").split("\n\n"):
        lines = entry.splitlines()
        branch = next((line for line in lines if line.startswith("branch ")), "")
        worktree = next((line[9:] for line in lines if line.startswith("worktree ")), "")
        if worktree and (not lane_only or branch.startswith("branch refs/heads/lane/")):
            paths.add(Path(worktree).resolve())
    return paths


def packet_worktree(raw: str) -> Path | None:
    """Recover a complete worktree string even when the rest of JSON is truncated."""
    match = re.search(r'"worktree"\s*:\s*("(?:\\.|[^"\\])*")', raw)
    if not match:
        return None
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return Path(value).resolve() if isinstance(value, str) and value else None


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

    before_worktrees = lane_worktrees(repo, lane_only=False)
    print(f"[mmr] Starting isolated task run: {title}")
    lane_error = ""
    try:
        res = subprocess.run(cmd, cwd=repo)
    except Exception as exc:
        lane_error = f"lane crashed: {type(exc).__name__}: {exc}"
        res = None

    packet_path = (
        repo
        / ".caddis"
        / "orchestrator"
        / "lane-runs"
        / slug
        / "phase-01.attempt-1.json"
    )
    packet = None
    raw_packet = ""
    packet_error = "no lane packet"
    try:
        if packet_path.is_file():
            raw_packet = packet_path.read_text(encoding="utf-8")
            packet = json.loads(raw_packet)
            if not isinstance(packet, dict):
                raise ValueError("lane packet is not an object")
    except Exception as exc:
        packet_error = f"failed to read packet: {type(exc).__name__}: {exc}"

    if lane_error or packet is None:
        reason = lane_error or packet_error
        new_worktrees = lane_worktrees(repo) - before_worktrees
        preferred = packet_worktree(raw_packet)
        kept_paths = sorted(new_worktrees, key=str)
        if preferred and preferred.exists() and preferred not in before_worktrees:
            kept_paths = [preferred, *[path for path in kept_paths if path != preferred]]
        for path in kept_paths:
            print(f"KEPT: {path}")
        print(f"[mmr] {reason}")
        state = {
            "slug": slug,
            "title": title,
            "task": prompt,
            "task_type": task_type,
            "branch": f"lane/adhoc-{slug}",
            "base_sha": head_sha,
            "commit_sha": head_sha,
            "changed_files": [],
            "lane": lane or "",
            "model": "",
            "gates_passed": False,
            "review_status": "MISSING",
            "diff_stat": "",
            "modified_deps": [],
            "verdict": "FAIL",
            "kept_worktree": str(kept_paths[0]) if kept_paths else None,
            "reason": reason,
            "plan_path": plan_rel,
            "created": datetime.now(timezone.utc).isoformat(),
        }
        if len(kept_paths) > 1:
            state["kept_worktrees"] = [str(path) for path in kept_paths]
        adhoc_latest_path(repo).write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        return EXIT_FAIL

    worktree_str = packet.get("worktree")
    changed_files = packet_changed_files(packet.get("changed_files", []))
    code_changes = [
        name for name in changed_files
        if not name.replace("\\", "/").startswith(EXCLUDED_PREFIXES)
    ]
    gates_passed = packet.get("gates_passed", False)
    no_tests_collected = any(
        isinstance(gate, dict) and gate.get("returncode") == 5
        and "pytest" in str(gate.get("cmd", ""))
        for gate in packet.get("gates", [])
    )
    if no_tests_collected:
        gates_passed = False
    review_info = packet.get("review", {})
    review_status = review_info.get("status", "MISSING")
    assigned_lane = packet.get("lane", "")
    assigned_model = packet.get("model", "")
    pending = res.returncode == 0 and packet.get("result") == "PENDING"
    adhoc_branch = (packet.get("branch") or f"lane/adhoc-{slug}") if pending else f"lane/adhoc-{slug}"
    base_sha = packet.get("base_sha", head_sha)
    commit_sha = base_sha
    kept_worktree = worktree_str or None
    reason = ""
    verified_names: list[str] = []

    # A failed lane can return before it records changed_files. Never use an empty
    # file list as evidence that its worktree is safe to remove.
    lane_succeeded = res.returncode == 0 and packet.get("result") == "OK"
    dep_files = {"package.json", "requirements.txt", "pyproject.toml", "Cargo.toml", "go.mod", "pom.xml"}
    modified_deps = [name for name in changed_files if Path(name).name in dep_files]
    if pending and (not worktree_str or not Path(worktree_str).is_dir()):
        reason = "PENDING worktree missing"
    elif pending:
        pass
    elif not lane_succeeded:
        reason = f"lane result: {packet.get('result', 'MISSING')} (exit {res.returncode})"
    elif no_tests_collected:
        reason = "no tests collected"
    elif not gates_passed:
        reason = "gates failed"
    elif not code_changes:
        reason = "no code changes"
    elif review_status != "CLEAN":
        reason = f"review is {review_status}"
    elif modified_deps:
        reason = f"dependency files changed: {', '.join(modified_deps)}"
    elif not worktree_str:
        reason = "lane packet has no worktree path"
    elif not Path(worktree_str).exists():
        reason = f"worktree missing: {worktree_str}"
    else:
        wt_path = Path(worktree_str)
        try:
            add_res = subprocess.run(
                ["git", "-C", str(wt_path), "add", "--", *code_changes],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            if add_res.returncode != 0:
                raise subprocess.CalledProcessError(add_res.returncode, add_res.args, stderr=add_res.stderr)
            commit_res = subprocess.run(
                ["git", "-C", str(wt_path), "commit", "-m", f"adhoc({slug}): {title}"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            if commit_res.returncode != 0:
                raise subprocess.CalledProcessError(commit_res.returncode, commit_res.args, stderr=commit_res.stderr)
        except Exception as exc:
            stderr = getattr(exc, "stderr", None) or str(exc)
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            reason = f"commit failed: {stderr.splitlines()[0] if stderr.splitlines() else str(exc)}"

        if not reason:
            try:
                commit_sha = git_output(wt_path, "rev-parse", "HEAD")
            except Exception as exc:
                reason = f"commit verification failed: {type(exc).__name__}: {exc}"
            if not commit_sha:
                reason = reason or "commit verification failed: could not resolve HEAD"
            elif not reason:
                try:
                    diff_res = subprocess.run(
                        ["git", "-C", str(wt_path), "diff", "--name-only", "-z", f"{base_sha}..{commit_sha}"],
                        capture_output=True,
                    )
                    if diff_res.returncode != 0:
                        reason = "commit verification failed: git diff failed"
                    else:
                        verified_names = [name.decode("utf-8", errors="replace") for name in diff_res.stdout.split(b"\0") if name]
                        if not verified_names or set(verified_names) != set(code_changes):
                            reason = "commit verification failed: committed files differ from reported files"
                    if not reason:
                        # The lane copied our generated plan into its worktree. Remove only that
                        # exact copy; any edited plan or other excluded file remains protected.
                        generated_plan = wt_path / plan_rel
                        if (plan_rel in changed_files and generated_plan.is_file()
                                and generated_plan.read_bytes() == plan_path.read_bytes()):
                            generated_plan.unlink()
                        status_res = subprocess.run(
                            ["git", "-C", str(wt_path), "status", "--porcelain=v1", "-z",
                             "--untracked-files=all", "--ignored"],
                            capture_output=True,
                        )
                        if status_res.returncode != 0 or _work_left(status_res.stdout):
                            reason = "commit verification failed: uncommitted or ignored work remains"
                except Exception as exc:
                    reason = f"commit verification failed: {type(exc).__name__}: {exc}"

        if not reason:
            try:
                branch_res = subprocess.run(
                    ["git", "-C", str(repo), "branch", "-f", adhoc_branch, commit_sha],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                )
                if branch_res.returncode != 0:
                    reason = f"branch update failed: {branch_res.stderr.strip()}"
                else:
                    remove_res = subprocess.run(
                        ["git", "-C", str(repo), "worktree", "remove", "--force", str(wt_path)],
                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                    )
                    if remove_res.returncode != 0 or wt_path.exists():
                        reason = f"worktree remove failed: {remove_res.stderr.strip() or wt_path}"
                    else:
                        kept_worktree = None
                        subprocess.run(["git", "-C", str(repo), "worktree", "prune"], capture_output=True)
                        attempt_branch = packet.get("branch")
                        if attempt_branch and attempt_branch != adhoc_branch:
                            subprocess.run(
                                ["git", "-C", str(repo), "branch", "-D", attempt_branch],
                                capture_output=True,
                            )
            except OSError as exc:
                reason = f"worktree cleanup failed: {exc}"

    if reason:
        print(f"[mmr] {reason}")
    if pending and not reason:
        print(f"MMR: PENDING — Claude lane. Worktree kept: {kept_worktree}")
        print(f"NEXT: {packet.get('next', 'claude-implement')} worktree={kept_worktree}")
    if kept_worktree:
        print(f"KEPT: {kept_worktree}")

    diff_ref = commit_sha if verified_names else adhoc_branch
    diff_stat = git_output(repo, "diff", "--shortstat", base_sha, diff_ref)
    diff_names = verified_names or changed_files

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
        "verdict": "PENDING" if pending and not reason else "FAIL" if reason or kept_worktree else "PASS",
        "kept_worktree": kept_worktree,
        "reason": reason,
        "plan_path": plan_rel,
        "created": datetime.now(timezone.utc).isoformat(),
    }
    adhoc_latest_path(repo).write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    # Render Verdict Card
    is_success = not reason and kept_worktree is None
    status_label = "PENDING" if pending and not reason else "PASS" if is_success else "FAIL"
    gates_label = "not run" if not packet.get("gates") else "PASS" if gates_passed else "FAILED"

    card = [
        "┌────────────────────────────────────────────────────────┐",
        f"│ MMR VERDICT: {status_label:<42}│",
        f"│ Task: {title[:48]:<49}│",
        f"│ Branch: {adhoc_branch:<47}│",
        f"│ Model: {assigned_lane or 'auto'} ({assigned_model or 'default'}){' ' * max(0, 39 - len(assigned_lane or '') - len(assigned_model or ''))}│",
        f"│ Diff: {(diff_stat or 'no changes')[:48]:<49}│",
        f"│ Gates: {gates_label:<48}│",
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
    return EXIT_OK if is_success or pending and not reason else EXIT_FAIL


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

    kept_worktree = state.get("kept_worktree")
    if kept_worktree and Path(kept_worktree).resolve() not in lane_worktrees(repo):
        # latest.json is a plain file: never let it point `drop` at a worktree /mmr did not make.
        print(f"[mmr] Refusing to remove {kept_worktree}: not a registered lane/* worktree")
        return EXIT_FAIL
    if kept_worktree:
        removed = subprocess.run(
            ["git", "-C", str(repo), "worktree", "remove", "--force", kept_worktree],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if removed.returncode != 0:
            print(f"[mmr] Could not remove kept worktree: {removed.stderr.strip()}")
            return EXIT_FAIL
        pruned = subprocess.run(
            ["git", "-C", str(repo), "worktree", "prune"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if pruned.returncode != 0:
            print(f"[mmr] Could not prune worktrees: {pruned.stderr.strip()}")
            return EXIT_FAIL

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
        Path(__file__).with_name("oss_review.py"),
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

    if args_list and re.fullmatch(r"[^\s]+\.\.\.?[^\s]*", args_list[0]):
        return review_diff(repo_root(), args_list[0])
    if args_list and args_list[0].startswith("--") and args_list[0] not in ("--help",):
        print(parser.format_usage().strip())
        return EXIT_USAGE

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
