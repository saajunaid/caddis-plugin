"""SubagentStop → append one line to `<artifact-dir>/agent-log.jsonl`.

Signal 1 of the agent-eval runbook (`.github/agent-docs/agent-eval.md`): an always-on
log of subagent dispatches + verdicts, so verdict distribution per agent is reviewable
over time (rubber-stamping, over-strictness, never-dispatched agents).

Non-blocking by construction: prints nothing, exits 0 on every path — a broken log
must never fail a subagent's turn. Anchors to the SESSION repo (payload `cwd`, same
convention as session_end.py/inject_relay.py), not the hook process's launch cwd.
Cross-platform, stdlib only.

Writes into the repo's `.caddis/` artifact dir, only when that folder already exists.
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

# No child process of this hook opens a console window on Windows (scripts/no_window.py). The inline
# fallback keeps a hook from ever dying on an import problem.
try:
    _nw_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
    if _nw_dir not in sys.path:
        sys.path.insert(0, _nw_dir)
    from no_window import NO_WINDOW_KW  # noqa: E402
except Exception:  # pragma: no cover - defensive
    NO_WINDOW_KW = {"creationflags": 0x08000000} if os.name == "nt" else {}

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


def _repo_root(start: str):
    """Git repo root for `start`, or None when `start` is in no git repository."""
    try:
        out = subprocess.run(
            ["git", "-C", start, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=3, **NO_WINDOW_KW,
        )
        root = out.stdout.strip()
        if out.returncode == 0 and root:
            return root
    except Exception:
        pass
    return None


def _agent_type_from_meta(transcript_path: str) -> str:
    """Recover the agent type from the subagent's own `<transcript>.meta.json` sidecar.

    Claude Code's SubagentStop payload carries agent_id, agent_transcript_path, and in
    current versions agent_type. Evidence from the last 50 local agent-log rows on
    2026-09-25: all carried ts/agent/verdict/session_id; 48 had a hex id in agent.
    The payload type is primary. This sidecar is a fallback when it is absent.
    """
    if not isinstance(transcript_path, str) or not transcript_path:
        return ""
    meta_path = re.sub(r"\.jsonl$", ".meta.json", transcript_path)
    if meta_path == transcript_path:
        return ""
    for attempt in range(5):
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, encoding="utf-8") as fh:
                    meta = json.load(fh)
            except Exception:  # half-written by Claude Code at this moment: wait and read again
                meta = None
            if isinstance(meta, dict):
                val = meta.get("agentType")
                return val.strip() if isinstance(val, str) and val.strip() else ""
            if meta is not None:  # complete JSON, but not an object: waiting will not help
                return ""
        if attempt < 4:
            time.sleep(0.2)
    return ""


def _agent_name(data: dict) -> str:
    def is_type(value: object) -> bool:
        return (isinstance(value, str) and bool(value.strip())
                and value.strip() != data.get("agent_id")
                and not re.fullmatch(r"[0-9a-fA-F]{8,}", value.strip()))

    val = data.get("agent_type")
    if is_type(val):
        return val.strip()
    meta_type = _agent_type_from_meta(data.get("agent_transcript_path") or data.get("transcript_path") or "")
    if is_type(meta_type):
        return meta_type
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
    # Tolerate markdown emphasis around the label (e.g. "**Verdict: changes-requested**") --
    # found live 2026-07-30: a subagent that phrases its verdict as bolded prose instead of a
    # plain yaml-style `verdict:` line was silently logged as "none". Still anchored to the
    # START of a line (re.M) so a mid-sentence reference like "...per the verdict: above" can't
    # false-positive.
    hits = re.findall(r"^\s*[*_]{0,2}verdict[*_]{0,2}\s*:\s*[*_]{0,2}\s*([A-Za-z][A-Za-z_-]*)",
                       text, re.M | re.I)
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
    if not root:
        return 0  # in no git repository: nothing to attach a log to
    transcript = data.get("agent_transcript_path") or data.get("transcript_path") or ""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "agent": _agent_name(data),
        "agent_id": data.get("agent_id", ""),
        "verdict": _verdict(_last_assistant_text(transcript)),
        "session_id": data.get("session_id", ""),
    }
    try:
        log_dir = str(artifact_root(root))
        if not os.path.isdir(log_dir):
            return 0  # the repo never opted in: do not create the artifact folder
        with open(os.path.join(log_dir, "agent-log.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # a broken log must never fail the turn
    return 0


if __name__ == "__main__":
    sys.exit(main())
