"""Session-end nudge + token-usage digest on Stop.

Two jobs, both non-blocking (prints, exits 0; never fails a turn):
  1. Remind the operator to persist what survives context death (relay.md + lessons).
  2. Summarise this session's token usage from the transcript, print a digest, and
     append one line to `<artifact-dir>/usage-log.jsonl` so spend is trackable over time.

The usage parse is fully defensive: any missing/odd field just drops the digest and
still prints the nudge. Cost is a rough ESTIMATE from an editable per-model rate table —
adjust PRICING_PER_MTOK to your actual plan/rates (or ignore cost and read the tokens).
Cross-platform (pure Python, stdlib only).

Writes where the repo lives: `.caddis/` normally, but an unmigrated repo that still has
`.claudster/` keeps its state there rather than growing a second dir.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

# Shared artifact-dir resolution (scripts/claudster_config.py) with an inline fallback — a Stop
# hook must never die on an import problem. Same rule either way: write where the repo lives.
try:
    _CFG_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
    if _CFG_SCRIPTS not in sys.path:
        sys.path.insert(0, _CFG_SCRIPTS)
    from claudster_config import artifact_root  # noqa: E402
except Exception:  # pragma: no cover — defensive
    def artifact_root(root):
        for _n in (".caddis", ".claudster"):
            if os.path.isdir(os.path.join(str(root), _n)):
                return os.path.join(str(root), _n)
        return os.path.join(str(root), ".caddis")

_reconfig = getattr(sys.stdout, "reconfigure", None)
if _reconfig:
    try:
        _reconfig(encoding="utf-8")
    except Exception:
        pass

# ── editable: approximate USD per 1M tokens (input, output). Cache read ≈ 0.1× input,
#    cache write ≈ 1.25× input. These are estimates — set them to your real rates. ──
#    Non-Anthropic tiers matter because model-lane work runs GLM/DeepSeek/Qwen and
#    self-hosted models; without them those sessions would misbill as Sonnet. ──
PRICING_PER_MTOK = {
    "opus":     (15.0, 75.0),
    "sonnet":   (3.0, 15.0),
    "haiku":    (1.0, 5.0),
    "glm":      (0.60, 2.20),   # Zhipu GLM-4.6 (Z.ai)
    "deepseek": (0.27, 1.10),   # DeepSeek V3 chat (cache-miss)
    "qwen":     (0.40, 1.20),   # Alibaba Qwen (DashScope)
    "kimi":     (0.60, 2.50),   # Moonshot Kimi K2
    "local":    (0.0, 0.0),     # self-hosted / ollama / lm-studio — no per-token API cost
}


def _tier(model: str) -> str:
    m = (model or "").lower()
    if "opus" in m:
        return "opus"
    if "sonnet" in m:
        return "sonnet"
    if "haiku" in m:
        return "haiku"
    if "glm" in m:
        return "glm"
    if "deepseek" in m:
        return "deepseek"
    if "qwen" in m:
        return "qwen"
    if "kimi" in m or "moonshot" in m:
        return "kimi"
    # Self-hosted / local runtimes carry no per-token API cost.
    if any(k in m for k in ("ollama", "local", "llama", "mistral", "lmstudio", "lm-studio", "gemma", "phi")):
        return "local"
    return "sonnet"  # unknown hosted model → conservative Anthropic-mid estimate


def _read_input() -> dict:
    try:
        return json.load(sys.stdin) or {}
    except Exception:
        return {}


def _summarise(transcript_path: str) -> dict | None:
    """Sum token usage across assistant messages in the transcript JSONL."""
    if not transcript_path or not os.path.isfile(transcript_path):
        return None
    tot = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}
    models: dict[str, int] = {}
    cost = 0.0
    found = False
    try:
        with open(transcript_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                msg = ev.get("message") if isinstance(ev.get("message"), dict) else ev
                usage = msg.get("usage") if isinstance(msg, dict) else None
                if not isinstance(usage, dict):
                    continue
                found = True
                i = int(usage.get("input_tokens", 0) or 0)
                o = int(usage.get("output_tokens", 0) or 0)
                cw = int(usage.get("cache_creation_input_tokens", 0) or 0)
                cr = int(usage.get("cache_read_input_tokens", 0) or 0)
                tot["input"] += i
                tot["output"] += o
                tot["cache_write"] += cw
                tot["cache_read"] += cr
                model = (msg.get("model") if isinstance(msg, dict) else "") or ""
                if model:
                    models[model] = models.get(model, 0) + 1
                inp, outp = PRICING_PER_MTOK[_tier(model)]
                cost += (i * inp + cw * inp * 1.25 + cr * inp * 0.1 + o * outp) / 1_000_000
    except Exception:
        return None
    if not found:
        return None
    tot["billable_input"] = tot["input"] + tot["cache_write"] + tot["cache_read"]
    tot["est_cost_usd"] = round(cost, 4)
    tot["models"] = sorted(models)
    return tot


def _fmt(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}k"
    return str(n)


def _repo_root(start: str) -> str:
    """Git repo root for `start`, or `start` itself when not a git repo.

    State anchors to the repo root so a session launched from a subfolder appends
    to the one shared log instead of scattering a `.caddis/` into every cwd.
    Best-effort: any git failure (not a repo / git missing) falls back to `start`.
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


