"""Close a lane's git worktree after its PR merged: compare content, then remove the worktree and its branches.

Refuses (exit 1) when the PR is not merged, the worktree has commits the PR head does not contain, the merged files differ
from the PR head, a named port still listens, the worktree is dirty, or the worktree holds a junction or symlink. The PR
may be a combined release PR: the lane branch need not be the PR's head branch, only contained in its head. The remote
branch is deleted only when its tip is contained in the PR head; a branch someone pushed to after the merge is kept,
because deleting it would lose work that is not on main.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
from typing import Callable, Sequence

try:
    import caddis_exit
except ModuleNotFoundError as exc:
    if exc.name != "caddis_exit":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-harness" / "scripts"))
    import caddis_exit

try:
    import caddis_worktree_safety
except ModuleNotFoundError as exc:
    if exc.name != "caddis_worktree_safety":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import caddis_worktree_safety


def _is_symlink_or_reparse(p: Path | str) -> bool:
    """Return True if path is a symlink or Windows reparse point."""
    try:
        path_obj = Path(p)
        if os.path.islink(path_obj):
            return True
        st = os.lstat(path_obj)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", None)
        if reparse_flag is not None and hasattr(st, "st_file_attributes"):
            if bool(st.st_file_attributes & reparse_flag):
                return True
    except OSError:
        pass
    return False


def _same_path(p1: str | Path, p2: str | Path) -> bool:
    """Compare two paths for equality accounting for Windows semantics."""
    try:
        if Path(p1).resolve() == Path(p2).resolve():
            return True
    except Exception:
        pass
    return os.path.normcase(os.path.abspath(str(p1))) == os.path.normcase(os.path.abspath(str(p2)))


def close_worktree(
    *,
    repo: Path,
    worktree: Path,
    pr: int,
    gh: Callable[[list[str]], str],
    ports: Sequence[int] = (),
    dry_run: bool = False,
) -> int:
    """Close a worktree after verifying PR merge and cleanliness."""
    if _is_symlink_or_reparse(worktree):
        # Checked on the path as given: resolve() would follow the junction and hide it.
        print(f"refuse: worktree folder {worktree} is a junction or symlink; deleting through it destroys its target")
        return caddis_exit.BLOCKED
    repo = Path(repo).resolve()
    worktree = Path(worktree).resolve()

    # 1. Resolve worktree and find it in git -C repo worktree list --porcelain
    proc = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        print(f"git worktree list failed: {proc.stderr.strip()}", file=sys.stderr)
        return caddis_exit.ERROR

    blocks: list[dict[str, str]] = []
    current_block: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            if current_block:
                blocks.append(current_block)
                current_block = {}
            continue
        if line.startswith("worktree "):
            if current_block:
                blocks.append(current_block)
                current_block = {}
            current_block["worktree"] = line[len("worktree "):].strip()
        elif line.startswith("HEAD "):
            current_block["HEAD"] = line[len("HEAD "):].strip()
        elif line.startswith("branch "):
            current_block["branch"] = line[len("branch "):].strip()
        elif line == "detached":
            current_block["detached"] = "true"
    if current_block:
        blocks.append(current_block)

    if not blocks:
        print(f"No worktrees found for repo {repo}", file=sys.stderr)
        return caddis_exit.ERROR

    # First entry is the main checkout
    if _same_path(blocks[0].get("worktree", ""), worktree):
        print(f"refuse: {worktree} is the main checkout (first entry); will not remove", file=sys.stderr)
        return caddis_exit.ERROR

    target_block: dict[str, str] | None = None
    for b in blocks[1:]:
        if _same_path(b.get("worktree", ""), worktree):
            target_block = b
            break

    if target_block is None:
        print(f"refuse: {worktree} is not listed in worktrees of {repo}", file=sys.stderr)
        return caddis_exit.ERROR

    branch_ref = target_block.get("branch", "")
    if branch_ref.startswith("refs/heads/"):
        branch_name = branch_ref[len("refs/heads/"):]
    elif branch_ref:
        branch_name = branch_ref
    else:
        print(f"refuse: worktree {worktree} has no branch (detached)", file=sys.stderr)
        return caddis_exit.ERROR

    # 2. gh pr view
    try:
        raw_json = gh(["pr", "view", str(pr), "--json", "state,mergeCommit,headRefOid,headRefName"])
        pr_data = json.loads(raw_json)
    except Exception as exc:
        detail = getattr(exc, "stderr", "") or ""
        print(f"refuse: failed to view PR #{pr}: {exc} {detail}".rstrip())
        return caddis_exit.BLOCKED

    state = pr_data.get("state")
    merge_commit = pr_data.get("mergeCommit")
    merge_oid = merge_commit.get("oid") if isinstance(merge_commit, dict) else None
    head_ref_oid = pr_data.get("headRefOid")

    if state != "MERGED" or not merge_oid:
        print(f"refuse: PR #{pr} is not merged")
        return caddis_exit.BLOCKED

    # 3. git fetch origin --prune; git fetch origin <headRefOid>; cat-file
    subprocess.run(["git", "-C", str(repo), "fetch", "-q", "origin", "--prune"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if head_ref_oid:
        subprocess.run(["git", "-C", str(repo), "fetch", "-q", "origin", str(head_ref_oid)], capture_output=True, text=True, encoding="utf-8", errors="replace")

    proc = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-e", f"{head_ref_oid}^{{commit}}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        print(f"refuse: PR head commit {head_ref_oid} not found in repo")
        return caddis_exit.BLOCKED

    # 4. Unpushed work
    proc = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        print(f"refuse: failed to get HEAD of worktree {worktree}")
        return caddis_exit.BLOCKED

    wt_head = proc.stdout.strip()
    if wt_head != head_ref_oid:
        proc_ancestor = subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", wt_head, str(head_ref_oid)],
            capture_output=True,
            text=True,
        )
        if proc_ancestor.returncode != 0:
            print("refuse: worktree has commits the PR does not")
            return caddis_exit.BLOCKED

    # 5. Content compare
    proc = subprocess.run(
        ["git", "-C", str(repo), "diff", "--name-only", f"{merge_oid}^", merge_oid],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        print(f"git diff failed for {merge_oid}^ {merge_oid}: {proc.stderr.strip()}", file=sys.stderr)
        return caddis_exit.ERROR

    files = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    files_compared = len(files)
    if files:
        proc_diff = subprocess.run(
            ["git", "-C", str(repo), "diff", "--quiet", str(head_ref_oid), merge_oid, "--", *files],
            capture_output=True,
            text=True,
        )
        if proc_diff.returncode != 0:
            print("refuse: PR head differs from the merged content; not deleted")
            return caddis_exit.BLOCKED

    # 6. Ports
    for port in ports:
        try:
            with socket.create_connection(("127.0.0.1", int(port)), timeout=0.5):
                print(f"refuse: a server still listens on {port}")
                return caddis_exit.BLOCKED
        except (OSError, socket.timeout):
            pass

    # 7. Dirty
    proc = subprocess.run(
        ["git", "-C", str(worktree), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        print(f"git status failed on worktree {worktree}: {proc.stderr.strip()}", file=sys.stderr)
        return caddis_exit.ERROR

    dirty = proc.stdout.strip()
    if dirty:
        print(f"refuse: worktree {worktree} is dirty:\n{dirty}")
        return caddis_exit.BLOCKED

    # 8. Junction or symlink guard
    if _is_symlink_or_reparse(worktree):
        print(f"refuse: worktree folder {worktree} is a junction or symlink; deleting through a junction destroys its target")
        return caddis_exit.BLOCKED

    if worktree.is_dir():
        try:
            for item in worktree.iterdir():
                if _is_symlink_or_reparse(item):
                    print(f"refuse: entry {item} inside worktree is a junction or symlink; deleting through a junction destroys its target")
                    return caddis_exit.BLOCKED
        except OSError as exc:
            print(f"refuse: failed to inspect worktree {worktree}: {exc}")
            return caddis_exit.BLOCKED

    # 9. dry_run
    if dry_run:
        print(f"would remove {worktree}, branch {branch_name} (local and origin)")
        return caddis_exit.CLEAN

    # 10. Remove. Step 8 checks only the top level; the helper unlinks every deeper link before git removes the tree.
    problem = caddis_worktree_safety.safe_remove_worktree(repo, worktree)
    if problem:
        print(f"failed command: git -C {repo} worktree remove --force {worktree}\n{problem}", file=sys.stderr)
        return caddis_exit.ERROR

    cmd_br_d = ["git", "-C", str(repo), "branch", "-D", branch_name]
    proc = subprocess.run(cmd_br_d, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        print(f"failed command: {' '.join(cmd_br_d)}\n{proc.stderr.strip() or proc.stdout.strip()}", file=sys.stderr)
        return caddis_exit.ERROR

    cmd_ls = ["git", "-C", str(repo), "ls-remote", "--exit-code", "--heads", "origin", branch_name]
    proc_ls = subprocess.run(cmd_ls, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc_ls.returncode not in (0, 2):  # 2 = no such branch; anything else = origin could not be read
        print(f"WARNING: could not read origin (ls-remote exit {proc_ls.returncode}); origin/{branch_name} not deleted")
    remote_tip = proc_ls.stdout.split()[0] if proc_ls.returncode == 0 and proc_ls.stdout.split() else ""
    contained = remote_tip == head_ref_oid or (remote_tip and subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", remote_tip, str(head_ref_oid)],
        capture_output=True, text=True, encoding="utf-8", errors="replace").returncode == 0)
    if remote_tip and not contained:
        # Someone pushed after the merge: that work is not in main. Keep the remote branch.
        print(f"kept origin/{branch_name}: its tip {remote_tip[:12]} is not contained in the merged PR head {str(head_ref_oid)[:12]}")
    elif remote_tip:
        # The check above is followed by a compare-and-delete on the server: a push that lands in between wins.
        cmd_push_del = ["git", "-C", str(repo), *caddis_worktree_safety.remote_delete_args(branch_name, remote_tip)]
        proc = subprocess.run(cmd_push_del, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            # A push that landed after our check makes the server refuse the compare-and-delete. That is the same
            # outcome as the "kept" path above, not an error: look at the remote again.
            again = subprocess.run(cmd_ls, capture_output=True, text=True, encoding="utf-8", errors="replace")
            new_tip = again.stdout.split()[0] if again.returncode == 0 and again.stdout.split() else ""
            if new_tip and new_tip != remote_tip:
                print(f"kept origin/{branch_name}: its tip moved from {remote_tip[:12]} to {new_tip[:12]} while it was being deleted")
            else:
                print(f"failed command: {' '.join(cmd_push_del)}\n{proc.stderr.strip() or proc.stdout.strip()}", file=sys.stderr)
                return caddis_exit.ERROR

    # No `git worktree prune`: `git worktree remove` (above) dropped this registration, and a prune would also drop
    # the registrations of other tools whose folders are missing for the moment (robustness #19).

    print(f"removed {worktree} ({branch_name}); merge {merge_oid}; files compared: {files_compared}")
    return caddis_exit.CLEAN


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for caddis_worktree_close."""
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(description="Close a worktree after PR merge.")
    parser.add_argument("--repo", required=True, type=Path, help="Path to main repository")
    parser.add_argument("--worktree", required=True, type=Path, help="Path to worktree to close")
    parser.add_argument("--pr", required=True, type=int, help="PR number")
    parser.add_argument(
        "--port",
        dest="ports",
        type=int,
        nargs="+",
        action="extend",
        default=[],
        help="Ports to check for listening servers",
    )
    parser.add_argument("--dry-run", action="store_true", default=False, help="Dry run mode")

    args = parser.parse_args(argv)

    def real_gh(gh_args: list[str]) -> str:
        proc = subprocess.run(
            ["gh", *gh_args],
            cwd=str(args.repo),
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout

    return close_worktree(
        repo=args.repo,
        worktree=args.worktree,
        pr=args.pr,
        gh=real_gh,
        ports=tuple(args.ports),
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
