"""The session-start hygiene report: worktrees, branches, uncommitted work and the pre-push gate, in ONE line.

Plan: `.caddis/plans/repo-hygiene-report.md` (Phase 3). `repo_freshness._report` calls `report_lines()`, so Claude
Code, Codex and agy all get the report through one function, one process and one time budget.

REPORT ONLY. Nothing here deletes, moves or changes anything. The one file it writes is the gh cache
`<git-common-dir>/caddis-hygiene-prs.json`. Removal is `caddis_tidy.py --hygiene --apply`, which re-proves every
candidate with the deletion-grade test in `caddis_finished.py`.

Every decision lives in `caddis_finished.py` (stdlib only). This module holds the I/O and the formatting. Every git
call goes through the `git(cwd, *args) -> (code, stdout)` seam (`repo_freshness._git` in the hook). gh and orca go
through a `subprocess.run`-shaped seam that never opens a console window.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import NamedTuple


def _import_finished():
    """`caddis_finished`, probed beside this hook: plugin layout, agy flat layout, then the source tree (D1)."""
    here = Path(__file__).resolve().parent
    for cand in (here.parent / "scripts", here / "scripts", here.parent.parent / "scripts"):
        if (cand / "caddis_finished.py").is_file():
            if str(cand) not in sys.path:
                sys.path.append(str(cand))
            try:
                import caddis_finished
            except (ImportError, SyntaxError, OSError):  # a broken file must not crash a session start
                return None
            return caddis_finished
    return None


cf = _import_finished()

ScanResult = tuple[list[dict], int, int]
SCAN_STOP_S = 4.0  # the scan of other repos stops when fewer seconds than this are left
PR_CACHE_NAME = "caddis-hygiene-prs.json"
PR_CACHE_MAX_AGE_S = 600  # the same as repo_freshness.FETCH_MAX_AGE_S
GH_FIELDS = "headRefName,state,number,headRefOid"
GH_TIMEOUT_S = 5.0    # the most gh may take; less when less of the session-start budget is left
ORCA_TIMEOUT_S = 3.0  # the same for orca
NO_TIME_LEFT = "no time left in the session-start budget"

# No child opens a console window on Windows; git never takes an optional lock or asks for a credential.
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_ENV_OVERRIDES = {"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}


def _key(path: str | os.PathLike) -> str:
    """One spelling for a path: resolved, case-folded and back-slashed on Windows (git and Orca write `E:/x`)."""
    return os.path.normcase(os.path.realpath(str(path)))


# ---- roots and the cheap scan (Task 3.1) -----------------------------------------------------------------------

def _common_dir(top: Path, git: Callable) -> Path | None:
    code, out = git(str(top), "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(out) if code == 0 and out else None


def main_checkout(top: Path, git: Callable) -> Path:
    """The main checkout of the repo that holds `top`: the parent of `--git-common-dir`. `top` when git fails."""
    common = _common_dir(top, git)
    return common.parent if common is not None else top


def _config_roots(home: Path) -> list[str]:
    """`[hygiene] roots` from `<home>/.caddis/config.toml`, else []. A missing or bad file is just no config."""
    path = home / ".caddis" / "config.toml"
    try:
        import tomllib
    except ImportError:  # Python < 3.11
        return []
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except (OSError, ValueError):
        return []
    roots = data.get("hygiene", {}).get("roots", []) if isinstance(data.get("hygiene"), dict) else []
    return [r for r in roots if isinstance(r, str)] if isinstance(roots, list) else []


def resolve_roots(current_top: Path | None, env: Mapping[str, str], home: Path) -> list[Path]:
    """The folders whose direct children are scanned for repos (decision 6).

    `CADDIS_FLEET_ROOTS` (`;`-separated) > `<home>/.caddis/config.toml` `[hygiene] roots` > the parent of the
    current repo's main checkout plus `<home>/Documents` when it exists. Duplicates (by case and slash form) go.
    """
    raw = [p.strip() for p in env.get("CADDIS_FLEET_ROOTS", "").split(";") if p.strip()]
    if not raw:
        raw = [p.strip() for p in _config_roots(home) if p.strip()]
    if raw:
        roots = [Path(p) for p in raw]
    else:
        roots = [current_top.parent] if current_top is not None else []
        if (home / "Documents").is_dir():
            roots.append(home / "Documents")
    seen: set[str] = set()
    unique: list[Path] = []
    for root in roots:
        k = _key(root)
        if k not in seen:
            seen.add(k)
            unique.append(root)
    return unique


def _repos_under(roots: list[Path], exclude: Path | None) -> list[Path]:
    """Direct children of the roots whose `.git` is a DIRECTORY (a `.git` file is a linked worktree), sorted."""
    skip = {_key(exclude)} if exclude is not None else set()
    repos: list[Path] = []
    for root in roots:
        try:
            children = sorted(p for p in Path(root).iterdir() if p.is_dir())
        except OSError:
            continue
        for child in children:
            k = _key(child)
            if k in skip or not (child / ".git").is_dir():
                continue
            skip.add(k)
            repos.append(child)
    return repos


def _worktree_records(repo: Path, git: Callable) -> list[dict]:
    """`git worktree list --porcelain` of one repo, parsed; the first record is the main working tree."""
    code, out = git(str(repo), "worktree", "list", "--porcelain")
    return cf.parse_worktree_porcelain(out) if code == 0 else []


def _classify(repo_name: str, linked: list[dict], git: Callable) -> list[dict]:
    """One finding per linked worktree record, classified by `caddis_finished.worktree_state`."""
    findings = []
    for rec in linked:
        exists = Path(rec["path"]).is_dir()
        dirty = False
        if exists:
            s_code, s_out = git(rec["path"], "--no-optional-locks", "status", "--porcelain")
            dirty = s_code != 0 or bool(s_out)  # git failed: unknown is treated as dirty (the keep side)
        session = cf.session_id_from_path(rec["path"])
        idle = cf.session_idle_minutes(session) if session else -1
        findings.append({"repo": repo_name, "path": rec["path"], "branch": rec["branch"],
                         "state": cf.worktree_state(exists, dirty, session is not None, idle),
                         "session": session, "idle": idle})
    return findings


def _scan_repo(repo: Path, git_dir: Path, git: Callable) -> list[dict]:
    """The linked worktrees of one repo, classified. No git spawn when git records no linked worktree."""
    if not cf.has_linked_worktrees(git_dir):
        return []
    return _classify(repo.name, _worktree_records(repo, git)[1:], git)


def scan_repos(roots: list[Path], exclude: Path | None, git: Callable,
               remaining: Callable[[], float]) -> ScanResult:
    """The cheap worktree scan of every repo under the roots except `exclude`: (findings, scanned, not_scanned).

    It stops when fewer than SCAN_STOP_S seconds of the budget are left; the repos it did not reach are counted.
    """
    findings: list[dict] = []
    repos = _repos_under(roots, exclude)
    for i, repo in enumerate(repos):
        if remaining() < SCAN_STOP_S:
            return findings, i, len(repos) - i
        findings.extend(_scan_repo(repo, repo / ".git", git))
    return findings, len(repos), 0


# ---- gh and Orca (Task 3.2) -------------------------------------------------------------------------------------

def _run(argv: list[str], timeout: float | None = None, cwd: str | None = None) -> subprocess.CompletedProcess:
    """The default `subprocess.run`-shaped seam. Raises FileNotFoundError when the program is not on PATH and
    subprocess.TimeoutExpired on a timeout; the callers turn both into a skip reason."""
    exe = shutil.which(argv[0])
    if exe is None:
        raise FileNotFoundError(argv[0])
    return subprocess.run([exe, *argv[1:]], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, stdin=subprocess.DEVNULL, check=False,
                          env={**os.environ, **_ENV_OVERRIDES}, creationflags=_NO_WINDOW)


def _last_line(proc: subprocess.CompletedProcess, name: str) -> str:
    text = (proc.stderr or proc.stdout or "").strip()
    return text.splitlines()[-1].strip() if text else f"{name} exited {proc.returncode}"


def _read_cache(path: Path, now: float) -> list[dict] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("prs"), list):
        return None
    ts = data.get("ts")
    if not isinstance(ts, (int, float)) or not 0 <= now - ts < PR_CACHE_MAX_AGE_S:
        return None
    return data["prs"]


def fetch_prs(top: Path, git_dir: Path, run: Callable, now: float,
              timeout_s: float = GH_TIMEOUT_S) -> tuple[list[dict] | None, str]:
    """The last 200 PRs of the current repo from ONE gh call, cached in `<git_dir>/caddis-hygiene-prs.json` for
    600 s. (prs, "") or (None, reason). The cache is read first, so a fresh cache answers with no process at all.
    """
    cache = Path(git_dir) / PR_CACHE_NAME
    cached = _read_cache(cache, now)
    if cached is not None:
        return cached, ""
    try:
        origin = run(["git", "-C", str(top), "remote", "get-url", "origin"], timeout=timeout_s)
    except (OSError, subprocess.SubprocessError):
        return None, "could not read the origin URL"
    slug = cf.slug_from_url(origin.stdout.strip() if origin.returncode == 0 else "")
    if not slug:
        return None, "origin is not a GitHub repo"
    argv = ["gh", "pr", "list", "--repo", slug, "--state", "all", "--limit", "200", "--json", GH_FIELDS]
    try:
        proc = run(argv, timeout=timeout_s, cwd=str(top))
    except FileNotFoundError:
        return None, "gh not on PATH"
    except subprocess.TimeoutExpired:
        return None, f"gh took longer than {timeout_s:g} s"
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"gh could not start: {exc}"
    if proc.returncode != 0:
        return None, _last_line(proc, "gh")
    try:
        prs = json.loads(proc.stdout)
    except ValueError:
        return None, "gh returned unreadable JSON"
    if not isinstance(prs, list):
        return None, "gh returned unreadable JSON"
    try:
        cache.write_text(json.dumps({"ts": now, "prs": prs}), encoding="utf-8")
    except OSError:
        pass  # no cache this time: the next session start asks gh again
    return prs, ""


def orca_worktrees(run: Callable, which: Callable, timeout_s: float = ORCA_TIMEOUT_S) -> tuple[dict[str, str] | None, str]:
    """Every path Orca manages -> its Orca id, keyed by `_key(path)`. (None, reason) when Orca cannot answer
    completely: not on PATH, a non-zero exit, a timeout, bad JSON, `ok` false, or `result.truncated` true."""
    exe = which("orca")
    if not exe:
        return None, "orca not on PATH"
    try:
        proc = run([exe, "worktree", "list", "--limit", "10000", "--json"], timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return None, f"orca took longer than {timeout_s:g} s"
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"orca could not start: {exc}"
    if proc.returncode != 0:
        return None, _last_line(proc, "orca")
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return None, "orca returned unreadable JSON"
    if not isinstance(data, dict) or data.get("ok") is not True:
        return None, "orca answered ok=false"
    result = data.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("worktrees"), list):
        return None, "orca returned unreadable JSON"
    if result.get("truncated"):
        return None, "orca list is truncated"
    mapping: dict[str, str] = {}
    for wt in result["worktrees"]:
        if isinstance(wt, dict) and wt.get("path") and wt.get("id"):
            mapping[_key(wt["path"])] = str(wt["id"])
    return mapping, ""


def orca_id(mapping: dict[str, str] | None, path: str) -> str | None:
    """The Orca id of `path`, matched case- and slash-insensitively; None when Orca does not manage it."""
    return mapping.get(_key(path)) if mapping else None


# ---- current-repo facts and the summary line (Task 3.3) ----------------------------------------------------------

_which = shutil.which
SKIP_HYGIENE = "[HARNESS] skipped: repo hygiene - caddis_finished.py not found beside this hook"
TOP_REPOS = 6
TOP_TRIAGE = 3
BUCKETS = ("merged", "DIRTY", "idle-session", "orphan", "merge not checked", "needs-triage")
_STATE_BUCKET = {"orphan-registration": "orphan", "DIRTY": "DIRTY", "idle-session": "idle-session"}


def summary_line(f: dict) -> str:
    """PURE: the one line every session start prints. `[OK]` only when every field is known and level.

    Unknown is never 0 (D5): a skipped gh call prints `branches ? (gh skipped)` and a scan cut short prints
    `worktrees >=<n> stale (<k> repos not scanned)`; either one makes the prefix `[HARNESS]`.
    """
    ref = f.get("ref") or ""
    parts = [f"branch '{f['branch']}'"]
    parts += [f"{f['behind']} behind {ref}", f"{f['ahead']} ahead"] if ref else ["no remote"]
    parts.append(f"{f['dirty']} uncommitted")
    if f.get("not_scanned"):
        parts.append(f"worktrees >={f['stale']} stale ({f['not_scanned']} repos not scanned)")
    else:
        parts.append(f"worktrees {f['stale']} stale")
    if not ref:
        parts.append("branches ? (no origin)")
    elif f.get("gh_skipped"):
        parts.append("branches ? (gh skipped)")
    else:
        parts.append(f"branches {f['merged']} merged-not-deleted, {f['triage']} needs-triage")
    if f.get("gate_missing"):
        parts.append("pre-push gate missing")
    level = (ref and f["branch"] == ref.split("/", 1)[-1] and not f.get("gh_skipped") and not f.get("gate_missing")
             and not any(f.get(k) for k in ("behind", "ahead", "dirty", "stale", "not_scanned", "merged", "triage")))
    return ("[OK] " if level else "[HARNESS] ") + " | ".join(parts)


def _old_line(fresh: dict) -> list[str]:
    """The pre-hygiene freshness line, kept when caddis_finished cannot be imported."""
    ref = fresh.get("ref") or ""
    if ref and (fresh["branch"] != ref.split("/", 1)[-1] or fresh["behind"] or fresh["dirty"]):
        return [(f"[HARNESS] branch '{fresh['branch']}' | {fresh['behind']} behind {ref} | {fresh['ahead']} ahead "
                f"| {fresh['dirty']} uncommitted")]
    return []


def _local_branches(repo: Path, git: Callable) -> dict[str, tuple[str, int]]:
    """{branch: (tip oid, committer unix time)} for every local branch."""
    code, out = git(str(repo), "for-each-ref", "--format=%(refname:short)%09%(objectname)%09%(committerdate:unix)",
                    "refs/heads")
    branches: dict[str, tuple[str, int]] = {}
    for line in out.splitlines() if code == 0 else []:
        name, _, rest = line.partition("\t")
        oid, _, date = rest.partition("\t")
        if name and oid:
            branches[name] = (oid, int(date) if date.strip().isdigit() else 0)
    return branches


def _result(future: Future | None, what: str, fallback: tuple) -> tuple:
    """A future's result; a crash in the thread becomes a skip reason, never an exception at session start."""
    if future is None:
        return fallback
    try:
        return future.result()
    except Exception as exc:  # noqa: BLE001 - fail open: the hook must never break a session start
        return None, f"{what} failed: {type(exc).__name__}"


