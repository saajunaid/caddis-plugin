#!/usr/bin/env python3
"""Minimal self-contained MCP stdio server (raw JSON-RPC 2.0, zero dependencies).

Ships in the claudster agy plugin to prove the MCP wiring end-to-end without pulling in the `mcp`
package or any retired server (junai-mcp is gone). Exposes ONE tool, `claudster_ping`, which returns
the marker `CLAUDSTER-MCP-OK`. Transport: newline-delimited JSON-RPC on stdin/stdout (MCP stdio).
"""
import json
import sys


def _send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        mid = req.get("id")
        method = req.get("method")
        if method == "initialize":
            _send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "claudster", "version": "0.1.0"},
            }})
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": mid, "result": {"tools": [{
                "name": "claudster_ping",
                "description": "Health-check tool — returns a claudster marker so MCP wiring can be verified.",
                "inputSchema": {"type": "object", "properties": {}},
            }]}})
        elif method == "tools/call":
            name = (req.get("params") or {}).get("name")
            if name == "claudster_ping":
                _send({"jsonrpc": "2.0", "id": mid, "result": {
                    "content": [{"type": "text", "text": "CLAUDSTER-MCP-OK"}]
                }})
            else:
                _send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown tool: {name}"}})
        elif method and method.startswith("notifications/"):
            pass  # notifications get no response
        elif mid is not None:
            _send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}})


if __name__ == "__main__":
    main()
