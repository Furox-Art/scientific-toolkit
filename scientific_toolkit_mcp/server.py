"""Minimal MCP 2025-06-18 stdio server with no extra runtime dependencies.

All machine-readable protocol messages go to stdout; no log messages do.
The protocol is one JSON-RPC object per UTF-8 line. No network listener.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from . import __version__
from .tools import ToolFailure, dispatch

PROTO = "2025-06-18"


def spec(name: str, description: str, properties: dict | None = None,
         required: list[str] | None = None) -> dict:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object", "properties": properties or {}, "required": required or [],
            "additionalProperties": False,
        },
    }


NUMBERS = {"type": "array", "minItems": 2, "maxItems": 1000,
           "items": {"type": "number"}}
UNIT = {"type": "number", "minimum": 0, "maximum": 1}

TOOLS = [
    spec("toolkit_catalog", "List the seven original, public Furox-Art repositories and their exact roles."),
    spec("toolkit_doctor", "Check local upstream CLI availability; does not run scientific computations."),
    spec("axiomize_intake", "Axiomize: clarify a scientific modeling idea using the upstream intake CLI.",
         {"idea": {"type": "string", "minLength": 1, "maxLength": 6000}}, ["idea"]),
    spec("axiomize_model", "Axiomize: invoke a conservative model operation. Input must use upstream Model IR / request schema; no shell commands.",
         {"action": {"type": "string", "enum": ["validate", "simulate", "validity", "uncertainty", "stability", "numerical-verify"]},
          "request": {"type": "object"}}, ["action", "request"]),
    spec("cds_stats", "Pure-Python scientific-computing-system: run its descriptive statistics CLI.",
         {"values": NUMBERS}, ["values"]),
    spec("cds2_stats", "NumPy-backed scientific-computing-system-2.0: run its descriptive statistics CLI.",
         {"values": NUMBERS}, ["values"]),
    spec("plan_auditor_inspect", "Inspect an explicitly configured trusted workspace plan; does not certify work as complete."),
    spec("plan_auditor_audit", "Run the independent fail-closed audit on the configured trusted workspace; disabled unless SCITOOL_ALLOW_AUDIT_EXECUTION=1. Audit can execute user-approved checks."),
    spec("quantum_skill_validate", "Inspect/validate the installed quantum-reasoning-skill contract; does NOT prove improved model performance."),
    spec("axiomize_reason_score", "Score a reasoning branch via axiomize-quantum-skills-2.0's axiomize-reason CLI; thresholds are not empirical calibrations.",
         {"evidence": UNIT, "verification": UNIT}, ["evidence", "verification"]),
    spec("eq_layer_route", "EQ-Layer local intent/affect routing; not factual truth verification or clinical emotion diagnosis.",
         {"messages": {"type": "array", "minItems": 1, "maxItems": 20,
                       "items": {"type": "object", "properties": {
                           "role": {"type": "string", "enum": ["user", "assistant", "system"]},
                           "content": {"type": "string", "minLength": 1, "maxLength": 4000},
                       }, "required": ["role", "content"], "additionalProperties": False}},
          "intent_mode": {"type": "string", "enum": ["auto", "heuristic", "learned"], "default": "heuristic"}},
         ["messages"]),
]
TOOL_NAMES = {tool["name"] for tool in TOOLS}


def response(request_id: Any, *, result: Any = None, error: dict | None = None) -> dict:
    obj: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        obj["error"] = error
    else:
        obj["result"] = result
    return obj


def handle(msg: Any) -> dict | None:
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return response(msg.get("id") if isinstance(msg, dict) else None,
                        error={"code": -32600, "message": "Invalid JSON-RPC request"})
    request_id = msg.get("id")
    # Notifications (including initialized) never get responses.
    if "id" not in msg:
        return None
    method = msg["method"]
    params = msg.get("params", {})
    if not isinstance(params, dict):
        return response(request_id, error={"code": -32602, "message": "params must be an object"})
    if method == "initialize":
        return response(request_id, result={
            "protocolVersion": PROTO,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "furox-scientific-toolkit", "version": __version__},
            "instructions": "Seven public repositories. Execute only installed local tools; tools report actual exit codes. Audit execution requires explicit opt-in.",
        })
    if method == "ping":
        return response(request_id, result={})
    if method == "tools/list":
        return response(request_id, result={"tools": TOOLS})
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments", {})
        if not isinstance(name, str) or name not in TOOL_NAMES:
            return response(request_id, error={"code": -32602, "message": "Unknown tool"})
        try:
            payload = dispatch(name, args)
            # Upstream processes are permitted to fail; report that as isError.
            failed = isinstance(payload, dict) and payload.get("status") == "COMMAND_FAILED"
            result = {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
                      "isError": failed}
        except (ToolFailure, ValueError, TypeError, OverflowError) as exc:
            result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
        except Exception as exc:
            # Do not crash stdio process or expose credentials/tracebacks.
            result = {"content": [{"type": "text", "text": f"INTERNAL_ERROR: {type(exc).__name__}"}], "isError": True}
        return response(request_id, result=result)
    return response(request_id, error={"code": -32601, "message": "Method not found"})


def main() -> None:
    # A minimal stdio endpoint: newline-delimited UTF-8 JSON. Never write to
    # stdout except protocol frames. Clients launch it as a local subprocess.
    for raw in sys.stdin.buffer:
        if not raw.strip():
            continue
        if len(raw) > 1024 * 1024:
            outgoing = response(None, error={"code": -32600, "message": "Message too large"})
        else:
            try:
                incoming = json.loads(raw)
                outgoing = handle(incoming)
            except (json.JSONDecodeError, UnicodeDecodeError):
                outgoing = response(None, error={"code": -32700, "message": "Parse error"})
        if outgoing is not None:
            try:
                sys.stdout.write(json.dumps(outgoing, ensure_ascii=False, allow_nan=False) + "\n")
                sys.stdout.flush()
            except BrokenPipeError:
                return


if __name__ == "__main__":
    main()
