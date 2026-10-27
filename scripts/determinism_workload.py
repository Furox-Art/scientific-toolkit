"""Deterministic catalog/tool-routing workload sampled by the determinism matrix."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _wire_verdict(loads: Any, text: str) -> str:
    try:
        loads(text)
    except (UnicodeDecodeError, ValueError):
        return "rejected"
    return "accepted"


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))

    from scientific_toolkit_mcp.catalog import catalog
    from scientific_toolkit_mcp.http_server import (
        _accepts_mcp,
        _valid_json_content_type,
    )
    from scientific_toolkit_mcp.server import PROTO, TOOLS, handle
    from scientific_toolkit_mcp.strict_json import loads as wire_loads
    from scientific_toolkit_mcp.tools import TOOL_ROUTES

    initialize = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    listing = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    ping = handle({"jsonrpc": "2.0", "id": 3, "method": "ping"})
    notification = handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
    invalid_request = handle({"jsonrpc": "1.0", "id": 4, "method": "ping"})
    bad_params = handle(
        {"jsonrpc": "2.0", "id": 5, "method": "initialize", "params": []}
    )
    unknown_method = handle({"jsonrpc": "2.0", "id": 6, "method": "resources/list"})
    unknown_tool = handle(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "absent", "arguments": {}},
        }
    )
    protocol = {
        "protocol_version": initialize["result"]["protocolVersion"],
        "server": initialize["result"]["serverInfo"]["name"],
        "tools": [tool["name"] for tool in listing["result"]["tools"]],
        "ping": ping["result"],
        "notification": notification,
        "invalid_request": invalid_request["error"]["code"],
        "bad_params": bad_params["error"]["code"],
        "unknown_method": unknown_method["error"]["code"],
        "unknown_tool": unknown_tool["error"]["code"],
        "wire": {
            name: _wire_verdict(wire_loads, text)
            for name, text in (
                (
                    "duplicate_key",
                    '{"jsonrpc":"2.0","id":1,"method":"ping","method":"tools/list"}',
                ),
                ("nan", '{"jsonrpc":"2.0","id":NaN,"method":"ping"}'),
                ("infinity", '{"jsonrpc":"2.0","id":Infinity,"method":"ping"}'),
                ("overflow", '{"jsonrpc":"2.0","id":1e400,"method":"ping"}'),
                ("lone_surrogate", '{"jsonrpc":"2.0","id":"\\ud800","method":"ping"}'),
                ("valid", '{"jsonrpc":"2.0","id":1,"method":"ping"}'),
            )
        },
        "http": {
            "accept_ok": _accepts_mcp(["application/json, text/event-stream"]),
            "accept_q0": _accepts_mcp(["application/json;q=0,text/event-stream"]),
            "json_utf8": _valid_json_content_type("application/json; charset=utf-8"),
            "json_utf16": _valid_json_content_type("application/json; charset=utf-16"),
        },
    }
    payload: dict[str, Any] = {
        "catalog": catalog(),
        "tools": TOOLS,
        "routes": {
            name: {
                "tools": sorted(entry[0]),
                "handler": getattr(entry[1], "__name__", type(entry[1]).__name__),
            }
            for name, entry in TOOL_ROUTES.items()
        },
        "protocol": protocol,
    }
    if not payload["catalog"] or not payload["tools"] or not payload["routes"]:
        raise SystemExit("workload produced an empty registry; it is vacuous")
    if protocol != {
        "protocol_version": PROTO,
        "server": "furox-scientific-toolkit",
        "tools": [tool["name"] for tool in TOOLS],
        "ping": {},
        "notification": None,
        "invalid_request": -32600,
        "bad_params": -32602,
        "unknown_method": -32601,
        "unknown_tool": -32602,
        "wire": {
            "duplicate_key": "rejected",
            "nan": "rejected",
            "infinity": "rejected",
            "overflow": "rejected",
            "lone_surrogate": "rejected",
            "valid": "accepted",
        },
        "http": {
            "accept_ok": True,
            "accept_q0": False,
            "json_utf8": True,
            "json_utf16": False,
        },
    }:
        raise SystemExit("MCP protocol contract changed; the workload is vacuous")
    artifact_dir = os.environ.get("DETERMINISM_ARTIFACT_DIR")
    if artifact_dir:
        Path(artifact_dir, "payload.json").write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
            newline="\n",
        )
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
