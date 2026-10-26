"""Mark a session as waiting for the owner, and clear the mark when the owner answers.

Readers of the marks: `claude-harness/scripts/session_state.py` (it removes a mark with its session) and the review
lane's tests. The hub does not read them: it gets live sessions from `claude agents`. H6.9 retired the old roadmap
page that used to show them.

- `Notification` (Claude Code sends it when a permission prompt has waited about 6 s, or about 60 s after Claude
  finished a turn with no typing since, or for an MCP question): write `.caddis/session-state/<sid>.waiting` as JSON
  `{utc, kind, message, cwd}`. Other notification types (auth_success, agent_completed, quota_*) are ignored.
- `UserPromptSubmit` (the owner typed), `Stop` (the turn ended) and `SessionEnd`: delete `<sid>.waiting`.
- A session in a git worktree writes to the MAIN checkout's session-state (the `.git` file names it), so all
  marks of a repo are in one folder; a fresh worktree has no `.caddis/session-state` of its own.
  Accepted limit: after the owner approves a permission prompt, the mark stays until that turn ends (clearing on
  every PostToolUse would start a process per tool call).

Rules for a hook that runs in every session: stdlib only, no network in the hook itself, prints nothing (UserPromptSubmit stdout would
become context), never raises, always exits 0. Headless runs are skipped: they never wait for input.
"""
import json
import os
import sys
from datetime import datetime, timezone

WAITING_KINDS = {
    "permission_prompt": "needs permission",
    "elicitation_dialog": "asks a question",
    "elicitation_url_dialog": "asks a question",
    "agent_needs_input": "needs input",
    "idle_prompt": "idle, waiting for your next message",
}
CLEAR_EVENTS = ("UserPromptSubmit", "Stop", "SessionEnd")
MESSAGE_MAX = 300


def _repo_root(start: str) -> str:
    """The main checkout of the nearest repo: the folder holding `.git`; for a worktree (`.git` is a file with
    `gitdir: <main>/.git/worktrees/<name>`) the main checkout. Pure file reads, no subprocess."""
    path = os.path.abspath(start)
    while True:
        dot_git = os.path.join(path, ".git")
        if os.path.isfile(dot_git):
            try:
                with open(dot_git, encoding="utf-8") as fh:
                    line = fh.readline().strip()
                gitdir = line.split(":", 1)[1].strip() if line.startswith("gitdir:") else ""
                parts = os.path.normpath(os.path.join(path, gitdir)).split(os.sep)
                if "worktrees" in parts and parts[parts.index("worktrees") - 1] == ".git":
                    return os.sep.join(parts[:parts.index("worktrees") - 1]) or path
            except (OSError, IndexError, ValueError):
                pass
            return path
        if os.path.isdir(dot_git):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            return os.path.abspath(start)
        path = parent


def _marker(data: dict) -> str | None:
    sid = str(data.get("session_id", "") or "").strip()
    slug = "".join(c for c in sid if c.isalnum() or c in "-_")[:64]
    if not slug:
        return None
    root = _repo_root(str(data.get("cwd") or os.getcwd()))
    state = os.path.join(root, ".caddis", "session-state")
    return os.path.join(state, slug + ".waiting") if os.path.isdir(state) else None


def handle(data: dict) -> None:
    event = str(data.get("hook_event_name", "") or "")
    marker = _marker(data)
    if marker is None:
        return
    if event == "Notification":
        kind = WAITING_KINDS.get(str(data.get("notification_type", "") or ""))
        if kind is None:
            return
        record = {"utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "kind": kind,
                  "message": str(data.get("message", "") or "")[:MESSAGE_MAX], "cwd": str(data.get("cwd", "") or "")}
        tmp = f"{marker}.{os.getpid()}.tmp"  # async hooks may overlap: one scratch file each
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(record, fh)
        os.replace(tmp, marker)
    elif event in CLEAR_EVENTS:
        try:
            os.remove(marker)
        except FileNotFoundError:
            return


def main() -> None:
    try:
        if any(str(os.environ.get(n, "")).strip() for n in ("CADDIS_HEADLESS",)):
            return
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
        if isinstance(data, dict):
            handle(data)
    except Exception:
        pass  # a waiting mark must never break a session


if __name__ == "__main__":
    main()
