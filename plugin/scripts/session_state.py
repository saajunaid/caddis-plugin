"""Reconstruct "what were we doing" from a live transcript, for the Stop hook.

WHY THIS EXISTS. The pain it solves is an abrupt VS Code / CLI close, after which the
operator cannot remember where they were. The data was never lost — Claude Code writes the
transcript JSONL live, so nothing already exchanged is gone, and `claude --continue` reopens
it. What is lost is the INDEX: nobody reads back an 8 MB JSONL to find out what they were in
the middle of.

So this does not persist anything new. It reads what is already on disk and renders the
small part a human needs.

WHY IT HANGS OFF `Stop` AND NOT A COMMAND. A command (`/handoff`, a hypothetical `/todo`)
has to be remembered and run — and the failure mode is precisely that there was no chance to
run anything. `Stop` fires at the end of EVERY assistant turn, so the file is current without
anyone deciding to make it current. The residual gap is honest and small: a process killed
mid-turn loses that one turn, not the session.

MEASURED, NOT ASSUMED (2026-08-27, against real transcripts in ~/.claude/projects). The task
tools do not carry their own ids on the way in, so state has to be correlated:

  - `TaskCreate` input carries {subject, description, activeForm} and NO id.
  - Its `tool_result` carries the id, as the text "Task #3 created successfully: <subject>".
  - `TaskUpdate` input carries {task_id, status, description?} — incremental, not a snapshot.
  - `TodoWrite` input carries the WHOLE list every time, so the last one simply wins.

Both shapes are handled because both appear in real transcripts (274 TaskCreate / 465
TaskUpdate / 360 TodoWrite across this machine's projects).

Every function here is defensive to the point of dullness. This runs on every turn of every
session; a traceback out of it would be worse than the problem it solves.
"""
from __future__ import annotations

import json
import os
import re
import tempfile


def _norm(path: str) -> str:
    """Compare paths case- and separator-insensitively.

    On Windows `git rev-parse --show-toplevel` returns forward slashes while the Edit/Write
    tools record backslashes for the same directory. Comparing them raw silently fails, which
    is why every file first rendered as an absolute path.
    """
    return str(path or "").replace("\\", "/").rstrip("/").lower()

# The id a TaskCreate was assigned is only ever stated in its result text.
_TASK_ID_RE = re.compile(r"Task #(\d+)", re.I)

# Turn-level noise that is not a real user request. A Stop hook that surfaced one of these as
# "what you were doing" would be worse than surfacing nothing.
_COMMAND_BODY_RE = re.compile(r"^#\s*/[a-z0-9][\w:-]*", re.I)

_NOISE_PREFIXES = (
    "<system-reminder",
    "<command-name",
    "<local-command",
    "[HARNESS]",
    "Caveat: The messages below",
)

_STATUS_ORDER = {"in_progress": 0, "pending": 1, "completed": 2}
_MAX_TASKS = 20
_MAX_FILES = 12
_REQUEST_CHARS = 400


def _is_scratch(path: str) -> bool:
    """True for a file under the OS temp directory.

    Scratch files are written to be thrown away — a patch script, an intermediate dump. Listing
    them as "files changed this session" buries the two or three that a person actually needs
    to look at. Deliberately narrow: only the temp root, so nothing inside a real project is
    ever hidden.
    """
    try:
        temp = _norm(tempfile.gettempdir())
        return bool(temp) and _norm(path).startswith(temp + "/")
    except Exception:
        return False


def _content_blocks(event):
    """Yield the content blocks of a transcript event, whatever shape it arrived in."""
    message = event.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def _text_of(block) -> str:
    """A tool_result's content is sometimes a string, sometimes a list of blocks."""
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return " ".join(parts)
    return ""


def _user_text(event) -> str:
    """Plain text of a user turn, or '' if this is a tool result or harness noise."""
    message = event.get("message")
    if not isinstance(message, dict) or message.get("role") != "user":
        return ""
    content = message.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        # A turn carrying ANY tool_result is the harness replying to itself, not the operator.
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                return ""
        text = " ".join(
            b["text"] for b in content
            if isinstance(b, dict) and isinstance(b.get("text"), str)
        )
    else:
        return ""
    text = text.strip()
    if not text or text.startswith(_NOISE_PREFIXES):
        return ""
    if _COMMAND_BODY_RE.match(text):
        return ""  # the expanded body of a slash command, not something the operator typed
    return text


