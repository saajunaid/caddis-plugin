"""Check a merge on prod, item by item, from the repo's profile `.caddis/prod-check.toml`.

Items (design section 10): (1) a push run exists for the merge SHA and is not cancelled; (2) the required jobs
succeeded (with --docs-only: the deploy job was skipped); (3) the version endpoint SHA equals the merge SHA or contains
it; (4) the health endpoint JSON has every value `true`, not only HTTP 200; (5) optional: named background jobs were
attempted after the deploy with zero failures. A repo with no profile gets items 1 and 2 only.

Prints one PASS or FAIL line per item and a RESULT line. Exit 0 only when every item passes; 1 when one fails; 3 when
the profile cannot be read; 4 when the SHA is ambiguous or not found. Read-only: it never writes to GitHub or prod.

Usage: caddis_prod_check.py [--repo PATH] [--gh-repo OWNER/NAME] [--docs-only] [--dry-run] <sha>
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, NamedTuple

try:
    import caddis_exit
except ModuleNotFoundError as exc:
    if exc.name != "caddis_exit":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-harness" / "scripts"))
    import caddis_exit

FULL_SHA = re.compile(r"[0-9a-f]{40}")
SHORT_SHA = re.compile(r"[0-9a-f]{4,39}")
POLL_SECONDS = 30


class Proc(NamedTuple):
    rc: int
    out: str
    err: str


Runner = Callable[[list[str]], Proc]


class Clock:
    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


def real_runner(cwd: Path) -> Runner:
    def run(cmd: list[str]) -> Proc:
        try:
            done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        except FileNotFoundError as exc:
            return Proc(127, "", str(exc))
        return Proc(done.returncode, done.stdout, done.stderr)
    return run


@dataclass
class Profile:
    found: bool = False
    branch: str = "main"
    required_jobs: list[str] = field(default_factory=list)
    deploy_job: str = "deploy_prod"
    push_run_wait_minutes: float = 10
    run_wait_minutes: float = 60
    version_url: str | None = None
    version_field: str = "sha"
    health_url: str | None = None
    auth: str = "none"
    timeout_seconds: int = 60
    background: dict | None = None


_KEY_TYPES: dict[str, type | tuple[type, ...]] = {
    "branch": str, "required_jobs": list, "deploy_job": str, "push_run_wait_minutes": (int, float),
    "run_wait_minutes": (int, float), "version_url": str, "version_field": str, "health_url": str, "auth": str,
    "timeout_seconds": int,
}


def load_profile(repo: Path, path: Path | None = None) -> Profile:
    """Read `.caddis/prod-check.toml`. No file is a valid, empty profile. A bad file raises ValueError."""
    path = path or Path(repo) / ".caddis" / "prod-check.toml"
    if not path.is_file():
        return Profile()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"{path}: {exc}") from exc
    ci, prod = data.get("ci", {}), data.get("prod", {})
    background = data.get("background")
    if not isinstance(ci, dict) or not isinstance(prod, dict) or not isinstance(background, (dict, type(None))):
        raise ValueError(f"{path}: [ci], [prod] and [background] must be tables")
    profile = Profile(found=True)
    for key, value in {**ci, **prod}.items():
        expected = _KEY_TYPES.get(key)
        if expected is None:
            raise ValueError(f"{path}: unknown key {key!r}")
        if isinstance(value, bool) or not isinstance(value, expected):
            raise ValueError(f"{path}: {key} has the wrong type")
        if key == "required_jobs" and not all(isinstance(job, str) for job in value):
            raise ValueError(f"{path}: required_jobs must be a list of job names")
        setattr(profile, key, value)
    if profile.auth not in ("none", "ntlm"):
        raise ValueError(f"{path}: auth must be 'none' or 'ntlm'")
    if background is not None:
        need = ("url", "list_key", "name_key", "attempt_key", "failure_key")
        missing = [key for key in need if not isinstance(background.get(key), str)]
        if missing:
            raise ValueError(f"{path}: [background] needs {', '.join(missing)}")
        profile.background = background
    return profile


@dataclass
class Context:
    run: Runner
    clock: Clock
    profile: Profile
    repo: Path
    gh_repo: str | None = None
    dry_run: bool = False
    out: Callable[[str], None] = print

    def gh(self, *args: str) -> Proc:
        cmd = ["gh", *args]
        if self.gh_repo and args and args[0] in ("pr", "run"):
            cmd += ["-R", self.gh_repo]
        return self.run(cmd)

    def gh_json(self, *args: str) -> object:
        proc = self.gh(*args)
        if proc.rc != 0:
            raise RuntimeError(f"gh {' '.join(args[:3])} failed: {(proc.err or proc.out).strip()[:300]}")
        return json.loads(proc.out)


def resolve_sha(ctx: Context, sha: str) -> tuple[int, str]:
    """Return (exit code, full SHA). A full SHA is used as given; a short one is resolved with git."""
    sha = sha.strip().lower()
    if FULL_SHA.fullmatch(sha):
        return caddis_exit.CLEAN, sha
    if not SHORT_SHA.fullmatch(sha):
        ctx.out(f"FAIL sha {sha!r} is not a commit SHA")
        return caddis_exit.ERROR, ""
    for attempt in range(2):
        proc = ctx.run(["git", "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"])
        if proc.rc == 0 and FULL_SHA.fullmatch(proc.out.strip()):
            return caddis_exit.CLEAN, proc.out.strip()
        if "ambiguous" in proc.err:
            ctx.out(f"FAIL short sha {sha} is ambiguous; give more characters")
            return caddis_exit.ERROR, ""
        if attempt == 0:
            ctx.run(["git", "fetch", "-q", "origin"])
    ctx.out(f"FAIL sha {sha} not found, also after git fetch")
    return caddis_exit.ERROR, ""


def push_runs(ctx: Context, limit: int = 20) -> list[dict]:
    return ctx.gh_json("run", "list", "--branch", ctx.profile.branch, "--event", "push", "--limit", str(limit),
                       "--json", "databaseId,headSha,status,conclusion")  # type: ignore[return-value]


def find_push_run(ctx: Context, sha: str) -> dict | None:
    """Wait up to the profile's minutes for a push run of `sha` to appear."""
    deadline = ctx.clock.now() + ctx.profile.push_run_wait_minutes * 60
    while True:
        run = next((r for r in push_runs(ctx) if r.get("headSha") == sha), None)
        if run or ctx.dry_run or ctx.clock.now() >= deadline:
            return run
        ctx.clock.sleep(15)


