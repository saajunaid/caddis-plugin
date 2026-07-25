#!/usr/bin/env python3
"""caddis /usage-review: local usage analysis + harness self-tuning recommendations.

Reads:
  .claudster/usage-log.jsonl      per-session digest (Stop hook); legacy .claude/usage-log.jsonl fallback
  ~/.claude/projects/<slug>/      session transcripts (agent dispatches, context size)
  claude-harness/agents/*.md      agent model tiers (frontmatter)

Writes:
  <output-dir>/usage-review.html  graph-first HTML dashboard (default: .claudster/reviews)
  .claudster/.last-usage-review   timestamp for cadence nudge (updated on each run)

Prints: markdown report to stdout.

CLI: usage_review.py [--days N] [--cwd PATH] [--no-html] [--output-dir DIR]
"""
import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

_reconfig = getattr(sys.stdout, "reconfigure", None)
if _reconfig:
    try:
        _reconfig(encoding="utf-8")
    except Exception:
        pass

# ── repo root ────────────────────────────────────────────────────────────────

def _repo_root(start: str) -> str:
    """Git repo root for `start`, or `start` when not a git repo (best-effort).

    The Stop hook writes the usage log to the repo root's `.claudster/`, so the
    review anchors there too — otherwise running it from a subfolder reads an
    empty/partial log. Non-git projects fall back to `start` unchanged.
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


# ── model helpers ──────────────────────────────────────────────────────────────

def _tier(model: str) -> str:
    m = (model or "").lower()
    if "fable" in m:
        return "fable"
    if "opus" in m:
        return "opus"
    if "sonnet" in m:
        return "sonnet"
    if "haiku" in m:
        return "haiku"
    return "sonnet"

TIER_COLORS = {
    "fable": "#B06BC9",
    "opus": "#C9736B",
    "sonnet": "#E8A04C",
    "haiku": "#8FA66B",
}

# ── project slug → transcript dir ─────────────────────────────────────────────

def _transcript_dir(cwd: str) -> Path | None:
    """Locate ~/.claude/projects/<slug>/ for a project path."""
    p = cwd.replace("\\", "/").rstrip("/")
    p = re.sub(r"^([a-zA-Z]):/", lambda m: m.group(1) + "--", p)
    slug = p.replace("/", "-")
    base = Path.home() / ".claude" / "projects"
    for candidate in [slug, slug.lower()]:
        d = base / candidate
        if d.is_dir():
            return d
    return None

# ── data loading ───────────────────────────────────────────────────────────────

def _load_log_window(cwd: str, start: datetime, end: datetime) -> list[dict]:
    """Return one record per session with ts = first entry, metrics = last entry."""
    path = os.path.join(cwd, ".claudster", "usage-log.jsonl")
    if not os.path.isfile(path):
        legacy = os.path.join(cwd, ".claude", "usage-log.jsonl")
        if os.path.isfile(legacy):
            path = legacy
    if not os.path.isfile(path):
        return []
    first_ts: dict[str, datetime] = {}
    last_rec: dict[str, dict] = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                raw_ts = rec.get("ts", "")
                ts = datetime.fromisoformat(raw_ts)
                if not ts.tzinfo:
                    ts = ts.replace(tzinfo=timezone.utc)
                sid = rec.get("session") or f"_unknown_{line[:12]}"
                if sid not in first_ts:
                    first_ts[sid] = ts
                last_rec[sid] = rec
            except Exception:
                continue
    result = []
    for sid, rec in last_rec.items():
        ts = first_ts[sid]
        if start <= ts < end:
            r = dict(rec)
            r["ts"] = ts.isoformat()
            r["_session_id"] = sid
            result.append(r)
    return sorted(result, key=lambda r: r["ts"])


def load_usage_log(cwd: str, days: int) -> tuple[list[dict], list[dict]]:
    """Return (current_window, prev_window) session lists."""
    now = datetime.now(timezone.utc)
    curr_start = now - timedelta(days=days)
    prev_start = now - timedelta(days=2 * days)
    current = _load_log_window(cwd, curr_start, now)
    previous = _load_log_window(cwd, prev_start, curr_start)
    return current, previous


def _parse_transcript(path: str) -> dict:
    """Extract per-session metrics from a transcript JSONL file."""
    peak_context = 0
    agent_dispatches: dict[str, int] = defaultdict(int)
    agent_models: dict[str, list[str]] = defaultdict(list)
    skill_dispatches: dict[str, int] = defaultdict(int)

    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    ev = json.loads(raw)
                except Exception:
                    continue
                msg = ev.get("message") if isinstance(ev.get("message"), dict) else None
                if not msg or msg.get("role") != "assistant":
                    continue
                usage = msg.get("usage") or {}
                if isinstance(usage, dict):
                    ctx = (int(usage.get("input_tokens") or 0)
                           + int(usage.get("cache_read_input_tokens") or 0))
                    peak_context = max(peak_context, ctx)
                content = msg.get("content") or []
                if not isinstance(content, list):
                    continue
                for item in content:
                    if not isinstance(item, dict) or item.get("type") != "tool_use":
                        continue
                    name = item.get("name", "")
                    inp = item.get("input") or {}
                    if name == "Agent":
                        atype = inp.get("subagent_type") or "unknown"
                        model = inp.get("model") or ""
                        agent_dispatches[atype] += 1
                        if model:
                            agent_models[atype].append(model)
                    elif name == "Skill":
                        skill = inp.get("skill") or "unknown"
                        skill_dispatches[skill] += 1
    except Exception:
        pass

    return {
        "peak_context": peak_context,
        "agent_dispatches": dict(agent_dispatches),
        "agent_models": {k: list(v) for k, v in agent_models.items()},
        "skill_dispatches": dict(skill_dispatches),
    }


def load_transcripts(cwd: str, session_ids: list[str]) -> dict[str, dict]:
    tdir = _transcript_dir(cwd)
    if not tdir:
        return {}
    result = {}
    for sid in session_ids:
        p = tdir / f"{sid}.jsonl"
        if p.is_file():
            result[sid] = _parse_transcript(str(p))
    return result


def load_agent_config(cwd: str) -> list[dict]:
    """Parse frontmatter from agent definition files.

    Checks paths in priority order:
      1. $CLAUDE_PLUGIN_ROOT/agents/   — plugin install
      2. <cwd>/.claude/agents/         — user's project agents
      3. <cwd>/claude-harness/agents/  — caddis dev checkout
    """
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    candidates = []
    if plugin_root:
        candidates.append(os.path.join(plugin_root, "agents"))
    candidates.append(os.path.join(cwd, ".claude", "agents"))
    candidates.append(os.path.join(cwd, "claude-harness", "agents"))

    agents_dir = next((c for c in candidates if os.path.isdir(c)), None)
    if not agents_dir:
        return []
    agents = []
    for fname in sorted(os.listdir(agents_dir)):
        if not fname.endswith(".md"):
            continue
        path = os.path.join(agents_dir, fname)
        try:
            text = open(path, encoding="utf-8").read()
            fm = re.search(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
            if not fm:
                continue
            rec: dict[str, str] = {"_file": path}
            for line in fm.group(1).splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    rec[k.strip()] = v.strip()
            if rec.get("name"):
                agents.append(rec)
        except Exception:
            continue
    return agents

# ── metrics aggregation ────────────────────────────────────────────────────────

def compute_metrics(sessions: list[dict], transcripts: dict[str, dict]) -> dict:
    if not sessions:
        return {
            "sessions": 0, "input": 0, "output": 0,
            "cache_write": 0, "cache_read": 0, "est_cost_usd": 0.0,
            "model_mix": {}, "per_day": {}, "agent_dispatches": {},
            "agent_models": {}, "skill_dispatches": {}, "peak_contexts": [],
        }
    model_mix: dict[str, int] = defaultdict(int)
    per_day: dict[str, dict] = {}
    tot_input = tot_output = tot_cw = tot_cr = 0
    tot_cost = 0.0
    agent_dispatches: dict[str, int] = defaultdict(int)
    agent_models: dict[str, list[str]] = defaultdict(list)
    skill_dispatches: dict[str, int] = defaultdict(int)
    peak_contexts: list[int] = []

    for s in sessions:
        day = s["ts"][:10]
        if day not in per_day:
            per_day[day] = {"sessions": 0, "input": 0, "output": 0,
                            "cache_write": 0, "cache_read": 0, "cost": 0.0}
        inp = int(s.get("input") or 0)
        out = int(s.get("output") or 0)
        cw  = int(s.get("cache_write") or 0)
        cr  = int(s.get("cache_read") or 0)
        cost = float(s.get("est_cost_usd") or 0.0)

        tot_input += inp; tot_output += out; tot_cw += cw; tot_cr += cr; tot_cost += cost
        pd = per_day[day]
        pd["sessions"] += 1; pd["input"] += inp; pd["output"] += out
        pd["cache_write"] += cw; pd["cache_read"] += cr; pd["cost"] += cost

        for model in (s.get("models") or []):
            if model == "<synthetic>":
                continue
            model_mix[_tier(model)] += out

        sid = s.get("_session_id", "")
        if sid in transcripts:
            td = transcripts[sid]
            ctx = td.get("peak_context", 0)
            if ctx:
                peak_contexts.append(ctx)
            for atype, cnt in td.get("agent_dispatches", {}).items():
                agent_dispatches[atype] += cnt
            for skill, cnt in td.get("skill_dispatches", {}).items():
                skill_dispatches[skill] += cnt
            for atype, models in td.get("agent_models", {}).items():
                agent_models[atype].extend(models)

    return {
        "sessions": len(sessions),
        "input": tot_input, "output": tot_output,
        "cache_write": tot_cw, "cache_read": tot_cr,
        "est_cost_usd": round(tot_cost, 2),
        "model_mix": dict(model_mix),
        "per_day": per_day,
        "agent_dispatches": dict(agent_dispatches),
        "agent_models": {k: list(v) for k, v in agent_models.items()},
        "skill_dispatches": dict(skill_dispatches),
        "peak_contexts": peak_contexts,
    }

# ── rule engine ────────────────────────────────────────────────────────────────

_CHEAP_AGENTS = {"preflight", "tester", "codebase-audit", "ui-design-reviewer", "data-engineer",
                 "sql-expert", "claude-md-curator", "debug"}
_HEAVY_AGENTS = {"anchor", "security-analyst"}
# Core skill identity is the caddis plugin's; the pre-rename "caddis:" prefix is also listed so
# legacy usage-log entries (recorded before the caddis rename) still categorize correctly.
_CORE_SKILL_NAMES = ("feature-plan", "handoff", "prd", "ship", "tdd", "ui-brief")
_CORE_SKILLS  = {f"{p}:{n}" for p in ("caddis", "claudster") for n in _CORE_SKILL_NAMES}


def run_rules(metrics: dict, prev: dict, agents: list[dict]) -> list[dict]:
    findings: list[dict] = []
    mm         = metrics.get("model_mix", {})
    tot_out    = metrics.get("output") or 1
    sessions   = metrics.get("sessions", 0)
    prev_sess  = prev.get("sessions", 0)
    ctxs       = metrics.get("peak_contexts", [])
    a_disp     = metrics.get("agent_dispatches", {})
    s_disp     = metrics.get("skill_dispatches", {})

    # R0 — Rate-limit proxy ────────────────────────────────────────────────────
    heavy_out  = mm.get("opus", 0) + mm.get("fable", 0)
    heavy_pct  = heavy_out / tot_out * 100 if tot_out else 0
    trend_note = ""
    if prev_sess > 0:
        delta = sessions - prev_sess
        arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
        trend_note = f" ({arrow} from {prev_sess} last window)"
    findings.append({
        "id": "R0", "severity": "info",
        "title": "Your usage this window",
        "finding": (
            f"{sessions} session{'s' if sessions != 1 else ''}{trend_note}. "
            f"{'All on' if heavy_pct >= 99 else f'{heavy_pct:.0f}% used'} Opus or Fable — "
            "the models most likely to hit rate limits. "
            "Actual rate-limit % (5h / weekly cap) is not stored locally."
        ),
        "action": "Run `/usage` in Claude Code to see your real-time rate-limit status.",
        "apply_target": None,
    })

    # R1 — Agent model tier mismatches ────────────────────────────────────────
    issues: list[str] = []
    apply_agents: list[dict] = []
    for ag in agents:
        name  = ag.get("name", "")
        model = ag.get("model", "inherit")
        if model == "inherit" and name in _CHEAP_AGENTS:
            issues.append(f"`{name}` (set to `inherit` — picks up whatever model the session is on)")
            apply_agents.append({"file": ag["_file"], "name": name, "current": model, "suggested": "sonnet"})
        elif model in ("sonnet", "haiku") and name in _HEAVY_AGENTS:
            issues.append(f"`{name}` (set to `{model}` — too light for safety/security verification)")
            apply_agents.append({"file": ag["_file"], "name": name, "current": model, "suggested": "opus"})
    if issues:
        n = len(issues)
        findings.append({
            "id": "R1", "severity": "medium",
            "title": f"{n} agent{'s have' if n > 1 else ' has'} the wrong model set",
            "finding": (
                "These agents are not pinned to the right model tier, meaning they inherit "
                "whatever model you happen to be on — usually Opus: "
                + "; ".join(issues) + "."
            ),
            "action": "Pin each agent to the right tier. Quick agents (preflight, tester) → `sonnet`. "
                      "Safety-critical agents (anchor, security-analyst) → `opus`.",
            "apply_target": {"type": "agent_frontmatter", "agents": apply_agents},
        })

    # R2 — Model mix ──────────────────────────────────────────────────────────
    if heavy_pct > 70 and sessions >= 2:
        findings.append({
            "id": "R2", "severity": "medium",
            "title": f"You're using the heaviest model for {heavy_pct:.0f}% of your work",
            "finding": (
                f"{'All of' if heavy_pct >= 99 else f'{heavy_pct:.0f}% of'} your output this window "
                f"ran on Opus{'or Fable ' if mm.get('fable', 0) > 0 else ''}— the models most likely "
                "to hit rate limits. For everyday tasks like coding, searching, and editing, Sonnet "
                "delivers the same results and uses less of your rate-limit quota."
            ),
            "action": "Switch to Sonnet for day-to-day work: type `/model` and pick Sonnet. "
                      "Keep Opus for planning, architecture decisions, and final reviews.",
            "apply_target": None,
        })

    # R3 — Effort right-sizing (advisory) ─────────────────────────────────────
    findings.append({
        "id": "R3", "severity": "info",
        "title": "Tip: save `max` effort for when it really matters",
        "finding": (
            "Effort level is not recorded in transcripts, so this is a general tip rather than a measured finding. "
            "`max` effort burns rate-limit quota significantly faster than `high` — "
            "reserve it for complex planning and architecture decisions. "
            "For regular coding, `high` is sufficient; for searches and quick edits, `medium` is fine."
        ),
        "action": "Before each task, ask: does this actually need `max`? For most coding tasks, `high` is the right call.",
        "apply_target": None,
    })

    # R4 — Long context ───────────────────────────────────────────────────────
    if ctxs:
        high_ctxs = [c for c in ctxs if c > 150_000]
        if high_ctxs:
            pct = len(high_ctxs) / len(ctxs) * 100
            sev = "medium" if pct > 50 else "low"
            findings.append({
                "id": "R4", "severity": sev,
                "title": f"{'Most' if pct > 50 else 'Some'} of your sessions are running very long",
                "finding": (
                    f"{len(high_ctxs)} of {len(ctxs)} session{'s' if len(ctxs) > 1 else ''} "
                    "peaked above 150k tokens of context. Long contexts make Claude slower, "
                    "consume more of your rate-limit, and can get truncated above 200k. "
                    "This usually means work is piling up without clearing out old context."
                ),
                "action": "Use `/compact` mid-task to summarise context without losing the thread. "
                          "Use `/clear` when switching to a completely different task.",
                "apply_target": None,
            })

    # R5 — Extras footprint ───────────────────────────────────────────────────
    extras_fired = {s for s in s_disp if s.startswith(("caddis:", "claudster:")) and s not in _CORE_SKILLS}
    total_skill_fires = sum(s_disp.values())
    if total_skill_fires > 0 and not extras_fired and sessions >= 3:
        findings.append({
            "id": "R5", "severity": "low",
            "title": "Extras plugin doesn't seem to be getting used",
            "finding": (
                f"You had {total_skill_fires} skill call{'s' if total_skill_fires > 1 else ''} "
                "this window but none from the extras tier. "
                "If caddis-extras is enabled, it adds context to every session even when unused."
            ),
            "action": "Disable caddis-extras if you don't use those skills: remove it from the plugins list in `.claude/settings.json`.",
            "apply_target": None,
        })

    # R6 — Per-agent heavy dispatch ───────────────────────────────────────────
    if a_disp:
        heavy: list[tuple[str, int, str]] = []
        for atype, cnt in sorted(a_disp.items(), key=lambda x: -x[1]):
            models = metrics.get("agent_models", {}).get(atype, [])
            if models:
                from collections import Counter
                dominant = Counter(_tier(m) for m in models).most_common(1)[0][0]
                if dominant in ("opus", "fable"):
                    heavy.append((atype, cnt, dominant))
        if heavy:
            names = ", ".join(f"`{t}`" for t, _, _ in heavy[:4])
            n = len(heavy)
            findings.append({
                "id": "R6", "severity": "medium",
                "title": f"{n} subagent{'s are' if n > 1 else ' is'} running on Opus unnecessarily",
                "finding": (
                    f"These subagents dispatched on Opus this window: {names}. "
                    "Most subagents don't need Opus-level reasoning — Sonnet handles code review, "
                    "preflight checks, and testing just as well at a lower rate-limit cost."
                ),
                "action": "Pin these agents to `model: sonnet` in their frontmatter files.",
                "apply_target": {
                    "type": "agent_frontmatter",
                    "agents": [{"name": t, "suggested": "sonnet"} for t, _, _ in heavy],
                },
            })

    # R7 — Dead weight ────────────────────────────────────────────────────────
    if sessions >= 5 and a_disp:
        all_names = {ag.get("name", "") for ag in agents} - {""}
        fired = set(a_disp.keys())
        never = all_names - fired
        if len(never) >= 4 and len(never) / max(len(all_names), 1) > 0.5:
            sample = ", ".join(f"`{n}`" for n in sorted(never)[:5])
            n_never = len(never)
            findings.append({
                "id": "R7", "severity": "low",
                "title": f"{n_never} agents were never dispatched this window",
                "finding": (
                    f"These agents haven't been used at all: {sample}"
                    f"{'…' if n_never > 5 else ''}. "
                    "Unused agents don't cost much, but if they're consistently idle across "
                    "multiple weeks it may be worth moving them to extras."
                ),
                "action": "If these agents aren't part of your workflow, consider moving them to the extras tier.",
                "apply_target": None,
            })

    # R8 — Trend ──────────────────────────────────────────────────────────────
    prev_out = prev.get("output", 0)
    if prev_out > 0 and metrics.get("output", 0) > 0:
        delta_pct = (metrics["output"] - prev_out) / prev_out * 100
        if abs(delta_pct) >= 40:
            direction = "up" if delta_pct > 0 else "down"
            findings.append({
                "id": "R8", "severity": "info",
                "title": f"Your usage is {direction} {abs(delta_pct):.0f}% vs last window",
                "finding": (
                    f"Output token volume went {direction} {abs(delta_pct):.0f}% "
                    f"({_fmt(prev_out)} → {_fmt(metrics['output'])}) compared to the previous window."
                    + (" If it's trending up, check whether a new workflow or heavy agent is the cause."
                       if delta_pct > 0 else "")
                ),
                "action": "Check which sessions or agents are driving the change." if delta_pct > 0 else "",
                "apply_target": None,
            })

    return findings

# ── format helpers ─────────────────────────────────────────────────────────────

def _fmt(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _pct(a: int, b: int) -> str:
    return f"{a / b * 100:.0f}%" if b else "—"

# ── markdown renderer ──────────────────────────────────────────────────────────

def render_markdown(metrics: dict, findings: list[dict], days: int,
                    ws: str, we: str) -> str:
    mm     = metrics.get("model_mix", {})
    tot_out = metrics.get("output") or 1
    mix    = " · ".join(
        f"{t}: {_pct(v, tot_out)}"
        for t, v in sorted(mm.items(), key=lambda x: -x[1])
    ) or "no model data"

    lines = [
        "# /usage-review",
        f"**Window:** {days}d ({ws} – {we})  ·  **Sessions:** {metrics['sessions']}  ·  {mix}",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Output tokens | {_fmt(metrics['output'])} |",
        f"| Input + cache read | {_fmt(metrics['input'] + metrics['cache_read'])} |",
        f"| Cache efficiency | {_pct(metrics['cache_read'], metrics['input'] + metrics['cache_read'])} read from cache |",
        f"| Est. cost equiv. | ${metrics['est_cost_usd']:.2f} (estimate; edit rates in session_end.py) |",
        "",
        "## Findings",
        "",
    ]

    sev_order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    icon      = {"high": "🔴", "medium": "🟡", "low": "🔵", "info": "ℹ️"}
    for f in sorted(findings, key=lambda x: sev_order.get(x["severity"], 4)):
        lines.append(f"### {icon.get(f['severity'], '•')} [{f['id']}] {f['title']}")
        lines.append("")
        lines.append(f"  {f['finding']}")
        lines.append("")
        if f.get("action"):
            lines.append(f"  **Action:** {f['action']}")
        if f.get("apply_target"):
            lines.append(f"  **[apply]** — tell Claude: _apply finding {f['id']}_")
        lines.append("")

    if metrics.get("agent_dispatches"):
        lines += ["## Agent dispatches this window", ""]
        am = metrics.get("agent_models", {})
        for atype, cnt in sorted(metrics["agent_dispatches"].items(), key=lambda x: -x[1]):
            models = am.get(atype, [])
            note = f" (on {', '.join(sorted(set(models)))})" if models else ""
            lines.append(f"- `{atype}` × {cnt}{note}")
        lines.append("")

    if metrics.get("skill_dispatches"):
        lines += ["## Skills fired this window", ""]
        for skill, cnt in sorted(metrics["skill_dispatches"].items(), key=lambda x: -x[1]):
            lines.append(f"- `{skill}` × {cnt}")
        lines.append("")

    lines += [
        "---",
        "HTML dashboard written alongside this report — see path printed by the script.",
    ]
    return "\n".join(lines)

# ── SVG chart helpers ──────────────────────────────────────────────────────────

def _svg_empty(w: int, h: int, msg: str = "No data") -> str:
    return (
        f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg">'
        f'<text x="{w//2}" y="{h//2}" text-anchor="middle" dominant-baseline="middle" '
        f'fill="#6f6857" font-size="12" font-family="system-ui,sans-serif">{msg}</text>'
        f'</svg>'
    )


def _svg_timeline(data: dict[str, float], color: str = "#E8A04C",
                  w: int = 380, h: int = 120) -> str:
    """Single-series line + area chart keyed by YYYY-MM-DD."""
    if not data or max(data.values(), default=0) == 0:
        return _svg_empty(w, h)
    days = sorted(data)
    vals = [data[d] for d in days]
    max_v = max(vals) or 1
    pad_l, pad_r, pad_t, pad_b = 4, 4, 8, 20
    aw = w - pad_l - pad_r
    ah = h - pad_t - pad_b
    n  = max(len(vals) - 1, 1)

    pts = []
    for i, v in enumerate(vals):
        x = pad_l + i / n * aw
        y = pad_t + ah - v / max_v * ah
        pts.append((x, y))

    line_pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area_pts  = (
        f"{pts[0][0]:.1f},{pad_t + ah:.1f} "
        + line_pts
        + f" {pts[-1][0]:.1f},{pad_t + ah:.1f}"
    )

    # x-axis labels (first + last date)
    label_y = h - 4
    labels = (
        f'<text x="{pad_l}" y="{label_y}" font-size="9" fill="#6f6857">{days[0][5:]}</text>'
        f'<text x="{w - pad_r}" y="{label_y}" font-size="9" fill="#6f6857" text-anchor="end">{days[-1][5:]}</text>'
    )
    return (
        f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg"'
        f' font-family="system-ui,sans-serif" style="cursor:crosshair">'
        f'<polygon points="{area_pts}" fill="{color}" fill-opacity="0.12"/>'
        f'<polyline points="{line_pts}" fill="none" stroke="{color}"'
        f' stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>'
        + "".join(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="{color}">'
            f'<title>{days[i][5:]}: {vals[i]:.0f}</title>'
            f'</circle>'
            for i, (x, y) in enumerate(pts)
        )
        + labels
        + "</svg>"
    )


def _svg_stacked_bar(per_day: dict[str, dict], w: int = 380, h: int = 130) -> str:
    """Stacked bar: output (amber) + cache_read (blue) per day."""
    if not per_day:
        return _svg_empty(w, h)
    days = sorted(per_day)
    out_vals  = [per_day[d].get("output", 0) for d in days]
    cr_vals   = [per_day[d].get("cache_read", 0) for d in days]
    max_v = max((a + b for a, b in zip(out_vals, cr_vals)), default=0) or 1
    pad_l, pad_r, pad_t, pad_b = 4, 4, 8, 20
    aw = w - pad_l - pad_r
    ah = h - pad_t - pad_b
    bar_w = max(aw / max(len(days), 1) - 3, 4)
    n = max(len(days) - 1, 1)
    parts = []
    for i, day in enumerate(days):
        x = pad_l + i / max(len(days) - 1, 1) * aw - bar_w / 2
        x = max(pad_l, min(x, w - pad_r - bar_w))
        out_h = out_vals[i] / max_v * ah
        cr_h  = cr_vals[i] / max_v * ah
        # cache_read bar (bottom)
        cr_y = pad_t + ah - cr_h
        parts.append(
            f'<rect x="{x:.1f}" y="{cr_y:.1f}" width="{bar_w:.1f}" height="{cr_h:.1f}"'
            f' rx="2" fill="#6B9BC9" fill-opacity="0.7">'
            f'<title>{day[5:]}: cache read {_fmt(int(cr_vals[i]))}</title>'
            f'</rect>'
        )
        # output bar (stacked on top)
        out_y = pad_t + ah - cr_h - out_h
        parts.append(
            f'<rect x="{x:.1f}" y="{out_y:.1f}" width="{bar_w:.1f}" height="{out_h:.1f}"'
            f' rx="2" fill="#E8A04C" fill-opacity="0.85">'
            f'<title>{day[5:]}: output {_fmt(int(out_vals[i]))}</title>'
            f'</rect>'
        )
    # x labels
    label_y = h - 4
    parts.append(f'<text x="{pad_l}" y="{label_y}" font-size="9" fill="#6f6857">{days[0][5:]}</text>')
    if len(days) > 1:
        parts.append(f'<text x="{w - pad_r}" y="{label_y}" font-size="9" fill="#6f6857" text-anchor="end">{days[-1][5:]}</text>')
    # legend
    parts.append(f'<rect x="{w-80}" y="4" width="8" height="8" rx="1" fill="#E8A04C"/>')
    parts.append(f'<text x="{w-70}" y="11" font-size="9" fill="#9a9282">output</text>')
    parts.append(f'<rect x="{w-80}" y="16" width="8" height="8" rx="1" fill="#6B9BC9"/>')
    parts.append(f'<text x="{w-70}" y="23" font-size="9" fill="#9a9282">cache</text>')
    return (
        f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg"'
        f' font-family="system-ui,sans-serif">'
        + "".join(parts)
        + "</svg>"
    )


def _svg_donut(slices: list[tuple[str, float, str]], size: int = 160) -> str:
    """Donut chart. slices = [(label, value, color)]."""
    total = sum(v for _, v, _ in slices)
    if not total:
        return _svg_empty(size, size, "No data")
    cx = cy = size / 2
    r  = size / 2 - 22
    sw = 20
    circ = 2 * 3.14159265 * r
    parts = []
    offset = 0.0
    for label, value, color in slices:
        pct   = value / total
        dash  = pct * circ
        parts.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r:.1f}" fill="none" stroke="{color}"'
            f' stroke-width="{sw}" stroke-dasharray="{dash:.2f} {circ:.2f}"'
            f' stroke-dashoffset="{-offset:.2f}"'
            f' transform="rotate(-90 {cx} {cy})" style="cursor:crosshair">'
            f'<title>{label}: {pct*100:.1f}%</title>'
            f'</circle>'
        )
        offset += dash
    # center label
    parts.append(
        f'<text x="{cx}" y="{cy - 5}" text-anchor="middle" dominant-baseline="middle"'
        f' font-size="11" font-weight="600" fill="#F5EFE0" font-family="system-ui,sans-serif">'
        + slices[0][0][:8] + "</text>"
    )
    parts.append(
        f'<text x="{cx}" y="{cy + 10}" text-anchor="middle" dominant-baseline="middle"'
        f' font-size="10" fill="#9a9282" font-family="system-ui,sans-serif">'
        f"{slices[0][1] / total * 100:.0f}%</text>"
    )
    return (
        f'<svg viewBox="0 0 {size} {size}" xmlns="http://www.w3.org/2000/svg">'
        + "".join(parts)
        + "</svg>"
    )


def _svg_histogram(values: list[int], bins: int = 6,
                   w: int = 320, h: int = 120) -> str:
    """Histogram of context sizes (in tokens)."""
    if not values:
        return _svg_empty(w, h)
    max_v = max(values)
    bin_size = max(max_v // bins, 1)
    counts = [0] * bins
    for v in values:
        idx = min(int(v / bin_size), bins - 1)
        counts[idx] += 1
    max_count = max(counts) or 1
    pad_l, pad_r, pad_t, pad_b = 4, 4, 8, 24
    aw = w - pad_l - pad_r
    ah = h - pad_t - pad_b
    bar_w = aw / bins - 3
    parts = []
    for i, cnt in enumerate(counts):
        x = pad_l + i * (aw / bins)
        bar_h = cnt / max_count * ah
        y = pad_t + ah - bar_h
        color = "#C9736B" if (i + 1) * bin_size > 150_000 else "#E8A04C"
        lo_k = i * bin_size // 1000
        hi_k = (i + 1) * bin_size // 1000
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}"'
            f' rx="2" fill="{color}" fill-opacity="0.8" style="cursor:crosshair">'
            f'<title>{lo_k}k–{hi_k}k tokens: {cnt} session{"s" if cnt != 1 else ""}</title>'
            f'</rect>'
        )
        label = f"{lo_k}k"
        parts.append(
            f'<text x="{x + bar_w/2:.1f}" y="{h - 6}" text-anchor="middle"'
            f' font-size="8" fill="#6f6857">{label}</text>'
        )
    # 150k threshold line
    if max_v > 150_000:
        tx = pad_l + (150_000 / max(max_v, 1)) * aw
        parts.append(
            f'<line x1="{tx:.1f}" y1="{pad_t}" x2="{tx:.1f}" y2="{pad_t + ah}"'
            f' stroke="#C9736B" stroke-width="1" stroke-dasharray="3,2"/>'
        )
        parts.append(
            f'<text x="{tx + 2:.1f}" y="{pad_t + 8}" font-size="8" fill="#C9736B">150k</text>'
        )
    return (
        f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg"'
        f' font-family="system-ui,sans-serif">'
        + "".join(parts)
        + "</svg>"
    )


def _svg_bar_h(items: list[tuple[str, int, str]], w: int = 320, h: int = 160) -> str:
    """Horizontal bar chart. items = [(label, value, color)]."""
    if not items:
        return _svg_empty(w, h)
    max_v = max(v for _, v, _ in items) or 1
    n     = len(items)
    row_h = h / n
    bar_h = min(row_h * 0.55, 22)
    lw    = 110
    bw    = w - lw - 36
    parts = []
    for i, (label, value, color) in enumerate(items):
        y_mid = i * row_h + row_h / 2
        parts.append(
            f'<text x="{lw - 6}" y="{y_mid + 4:.1f}" text-anchor="end"'
            f' font-size="11" fill="#9a9282">{label[:18]}</text>'
        )
        bar_w = value / max_v * bw
        y_bar = y_mid - bar_h / 2
        parts.append(
            f'<rect x="{lw}" y="{y_bar:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}"'
            f' rx="3" fill="{color}" fill-opacity="0.8" style="cursor:crosshair">'
            f'<title>{label}: {value} dispatch{"es" if value != 1 else ""}</title>'
            f'</rect>'
        )
        parts.append(
            f'<text x="{lw + bar_w + 4:.1f}" y="{y_mid + 4:.1f}"'
            f' font-size="10" fill="#6f6857">{value}</text>'
        )
    return (
        f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg"'
        f' font-family="system-ui,sans-serif">'
        + "".join(parts)
        + "</svg>"
    )

# ── HTML renderer ──────────────────────────────────────────────────────────────

_CSS = """
:root {
  --bg:#16140f;--bg-2:#1c1a14;--surface:#242018;--surface-2:#2c281f;
  --line:#3a352a;--ink-1:#F5EFE0;--ink-2:#C9C2B2;--ink-3:#9a9282;--ink-4:#6f6857;
  --amber:#E8A04C;--amber-soft:#f0c089;--sage:#8FA66B;--rose:#C9736B;--blue:#6B9BC9;
  --radius:14px;--shadow:0 1px 2px rgba(0,0,0,.4),0 12px 32px -12px rgba(0,0,0,.6);
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink-1);
  font-family:'Plus Jakarta Sans',system-ui,-apple-system,'Segoe UI',sans-serif;
  font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased}