def extract_state(transcript_path: str) -> dict:
    """Single forward pass over the transcript. Returns {} when there is nothing to say.

    Forward, not reversed: task state is built by correlation (create -> id -> updates), so
    the order matters and a tail-only read could see an update whose create it never saw.
    """
    empty: dict = {"tasks": [], "todos": [], "last_request": "", "files": [], "branch": ""}
    if not transcript_path or not os.path.isfile(transcript_path):
        return empty

    pending_creates: dict[str, dict] = {}   # tool_use id -> task, awaiting its result
    tasks: dict[str, dict] = {}             # "3" -> task
    order: list[str] = []
    todos: list[dict] = []
    last_request = ""
    files: list[str] = []
    branch = ""

    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except Exception:
                    continue  # a torn final line is expected if the process died mid-write
                if not isinstance(event, dict):
                    continue

                if isinstance(event.get("gitBranch"), str) and event["gitBranch"]:
                    branch = event["gitBranch"]

                text = _user_text(event)
                if text:
                    last_request = text

                for block in _content_blocks(event):
                    kind = block.get("type")

                    if kind == "tool_use":
                        name = block.get("name")
                        args = block.get("input")
                        if not isinstance(args, dict):
                            continue

                        if name == "TaskCreate":
                            subject = str(
                                args.get("subject") or args.get("content") or ""
                            ).strip()
                            if subject:
                                pending_creates[str(block.get("id"))] = {
                                    "subject": subject,
                                    "status": "pending",
                                    "note": str(args.get("description") or "").strip(),
                                }

                        elif name == "TaskUpdate":
                            # Both spellings occur in real transcripts on this machine:
                            # `taskId` and `task_id`. Accepting one silently produced a task
                            # list where every entry read "pending" — worse than no list, since
                            # it looks authoritative. Measured, not assumed.
                            task_id = str(
                                args.get("taskId") or args.get("task_id") or ""
                            ).strip()
                            task = tasks.get(task_id)
                            if task:
                                status = str(args.get("status") or "").strip()
                                if status:
                                    task["status"] = status
                                note = str(args.get("description") or "").strip()
                                if note:
                                    task["note"] = note

                        elif name == "TodoWrite":
                            items = args.get("todos")
                            if isinstance(items, list):
                                todos = [t for t in items if isinstance(t, dict)]

                        elif name in ("Edit", "Write", "NotebookEdit"):
                            path = args.get("file_path") or args.get("notebook_path")
                            if isinstance(path, str) and path and not _is_scratch(path):
                                if path in files:
                                    files.remove(path)   # keep most-recent-last, no duplicates
                                files.append(path)

                    elif kind == "tool_result":
                        created = pending_creates.pop(str(block.get("tool_use_id")), None)
                        if created:
                            match = _TASK_ID_RE.search(_text_of(block))
                            if match:
                                task_id = match.group(1)
                                tasks[task_id] = created
                                order.append(task_id)
    except Exception:
        return empty

    return {
        "tasks": [dict(tasks[i], id=i) for i in order if i in tasks],
        "todos": todos,
        "last_request": last_request,
        "files": files,
        "branch": branch,
    }


def _rank(task) -> tuple:
    return (_STATUS_ORDER.get(str(task.get("status") or ""), 3), int(task.get("id") or 0))


def _trim(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def render(state: dict, meta: dict) -> str:
    """Render the state as short markdown. Written for a human reading it cold."""
    lines = [
        "# Session state — auto-captured",
        "",
        "Written by the caddis `Stop` hook at the end of every assistant turn. **Do not edit "
        "by hand** — the next turn overwrites it.",
        "",
        "This is a recovery aid, not a record. The full conversation is already on disk and "
        "nothing was lost; run **`claude --continue`** in this folder to reopen it exactly, "
        "or `claude --resume` to pick an older session.",
        "",
    ]

    updated = meta.get("updated") or ""
    session = meta.get("session") or ""
    branch = meta.get("branch") or ""
    facts = []
    if updated:
        facts.append("**Updated:** " + updated)
    if branch:
        facts.append("**Branch:** " + branch)
    if session:
        facts.append("**Session:** `" + session + "`")
    if facts:
        lines += [" · ".join(facts), ""]

    request = state.get("last_request") or ""
    if request:
        lines += ["## Last thing you asked", "", "> " + _trim(request, _REQUEST_CHARS), ""]

    tasks = sorted(state.get("tasks") or [], key=_rank)[:_MAX_TASKS]
    if tasks:
        lines += ["## Tasks", "", "| # | Status | Task |", "|---|---|---|"]
        for task in tasks:
            status = str(task.get("status") or "pending")
            mark = {"in_progress": "**IN PROGRESS**", "completed": "done"}.get(status, status)
            lines.append(
                "| %s | %s | %s |" % (task.get("id", "?"), mark, _trim(task.get("subject"), 90))
            )
        lines.append("")
        active = [t for t in tasks if t.get("status") == "in_progress" and t.get("note")]
        for task in active[:2]:
            lines += ["**Task %s note:** %s" % (task.get("id"), _trim(task.get("note"), 300)), ""]

    todos = state.get("todos") or []
    if todos:
        lines += ["## Todo list", ""]
        for item in todos[:_MAX_TASKS]:
            status = str(item.get("status") or "pending")
            box = "[x]" if status == "completed" else ("[>]" if status == "in_progress" else "[ ]")
            lines.append("- %s %s" % (box, _trim(item.get("content") or item.get("subject"), 100)))
        lines.append("")

    files = list(reversed(state.get("files") or []))[:_MAX_FILES]
    if files:
        lines += ["## Files changed this session", "", "Most recent first.", ""]
        root = _norm(meta.get("root") or "")
        for path in files:
            shown = str(path).replace("\\", "/")
            if root and _norm(path).startswith(root + "/"):
                shown = shown[len(root) + 1:]
            lines.append("- `%s`" % shown)
        lines.append("")

    if len(lines) <= 8:
        return ""  # nothing worth writing; better no file than an empty ceremonial one
    return "\n".join(lines).rstrip() + "\n"


def write_state(path: str, text: str) -> bool:
    """Atomic write. A crash mid-write must not leave a truncated recovery file — that
    would be the one moment the file is read and the one moment it is corrupt."""
    if not text:
        return False
    try:
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        handle, tmp = tempfile.mkstemp(dir=directory, prefix=".session-state-", suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            raise
        return True
    except Exception:
        return False
