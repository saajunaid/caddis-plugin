"""Runner: start one fresh headless session per batch, until a stop. Plan mode runs a plain plan; roadmap mode runs
the next batches of a roadmap.

Design: programme-method-design.md sections 8.1 to 8.5 and 9.2; caddis-next Phases 7 and 9. `roadmap-run.ps1` is a
thin shim over this file. The programme layer (programme folders, ledger, budget block) is gone (caddis-next Phase 7).

One session: stop checks (STOP file, session, hour and dollar caps); for agy, a reservation under the global spend cap
(`caddis_spend.py`, settled after the session); read the relay hash; launch ONE session through the governor with the
resume prompt and `CADDIS_HEADLESS=1` in its environment; parse its JSON result (cost, error); read the relay status
line; decide. CONTINUE with an unchanged relay is `FAILED no progress`; three sessions in a row with no newly closed
row is `BLOCKED stuck`.

Plan mode (`--plan <slug>`, decision D-I, design section 8.5) runs `.caddis/plans/<slug>.md`. A closed row in its
tracker is progress (`.caddis/open-work.md` is retired with the 3-store model, 21 Oct 2026); the relay is `.caddis/relay/<slug>.md`; the log and STOP file are in
`.caddis/plans/.local/<slug>/`; the lock is `<git common dir>/caddis-runner/plan-<slug>/runner.lock`. The loop goes on only
at CONTINUE. Its lock holds the whole plan (`batch` `<slug>#*`). A plan that another live runner lock names is refused
(exit 3 at start, 1 at any later iteration: the check runs before every session).

Roadmap mode (`--roadmap <slug>`, caddis-next Phase 9) runs `.caddis/roadmaps/<slug>/roadmap.md` as it is on
`origin/<default>`; the log and STOP file are in `.caddis/roadmaps/<slug>/.local/`; the lock is
`<git common dir>/caddis-runner/roadmap-<slug>/runner.lock`. It refuses to start (exit 3) on a host that is not the roadmap's
`Runner host`. Each iteration: `caddis_roadmap.next_batch`; none is `BLOCKED nothing ready` (exit 1, the notification
carries the `status` line). `next` and the batch claim in the lock happen under one repo-level claim lock, so two
runners never choose the same batch. Found: print `next: <milestone> <plan>#<phase>`. A phase whose `**Lane:**` line
is not this engine (a cloud session, the owner, another tool), or that has no Lane line, is not run: the runner adds an
`owner-gate` blocker `phase <n> lane: <lane>` (`none` when there is no line) and goes on. Else a `todo` milestone is
set `in-progress`, the runner makes a fresh branch `caddis/roadmap/<slug>/<plan>-p<n>` from origin/<default>, and ONE
session runs `plan-resume-prompt.md` for that plan and phase on it. Sessions never push. A relay `STATUS: CONTINUE`
with new commits on that branch (still checked out, nothing under `.caddis/roadmaps/` changed): the RUNNER writes a
persistent claim for the phase, pushes the branch, opens a PR (`gh api`) and stops `BLOCKED waiting for merge
<plan>#<phase> <url>` (exit 1); `--last-stop` lets the recheck task restart it once the PR merged; the restart checks
the merged origin roadmap against the hash taken at publish time, removes the claim, rolls that milestone up and goes
on. Every roadmap runs its sessions in ONE dedicated worktree, `<worktree root>/<repo>/caddis-roadmap-<slug>-<repo tag>`
(`$CADDIS_WORKTREE_ROOT`, else `<parent of the main checkout>/.worktrees`, never %TEMP%; `caddis_worktree_root.py`; made with
`git worktree add --detach` from origin/<default> on the first session, reused on restart, recorded in the runner
folder, never the `--repo` checkout); when the roadmap is finished the runner removes it if it is clean, and keeps it
(saying so in the stop line) if not. The caps (hours, sessions, USD per session and in total) are per run, in memory. CONTINUE with the phase already merged on
origin: `rollup` when every phase of the milestone is merged, then the next batch. A relay `STATUS: OWNER-GATE <r>`
becomes an `owner-gate` blocker, `STATUS: BLOCKED <r>` an `external` one, and the loop goes on.

Review gate (caddis-next Phase 11): a phase is pending review when its Tracker row is done in the working copy of
the plan (its path, or `.caddis/plans/done/` after tidy moved it), not done on origin/<default>, marked
`**Risk:** high` in any copy (working, origin, the copy from before the session; `caddis_review.phase_risk`), and not
recorded clean in this runner's own `<git common dir>/caddis-runner/<kind>-<slug>/reviewed/<plan>.json`
(phase -> head, utc, result; another runner's record does not count). Plan mode
reviews every pending phase before each session (so a restart still reviews what an earlier run left); roadmap mode
reviews the plan's pending phases BEFORE it pushes and opens the PR, so a `risk: high` phase is never published
unreviewed. Pending is recomputed after every review and every fix session. Each review is `caddis_review.py --plan
<plan> --phase <n> --runs 2 --out-dir <local>/reviews/<plan>`, a child with `CADDIS_HEADLESS=1` (the `review_cmd`
seam). Exit 0 records the phase clean. Exit 1: ONE fix session for that phase (a session against the session cap and
the USD caps) with the prompt `Read <out-dir>/review-<n>-merged.md and fix every blocking finding
...`, then one more review; exit 1 again stops `BLOCKED review`. Exit 3, 4, any other code, a timeout, exit 1 with
no merged file, a plan that cannot be read, or a done row with no `### Phase <n>` heading stops `BLOCKED review not
run`. Neither stop is restartable by the recheck task; an owner restart reviews the phase again. The review's
`review-<n>-cost.json` `total_cost_usd` is added to the spend; a missing or unreadable file adds USD 10 (USD 5 per
run, 2 runs). A review that could take the spend over the total cap does not start (a cap stop). The
review child (the reviewer has full Bash) and the fix session are each guarded by the runner-state check like any
session; the runner writes `reviewed/<plan>.json` only between children, before the next child's snapshot.

Snapshot guard: one baseline across the whole run. The Milestones and Blockers tables (every cell of every row, rows
added, removed or moved), the `Runner host` line and the `**Exit setup:**` line are frozen. Every origin read (each
`next`, and the reads after the runner's own writes and after each session) is compared with the previous read: the
only differences allowed are the exact edits the runner made and recorded for that read (a Status it set, a blocker
row it added, and what a rollup's audit entry says it actually wrote). Anything else stops the run `FAILED roadmap changed` (exit 1). Every
roadmap change goes through `caddis_roadmap.py` as a child process with `CADDIS_HEADLESS=1`; the runner never passes
`--by-owner`.

Runner state: one folder per runner, `<git common dir>/caddis-runner/<roadmap|plan>-<slug>/` (lock, last stop,
options, branches, worktree, saved roadmap text); shared at the top level: `claims/` and `claim.lock`. Sessions
are cooperative (our own sessions): the runner guards against mistakes and runaway spend, not against a hostile
session. Around every session it hashes its own folder and its own claims; a change there is `FAILED runner state
changed`. Another runner's writes never stop it. A restart checks that the claim its last stop records
is still there, unchanged (`FAILED own claim missing or changed`).

Lock: `<git common dir>/caddis-runner/<roadmap|plan>-<slug>/runner.lock` (every worktree sees it; outside a git repo,
`<local>/runner.lock`) holds `{"host", "pid", "started_utc", "batch", "max_hours"}`. On this host a lock is stale when
its pid is not running, or the process now holding that pid started after `started_utc` (pid reuse after a reboot;
when the start time cannot be read, live). Another host's lock is stale when `started_utc` is older than the lock's
own `max_hours` plus 1 h. A stale lock is removed with a toast and the run goes on; a live lock is exit 3. The runner
that holds the lock records `running` as its last stop at once, with its launch options, and its real last stop at the
end; an unexpected exception records `FAILED crash: <type>`, notifies once and re-raises. `roadmap-recheck.ps1`
restarts the runner only after `BLOCKED nothing ready`, a merged `BLOCKED waiting for merge`, or no recorded stop
(`--last-stop`), with the recorded options clamped to the built-in caps (`--restart-args`). Every lock write is a temp
file in the same folder, then a hard link (create) or os.replace.

On every stop: one Windows toast, and the push-notification fallback when the last session did not report `PUSH-SENT`
(not for a STOP file, a lock or a usage limit). One JSON line per session and one per stop go to `<local>/runner.jsonl`.
Session output, relay text and every log line, printed stop line, toast and push pass through `caddis_redact` first.

The runner never passes an owner gate, never raises a cap and never deletes a STOP file.

Exit codes: 0 stopped at a status the session wrote (plan mode: OWNER-GATE, BLOCKED), or at a STOP file after a
session; 1 a FAILED stop, a cap, the agy spend cap, a usage limit, `BLOCKED stuck`, `BLOCKED nothing ready`,
`BLOCKED waiting for merge`, `BLOCKED review`, `BLOCKED review not run`, `BLOCKED rollup not run` (a rollup exit 3,
for example an exit check that cannot run in the merged checkout; not restartable by the recheck task), or the
snapshot guard; 3 never started (lock, STOP file, no governor, agy spend cap not configured, another host, a plan a roadmap runner holds); 4 bad input (no plan or roadmap, both, a bad slug, no prompt template,
bad engine).

Engines: `claude` is built and live-tested. `agy` and `codex` are command-line adapters with unit tests only (not
live-tested; design 8.2).
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

_HERE = Path(__file__).resolve().parent
try:
    import caddis_exit
except ModuleNotFoundError as exc:
    if exc.name != "caddis_exit":
        raise
    sys.path.insert(0, str(_HERE))
    sys.path.insert(0, str(_HERE.parent / "claude-harness" / "scripts"))
    import caddis_exit

import caddis_created  # noqa: E402
import caddis_notify  # noqa: E402
import caddis_redact  # noqa: E402
import caddis_review  # noqa: E402
import caddis_roadmap  # noqa: E402
import caddis_spend  # noqa: E402
import caddis_worktree_root  # noqa: E402
import caddis_worktree_safety  # noqa: E402
import caddis_workstreams  # noqa: E402

ENGINES: dict[str, dict] = {
    "claude": {"live_tested": True, "default_model": "opus", "limit_key": "claude"},
    "agy": {"live_tested": False, "default_model": "gemini-4-argon-medium", "limit_key": "agy"},
    "codex": {"live_tested": False, "default_model": "gpt-5", "limit_key": "codex-sol"},
}
PROMPT_ON_STDIN = {"claude"}
STUCK_SESSIONS = 3
PLAN_PROMPT_NAME = "plan-resume-prompt.md"
# CLAUDE_CODE_FORK_SUBAGENT=0: since 2.1.302 fork subagents are on by default in `claude -p`. A fork can run in the
# background, and a print-mode session can end before it finishes, so its work is lost; the session prompt already
# asks for foreground work only. Normal subagents stay available.
HEADLESS_ENV = {"CADDIS_HEADLESS": "1", "CLAUDE_CODE_FORK_SUBAGENT": "0"}
# Robustness #4: what a session never gets. The publish tokens (the same list as caddis_lanes.LANE_SECRET_VARS), the
# runner publish step's marker, and the guard kill switch (the guard denies push, merge and publish headless).
SESSION_SECRET_VARS = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "NPM_TOKEN", "NODE_AUTH_TOKEN",
                       "CADDIS_ALLOW_PUBLISH", "CADDIS_GUARD_DISABLED")
SESSION_NO_PROMPT_ENV = {"GH_PROMPT_DISABLED": "1", "GIT_TERMINAL_PROMPT": "0"}
# Layer 3 for claude sessions. Not a boundary: Claude Code matches a rule against the raw command string, so
# `git "push"` or `bash -c "git push"` passes it (#65, 18 Oct). The boundary is layer 1 (session_env: no token) and
# layer 2 (the guard denies push, merge and publish when CADDIS_HEADLESS=1). With those, bypassPermissions is
# acceptable for implementers: they need a shell and the write tools, and on native Windows there is no sandbox.
SESSION_DENY_RULES = ("Bash(git push:*)", "Bash(gh pr merge:*)", "Bash(gh pr create:*)", "Bash(gh release:*)",
                      "Bash(gh api:*)", "Bash(npm publish:*)")
ROADMAP_WRITE_TIMEOUT_S = (caddis_roadmap.MERGE_CHAIN_TIMEOUT + caddis_roadmap.EXIT_SETUP_TIMEOUT
                           + caddis_roadmap.EXIT_CHECK_TIMEOUT + 600)  # a backstop: every call inside is bounded
RUNNING = "running"  # the last-stop record while a runner holds the lock; a killed run leaves it (needs the owner)
GH_STOP_PREFIX = "BLOCKED gh cannot see"  # a gh error at a restart: waiting.json stays, a later tick may resume
RESTARTABLE_STOP = "BLOCKED nothing ready"  # restartable once a blocker cleared
WAITING_PREFIX = "BLOCKED waiting for merge"  # restartable once its PR merged
# The blocker rollup writes: its stable prefix, then (since caddis-robustness Phase 7) `: ` and the output tail. The
# lookahead caps the WHOLE reason at caddis_roadmap.REASON_CELL_CHARS, the same cap blocker_reason applies, so the
# tail may hold REASON_CELL_CHARS - len(prefix) - len(": ") characters at most.
ROLLUP_BLOCK_RE = (rf"(?=[ -~]{{1,{caddis_roadmap.REASON_CELL_CHARS}}}\Z)" + caddis_roadmap.ROLLUP_PREFIX_RE.pattern
                   + r"(: [ -~]+)?")
ROLLUP_NOT_RUN = "BLOCKED rollup not run"  # rollup exit 3 (exit check, Exit setup, git or lock); the owner decides
_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
_CLOSED = {"done", "not-needed"}
_LANE_RE = re.compile(r"^\s*\*\*Lane:\*\*\s*(.*?)\s*$")
_PHASE_HEAD_RE = re.compile(r"^ {0,3}#{2,4}\s+Phase\s+(\d+)\b", re.IGNORECASE)
_HEAD_RE = re.compile(r"^ {0,3}#{1,6}\s")
_LANE_TOOL_RE = re.compile(r"^\W*([A-Za-z][A-Za-z0-9_-]*)")
_NOT_RUNNER_LANE_RE = re.compile(r"cloud|owner", re.IGNORECASE)


@dataclass
class Caps:
    max_hours: float = 10.0
    max_sessions: int = 12
    session_timeout_min: float = 120.0
    max_usd_per_session: float = 25.0
    max_usd_total: float = 150.0


def _usd(value: float) -> str:
    return f"{round(value, 2):g}"


def headless_env(base: dict | None = None) -> dict:
    """A copy of the environment with CADDIS_HEADLESS=1: headless detection cannot see a process started in a fresh
    console, so every session and every caddis_roadmap.py call the runner starts carries the marker."""
    env = dict(os.environ if base is None else base)
    env.update(HEADLESS_ENV)
    # One level deeper for every session it starts. main() refuses to start past the limit (robustness #19).
    env[caddis_spend.HEADLESS_DEPTH_VAR] = str(caddis_spend.headless_depth(env) + 1)
    return env


def session_env(base: dict | None = None) -> dict:
    """The environment of a session (and of the review child, whose reviewer sessions inherit it): headless_env with
    no publish credential (SESSION_SECRET_VARS) and no credential prompt. A session can be prompt-injected through a
    plan or a diff; the runner pushes, opens the PR and merges by itself, with its own login (runner_env)."""
    env = headless_env(base)
    for name in SESSION_SECRET_VARS:
        env.pop(name, None)
    env.update(SESSION_NO_PROMPT_ENV)
    return env


def runner_env() -> dict:
    """The environment of the runner's own caddis_roadmap.py children (writes, merge chain): headless_env
    plus the runner's gh login. Never given to a session."""
    env = headless_env()
    env.update(caddis_roadmap.AUTH_ENV)
    return env


def build_command(engine: str, model: str, prompt: str, *, usd: float, timeout_min: float,
                  governor: Sequence[str], engine_cmd: Sequence[str] | None = None,
                  worktree: Path | str | None = None) -> list[str]:
    """The full command line for one session: the governor prefix, then the engine's print-mode call.

    `claude` gets its prompt on stdin, not as an argument (PROMPT_ON_STDIN): on Windows `claude` is an npm `.cmd`
    shim, and cmd.exe cuts a multi-line argument at its first newline, which drops the rest of the prompt and every
    argument after it.

    Every engine gets its permission mode on the command line (robustness #19), none is left to a settings file or
    a default that a new version may change: `claude` bypassPermissions (with the deny rules), `agy` accept-edits
    plus --dangerously-skip-permissions (as the lanes do; a print session cannot answer a prompt), `codex` the
    workspace-write sandbox confined to `worktree` with `-C` (as the lanes do; the session's own folder, default
    the current one). The boundary is the same for all three: no publish token (session_env) and the guard."""
    if engine not in ENGINES:
        raise ValueError(f"unknown engine {engine!r}; known: {', '.join(ENGINES)}")
    exe = list(engine_cmd) if engine_cmd else [engine]
    if engine == "claude":
        # The mode is explicit: since Claude Code 2.1.302 a headless run with no mode starts in `default` (third-party
        # providers) and no longer in auto mode, so a machine without `defaultMode` in its settings would stop at
        # every permission prompt. The session runs in its own worktree under the governor, and the guard still runs.
        # The deny rules are an extra only (SESSION_DENY_RULES); the token-free env and the guard are the boundary.
        tail = [*exe, "-p", "--disallowedTools", *SESSION_DENY_RULES, "--permission-mode", "bypassPermissions",
                "--model", model, "--output-format", "json", "--max-budget-usd", _usd(usd)]
    elif engine == "agy":  # probe 5: --model must come before --print
        tail = [*exe, "--model", model, "--mode", "accept-edits", "--dangerously-skip-permissions",
                "--print", prompt, "--output-format", "json", "--print-timeout", f"{max(1, int(timeout_min))}m"]
    else:
        tail = [*exe, "exec", "--model", model, "-s", "workspace-write", "-C", str(worktree or "."), "--json", prompt]
    return [*governor, *tail]


