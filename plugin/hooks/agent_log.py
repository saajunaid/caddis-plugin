"""SubagentStop → append one line to `<artifact-dir>/agent-log.jsonl`.

Signal 1 of the agent-eval runbook (`.github/agent-docs/agent-eval.md`): an always-on
log of subagent dispatches + verdicts, so verdict distribution per agent is reviewable
over time (rubber-stamping, over-strictness, never-dispatched agents).

Non-blocking by construction: prints nothing, exits 0 on every path — a broken log
must never fail a subagent's turn. Anchors to the SESSION repo (payload `cwd`, same
convention as session_end.py/inject_relay.py), not the hook process's launch cwd.
Cross-platform, stdlib only.

Writes into the repo's `.caddis/` artifact dir.
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

# Shared artifact-dir resolution (scripts/claudster_config.py) with an inline fallback, so a
# SubagentStop can never die on an import problem.
try:
    _SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
    if _SCRIPTS not in sys.path:
        sys.path.insert(0, _SCRIPTS)
    from claudster_config import artifact_root  # noqa: E402
except Exception:  # pragma: no cover — defensive
    def artifact_root(root):
        return os.path.join(str(root), ".caddis")


def _read_input() -> dict:
    try:
        data = json.load(sys.stdin)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _repo_root(start: str) -> str:
    """Git repo root for `start`, or `start` itself when not a git repo."""
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


def _agent_type_from_meta(transcript_path: str) -> str:
    """Recover the agent type from the subagent's own `<transcript>.meta.json` sidecar.

    Claude Code's SubagentStop payload does not always carry agent_type/subagent_type/
    agent_name directly (observed empirically 2026-07-30: intermittently absent across an
    otherwise-identical dispatch shape, cause not pinned down) -- but the sidecar file next
    to agent_transcript_path (agent-<id>.jsonl -> agent-<id>.meta.json) reliably has
    `{"agentType": "..."}`. Falls back to "" on any problem (missing file, bad JSON, no key)."""
    if not transcript_path:
        return ""
    meta_path = re.sub(r"\.jsonl$", ".meta.json", transcript_path)
    if meta_path == transcript_path or not os.path.isfile(meta_path):
        return ""
    try:
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)
        val = meta.get("agentType")
        if isinstance(val, str) and val.strip():
            return val.strip()
    except Exception:
        pass
    return ""


def _agent_name(data: dict) -> str:
    for key in ("agent_type", "subagent_type", "agent_name"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    meta_type = _agent_type_from_meta(data.get("agent_transcript_path") or data.get("transcript_path") or "")
    if meta_type:
        return meta_type
    val = data.get("agent_id")
    if isinstance(val, str) and val.strip():
        return val.strip()
    return "unknown"


def _last_assistant_text(transcript_path: str) -> str:
    """Last assistant text block in the transcript JSONL ('' when unreadable)."""
    if not transcript_path or not os.path.isfile(transcript_path):
        return ""
    last = ""
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
                if not isinstance(msg, dict) or msg.get("role") != "assistant":
                    continue
                content = msg.get("content")
                if isinstance(content, str) and content.strip():
                    last = content
                elif isinstance(content, list):
                    texts = [b.get("text", "") for b in content
                             if isinstance(b, dict) and b.get("type") == "text"]
                    joined = "\n".join(t for t in texts if t)
                    if joined.strip():
                        last = joined
    except Exception:
        return ""
    return last


def _verdict(text: str) -> str:
    """Best-effort verdict classification from a subagent's final message.

    Priority: an explicit `verdict:` field (the house return-format for reviewer-style
    agents) → a final-line REVIEW/PREFLIGHT-style marker → a bare PASS/FAIL token.
    Returns a lowercase token, or "none" when nothing recognizable is present.
    """
    if not text:
        return "none"
    hits = re.findall(r"^\s*verdict:\s*([A-Za-z][A-Za-z_-]*)", text, re.M | re.I)
    if hits:
        return hits[-1].lower()
    for line in reversed([ln.strip() for ln in text.splitlines() if ln.strip()]):
        m = re.match(r"(?:REVIEW|PREFLIGHT|GATE)\s*:\s*([A-Za-z][A-Za-z_-]*)", line, re.I)
        if m:
            return m.group(1).lower()
        break  # only the final non-empty line counts for markers (the F6 lesson)
    m = re.search(r"\b(PASS(?:ED)?|FAIL(?:ED)?|APPROVED|BLOCKED)\b", text)
    if m:
        return m.group(1).lower()
    return "none"


def main() -> int:
    data = _read_input()
    cwd = data.get("cwd") or os.getcwd()
    root = _repo_root(cwd)
    transcript = data.get("agent_transcript_path") or data.get("transcript_path") or ""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "agent": _agent_name(data),
        "verdict": _verdict(_last_assistant_text(transcript)),
        "session_id": data.get("session_id", ""),
    }
    try:
        log_dir = str(artifact_root(root))
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "agent-log.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # a broken log must never fail the turn
    return 0


if __name__ == "__main__":
    sys.exit(main())
