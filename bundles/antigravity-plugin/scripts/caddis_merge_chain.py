"""Merge pull requests one at a time, from green CI to a verified deploy, and stop the line at the first problem.

For each PR (design section 11): when BEHIND, update the branch and cancel the old head's runs (force-cancel after
2 minutes); a cancelled run on the head is re-run, never merged on; "no checks reported" waits; a failed check stops;
no merge while a push run is in progress on the default branch; squash merge with --match-head-commit; then the merge
SHA must get a push run, and `caddis_prod_check.py` must pass before the next PR starts. A STOP file is checked before
each update-branch and each merge. --dry-run makes read-only `gh` calls and prints what it would do.

Exit 0 when every PR merged and verified; 1 at the first stop; 3 when the profile cannot be read.

Usage: caddis_merge_chain.py [--repo PATH] [--gh-repo OWNER/NAME] [--docs-only] [--dry-run]
                             [--stop-file PATH ...] <pr> [<pr> ...]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import caddis_exit
    import caddis_prod_check as prod
except ModuleNotFoundError as exc:
    if exc.name not in {"caddis_exit", "caddis_prod_check"}:
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-harness" / "scripts"))
    import caddis_exit
    import caddis_prod_check as prod

MAX_ATTEMPTS = 8
CHECKS_WAIT_MINUTES = 30
PUSH_IDLE_WAIT_MINUTES = 45
FORCE_CANCEL_AFTER_SECONDS = 120
MERGEABLE = ("CLEAN", "HAS_HOOKS")


class Stop(Exception):
    """The line stops: print the reason, merge nothing more."""


@dataclass
class ChainContext(prod.Context):
    stop_files: list[Path] = field(default_factory=list)
    docs_only: bool = False


def _stop_check(ctx: ChainContext, before: str) -> None:
    for path in ctx.stop_files:
        if Path(path).exists():
            raise Stop(f"STOP file {path} exists; nothing more before {before}")


def _view(ctx: ChainContext, pr: int) -> dict:
    return ctx.gh_json("pr", "view", str(pr), "--json",
                       "state,mergeStateStatus,headRefOid,headRefName,mergeCommit")  # type: ignore[return-value]


def _update_branch(ctx: ChainContext, pr: int, branch: str) -> None:
    old = [r["databaseId"] for r in ctx.gh_json("run", "list", "--branch", branch, "--limit", "10",
                                                "--json", "databaseId,status")  # type: ignore[union-attr]
           if r.get("status") != "completed"]
    _stop_check(ctx, "update-branch")
    proc = ctx.gh("pr", "update-branch", str(pr))
    if proc.rc != 0:
        raise Stop(f"update-branch failed on #{pr}: {(proc.err or proc.out).strip()[:300]}")
    ctx.out(f"  #{pr} was behind: branch updated; cancelling {len(old)} old run(s)")
    for run_id in old:
        cancel = ctx.gh("run", "cancel", str(run_id))
        if cancel.rc != 0:
            ctx.out(f"  WARNING: could not cancel run {run_id}: {(cancel.err or cancel.out).strip()[:200]}")
    if not old:
        return
    ctx.clock.sleep(FORCE_CANCEL_AFTER_SECONDS)
    for run_id in old:
        view = ctx.gh_json("run", "view", str(run_id), "--json", "status")
        if view.get("status") != "completed":  # type: ignore[union-attr]
            ctx.out(f"  run {run_id} still {view.get('status')}; force-cancel")  # type: ignore[union-attr]
            repo = ctx.gh_repo or "{owner}/{repo}"
            forced = ctx.gh("api", "-X", "POST", f"repos/{repo}/actions/runs/{run_id}/force-cancel")
            if forced.rc != 0:
                ctx.out(f"  WARNING: force-cancel of run {run_id} failed: {(forced.err or forced.out).strip()[:200]}")


def _head_run(ctx: ChainContext, branch: str, head: str) -> dict | None:
    runs = ctx.gh_json("run", "list", "--event", "pull_request", "--branch", branch, "--limit", "20",
                       "--json", "databaseId,headSha,status,conclusion")
    return next((r for r in runs if r.get("headSha") == head), None)  # type: ignore[union-attr]


def _wait_checks(ctx: ChainContext, pr: int) -> str:
    """Return 'pass', 'fail' or 'cancel'. Raise Stop when no check reports in time."""
    deadline = ctx.clock.now() + CHECKS_WAIT_MINUTES * 60
    while True:
        proc = ctx.gh("pr", "checks", str(pr), "--json", "name,bucket")
        if proc.rc != 0 and not proc.out.strip() and "no checks reported" not in proc.err + proc.out:
            # Auth or network failure: say so now instead of waiting 30 minutes as if no check had started.
            raise Stop(f"#{pr}: gh pr checks failed: {(proc.err or proc.out).strip()[:300]}")
        buckets: list[str] = []
        try:
            buckets = [c.get("bucket", "") for c in prod.json.loads(proc.out)] if proc.out.strip() else []
        except ValueError:
            buckets = []
        if "fail" in buckets:
            return "fail"
        if "cancel" in buckets:
            return "cancel"
        if buckets and "pending" not in buckets:
            return "pass"
        waiting = "no checks reported yet" if not buckets else "checks pending"
        if ctx.clock.now() >= deadline:
            raise Stop(f"#{pr}: {waiting} after {CHECKS_WAIT_MINUTES} min")
        if ctx.dry_run:
            raise Stop(f"#{pr}: {waiting}; a real run would wait")
        ctx.clock.sleep(30)


def _wait_push_idle(ctx: ChainContext) -> None:
    deadline = ctx.clock.now() + PUSH_IDLE_WAIT_MINUTES * 60
    while True:
        busy = [r for r in prod.push_runs(ctx, limit=10) if r.get("status") != "completed"]
        if not busy:
            return
        if ctx.clock.now() >= deadline:
            raise Stop(f"a push run on {ctx.profile.branch} is still in progress after {PUSH_IDLE_WAIT_MINUTES} min")
        ctx.out(f"  push run {busy[0].get('databaseId')} in progress on {ctx.profile.branch}; waiting")
        ctx.clock.sleep(60)


def merge_one(ctx: ChainContext, pr: int) -> str | None:
    """Bring one PR to a merge. Return the merge SHA, or None after a dry run that stops before merging."""
    for _attempt in range(MAX_ATTEMPTS):
        _stop_check(ctx, f"#{pr}")
        view = _view(ctx, pr)
        state, merge_state = view.get("state"), view.get("mergeStateStatus")
        if state == "MERGED":
            sha = (view.get("mergeCommit") or {}).get("oid")
            ctx.out(f"#{pr} already merged at {sha}")
            return sha
        if state != "OPEN":
            raise Stop(f"#{pr} is {state}, not open")
        head, branch = view["headRefOid"], view["headRefName"]
        if merge_state == "BEHIND":
            if ctx.dry_run:
                ctx.out(f"#{pr} is BEHIND: would update-branch, cancel the old runs, wait for checks, then merge")
                return None
            _update_branch(ctx, pr, branch)
            continue
        run = _head_run(ctx, branch, head)
        if run and run.get("conclusion") == "cancelled":
            if ctx.dry_run:
                ctx.out(f"#{pr}: the run on head {head[:12]} was cancelled: would re-run it, never merge on it")
                return None
            ctx.out(f"  #{pr}: run {run['databaseId']} on the head was cancelled; re-running")
            rerun = ctx.gh("run", "rerun", str(run["databaseId"]))
            if rerun.rc != 0:
                ctx.out(f"  WARNING: re-run of {run['databaseId']} refused: {(rerun.err or rerun.out).strip()[:200]}")
            ctx.clock.sleep(60)
            continue
        result = _wait_checks(ctx, pr)
        if result == "fail":
            raise Stop(f"#{pr}: CI failed on head {head[:12]}")
        if result == "cancel":
            continue
        if ctx.dry_run:
            ctx.out(f"#{pr} ({merge_state}): checks green; would wait for idle push runs, then squash-merge {head[:12]}")
            return None
        _wait_push_idle(ctx)
        _stop_check(ctx, f"the merge of #{pr}")
        view = _view(ctx, pr)
        if view.get("state") == "MERGED":
            continue
        if view.get("mergeStateStatus") == "BEHIND" or view.get("headRefOid") != head:
            continue
        if view.get("mergeStateStatus") not in MERGEABLE:
            ctx.out(f"  #{pr}: merge refused (state {view.get('mergeStateStatus')}); waiting")
            ctx.clock.sleep(120)
            continue
        proc = ctx.gh("pr", "merge", str(pr), "--squash", "--match-head-commit", head)
        if proc.rc != 0:
            ctx.out(f"  #{pr}: merge refused: {(proc.err or proc.out).strip()[:300]}")
            ctx.clock.sleep(120)
            continue
        sha = (_view(ctx, pr).get("mergeCommit") or {}).get("oid")
        if not sha:
            raise Stop(f"#{pr}: merge reported success but no merge commit is visible")
        ctx.out(f"#{pr} merged at {sha}")
        return sha
    raise Stop(f"#{pr} did not merge after {MAX_ATTEMPTS} attempts")


def merge_chain(ctx: ChainContext, prs: list[int]) -> int:
    try:
        for pr in prs:
            sha = merge_one(ctx, pr)
            if sha is None:
                ctx.out("dry run: stopping before any write")
                return caddis_exit.CLEAN
            code = prod.check(ctx, sha, docs_only=ctx.docs_only)
            if code != caddis_exit.CLEAN:
                raise Stop(f"the check after #{pr} did not pass; the line stops here")
    except Stop as stop:
        ctx.out(f"STOP: {stop}")
        return caddis_exit.BLOCKED
    except (RuntimeError, ValueError, KeyError) as exc:
        ctx.out(f"STOP: could not read GitHub state: {exc}")
        return caddis_exit.BLOCKED
    ctx.out(("DRY RUN DONE: " if ctx.dry_run else "ALL MERGED AND VERIFIED: ") + ", ".join(f"#{p}" for p in prs))
    return caddis_exit.CLEAN


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("prs", nargs="+", type=int)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--gh-repo", help="OWNER/NAME when the repo's remote is not the one to read")
    parser.add_argument("--profile", type=Path, help="default: <repo>/.caddis/prod-check.toml")
    parser.add_argument("--docs-only", action="store_true", help="the PRs change docs only: expect no deploy")
    parser.add_argument("--dry-run", action="store_true", help="read-only gh calls; print the steps")
    parser.add_argument("--stop-file", type=Path, action="append", default=[],
                        help="extra STOP file (~/.caddis/STOP is always checked)")
    args = parser.parse_args(argv)
    try:
        profile = prod.load_profile(args.repo, args.profile)
    except ValueError as exc:
        print(f"bad profile: {exc}", file=sys.stderr)
        return caddis_exit.NOT_RUN
    ctx = ChainContext(run=prod.real_runner(args.repo), clock=prod.Clock(), profile=profile, repo=args.repo,
                       gh_repo=args.gh_repo, dry_run=args.dry_run, docs_only=args.docs_only,
                       stop_files=[Path.home() / ".caddis" / "STOP", *args.stop_file])
    return merge_chain(ctx, args.prs)


if __name__ == "__main__":
    sys.exit(main())