def default_governor() -> list[str] | None:
    """`caddis_governor.py exec --scope session --`, preferring the admin-installed copy (as caddis-run.ps1 does)."""
    installed = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "caddis" / "caddis_governor.py"
    for gov in (installed, _HERE / "caddis_governor.py", _HERE.parent / "claude-harness" / "scripts" / "caddis_governor.py"):
        if gov.is_file():
            return [sys.executable, str(gov), "exec", "--scope", "session", "--"]
    return None


def default_roadmap_cmd() -> list[str]:
    return [sys.executable, str(_HERE / "caddis_roadmap.py")]


def find_prompt_template(name: str = PLAN_PROMPT_NAME) -> Path | None:
    for assets in (_HERE.parent / ".github" / "skills" / "workflow" / "roadmap" / "assets",
                   _HERE.parent / "skills" / "roadmap" / "assets"):
        if (assets / name).is_file():
            return assets / name
    return None


def _local_dir(repo: Path, kind: str, slug: str) -> Path:
    """The runner's local folder: plan `.caddis/plans/.local/<slug>`, roadmap `.caddis/roadmaps/<slug>/.local`."""
    if kind == "plan":
        return Path(repo) / ".caddis" / "plans" / ".local" / slug
    if kind == "roadmap":
        return Path(repo) / ".caddis" / "roadmaps" / slug / ".local"
    raise ValueError(f"unknown target kind {kind!r}")


def _ensure_local(path: Path) -> Path:
    """Create the local folder. A plan's `.caddis/plans/.local/` and a roadmap's `.local/` get a `.gitignore` of `*`
    when they have none (the repo's own `.gitignore` may not cover them)."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    if path.parent.name == ".local" and path.parent.parent.name == "plans":
        gitignore = path.parent / ".gitignore"
    elif path.name == ".local" and path.parent.parent.name == "roadmaps":
        gitignore = path / ".gitignore"
    else:
        return path
    if not gitignore.exists():
        gitignore.write_text("*\n", encoding="utf-8")
    return path


@dataclass
class Target:
    """What the runner runs: a plain plan file (plan mode) or a roadmap (roadmap mode)."""
    kind: str  # "plan" | "roadmap"
    slug: str
    local: Path  # lock, runner.jsonl, STOP
    progress: tuple[Path, ...]  # plan mode: files whose closed rows count as progress
    prompt_name: str


def resolve_target(repo: Path, plan: str | None) -> Target:
    """The plan-mode target; ValueError when the slug is missing or bad, or its plan file is missing."""
    slug = plan
    if not isinstance(slug, str) or not _SLUG_RE.fullmatch(slug):
        raise ValueError(f"bad plan {slug!r}: invalid slug: {slug!r}")
    plan_file = repo / ".caddis" / "plans" / f"{slug}.md"
    if not plan_file.is_file():
        raise ValueError(f"no plan {slug!r}: {plan_file} does not exist")
    return Target("plan", slug, _local_dir(repo, "plan", slug), (plan_file,), PLAN_PROMPT_NAME)


def render_prompt(template: Path, slug: str, phase: int | None = None) -> str:
    """The template body with `{{slug}}`, `{{phase}}` (empty when None) and `{{scripts}}` (this scripts folder: an
    app repo has no caddis `scripts/`) filled in."""
    text = template.read_text(encoding="utf-8")
    _meta, body = caddis_workstreams.split_document(text)
    for key, value in (("{{slug}}", slug), ("{{phase}}", "" if phase is None else str(phase)),
                       ("{{scripts}}", _HERE.as_posix())):
        body = body.replace(key, value)
    return body.strip() + "\n"


# -- closed rows ------------------------------------------------------------------------------------------------------


def closed_rows(path: Path) -> int:
    """Rows whose `Status` column (by name) is done or not-needed, over every table of the file."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    count, status_col = 0, None
    for line in lines:
        s = line.strip()
        if not s.startswith("|"):
            status_col = None
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if status_col is None:
            status_col = cells.index("Status") if "Status" in cells else -1
            continue
        if status_col >= 0 and status_col < len(cells) and cells[status_col].lower() in _CLOSED:
            count += 1
    return count


# -- session output ---------------------------------------------------------------------------------------------------


def parse_result(stdout: str) -> dict | None:
    text = (stdout or "").strip()
    candidates = [text] + [line for line in reversed(text.splitlines()) if line.lstrip().startswith("{")]
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _agy_engine_model(repo: Path) -> str:
    """`<agy model>-medium`: the `[lanes.models] agy` pin in `<repo>/.caddis/config.toml` when set, else the default
    agy model as `agy models` offers it here (see caddis_lanes.resolve_models)."""
    try:
        try:
            import caddis_lanes
        except ModuleNotFoundError:
            sys.path.insert(0, str(_HERE))
            import caddis_lanes
        return caddis_lanes.resolve_models(caddis_lanes.load_lanes_config(repo))["agy"] + "-medium"
    except Exception:  # the lane engine is missing or the config is bad: the display default
        return ENGINES["agy"]["default_model"]


def usage_limited(engine: str, text: str) -> bool:
    try:
        import caddis_lanes
        patterns = caddis_lanes.BUDGET_PATTERNS.get(ENGINES[engine]["limit_key"], ())
    except Exception:  # the lane engine is missing: use the Claude wording only
        patterns = (r"You[’']ve hit your (?:session|weekly|Opus|Sonnet|Fable|usage credit) limit\b",)
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _read_relay(repo: Path, slug: str) -> tuple[str, str | None]:
    """The plan's relay text and hash; an unsafe relay path (a symlink, an escape) counts as no relay, never a crash."""
    try:
        return caddis_workstreams.read_relay(repo, slug)
    except (ValueError, OSError) as exc:  # OSError: the relay path is a folder or locked - still no crash
        print(f"caddis_roadmap_run: relay not read: {exc}", file=sys.stderr)
        return "", None


def _cost(result: dict | None) -> float:
    value = (result or {}).get("total_cost_usd", 0)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else 0.0


# -- roadmap mode helpers ---------------------------------------------------------------------------------------------


def phase_lane(plan_text: str, phase: int) -> str | None:
    """The `**Lane:**` text of the `Phase <n>` heading's section in a plan (until the next heading of the same or a
    higher level), or None when the phase has no Lane line. Fenced code is skipped."""
    level = 0  # the open phase heading's level; 0 = not inside the phase
    for line in caddis_roadmap._mask_fences(plan_text.splitlines()):
        head = _HEAD_RE.match(line)
        if head:
            this_level = len(line.lstrip(" ")) - len(line.lstrip(" ").lstrip("#"))
            phase_head = _PHASE_HEAD_RE.match(line)
            if phase_head:
                level = this_level if int(phase_head.group(1)) == phase else 0
            elif level and this_level <= level:
                level = 0
            continue
        if level:
            match = _LANE_RE.match(line)
            if match:
                return match.group(1)
    return None


def lane_runs_here(lane: str, engine: str) -> bool:
    """True when the runner may run a phase with this Lane: its first word names this engine, and it names neither
    a cloud session nor the owner. Anything else (another tool, no tool named) is not the runner's (fail closed)."""
    if _NOT_RUNNER_LANE_RE.search(lane):
        return False
    match = _LANE_TOOL_RE.match(lane)
    return bool(match) and match.group(1).lower() == engine


def _milestone_cells(ms: "caddis_roadmap.Milestone") -> list:
    return [ms.id, ms.name, list(ms.phases), list(ms.depends), ms.exit_check, ms.status, ms.owner, ms.target]


def roadmap_guard(before: "caddis_roadmap.Roadmap", after: "caddis_roadmap.Roadmap",
                  edits: Sequence[tuple] = ()) -> list[str]:
    """Every difference between two origin reads that the runner's own recorded `edits` do not explain.

    The Milestones and Blockers tables, the `Runner host` line and the `**Exit setup:**` line are frozen: every cell
    of every milestone row, the row order, and the multiset of blocker rows. `edits` are what the runner itself wrote since `before`:
    `("status", mid, value)`, `("blocker", mid, type, reason)` (a row with no Check; nothing when the same
    milestone, type and reason exist, as `caddis_roadmap.add_blocker` does), and `("blocker-like", mid, type,
    regex)` (one added row whose reason matches, for the blocker a rollup writes)."""
    cols = caddis_roadmap.MILESTONE_COLS
    rows = {ms.id: _milestone_cells(ms) for ms in before.milestones}
    blockers = Counter(b.key for b in before.blockers)
    patterns: list[tuple[str, str, str]] = []
    for edit in edits:
        if edit[0] == "status" and edit[1] in rows:
            rows[edit[1]][cols.index("Status")] = edit[2]
        elif edit[0] == "blocker":
            _kind, mid, btype, reason = edit
            if not any(k[0] == mid and k[1] == btype and k[2] == reason for k in blockers):
                blockers[(mid, btype, reason, "")] += 1
        elif edit[0] == "blocker-like":
            patterns.append(tuple(edit[1:]))
    changes: list[str] = []
    if after.runner_host != before.runner_host:
        changes.append("Runner host changed")
    if after.exit_setup != before.exit_setup:  # a command rollup runs unattended, like an Exit check
        changes.append("Exit setup changed")
    now = {ms.id: _milestone_cells(ms) for ms in after.milestones}
    changes += [f"{mid} milestone removed" for mid in rows if mid not in now]
    changes += [f"{mid} milestone added" for mid in now if mid not in rows]
    for mid in (m for m in rows if m in now):
        changed = [col for col, old, new in zip(cols, rows[mid], now[mid]) if old != new]
        if changed:
            changes.append(f"{mid} {', '.join(changed)} changed")
    kept_before = [ms.id for ms in before.milestones if ms.id in now]
    kept_after = [ms.id for ms in after.milestones if ms.id in rows]
    if kept_before != kept_after:
        changes.append("milestone rows reordered")
    found = Counter(b.key for b in after.blockers)
    for key, n in sorted((blockers - found).items()):
        changes.append(f"{key[0]} {key[1]} blocker removed ({key[2]})" + (f" x{n}" if n > 1 else ""))
    for key, n in sorted((found - blockers).items()):
        for _ in range(n):
            match = next((p for p in patterns if p[0] == key[0] and p[1] == key[1] and not key[3]
                          and re.fullmatch(p[2], key[2])), None)
            if match is not None:
                patterns.remove(match)
            else:
                changes.append(f"{key[0]} {key[1]} blocker added ({key[2]})")
    return changes


def _done_phases(snap: "caddis_roadmap.Snapshot", plan: str) -> int:
    rows = snap.phases.tracker(plan) or {}
    return sum(1 for cell in rows.values() if caddis_roadmap._is_done_status(cell))


def _plan_text(snap: "caddis_roadmap.Snapshot", plan: str) -> str:
    for path in (f".caddis/plans/{plan}.md", f".caddis/plans/done/{plan}.md"):
        text = caddis_roadmap.show(snap.root, snap.branch, path)
        if text is not None:
            return text
    return ""


def _status_line(repo: Path, slug: str) -> str:
    try:
        return caddis_roadmap.status(repo, slug)["line"]
    except Exception as exc:  # the stop must still notify
        return f"status not read: {type(exc).__name__}"


# -- the lock ---------------------------------------------------------------------------------------------------------


def _tmp_beside(path: Path, text: str) -> Path:
    tmp = path.with_name(f"{path.name}.{os.getpid()}-{uuid.uuid4().hex}.tmp")
    tmp.write_text(text, encoding="utf-8")
    return tmp


def _create_with(path: Path, text: str) -> None:
    """Create `path` holding `text` in one step (a reader never sees it empty); FileExistsError when it exists.
    A temp file in the same folder is hard-linked to the name (the link fails when the name exists)."""
    tmp = _tmp_beside(path, text)
    try:
        os.link(tmp, path)
    except FileExistsError:
        raise
    except PermissionError as exc:
        if not caddis_roadmap._WINDOWS:
            raise
        # Windows refuses while the old lock's delete is still pending: the name is taken, for now.
        raise FileExistsError(str(path)) from exc
    except OSError:  # no hard links on this file system: O_EXCL, then the text
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
    finally:
        tmp.unlink(missing_ok=True)


def _replace_with(path: Path, text: str) -> None:
    """Rewrite `path` with a temp file in the same folder and os.replace (a reader sees the old or the new text)."""
    tmp = _tmp_beside(path, text)
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


