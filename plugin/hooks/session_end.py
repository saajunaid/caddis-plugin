"""Session-end nudge + token-usage digest on Stop.

Two jobs, both non-blocking (prints, exits 0; never fails a turn):
  1. Remind the operator to persist what survives context death (relay.md + lessons).
  2. Summarise this session's token usage from the transcript, print a digest, and
     append one line to `<artifact-dir>/usage-log.jsonl` so spend is trackable over time.

The usage parse is fully defensive: any missing/odd field just drops the digest and
still prints the nudge. Cost is a rough ESTIMATE from an editable per-model rate table —
adjust PRICING_PER_MTOK to your actual plan/rates (or ignore cost and read the tokens).
Cross-platform (pure Python, stdlib only).

Writes into the repo's `.caddis/` artifact dir.
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

# Shared artifact-dir resolution (scripts/claudster_config.py) with an inline fallback — a Stop
# hook must never die on an import problem.
try:
    _CFG_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
    if _CFG_SCRIPTS not in sys.path:
        sys.path.insert(0, _CFG_SCRIPTS)
    from claudster_config import artifact_root  # noqa: E402
except Exception:  # pragma: no cover — defensive
    def artifact_root(root):
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


def _extract_identity(transcript_path: str) -> tuple[set[str], set[str], set[str]]:
    """Return ``(skills, commands, skills_read)`` for this session — names only.

    V16 (2026-08-22): ``skills`` counts only ``Skill`` tool_use events, so a skill that a
    COMMAND told the model to read never registered. Every such skill scored zero, and a
    zero was about to be read as "nobody uses this". ``skills_read`` closes that gap: a
    ``Read`` of a ``SKILL.md`` under an INSTALL path is the model following a skill it was
    pointed at. A read under the working repo is authoring the skill, not using it, so it
    is excluded — otherwise editing caddis would look like using caddis.

    Still invisible, and deliberately not guessed at: a skill inlined into a command's own
    prose, and a skill file opened through ``Bash`` (``sed``/``cat``), which is equally
    often authoring. Treat ``skills_read`` as a floor, never as a complete count.

    V15: the usage log carried token totals but no skill/command identity, so the pruning
    question (Phase 12) was unanswerable from evidence. This recovers that identity at the
    Stop hook (where the per-session record is born and the transcript is already read once
    for tokens), so the log becomes self-describing and survives transcript compaction.

    Sources (both verified against live fleet transcripts 2026-08-05):
      * **Skills** — ``Skill`` tool_use events on assistant turns; only ``input.skill`` is
        taken, never any other argument.
      * **Commands** — the ``<command-name>/plugin:cmd</command-name>`` marker the harness
        embeds in user-message text; the leading slash is stripped.

    Privacy bar: a Skill tool_use may carry a prompt or args in other ``input`` keys — those
    are ignored. Fully fail-open: any read/parse error returns empty sets, never a crash.
    """
    skills: set[str] = set()
    commands: set[str] = set()
    skills_read: set[str] = set()
    # A skill file under the session's own working tree is being authored, not followed.
    _repo = os.path.abspath(os.getcwd()).replace("\\", "/").lower()
    if not transcript_path or not os.path.isfile(transcript_path):
        return skills, commands, skills_read
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
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role")
                content = msg.get("content")
                # Skills: Skill tool_use on assistant turns — name only.
                if role == "assistant" and isinstance(content, list):
                    for item in content:
                        if not isinstance(item, dict) or item.get("type") != "tool_use":
                            continue
                        if item.get("name") == "Skill":
                            inp = item.get("input") if isinstance(item.get("input"), dict) else {}
                            sk = inp.get("skill")
                            if isinstance(sk, str) and sk.strip():
                                skills.add(sk.strip())
                        elif item.get("name") == "Read":
                            # Deliberately Read only. Edit/Write is authoring; Bash is
                            # ambiguous. A floor is more useful than a wrong number.
                            inp = item.get("input") if isinstance(item.get("input"), dict) else {}
                            fp = inp.get("file_path")
                            if isinstance(fp, str):
                                norm = fp.replace("\\", "/")
                                if norm.lower().endswith("/skill.md") and not norm.lower().startswith(_repo):
                                    parts = [seg for seg in norm.split("/") if seg]
                                    if len(parts) >= 2:
                                        skills_read.add(parts[-2])
                # Commands: <command-name>/plugin:cmd</command-name> marker on user turns.
                if role == "user":
                    text = ""
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, list):
                        text = "\n".join(
                            b.get("text", "") for b in content
                            if isinstance(b, dict) and isinstance(b.get("text"), str)
                        )
                    for m in re.finditer(r"<command-name>\s*(/[^<\s]+)\s*</command-name>", text):
                        commands.add(m.group(1).strip().lstrip("/"))
    except Exception:
        pass
    return skills, commands, skills_read


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
# V15/V16: record which skills/commands fired (names only) alongside the token totals, so the
# pruning question is answerable from the log instead of taste. Computed unconditionally so
# identity is captured even when the token parse yields nothing. V16 adds skills_read, because
# counting only Skill tool_use produced a zero for every skill a command pointed the model at —
# and those zeros were about to be read as evidence of disuse.
skills, commands, skills_read = _extract_identity(data.get("transcript_path", ""))
if u:
    print(
        f"\n[USAGE] this session ~ in {_fmt(u['input'])} · out {_fmt(u['output'])} · "
        f"cache {_fmt(u['cache_write'] + u['cache_read'])} "
        f"({_fmt(u['cache_read'])} read) · est. ${u['est_cost_usd']:.2f} "
        f"(estimate — edit rates in session_end.py)"
    )
# Write a record whenever there is token data OR identity. Tying the write to tokens alone
# would lose identity for any session whose usage parse returned nothing — pruning evidence
# must not depend on token accounting succeeding.
if u or skills or commands or skills_read:
    try:
        caddis_dir = str(artifact_root(_repo_root(_session_cwd)))
        os.makedirs(caddis_dir, exist_ok=True)
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "session": data.get("session_id", ""),
            "input": u["input"] if u else 0,
            "output": u["output"] if u else 0,
            "cache_write": u["cache_write"] if u else 0,
            "cache_read": u["cache_read"] if u else 0,
            "est_cost_usd": u["est_cost_usd"] if u else 0.0,
            "models": u["models"] if u else [],
            "skills": sorted(skills),
            "commands": sorted(commands),
            # V16: skills the model READ because something pointed it there, as opposed to
            # skills it CHOSE via the Skill tool. Kept as a separate key on purpose — merging
            # them would make "the model picked this" indistinguishable from "a command made
            # it read this", and that difference is the whole point of the measurement.
            "skills_read": sorted(skills_read),
        }
        with open(os.path.join(caddis_dir, "usage-log.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except Exception:
        pass

# Dream Memory capture RETIRED 2026-08-26 — see the note in inject_relay.py. The store it fed
# (.caddis/memory.jsonl) is left in place; nothing reads it. Claude Code's per-repo memory
# directory holds the curated facts instead, with descriptions, types and an index.
sys.exit(0)
