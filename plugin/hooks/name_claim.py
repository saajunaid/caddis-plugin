#!/usr/bin/env python3
"""UserPromptSubmit hook: claim this session's role name, once per session.

A Claude Code background session keeps its name after `/clear` and `/exit`. A new session for the same role then
shares the name or gets " (2)", and peers that message the role by name reach the old, idle session. On the first
prompt of a session this hook reads `claude agents --json` once. When another session in the SAME repo holds the
same base name, it:
  - stops that session only when it is a background session that is idle and done or blocked (`claude stop <id>`;
    its conversation is kept, `claude attach <id>` brings it back);
  - renames this session to the plain name (`sessionTitle`) when it had a " (N)" suffix and every holder stopped;
  - warns about every other holder (an open window, a busy or waiting session, a failed stop).

Rules for a hook that runs in every session: stdlib only, fail open and silent, never raises, always exits 0,
prints nothing unless it stopped, renamed or warned. A marker file written BEFORE the `claude agents` call makes
the check run once per session id, so a crash or timeout never repeats it. Headless runs are skipped.
Plan: .caddis/plans/session-name-claim.md.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable

_HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)
try:
    from session_waiting import _repo_root
except Exception:  # pragma: no cover - defensive: without it main() does nothing
    _repo_root = None

# No child process of this hook opens a console window on Windows (scripts/no_window.py). The inline
# fallback keeps a hook from ever dying on an import problem.
try:
    _nw_dir = os.path.join(os.path.dirname(_HOOKS_DIR), "scripts")
    if _nw_dir not in sys.path:
        sys.path.insert(0, _nw_dir)
    from no_window import NO_WINDOW_KW
except Exception:  # pragma: no cover - defensive
    NO_WINDOW_KW = {"creationflags": 0x08000000} if os.name == "nt" else {}

_SUFFIX = re.compile(r" \((\d+)\)$")
CLASH_KINDS = ("interactive", "background")
STOP_STATES = ("done", "blocked")


def base_name(name: str) -> str:
    """The role name without Claude Code's " (N)" counter."""
    return _SUFFIX.sub("", name)


def started_at(row: dict) -> float | None:
    """The row's `startedAt` (ms since the epoch): when its process started. `/clear` does not reset it
    (measured 23 Nov 2026), so an old holder that had /clear still looks old. None when missing, not a number,
    zero, negative or not finite: an unknown time must never make a holder look older."""
    value = row.get("startedAt")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and value > 0 else None


def is_older(row: dict, me: dict) -> bool:
    """True only when both start times are known and the row's process started strictly before ours."""
    theirs, mine = started_at(row), started_at(me)
    return theirs is not None and mine is not None and theirs < mine


def sid8(row: dict) -> str:
    return str(row.get("sessionId") or "")[:8].lower()


def label(row: dict) -> str:
    return f"{row['name']}@{sid8(row)}"


def stoppable(row: dict) -> bool:
    """Only an idle background session that finished its turn may be stopped. Unknown values fall to "warn"."""
    return row.get("kind") == "background" and row.get("status") == "idle" and row.get("state") in STOP_STATES


def decide(own_sid: str, own_cwd: str, rows: list[dict], root_of: Callable[[str], str]) -> dict:
    """Split the rows that clash with this session's name (same base name, same repo, not stopped) into the ones
    to stop and the ones to warn about. Only a holder whose process started before ours (`startedAt`) may be
    stopped: the old session must never stop the one the owner now uses, also when both names are plain. A missing
    start time means "warn". `rename` is True when this session
    has a " (N)" suffix, at least one holder is to be stopped and none needs a warning; the caller still checks
    that each stop worked."""
    empty = {"base": None, "own_name": None, "stop": [], "warn": [], "rename": False}
    own_key = own_sid.strip().lower()
    if not own_key:
        return empty
    me = next((r for r in rows if str(r.get("sessionId") or "").lower() == own_key), None)
    if me is None or not me.get("name"):
        return empty
    own_name = str(me["name"])
    base = base_name(own_name)
    own_root = os.path.normcase(root_of(own_cwd))
    stop: list[dict] = []
    warn: list[dict] = []
    for row in rows:
        name = row.get("name")
        cwd = row.get("cwd")
        if (str(row.get("sessionId") or "").lower() == own_key or not name or not cwd
                or base_name(str(name)) != base or row.get("kind") not in CLASH_KINDS
                or row.get("state") == "stopped" or os.path.normcase(root_of(str(cwd))) != own_root):
            continue
        (stop if is_older(row, me) and stoppable(row) else warn).append(row)
    rename = own_name != base and bool(stop) and not warn
    return {"base": base, "own_name": own_name, "stop": stop, "warn": warn, "rename": rename}


def build_message(base: str, stopped: list[dict], warned: list[dict], renamed: bool, relay8: str | None) -> str | None:
    """One line for the owner. None when nothing clashed."""
    if not stopped and not warned:
        return None
    parts = [f"[caddis] session name {base}: stopped the idle old session {label(r)} (background); "
             "its conversation is kept." for r in stopped]
    if renamed:
        parts.append(f"This session is now {base}.")
    for r in warned:
        how = r.get("status") or r.get("state") or "unknown"
        parts.append(f"[caddis] session name {base} is also used by {label(r)} ({r.get('kind')}, {how}).")
    if warned:
        parts.append(f"Peers that message {base} may reach the wrong session. Close the one you do not use: "
                     "/exit in its window, or ask this session to stop a background one.")
        if relay8:
            parts.append(f"The role relay names {base}@{relay8}.")
    return " ".join(parts)