data = _read_input()

# Anchor all session state (usage log + Dream Memory store) to the repo the SESSION
# is operating in — the payload's cwd — not the hook process's launch cwd. Without
# this, a session launched in one repo but working in another (e.g. caddis ↔
# docket) leaks the second repo's facts into the first's store. Mirrors guard.py.
_session_cwd = data.get("cwd") or os.getcwd()

print(
    "\n[HARNESS] Session ending. Two things survive context death:\n"
    "  1. relay.md — refresh it so the next session resumes exactly (run /handoff).\n"
    "  2. Durable lessons — if you wrote or fixed code this session, dispatch the\n"
    "     knowledge-transfer subagent BEFORE relay.md. Don't skip it just because you\n"
    "     hand-wrote some docs. Record the outcome in relay.md's 'Learnings captured' line."
)

u = _summarise(data.get("transcript_path", ""))
if u:
    print(
        f"\n[USAGE] this session ~ in {_fmt(u['input'])} · out {_fmt(u['output'])} · "
        f"cache {_fmt(u['cache_write'] + u['cache_read'])} "
        f"({_fmt(u['cache_read'])} read) · est. ${u['est_cost_usd']:.2f} "
        f"(estimate — edit rates in session_end.py)"
    )
    try:
        caddis_dir = str(artifact_root(_repo_root(_session_cwd)))
        os.makedirs(caddis_dir, exist_ok=True)
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "session": data.get("session_id", ""),
            "input": u["input"], "output": u["output"],
            "cache_write": u["cache_write"], "cache_read": u["cache_read"],
            "est_cost_usd": u["est_cost_usd"], "models": u["models"],
        }
        with open(os.path.join(caddis_dir, "usage-log.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except Exception:
        pass

# ── Dream Memory capture (fann Phase 5b) ──────────────────────────────────────
# Mine the transcript for deterministic, high-confidence facts (a Bash command that failed; a
# build/test that went red→green) and consolidate them into the per-repo store. Privacy-first
# (secret-touching commands skipped, inline secrets redacted) and fully fail-open — capture must
# never slow or break a Stop, so the whole block is wrapped and silent on any error.
try:
    _scripts = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
    if _scripts not in sys.path:
        sys.path.insert(0, _scripts)
    import dream_memory as _dm
    import dream_capture as _dc

    _now = datetime.now(timezone.utc).isoformat()
    _candidates = []
    _tp = data.get("transcript_path", "")
    if _tp and os.path.isfile(_tp):
        _records = []
        with open(_tp, encoding="utf-8") as _fh:
            for _line in _fh:
                _line = _line.strip()
                if not _line:
                    continue
                try:
                    _records.append(json.loads(_line))
                except Exception:
                    continue
        _candidates = _dc.extract_facts(_records, _now)
    # Consolidate whenever there's something to do: new candidates, OR an existing store to
    # self-compact (apply decay/cap, and dedup any facts the knowledge-transfer agent appended
    # out-of-band). No store and no candidates → nothing written (no noise).
    _root = _repo_root(_session_cwd)
    _store = _dm.store_path(_root)
    _existing = _dm.load_facts(_store)
    if _candidates or _existing:
        _t = _dm.load_tunables(_root)
        _dm.save_facts(_store, _dm.consolidate(
            _existing + _candidates, _now, max_age_days=_t["prune_age_days"], cap=_t["max_facts"]))
except Exception:
    pass

sys.exit(0)