h1,h2,h3.display-font{font-family:'Space Grotesk','Segoe UI',system-ui,sans-serif;letter-spacing:-.02em}
.page{max-width:1040px;margin:0 auto;padding:48px 24px 80px}
h1{font-size:38px;font-weight:700;letter-spacing:-.05em}
.subtitle{color:var(--ink-3);font-size:14px;margin-top:6px}
.brand-strip{margin-bottom:28px;padding-bottom:20px;border-bottom:1px solid var(--line)}
/* running hamster logo */
.hamster-logo{display:flex;align-items:center;gap:20px}
.h-run{position:relative;height:6em;width:9ch;
  font-family:'JetBrains Mono',ui-monospace,'Cascadia Code',Consolas,monospace;
  color:var(--amber);font-size:11px;line-height:1.5}
.rf{position:absolute;top:0;left:0;margin:0;white-space:pre}
.rf1{animation:rf-a .9s linear infinite    0s}
.rf2{animation:rf-a .9s linear infinite -.6s}
.rf3{animation:rf-a .9s linear infinite -.3s}
@keyframes rf-a{0%,32.9%{opacity:1}33%,100%{opacity:0}}
.h-brand{display:flex;flex-direction:column;gap:5px;padding-left:4px}
.brand-name{font-family:'Space Grotesk',system-ui,sans-serif;font-size:13px;font-weight:700;
  letter-spacing:.08em;text-transform:uppercase;color:var(--amber)}