class _RunnerLock:
    """The runner lock: JSON `{"host", "pid", "started_utc", "batch", "max_hours"}`, created with O_EXCL, in
    `<git common dir>/caddis-runner/<kind>-<slug>/` (every worktree sees it; outside a git repo, the local folder).

    A stale lock (caddis_roadmap.runner_lock_stale: judged with the `max_hours` the lock itself records) is taken over
    race-safely: rename it to a unique name (only one contender's rename succeeds), check the renamed file still
    holds what was judged stale, then create the lock."""

    def __init__(self, path: Path, max_hours: float, batch: str = "", claim_path: Path | None = None):
        self.path, self.max_hours = Path(path), max_hours
        self.claim_path = claim_path  # takeovers of a stale lock happen under this repo-level lock
        self.text: str | None = None
        self.holder = {"host": socket.gethostname(), "pid": os.getpid(),
                       "started_utc": _iso(datetime.now(timezone.utc)), "batch": batch, "max_hours": max_hours}

    def acquire(self, on_stale: Callable[[str], None], claim_held: bool = False) -> None:
        """`claim_held`: the caller already holds claim.lock (plan mode): the stale takeover must not take it again."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(3):
            text = json.dumps(self.holder)
            try:
                _create_with(self.path, text)
            except FileExistsError:
                if attempt < 2 and self._take_stale(on_stale, claim_held):
                    continue
                raise _Stop(f"BLOCKED another runner holds {self.path} (live; delete it only when no runner runs)",
                            caddis_exit.NOT_RUN, push=False) from None
            self.text = text
            return
        raise _Stop(f"BLOCKED another runner holds {self.path}", caddis_exit.NOT_RUN, push=False)

    def _take_stale(self, on_stale: Callable[[str], None], claim_held: bool = False) -> bool:
        if self.claim_path is not None:  # serialised: of several contenders on one stale lock, one takes it over
            try:
                with (contextlib.nullcontext() if claim_held
                      else caddis_roadmap._Lock(self.claim_path, timeout=caddis_roadmap.CLAIM_TIMEOUT)):
                    try:
                        judged = self.path.read_bytes()
                    except FileNotFoundError:
                        return True
                    stale = caddis_roadmap.runner_lock_stale(self.path)
                    if stale is None:
                        return True  # gone between the read and the judgement: free, try the create again
                    if not stale:
                        return False  # live: a contender before us won
                    self.path.unlink(missing_ok=True)
            except caddis_roadmap.RoadmapError:
                return False
            on_stale(f"removed a stale runner lock {self.path}: {judged.decode('utf-8', 'replace')[:200]}")
            return True
        try:
            judged = self.path.read_bytes()
        except FileNotFoundError:
            return True  # gone: try to create it again
        except OSError:
            return False
        stale = caddis_roadmap.runner_lock_stale(self.path)
        if stale is None:
            return True
        if not stale:
            return False
        grave = self.path.with_name(f"{self.path.name}.stale-{os.getpid()}-{uuid.uuid4().hex}")
        try:
            os.rename(self.path, grave)
        except OSError:  # another contender took it first, or the holder still has it open
            return False
        try:
            if grave.read_bytes() != judged:  # a fresh lock replaced the stale one: put it back
                with contextlib.suppress(OSError):
                    os.link(grave, self.path)
                return False
        finally:
            grave.unlink(missing_ok=True)
        on_stale(f"removed a stale runner lock {self.path}: {judged.decode('utf-8', 'replace')[:200]}")
        return True

    def set_batch(self, batch: str) -> None:
        self.holder["batch"] = batch
        text = json.dumps(self.holder)
        try:
            _replace_with(self.path, text)
            self.text = text
        except OSError as exc:  # other runners could not see the batch: never run it unclaimed
            raise _Stop(f"BLOCKED claim not written: {batch} ({type(exc).__name__})", caddis_exit.BLOCKED) from None

    def release(self) -> None:
        try:
            if self.text is not None and self.path.read_text(encoding="utf-8") == self.text:
                self.path.unlink()
        except OSError:
            pass


def runner_lock_file(repo: Path, kind: str, slug: str) -> Path:
    """The runner lock path: in the git common dir, or the local folder outside a git repo."""
    return caddis_roadmap.runner_lock_path(repo, kind, slug) or _local_dir(repo, kind, slug) / "runner.lock"


def last_stop_file(repo: Path, kind: str, slug: str) -> Path:
    return caddis_roadmap.last_stop_path(repo, kind, slug) or _local_dir(repo, kind, slug) / "last-stop.json"


@contextlib.contextmanager
def _claim(repo: Path):
    """One repo-level lock around `next` plus the batch claim (and plan mode's holder check plus its lock), so two
    runners cannot choose the same batch. Outside a git repo there is nothing to share it with."""
    path = caddis_roadmap.claim_lock_path(repo)
    if path is None:
        yield
        return
    try:
        lock = caddis_roadmap._Lock(path, timeout=caddis_roadmap.CLAIM_TIMEOUT)
        lock.__enter__()
    except caddis_roadmap.RoadmapError as exc:
        raise _Stop(f"BLOCKED claim lock busy: {exc}", caddis_exit.BLOCKED) from None
    try:
        yield
    finally:
        lock.__exit__(None, None, None)


def _roadmap_holder_of(repo: Path, plan: str, own_lock: Path | None = None) -> tuple[dict, str] | None:
    """(holder, batch) when another live runner lock holds a phase of this plan (or the whole plan)."""
    for batch, holder in caddis_roadmap.live_runner_holders(repo, exclude=own_lock).items():
        if caddis_roadmap.match_ref(batch) == plan:
            return holder, batch
    return None


def _read_record(path: Path) -> dict:
    try:
        record = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return record if isinstance(record, dict) else {}


class GhError(caddis_roadmap.RoadmapError):
    """gh could not answer (not installed, no login, 401/404, bad output): an error, never "not merged"."""


GH_ACCOUNT = {"name": None}  # the account the runner's gh calls use (GH_TOKEN set from it), None: the active one


def use_gh_account(account: str | None) -> str | None:
    """Make every gh call of this process (through caddis_roadmap._quiet_env) and of its caddis_roadmap.py children
    (runner_env) use `account`: GH_TOKEN from `gh auth token -u <account>`, held in caddis_roadmap.AUTH_ENV, never in
    os.environ, so no session inherits it. None keeps the environment / active account. Returns the value set, so
    it can be masked; GhError when gh cannot give it."""
    GH_ACCOUNT["name"] = account or None
    if not account:
        caddis_roadmap.AUTH_ENV.pop("GH_TOKEN", None)
        return None
    try:
        proc = subprocess.run(["gh", "auth", "token", "-u", account], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                              timeout=caddis_roadmap.GH_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GhError(f"gh cannot give a login for account {account}: {type(exc).__name__}",
                      caddis_exit.BLOCKED) from None
    gh_auth = (proc.stdout or "").strip()
    if proc.returncode != 0 or not gh_auth:
        raise GhError(f"gh has no login for account {account}", caddis_exit.BLOCKED)
    caddis_roadmap.AUTH_ENV["GH_TOKEN"] = gh_auth
    return gh_auth


def _gh_who() -> str:
    return GH_ACCOUNT["name"] or "(the active gh account)"


def _pr_state(url: str) -> dict | None:
    """The PR document from `gh api repos/<o>/<r>/pulls/<n>`; None for a URL that is not a GitHub PR. GhError when
    gh cannot answer (missing, 401, 404, a timeout, bad output)."""
    match = re.search(r"github\.com/([^/]+/[^/]+)/pull/(\d+)$", url or "")
    if not match:
        return None
    gh_repo = match.group(1)
    try:
        proc = caddis_roadmap.run_bounded(["gh", "api", f"repos/{gh_repo}/pulls/{match.group(2)}"],
                                          caddis_roadmap.GH_TIMEOUT, "gh api (PR state)")
    except (OSError, caddis_roadmap.RoadmapError) as exc:
        raise GhError(f"gh cannot see {gh_repo} with account {_gh_who()}: {type(exc).__name__}",
                      caddis_exit.BLOCKED) from None
    if proc.returncode != 0:
        tail = " ".join((proc.stderr or proc.stdout or "").split())[:160]
        raise GhError(f"gh cannot see {gh_repo} with account {_gh_who()}: {tail}", caddis_exit.BLOCKED)
    try:
        doc = json.loads(proc.stdout)
    except ValueError:
        raise GhError(f"gh gave no PR document for {url}", caddis_exit.BLOCKED) from None
    if not isinstance(doc, dict):
        raise GhError(f"gh gave no PR document for {url}", caddis_exit.BLOCKED)
    return doc


def default_pr_merged(repo: Path, url: str) -> bool:
    """GitHub says the PR merged. GhError when gh cannot answer."""
    doc = _pr_state(url)
    return bool(doc) and doc.get("merged") is True


def default_pr_closed(repo: Path, url: str) -> bool:
    """GitHub says the PR is closed without a merge. GhError when gh cannot answer."""
    doc = _pr_state(url)
    return bool(doc) and doc.get("state") == "closed" and doc.get("merged") is not True


def last_stop_restartable(repo: Path, roadmap: str,
                          pr_merged: Callable[[Path, str], bool] | None = None,
                          pr_closed: Callable[[Path, str], bool] | None = None) -> tuple[bool, str]:
    """(may the recheck task restart the runner, why). Yes after no recorded stop or `BLOCKED nothing ready` (then
    only when recheck cleared a blocker), and after `BLOCKED waiting for merge` once GitHub says that PR merged (the
    why starts with `merged:`; no cleared blocker is needed). Read only: no fetch, no ref or file changes (the runner
    checks the Tracker on origin after it holds the lock). Everything else, `running` included, needs the owner."""
    path = last_stop_file(repo, "roadmap", roadmap)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return True, "no recorded stop"
    except (OSError, ValueError) as exc:
        return False, f"last stop not readable ({type(exc).__name__}); the owner decides"
    if not isinstance(record, dict):
        return False, "last stop not readable (not an object); the owner decides"
    reason = str(record.get("reason"))
    if reason == RESTARTABLE_STOP:
        held = [h for h in record.get("held") or [] if isinstance(h, dict) and h.get("ref")]
        if held:  # skipped only because another runner held them: free now?
            live = caddis_roadmap.live_runner_batches(Path(repo), exclude=runner_lock_file(Path(repo), "roadmap",
                                                                                         roadmap))
            held_plans = {caddis_roadmap.match_ref(b) for b in live}
            still = [h["ref"] for h in held if caddis_roadmap.match_ref(h["ref"]) in held_plans]
            if not still:
                return True, "freed: " + ", ".join(h["ref"] for h in held)
        ready = _rollup_ready_without_fetch(Path(repo), roadmap)
        if ready:  # a milestone waits only for its rollup (its blocker went): restart, no cleared blocker needed
            return True, "rollup-ready: " + ", ".join(ready)
        return True, f"last stop: {reason}"
    waiting = _read_record(_state_file(Path(repo), roadmap, "waiting"))
    if waiting and (reason.startswith(WAITING_PREFIX) or reason.startswith(GH_STOP_PREFIX)):
        ref, url = str(waiting.get("ref", "")), str(waiting.get("pr", ""))
        try:
            if (pr_merged or default_pr_merged)(Path(repo), url):  # gh only: no fetch, no ref changes
                return True, f"merged: {ref} {url}"
            if (pr_closed or default_pr_closed)(Path(repo), url):  # read only: the runner's start cleans it up
                return False, f"last stop needs the owner: the PR closed without a merge: {ref} {url}"
        except Exception as exc:  # gh missing, 401, 404: an error, never "not merged"
            detail = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            return False, f"gh error: {detail}"
        return False, f"waiting for merge: {ref} {url}"
    if reason == RUNNING:
        return False, ("last stop needs the owner: running (a runner is running, or it was killed without a stop: "
                       "a crash, a reboot)")
    return False, f"last stop needs the owner: {reason} (exit {record.get('exit')})"


# -- the runner -------------------------------------------------------------------------------------------------------


class _Stop(Exception):
    def __init__(self, reason: str, code: int, *, push: bool = True, from_relay: bool = False,
                 status: tuple[str, str] | None = None, detail: str | None = None, record: dict | None = None):
        super().__init__(reason)
        self.reason, self.code, self.push, self.from_relay = reason, code, push, from_relay
        self.status, self.detail, self.record = status, detail, record or {}


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class _Ctx:
    """What one run shares between its sessions."""
    repo: Path
    target: Target
    caps: Caps
    engine: str
    model: str
    engine_cmd: Sequence[str] | None
    governor: Sequence[str]
    home: Path
    now: Callable[[], datetime]
    clock: Callable[[], float]
    toast: Callable[[str, str], int]
    push: Callable[[str], int]
    masks: list[str]
    last_stop: Path | None = None  # set once this run holds the lock: only the holder records its last stop
    written_claims: list = field(default_factory=list)  # claims this run wrote (removed again if it crashes)
    gh_account: str | None = None  # recorded in the launch options; recheck restarts with it
    review_cmd: Sequence[str] = ()  # the `caddis_review.py` command (a seam: tests pass a fake)

    @property
    def log_path(self) -> Path:
        return self.target.local / "runner.jsonl"

    def log(self, record: dict) -> None:
        _ensure_local(self.target.local)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(caddis_redact.redact_obj(record, self.masks), ensure_ascii=False) + "\n")

    def stop_file(self) -> bool:
        return (self.home / ".caddis" / "STOP").exists() or (self.target.local / "STOP").exists()

    def checks(self, sessions: int, spent: float, elapsed: float) -> None:
        """Raise _Stop for the first reason not to launch another session."""
        started = sessions > 0
        if self.stop_file():
            raise _Stop("STOP file", caddis_exit.CLEAN if started else caddis_exit.NOT_RUN, push=False)
        if sessions >= self.caps.max_sessions:
            raise _Stop(f"cap: sessions {self.caps.max_sessions}", caddis_exit.BLOCKED)
        if elapsed >= self.caps.max_hours * 3600:
            raise _Stop(f"cap: hours {elapsed / 3600:.2f} of {self.caps.max_hours:g}", caddis_exit.BLOCKED)
        if spent >= self.caps.max_usd_total:
            raise _Stop(f"cap: usd {spent:.2f} of {self.caps.max_usd_total:g}", caddis_exit.BLOCKED)


@dataclass
class _Session:
    outcome: "_Outcome"
    result: dict | None
    cost: float
    pushed: bool
    relay_text: str
    hash_before: str | None
    hash_after: str | None
    record: dict


def _one_session(ctx: _Ctx, prompt: str, relay_slug: str, n: int, spent: float, elapsed: float,
                 spend_slug: str, cwd: Path | None = None) -> _Session:
    """Launch one session (agy: under a spend reservation) in `cwd` (default the repo) and read what it left."""
    caps = ctx.caps
    cwd = cwd or ctx.repo
    remaining_s = max(1.0, min(caps.session_timeout_min * 60, caps.max_hours * 3600 - elapsed))
    usd = min(caps.max_usd_per_session, caps.max_usd_total - spent)
    cmd = build_command(ctx.engine, ctx.model, prompt, usd=usd, timeout_min=remaining_s / 60, governor=ctx.governor,
                        engine_cmd=ctx.engine_cmd, worktree=cwd)
    rid = _spend_reserve(ctx.home, spend_slug, ctx.now(), n > 1) if ctx.engine == "agy" else None
    if ctx.engine == "agy":  # agy's tool consoles open on a hidden desktop, not on the owner's screen
        g = len(ctx.governor)
        cmd = [*cmd[:g], *caddis_spend.hidden_argv(cmd[g:], session_env())]
    launched, outcome = ctx.clock(), None
    try:
        _, hash_before = _read_relay(cwd, relay_slug)
        record = {"kind": "session", "n": n, "start": _iso(ctx.now()), "relay_hash_before": hash_before}
        outcome = _launch(cmd, cwd, remaining_s, prompt if ctx.engine in PROMPT_ON_STDIN else None,
                          env=session_env())
    finally:  # any exception, KeyboardInterrupt too, still settles the reservation
        if rid is not None:
            _spend_settle(ctx.home, rid, cmd, outcome, ctx.now(), ctx.clock() - launched)
    outcome = _Outcome(outcome.code, caddis_redact.redact(outcome.stdout, ctx.masks),
                       caddis_redact.redact(outcome.stderr, ctx.masks), outcome.timed_out, outcome.started)
    record["end"] = _iso(ctx.now())
    # The hour cap is checked again by the next iteration's checks(), before any further session.
    result = parse_result(outcome.stdout)
    cost = _cost(result)
    text = result.get("result", "") if isinstance(result, dict) else ""
    pushed = caddis_notify.PUSH_MARKER in (text if isinstance(text, str) else "") or \
        caddis_notify.PUSH_MARKER in outcome.stdout
    relay_text, hash_after = _read_relay(cwd, relay_slug)
    record.update({"exit": outcome.code, "cost_usd": cost, "relay_hash_after": hash_after, "push_sent": pushed})
    return _Session(outcome, result, cost, pushed, relay_text, hash_before, hash_after, record)


# -- the review gate (caddis-next Phase 11) ---------------------------------------------------------------------------

REVIEW_RUNS = 2
REVIEW_MAX_USD = REVIEW_RUNS * caddis_review.MAX_BUDGET_USD  # the most one review may cost; counted when unknown
REVIEW_TIMEOUT_S = REVIEW_RUNS * caddis_review.CLAUDE_TIMEOUT_SECS + 900  # a backstop: each run has its own timeout
REVIEW_BLOCKED = "BLOCKED review"  # findings left after the one fix round; needs the owner
REVIEW_NOT_RUN = "BLOCKED review not run"  # exit 3, 4, any other code, no heading, no plan; needs the owner
REVIEW_ROUND_LIMIT = "BLOCKED review round limit: the owner decides"  # exit 5: never review again


def default_review_cmd() -> list[str]:
    return [sys.executable, str(_HERE / "caddis_review.py")]


@dataclass
class _Tally:
    """The run's counters while the review gate runs: its fix session and its cost count against the caps."""
    sessions: int
    spent: float
    pushed: bool


def plan_paths(repo: Path, plan: str) -> tuple[Path, Path]:
    """Where a plan lives: `.caddis/plans/<plan>.md`, or `.caddis/plans/done/<plan>.md` after tidy moved it."""
    plans = Path(repo) / ".caddis" / "plans"
    return plans / f"{plan}.md", plans / "done" / f"{plan}.md"


def _working_plan(repo: Path, plan: str) -> tuple[Path, str] | None:
    """The working copy of the plan (its current path, else done/) and its text; None when neither is readable."""
    for path in plan_paths(repo, plan):
        if path.is_file():
            try:
                return path, path.read_text(encoding="utf-8")
            except OSError:
                continue
    return None


def _origin_plan_text(repo: Path, plan: str) -> str | None:
    """The plan on `origin/<default>` as last fetched (no fetch and no remote call here), from its path or done/;
    None when absent or when origin/HEAD is not set locally."""
    ref = _git_out(repo, "symbolic-ref", "refs/remotes/origin/HEAD") or ""
    if not ref.startswith("refs/remotes/origin/"):
        return None
    branch = ref[len("refs/remotes/origin/"):]
    for path in (f".caddis/plans/{plan}.md", f".caddis/plans/done/{plan}.md"):
        text = caddis_roadmap.show(repo, branch, path)
        if text is not None:
            return text
    return None


def phase_info(texts: Sequence[str], phase: int, scratch: Path) -> tuple[bool, bool]:
    """(some copy has a `### Phase <n> ` heading, some copy marks the phase high). `caddis_review.phase_risk` fails
    closed, so anything but normal, low or medium is high. Every copy counts: a session cannot lower its own risk."""
    found = high = False
    _ensure_local(scratch)  # the local folder gets its `*` .gitignore before anything is written there
    probe = scratch / f"risk-probe-{os.getpid()}-{uuid.uuid4().hex}.md"
    try:
        for text in texts:
            if not text:
                continue
            probe.write_text(text, encoding="utf-8")
            try:
                risk = caddis_review.phase_risk(probe, phase)
            except ValueError:  # no such phase heading in this copy
                continue
            found = True
            high = high or risk == "high"
    finally:
        probe.unlink(missing_ok=True)
    return found, high


def _done_rows(text: str | None) -> list[int]:
    rows = caddis_roadmap.parse_tracker(text or "")
    return [n for n in sorted(rows) if caddis_roadmap._is_done_status(rows[n])]


def reviewed_file(repo: Path, kind: str, slug: str, plan: str) -> Path:
    """The record of reviewed phases of `plan`, in THIS runner's own folder:
    `<git common dir>/caddis-runner/<kind>-<slug>/reviewed/<plan>.json` (every worktree and every restart of this
    runner sees it; outside a git repo, `<local>/reviewed/<plan>.json`). A runner trusts only records in its own
    folder, so the per-runner state check covers them and a session cannot forge them unseen during this runner's
    sessions. Another runner's record for the same plan does not count: a phase reviewed by a plan-mode runner is
    reviewed again when a roadmap runner picks it (safe, accepted). Limit: the state check hashes only this runner's
    own folder, so a session can edit ANOTHER runner's folder unseen by this runner (sessions are cooperative, same
    OS user; the state check is not a security boundary)."""
    return runner_folder(repo, kind, slug) / "reviewed" / f"{plan}.json"


def read_reviewed(path: Path) -> dict:
    """phase (str) -> {"head", "utc", "result"}. A missing or unreadable record is empty: every phase is pending
    again (fail closed: review once more, never skip)."""
    record = _read_record(path)
    return {k: v for k, v in record.items() if isinstance(v, dict)}


def _record_review(path: Path, phase: int, head: str | None, result: str) -> None:
    """The ONLY writer of `reviewed/<plan>.json`. The runner calls it only between children (after a review child
    exited and its state check passed, never while a session or a review runs); every session and review child takes
    its own state snapshot right before it starts, so the runner's write is already in that baseline."""
    record = read_reviewed(path)
    record[str(phase)] = {"head": head, "utc": _iso(datetime.now(timezone.utc)), "result": result}
    _write_record(path, record)


def pending_reviews(working: str, origin: str | None, reviewed: dict, also: Sequence[int] = ()) -> list[int]:
    """Phases to review: done in the working copy's Tracker, not done on origin/<default> (merged phases were reviewed
    before their PR, or merged by the owner), and not recorded as reviewed clean. The caller then keeps only the
    `risk: high` ones."""
    merged = set(_done_rows(origin)) if origin is not None else set()
    return [n for n in sorted(set(_done_rows(working)) | set(also)) if n not in merged
            and (reviewed.get(str(n)) or {}).get("result") != "clean"]


def _rel(repo: Path, path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(repo).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _review_cost(cost_file: Path) -> tuple[float, str]:
    """The review's `total_cost_usd`, or REVIEW_MAX_USD when the file is missing or unreadable (fail toward
    spending less: the caps then stop the run sooner, never later)."""
    try:
        value = json.loads(cost_file.read_text(encoding="utf-8")).get("total_cost_usd")
    except FileNotFoundError:
        return float(REVIEW_MAX_USD), "missing"
    except (OSError, ValueError, AttributeError):
        return float(REVIEW_MAX_USD), "unreadable"
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not (0 <= value < float("inf")):
        return float(REVIEW_MAX_USD), "unreadable"
    return float(value), "file"


def _run_review(ctx: _Ctx, tally: _Tally, plan_file: Path, phase: int, out_dir: Path, elapsed: Callable[[], float],
                ref: str, round_no: int, cwd: Path | None = None) -> int | None:
    """One `caddis_review.py --plan --phase --runs 2` child with CADDIS_HEADLESS=1. Its cost is added to `spent`.
    Returns its exit code; None when it timed out, did not start, or exit 1 left no merged findings file. It reviews
    the checkout `cwd` (default the repo; roadmap mode: the roadmap's worktree, where the phase session ran)."""
    cwd = Path(cwd) if cwd is not None else ctx.repo
    caps = ctx.caps
    if ctx.stop_file():
        raise _Stop("STOP file", caddis_exit.CLEAN if tally.sessions else caddis_exit.NOT_RUN, push=False)
    left_s = caps.max_hours * 3600 - elapsed()
    if left_s <= 0:
        raise _Stop(f"cap: hours {caps.max_hours:g} reached before the review of {ref}", caddis_exit.BLOCKED)
    if tally.spent + REVIEW_MAX_USD > caps.max_usd_total:
        raise _Stop(f"cap: usd {tally.spent:.2f} of {caps.max_usd_total:g} (the review of {ref} may cost up to "
                    f"{REVIEW_MAX_USD:g})", caddis_exit.BLOCKED)
    out_dir.mkdir(parents=True, exist_ok=True)
    cost_file = out_dir / f"review-{phase}-cost.json"
    merged = out_dir / f"review-{phase}-merged.md"
    stale = False
    for old in (cost_file, merged):  # a file from an earlier review never counts for this one
        try:
            old.unlink(missing_ok=True)
        except OSError:
            stale = True
    argv = [*ctx.review_cmd, "--worktree", str(cwd), "--plan", str(plan_file), "--phase", str(phase),
            "--runs", str(REVIEW_RUNS), "--out-dir", str(out_dir)]
    print(f"review: {ref} round {round_no} ({REVIEW_RUNS} runs)")
    code: int | None = None
    kind, slug = ctx.target.kind, ctx.target.slug
    state_before = state_snapshot(ctx.repo, kind, slug)  # the reviewer has full Bash: it is guarded like a session
    try:
        proc = subprocess.run(argv, cwd=cwd, env=session_env(), stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=max(1.0, min(REVIEW_TIMEOUT_S, left_s)))
        code, output = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        output = "the review timed out"
    except OSError as exc:
        output = f"the review did not start: {exc}"
    for line in output.splitlines():
        if line.strip():
            print(caddis_redact.redact(f"review {ref}: {line}", ctx.masks))
    cost, source = (float(REVIEW_MAX_USD), "stale") if stale else _review_cost(cost_file)
    tally.spent += cost
    if source != "file":
        print(f"caddis_roadmap_run: review cost file {cost_file} is {source}; counting USD {REVIEW_MAX_USD:g} "
              f"(the most {REVIEW_RUNS} runs may cost)", file=sys.stderr)
    note = None
    if code == caddis_exit.BLOCKED and (stale or not merged.is_file()):
        note, code = "exit 1 with no merged findings file", None  # nothing for a fix session to read: not run
    ctx.log({"kind": "review", "batch": ref, "round": round_no, "exit": code, "cost_usd": cost,
             "cost_source": source, **({"note": note} if note else {}), "time": _iso(ctx.now())})
    _check_state(ctx.repo, kind, slug, state_before)  # after its cost is counted, before the record is written
    return code


def _review_gate(ctx: _Ctx, tally: _Tally, *, plan: str, extra_texts: Sequence[str] = (),
                 origin_text: str | None = None, elapsed: Callable[[], float], spend_slug: str,
                 also: Sequence[int] = (), cwd: Path | None = None) -> bool:
    """Review every pending `risk: high` phase of `plan`, in order; True when it reviewed one (all now clean).

    Pending (recomputed after every review and every fix session): a Tracker row done in the working copy, not done on
    origin/<default>, not recorded clean in `reviewed_file`, and high in any copy (working, origin, `extra_texts`).
    The plan is read from its path or from done/; neither readable stops `BLOCKED review not run`, and so does a done
    row with no `### Phase <n>` heading in any copy. Review exit 0 records the phase clean. Exit 1 starts ONE fix
    session per phase (a session against the caps), then that phase is reviewed again; exit 1 again stops
    `BLOCKED review`; exit 5 (round limit) stops at once `BLOCKED review round limit: the owner decides`, with no
    fix session and no later review; exit 3, 4 or any other code stops `BLOCKED review not run`. Neither stop is restartable by the
    recheck task; an owner restart reviews the phase again (it is still pending). `also`: phases that count as done
    even when their row is not (roadmap mode: the phase it is about to publish). `cwd`: where the phase session ran
    (roadmap mode: the roadmap's worktree; default the repo): the plan is read there, the review reviews that
    checkout, and the fix session runs there."""
    cwd = Path(cwd) if cwd is not None else ctx.repo
    record_path = reviewed_file(ctx.repo, ctx.target.kind, ctx.target.slug, plan)
    out_dir = ctx.target.local / "reviews" / plan
    fixed: set[int] = set()
    reviewed_any = False
    while True:
        working = _working_plan(cwd, plan)
        if working is None:
            raise _Stop(f"{REVIEW_NOT_RUN}: plan {plan} not found", caddis_exit.BLOCKED, record={"plan": plan})
        plan_file, text = working
        texts = [text, origin_text or "", *extra_texts]
        phase = None
        for n in pending_reviews(text, origin_text, read_reviewed(record_path), also):
            found, high = phase_info(texts, n, ctx.target.local)
            if not found:
                raise _Stop(f"{REVIEW_NOT_RUN}: no heading for phase {n}", caddis_exit.BLOCKED,
                            record={"ref": f"{plan}#{n}"})
            if high:
                phase = n
                break
        if phase is None:
            return reviewed_any
        reviewed_any = True
        ref = f"{plan}#{phase}"
        merged = out_dir / f"review-{phase}-merged.md"
        record = {"ref": ref, "review": str(merged)}
        code = _run_review(ctx, tally, plan_file, phase, out_dir, elapsed, ref, 2 if phase in fixed else 1, cwd)
        head = _git_out(cwd, "rev-parse", "HEAD")
        result = {caddis_exit.CLEAN: "clean", caddis_exit.BLOCKED: "blocked"}.get(code, "not-run")
        _record_review(record_path, phase, head, result)
        if code == caddis_exit.CLEAN:
            continue
        if code == caddis_exit.ROUND_LIMIT:  # the phase used its review rounds: stop at once, never review again
            raise _Stop(REVIEW_ROUND_LIMIT, caddis_exit.BLOCKED, record=record,
                        detail=f"{ref}: review exit {code} (round limit); see {merged}")
        if code != caddis_exit.BLOCKED:
            raise _Stop(REVIEW_NOT_RUN, caddis_exit.BLOCKED, record=record,
                        detail=f"{ref}: review exit {'none' if code is None else code}; see {merged}")
        if phase in fixed:
            raise _Stop(REVIEW_BLOCKED, caddis_exit.BLOCKED, record=record,
                        detail=f"{ref}: blocking findings left after one fix round; see {merged}")
        fixed.add(phase)
        ctx.checks(tally.sessions, tally.spent, elapsed())  # the fix session is a session like any other
        prompt = (f"Read {_rel(cwd, merged)} and fix every blocking finding in Phase {phase} of "
                  f"{_rel(cwd, plan_file)}; commit. Work on the branch that is checked out; do not push.\n")
        state_before = state_snapshot(ctx.repo, ctx.target.kind, ctx.target.slug)  # AFTER the record write
        s = _one_session(ctx, prompt, plan, tally.sessions + 1, tally.spent, elapsed(), spend_slug, cwd=cwd)
        tally.sessions += 1
        tally.spent += s.cost
        tally.pushed = s.pushed
        failed = _session_failed(ctx.engine, s.outcome, s.result)
        s.record.update({"batch": ref, "fix_for": "review", "status": "FIX" if failed is None else failed.reason})
        ctx.log(s.record)
        _check_state(ctx.repo, ctx.target.kind, ctx.target.slug, state_before)  # before any runner write
        if failed is not None:
            raise failed


def run(*, repo: Path, plan: str | None = None, roadmap: str | None = None, caps: Caps, engine: str = "claude",
        model: str | None = None, engine_cmd: Sequence[str] | None = None, governor: Sequence[str] | None = None,
        prompt_template: Path | None = None, dry_run: bool = False,
        home: Path | None = None, toast: Callable[[str, str], int] | None = None,
        push: Callable[[str], int] | None = None, clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] | None = None, after_session: Callable[[int], None] | None = None,
        roadmap_cmd: Sequence[str] | None = None, hostname: str | None = None,
        publish: Callable[..., str] | None = None, pr_merged: Callable[[Path, str], bool] | None = None,
        worktree_root: Path | None = None, delete_remote_branch: Callable[[Path, str], None] | None = None,
        pr_closed: Callable[[Path, str], bool] | None = None, gh_account: str | None = None,
        gh_login: Callable[[str | None], str | None] | None = None,
        review_cmd: Sequence[str] | None = None) -> int:
    repo = Path(repo).resolve()
    if (plan is None) == (roadmap is None):
        print("caddis_roadmap_run: give exactly one of --plan and --roadmap", file=sys.stderr)
        return caddis_exit.ERROR
    if roadmap is not None:
        if not isinstance(roadmap, str) or not caddis_roadmap.SLUG_RE.match(roadmap):
            print(f"caddis_roadmap_run: bad roadmap {roadmap!r}: invalid slug", file=sys.stderr)
            return caddis_exit.ERROR
        target = Target("roadmap", roadmap, _local_dir(repo, "roadmap", roadmap), (), PLAN_PROMPT_NAME)
    else:
        try:
            target = resolve_target(repo, plan)
        except ValueError as exc:
            print(f"caddis_roadmap_run: {exc}", file=sys.stderr)
            return caddis_exit.ERROR
    if engine not in ENGINES:
        print(f"caddis_roadmap_run: unknown engine {engine!r}", file=sys.stderr)
        return caddis_exit.ERROR
    if not model and engine == "agy":  # the model this machine offers (Argon, else the fallback); the table is display only
        model = _agy_engine_model(repo)
    model = model or ENGINES[engine]["default_model"]
    template = prompt_template or find_prompt_template(target.prompt_name)
    if template is None or not Path(template).is_file():
        print(f"caddis_roadmap_run: resume prompt template {target.prompt_name} not found", file=sys.stderr)
        return caddis_exit.ERROR
    template = Path(template)
    if governor is None:
        governor = default_governor()
        if governor is None:
            print("caddis_roadmap_run: caddis_governor.py not found; refusing to start ungoverned", file=sys.stderr)
            return caddis_exit.NOT_RUN
    home = home or Path.home()
    now = now or (lambda: datetime.now(timezone.utc))
    toast = toast or (lambda title, message: caddis_notify.toast(title, message))
    push = push or (lambda message: caddis_notify.push(message))
    ctx = _Ctx(repo, target, caps, engine, model, engine_cmd, governor, home, now, clock, toast, push,
               caddis_redact.load_secrets(home), gh_account=gh_account or None,
               review_cmd=list(review_cmd or default_review_cmd()))
    if gh_account and not dry_run:  # every gh call of this run (and its caddis_roadmap.py children) uses it
        try:
            value = (gh_login or use_gh_account)(gh_account)
        except caddis_roadmap.RoadmapError as exc:
            print(f"caddis_roadmap_run: {exc}", file=sys.stderr)
            ctx.toast(f"caddis {target.kind} {target.slug}", caddis_redact.redact(f"RUNNER STOP: BLOCKED {exc}",
                                                                                 ctx.masks))
            return caddis_exit.BLOCKED
        if value:
            ctx.masks.append(value)
            caddis_roadmap.AUTH_ENV["GH_TOKEN"] = value  # the runner's own calls only; never a session's env
    if roadmap is not None:
        rm_cmd = list(roadmap_cmd or default_roadmap_cmd())
        return _run_roadmap(ctx, template, dry_run, after_session, rm_cmd,
                            hostname or socket.gethostname(), publish or default_publish,
                            pr_merged or default_pr_merged, worktree_root,
                            delete_remote_branch or default_delete_remote_branch, pr_closed or default_pr_closed)
    return _run_plan(ctx, template, dry_run, after_session)


def _dry_run_tail(ctx: _Ctx, template: Path, prompt: str, cwd: Path | None = None) -> None:
    caps = ctx.caps
    cmd = build_command(ctx.engine, ctx.model, "<resume prompt>", usd=min(caps.max_usd_per_session, caps.max_usd_total),
                        timeout_min=caps.session_timeout_min, governor=ctx.governor, engine_cmd=ctx.engine_cmd,
                        worktree=cwd or ctx.repo)
    print(f"would launch (cwd {cwd or ctx.repo}, CADDIS_HEADLESS=1): {subprocess.list2cmdline(cmd)}"
          + (" (resume prompt on stdin)" if ctx.engine in PROMPT_ON_STDIN else ""))
    print(f"resume prompt from {template}:\n{prompt}")
    if ctx.engine != "claude":
        print(f"note: engine {ctx.engine} is an adapter, not live-tested")


def _dry_lock_check(lock: Path) -> None:
    stale = caddis_roadmap.runner_lock_stale(lock)
    if stale is False:
        raise _Stop("BLOCKED another runner holds the lock", caddis_exit.NOT_RUN, push=False)
    if stale:
        print(f"would remove a stale lock {lock}")


def _run_plan(ctx: _Ctx, template: Path, dry_run: bool, after_session: Callable[[int], None] | None) -> int:
    repo, target, slug, masks = ctx.repo, ctx.target, ctx.target.slug, ctx.masks
    prompt = render_prompt(template, slug)
    lock_file = runner_lock_file(repo, "plan", slug)
    lock = _RunnerLock(lock_file, ctx.caps.max_hours, batch=f"{slug}#*",  # the whole plan is held
                       claim_path=caddis_roadmap.claim_lock_path(repo))

    def held_stop(code: int) -> _Stop | None:
        holder = _roadmap_holder_of(repo, slug, own_lock=lock_file)
        if holder is None:
            return None
        what = "its claim: its PR waits for a merge" if holder[0].get("kind") == "claim" else "its runner lock"
        return _Stop(f"BLOCKED {holder[0].get('holder')} holds {holder[1]} ({what})", code, push=False)

    if dry_run:
        try:
            held = held_stop(caddis_exit.NOT_RUN)
            if held is not None:
                raise held
            _dry_lock_check(lock.path)
            ctx.checks(0, 0.0, 0.0)
            if ctx.engine == "agy":
                _spend_preview(ctx.home, ctx.now())
        except _Stop as stop:
            print(f"would stop: {caddis_redact.redact(stop.reason, masks)}")
            return caddis_exit.NOT_RUN
        progress = ", ".join(str(p) for p in target.progress)
        print(f"{target.kind} {slug}: progress from {progress}; local files in {target.local}; lock {lock.path}")
        _dry_run_tail(ctx, template, prompt)
        return caddis_exit.CLEAN

    try:
        with _claim(repo):  # the holder check and the lock, atomic against a roadmap runner's choice
            held = held_stop(caddis_exit.NOT_RUN)
            if held is not None:
                raise held
            lock.acquire(lambda message: _stale_notice(ctx, message),
                         claim_held=caddis_roadmap.claim_lock_path(repo) is not None)  # _claim holds it already
    except _Stop as stop:
        return _finish(stop, ctx, False, 0, 0.0, slug)
    except OSError as exc:
        return _finish(_Stop(f"BLOCKED claim not written: the runner lock ({type(exc).__name__})",
                             caddis_exit.BLOCKED), ctx, False, 0, 0.0, slug)
    _mark_running(ctx, last_stop_file(repo, "plan", slug))
    if not ENGINES[ctx.engine]["live_tested"]:
        print(f"caddis_roadmap_run: engine {ctx.engine} is an adapter, not live-tested", file=sys.stderr)

    sessions, spent, stuck, pushed = 0, 0.0, 0, False
    plan_before = ""
    start = ctx.clock()
    try:
        while True:
            elapsed = ctx.clock() - start
            ctx.checks(sessions, spent, elapsed)
            held = held_stop(caddis_exit.BLOCKED)  # checked on every iteration, not only at start
            if held is not None:
                raise held
            # Review gate: every pending `risk: high` phase is reviewed before another session builds on it (also
            # after a restart: the record of reviewed phases is in the runner state, not in this process).
            tally = _Tally(sessions, spent, pushed)
            try:
                reviewed = _review_gate(ctx, tally, plan=slug, extra_texts=(plan_before,),
                                        origin_text=_origin_plan_text(repo, slug),
                                        elapsed=lambda: ctx.clock() - start, spend_slug=slug)
            finally:
                sessions, spent, pushed = tally.sessions, tally.spent, tally.pushed
            if reviewed:
                ctx.checks(sessions, spent, ctx.clock() - start)  # the review and its fix session count
            closed_before = _closed(target)
            working = _working_plan(repo, slug)
            plan_before = working[1] if working else ""
            state_before = state_snapshot(repo, "plan", slug)
            s = _one_session(ctx, prompt, slug, sessions + 1, spent, elapsed, slug)
            _check_state(repo, "plan", slug, state_before)
            sessions += 1
            spent += s.cost
            pushed = s.pushed
            try:
                stop = _decide(ctx.engine, s.outcome, s.result, s.relay_text, s.hash_before, s.hash_after)
                if stop is None:
                    closed = _closed(target)
                    stuck = 0 if closed > closed_before else stuck + 1
                    s.record["status"] = "CONTINUE"
                    if stuck >= STUCK_SESSIONS:
                        raise _Stop("BLOCKED stuck", caddis_exit.BLOCKED)
                else:
                    s.record["status"] = stop.reason
                    raise stop
            finally:
                s.record.setdefault("status", "FAILED")
                ctx.log(s.record)
            if after_session is not None:
                after_session(sessions)
    except _Stop as stop:
        return _finish(stop, ctx, pushed, sessions, spent, slug)
    except Exception as exc:
        _crashed(ctx, exc, pushed, sessions, spent, slug)
        raise
    finally:
        lock.release()


def _stale_notice(ctx: _Ctx, message: str) -> None:
    message = caddis_redact.redact(message, ctx.masks)
    print(f"caddis_roadmap_run: {message}", file=sys.stderr)
    ctx.log({"kind": "stale-lock", "message": message, "time": _iso(datetime.now(timezone.utc))})
    ctx.toast(f"caddis {ctx.target.kind} {ctx.target.slug}", message)


def _roadmap_write(ctx: _Ctx, roadmap_cmd: Sequence[str], args: list[str]) -> int:
    """Run one `caddis_roadmap.py` write as a child process with CADDIS_HEADLESS=1; return its exit code."""
    if "--by-owner" in args:
        raise ValueError("the runner never makes an owner-only roadmap change")
    argv = [*roadmap_cmd, *args, "--roadmap", ctx.target.slug, "--root", str(ctx.repo)]
    try:
        proc = subprocess.run(argv, cwd=ctx.repo, env=runner_env(), stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=ROADMAP_WRITE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        print(f"caddis_roadmap_run: roadmap {args[0]} timed out", file=sys.stderr)
        return caddis_exit.NOT_RUN
    except OSError as exc:
        print(f"caddis_roadmap_run: roadmap {args[0]} not started: {exc}", file=sys.stderr)
        return caddis_exit.NOT_RUN
    for line in ((proc.stdout or "") + (proc.stderr or "")).splitlines():
        if line.strip():
            print(caddis_redact.redact(f"roadmap {args[0]}: {line}", ctx.masks))
    ctx.log({"kind": "roadmap", "args": args, "exit": proc.returncode, "time": _iso(datetime.now(timezone.utc))})
    return proc.returncode


class _Baseline:
    """The snapshot guard's baseline, kept across iterations. Every origin read is compared with the previous read
    first: the Milestones and Blockers tables, the Runner host line and the Exit setup line are frozen, except for
    the exact edits the runner itself made and recorded (`expect`) since that read. Then the new read becomes the
    baseline."""

    def __init__(self, roadmap: "caddis_roadmap.Roadmap"):
        self.roadmap = roadmap
        self.edits: list[tuple] = []

    def expect(self, *edit) -> None:
        self.edits.append(edit)

    def observe(self, snap: "caddis_roadmap.Snapshot") -> "caddis_roadmap.Snapshot":
        changes = roadmap_guard(self.roadmap, snap.roadmap, self.edits)
        self.edits = []
        if changes:
            raise _Stop("FAILED roadmap changed: " + "; ".join(changes), caddis_exit.BLOCKED)
        self.roadmap = snap.roadmap
        return snap


def _load_observed(repo: Path, slug: str, baseline: _Baseline) -> "caddis_roadmap.Snapshot":
    try:
        snap = caddis_roadmap.load(repo, slug)
    except caddis_roadmap.RoadmapError as exc:
        raise _Stop(f"FAILED roadmap changed: the origin copy no longer loads: {str(exc).splitlines()[0]}",
                    caddis_exit.BLOCKED) from None
    return baseline.observe(snap)


def _audit_lines(repo: Path, slug: str) -> list[str]:
    try:
        return (caddis_roadmap.local_dir(repo, slug) / "changes.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def _git_out(repo: Path, *args: str) -> str | None:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", stdin=subprocess.DEVNULL)
    return proc.stdout.strip() if proc.returncode == 0 else None


def _phase_title(plan_text: str, phase: int) -> str:
    for line in plan_text.splitlines():
        head = _PHASE_HEAD_RE.match(line)
        if head and int(head.group(1)) == phase:
            title = re.sub(r"^ {0,3}#{2,4}\s+Phase\s+\d+\s*[-:–—]*\s*", "", line).strip()
            return " ".join(title.split())[:100]
    return ""


def default_publish(repo: Path, branch: str, base: str, title: str, body: str) -> str:
    """Push `branch` to origin and open a PR with `gh api` (REST; the account comes from GH_TOKEN). Returns its URL.
    When a PR for the branch is already open, returns that one. RoadmapError when it cannot."""
    caddis_roadmap._git(repo, "push", "--quiet", "-u", "origin", f"{branch}:{branch}")
    gh_repo = caddis_roadmap.gh_repo_of(repo)
    if gh_repo is None:
        raise caddis_roadmap.RoadmapError("origin is not a GitHub remote; cannot open the PR", caddis_exit.NOT_RUN)
    try:
        number = caddis_roadmap.open_pr(repo, gh_repo, branch, base, title, body)
    except caddis_roadmap.RoadmapError:
        owner = gh_repo.split("/", 1)[0]
        proc = caddis_roadmap.run_bounded(["gh", "api", f"repos/{gh_repo}/pulls?head={owner}:{branch}&state=open"],
                                          caddis_roadmap.GH_TIMEOUT, "gh api (find the PR)")
        found = json.loads(proc.stdout or "[]") if proc.returncode == 0 else []
        if not found:
            raise
        number = int(found[0]["number"])
    return f"https://github.com/{gh_repo}/pull/{number}"


def session_branch(slug: str, plan: str, phase: int) -> str:
    """The branch the runner makes for one roadmap-mode session: `caddis/roadmap/<slug>/<plan>-p<n>`."""
    return f"caddis/roadmap/{slug}/{plan}-p{phase}"


def runner_folder(repo: Path, kind: str, slug: str) -> Path:
    """This runner's own state folder: `<git common dir>/caddis-runner/<kind>-<slug>/` (outside a git repo, the
    local folder). Shared at the top level: `claims/` and `claim.lock`."""
    lock = caddis_roadmap.runner_lock_path(repo, kind, slug)
    return lock.parent if lock is not None else _local_dir(repo, kind, slug)


def _state_file(repo: Path, slug: str, name: str) -> Path:
    """Roadmap runner state in its own folder: `<git common dir>/caddis-runner/roadmap-<slug>/<name>.json`."""
    return runner_folder(repo, "roadmap", slug) / f"{name}.json"


def claim_file(repo: Path, ref: str) -> Path | None:
    base = caddis_roadmap.runner_state_dir(repo)
    return None if base is None else base / "claims" / f"{ref}.json"


def _roadmap_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _branch_on_origin(repo: Path, branch: str) -> bool:
    proc = caddis_roadmap._git(repo, "ls-remote", "--heads", "origin", f"refs/heads/{branch}", check=False)
    return proc.returncode == 0 and bool(proc.stdout.strip())


WORKTREE_PREFIX = "caddis-roadmap-"


def _registered_worktrees(repo: Path) -> set[Path]:
    out = _git_out(repo, "worktree", "list", "--porcelain") or ""
    return {Path(line[len("worktree "):]).resolve() for line in out.splitlines() if line.startswith("worktree ")}


def worktree_path(repo: Path, slug: str, root: Path | None = None) -> Path:
    """The roadmap's session worktree: the recorded path, else (a NEW one) `caddis-roadmap-<slug>-<repo tag>` under
    `<worktree root>/<repo>/` (`caddis_worktree_root`: `root`, `$CADDIS_WORKTREE_ROOT`, else `<parent of the main
    checkout>/.worktrees`; never %TEMP%)."""
    recorded = _read_record(_state_file(repo, slug, "worktree")).get("path")
    if isinstance(recorded, str) and recorded:
        return Path(recorded)
    return caddis_worktree_root.worktree_path(repo, f"{WORKTREE_PREFIX}{slug}-{_repo_tag(repo)}", root)


def _repo_tag(repo: Path) -> str:
    """8 hex of sha256 of the resolved git common dir: two repos with the same roadmap slug get two worktrees."""
    base = caddis_roadmap.runner_state_dir(repo)
    common = base.parent if base is not None else Path(repo)
    return hashlib.sha256(os.path.normcase(str(common.resolve())).encode("utf-8")).hexdigest()[:8]


def ensure_worktree(repo: Path, slug: str, default: str, root: Path | None = None) -> Path:
    """Reuse the roadmap's worktree, or make it (`git worktree add --detach` at origin/<default>) and record it."""
    path = worktree_path(repo, slug, root)
    if path.resolve() in _registered_worktrees(repo):
        if path.is_dir():
            return path
        # Listed, but its folder is gone (temp cleanup): drop this one registration and make it again. Not
        # `git worktree prune`: that would drop every other tool's registration with a missing folder too.
        if caddis_worktree_safety.safe_remove_worktree(repo, path) is not None:
            raise _Stop(f"FAILED cannot drop the registration of the missing worktree {path}", caddis_exit.BLOCKED)
    if path.exists():
        raise _Stop(f"FAILED worktree path {path} exists and is not a worktree of this repo", caddis_exit.BLOCKED)
    path.parent.mkdir(parents=True, exist_ok=True)
    if _git_out(repo, "worktree", "add", "--quiet", "--detach", str(path), f"origin/{default}") is None:
        raise _Stop(f"FAILED cannot make the roadmap worktree {path}", caddis_exit.BLOCKED)
    caddis_created.record(path, "worktree", f"roadmap {slug} runner worktree", repo=repo, by="roadmap-run")
    _write_record(_state_file(repo, slug, "worktree"), {"path": str(path), "utc": _iso(datetime.now(timezone.utc))})
    return path


def _worktree_work(path: Path) -> list[str] | None:
    """Uncommitted work in a worktree (`git status --porcelain --untracked-files=all`, untracked `.caddis/relay/`
    files left out); None when the status cannot be read."""
    status = _git_out(path, "status", "--porcelain", "--untracked-files=all")
    if status is None:
        return None
    return [line for line in status.splitlines()
            if line.strip() and not (line.startswith("??") and line[3:].replace("\\", "/").startswith(".caddis/relay/"))]


def remove_worktree_if_clean(repo: Path, slug: str, root: Path | None = None) -> str:
    """At the end of a roadmap: remove its worktree when it holds no work (only session relays may be left);
    keep it otherwise. Returns a line for the stop."""
    path = worktree_path(repo, slug, root)
    if path.resolve() not in _registered_worktrees(repo):
        _state_file(repo, slug, "worktree").unlink(missing_ok=True)
        return "no worktree"
    work = _worktree_work(path)
    if work is None:
        return f"worktree kept (status not readable): {path}"
    if work:
        return f"worktree kept (not clean, {len(work)} change(s)): {path}"
    if caddis_worktree_safety.safe_remove_worktree(repo, path) is not None:
        return f"worktree kept (remove failed): {path}"
    _state_file(repo, slug, "worktree").unlink(missing_ok=True)
    caddis_created.record(path, "worktree", "", repo=repo, status="removed", by="roadmap-run")
    return f"worktree removed: {path}"


def default_delete_remote_branch(repo: Path, branch: str) -> None:
    """Delete the branch on GitHub (`gh api -X DELETE .../git/refs/heads/<branch>`; the account comes from GH_TOKEN).
    RoadmapError when it cannot."""
    gh_repo = caddis_roadmap.gh_repo_of(repo)
    if gh_repo is None:
        raise caddis_roadmap.RoadmapError("origin is not a GitHub remote; cannot delete the branch", caddis_exit.NOT_RUN)
    try:
        proc = caddis_roadmap.run_bounded(["gh", "api", "-X", "DELETE", f"repos/{gh_repo}/git/refs/heads/{branch}"],
                                          caddis_roadmap.GH_TIMEOUT, "gh api (delete the branch)")
    except OSError as exc:
        raise GhError(f"gh cannot delete {branch}: {type(exc).__name__}", caddis_exit.BLOCKED) from None
    if proc.returncode != 0:
        raise caddis_roadmap.RoadmapError(f"could not delete {branch} on origin: {(proc.stderr or '').strip()[:200]}",
                                          caddis_exit.BLOCKED)


def _checked_out_in(repo: Path, branch: str) -> list[Path]:
    """The worktrees (`git worktree list --porcelain`) that have `branch` checked out."""
    out, path = [], None
    for line in (_git_out(repo, "worktree", "list", "--porcelain") or "").splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree "):])
        elif line == f"branch refs/heads/{branch}" and path is not None:
            out.append(path)
    return out


def _delete_local_branch(repo: Path, branch: str, wt: Path | None) -> str | None:
    """Delete a local branch. Only the roadmap worktree `wt` may be detached for it; HEAD never moves in any other
    checkout: a branch checked out elsewhere is kept, and that checkout is returned as the reason."""
    for path in _checked_out_in(repo, branch):
        if wt is not None and path.resolve() == Path(wt).resolve():
            _git_out(path, "checkout", "-q", "--detach")
        else:
            return f"kept locally: checked out in {path}"
    if _git_out(repo, "branch", "-q", "-D", branch) is None and \
            _git_out(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}") is not None:
        return "kept locally: git branch -D failed"
    return None


def _cleanup_merged_branch(ctx: _Ctx, repo: Path, branch: str, wt: Path | None,
                           delete_remote_branch: Callable[[Path, str], None], made_branches: set,
                           branches_file: Path) -> None:
    """Whoever creates a branch removes it when its PR merges: the local branch, the branch on origin, the record."""
    if not branch:
        return
    kept = _delete_local_branch(repo, branch, wt)
    if kept:
        print(f"caddis_roadmap_run: {branch} {kept}", file=sys.stderr)
    try:
        delete_remote_branch(repo, branch)
    except caddis_roadmap.RoadmapError as exc:
        print(f"caddis_roadmap_run: {str(exc).splitlines()[0]}", file=sys.stderr)
    made_branches.discard(branch)
    prs = dict(_read_record(branches_file).get("prs") or {})
    prs.pop(branch, None)
    _write_record(branches_file, {"branches": sorted(made_branches), "prs": prs})
    ctx.log({"kind": "branch-removed", "branch": branch, "local": kept or "deleted",
             "time": _iso(datetime.now(timezone.utc))})


def _cleanup_finished_branches(repo: Path, slug: str, default: str,
                               pr_merged: Callable[[Path, str], bool] = lambda repo, url: False,
                               delete_remote_branch: Callable[[Path, str], None] = lambda repo, branch: None) -> str:
    """At the end of a roadmap: delete the local `caddis/roadmap/<slug>/*` branches that are merged: in
    origin/<default>'s history, or with a PR that GitHub says merged (a squash merge). A branch with a merged PR is
    deleted on origin too. Keep the others and name them."""
    names = (_git_out(repo, "for-each-ref", "--format=%(refname:short)", f"refs/heads/caddis/roadmap/{slug}/") or "")
    branches_file = _state_file(repo, slug, "branches")
    record = _read_record(branches_file)
    prs = dict(record.get("prs") or {})
    kept: list[str] = []
    for name in (n.strip() for n in names.splitlines() if n.strip()):
        url = prs.get(name)
        try:
            by_pr = bool(url) and pr_merged(repo, url)
        except Exception:  # gh cannot answer: keep the branch and name it
            by_pr = False
        merged = by_pr or subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", name,
                                          f"origin/{default}"], capture_output=True,
                                         stdin=subprocess.DEVNULL).returncode == 0
        if not (merged and _git_out(repo, "branch", "-q", "-D", name) is not None):
            kept.append(name)
            continue
        if by_pr:
            try:
                delete_remote_branch(repo, name)
            except caddis_roadmap.RoadmapError as exc:
                print(f"caddis_roadmap_run: {str(exc).splitlines()[0]}", file=sys.stderr)
        prs.pop(name, None)
    branches = sorted(set(record.get("branches") or []) & set(kept))
    if record:
        _write_record(branches_file, {"branches": branches, "prs": prs})
    return f"unmerged branches kept: {', '.join(kept)}" if kept else "no roadmap branches left"