def _prs_by_branch(prs: list[dict]) -> dict[str, list[dict]]:
    """PRs grouped on headRefName, newest (highest number) first."""
    grouped: dict[str, list[dict]] = {}
    for pr in prs:
        if isinstance(pr, dict) and pr.get("headRefName"):
            grouped.setdefault(pr["headRefName"], []).append(pr)
    for group in grouped.values():
        group.sort(key=lambda pr: pr.get("number") or 0, reverse=True)
    return grouped


def _bucket(f: dict, orca_map: dict | None, prs: dict[str, list[dict]] | None, tips: dict, is_anc: Callable,
            here: bool) -> str | None:
    """The stale bucket of one linked worktree, or None when it is not stale (D4): IN USE, Orca-managed, or (in the
    current repo, with PRs known) its branch has an OPEN PR."""
    if f["state"] == "IN USE" or orca_id(orca_map, f["path"]):
        return None
    branch_prs = prs.get(f["branch"], []) if here and prs is not None else []
    if any(pr.get("state") == "OPEN" for pr in branch_prs):
        return None
    if f["state"] in _STATE_BUCKET:
        return _STATE_BUCKET[f["state"]]
    if not here or prs is None:
        return "merge not checked"
    state, _ = cf.branch_report_state(tips.get(f["branch"], ("", 0))[0], branch_prs, is_anc)
    return "merged" if state == "merged-not-deleted" else "needs-triage"


