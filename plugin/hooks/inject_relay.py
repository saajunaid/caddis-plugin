"""Inject the session-resume doc into context at SessionStart / PreCompact.

The harness loop treats relay.md as the durable session-resume doc. Printing it to
stdout from a SessionStart/PreCompact hook surfaces it in the next context window, so a
fresh session resumes with zero re-discovery. No-ops silently when none is present.
Cross-platform (pure Python) — works the same on Windows, Linux, and macOS.

Team/parallel-branch mode: a per-branch file at `.claude/relay/<branch>.md` is preferred
when present, so two developers on two branches never collide on a single committed
relay.md. Solo/default stays exactly `relay.md` at the repo root — fully backward-compatible.

Artifact dir: every lookup here is a READ, so it tries `.caddis/` first and falls back to the
legacy `.claudster/` (and then to the older `.claude/` locations already handled). A repo that
still has only `.claudster/` gets a one-line nudge to run `/caddis:migrate-dir` — never a
silent rename (that would move files under a concurrent session's feet).
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
    for (or scattering) a `.claudster/` in every cwd.
    """
    try:
        out = subprocess.run(
            ["git", "-C", start, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=3,
        )
        root = out.stdout.strip()
        if out.returncode == 0 and root:
            return root
    except Exception:
        pass
    return start


ROOT = _repo_root(_session_cwd)

# Artifact-dir resolution comes from the one shared helper (scripts/claudster_config.py) so the
# dir name lives in a single place. The inline fallback keeps a SessionStart hook from ever dying
# on an import problem — it re-states the same read order (`.caddis`, then legacy `.claudster`).
try:
    _cfg_scripts = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
    if _cfg_scripts not in sys.path:
        sys.path.insert(0, _cfg_scripts)
    from claudster_config import ARTIFACT_DIRS, artifact_root  # noqa: E402
except Exception:  # pragma: no cover — defensive; a hook must never crash a session start
    ARTIFACT_DIRS = (".caddis", ".claudster")

    def artifact_root(root):
        for _n in ARTIFACT_DIRS:
            if os.path.isdir(os.path.join(str(root), _n)):
                return os.path.join(str(root), _n)
        return os.path.join(str(root), ARTIFACT_DIRS[0])


def _art(*parts: str) -> list[str]:
    """Candidate paths for `<artifact-dir>/<parts>` across both dir names, preferred first."""
    return [os.path.join(ROOT, name, *parts) for name in ARTIFACT_DIRS]


def _art_default(*parts: str) -> str:
    """The path to use when none exists — under the dir this repo actually lives in."""
    return os.path.join(str(artifact_root(ROOT)), *parts)


def _resolve_relay() -> str:
    """Prefer the current artifact dir; fall back to the legacy dir, then every legacy location.

    Preference order (first existing wins):
      1. <artifact-dir>/relay/<branch>.md   (per-branch team mode — `.caddis`, then `.claudster`)
      2. <artifact-dir>/relay.md            (solo/default — `.caddis`, then `.claudster`)
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
except Exception:
    pass

if os.path.isfile(RELAY):
    try:
        text = open(RELAY, encoding="utf-8").read().strip()
    except Exception:
        sys.exit(0)
    if text:
        print("\n=== relay.md (session resume — read before acting) ===\n")
        print(_truncate_relay(text))

# Reference-doc index pointer: when the repo keeps a DOC-MAP (the meta-KB), make "read the KB
# first" deterministic. One line only, so it never crowds the relay or the usage nudge. The path
# is printed as-written so the agent reads the dir this repo actually uses.
_DOC_MAP = _first_existing(_art("kb", "DOC-MAP.md"), "")
if _DOC_MAP:
    print(f"\n[DOC-MAP] reference index available — read {os.path.relpath(_DOC_MAP, ROOT).replace(os.sep, '/')} "
          "first to find the right doc, then read it on demand (dispatch a subagent for heavy reads).")

# Dream Memory (fann Phase 5): surface the top reinforced facts for this repo — the
# "don't step on the same rake twice" nudge. ≤5 lines, weighted/capped by the engine.
# Fail-open & silent: a missing store, an unparseable file, or an import error must never
# disrupt a session start (same bar as every other block here).
try:
    _scripts = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
    if _scripts not in sys.path:
        sys.path.insert(0, _scripts)
    import dream_memory as _dm  # noqa: E402

    _store = _dm.store_path(ROOT)
    _facts = _dm.load_facts(_store)
    if _facts:
        from datetime import datetime as _dtm, timezone as _tzm
        _limit = _dm.load_tunables(ROOT)["surface_limit"]
        _top = _dm.rank_for_surfacing(_facts, _limit, now=_dtm.now(_tzm.utc).isoformat())
        if _top:
            print("\n[memory] reinforced facts for this repo (auto; fades if not seen):")
            for _line in _dm._format_surface(_top):
                print(_line)
except Exception:
    pass

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
except Exception:
    pass

# Artifact-dir migration nudge: ONE line when the repo still carries the pre-rename `.claudster/`.
# Everything keeps working (all reads dual-path), so this is an invitation, not a warning — and the
# rename is never automatic: `git mv`-ing a dir under a concurrent session would clobber its
# in-flight writes. Suppressed once `.caddis/` exists (a half-migrated repo is the command's job).
try:
    if os.path.isdir(os.path.join(ROOT, ".claudster")) and not os.path.isdir(os.path.join(ROOT, ".caddis")):
        print("\n[caddis] legacy `.claudster/` detected — everything still works (dual-path reads); "
              "run `/caddis:migrate-dir` when convenient to rename it to `.caddis/`.")
except Exception:
    pass

# Mid-week cadence nudge: suggest /usage-review when overdue (>7 days) or never run (enough data exists).
# Prefer the current artifact dir, then the legacy one, then the older .claude path.
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
except Exception:
    pass

sys.exit(0)