def rollup_ready(snap: "caddis_roadmap.Snapshot", failed: dict | None = None) -> list[str]:
    """Milestones that wait only for their rollup: Status not done/not-needed, every phase merged (Tracker done on
    origin), and the same runner rule as `next` (caddis_roadmap.runner_ineligible: dependencies, blockers, Owner).
    `failed` (milestone -> roadmap hash) leaves out a milestone whose rollup already failed on this same roadmap."""
    rm = snap.roadmap
    failed = failed or {}
    sha = _roadmap_sha(snap.text)
    out = []
    for ms in rm.milestones:
        if ms.status in caddis_roadmap.FINISHED or not ms.phases or caddis_roadmap.runner_ineligible(rm, ms):
            continue
        if failed.get(ms.id) == sha:  # tried on this very roadmap and nothing was written: the owner decides
            continue
        if all(snap.phases.state(r) == "done" for r in ms.phases):
            out.append(ms.id)
    return out


def _rollup_ready_without_fetch(repo: Path, slug: str) -> list[str]:
    """rollup_ready on the origin copy as the local refs have it (no fetch: --last-stop only reads)."""
    try:
        branch = caddis_roadmap.default_branch(repo)
        text = caddis_roadmap.show(repo, branch, caddis_roadmap.roadmap_path(slug))
        if text is None:
            return []
        rm = caddis_roadmap.parse_roadmap(text)
        if rm.errors:
            return []
        snap = caddis_roadmap.Snapshot(repo, slug, branch, text, rm, caddis_roadmap.PhaseIndex(repo, branch), [])
        return rollup_ready(snap, _read_record(_state_file(repo, slug, "rollup-failed")))
    except Exception:  # a read that fails: nothing to report
        return []


