"""Mark a session as waiting for the owner, and clear the mark when the owner answers.

Roadmap-page Phase 2 (`.caddis/plans/roadmap-page.md`): the local roadmap page lists every session that waits for
input, also sessions started by hand.

- `Notification` (Claude Code sends it when a permission prompt has waited about 6 s, or about 60 s after Claude
  finished a turn with no typing since, or for an MCP question): write `.caddis/session-state/<sid>.waiting` as JSON
  `{utc, kind, message, cwd}`. Other notification types (auth_success, agent_completed, quota_*) are ignored.
- `UserPromptSubmit` (the owner typed), `Stop` (the turn ended) and `SessionEnd`: delete `<sid>.waiting`.
- A session in a git worktree writes to the MAIN checkout's session-state (the `.git` file names it), so the
  main checkout's page sees it; a fresh worktree has no `.caddis/session-state` of its own.
  Accepted limit: after the owner approves a permission prompt, the mark stays until that turn ends (clearing on
  every PostToolUse would start a process per tool call).

Rules for a hook that runs in every session: stdlib only, no network in the hook itself, prints nothing (UserPromptSubmit stdout would
become context), never raises, always exits 0. Headless runs are skipped: they never wait for input.

Refresh (roadmap-page Phase 3): when a mark was written or removed AND the checkout has `.caddis/roadmaps/`, start
`caddis_roadmap.py render --all --no-fetch` in the background and do not wait for it, so the page's "Waiting for
you" stays current and no prompt is slowed. A prompt with no mark to clear starts nothing.
Robustness #8: N sessions must not start N renders. The hook starts one only when the repo's debounce stamp
(`.caddis/session-state/.roadmap-render.stamp`) is older than 60 s; the render itself takes a non-blocking per-repo
lock and exits at once when another render holds it; `--no-fetch` reads the origin refs the checkout already has, so
no hook ever runs `git fetch` against a peer's pull or push. The first mark change inside the 60 s window creates
`.roadmap-render.pending` and starts ONE follow-up render with `--delay` (it waits for the window's end); later
changes in the window start nothing. A render that runs when the pending file appears renders once more at its end,
so the last change always reaches the page: at most two starts per repo per minute.
"""
import json
import os
import subprocess
import sys
import time
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
RENDER_DEBOUNCE_S = 60
STAMP_NAME = ".roadmap-render.stamp"
PENDING_NAME = ".roadmap-render.pending"  # caddis_roadmap.py render reads it: one more render at its end


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
        _render_detached(marker)
    elif event in CLEAR_EVENTS:
        try:
            os.remove(marker)
        except FileNotFoundError:
            return  # nothing changed: start nothing
        _render_detached(marker)


def _roadmap_script() -> str | None:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for cand in (os.path.join(here, "scripts", "caddis_roadmap.py"),  # the plugin: hooks/ and scripts/ side by side
                 os.path.join(os.path.dirname(here), "scripts", "caddis_roadmap.py")):  # the source checkout
        if os.path.isfile(cand):
            return cand
    return None


def _render_detached(marker: str) -> None:
    """Re-render every roadmap page of this checkout in the background; never waits, never fails."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(marker)))  # <root>/.caddis/session-state/<sid>.waiting
    script = _roadmap_script()
    if script is None or not os.path.isdir(os.path.join(root, ".caddis", "roadmaps")):
        return
    state = os.path.dirname(marker)
    stamp = os.path.join(state, STAMP_NAME)
    try:
        age = time.time() - os.path.getmtime(stamp)
    except OSError:
        age = None
    if age is not None and 0 <= age < RENDER_DEBOUNCE_S:
        # A render started under a minute ago. Queue ONE follow-up for the end of the window, so this change still
        # reaches the page: the first hook to create the pending file starts it; the others start nothing.
        pending = os.path.join(state, PENDING_NAME)
        try:
            os.close(os.open(pending, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except OSError:
            return  # already queued (or a running render will render once more)
        if not _start(script, root, ["--delay", str(int(RENDER_DEBOUNCE_S - age) + 1)]):
            try:
                os.remove(pending)
            except OSError:
                pass
        return
    if _start(script, root, []):
        _touch(stamp)  # only after the start worked: a failed start must not hold the next one back


def _start(script: str, root: str, extra: list) -> bool:
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "cwd": root,
              "env": {**os.environ, "CADDIS_HEADLESS": "1"}}
    # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP: a hidden console that the render's git.exe calls share.
    # Never DETACHED_PROCESS: Windows then ignores CREATE_NO_WINDOW, the render has no console, and every
    # git.exe it starts opens its own visible window (owner report, 18 Oct).
    flags = (0x08000000 | 0x00000200) if os.name == "nt" else 0
    if os.name != "nt":
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen([sys.executable, script, "render", "--all", "--no-fetch", *extra, "--root", root],
                         creationflags=flags, **kwargs)
    except (OSError, ValueError):
        return False
    return True


def _touch(path: str) -> None:
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(str(os.getpid()))
    except OSError:
        pass  # a debounce file is a convenience: never fail the hook


def main() -> None:
    try:
        if any(str(os.environ.get(n, "")).strip() for n in ("CADDIS_HEADLESS",)):
            return
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
        if isinstance(data, dict):
            handle(data)
    except Exception:
        pass  # a mark for a page must never break a session


if __name__ == "__main__":
    main()
