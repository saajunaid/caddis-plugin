#!/usr/bin/env python3
"""Minimal self-contained MCP stdio server (raw JSON-RPC 2.0, zero dependencies).

Ships in the caddis plugin for agy, Claude Code, and Codex. Exposes:
- `caddis_ping`: health check returning `CADDIS-MCP-OK`
- `caddis_task_create`, `caddis_task_update`, `caddis_task_list`, `caddis_task_get`, `caddis_task_clear`:
  universal repo-agnostic, agent-agnostic task list backed atomically by
  `<repo>/.caddis/relay/<workstream>.tasks.md`.

Transport: newline-delimited JSON-RPC on stdin/stdout (MCP stdio).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_CANDIDATES = [_HERE / "scripts"] + [p / "scripts" for p in _HERE.parents[:2]]
for _cand in _CANDIDATES:
    if (_cand / "caddis_tasks.py").is_file() and str(_cand) not in sys.path:
        sys.path.insert(0, str(_cand))
        break

try:
    import caddis_tasks as _tasks  # noqa: E402
except ImportError:
    _tasks = None  # type: ignore[assignment]

_VALID_STATUSES = list(_tasks.VALID_STATUSES) if _tasks is not None else ["pending", "in_progress", "completed", "blocked"]


TOOLS = [
    {
        "name": "caddis_ping",
        "description": "Health-check tool - returns a caddis marker so MCP wiring can be verified.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "caddis_task_create",
        "description": "Create a persistent task in <repo>/.caddis/relay/<workstream>.tasks.md (shared across agy, Claude Code, Codex, and Orca bots).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository root path (defaults to cwd)."},
                "workstream": {"type": "string", "description": "Relay/workstream name (default: 'default')."},
                "subject": {"type": "string", "description": "Short actionable task title."},
                "description": {"type": "string", "description": "Optional details."},
                "status": {"type": "string", "enum": _VALID_STATUSES},
                "priority": {"type": "string"},
                "track": {"type": "string"},
                "owner": {"type": "string"},
                "blocked_by": {"type": "array", "items": {"type": "string"}},
                "id": {"type": "string", "description": "Optional explicit task id."},
            },
            "required": ["subject"],
        },
    },
    {
        "name": "caddis_task_update",
        "description": "Update an existing task's status, owner, priority, blocked_by, subject, or description.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "workstream": {"type": "string"},
                "id": {"type": "string"},
                "subject": {"type": "string"},
                "description": {"type": "string"},
                "status": {"type": "string", "enum": _VALID_STATUSES},
                "priority": {"type": "string"},
                "track": {"type": "string"},
                "owner": {"type": "string"},
                "blocked_by": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["id"],
        },
    },
    {
        "name": "caddis_task_list",
        "description": "List tasks and status counts from <repo>/.caddis/relay/<workstream>.tasks.md.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "workstream": {"type": "string"},
                "status": {"type": "string", "enum": _VALID_STATUSES},
            },
        },
    },
    {
        "name": "caddis_task_get",
        "description": "Get one task by id from <repo>/.caddis/relay/<workstream>.tasks.md.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "workstream": {"type": "string"},
                "id": {"type": "string"},
            },
            "required": ["id"],
        },
    },
    {
        "name": "caddis_task_clear",
        "description": "Remove completed tasks (or all tasks when completed_only=false) from the task list.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "workstream": {"type": "string"},
                "completed_only": {"type": "boolean"},
            },
        },
    },
]


def _send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def _text_result(mid: object, text: str) -> None:
    _send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}})


def _opt_str(args: dict, key: str, default: str | None = None) -> str | None:
    val = args.get(key)
    if val is None:
        return default
    if not isinstance(val, str):
        raise ValueError(f"{key} must be a string")
    return val


def _handle_tool(mid: object, name: str, args: dict) -> None:
    if name == "caddis_ping":
        _text_result(mid, "CADDIS-MCP-OK")
        return
    if _tasks is None:
        _send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": "caddis_tasks backend unavailable"}})
        return
    if not isinstance(args, dict):
        _send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "arguments must be an object"}})
        return
    try:
        repo = _opt_str(args, "repo") or os.getcwd()
        ws = _opt_str(args, "workstream") or "default"
        if name == "caddis_task_create":
            task = _tasks.create_task(
                repo,
                workstream=ws,
                subject=_opt_str(args, "subject", "") or "",
                description=_opt_str(args, "description", "") or "",
                status=_opt_str(args, "status") or "pending",
                priority=_opt_str(args, "priority", "") or "",
                track=_opt_str(args, "track", "") or "",
                owner=_opt_str(args, "owner", "") or "",
                blocked_by=args.get("blocked_by"),
                task_id=_opt_str(args, "id"),
            )
            _text_result(mid, json.dumps(task, ensure_ascii=False))
        elif name == "caddis_task_update":
            tid = _opt_str(args, "id")
            if not tid:
                raise ValueError("id is required")
            task = _tasks.update_task(
                repo,
                workstream=ws,
                task_id=tid,
                subject=_opt_str(args, "subject"),
                description=_opt_str(args, "description"),
                status=_opt_str(args, "status"),
                priority=_opt_str(args, "priority"),
                track=_opt_str(args, "track"),
                owner=_opt_str(args, "owner"),
                blocked_by=args.get("blocked_by"),
            )
            _text_result(mid, json.dumps(task, ensure_ascii=False))
        elif name == "caddis_task_list":
            rows = _tasks.list_tasks(repo, workstream=ws, status=_opt_str(args, "status"))
            _text_result(mid, json.dumps({"tasks": rows, "summary": _tasks.summarize(rows)}, ensure_ascii=False))
        elif name == "caddis_task_get":
            tid = _opt_str(args, "id")
            if not tid:
                raise ValueError("id is required")
            task = _tasks.get_task(repo, workstream=ws, task_id=tid)
            _text_result(mid, json.dumps(task, ensure_ascii=False))
        elif name == "caddis_task_clear":
            raw_co = args.get("completed_only")
            if raw_co is None:
                completed_only = True
            elif isinstance(raw_co, bool):
                completed_only = raw_co
            else:
                raise ValueError("completed_only must be a boolean")
            removed = _tasks.clear_tasks(repo, workstream=ws, completed_only=completed_only)
            _text_result(mid, json.dumps({"removed": removed}, ensure_ascii=False))
        else:
            _send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown tool: {name}"}})
    except (KeyError, ValueError, TypeError, AttributeError, OSError) as exc:
        _send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": str(exc)}})
    except Exception as exc:  # noqa: BLE001
        _send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": f"internal error: {exc}"}})


def main() -> None:
    for stream in (sys.stdin, sys.stdout):
        reconf = getattr(stream, "reconfigure", None)
        if reconf:
            try:
                reconf(encoding="utf-8")
            except Exception:
                pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(req, dict):
            continue
        mid = req.get("id")
        method = req.get("method")
        try:
            if method == "initialize":
                _send({"jsonrpc": "2.0", "id": mid, "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "caddis", "version": "0.2.0"},
                }})
            elif method == "tools/list":
                _send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
            elif method == "tools/call":
                params = req.get("params")
                if not isinstance(params, dict):
                    if mid is not None:
                        _send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "params must be an object"}})
                    continue
                _handle_tool(mid, str(params.get("name") or ""), params.get("arguments") if params.get("arguments") is not None else {})
            elif isinstance(method, str) and method.startswith("notifications/"):
                pass
            elif mid is not None:
                _send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}})
        except Exception as exc:  # noqa: BLE001
            if mid is not None:
                _send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": f"internal error: {exc}"}})


if __name__ == "__main__":
    main()
