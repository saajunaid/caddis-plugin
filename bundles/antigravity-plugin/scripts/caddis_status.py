"""One vocabulary for a plan Tracker's Status cell, for every caller (todo, tidy, roadmap, runner, hub).

Owner decisions: "pending" anywhere is never done (2026-09-27); the check marks below count as done (2026-10-26).
"""

from __future__ import annotations

import re

DONE_WORDS = ("done", "merged")
DONE_MARKS = ("✅", "☑", "✔", "✓")
OPEN_MARKS = ("☐",)
BLOCKED_WORDS = ("blocked", "halt", "waiting")
IN_PROGRESS_WORDS = ("in progress", "in-progress", "active", "building", "built", "⏳")
STATES = ("todo", "in-progress", "blocked", "done", "moved")

_DONE_WORD = re.compile(r"^(?:%s)\b" % "|".join(DONE_WORDS))


def _clean(cell: str) -> str:
    text = (cell or "").strip().strip("*").strip()
    while text.startswith(OPEN_MARKS):
        text = text[1:].lstrip()
    return text.lower()


def status_state(cell: str, fallback: str = "todo") -> str:
    """todo | in-progress | blocked | done | moved. `fallback` when the cell names no state (empty, a bare open box,
    "not started")."""
    text = _clean(cell)
    if "pending" in text:
        return "in-progress"
    if text.startswith("moved") or "moved" in text.split(" - ", 1)[0]:
        return "moved"
    if _DONE_WORD.match(text) or text.startswith(DONE_MARKS):
        return "done"
    if text.startswith(BLOCKED_WORDS):
        return "blocked"
    if text.startswith(IN_PROGRESS_WORDS):
        return "in-progress"
    return fallback


def is_done(cell: str) -> bool:
    return status_state(cell) == "done"