# ---- once per session: marker, relay, run_claim --------------------------------------------------------------

MARKER_SUFFIX = ".name-claim"
MARKER_MAX_AGE_S = 7 * 24 * 3600
_RELAY_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def _own_cwd(data: dict) -> str:
    return str(data.get("cwd") or os.getcwd())


def marker_path(data: dict) -> str | None:
    """`<root>/.caddis/session-state/<sid>.name-claim`, or None when the repo has no session-state folder."""
    sid = str(data.get("session_id") or "").strip()
    slug = "".join(c for c in sid if c.isascii() and (c.isalnum() or c in "-_"))[:64]
    if not slug:
        return None
    state = os.path.join(_repo_root(_own_cwd(data)), ".caddis", "session-state")
    return os.path.join(state, slug + MARKER_SUFFIX) if os.path.isdir(state) else None


def prune_markers(folder: str, now: float) -> int:
    """Delete name-claim markers older than MARKER_MAX_AGE_S. Returns the count."""
    removed = 0
    try:
        names = os.listdir(folder)
    except OSError:
        return 0
    for name in names:
        if not name.endswith(MARKER_SUFFIX):
            continue
        path = os.path.join(folder, name)
        try:
            if now - os.path.getmtime(path) > MARKER_MAX_AGE_S:
                os.remove(path)
                removed += 1
        except OSError:
            pass
    return removed


def relay_sid8(root: str, base: str) -> str | None:
    """The first 8 characters of the session id that the role relay `.caddis/relay/<base>.md` names."""
    if not _RELAY_NAME.match(base) or base in (".", ".."):
        return None
    try:
        with open(os.path.join(root, ".caddis", "relay", base + ".md"), encoding="utf-8", errors="replace") as fh:
            for _ in range(20):
                line = fh.readline()
                if not line:
                    break
                if line.startswith("session_id:"):
                    value = line.split(":", 1)[1].strip()[:8].lower()
                    return value or None
    except OSError:
        pass
    return None


def run_claim(data: dict, agents: Callable[[], list[dict]], stop: Callable[[str], bool], now: float) -> dict | None:
    """The hook body. Returns the hook output dict, or None when there is nothing to say."""
    marker = marker_path(data)
    if marker is None or os.path.exists(marker):
        return None
    # The marker goes first: a crash or a timeout below must never repeat the check.
    with open(marker, "w", encoding="utf-8"):
        pass
    prune_markers(os.path.dirname(marker), now)
    try:
        rows = agents()
    except Exception:
        return None
    d = decide(str(data.get("session_id") or ""), _own_cwd(data), rows, _repo_root)
    if d["base"] is None:
        return None
    stopped: list[dict] = []
    warned: list[dict] = list(d["warn"])
    for row in d["stop"]:
        (stopped if stop(str(row.get("id") or "")) else warned).append(row)
    renamed = d["rename"] and not warned
    msg = build_message(d["base"], stopped, warned, renamed,
                        relay_sid8(_repo_root(_own_cwd(data)), d["base"]))
    if msg is None:
        return None
    context = msg
    if warned:
        context += " Ids: " + ", ".join(f"{label(r)}={r.get('id')}" for r in warned)
    specific = {"hookEventName": "UserPromptSubmit", "additionalContext": context}
    if renamed:
        specific["sessionTitle"] = d["base"]
    return {"systemMessage": msg, "hookSpecificOutput": specific}


# ---- the real `claude` calls ---------------------------------------------------------------------------------

def _claude() -> str:
    exe = shutil.which("claude")
    if not exe:
        raise OSError("claude is not on PATH")
    return exe


def _agents() -> list[dict]:
    proc = subprocess.run([_claude(), "agents", "--json"], capture_output=True, text=True, encoding="utf-8",
                          timeout=8, **NO_WINDOW_KW)
    if proc.returncode != 0:
        raise ValueError(f"claude agents exited {proc.returncode}")
    rows = json.loads(proc.stdout)
    if not isinstance(rows, list):
        raise ValueError("claude agents --json did not return a list")
    return [r for r in rows if isinstance(r, dict)]


def _stop(short_id: str) -> bool:
    if not short_id:
        return False
    try:
        # The output is not used: no decoding, so a byte the console code page cannot decode never turns a
        # stop that worked into a False.
        return subprocess.run([_claude(), "stop", short_id], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=8, **NO_WINDOW_KW).returncode == 0
    except Exception:
        return False


def main() -> None:
    try:
        if os.environ.get("CADDIS_HEADLESS", "").strip().lower() in ("1", "true", "yes", "on"):
            return
        if _repo_root is None:
            return
        # Claude Code sends UTF-8. A plain sys.stdin.read() uses the Windows code page (cp1252), and a prompt
        # with a character such as "⏳" would then fail to decode and skip the check.
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace") or "{}")
        if not isinstance(data, dict) or data.get("hook_event_name") != "UserPromptSubmit":
            return
        out = run_claim(data, _agents, _stop, time.time())
        if out is not None:
            print(json.dumps(out))
    except Exception:
        pass


if __name__ == "__main__":
    main()
    sys.exit(0)