def wait_run(ctx: Context, run_id: int) -> dict | None:
    """Return the completed run view (status, conclusion, jobs), or None when it does not complete in time."""
    deadline = ctx.clock.now() + ctx.profile.run_wait_minutes * 60
    while True:
        view = ctx.gh_json("run", "view", str(run_id), "--json", "status,conclusion,jobs,headSha")
        if view.get("status") == "completed" or ctx.dry_run:  # type: ignore[union-attr]
            return view  # type: ignore[return-value]
        if ctx.clock.now() >= deadline:
            return None
        ctx.clock.sleep(POLL_SECONDS)


def _jobs(view: dict) -> dict[str, str]:
    return {j.get("name", ""): (j.get("conclusion") or j.get("status") or "") for j in view.get("jobs", [])}


def _deploy_done(view: dict, deploy_job: str) -> datetime | None:
    for job in view.get("jobs", []):
        if job.get("name") == deploy_job and job.get("completedAt"):
            return _utc(job["completedAt"])
    return None


def _utc(text: str) -> datetime:
    when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def check_ci(ctx: Context, sha: str, docs_only: bool) -> tuple[list[str], dict | None]:
    """Items 1 and 2. Return (failed item labels, completed run view)."""
    run = find_push_run(ctx, sha)
    if not run:
        ctx.out(f"FAIL 1 no push run for {sha} on {ctx.profile.branch} after "
                f"{ctx.profile.push_run_wait_minutes:g} min")
        return ["1 push run"], None
    if ctx.dry_run and run.get("status") != "completed":
        ctx.out(f"INFO 1 push run {run['databaseId']} is {run.get('status')}; would wait for it")
        return [], None
    view = wait_run(ctx, run["databaseId"])
    if view is None:
        ctx.out(f"FAIL 1 push run {run['databaseId']} did not complete in {ctx.profile.run_wait_minutes:g} min")
        return ["1 push run"], None
    conclusion = view.get("conclusion") or ""
    if conclusion in ("cancelled", ""):
        ctx.out(f"FAIL 1 push run {run['databaseId']} conclusion {conclusion or 'none'}")
        return ["1 push run"], view
    ctx.out(f"PASS 1 push run {run['databaseId']} completed ({conclusion})")
    jobs = _jobs(view)
    ctx.out("jobs: " + ", ".join(f"{name}={state}" for name, state in jobs.items()))
    deploy = ctx.profile.deploy_job
    if docs_only:
        if jobs.get(deploy) == "skipped" and conclusion == "success":
            ctx.out(f"PASS 2 docs-only: {deploy} skipped, run conclusion success")
            return [], view
        if conclusion != "success":
            ctx.out(f"FAIL 2 docs-only merge, but the run concluded {conclusion}")
            return ["2 jobs"], view
        ctx.out(f"FAIL 2 docs-only merge, but {deploy} = {jobs.get(deploy, 'absent')}; run the full prod check")
        return ["2 jobs"], view
    if not ctx.profile.found:
        if conclusion == "success":
            ctx.out("PASS 2 run conclusion success (no profile: required jobs unknown)")
            return [], view
        ctx.out(f"FAIL 2 run conclusion {conclusion}")
        return ["2 jobs"], view
    bad = {name: jobs.get(name, "absent") for name in ctx.profile.required_jobs if jobs.get(name) != "success"}
    if deploy and jobs.get(deploy) != "success":
        # A code merge that did not deploy fails, also when the job is not listed as required.
        # A repo with no deploy job sets `deploy_job = ""` in its profile.
        bad[deploy] = jobs.get(deploy, "absent")
    if bad:
        skipped = " (skipped without --docs-only)" if bad.get(deploy) == "skipped" else ""
        ctx.out("FAIL 2 " + ", ".join(f"{n}={c}" for n, c in bad.items()) + skipped)
        return ["2 jobs"], view
    ctx.out(f"PASS 2 {', '.join(ctx.profile.required_jobs) or 'no required jobs'} success")
    return [], view


