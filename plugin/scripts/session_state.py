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

BOUNDED, SINCE PHASE 13 (2026-09-27). The hook reads only the last `TAIL_BYTES` of the
transcript. A task created before that window and updated inside it would otherwise be lost:
`TaskUpdate` carries only the number, and its result reads just "Updated task #7 status"
(measured on a live transcript). So each render carries the number -> subject map, the task
metadata id and the few other facts a tail can miss in one hidden line above `**Updated:**`, and
the next Stop starts from it. inject_relay.py drops everything above `**Updated:**`, so the
carry never reaches a model's context.

Every function here is defensive to the point of dullness. This runs on every turn of every
session; a traceback out of it would be worse than the problem it solves.

Run as a script, it also serves `/handoff` (see `main`): `usage` appends this session's token
and skill record to `usage-log.jsonl`, and `prune` keeps the state folder small. Both used to
run inside the Stop hook on every turn.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone


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

# Measured, not guessed: these are the shapes that actually appear as user-role turns in the
# transcripts on this machine, found by counting the first 60 characters of every such turn
# across the six most recent sessions. Each one is the harness talking, not the operator.
_NOISE_PREFIXES = (
    "<system-reminder",
    "<command-name",
    "<local-command",              # includes <local-command-caveat>
    "[HARNESS]",
    "Caveat: The messages below",
    "[Request interrupted by user]",
    "Another Claude session sent a message",   # cross-session relay, not this operator
    "This session is being continued from",    # the compaction preamble
    "Launching skill:",
)

# "Skill /caddis:handoff is already loaded above; instructions unchanged." — a re-invocation
# notice. Matched as a pattern rather than a prefix so it cannot swallow a real message that
# happens to start with the word "Skill".
_SKILL_NOTICE_RE = re.compile(r"^Skill\s+/\S+\s+is already loaded\b", re.I)

_STATUS_ORDER = {"in_progress": 0, "pending": 1, "completed": 2}
_MAX_TASKS = 20
_MAX_FILES = 12
_REQUEST_CHARS = 400

# How much of the transcript the Stop hook reads. Big enough to hold several ordinary turns,
# small enough that an 8 MB transcript costs the same as a 2 MB one.
TAIL_BYTES = 2 * 1024 * 1024
# How many state files /handoff keeps. They are recovery aids with a short useful life; the
# transcript is the real record.
STATE_KEEP = 8

_CARRY_RE = re.compile(r"^<!-- caddis-carry: (\{.*\}) -->$", re.M)
_CARRY_TASKS = 200
_CARRY_SUBJECT = 200


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
    if _SKILL_NOTICE_RE.match(text):
        return ""  # "Skill /x is already loaded" — the harness, not the operator
    return text


def _tail_lines(transcript_path: str, max_bytes: int):
    """Yield decoded lines from the last `max_bytes` of the file.

    Binary, because a seek can land inside a multi-byte character. When the window starts
    mid-file, the partial line it lands in is dropped: seek one byte early and discard through
    the next newline, so a window that starts exactly on a line boundary loses nothing.
    """
    with open(transcript_path, "rb") as fh:
        size = os.fstat(fh.fileno()).st_size
        if max_bytes and size > max_bytes:
            fh.seek(size - max_bytes - 1)
            fh.readline()
        for raw in fh:
            yield raw.decode("utf-8", errors="replace")


