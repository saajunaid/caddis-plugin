#!/usr/bin/env python3
"""caddis warm-start hook for agy (Antigravity) — PreInvocation event.

Ports the relay half of claude-harness/hooks/inject_relay.py. agy has NO SessionStart event, so the
nearest equivalent is PreInvocation with `invocationNum == 0` — the first model turn of a session.
**agy's invocations are 0-indexed** (confirmed via a live-fire session against the real `agy` binary
2026-07-30 -- the original code checked `== 1`, which is agy's SECOND turn, so this hook silently
never fired at all until the live check caught it; see .caddis/plans/agy-hooks-port.md step 5).
On that turn only, the workspace's relay doc is injected as an ephemeral step so a fresh agy session
resumes with zero re-discovery. Every later invocation emits nothing (re-injecting the relay on every
turn would burn context and drown the conversation).

Self-contained (the agy bundle ships neither claude-harness/hooks/ nor scripts/), stdlib-only.

agy PreInvocation stdin (camelCase protojson):
  {"invocationNum": 1, "initialNumSteps": N, "conversationId": "…", "workspacePaths": ["…"], …}
  NOTE: cwd is the PLUGIN dir, not the workspace — the repo root comes from workspacePaths[0].

agy PreInvocation stdout:
  {"injectSteps": [{"ephemeralMessage": "…"}]}   — or nothing at all.

Fail open: any error, missing relay, or non-first invocation prints NOTHING and exits 0.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

_ARTIFACT_DIRS = (".caddis",)

INJECT_MAX_LINES = 120      # same budget as the Claude Code hook
INJECT_MAX_CHARS = 24000    # hard backstop: an ephemeralMessage should never be a context bomb


def _first_existing(paths: list[str]) -> str:
    for p in paths:
        try:
            if os.path.isfile(p):
                return p
        except Exception:
            continue
    return ""


def _branch_slug(root: str) -> str:
    """Filesystem-safe current branch name, or "" when it can't be determined (best-effort)."""
    try:
        branch = subprocess.run(
            ["git", "-C", root, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip()
    except Exception:
        return ""
    if not branch or branch == "HEAD":
        return ""
    return "".join(c if (c.isalnum() or c in "-_.") else "-" for c in branch)


def resolve_relay(root: str) -> str:
    """First existing relay doc for `root`, else "".

    Preference order mirrors inject_relay.py:
      1. .caddis/relay/<branch>.md          (per-branch team mode)
      2. .caddis/relay.md                   (solo/default)
      3. .claude/relay/<branch>.md          (legacy per-branch)
      4. relay.md                           (legacy repo root)
    """
    slug = _branch_slug(root)
    candidates: list[str] = []
    if slug:
        candidates += [os.path.join(root, d, "relay", f"{slug}.md") for d in _ARTIFACT_DIRS]
    candidates += [os.path.join(root, d, "relay.md") for d in _ARTIFACT_DIRS]
    if slug:
        candidates.append(os.path.join(root, ".claude", "relay", f"{slug}.md"))
    candidates.append(os.path.join(root, "relay.md"))
    return _first_existing(candidates)


def truncate_relay(text: str) -> str:
    """Cap the injected doc.

    Line pass (from inject_relay.py): over INJECT_MAX_LINES, replace the unbounded `## Done` bullets
    with a one-liner so `## Next step` / the resume prompt is never pushed off-screen; if the section
    headers can't be found, keep the text as-is rather than lose data. Char pass: a hard tail-cut so a
    pathological relay can't blow up the ephemeral message.
    """
    lines = text.splitlines()
    if len(lines) > INJECT_MAX_LINES:
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
        if done_idx is not None and next_step_idx is not None and read_first_idx is not None:
            omitted = len([l for l in lines[done_idx + 1:next_step_idx] if l.strip().startswith("-")])
            summary = f"- [Done section truncated — {omitted} bullets omitted to save context; see git log]"
            text = "\n".join(lines[:done_idx + 1] + [summary, ""] + lines[next_step_idx:])
    if len(text) > INJECT_MAX_CHARS:
        text = text[:INJECT_MAX_CHARS] + "\n\n[…relay truncated — read the file for the rest]"
    return text


def main() -> None:
    try:
        _reconfig = getattr(sys.stdout, "reconfigure", None)
        if _reconfig:
            try:
                _reconfig(encoding="utf-8")
            except Exception:
                pass
        try:
            data = json.load(sys.stdin)
        except Exception:
            return
        if not isinstance(data, dict):
            return
        # SessionStart equivalent: the FIRST invocation only (agy 0-indexes invocationNum, so the
        # first turn is 0, not 1). Anything else (or an unparseable invocationNum) injects nothing.
        try:
            if int(data.get("invocationNum")) != 0:
                return
        except Exception:
            return
        workspaces = data.get("workspacePaths") or []
        if not (isinstance(workspaces, list) and workspaces):
            return
        root = str(workspaces[0])
        relay = resolve_relay(root)
        if not relay:
            return
        text = open(relay, encoding="utf-8").read().strip()
        if not text:
            return
        message = ("=== relay.md (session resume — read before acting) ===\n\n"
                   + truncate_relay(text))
        payload = json.dumps({"injectSteps": [{"ephemeralMessage": message}]})
        sys.stdout.write(payload)
    except Exception:
        return  # fail open: no injection is always better than a broken invocation
    finally:
        sys.exit(0)


if __name__ == "__main__":
    main()