.brand-tag{font-size:12px;color:var(--ink-4)}
.summary-bar{display:inline-flex;align-items:center;gap:10px;margin-top:16px;
  padding:8px 16px;background:var(--surface);border:1px solid var(--line);
  border-radius:999px;font-size:13px;font-weight:600;color:var(--ink-2)}
.summary-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.summary-dot.ok{background:var(--sage)}
.summary-dot.warn{background:var(--amber)}
.summary-dot.bad{background:var(--rose)}
.section-label{font-size:11px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;
  color:var(--ink-4);margin:40px 0 14px;display:flex;align-items:center;gap:10px}
.section-label::after{content:"";flex:1;height:1px;background:var(--line)}
.section-label.warn::before{content:"";width:6px;height:6px;border-radius:50%;
  background:var(--amber);flex-shrink:0}
.section-label.info-lbl::before{content:"";width:6px;height:6px;border-radius:50%;
  background:var(--ink-4);flex-shrink:0}
.pills{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0 0}
.pill{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
  padding:14px 20px;min-width:118px;box-shadow:var(--shadow)}
.pill .n{font-size:24px;font-weight:700;letter-spacing:-.03em;color:var(--amber);line-height:1;
  font-family:'Space Grotesk',system-ui,sans-serif}
.pill .l{font-size:10px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;
  color:var(--ink-4);margin-top:7px}