def curl(ctx: Context, url: str) -> tuple[int, object]:
    """GET `url`. Return (HTTP code, parsed JSON or None)."""
    auth = ["--ntlm", "-u", ":"] if ctx.profile.auth == "ntlm" else []
    proc = ctx.run(["curl", "-s", "-m", str(ctx.profile.timeout_seconds), *auth, "-w", "\n%{http_code}", url])
    body, _, code = proc.out.rpartition("\n")
    try:
        status = int(code.strip())
    except ValueError:
        status = 0
    try:
        return status, json.loads(body)
    except ValueError:
        return status, None


def _false_leaves(value: object, path: str = "") -> list[str]:
    """Paths whose leaf value is not exactly True. An empty object counts as not healthy."""
    if isinstance(value, dict):
        if not value:
            return [path or "(empty)"]
        return [p for key, sub in value.items() for p in _false_leaves(sub, f"{path}.{key}" if path else str(key))]
    return [] if value is True else [f"{path}={value!r}"]


def check_version(ctx: Context, sha: str) -> list[str]:
    status, body = curl(ctx, ctx.profile.version_url or "")
    found = body.get(ctx.profile.version_field) if isinstance(body, dict) else None
    if status == 200 and isinstance(found, str) and found:
        if found == sha:
            ctx.out(f"PASS 3 version sha {found}")
            return []
        if ctx.run(["git", "merge-base", "--is-ancestor", sha, found]).rc == 0:
            ctx.out(f"PASS 3 version sha {found} contains {sha}")
            return []
    ctx.out(f"FAIL 3 version sha {found!r} (HTTP {status}) is not {sha} and does not contain it")
    return ["3 version"]