def _check_orphaned_claims(repo: Path, slug: str, waiting: dict, pending: dict) -> None:
    """An own claim (`roadmap` = this slug) that neither the waiting record nor pending-rollup.json names is from a run
    killed between writing the claim and recording the wait. It is never deleted here: the owner checks the branch and
    its PR first."""
    known: set[str] = set()
    if waiting.get("ref"):
        named = claim_file(repo, str(waiting["ref"]))
        if named is not None:
            known.add(os.path.normcase(str(named)))
    if isinstance(pending.get("claim"), str) and pending["claim"]:
        known.add(os.path.normcase(pending["claim"]))
    for _name, path in sorted(_claims_of(repo, "roadmap", slug).items()):
        if os.path.normcase(str(path)) in known:
            continue
        batch = str(_read_record(path).get("batch") or path.stem)
        match = caddis_roadmap.REF_RE.match(batch)
        branch = session_branch(slug, match.group(1), int(match.group(2))) if match else "its branch"
        raise _Stop(f"BLOCKED orphaned claim {path} from a killed run: check {branch} / its PR, then delete the claim",
                    caddis_exit.BLOCKED)


def _held_batches(repo: Path, slug: str, snap: "caddis_roadmap.Snapshot") -> list[dict]:
    """The batches `next` skipped only because another runner's lock or claim held them (ref, kind, holder), from
    caddis_roadmap's structure, never from the reason text."""
    held: list[dict] = []
    caddis_roadmap._select(snap, caddis_roadmap.other_roadmap_holders(repo, slug), held_out=held)
    return held