.charts-label{font-size:11px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;
  color:var(--ink-4);margin:40px 0 14px;display:flex;align-items:center;gap:10px}
.charts-label::after{content:"";flex:1;height:1px;background:var(--line)}
.charts{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}
.chart-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
  padding:20px;box-shadow:var(--shadow)}
.chart-card h3{font-size:11px;font-weight:700;color:var(--ink-4);letter-spacing:.07em;
  text-transform:uppercase;margin-bottom:2px;font-family:'Space Grotesk',system-ui,sans-serif}
.chart-card svg{width:100%;height:auto;display:block;margin-top:10px}
.findings{display:flex;flex-direction:column;gap:10px}
.finding{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
  padding:20px 22px;box-shadow:var(--shadow)}
.finding.medium{border-left:3px solid var(--amber)}
.finding.high{border-left:3px solid var(--rose)}
.finding.low{border-left:3px solid var(--blue)}
.finding.info{border-left:3px solid var(--line)}
.finding-meta{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.finding-badge{font-size:10px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;
  background:var(--bg-2);border:1px solid var(--line);border-radius:5px;
  padding:2px 7px;color:var(--ink-4);font-family:'JetBrains Mono',monospace}
.finding-sev{font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase}
.finding-sev.medium{color:var(--amber)}
.finding-sev.high{color:var(--rose)}
.finding-sev.low{color:var(--blue)}
.finding-sev.info{color:var(--ink-4)}
.finding-title{font-size:16px;font-weight:600;color:var(--ink-1);margin-bottom:10px;
  letter-spacing:-.01em;line-height:1.3;font-family:'Space Grotesk',system-ui,sans-serif}
.finding-body{font-size:14px;color:var(--ink-2);line-height:1.65}
.fix-block{margin-top:14px;padding:12px 16px;background:rgba(232,160,76,.07);
  border:1px solid rgba(232,160,76,.2);border-radius:10px;
  font-size:13px;color:var(--amber-soft);line-height:1.6}
.fix-label{font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;
  color:var(--amber);margin-bottom:5px}
.apply-tag{display:inline-block;background:rgba(232,160,76,.12);
  border:1px solid rgba(232,160,76,.3);border-radius:6px;padding:2px 8px;
  font-size:10px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;
  color:var(--amber-soft);margin-left:8px;vertical-align:middle}
.legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:10px}
.legend-item{display:flex;align-items:center;gap:5px;font-size:11px;color:var(--ink-3)}
.legend-dot{width:8px;height:8px;border-radius:2px;flex-shrink:0}
code{font-family:'JetBrains Mono',ui-monospace,'Cascadia Code',Consolas,monospace;
  background:var(--bg-2);padding:1px 5px;border-radius:4px;font-size:.85em;color:var(--amber-soft)}