def _stale_line(here: list[str], other: list[dict], home: Path, repo: Path) -> str:
    counts = dict.fromkeys(BUCKETS, 0)
    for b in here + [f["bucket"] for f in other]:
        counts[b] += 1
    where = f"{len(here)} here, {len(other)} in other repos"
    if other:
        groups = cf.count_by_repo(other)
        listed = ", ".join(f"{name} x{n}" for name, n in groups[:TOP_REPOS])
        more = f" (+{len(groups) - TOP_REPOS} more repos)" if len(groups) > TOP_REPOS else ""
        where += f" ({listed}{more})"
    buckets = ", ".join(f"{counts[b]} {b}" for b in BUCKETS)
    return (f"[HARNESS] stale worktrees: {where}. {buckets}. List: python \"{home.as_posix()}/.caddis/bin/"
            f"caddis_run.py\" caddis_tidy.py --hygiene --repo-root {repo.as_posix()}")


def _triage_line(names: list[str], repo: Path, ref: str, tips: dict, git: Callable, now: float) -> str:
    shown = []
    for name in names[:TOP_TRIAGE]:
        code, out = git(str(repo), "rev-list", "--count", f"{ref}..{name}" if ref else name)
        commits = out.strip() if code == 0 and out.strip().isdigit() else "?"
        age = max(0, int((now - tips[name][1]) // 86400)) if tips[name][1] else "?"
        shown.append(f"{name} ({age}d, {commits} commits)")
    more = f" (+{len(names) - TOP_TRIAGE} more)" if len(names) > TOP_TRIAGE else ""
    return f"[HARNESS] branches needing triage (no PR or closed): {', '.join(shown)}{more}"


class Jobs(NamedTuple):
    """The current repo's main checkout, the roots, and the gh and orca threads `start_jobs` started."""
    main: Path
    roots: list[Path]
    any_linked: bool
    gh: Future | None
    orca: Future | None


def _done(value: tuple) -> Future:
    future: Future = Future()
    future.set_result(value)
    return future


def start_jobs(top: Path, git: Callable, remaining: Callable[[], float], *, want_prs: bool = True,
               env: Mapping[str, str] | None = None, home: Path | None = None) -> Jobs:
    """Resolve the main checkout and the roots, and start gh and orca in two threads (D8). The caller starts this
    as early as it can, so the gh and orca waits overlap its own git work. Each timeout is cut to the time left in
    the budget, so neither thread outlives it; with no time left neither starts and the reason is the answer.
    orca is asked only when a linked worktree exists (D7)."""
    if cf is None:
        raise RuntimeError("caddis_finished.py is missing")  # the caller falls back to report_lines
    env = os.environ if env is None else env
    home = Path.home() if home is None else home
    common = _common_dir(Path(top), git)
    main = common.parent if common is not None else Path(top)
    git_dir = common if common is not None else main / ".git"
    roots = resolve_roots(main, env, home)
    any_linked = cf.has_linked_worktrees(git_dir) or any(
        cf.has_linked_worktrees(r / ".git") for r in _repos_under(roots, main))
    gh_s, orca_s = min(GH_TIMEOUT_S, remaining()), min(ORCA_TIMEOUT_S, remaining())
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        gh = orca = None
        if want_prs:
            gh = (pool.submit(fetch_prs, main, git_dir, _run, time.time(), gh_s) if gh_s > 0
                  else _done((None, NO_TIME_LEFT)))
        if any_linked:
            orca = pool.submit(orca_worktrees, _run, _which, orca_s) if orca_s > 0 else _done((None, NO_TIME_LEFT))
    finally:
        pool.shutdown(wait=False)  # the submitted calls still run; their timeouts bound them
    return Jobs(main, roots, any_linked, gh, orca)


def report_lines(top: Path | None, fresh: dict, git: Callable, remaining: Callable[[], float],
                 env: Mapping[str, str] | None = None, home: Path | None = None,
                 jobs: Jobs | None = None) -> list[str]:
    """The summary line, then the skipped and detail lines. REPORT ONLY: nothing here changes anything.

    `fresh` holds `branch`, `ref`, `behind`, `ahead`, `dirty`, `gate_missing` from repo_freshness. The current repo
    (resolved to its MAIN checkout, so a session in a linked worktree counts it once) gets the full report; every
    other repo under the roots gets the cheap worktree scan. gh and orca run in two threads that start before the
    scans (D8): pass `jobs` from an earlier `start_jobs` call, or this call starts them itself.
    """
    if top is None:
        return []
    if cf is None:
        return [SKIP_HYGIENE, *_old_line(fresh)]
    ref = fresh.get("ref") or ""
    if jobs is None:
        jobs = start_jobs(Path(top), git, remaining, want_prs=bool(ref), env=env, home=home)
    home = Path.home() if home is None else home
    main, roots, any_linked = jobs.main, jobs.roots, jobs.any_linked
    gh_job = jobs.gh if ref else None  # started early on `origin` alone: with no default ref its answer is unused

    records = _worktree_records(main, git)
    here_found = _classify(main.name, records[1:], git)
    other_found, _scanned, not_scanned = scan_repos(roots, main, git, remaining)
    tips = _local_branches(main, git)
    prs, gh_reason = _result(gh_job, "gh", (None, ""))
    orca_map, orca_reason = _result(jobs.orca, "orca", ({}, ""))

    def is_anc(tip: str, head: str) -> bool:
        return git(str(main), "merge-base", "--is-ancestor", tip, head)[0] == 0

    by_branch = _prs_by_branch(prs) if prs is not None else None
    here = [b for f in here_found if (b := _bucket(f, orca_map, by_branch, tips, is_anc, True))]
    other = [{**f, "bucket": b} for f in other_found if (b := _bucket(f, orca_map, None, tips, is_anc, False))]

    merged, triage = 0, []
    if by_branch is not None:
        default = ref.split("/", 1)[-1]
        checked_out = {r["branch"] for r in records}
        for name, (tip, _date) in tips.items():
            if name == default or name in checked_out:
                continue
            state, _ = cf.branch_report_state(tip, by_branch.get(name, []), is_anc)
            if state == "merged-not-deleted":
                merged += 1
            elif state == "needs-triage":
                triage.append(name)

    gh_skipped = bool(ref) and prs is None
    lines = [summary_line({**fresh, "stale": len(here) + len(other), "not_scanned": not_scanned, "merged": merged,
                           "triage": len(triage), "gh_skipped": gh_skipped})]
    if gh_skipped:
        lines.append(f"[HARNESS] skipped: branch PR states - {gh_reason}")
    if any_linked and orca_map is None:
        lines.append(f"[HARNESS] skipped: Orca check - {orca_reason}; no worktree is treated as Orca-managed")
    if here or other:
        lines.append(_stale_line(here, other, home, main))
    if triage:
        lines.append(_triage_line(triage, main, ref, tips, git, time.time()))
    return lines
