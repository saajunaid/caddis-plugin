"""Inject the session-resume doc into context at SessionStart / PreCompact.

The harness loop treats relay.md as the durable session-resume doc. Printing it to
stdout from a SessionStart/PreCompact hook surfaces it in the next context window, so a
fresh session resumes with zero re-discovery. No-ops silently when none is present.
Cross-platform (pure Python) — works the same on Windows, Linux, and macOS.

Team/parallel-branch mode: a per-branch file at `.claude/relay/<branch>.md` is preferred
when present, so two developers on two branches never collide on a single committed
relay.md. Solo/default stays exactly `relay.md` at the repo root — fully backward-compatible.

Artifact dir: every lookup here is a READ under `.caddis/` (falling back to the older `.claude/`
locations already handled).
"""
import json
import os
import subprocess
import sys

# relay.md may contain any Unicode; force UTF-8 so a narrow Windows console
# (cp1252/cp437) can't raise UnicodeEncodeError or mangle the output.
_reconfig = getattr(sys.stdout, "reconfigure", None)
if _reconfig:
    try:
        _reconfig(encoding="utf-8")
    except Exception:
        pass

# Read the event payload on stdin (also avoids a broken pipe on some platforms).
# We keep `cwd`: state anchors to the repo the SESSION is in, not the hook process's
# launch cwd — otherwise a session launched in one repo but operating in another
# resolves the wrong repo's relay/usage state.
try:
    _payload = json.load(sys.stdin)
except Exception:
    _payload = {}
_session_cwd = (_payload.get("cwd") if isinstance(_payload, dict) else None) or os.getcwd()

INJECT_MAX_LINES = 120

# The relay arrives BEFORE the user's prompt, and it used to arrive under the header
# "read before acting" followed verbatim by its own "## Next step (exact)" section. Claude
# treats that position as background; other models do not. Measured three times on a
# glm-headless docket (2026-08-03): GLM executed the relay's next step FIRST, committed it,
# and only then started the task it was given — and an explicit "ignore the relay" line in
# the prompt did not change the ordering. That is expensive twice over: an early status check
# sees only the relay's commit and reads the run as off-task, and relay.md is gitignored and
# machine-local, so the session's first act can be executing a STALE instruction against a
# current tree. So the injection now says what it is. Cheap, and it helps every lane.
RELAY_FRAME_HEADER = (
    "=== session-context: relay.md — BACKGROUND STATE, NOT A TASK ===\n"
    "Carried over from a previous session and injected before your prompt. This is state, not\n"
    "an instruction: the \"Next step\" and \"Resume prompt\" sections below describe what the\n"
    "PREVIOUS session intended to do next. Do not act on them unless the user's prompt asks\n"
    "you to. This file is machine-local and gitignored, so it may also be stale. Your task is\n"
    "whatever the user's prompt says.\n"
)
RELAY_FRAME_FOOTER = "=== end session-context ==="

_TRUTHY = {"1", "true", "yes", "on"}


def _is_headless() -> bool:
    """True when no human is watching this session.

    A headless run is handed its task explicitly on the command line; it has no use for a
    resume pointer, and injecting one only gives it a second, older task to confuse with the
    real one. Two signals, both set by the thing that spawned the session:
      - CADDIS_HEADLESS — set by the caddis OSS launchers when they see claude's -p/--print.
      - DOCKET_PLAN / DOCKET_BRANCH — set by the docket runner, which spawns implement lanes
        autonomously (implement.md's own contract is "no human is present").
    """
    if str(os.environ.get("CADDIS_HEADLESS", "")).strip().lower() in _TRUTHY:
        return True
    return bool(os.environ.get("DOCKET_PLAN") or os.environ.get("DOCKET_BRANCH"))


def _first_existing(paths: list[str], default: str) -> str:
    """Return the first path that exists on disk, else `default` (the new canonical path)."""
    for p in paths:
        if os.path.isfile(p):
            return p
    return default