def check_health(ctx: Context) -> list[str]:
    status, body = curl(ctx, ctx.profile.health_url or "")
    bad = _false_leaves(body) if isinstance(body, dict) else ["body is not a JSON object"]
    if status == 200 and not bad:
        ctx.out(f"PASS 4 health {json.dumps(body)}")
        return []
    ctx.out(f"FAIL 4 health HTTP {status}; not true: {', '.join(bad) or '-'}")
    return ["4 health"]


def check_background(ctx: Context, since: datetime | None) -> list[str]:
    spec = ctx.profile.background or {}
    since = since or datetime.now(timezone.utc)
    deadline = ctx.clock.now() + float(spec.get("wait_minutes", 15)) * 60
    while True:
        status, body = curl(ctx, spec["url"])
        jobs = body.get(spec["list_key"]) if isinstance(body, dict) and status == 200 else None
        if not isinstance(jobs, list) or not jobs:
            ctx.out(f"FAIL 5 background list {spec['list_key']!r} missing or empty (HTTP {status})")
            return ["5 background"]
        failed = [(j.get(spec["name_key"]), j.get(spec["failure_key"])) for j in jobs if j.get(spec["failure_key"])]
        late = [j.get(spec["name_key"]) for j in jobs
                if not j.get(spec["attempt_key"]) or _utc(str(j[spec["attempt_key"]])) < since]
        if failed:
            ctx.out(f"FAIL 5 failed background jobs: {failed}")
            return ["5 background"]
        if not late:
            ctx.out(f"PASS 5 {len(jobs)} background jobs attempted after {since:%H:%M:%S} UTC, no failures")
            return []
        if ctx.clock.now() >= deadline:
            ctx.out(f"FAIL 5 not attempted since the deploy: {late}")
            return ["5 background"]
        ctx.clock.sleep(60)


def check(ctx: Context, sha: str, docs_only: bool = False) -> int:
    code, full = resolve_sha(ctx, sha)
    if code != caddis_exit.CLEAN:
        return code
    if not ctx.profile.found:
        ctx.out("no profile .caddis/prod-check.toml: checking items 1 and 2 only")
    try:
        fails, view = check_ci(ctx, full, docs_only)
        if not fails and not docs_only and ctx.profile.found:
            if ctx.dry_run:
                ctx.out("would check items 3 to 5 against prod (version, health, background jobs)")
            else:
                if ctx.profile.version_url:
                    fails += check_version(ctx, full)
                if ctx.profile.health_url:
                    fails += check_health(ctx)
                if ctx.profile.background:
                    fails += check_background(ctx, _deploy_done(view or {}, ctx.profile.deploy_job))
    except (RuntimeError, ValueError, KeyError) as exc:
        ctx.out(f"FAIL could not read CI state: {exc}")
        fails = ["CI state"]
    ctx.out("RESULT PASS" if not fails else "RESULT FAIL " + ", ".join(fails))
    return caddis_exit.CLEAN if not fails else caddis_exit.BLOCKED


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sha")
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--gh-repo", help="OWNER/NAME when the repo's remote is not the one to read")
    parser.add_argument("--profile", type=Path, help="default: <repo>/.caddis/prod-check.toml")
    parser.add_argument("--docs-only", action="store_true", help="the merge changed docs only: expect no deploy")
    parser.add_argument("--dry-run", action="store_true", help="read CI state only; never call prod")
    args = parser.parse_args(argv)
    try:
        profile = load_profile(args.repo, args.profile)
    except ValueError as exc:
        print(f"bad profile: {exc}", file=sys.stderr)
        return caddis_exit.NOT_RUN
    ctx = Context(run=real_runner(args.repo), clock=Clock(), profile=profile, repo=args.repo,
                  gh_repo=args.gh_repo, dry_run=args.dry_run)
    return check(ctx, args.sha, docs_only=args.docs_only)


if __name__ == "__main__":
    sys.exit(main())
