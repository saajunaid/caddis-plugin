"""One SessionStart line when Claude Code has a version caddis has not read the changelog of yet.

caddis builds on Claude Code behaviour (hooks, headless `claude -p`, worktrees, subagents, plugins). Before a plan
builds or works around such behaviour, someone must know what the new release changed, fixed or plans. The record
is `.caddis/kb/claude-code-upstream-watch.md` in the caddis source repo (owner request, 2026-10-17).

- The version comes from Claude Code's own `package.json` next to `CLAUDE_CODE_EXECPATH` (no process is started).
- With the caddis source repo known (`~/.caddis/harness-root`) and its watch file present, the line shows on every
  session start until that file has a `## <version>` heading: reading the changelog is what clears it.
- Without that file (another machine or team), the line shows once per version (`~/.caddis/claude-code-version.json`).

Pure file reads; any error means no line.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

WATCH_REL = Path(".caddis") / "kb" / "claude-code-upstream-watch.md"
STATE_NAME = "claude-code-version.json"
CHANGELOG = "https://changelogs.core-directive.com/v/{version}?depth=read"
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def installed_version(execpath: str | None) -> str | None:
    """The version in `<package>/package.json`, where CLAUDE_CODE_EXECPATH is `<package>/bin/claude(.exe)`."""
    if not execpath:
        return None
    exe = Path(execpath)
    for candidate in (exe.parent.parent / "package.json", exe.parent / "package.json"):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        version = str(data.get("version") or "") if isinstance(data, dict) else ""
        if data.get("name") == "@anthropic-ai/claude-code" and _VERSION_RE.match(version):
            return version
    return None


def _watch_file(home: Path) -> Path | None:
    try:
        root = (home / ".caddis" / "harness-root").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not root or not Path(root).is_absolute():  # a relative value would read a file in the session's project
        return None
    path = Path(root) / WATCH_REL
    return path if path.is_file() else None


def _recorded(watch: Path, version: str) -> bool:
    try:
        text = watch.read_text(encoding="utf-8")
    except OSError:
        return False
    return re.search(rf"^## {re.escape(version)}\b", text, re.MULTILINE) is not None


def notice(execpath: str | None, home: Path) -> str | None:
    """The one line to print, or None. Writes the once-per-version state only on the no-watch-file path."""
    version = installed_version(execpath)
    if version is None:
        return None
    url = CHANGELOG.format(version=version)
    watch = _watch_file(home)
    if watch is not None:
        if _recorded(watch, version):
            return None
        return (f"[UPSTREAM] Claude Code {version} is not in the caddis upstream watch yet: read {url} (pages 1-3) "
                f"and add a '## {version}' section to {watch} before planning work on Claude Code behaviour.")
    state = home / ".caddis" / STATE_NAME
    try:
        seen = json.loads(state.read_text(encoding="utf-8")).get("seen")
    except (OSError, ValueError, AttributeError):
        seen = None
    if seen == version:
        return None
    try:
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"seen": version}), encoding="utf-8")
    except OSError:
        return None  # cannot remember it: stay quiet rather than repeat on every start
    return f"[UPSTREAM] Claude Code is now {version}: check {url} before building on changed behaviour."