def _repo_root(start: str) -> str:
    """Git repo root for `start`, or `start` itself when not a git repo (best-effort).

    Relay + usage state anchor to the repo root so a session launched from a
    subfolder resolves the same files the root session does, instead of looking
    for (or scattering) a `.caddis/` in every cwd.
    """
    try:
        out = subprocess.run(
            ["git", "-C", start, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=3,
        )
        root = out.stdout.strip()
        if out.returncode == 0 and root:
            return root
    except Exception as _exc:
        _hook_note("git repo-root resolution", _exc)
    return start


ROOT = _repo_root(_session_cwd)

# Artifact-dir resolution comes from the one shared helper (scripts/claudster_config.py) so the
# dir name lives in a single place. The inline fallback keeps a SessionStart hook from ever dying
# on an import problem — it re-states the same `.caddis` path.
try:
    _cfg_scripts = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
    if _cfg_scripts not in sys.path:
        sys.path.insert(0, _cfg_scripts)
    from claudster_config import ARTIFACT_DIRS, artifact_root  # noqa: E402
except Exception:  # pragma: no cover — defensive; a hook must never crash a session start
    ARTIFACT_DIRS = (".caddis",)

# ── hook error ledger ───────────────────────────────────────────────────────────────
# Every optional surface below is wrapped in `try/except`, because a broken surface must
# never break the session. Until 2026-08-22 the except body was a bare `pass`, so a
# surface that stopped working and a surface with nothing to say looked identical. These
# helpers keep the fail-open behaviour and add a throttled record. Both are themselves
# fail-open: a ledger that cannot load costs nothing.
def _hook_note(feature, exc, root=None):
    """Record that `feature` failed. Never raises."""
    try:
        _hl_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
        if _hl_dir not in sys.path:
            sys.path.insert(0, _hl_dir)
        import hook_log as _hl  # noqa: E402
        _hl.record("inject_relay", feature, exc, root)
    except Exception:
        pass


def _hook_summary(root=None):
    """One line about recent hook failures, or "" when clean. Never raises."""
    try:
        _hl_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
        if _hl_dir not in sys.path:
            sys.path.insert(0, _hl_dir)
        import hook_log as _hl  # noqa: E402
        return _hl.summarise(root)
    except Exception:
        return ""



    def artifact_root(root):
        return os.path.join(str(root), ARTIFACT_DIRS[0])


def _art(*parts: str) -> list[str]:
    """Candidate paths for `<artifact-dir>/<parts>`."""
    return [os.path.join(ROOT, name, *parts) for name in ARTIFACT_DIRS]


def _art_default(*parts: str) -> str:
    """The path to use when none exists — under the dir this repo actually lives in."""
    return os.path.join(str(artifact_root(ROOT)), *parts)


def _resolve_relay() -> str:
    """Prefer the current artifact dir; fall back to every legacy location.

    Preference order (first existing wins):
      1. .caddis/relay/<branch>.md          (per-branch team mode)
      2. .caddis/relay.md                   (solo/default)
      3. .claude/relay/<branch>.md          (legacy per-branch)
      4. relay.md                           (legacy repo root)
    When none exist yet, return the default under the dir this repo lives in; the isfile()
    guard at the call site then no-ops cleanly. Team mode keeps each branch's resume state in
    its own file so parallel developers never merge-conflict on relay.md.
    Branch lookup is best-effort; any failure → skip the per-branch candidates.
    """
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip()
    except Exception:
        branch = ""
    slug = ""
    if branch and branch != "HEAD":
        slug = "".join(c if (c.isalnum() or c in "-_.") else "-" for c in branch)
    candidates: list[str] = []
    if slug:
        candidates += _art("relay", f"{slug}.md")
    candidates += _art("relay.md")
    if slug:
        candidates.append(os.path.join(ROOT, ".claude", "relay", f"{slug}.md"))
    candidates.append(os.path.join(ROOT, "relay.md"))
    return _first_existing(candidates, _art_default("relay.md"))


RELAY = _resolve_relay()

def _truncate_relay(text: str) -> str:
    """Cap injected output at INJECT_MAX_LINES.

    Preserves the header, Current workstream, Done header (with count summary),
    Next step, and everything from Read first on resume to end.  The Done
    bullets are the unbounded part — they get replaced with a one-liner so the
    section that matters (Next step / Resume prompt) is never pushed off-screen.
    Graceful degradation: if section headers can't be found, returns text as-is.
    """
    lines = text.splitlines()
    if len(lines) <= INJECT_MAX_LINES:
        return text

    done_idx = next_step_idx = read_first_idx = None
    for i, line in enumerate(lines):
        s = line.strip()
        if done_idx is None and s.startswith("## Done"):
            done_idx = i
        elif next_step_idx is None and s.startswith("## Next step"):
            next_step_idx = i
        elif read_first_idx is None and s.startswith("## Read first on resume"):
            read_first_idx = i
            break

    if done_idx is None or next_step_idx is None or read_first_idx is None:
        return text  # can't parse — print full rather than lose data

    done_bullets = [l for l in lines[done_idx + 1:next_step_idx] if l.strip().startswith("-")]
    omitted = len(done_bullets)
    summary = f"- [Done section truncated — {omitted} bullets omitted to save context; see git log]"
    truncated = lines[:done_idx + 1] + [summary, ""] + lines[next_step_idx:]
    return "\n".join(truncated)


# Workstream stack (digression tracker): surface any PARKED workstreams BEFORE the relay, so a session
# that digressed from its original task never silently loses it. State lives at
# <artifact-dir>/workstreams.json (root-anchored, like relay). Fail-open & silent: a missing /
# unparseable / wrong-version / empty stack injects nothing and NEVER raises — a partially-written
# stack must not break session start.
try:
    _ws = _first_existing(_art("workstreams.json"), _art_default("workstreams.json"))
    if os.path.isfile(_ws):
        _data = json.load(open(_ws, encoding="utf-8"))
        _stack = _data.get("stack") if isinstance(_data, dict) and _data.get("version") == 1 else None
        if isinstance(_stack, list) and _stack:
            _wlines = []
            for _f in reversed(_stack):  # top-of-stack (most recently parked) first
                _plan = _f.get("plan", "?")
                _repo = _f.get("repo")
                _loc = f"{_repo} :: {_plan}" if _repo else _plan
                _phase = _f.get("phase", "?")
                _reason = _f.get("reason", "")
                _since = str(_f.get("pushedAt", ""))[:10]  # date part only
                _wlines.append(
                    f'⛏ Parked workstream: {_loc} @ {_phase} — "{_reason}" '
                    f"(since {_since}). Run /resume to pop."
                )
            if len(_stack) > 1:
                _wlines.append(f"({len(_stack)} parked total)")
            print("\n".join(_wlines))
except Exception as _exc:
    _hook_note("parked-stack surface", _exc)

if os.path.isfile(RELAY) and not _is_headless():
    try:
        text = open(RELAY, encoding="utf-8").read().strip()
    except Exception:
        sys.exit(0)
    if text:
        print("\n" + RELAY_FRAME_HEADER)
        print(_truncate_relay(text))
        print("\n" + RELAY_FRAME_FOOTER)

# ── session state, when it is fresher than the relay ─────────────────────────────────────
# relay.md only changes when someone runs /handoff. `.caddis/session-state.md` is rewritten by
# the Stop hook at the END OF EVERY TURN, so after a crash — or any session that did work and
# never handed off — the state file is current and the relay is not.
#
# Emitted ONLY when the state file is strictly newer. If a handoff just ran, the relay already
# says everything and repeating it would spend the context the relay needs. That comparison is
# the whole design: it is what lets this be automatic instead of another thing to remember.
_STATE = _first_existing(_art("session-state.md"), "")
if _STATE and not _is_headless():
    try:
        _state_newer = True
        if os.path.isfile(RELAY):
            # Strictly newer: equal mtimes mean the handoff wrote last, so the relay wins.
            _state_newer = os.path.getmtime(_STATE) > os.path.getmtime(RELAY)
        if _state_newer:
            _stext = open(_STATE, encoding="utf-8").read()
            # Drop the file's own preamble ("do not edit by hand", how to use claude --continue).
            # A human needs that when opening the file; an agent reading it as context does not.
            _marker = "**Updated:**"
            _cut = _stext.find(_marker)
            _body = _stext[_cut:] if _cut != -1 else _stext
            _slines = [l for l in _body.splitlines() if l.strip()]
            if _slines:
                _CAP = 30
                if len(_slines) > _CAP:
                    _slines = _slines[:_CAP] + [
                        "... (truncated — read %s for the rest)"
                        % os.path.relpath(_STATE, ROOT).replace(os.sep, "/")
                    ]
                print("\n=== session-state: WHERE THE LAST TURN LEFT OFF ===")
                print("Auto-captured by the Stop hook every turn, so this is NEWER than relay.md.")
                print("It is state, not instructions. `claude --continue` reopens that session in full.")
                print("\n".join(_slines))
                print("=== end session-state ===")
    except Exception as _exc:
        _hook_note("session-state surface", _exc)

# Reference-doc index pointer: when the repo keeps a DOC-MAP (the meta-KB), make "read the KB
# first" deterministic. One line only, so it never crowds the relay or the usage nudge. The path
# is printed as-written so the agent reads the dir this repo actually uses.
_DOC_MAP = _first_existing(_art("kb", "DOC-MAP.md"), "")
if _DOC_MAP:
    print(f"\n[DOC-MAP] reference index available — read {os.path.relpath(_DOC_MAP, ROOT).replace(os.sep, '/')} "
          "first to find the right doc, then read it on demand (dispatch a subagent for heavy reads).")

# Dream Memory surfacing was RETIRED 2026-08-26. It ranked facts by hit count, so the most-repeated
# shell typo always outranked a real insight: 128 of 131 records were `failure-mode`, the top six were
# a month stale with counts of 69-77, and the two genuinely useful records sat at hitCount 1 and never
# surfaced. A count of 77 means that command failed 77 times WHILE its own warning held the top slot —
# the mechanism did not change behaviour. Claude Code's own per-repo memory does the curated job.

# Maintenance nudge (Phase 9): ONE deterministic line when a signal fires — an oversize always-loaded
# AGENTS.md (curator), a dangling DOC-MAP link (/caddis:kb), or a stale doctor run. PURE FILE CHECKS
# via claudster_doctor.nudge_line (no subprocess, no LLM, no auto-fix). Fail-open & silent like every block.
try:
    _sc = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
    if _sc not in sys.path:
        sys.path.insert(0, _sc)
    import claudster_doctor as _cd  # noqa: E402

    _nudge = _cd.nudge_line(ROOT)
    if _nudge:
        print("\n" + _nudge)
except Exception as _exc:
    _hook_note("rules-budget nudge", _exc)

# Tidy nudge (artifact-lifecycle-tidy Phase 3): ONE line when a finished plan/prompt is sitting
# outside done/. Strictly read-only (dry-run scan only, no move) - the actual move happens at
# /caddis:handoff or /caddis:implement close, never from a SessionStart hook. Fail-open & silent
# like every other block here; an older install without the script just sees nothing.
try:
    from pathlib import Path as _Path

    _sc2 = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
    if _sc2 not in sys.path:
        sys.path.insert(0, _sc2)
    import caddis_tidy as _ct  # noqa: E402

    _tidy_nudge = _ct.nudge_line(_Path(ROOT))
    if _tidy_nudge:
        print("\n" + _tidy_nudge)
except Exception as _exc:
    _hook_note("tidy nudge", _exc)

# Output style provisioning: put `Plain.md` where the /config picker looks, once.
#
# This is the ONLY thing that runs "when someone installs caddis" — a Claude Code plugin has no
# install script, so a first session is the first moment any caddis code executes on a new machine.
# It writes a file and NEVER selects it: choosing an output style stays the human's call.
# Prints only when it actually wrote something, because a SessionStart line that fires every
# session is noise, and noise is why the AGENTS.md budget nudge went unread for 1,085 lines.
# Fail-open & silent like every block here.
try:
    _sc3 = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
    if _sc3 not in sys.path:
        sys.path.insert(0, _sc3)
    import setup_project_ai as _spa  # noqa: E402

    for _note in _spa.provision_output_style(dry=False):
        if _note.startswith("output style: wrote") or _note.startswith("output style: updated"):
            print("\n[caddis] output style `Plain` is available — pick it in /config > Output style.")
            break

    # Same one-time additive treatment for the todo-tools env key — and, more importantly, a LOUD
    # report when settings.json does not parse. An invalid settings.json makes Claude Code ignore
    # EVERY setting in it, silently: guard mode, permissions, hooks, statusline, plugins. Found
    # live on 2026-08-16, caused by one missing comma in a hand-added line. This is the only place
    # that would ever tell you.
    for _note in _spa.ensure_user_env(dry=False):
        if "NOT VALID JSON" in _note:
            print("\n[caddis] " + _note)
        elif _note.startswith("user env: added"):
            print("\n[caddis] enabled CLAUDE_CODE_ENABLE_TODO_TOOLS in your global settings — "
                  "restart Claude Code to pick it up.")
except Exception as _exc:
    _hook_note("todo-tools env enable", _exc)

# Mid-week cadence nudge: suggest /usage-review when overdue (>7 days) or never run (enough data exists).
# Prefer the current artifact dir, then the older .claude path.
_STAMP = _first_existing(
    _art(".last-usage-review") + [os.path.join(ROOT, ".claude", ".last-usage-review")],
    _art_default(".last-usage-review"),
)
_LOG = _first_existing(
    _art("usage-log.jsonl") + [os.path.join(ROOT, ".claude", "usage-log.jsonl")],
    _art_default("usage-log.jsonl"),
)

try:
    from datetime import datetime as _dt, timezone as _tz

    if os.path.isfile(_STAMP):
        _last_str = open(_STAMP, encoding="utf-8").read().strip()
        _last = _dt.fromisoformat(_last_str)
        if not _last.tzinfo:
            _last = _last.replace(tzinfo=_tz.utc)
        _days_ago = (_dt.now(_tz.utc) - _last).days
        if _days_ago >= 7:
            print(f"\n[USAGE-REVIEW] {_days_ago} days since last usage review — run `/usage-review` to optimise your harness.\n")
    elif os.path.isfile(_LOG):
        # Never reviewed yet; nudge once enough data has accumulated (3+ sessions)
        with open(_LOG, encoding="utf-8") as _fh:
            _lines = [l for l in _fh if l.strip()]
        if len(_lines) >= 3:
            print("\n[USAGE-REVIEW] You have usage data — run `/usage-review` to review patterns and right-size your harness.\n")
except Exception as _exc:
    _hook_note("usage-review nudge", _exc)

# Hook health: one line when something has been failing quietly. Throttled to one record
# per hook/feature/error per day, so a hook broken on every call reports once, not always.
# This is the ONLY place the user is told — a second channel is a channel to ignore.
try:
    _health = _hook_summary(ROOT)
    if _health:
        print("")
        print(_health)
except Exception:
    pass  # the health check must never be the thing that breaks the session

sys.exit(0)
