"""Read the simple frontmatter shapes used by caddis artifacts.

This is intentionally a small reader, not a YAML implementation.
"""

from __future__ import annotations

import fnmatch
import re
import tomllib
from pathlib import Path


# Single source of truth for allowed document types.
# .github/instructions/document-frontmatter.instructions.md must list the same set.
ALLOWED_TYPES: set[str] = {
    "plan",
    "prd",
    "adr",
    "design",
    "runbook",
    "handoff",
    "analysis",
    "review",
    "prompt",
    "parking-lot",
    "rca",
    "todo",
    "relay",
    "comms",
    "reference",
    "note",
    "phase-report",
    "implement-review",
    "phase-verdict",
    "hub-spawn",
    "advisory-context",
    "phase-prompt",
}


def _header_lines(text: str) -> list[str] | None:
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0] != "---":
        return None
    try:
        end = lines.index("---", 1)
    except ValueError:
        return None
    return lines[1:end]


def _value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def parse(text: str) -> dict:
    """Read top-level scalars and one level of indented maps or lists."""
    lines = _header_lines(text)
    if lines is None:
        return {}

    out: dict = {}
    parent: str | None = None
    child_indent: int | None = None
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        if not line[0].isspace():
            parent = None
            child_indent = None
            if ":" not in line:
                continue
            key, _, raw = line.partition(":")
            if not key:
                continue
            if raw.strip():
                out[key] = _value(raw)
            else:
                out[key] = {}
                parent = key
            continue

        if parent is None:
            continue
        indent = len(line) - len(line.lstrip(" "))
        if not indent:
            continue
        if child_indent is None:
            child_indent = indent
        if indent != child_indent:
            continue

        item = line[indent:]
        if item.startswith("- "):
            if isinstance(out[parent], dict) and not out[parent]:
                out[parent] = []
            if isinstance(out[parent], list):
                out[parent].append(_value(item[2:]))
        elif ":" in item and isinstance(out[parent], dict):
            subkey, _, raw = item.partition(":")
            if subkey:
                out[parent][subkey] = _value(raw)
    return out


def validate(text: str, allowed_types: set[str]) -> str | None:
    """Report the first missing or unsupported required header field."""
    if _header_lines(text) is None:
        return "missing frontmatter"
    kind = parse(text).get("type")
    if not isinstance(kind, str) or not kind:
        return "missing required field: type"
    if kind not in allowed_types:
        return f"unknown type: {kind}"
    return None


# Which .caddis documents must carry a valid header. Defined here, not in the write hook,
# because this module ships in every bundle and the hook ships only in the Claude plugin:
# caddis_gate docs-check (agy, Codex, CI) and doc_header_guard must share one rule.
_DOC_SCOPE = re.compile(
    r"^\.caddis/(plans|prd|kb|rca|decisions|parking-lot|reviews|todo-list|"
    r"comms|handoffs|prompts|relay)/.+\.md$"
)
_DOC_EXCLUDED = {"DOC-MAP.md", "README.md", "AGENTS.md", "CLAUDE.md"}


def doc_in_scope(relative: str, root: Path) -> bool:
    """True if the repo-relative POSIX path must carry a valid header."""
    if not _DOC_SCOPE.fullmatch(relative) or relative.rsplit("/", 1)[-1] in _DOC_EXCLUDED:
        return False
    config = root / ".caddis" / "config.toml"
    if not config.is_file():
        return True
    with config.open("rb") as stream:
        data = tomllib.load(stream)
    patterns = data.get("docs", {}).get("header_exempt", [])
    if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
        raise ValueError("[docs] header_exempt must be a list of globs")
    return not any(fnmatch.fnmatchcase(relative, pattern) for pattern in patterns)