footer{margin-top:48px;padding-top:20px;border-top:1px solid var(--line);
  font-size:12px;color:var(--ink-4)}
"""


def _pill(value: str, label: str) -> str:
    return (
        f'<div class="pill"><div class="n">{value}</div>'
        f'<div class="l">{label}</div></div>'
    )


def _backtick_to_code(text: str) -> str:
    """Replace `foo` with <code>foo</code> for HTML display."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", text)


def _card_html(f: dict) -> str:
    sev = f["severity"]
    sev_labels = {"high": "Needs fixing", "medium": "Worth fixing", "low": "Minor", "info": "Good to know"}
    apply_tag = '<span class="apply-tag">apply</span>' if f.get("apply_target") else ""
    body = _backtick_to_code(f["finding"])
    fix_html = ""
    if f.get("action"):
        fix_html = (
            f'<div class="fix-block">'
            f'<div class="fix-label">What to do</div>'
            + _backtick_to_code(f["action"])
            + "</div>"
        )
    return (
        f'<div class="finding {sev}">'
        f'<div class="finding-meta">'
        f'<span class="finding-badge">{f["id"]}</span>'
        f'<span class="finding-sev {sev}">{sev_labels.get(sev, sev)}</span>'
        f'</div>'
        f'<div class="finding-title">{f["title"]}{apply_tag}</div>'
        f'<div class="finding-body">{body}</div>'
        + fix_html
        + "</div>"
    )