def _clean_merged(ctx: _Ctx, repo: Path, slug: str, merged: dict, worktree_root: Path | None,
                  delete_remote_branch: Callable[[Path, str], None], made_branches: set, branches_file: Path) -> None:
    """A merged phase: its claim and its branch go (local, origin, the record)."""
    claim = merged.get("claim")
    if isinstance(claim, str) and claim:
        Path(claim).unlink(missing_ok=True)
    wt_now = worktree_path(repo, slug, worktree_root)
    _cleanup_merged_branch(ctx, repo, str(merged.get("branch") or ""), wt_now if wt_now.is_dir() else None,
                           delete_remote_branch, made_branches, branches_file)


def _run_roadmap(ctx: _Ctx, template: Path, dry_run: bool, after_session: Callable[[int], None] | None,
                 roadmap_cmd: list[str], hostname: str, publish: Callable[..., str],
                 pr_merged: Callable[[Path, str], bool] = lambda repo, url: False,
                 worktree_root: Path | None = None,
                 delete_remote_branch: Callable[[Path, str], None] = lambda repo, branch: None,
                 pr_closed: Callable[[Path, str], bool] = lambda repo, url: False) -> int:
    repo, slug, masks, caps = ctx.repo, ctx.target.slug, ctx.masks, ctx.caps
    lock = _RunnerLock(runner_lock_file(repo, "roadmap", slug), caps.max_hours,
                       claim_path=caddis_roadmap.claim_lock_path(repo))
    baseline: _Baseline | None = None

    def write(args: list[str], edit: tuple) -> None:
        rc = _roadmap_write(ctx, roadmap_cmd, args)
        if rc != caddis_exit.CLEAN:
            raise _Stop(f"FAILED roadmap {' '.join(args[:3])} exit {rc}", caddis_exit.BLOCKED)
        baseline.expect(*edit)

    def rollup(mid: str) -> int:
        """Roll the milestone up; the guard excuses only what the audit log says this rollup WROTE (merged). Returns
        how many changes it wrote."""
        written = 0
        seen = len(_audit_lines(repo, slug))
        rc = _roadmap_write(ctx, roadmap_cmd, ["rollup", "--id", mid])
        if rc == caddis_exit.NOT_RUN:  # a retry would fail the same way: the owner decides
            opened = []
            for line in _audit_lines(repo, slug)[seen:]:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict) and entry.get("id") == mid and entry.get("pr") is not None:
                    opened.append(f"#{entry['pr']}")
            if len(opened) > 1:
                written = (f"its docs PRs {', '.join(opened)} were opened and may still be open (the merge chain did "
                           "not finish): check them")
            elif opened:
                written = (f"its docs PR {opened[0]} was opened and may still be open (the merge chain did not "
                           "finish): check it")
            else:
                written = "nothing written"
            raise _Stop(f"{ROLLUP_NOT_RUN}: {mid} (its exit check or Exit setup could not run, or a git, lock or "
                        f"merge step; {written}; output in {caddis_roadmap.local_dir(repo, slug)}); the owner decides",
                        caddis_exit.BLOCKED)
        if rc not in (caddis_exit.CLEAN, caddis_exit.BLOCKED):
            raise _Stop(f"FAILED roadmap rollup {mid} exit {rc}", caddis_exit.BLOCKED)
        for line in _audit_lines(repo, slug)[seen:]:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict) or entry.get("id") != mid or entry.get("merge_exit") != caddis_exit.CLEAN:
                continue
            change = str(entry.get("change", ""))
            if change.startswith("Status "):
                baseline.expect("status", mid, change[len("Status "):])
                written += 1
            elif change == "block external":
                baseline.expect("blocker-like", mid, "external", ROLLUP_BLOCK_RE)
                written += 1
        return written

    if dry_run:  # no host check, no lock, no write: read origin and print what one iteration would do
        try:
            _dry_lock_check(lock.path)
            ctx.checks(0, 0.0, 0.0)
            if ctx.engine == "agy":
                _spend_preview(ctx.home, ctx.now())
            try:
                batch, snap = caddis_roadmap.next_with_snapshot(repo, slug)
            except caddis_roadmap.RoadmapError as exc:
                raise _Stop(f"FAILED roadmap not read: {exc}", exc.code, push=False) from None
            waiting = _read_record(_state_file(repo, slug, "waiting"))
            if waiting:  # a real start begins with the recorded wait
                ref, url = str(waiting.get("ref", "")), str(waiting.get("pr", ""))
                try:
                    merged = pr_merged(repo, url)
                except Exception as exc:
                    raise _Stop(f"{GH_STOP_PREFIX} {url} with account {_gh_who()}: {type(exc).__name__}",
                                caddis_exit.BLOCKED, push=False) from None
                if not merged:
                    print(f"still waiting for merge of {ref}: {url} (a real start stops here)")
                    return caddis_exit.CLEAN
                if snap.phases.state(ref) != "done":
                    raise _Stop(f"BLOCKED {ref} merged but its Tracker row is not done", caddis_exit.BLOCKED)
                print(f"merged path: {ref} merged ({url}); would check the roadmap against the published one, roll up "
                      f"{waiting.get('milestone')} when every phase is merged, then remove the claim and "
                      f"{waiting.get('branch')}, then take the next batch")
                return caddis_exit.CLEAN
            if batch is None:
                raise _Stop(f"BLOCKED nothing ready: {_status_line(repo, slug)}", caddis_exit.BLOCKED)
        except _Stop as stop:
            print(f"would stop: {caddis_redact.redact(stop.reason, masks)}")
            return stop.code if stop.code != caddis_exit.CLEAN else caddis_exit.NOT_RUN
        mid, plan, phase = batch["milestone"], batch["plan"], batch["phase"]
        ready = rollup_ready(snap, _read_record(_state_file(repo, slug, "rollup-failed")))
        if ready:
            print(f"would roll up first: {', '.join(ready)}")
        pending = _read_record(_state_file(repo, slug, "pending-rollup"))
        if pending:
            print(f"pending rollup: {pending.get('ref')} (would roll up {pending.get('milestone')} and clean up "
                  f"{pending.get('branch')} first)")
        print(f"next: {mid} {plan}#{phase}")
        print(f"roadmap {slug}: runner host {snap.roadmap.runner_host or '(none)'} (not checked in a dry run); "
              f"lock {lock.path}; local files in {ctx.target.local}")
        lane = phase_lane(_plan_text(snap, plan), phase) or "none"
        if not lane_runs_here(lane, ctx.engine):
            print(f"would block {mid}: owner-gate phase {phase} lane: {lane}")
            return caddis_exit.CLEAN
        if snap.roadmap.get(mid).status == "todo":
            print(f"would set {mid} Status in-progress (docs PR)")
        wt = worktree_path(repo, slug, worktree_root)
        if wt.resolve() in _registered_worktrees(repo):
            print(f"would reuse the roadmap worktree {wt}")
        else:
            print(f"would create the roadmap worktree {wt} from origin/{snap.branch} (git worktree add --detach)")
        print(f"would make the session branch {session_branch(slug, plan, phase)} from origin/{snap.branch} in it")
        _dry_run_tail(ctx, template, render_prompt(template, plan, phase), cwd=wt)
        print("then: on CONTINUE with new commits on that branch, push it, open a PR and stop "
              f"`{WAITING_PREFIX}`; the recheck task restarts the runner after the merge")
        return caddis_exit.CLEAN

    try:  # the Runner host first, read only: a wrong-host start must change nothing (no lock, no record)
        host = caddis_roadmap.load(repo, slug).roadmap.runner_host
    except caddis_roadmap.RoadmapError:
        host = None  # the read below, under the lock, reports and records it
    if host is not None and host.casefold() != hostname.casefold():
        return _finish(_Stop(f"BLOCKED this host {hostname} is not the roadmap's Runner host {host}",
                             caddis_exit.NOT_RUN, push=False), ctx, False, 0, 0.0, None)
    try:
        lock.acquire(lambda message: _stale_notice(ctx, message))
    except _Stop as stop:
        return _finish(stop, ctx, False, 0, 0.0, None)
    except OSError as exc:
        return _finish(_Stop(f"BLOCKED claim not written: the runner lock ({type(exc).__name__})",
                             caddis_exit.BLOCKED), ctx, False, 0, 0.0, None)
    try:
        first = caddis_roadmap.load(repo, slug)
    except caddis_roadmap.RoadmapError as exc:  # like any stop: notify once and record it (not restartable)
        ctx.last_stop = last_stop_file(repo, "roadmap", slug)
        try:
            return _finish(_Stop(f"FAILED roadmap not read: {str(exc).splitlines()[0]}", exc.code), ctx, False, 0,
                           0.0, None)
        finally:
            lock.release()
    if first.roadmap.runner_host.casefold() != hostname.casefold():
        lock.release()
        return _finish(_Stop(f"BLOCKED this host {hostname} is not the roadmap's Runner host "
                             f"{first.roadmap.runner_host}", caddis_exit.NOT_RUN, push=False), ctx, False, 0, 0.0, None)
    waiting_file = _state_file(repo, slug, "waiting")
    waiting = _read_record(waiting_file)  # the waiting-for-merge data lives here, never in the last stop
    merged_by_gh = tracker_done = False
    if waiting:
        ref, url = str(waiting.get("ref", "")), str(waiting.get("pr", ""))
        tracker_done = first.phases.state(ref) == "done"
        try:  # GitHub must confirm the merge, also when the Tracker row is done: no branch goes on the row alone
            merged_by_gh = pr_merged(repo, url)
            closed = not merged_by_gh and pr_closed(repo, url)
        except Exception as exc:  # gh missing, 401, 404: a recorded, notified stop; the lock is released
            gh_repo = re.search(r"github\.com/([^/]+/[^/]+)/pull/", url or "")
            ctx.last_stop = last_stop_file(repo, "roadmap", slug)
            try:
                return _finish(_Stop(f"{GH_STOP_PREFIX} {gh_repo.group(1) if gh_repo else url} with account "
                                     f"{_gh_who()}: {type(exc).__name__}", caddis_exit.BLOCKED),
                               ctx, False, 0, 0.0, None)  # waiting.json stays: the next start resumes
            finally:
                lock.release()
        if tracker_done and not merged_by_gh:  # the row says done, GitHub does not: keep everything, owner decides
            ctx.last_stop = last_stop_file(repo, "roadmap", slug)
            try:
                return _finish(_Stop(f"BLOCKED {ref} Tracker row is done but PR {url} is not merged",
                                     caddis_exit.BLOCKED), ctx, False, 0, 0.0, None)
            finally:
                lock.release()
        if not tracker_done:
            if closed:  # closed without a merge: clean up under the lock
                claim = claim_file(repo, ref) if ref else None
                if claim is not None:
                    claim.unlink(missing_ok=True)
                waiting_file.unlink(missing_ok=True)
                ctx.last_stop = last_stop_file(repo, "roadmap", slug)
                try:
                    return _finish(_Stop(f"BLOCKED {ref} PR closed without a merge", caddis_exit.BLOCKED),
                                   ctx, False, 0, 0.0, None)
                finally:
                    lock.release()
            if not merged_by_gh:  # still waiting: stop now, leave the waiting record, the claim and the last stop
                lock.release()
                return _finish(_Stop(f"BLOCKED still waiting for merge of {ref}: {url}", caddis_exit.BLOCKED,
                                     push=False), ctx, False, 0, 0.0, None)
    _mark_running(ctx, last_stop_file(repo, "roadmap", slug))
    if not ENGINES[ctx.engine]["live_tested"]:
        print(f"caddis_roadmap_run: engine {ctx.engine} is an adapter, not live-tested", file=sys.stderr)
    branches_file = _state_file(repo, slug, "branches")
    made_branches = set(_read_record(branches_file).get("branches") or [])

    sessions, spent, stuck, pushed = 0, 0.0, 0, False  # per run, in memory
    pending_file = _state_file(repo, slug, "pending-rollup")
    swept = False
    relay_slug: str | None = None
    last_write: tuple[str, str] | None = None
    wt: Path | None = None
    start = ctx.clock()

    try:
        baseline = _Baseline(first.roadmap)
        if waiting:
            # A restart after `BLOCKED waiting for merge`: the merged origin roadmap must still be the one the runner
            # published against. Never take a fresh baseline without this check.
            saved = _read_text(_state_file(repo, slug, "published-roadmap").with_suffix(".md"))
            hint = (f" (if the owner made this change: roadmap-run.ps1 -Roadmap {slug} -AcceptRoadmap, then start "
                    "again)")
            if waiting.get("roadmap_sha") != _roadmap_sha(first.text):
                if saved is None or _roadmap_sha(saved) != waiting.get("roadmap_sha"):
                    raise _Stop("FAILED roadmap changed: the origin roadmap differs from the one published against"
                                + hint, caddis_exit.BLOCKED)
                try:
                    _Baseline(caddis_roadmap.parse_roadmap(saved)).observe(first)
                except _Stop as stop:
                    raise _Stop(stop.reason + hint, stop.code) from None
            ref = str(waiting.get("ref", ""))
            claim = claim_file(repo, ref) if ref else None
            if claim is not None and (not waiting.get("claim_sha") or not claim.is_file()
                                      or _sha_file(claim) != waiting.get("claim_sha")):  # fail closed
                raise _Stop(f"FAILED own claim missing or changed: {ref}", caddis_exit.BLOCKED)
            merged = {"ref": ref, "pr": waiting.get("pr"), "milestone": waiting.get("milestone"),
                      "claim": str(claim) if claim is not None else None, "branch": waiting.get("branch")}
            if merged_by_gh and not tracker_done:  # GitHub says merged, the row is not done: the owner decides
                _clean_merged(ctx, repo, slug, merged, worktree_root, delete_remote_branch, made_branches,
                              branches_file)
                waiting_file.unlink(missing_ok=True)
                raise _Stop(f"BLOCKED {ref} merged but its Tracker row is not done", caddis_exit.BLOCKED)
            if tracker_done and merged_by_gh:
                # The merged work moves to its own file (rollup first, cleanup after, then the file goes), and the
                # wait is over. Any stop before that records itself; the next start finds pending-rollup.json.
                _write_record(pending_file, {**merged, "utc": _iso(datetime.now(timezone.utc))})
                waiting_file.unlink(missing_ok=True)
        _check_orphaned_claims(repo, slug, _read_record(waiting_file), _read_record(pending_file))
        while True:
            ctx.checks(sessions, spent, ctx.clock() - start)
            pending = _read_record(pending_file)
            if pending:
                mid = pending.get("milestone")
                if isinstance(mid, str):
                    snap = _load_observed(repo, slug, baseline)
                    ms = snap.roadmap.get(mid)
                    if ms is not None and ms.status in caddis_roadmap.OPEN and ms.phases and \
                            all(snap.phases.state(r) == "done" for r in ms.phases):
                        rollup(mid)  # raises _Stop on a failed rollup: recorded, the file stays
                _clean_merged(ctx, repo, slug, pending, worktree_root, delete_remote_branch, made_branches,
                              branches_file)
                pending_file.unlink(missing_ok=True)
            if not swept:  # once per run: roll up every milestone that waits only for its rollup
                swept = True
                snap = _load_observed(repo, slug, baseline)
                failed_file = _state_file(repo, slug, "rollup-failed")
                for mid in rollup_ready(snap, _read_record(failed_file)):
                    if rollup(mid) == 0:  # nothing written: a recorded stop, and recheck must not retry it
                        _write_record(failed_file, {**_read_record(failed_file), mid: _roadmap_sha(snap.text)})
                        raise _Stop(f"BLOCKED rollup of {mid} wrote nothing; the owner decides", caddis_exit.BLOCKED)
            with _claim(repo):  # choose and claim atomically: no other runner can choose the same batch
                try:
                    batch, snap = caddis_roadmap.next_with_snapshot(repo, slug)
                except caddis_roadmap.RoadmapError as exc:
                    raise _Stop(f"FAILED roadmap changed: the origin copy no longer loads: "
                                f"{str(exc).splitlines()[0]}", caddis_exit.BLOCKED) from None
                baseline.observe(snap)
                if batch is not None:
                    lock.set_batch(f"{batch['plan']}#{batch['phase']}")
            if batch is None:
                detail = _status_line(repo, slug)
                if snap.roadmap.milestones and all(ms.status in caddis_roadmap.FINISHED
                                                   for ms in snap.roadmap.milestones):
                    gone = remove_worktree_if_clean(repo, slug, worktree_root)
                    detail += "; roadmap finished; " + gone
                    if gone.startswith(("worktree removed", "no worktree")):
                        detail += "; " + _cleanup_finished_branches(repo, slug, snap.branch, pr_merged,
                                                                     delete_remote_branch)
                raise _Stop(RESTARTABLE_STOP, caddis_exit.BLOCKED, detail=detail,
                            record={"held": _held_batches(repo, slug, snap)})
            mid, plan, phase = batch["milestone"], batch["plan"], batch["phase"]
            ref = f"{plan}#{phase}"
            print(f"next: {mid} {ref}")
            if last_write == (mid, ref):  # the runner's own block did not take the batch off `next`
                raise _Stop(f"FAILED roadmap unchanged after the runner's write for {mid} {ref}",
                            caddis_exit.BLOCKED)
            relay_slug = plan
            plan_text = _plan_text(snap, plan)
            lane = phase_lane(plan_text, phase) or "none"  # no Lane line: not the runner's (fail closed)
            if not lane_runs_here(lane, ctx.engine):
                reason = f"phase {phase} lane: {' '.join(lane.split())[:160]}".strip()
                write(["block", "--id", mid, "--type", "owner-gate", "--reason", reason],
                      ("blocker", mid, "owner-gate", reason))
                last_write = (mid, ref)
                continue
            last_write = None
            if snap.roadmap.get(mid).status == "todo":
                write(["set", "--id", mid, "--col", "Status", "--value", "in-progress"],
                      ("status", mid, "in-progress"))
                snap = _load_observed(repo, slug, baseline)  # the write window is guarded too
            # Every session runs in the roadmap's own worktree, on a fresh branch made from origin/<default>.
            wt = wt or ensure_worktree(repo, slug, snap.branch, worktree_root)
            branch = session_branch(slug, plan, phase)
            if branch not in made_branches and _branch_on_origin(repo, branch):
                raise _Stop(f"BLOCKED branch {branch} is on origin and this runner did not make it",
                            caddis_exit.BLOCKED)
            for ref_name in (f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"):
                if _git_out(wt, "rev-parse", "--verify", "--quiet", ref_name) is None:
                    continue
                ahead = _git_out(wt, "rev-list", "--count", f"origin/{snap.branch}..{ref_name}")
                if ahead is None or ahead != "0":  # an earlier session's work: never reset it
                    raise _Stop(f"BLOCKED {branch} has unpublished commits from an earlier session",
                                caddis_exit.BLOCKED)
            left = _worktree_work(wt)  # a blocked session's uncommitted work must never ride into another branch
            if left is None or left:
                was = _git_out(wt, "rev-parse", "--abbrev-ref", "HEAD") or "?"
                raise _Stop(f"BLOCKED roadmap worktree has uncommitted work from {was} ({wt})", caddis_exit.BLOCKED)
            made = _git_out(wt, "checkout", "-q", "-B", branch, f"origin/{snap.branch}")
            if made is None:
                raise _Stop(f"FAILED cannot make the session branch {branch} in {wt} (is it clean?)",
                            caddis_exit.BLOCKED)
            head_before = _git_out(wt, "rev-parse", "HEAD")
            done_before = _done_phases(snap, plan)
            state_before = state_snapshot(repo, "roadmap", slug)
            s = _one_session(ctx, render_prompt(template, plan, phase), plan, sessions + 1, spent,
                             ctx.clock() - start, slug, cwd=wt)
            _check_state(repo, "roadmap", slug, state_before)  # before the runner writes anything after it
            sessions += 1
            spent += s.cost
            pushed = s.pushed
            s.record.update({"milestone": mid, "batch": ref, "branch": branch})
            try:
                stop = _decide(ctx.engine, s.outcome, s.result, s.relay_text, s.hash_before, s.hash_after)
                s.record["status"] = "CONTINUE" if stop is None else stop.reason
                after = _load_observed(repo, slug, baseline)  # one read after the session (no merge wait)
                stuck = 0 if _done_phases(after, plan) > done_before else stuck + 1
                if stop is not None:
                    if stop.status is None or stop.status[0] not in ("OWNER-GATE", "BLOCKED"):
                        raise stop
                    btype = "owner-gate" if stop.status[0] == "OWNER-GATE" else "external"
                    reason = f"{ref}: {stop.status[1]}".strip()
                    write(["block", "--id", mid, "--type", btype, "--reason", reason], ("blocker", mid, btype, reason))
                    last_write = (mid, ref)
                elif after.phases.state(ref) != "done":
                    def review_before_publish() -> None:
                        # The review gate runs BEFORE the claim and the push: a `risk: high` phase is never
                        # published unreviewed. Its review and fix session count against the caps.
                        nonlocal sessions, spent, pushed
                        tally = _Tally(sessions, spent, pushed)
                        try:
                            reviewed = _review_gate(ctx, tally, plan=plan, extra_texts=(plan_text,),
                                                    origin_text=_plan_text(after, plan) or None,
                                                    elapsed=lambda: ctx.clock() - start, spend_slug=slug,
                                                    also=(phase,), cwd=wt)
                        finally:
                            sessions, spent, pushed = tally.sessions, tally.spent, tally.pushed
                        if reviewed:
                            _load_observed(repo, slug, baseline)  # the review and fix window is guarded too
                            now_on = _git_out(wt, "rev-parse", "--abbrev-ref", "HEAD")
                            if now_on != branch:
                                raise _Stop(f"FAILED {ref}: the review fix round left the runner's branch {branch} "
                                            f"(now on {now_on})", caddis_exit.BLOCKED)

                    _publish_and_wait(ctx, wt, slug, mid, plan, phase, ref, branch, head_before, after, plan_text,
                                      publish, made_branches, branches_file, s.record,
                                      before_publish=review_before_publish)
                else:
                    ms = after.roadmap.get(mid)
                    if ms is not None and all(after.phases.state(r) == "done" for r in ms.phases):
                        rollup(mid)
                if stuck >= STUCK_SESSIONS:
                    raise _Stop("BLOCKED stuck", caddis_exit.BLOCKED)
            except _Stop as stop_now:
                s.record.setdefault("stop", stop_now.reason)
                raise
            finally:
                s.record.setdefault("status", "FAILED")
                ctx.log(s.record)
            if after_session is not None:
                after_session(sessions)
    except _Stop as stop:
        return _finish(stop, ctx, pushed, sessions, spent, relay_slug, wt)
    except Exception as exc:
        _crashed(ctx, exc, pushed, sessions, spent, relay_slug, wt)
        raise
    finally:
        lock.release()


def _sha_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "unreadable"


def _claims_of(repo: Path, kind: str, slug: str) -> dict[str, Path]:
    """This runner's claims (`claims/*.json` whose `roadmap` field, or `plan` for plan mode, is `slug`)."""
    base = caddis_roadmap.runner_state_dir(repo)
    out: dict[str, Path] = {}
    if base is None:
        return out
    try:
        files = sorted((base / "claims").glob("*.json"))
    except OSError:
        return out
    for path in files:
        if _read_record(path).get(kind) == slug:
            out[f"claims/{path.name}"] = path
    return out


def state_snapshot(repo: Path, kind: str, slug: str) -> dict[str, str]:
    """sha256 of every file in THIS runner's folder (`<git common dir>/caddis-runner/<kind>-<slug>/`, recursively,
    so later records such as `reviewed/` too) and of this runner's own claims. Another runner's state is not
    watched: it never stops this one. Outside a git repo: empty."""
    base = caddis_roadmap.runner_state_dir(repo)
    out: dict[str, str] = {}
    if base is None:
        return out
    own = base / f"{kind}-{slug}"
    if own.is_dir():
        for path in sorted(own.rglob("*")):
            if path.is_file():
                out[path.relative_to(base).as_posix()] = _sha_file(path)
    for name, path in _claims_of(repo, kind, slug).items():
        out[name] = _sha_file(path)
    return out


def _state_changes(before: dict[str, str], after: dict[str, str]) -> list[str]:
    changes = [f"{name} removed" for name in before if name not in after]
    changes += [f"{name} added" for name in after if name not in before]
    changes += [f"{name} changed" for name in before if name in after and before[name] != after[name]]
    return changes


def _check_state(repo: Path, kind: str, slug: str, before: dict[str, str]) -> None:
    """The runner writes none of its own state while a session runs, so a change there is a session's mistake:
    stop, not restartable. Sessions are cooperative; this catches accidents, it is not a security boundary."""
    changes = _state_changes(before, state_snapshot(repo, kind, slug))
    if changes:
        raise _Stop("FAILED runner state changed: " + "; ".join(changes[:5]), caddis_exit.BLOCKED)


def _read_text(path: Path) -> str | None:
    try:
        return Path(path).read_bytes().decode("utf-8")
    except OSError:
        return None


def _publish_and_wait(ctx: _Ctx, repo: Path, slug: str, mid: str, plan: str, phase: int, ref: str, branch: str,
                      head_before: str | None, after: "caddis_roadmap.Snapshot", plan_text: str,
                      publish: Callable[..., str], made_branches: set, branches_file: Path, record: dict,
                      before_publish: Callable[[], None] | None = None) -> None:
    """CONTINUE with the phase not merged: publish the runner's session branch and raise the waiting stop.
    Refuses (FAILED, not restartable) when the session left that branch, made no commit, or touched the roadmap."""
    def verify() -> None:
        current = _git_out(repo, "rev-parse", "--abbrev-ref", "HEAD")
        if current != branch:
            raise _Stop(f"FAILED {ref}: the session left the runner's branch {branch} (now on {current})",
                        caddis_exit.BLOCKED)
        head_after = _git_out(repo, "rev-parse", "HEAD")
        ahead = _git_out(repo, "rev-list", "--count", f"origin/{after.branch}..{branch}")
        if head_after == head_before or not ahead or ahead == "0":
            raise _Stop(f"FAILED {ref}: CONTINUE with no new commits on {branch} and not merged",
                        caddis_exit.BLOCKED)
        listing = _git_out(repo, "diff", "--name-only", f"origin/{after.branch}...{branch}")
        if listing is None:  # fail closed: without the list of changed files, never publish
            raise _Stop(f"FAILED {ref}: cannot list the session's changes (git diff --name-only failed); "
                        "not published", caddis_exit.BLOCKED)
        touched = [p for p in listing.splitlines() if p.replace("\\", "/").startswith(".caddis/roadmaps/")]
        if touched:
            raise _Stop(f"FAILED session changed the roadmap ({', '.join(touched[:3])}); not published",
                        caddis_exit.BLOCKED)

    verify()
    if before_publish is not None:  # the review gate (caddis-next Phase 11); a fix session may have committed
        before_publish()
        verify()
    claim = claim_file(repo, ref)
    utc = _iso(datetime.now(timezone.utc))
    if claim is not None:  # the phase stays held while its PR waits (written before the push)
        try:
            claim.parent.mkdir(parents=True, exist_ok=True)
            _replace_with(claim, json.dumps({"batch": ref, "roadmap": slug, "pr": None, "utc": utc}))
        except OSError as exc:
            raise _Stop(f"BLOCKED claim not written: {ref} ({type(exc).__name__})", caddis_exit.BLOCKED) from None
        ctx.written_claims.append(claim)
    try:  # from here to the waiting record, ANY failure removes the claim and stops FAILED (not restartable)
        title = f"{plan} phase {phase}" + (f": {_phase_title(plan_text, phase)}"
                                           if _phase_title(plan_text, phase) else "")
        body = f"Opened by caddis_roadmap_run.py for roadmap {slug}, milestone {mid}, {ref}."
        made_branches.add(branch)  # recorded BEFORE the push: a push that lands and a PR that fails do not lock it out
        _write_record(branches_file, {**_read_record(branches_file), "branches": sorted(made_branches)})
        url = publish(repo, branch, after.branch, title, body)
        prs = dict(_read_record(branches_file).get("prs") or {})
        prs[branch] = url  # the finished roadmap uses it to tell a squash-merged branch from an unmerged one
        _write_record(branches_file, {"branches": sorted(made_branches), "prs": prs})
        claim_sha = None
        if claim is not None:
            _write_record(claim, {"batch": ref, "roadmap": slug, "pr": url, "utc": utc})
            claim_sha = _sha_file(claim)
        saved = _state_file(repo, slug, "published-roadmap").with_suffix(".md")
        try:
            saved.parent.mkdir(parents=True, exist_ok=True)
            tmp = saved.with_name(f"{saved.name}.{os.getpid()}.tmp")
            tmp.write_bytes(after.text.encode("utf-8"))  # bytes: the exact text the hash was taken of
            os.replace(tmp, saved)
        except OSError as exc:
            print(f"caddis_roadmap_run: published roadmap not saved: {exc}", file=sys.stderr)
        record["pr"] = url
    except Exception as exc:
        if claim is not None:
            claim.unlink(missing_ok=True)
            if claim in ctx.written_claims:
                ctx.written_claims.remove(claim)
        detail = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        raise _Stop(f"FAILED {ref}: could not push or open the PR: {detail}", caddis_exit.BLOCKED) from None
    if claim is not None and claim in ctx.written_claims:
        ctx.written_claims.remove(claim)  # the waiting record below holds it now
    _write_record(_state_file(repo, slug, "waiting"),  # the waiting data, in its own file (never in the last stop)
                  {"ref": ref, "pr": url, "milestone": mid, "branch": branch,
                   "claim": str(claim) if claim is not None else None, "claim_sha": claim_sha,
                   "roadmap_sha": _roadmap_sha(after.text), "utc": _iso(datetime.now(timezone.utc))})
    raise _Stop(f"{WAITING_PREFIX} {ref} {url}", caddis_exit.BLOCKED)


def _spend_reserve(home: Path, slug: str, moment: datetime, started: bool) -> str:
    """Book one agy session under the global spend cap (caddis_spend.py); _Stop when the cap refuses it or cannot be
    read (a file error never crashes the runner: the stop is logged and notified, redacted, like any other).
    The caller name in the spend log is `runner-<slug>`."""
    try:
        rid = caddis_spend.reserve(home, f"runner-{slug}", moment)
    except caddis_spend.NotConfigured:
        code = caddis_exit.BLOCKED if started else caddis_exit.NOT_RUN
        raise _Stop("FAILED spend cap not configured", code) from None
    except TimeoutError:
        raise _Stop("BLOCKED spend cap lock busy", caddis_exit.BLOCKED) from None
    except Exception as exc:
        raise _Stop(f"FAILED spend cap error: {exc!r}", caddis_exit.BLOCKED) from None
    if rid is None:
        raise _Stop("BLOCKED spend cap", caddis_exit.BLOCKED)
    return rid


def _spend_settle(home: Path, rid: str, cmd: Sequence[str], outcome: "_Outcome | None", moment: datetime,
                  duration_s: float) -> None:
    """Record the session's real cost: (0, 0) when it never started, its reserve (estimated) when there is no outcome
    (an exception) or no readable token counts."""
    try:
        if outcome is None:
            usage_counts = None
        elif not outcome.started:
            usage_counts = (0, 0)  # nothing ran, nothing was spent
        elif caddis_spend.json_mode(list(cmd)):
            usage_counts = caddis_spend.tokens_from_output(outcome.stdout)
        else:
            usage_counts = None
        caddis_spend.settle(home, rid, usage_counts, moment, duration_s=duration_s)
    except Exception as exc:  # the pending reserve keeps counting for 24 h; never lose the session's result
        print(f"caddis_roadmap_run: could not settle spend {rid}: {exc}", file=sys.stderr)


def _spend_preview(home: Path, moment: datetime) -> None:
    """The dry run's read-only spend check: the same stops as _spend_reserve, with no pending line written."""
    try:
        cap = caddis_spend.load_cap(home)
        over = caddis_spend.committed_last_24h(home, moment) + cap.reserve > cap.eur_per_24h
    except caddis_spend.NotConfigured:
        raise _Stop("FAILED spend cap not configured", caddis_exit.NOT_RUN) from None
    except Exception as exc:
        raise _Stop(f"FAILED spend cap error: {exc!r}", caddis_exit.NOT_RUN) from None
    if over:
        raise _Stop("BLOCKED spend cap", caddis_exit.BLOCKED)


@dataclass
class _Outcome:
    code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    started: bool = True


def _launch(cmd: list[str], cwd: Path, timeout_s: float, stdin_text: str | None = None,
            env: dict | None = None) -> _Outcome:
    try:
        proc = subprocess.run(cmd, cwd=cwd, input=stdin_text if stdin_text is not None else "", capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout_s,
                              env=env if env is not None else session_env())
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return _Outcome(-1, out, err, timed_out=True)
    except OSError as exc:
        return _Outcome(-1, "", f"cannot start session: {exc}", started=False)
    return _Outcome(proc.returncode, proc.stdout or "", proc.stderr or "")


def _decide(engine: str, outcome: _Outcome, result: dict | None, relay_text: str, hash_before: str | None,
            hash_after: str | None) -> _Stop | None:
    """None to go on; else the stop. A missing or bad status line is FAILED, never CONTINUE (design 8.1)."""
    failed = _session_failed(engine, outcome, result)
    if failed is not None:
        return failed
    if hash_after is None:
        return _Stop("FAILED no relay", caddis_exit.BLOCKED)
    try:
        kind, arg = caddis_workstreams.parse_status(relay_text)
    except ValueError as exc:
        return _Stop(f"FAILED bad status line: {exc}", caddis_exit.BLOCKED)
    if kind == "CONTINUE":
        if hash_after == hash_before:
            return _Stop("FAILED no progress", caddis_exit.BLOCKED)
        return None
    if kind == "FAILED":
        return _Stop(f"FAILED {arg}", caddis_exit.BLOCKED, from_relay=True, status=(kind, arg))
    return _Stop(f"{kind} {arg}", caddis_exit.CLEAN, from_relay=True, status=(kind, arg))


def _session_failed(engine: str, outcome: _Outcome, result: dict | None) -> _Stop | None:
    """The stop for a session that did not finish cleanly (usage limit, timeout, exit code, output, error); None when
    it did. The relay is not read here: a review fix session writes no status line."""
    if usage_limited(engine, outcome.stdout + "\n" + outcome.stderr):
        return _Stop("BLOCKED usage limit", caddis_exit.BLOCKED, push=False)
    if outcome.timed_out:
        return _Stop("FAILED session timeout", caddis_exit.BLOCKED)
    if outcome.code != 0:
        tail = " ".join(outcome.stderr.split())[-160:]
        return _Stop(f"FAILED session exit {outcome.code}" + (f": {tail}" if tail else ""), caddis_exit.BLOCKED)
    if result is None:
        return _Stop("FAILED session output is not JSON", caddis_exit.BLOCKED)
    if result.get("is_error") is True:
        return _Stop(f"FAILED session error: {result.get('subtype', 'unknown')}", caddis_exit.BLOCKED)
    return None


def _closed(target: Target) -> int:
    return sum(closed_rows(path) for path in target.progress)


def _finish(stop: _Stop, ctx: _Ctx, pushed: bool, sessions: int, spent: float, relay_slug: str | None,
            relay_root: Path | None = None) -> int:
    masks, target = ctx.masks, ctx.target
    line = f"STATUS: {stop.reason}" if stop.from_relay else f"RUNNER STOP: {stop.reason}"
    if stop.detail:
        message = caddis_redact.redact(f"{line}. {stop.detail}", masks)
    else:
        relay_text = _read_relay(relay_root or ctx.repo, relay_slug)[0] if relay_slug else ""
        # Redact BEFORE _next_step cuts the text to 120 characters: a key cut in half is no longer an exact match.
        relay_text = caddis_redact.redact(relay_text, masks)
        next_step = caddis_workstreams._next_step(relay_text) if relay_text else "next step unrecorded"
        message = caddis_redact.redact(f"{line}. Next: {next_step}", masks)  # relay text is session-written
    if ctx.last_stop is not None:
        _write_options(ctx)  # re-written from memory at every stop: a changed file can never raise the caps
        _write_last_stop(ctx.last_stop, stop)  # always the REAL stop
    toast_exit = ctx.toast(f"caddis {target.kind} {target.slug}", message)
    push_exit = None
    if stop.push and not (pushed and stop.from_relay):  # PUSH-SENT covers only the stop the session reported
        push_exit = ctx.push(f"{target.kind} {target.slug}: {message}")
    ctx.log({"kind": "stop", "stop": stop.reason, "exit": stop.code, "sessions": sessions, "usd": round(spent, 4),
             "toast_exit": toast_exit, "push_exit": push_exit, "time": _iso(datetime.now(timezone.utc))})
    print(caddis_redact.redact(f"RUNNER STOP: {stop.reason} (sessions {sessions}, USD {spent:.2f}, exit {stop.code})",
                               masks))
    return stop.code


def _write_record(path: Path, record: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _replace_with(path, json.dumps(record))
    except OSError as exc:  # the recheck task then finds an old record; it restarts only after "nothing ready"
        print(f"caddis_roadmap_run: runner state not written to {path}: {exc}", file=sys.stderr)


def _write_last_stop(path: Path, stop: _Stop) -> None:
    _write_record(path, {**stop.record, "reason": stop.reason, "exit": stop.code,
                         "utc": _iso(datetime.now(timezone.utc))})


def options_file(last_stop: Path) -> Path:
    """The launch options of the run that holds (or last held) the lock, next to its last stop."""
    return last_stop.with_name("options.json")


def _write_options(ctx: _Ctx) -> None:
    """The launch options, from the run's memory (never from the file, which a session can write)."""
    caps = ctx.caps
    _write_record(options_file(ctx.last_stop), {
        "engine": ctx.engine, "model": ctx.model, "max_hours": caps.max_hours, "max_sessions": caps.max_sessions,
        "session_timeout_min": caps.session_timeout_min, "max_usd_per_session": caps.max_usd_per_session,
        "max_usd_total": caps.max_usd_total, "gh_account": ctx.gh_account})


def _mark_running(ctx: _Ctx, last_stop: Path) -> None:
    """At lock time: the last stop becomes `running` (not restartable) and the launch options are recorded, so a run
    that is killed without a stop needs the owner, and the recheck task restarts with the same options."""
    ctx.last_stop = last_stop
    _write_options(ctx)
    _write_record(last_stop, {"reason": RUNNING, "exit": None, "utc": _iso(datetime.now(timezone.utc)),
                              "pid": os.getpid()})


def _crashed(ctx: _Ctx, exc: Exception, pushed: bool, sessions: int, spent: float, relay_slug: str | None,
             relay_root: Path | None = None) -> None:
    """An unexpected exception in the loop: record `FAILED crash: <type>` and notify once; the caller re-raises.
    `relay_root`: where the session relay is (roadmap mode: the roadmap worktree)."""
    stop = _Stop(f"FAILED crash: {type(exc).__name__}", caddis_exit.BLOCKED)
    for claim in list(ctx.written_claims):  # a claim with no waiting record must not hold the phase for ever
        Path(claim).unlink(missing_ok=True)
    ctx.written_claims.clear()
    try:
        _finish(stop, ctx, pushed, sessions, spent, relay_slug, relay_root)
    except Exception as again:  # never hide the first exception
        print(f"caddis_roadmap_run: crash not notified: {again!r}", file=sys.stderr)
        if ctx.last_stop is not None:
            _write_last_stop(ctx.last_stop, stop)


_ARG_RE = re.compile(r"^[A-Za-z0-9._\[\]-]+$")
_RESTART_ARGS = (("engine", "-Engine"), ("model", "-Model"), ("max_hours", "-MaxHours"),
                 ("max_sessions", "-MaxSessions"), ("session_timeout_min", "-SessionTimeoutMin"),
                 ("max_usd_per_session", "-MaxUsdPerSession"), ("max_usd_total", "-MaxUsdTotal"),
                 ("gh_account", "-GhAccount"))


def restart_args(repo: Path, roadmap: str) -> list[str]:
    """`roadmap-run.ps1` arguments that repeat the last run's launch options; [] when none are recorded. ValueError
    for a record that is not readable or holds an unsafe value."""
    path = options_file(last_stop_file(Path(repo), "roadmap", roadmap))
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        raise ValueError(f"launch options not readable: {type(exc).__name__}") from None
    if not isinstance(record, dict):
        raise ValueError("launch options are not an object")
    out: list[str] = []
    defaults = Caps()
    for key, flag in _RESTART_ARGS:
        value = record.get(key)
        if value is None:
            continue
        if hasattr(defaults, key):  # a cap: never above the built-in default (the options file is writable)
            cap = getattr(defaults, key)
            number = value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
            if number is None or not (0 < number <= cap):
                print(f"caddis_roadmap_run: launch option {key} {value!r} is not in (0, {cap:g}]; using {cap:g}",
                      file=sys.stderr)
                number = cap
            value = int(number) if key == "max_sessions" else float(number)
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError(f"launch option {key} is not a value")
        text = value if isinstance(value, str) else (f"{value:g}" if isinstance(value, float) else str(value))
        if key == "engine" and text not in ENGINES:
            raise ValueError(f"launch option engine {text!r} is unknown")
        if not _ARG_RE.match(text):
            raise ValueError(f"launch option {key} holds an unsafe value")
        out += [flag, text]
    return out


def accept_roadmap(repo: Path, roadmap: str, yes: bool = False, dry_run: bool = False,
                   confirm: Callable[[str], str] = input) -> int:
    """Owner only (refused headless): accept the origin roadmap as it is now as the baseline of the current merge
    wait (the roadmap hash and the saved text in waiting.json), after an owner edit during the wait. It takes the runner
    lock (refuses a live runner), prints the unified diff from the published baseline, and asks for `accept` at the
    console unless `yes`. `dry_run` prints the diff and writes nothing (no lock either)."""
    if not dry_run and caddis_roadmap.is_headless():  # the dry run only reads, so it may run anywhere
        print("caddis_roadmap_run: --accept-roadmap is owner-only and this session is headless "
              f"({', '.join(caddis_roadmap.HEADLESS_VARS)} in the environment, or stdin is not a console)",
              file=sys.stderr)
        return caddis_exit.ERROR
    repo = Path(repo)
    lock = None
    if not dry_run:  # the lock FIRST; everything below is read under it
        lock = _RunnerLock(runner_lock_file(repo, "roadmap", roadmap), Caps().max_hours,
                           claim_path=caddis_roadmap.claim_lock_path(repo))
        try:
            lock.acquire(lambda message: print(f"caddis_roadmap_run: {message}", file=sys.stderr))
        except _Stop as stop:
            print(f"caddis_roadmap_run: {stop.reason}", file=sys.stderr)
            return stop.code
    try:
        waiting_file = _state_file(repo, roadmap, "waiting")
        waiting = _read_record(waiting_file)
        if not waiting:
            print("nothing to accept: no merge wait recorded")
            return caddis_exit.CLEAN
        try:
            snap = caddis_roadmap.load(repo, roadmap)
        except caddis_roadmap.RoadmapError as exc:
            print(f"caddis_roadmap_run: {exc}", file=sys.stderr)
            return exc.code
        saved = _state_file(repo, roadmap, "published-roadmap").with_suffix(".md")
        before = _read_text(saved) or ""
        diff = "".join(difflib.unified_diff(before.splitlines(keepends=True), snap.text.splitlines(keepends=True),
                                            "published (baseline of the wait)", f"origin/{snap.branch} (now)"))
        print(diff or "no difference")
        if dry_run:
            print("dry run: nothing written")
            return caddis_exit.CLEAN
        if not yes and confirm("type accept to accept this roadmap as the baseline of the wait: ").strip() != "accept":
            print("not accepted; nothing written")
            return caddis_exit.BLOCKED
        saved.parent.mkdir(parents=True, exist_ok=True)
        tmp = saved.with_name(f"{saved.name}.{os.getpid()}.tmp")
        tmp.write_bytes(snap.text.encode("utf-8"))
        os.replace(tmp, saved)
        _write_record(waiting_file, {**waiting, "roadmap_sha": _roadmap_sha(snap.text),
                                     "accepted_by_owner_utc": _iso(datetime.now(timezone.utc))})
        print(f"roadmap {roadmap}: the origin roadmap is accepted as the baseline of the wait for {waiting.get('ref')}")
        return caddis_exit.CLEAN
    finally:
        if lock is not None:
            lock.release()


def lock_state(repo: Path, roadmap: str) -> str:
    """`absent`, `stale` or `live`: the roadmap runner lock, judged with the lock's own `max_hours`."""
    stale = caddis_roadmap.runner_lock_stale(runner_lock_file(Path(repo), "roadmap", roadmap))
    return "absent" if stale is None else ("stale" if stale else "live")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", help="run a plain plan: .caddis/plans/<slug>.md (plan mode)")
    mode.add_argument("--roadmap", help="run a roadmap: .caddis/roadmaps/<slug>/roadmap.md on origin (roadmap mode)")
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--max-hours", type=float, default=Caps.max_hours)
    parser.add_argument("--max-sessions", type=int, default=Caps.max_sessions)
    parser.add_argument("--session-timeout-min", type=float, default=Caps.session_timeout_min)
    parser.add_argument("--max-usd-per-session", type=float, default=Caps.max_usd_per_session)
    parser.add_argument("--max-usd-total", type=float, default=Caps.max_usd_total)
    parser.add_argument("--engine", choices=sorted(ENGINES), default="claude")
    parser.add_argument("--model", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--gh-account", default=None,
                        help="the gh account every gh call uses (GH_TOKEN from `gh auth token -u <account>`); give "
                             "the repo's account on a machine with several gh logins")
    parser.add_argument("--lock-state", action="store_true",
                        help="roadmap mode: print absent, stale or live for the runner lock; exit 0 unless live (3)")
    parser.add_argument("--restart-args", action="store_true",
                        help="roadmap mode: print the roadmap-run.ps1 arguments of the last launch options, one per "
                             "line (none when not recorded); exit 1 when they cannot be read")
    parser.add_argument("--accept-roadmap", action="store_true",
                        help="roadmap mode, owner only (refused headless): accept the origin roadmap as it is now as "
                             "the baseline of the current merge wait, after an owner edit during the wait")
    parser.add_argument("--yes", action="store_true", help="--accept-roadmap without the console confirmation")
    parser.add_argument("--last-stop", action="store_true",
                        help="roadmap mode: exit 0 when the recheck task may restart the runner: no recorded "
                             "stop, BLOCKED nothing ready, or BLOCKED waiting for merge once that PR merged (the "
                             "line then starts with merged:); else 1 (running, any FAILED stop, a cap); prints why")
    args = parser.parse_args(argv)
    for name in ("max_hours", "max_sessions", "session_timeout_min", "max_usd_per_session", "max_usd_total"):
        value = getattr(args, name)
        if not (value > 0) or value != value or value == float("inf"):
            parser.error(f"--{name.replace('_', '-')} must be a finite number above 0")
    if args.lock_state:
        if not args.roadmap or not caddis_roadmap.SLUG_RE.match(args.roadmap):
            parser.error("--lock-state needs --roadmap <slug>")
        state = lock_state(args.repo, args.roadmap)
        print(state)
        return caddis_exit.NOT_RUN if state == "live" else caddis_exit.CLEAN
    if args.accept_roadmap:
        if not args.roadmap or not caddis_roadmap.SLUG_RE.match(args.roadmap):
            parser.error("--accept-roadmap needs --roadmap <slug>")
        return accept_roadmap(args.repo, args.roadmap, yes=args.yes, dry_run=args.dry_run)
    if args.restart_args:
        if not args.roadmap or not caddis_roadmap.SLUG_RE.match(args.roadmap):
            parser.error("--restart-args needs --roadmap <slug>")
        try:
            print("\n".join(restart_args(args.repo, args.roadmap)))
        except ValueError as exc:
            print(f"caddis_roadmap_run: {exc}", file=sys.stderr)
            return caddis_exit.BLOCKED
        return caddis_exit.CLEAN
    account = args.gh_account
    if args.last_stop and not account and args.roadmap and caddis_roadmap.SLUG_RE.match(args.roadmap):
        account = _read_record(options_file(last_stop_file(Path(args.repo), "roadmap", args.roadmap))).get(
            "gh_account") or None  # the account the run recorded
    if account and args.last_stop:
        try:
            use_gh_account(account)
        except caddis_roadmap.RoadmapError as exc:
            print(f"gh error: {exc}")
            return caddis_exit.BLOCKED
    if args.last_stop:
        if not args.roadmap or not caddis_roadmap.SLUG_RE.match(args.roadmap):
            parser.error("--last-stop needs --roadmap <slug>")
        ok, why = last_stop_restartable(args.repo, args.roadmap)
        print(why)
        return caddis_exit.CLEAN if ok else caddis_exit.BLOCKED
    try:
        caddis_spend.bump_headless_depth(os.environ)  # a check only: the sessions get the bump in headless_env
    except caddis_spend.HeadlessDepthExceeded as exc:
        print(f"caddis_roadmap_run: {exc}", file=sys.stderr)
        return caddis_exit.BLOCKED
    caps = Caps(args.max_hours, args.max_sessions, args.session_timeout_min, args.max_usd_per_session,
                args.max_usd_total)
    return run(repo=args.repo, plan=args.plan, roadmap=args.roadmap, caps=caps, engine=args.engine, model=args.model,
               dry_run=args.dry_run, gh_account=args.gh_account)


if __name__ == "__main__":
    raise SystemExit(main())
