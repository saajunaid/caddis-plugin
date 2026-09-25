"""PreToolUse guard for typed .caddis Markdown documents.

An invalid legacy file may still be edited. Only a new invalid file or a
valid-to-invalid change is denied. All evaluation errors fail open.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")


def repo_root(path: Path) -> Path | None:
    """Find the nearest .git entry without starting a process."""
    for directory in (path.parent, *path.parents):
        if (directory / ".git").exists():
            return directory
    return None


def in_scope(relative: str, root: Path) -> bool:
    """The shared hook and docs-check path rule, which lives in caddis_frontmatter."""
    if _SCRIPTS not in sys.path:
        sys.path.insert(0, _SCRIPTS)
    import caddis_frontmatter

    return caddis_frontmatter.doc_in_scope(relative, root)


def _apply_edit(current: str, edit: dict) -> str | None:
    old, new = edit["old_string"], edit["new_string"]
    if not isinstance(old, str) or not isinstance(new, str) or not old:
        return None
    count = current.count(old)
    if count == 0 or (count > 1 and not edit.get("replace_all", False)):
        return None  # The real Edit would not apply; never invent a denied result.
    return current.replace(old, new) if edit.get("replace_all", False) else current.replace(old, new, 1)


def _resulting_text(tool_name: str, fields: dict, current: str | None) -> str | None:
    if tool_name == "Write":
        return fields["content"]
    if current is None:
        return None
    if tool_name == "Edit":
        return _apply_edit(current, fields)
    if tool_name == "MultiEdit":
        result = current
        for edit in fields["edits"]:
            result = _apply_edit(result, edit)
            if result is None:
                return None
        return result
    return None


def _record(exc: Exception, root: Path | str) -> None:
    try:
        if _SCRIPTS not in sys.path:
            sys.path.insert(0, _SCRIPTS)
        import hook_log
        ledger_root = root if isinstance(root, (str, Path)) else os.getcwd()
        try:
            ledger_root = repo_root(Path(ledger_root).resolve() / ".caddis-hook") or ledger_root
        except Exception:
            pass
        hook_log.record("doc_header_guard", "document header check", exc, str(ledger_root))
    except Exception:
        pass  # The error ledger must not block the tool call.


def main() -> None:
    root: Path | str = os.getcwd()
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise TypeError("hook payload must be an object")
        root = payload.get("cwd") or root
        fields = payload["tool_input"]
        tool_name = payload["tool_name"]
        if not isinstance(fields, dict):
            raise TypeError("tool_input must be an object")
        raw_path = fields.get("file_path") or fields.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            raise ValueError("missing file path")
        path = Path(raw_path)
        if not path.is_absolute():
            path = Path(root) / path
        path = path.resolve()
        repo = repo_root(path)
        if repo is None:
            sys.exit(0)
        root = repo
        relative = path.relative_to(repo).as_posix()
        if not in_scope(relative, repo):
            sys.exit(0)
        if _SCRIPTS not in sys.path:
            sys.path.insert(0, _SCRIPTS)
        import caddis_frontmatter

        current = path.read_text(encoding="utf-8") if path.exists() else None
        result = _resulting_text(tool_name, fields, current)
        if result is None:
            sys.exit(0)
        if not isinstance(result, str):
            raise TypeError("document content must be text")
        if current is not None and caddis_frontmatter.validate(
            current, caddis_frontmatter.ALLOWED_TYPES
        ) is not None:
            sys.exit(0)  # Legacy invalid document: allow maintenance and migration.
        error = caddis_frontmatter.validate(result, caddis_frontmatter.ALLOWED_TYPES)
        if error:
            types = ", ".join(sorted(caddis_frontmatter.ALLOWED_TYPES))
            reason = (f"[caddis docs] {relative}: {error}. Add a header: "
                      f"---\ntype: <one of {types}>\n---")
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }}))
    except Exception as exc:
        _record(exc, root)
        sys.exit(0)
    sys.exit(0)


if __name__ == "__main__":
    main()