def render_html(metrics: dict, findings: list[dict], days: int,
                ws: str, we: str, generated: str) -> str:
    mm       = metrics.get("model_mix", {})
    tot_out  = metrics.get("output") or 1
    sessions = metrics.get("sessions", 0)
    per_day  = metrics.get("per_day", {})

    # Summary bar
    action_count = sum(1 for f in findings if f["severity"] in ("high", "medium"))
    info_count   = len(findings) - action_count
    if action_count == 0:
        dot_cls      = "ok"
        summary_text = f"Nothing needs immediate attention &middot; {info_count} tip{'s' if info_count != 1 else ''}"
    elif action_count <= 2:
        dot_cls      = "warn"
        summary_text = (
            f"{action_count} thing{'s' if action_count != 1 else ''} "
            f"need{'s' if action_count == 1 else ''} attention "
            f"&middot; {info_count} tip{'s' if info_count != 1 else ''}"
        )
    else:
        dot_cls      = "bad"
        summary_text = f"{action_count} things need attention &middot; {info_count} tips"

    # Pills
    mix_top  = max(mm.items(), key=lambda x: x[1], default=("—", 0))
    pills    = "".join([
        _pill(str(sessions), "sessions"),
        _pill(_fmt(metrics["output"]), "output tokens"),
        _pill(_pct(metrics["cache_read"], metrics["input"] + metrics["cache_read"]), "cache efficiency"),
        _pill(f"{mix_top[0]}: {_pct(mix_top[1], tot_out)}", "top model"),
    ])

    # Charts
    per_day_cost     = {d: v["cost"] for d, v in per_day.items()}
    per_day_sessions = {d: v["sessions"] for d, v in per_day.items()}
    mix_slices = [
        (t, mm.get(t, 0), TIER_COLORS.get(t, "#9a9282"))
        for t in ["fable", "opus", "sonnet", "haiku"]
        if mm.get(t, 0) > 0
    ]
    a_disp = metrics.get("agent_dispatches", {})
    agent_items = [
        (t, cnt, TIER_COLORS.get(
            _tier((metrics.get("agent_models", {}).get(t) or ["sonnet"])[0]),
            "#E8A04C"
        ))
        for t, cnt in sorted(a_disp.items(), key=lambda x: -x[1])[:8]
    ]

    charts_html = (
        f'<div class="chart-card"><h3>Sessions</h3>'
        + _svg_timeline(per_day_sessions, "#8FA66B") + "</div>"
        + f'<div class="chart-card"><h3>Est. API cost equiv. per day</h3>'
        + _svg_timeline(per_day_cost, "#E8A04C") + "</div>"
        + f'<div class="chart-card"><h3>Token volume per day</h3>'
        + _svg_stacked_bar(per_day)
        + '<div class="legend">'
        + '<div class="legend-item"><div class="legend-dot" style="background:#E8A04C"></div>output</div>'
        + '<div class="legend-item"><div class="legend-dot" style="background:#6B9BC9"></div>cache read</div>'
        + "</div></div>"
        + '<div class="chart-card" style="display:flex;flex-direction:column;align-items:center">'
        + '<h3 style="width:100%">Model mix (by output tokens)</h3>'
        + f'<div style="width:160px;margin:4px auto 0">{_svg_donut(mix_slices)}</div>'
        + '<div class="legend" style="justify-content:center;margin-top:8px">'
        + "".join(
            f'<div class="legend-item"><div class="legend-dot" style="background:{c}"></div>{t}</div>'
            for t, _, c in mix_slices
        )
        + "</div></div>"
    )
    if metrics.get("peak_contexts"):
        charts_html += (
            '<div class="chart-card"><h3>Context size per session</h3>'
            + _svg_histogram(metrics["peak_contexts"])
            + '<div class="legend"><div class="legend-item">'
            + '<div class="legend-dot" style="background:#C9736B"></div>above 150k (heavy)</div></div></div>'
        )
    if a_disp:
        charts_html += (
            '<div class="chart-card"><h3>Agent usage</h3>'
            + _svg_bar_h(agent_items, h=max(60, len(agent_items) * 30))
            + "</div>"
        )

    # Findings — split into "needs attention" and "good to know"
    sev_order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    sorted_f  = sorted(findings, key=lambda x: sev_order.get(x["severity"], 4))
    action_cards   = [_card_html(f) for f in sorted_f if f["severity"] in ("high", "medium")]
    advisory_cards = [_card_html(f) for f in sorted_f if f["severity"] in ("low", "info")]

    action_section = ""
    if action_cards:
        action_section = (
            '<div class="section-label warn">Needs attention</div>'
            + '<div class="findings">' + "\n".join(action_cards) + "</div>"
        )
    advisory_section = ""
    if advisory_cards:
        advisory_section = (
            '<div class="section-label info-lbl">Good to know</div>'
            + '<div class="findings">' + "\n".join(advisory_cards) + "</div>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>caddis · usage review</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>{_CSS}</style>
</head>
<body>
<div class="page">
  <div class="brand-strip">
    <div class="hamster-logo">
      <div class="h-run">
        <pre class="rf rf1"> (\\(\\
( ˘ω˘ )
(っ っ)
 ╱  ╲</pre>
        <pre class="rf rf2"> (\\(\\
( ˘ω˘ )
(っ っ)
 │  │</pre>
        <pre class="rf rf3"> (\\(\\
( ˘ω˘ )
(っ っ)
 ╲  ╱</pre>
      </div>
      <div class="h-brand">
        <span class="brand-name">◆ caddis</span>
        <span class="brand-tag">usage review</span>
      </div>
    </div>
  </div>

  <div>
    <h1>/usage-review</h1>
    <div class="subtitle">Last {days} days &middot; {ws} &ndash; {we} &middot; {sessions} session{"s" if sessions != 1 else ""}</div>
    <div class="summary-bar">
      <div class="summary-dot {dot_cls}"></div>
      <span>{summary_text}</span>
    </div>
  </div>

  <div class="pills">{pills}</div>

  <div class="charts-label">Usage charts</div>
  <div class="charts">{charts_html}</div>

  {action_section}
  {advisory_section}

  <footer>Generated {generated} &middot; <code>.claudster/usage-log.jsonl</code> + session transcripts &middot; Estimates only — all data stays local. &middot; <a href="https://github.com/saajunaid/caddis-plugin" style="color:var(--ink-4)">caddis</a></footer>
</div>
</body>
</html>"""

# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="caddis /usage-review: usage analysis + harness recommendations"
    )
    ap.add_argument("--days", type=int, default=7, help="Analysis window in days (default 7)")
    ap.add_argument("--cwd", default=os.getcwd(), help="Project root (default: cwd)")
    ap.add_argument("--no-html", action="store_true", help="Skip HTML dashboard generation")
    ap.add_argument(
        "--output-dir", default=None,
        help="Directory for HTML output relative to cwd. Defaults to .claudster/reviews.",
    )
    args = ap.parse_args()

    cwd  = _repo_root(os.path.abspath(args.cwd))
    days = args.days
    now  = datetime.now(timezone.utc)
    ws   = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    we   = now.strftime("%Y-%m-%d")

    # Resolve output directory: HTML dashboard lives under .claudster/reviews
    if args.output_dir is not None:
        out_subdir = args.output_dir
    else:
        out_subdir = os.path.join(".claudster", "reviews")

    # Load data
    current_sessions, prev_sessions = load_usage_log(cwd, days)

    if not current_sessions:
        print(
            f"# /usage-review\n\n"
            f"No sessions found in the last {days} days.\n"
            f"Run a few sessions to build up data, then re-run `/usage-review`.\n\n"
            f"(Data file: {os.path.join(cwd, '.claudster', 'usage-log.jsonl')})"
        )
        return

    session_ids = [s.get("_session_id", "") for s in current_sessions if s.get("_session_id")]
    transcripts = load_transcripts(cwd, session_ids)
    metrics     = compute_metrics(current_sessions, transcripts)
    prev_metrics = compute_metrics(prev_sessions, {})
    agents       = load_agent_config(cwd)
    findings     = run_rules(metrics, prev_metrics, agents)

    # Markdown to stdout
    print(render_markdown(metrics, findings, days, ws, we))

    # HTML dashboard
    if not args.no_html:
        generated = now.strftime("%Y-%m-%d %H:%M UTC")
        html = render_html(metrics, findings, days, ws, we, generated)
        out_dir = os.path.join(cwd, out_subdir)
        os.makedirs(out_dir, exist_ok=True)
        html_path = os.path.join(out_dir, "usage-review.html")
        with open(html_path, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"\n→ HTML dashboard: {html_path}")

    # Update last-review timestamp — in .claudster so inject_relay.py finds it
    claudster_dir = os.path.join(cwd, ".claudster")
    os.makedirs(claudster_dir, exist_ok=True)
    stamp_path = os.path.join(claudster_dir, ".last-usage-review")
    try:
        with open(stamp_path, "w", encoding="utf-8") as fh:
            fh.write(now.isoformat(timespec="seconds"))
    except Exception:
        pass


if __name__ == "__main__":
    main()