def read_carry(path: str) -> dict:
    """The facts a previous render carried forward, or {} when there are none."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            match = _CARRY_RE.search(fh.read())
        data = json.loads(match.group(1)) if match else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _from_carry(carry) -> tuple:
    """(tasks, order, todos, files, branch) seeded from a carry, each validated."""
    tasks: dict[str, dict] = {}
    order: list[str] = []
    todos: list[dict] = []
    files: list[str] = []
    branch = ""
    if not isinstance(carry, dict):
        return tasks, order, todos, files, branch
    for row in carry.get("tasks") or []:
        # [id, subject, status, caddis_id, note]; the note is kept only for in-progress tasks,
        # the only ones render() shows a note for.
        if not (isinstance(row, list) and len(row) in (4, 5)
                and all(isinstance(v, str) for v in row)):
            continue
        task_id, subject, status, caddis_id = row[:4]
        note = row[4] if len(row) == 5 else ""
        if task_id and subject and task_id not in tasks:
            tasks[task_id] = {"subject": subject, "status": status or "pending", "note": note,
                              "caddis_id": _caddis_id({"id": caddis_id})}
            order.append(task_id)
    todos = [t for t in carry.get("todos") or [] if isinstance(t, dict)]
    files = [f for f in carry.get("files") or [] if isinstance(f, str) and f]
    branch = carry.get("branch") if isinstance(carry.get("branch"), str) else ""
    return tasks, order, todos, files, branch


def extract_state(transcript_path: str, max_bytes: int = TAIL_BYTES, carry=None) -> dict:
    """Single forward pass over the transcript tail. Empty lists when there is nothing to say.

    Forward, not reversed: task state is built by correlation (create -> id -> updates), so
    the order matters. A create that fell out of the tail is recovered from `carry`, the map
    the previous Stop wrote into the state file (see `read_carry`).
    """
    empty: dict = {"tasks": [], "todos": [], "last_request": "", "files": [], "branch": ""}
    if not transcript_path or not os.path.isfile(transcript_path):
        # Nothing new to say. Writing the carry alone would replace a fuller previous file.
        return empty

    tasks, order, todos, files, branch = _from_carry(carry)
    pending_creates: dict[str, dict] = {}   # tool_use id -> task, awaiting its result
    last_request = ""

    try:
        for line in _tail_lines(transcript_path, max_bytes):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue  # a torn line: the process died mid-write, or the tail cut it
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
                                "caddis_id": _caddis_id(args.get("metadata")),
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
                            caddis_id = _caddis_id(args.get("metadata"))
                            if caddis_id:
                                task["caddis_id"] = caddis_id

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
                            if task_id not in tasks:
                                order.append(task_id)
                            tasks[task_id] = created
    except Exception:
        return empty

    return {
        "tasks": [dict(tasks[i], id=i) for i in order if i in tasks],
        "todos": todos,
        "last_request": last_request,
        "files": files,
        "branch": branch,
    }


def _carry_line(state: dict) -> str:
    """One hidden line holding what the next tail read may not see again.

    `<` and `>` are escaped so no subject can close the comment early.
    """
    tasks = state.get("tasks") or []
    if len(tasks) > _CARRY_TASKS:
        seeded = [t for t in tasks[:-_CARRY_TASKS] if t.get("caddis_id")]
        tasks = seeded + tasks[-_CARRY_TASKS:]
    carry = {
        "tasks": [[str(t.get("id") or ""), str(t.get("subject") or "")[:_CARRY_SUBJECT],
                   str(t.get("status") or ""), str(t.get("caddis_id") or ""),
                   str(t.get("note") or "")[:300] if t.get("status") == "in_progress" else ""]
                  for t in tasks],
        "todos": [{"content": str(t.get("content") or t.get("subject") or "")[:_CARRY_SUBJECT],
                   "status": str(t.get("status") or "")}
                  for t in (state.get("todos") or [])[:_MAX_TASKS]],
        "files": list(state.get("files") or [])[-_MAX_FILES:],
        "branch": str(state.get("branch") or ""),
    }
    blob = json.dumps(carry, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e")
    return "<!-- caddis-carry: %s -->" % blob


def _rank(task) -> tuple:
    return (_STATUS_ORDER.get(str(task.get("status") or ""), 3), int(task.get("id") or 0))


def _caddis_id(metadata: object) -> str:
    """The open-work id a seeded task carries in its metadata ("phase:7" or a UUID), else ""."""
    if not isinstance(metadata, dict):
        return ""
    value = str(metadata.get("id") or "").strip()
    return value if re.fullmatch(r"[A-Za-z0-9:-]{1,64}", value) else ""


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
    preamble_end = len(lines)

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

    ranked = sorted(state.get("tasks") or [], key=_rank)
    # Done tasks rank last, so the cap trims them first; seeded ones (with an open-work id)
    # are kept anyway, or /handoff's reconcile would never see them close.
    tasks = ranked[:_MAX_TASKS] + [t for t in ranked[_MAX_TASKS:] if t.get("caddis_id")]
    if tasks:
        lines += ["## Tasks", "", "| # | Status | Task |", "|---|---|---|"]
        for task in tasks:
            status = str(task.get("status") or "pending")
            mark = {"in_progress": "**IN PROGRESS**", "completed": "done"}.get(status, status)
            # The open-work id rides after the trimmed subject so trimming never cuts it:
            # /handoff's `caddis_todo.py reconcile` closes ad-hoc to-dos by this marker only.
            marker = ""
            if task.get("caddis_id"):
                marker = ' <!-- caddis: {"id": "%s"} -->' % task["caddis_id"]
            lines.append(
                "| %s | %s | %s%s |" % (task.get("id", "?"), mark, _trim(task.get("subject"), 90), marker)
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
    # Above the facts line, so it sits in the preamble inject_relay.py never surfaces.
    lines[preamble_end:preamble_end] = [_carry_line(state), ""]
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


# ── /handoff: usage record and state-folder pruning ──────────────────────────────────────
# Moved out of the Stop hook in Phase 13 (2026-09-27). The hook used to parse the WHOLE
# transcript twice more on every turn and append a cumulative record each time; /usage-review
# already kept only the last record per session, so all but one were waste. /handoff runs this
# once, with the whole transcript.

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
    question (Phase 12) was unanswerable from evidence. This recovers that identity where the
    per-session record is born (the Stop hook until Phase 13, /handoff since), so the log
    becomes self-describing and survives transcript compaction.

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


def find_repo_root(start: str) -> str:
    """The nearest folder at or above `start` holding `.git` (a folder, or a worktree's file).

    State anchors to the repo root so a session launched from a subfolder writes to the one
    shared `.caddis/` instead of scattering one into every cwd. No git subprocess: the Stop
    hook runs this every turn. Falls back to `start`.
    """
    try:
        current = os.path.abspath(start)
        while True:
            if os.path.exists(os.path.join(current, ".git")):
                return current
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
    except Exception:
        pass
    return start


def _artifact_dir(root: str) -> str:
    try:
        from claudster_config import artifact_root
        return str(artifact_root(root))
    except Exception:
        return os.path.join(str(root), ".caddis")


def find_transcript(session_id: str) -> str:
    """`<claude config>/projects/*/<session-id>.jsonl`, or "" when there is none."""
    slug = "".join(c for c in str(session_id or "") if c.isalnum() or c in "-_")[:64]
    if not slug:
        return ""
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    matches = glob.glob(os.path.join(glob.escape(base), "projects", "*", slug + ".jsonl"))
    return max(matches, key=os.path.getmtime) if matches else ""


def record_usage(transcript_path: str, session_id: str, root: str) -> dict | None:
    """Append one usage record for the session to `<root>/.caddis/usage-log.jsonl`."""
    u = _summarise(transcript_path)
    # V15/V16: record which skills/commands fired (names only) alongside the token totals, so
    # the pruning question is answerable from the log instead of taste. Written whenever there
    # is token data OR identity: pruning evidence must not depend on token accounting.
    skills, commands, skills_read = _extract_identity(transcript_path)
    if not (u or skills or commands or skills_read):
        return None
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session": session_id or "",
        "input": u["input"] if u else 0,
        "output": u["output"] if u else 0,
        "cache_write": u["cache_write"] if u else 0,
        "cache_read": u["cache_read"] if u else 0,
        "est_cost_usd": u["est_cost_usd"] if u else 0.0,
        "models": u["models"] if u else [],
        "skills": sorted(skills),
        "commands": sorted(commands),
        # V16: skills the model READ because something pointed it there, as opposed to skills
        # it CHOSE via the Skill tool. Kept separate on purpose — that difference is the point.
        "skills_read": sorted(skills_read),
    }
    art = _artifact_dir(root)
    os.makedirs(art, exist_ok=True)
    with open(os.path.join(art, "usage-log.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    rec["_digest"] = u
    return rec


def prune_session_states(directory: str, keep: int = STATE_KEEP) -> int:
    """Keep the newest `keep` state files by mtime. Returns how many were removed."""
    removed = 0
    try:
        entries = []
        for name in os.listdir(directory):
            if not name.endswith(".md"):
                continue  # never touch the .session-state-*.tmp atomic-write scratch files
            path = os.path.join(directory, name)
            try:
                entries.append((os.path.getmtime(path), path))
            except OSError:
                continue
        for _mtime, path in sorted(entries, reverse=True)[keep:]:
            try:
                os.unlink(path)
                removed += 1
            except OSError:
                pass
            try:
                os.unlink(path[:-3] + ".ended")  # the SessionEnd marker goes with its state file
            except OSError:
                pass
    except Exception:
        pass
    return removed


def main(argv=None) -> int:
    """`usage` and `prune`, for /handoff. Never fails the handoff: always exits 0 once parsed."""
    parser = argparse.ArgumentParser(prog="session_state.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    usage_p = sub.add_parser("usage", help="append this session's usage record to usage-log.jsonl")
    usage_p.add_argument("--session-id", required=True)
    usage_p.add_argument("--transcript", default="", help="default: found by session id")
    usage_p.add_argument("--root", default="", help="default: the repo holding the current folder")
    prune_p = sub.add_parser("prune", help="keep the newest session-state files")
    prune_p.add_argument("--root", default="")
    prune_p.add_argument("--keep", type=int, default=STATE_KEEP)
    args = parser.parse_args(argv)
    root = args.root or find_repo_root(os.getcwd())
    try:
        if args.cmd == "usage":
            transcript = args.transcript or find_transcript(args.session_id)
            if not transcript or not os.path.isfile(transcript):
                print("[USAGE] no transcript found for session %s; usage not recorded." % args.session_id)
                return 0
            rec = record_usage(transcript, args.session_id, root)
            u = rec.get("_digest") if rec else None
            if u:
                print(
                    f"[USAGE] this session ~ in {_fmt(u['input'])} · out {_fmt(u['output'])} · "
                    f"cache {_fmt(u['cache_write'] + u['cache_read'])} "
                    f"({_fmt(u['cache_read'])} read) · est. ${u['est_cost_usd']:.2f} "
                    f"(estimate — edit rates in session_state.py)"
                )
            print("[USAGE] %s" % ("recorded in usage-log.jsonl." if rec else "nothing to record."))
        else:
            removed = prune_session_states(os.path.join(_artifact_dir(root), "session-state"),
                                           max(args.keep, 1))
            print("[STATE] pruned %d old session-state file(s)." % removed)
    except Exception as exc:  # a handoff step must degrade, never block
        print("[%s] skipped: %s" % (args.cmd.upper(), type(exc).__name__))
    return 0


if __name__ == "__main__":
    _reconfig = getattr(sys.stdout, "reconfigure", None)
    if _reconfig:
        try:
            _reconfig(encoding="utf-8")
        except Exception:
            pass
    sys.exit(main())
