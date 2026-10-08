"""Opt-in Render startup verification using the server's existing bearer secret.

Runs real loopback MCP HTTP requests; prints only fixed test names and status.
Does not return a credential, read/write user projects, or claim scientific accuracy.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


ACCEPT = "application/json, text/event-stream"
CALLS = [
    ("axiomize_intake", {"idea": "How does sample size affect measurement uncertainty?"}),
    ("cds_stats", {"values": [1, 2, 3, 4, 5]}),
    ("cds2_stats", {"values": [1, 2, 3, 4, 5]}),
    ("quantum_skill_validate", {}),
    ("axiomize_reason_score", {"evidence": 0.75, "verification": 0.8}),
    ("eq_layer_route", {"messages": [
        {"role": "user", "content": "Explain the result clearly."}
    ], "intent_mode": "heuristic"}),
]


def _post(url: str, method: str, params: dict | None, token: str | None,
          timeout: float = 110.0) -> dict:
    message: dict = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        message["params"] = params
    headers = {"Content-Type": "application/json", "Accept": ACCEPT}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=json.dumps(message).encode("utf-8"),
                                 method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if response.status != 200:
            raise AssertionError("unexpected HTTP response code")
        result = json.load(response)
    if result.get("error"):
        raise AssertionError("JSON-RPC server returned an error")
    return result["result"]


def probe(port: int) -> bool:
    """Return true only after the real HTTP adapter, six safe CLI calls and guards pass."""
    token = os.environ.get("SCITOOL_MCP_BEARER_TOKEN", "")
    if not token:
        print("PRODUCTION_MCP_PROBE RESULT=BLOCKED reason=no_static_secret", flush=True)
        return False

    endpoint = f"http://127.0.0.1:{port}/mcp"
    succeeded = 0
    failed = 0

    class ProbeFailure(Exception):
        def __init__(self, code: str):
            self.code = code

    def public_failure_code(payload: dict, prefix: str) -> str:
        code = payload.get("exit_code")
        stdout = payload.get("stdout", "")
        stderr = payload.get("stderr", "")
        diagnostic = (stdout if isinstance(stdout, str) else "") + " " + (
            stderr if isinstance(stderr, str) else "")
        patterns = (
            ("ModuleNotFoundError", "missing_module"),
            ("No module named", "missing_module"),
            ("ImportError", "import_error"),
            ("MemoryError", "memory_error"),
            ("SyntaxError", "syntax_error"),
            ("Permission denied", "permission_denied"),
            ("usage:", "cli_usage"),
            ("Traceback", "python_exception"),
        )
        kind = next((label for phrase, label in patterns if phrase in diagnostic), "unclassified")
        exit_name = str(code) if type(code) is int and -255 <= code <= 255 else "unknown"
        return f"{prefix}_exit_{exit_name}_{kind}"

    def check(name: str, action) -> None:
        nonlocal succeeded, failed
        try:
            action()
        except Exception as exc:
            failed += 1
            # Codes are constructed solely from validated status / numeric process exits.
            # Never print exception text, tool output, authorization headers, or secrets.
            detail = f" detail={exc.code}" if isinstance(exc, ProbeFailure) else ""
            print(f"PRODUCTION_MCP_PROBE {name}=FAIL category={type(exc).__name__}{detail}",
                  flush=True)
        else:
            succeeded += 1
            print(f"PRODUCTION_MCP_PROBE {name}=PASS", flush=True)

    def unauthorized() -> None:
        try:
            _post(endpoint, "ping", None, token=None, timeout=10)
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                return
        raise AssertionError("anonymous request did not return HTTP 401")

    def initialization() -> None:
        result = _post(endpoint, "initialize",
                       {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "production-probe", "version": "1"}},
                       token)
        if result.get("serverInfo", {}).get("name") != "furox-scientific-toolkit":
            raise AssertionError("unexpected MCP serverInfo")

    def list_remote() -> None:
        result = _post(endpoint, "tools/list", None, token)
        names = {item["name"] for item in result["tools"]}
        if len(names) != 10 or "plan_auditor_audit" in names or "plan_auditor_inspect" not in names:
            raise AssertionError("wrong remote tool inventory")

    def catalog() -> None:
        output = _post(endpoint, "tools/call",
                       {"name": "toolkit_catalog", "arguments": {}}, token)
        data = json.loads(output["content"][0]["text"])
        if output.get("isError") or data.get("count") != 7:
            raise AssertionError("catalog mismatch")

    def doctor() -> None:
        output = _post(endpoint, "tools/call",
                       {"name": "toolkit_doctor", "arguments": {}}, token)
        data = json.loads(output["content"][0]["text"])
        if output.get("isError") or len(data.get("commands", {})) != 7:
            raise AssertionError("doctor did not list seven CLIs")
        if not all(v.get("installed") is True for v in data["commands"].values()):
            raise AssertionError("one or more upstream commands are not installed")

    def denied_audit() -> None:
        output = _post(endpoint, "tools/call",
                       {"name": "plan_auditor_audit", "arguments": {}}, token)
        if output.get("isError") is not True:
            raise AssertionError("workspace audit should be blocked remotely")

    check("unauthenticated_denied", unauthorized)
    check("initialize", initialization)
    check("remote_tool_inventory", list_remote)
    check("seven_repository_catalog", catalog)
    check("seven_upstream_cli_paths", doctor)
    check("remote_audit_denied", denied_audit)

    for name, arguments in CALLS:
        def execute(name=name, arguments=arguments):
            output = _post(endpoint, "tools/call",
                           {"name": name, "arguments": arguments}, token)
            if output.get("isError"):
                try:
                    payload = json.loads(output["content"][0]["text"])
                except (ValueError, KeyError, TypeError, IndexError):
                    raise ProbeFailure("mcp_error_no_json")
                raise ProbeFailure(public_failure_code(payload, "mcp_error"))
            payload = json.loads(output["content"][0]["text"])
            if payload.get("status") != "COMMAND_SUCCEEDED" or payload.get("exit_code") != 0:
                raise ProbeFailure(public_failure_code(payload, "upstream"))
        check(name, execute)

    try:
        from . import oauth
        state = "PROVIDER_CONFIGURED_NOT_LIVE_TESTED" if oauth.settings() else "PROVIDER_NOT_CONFIGURED"
    except ValueError:
        state = "INVALID_CONFIGURATION"
    print("PRODUCTION_MCP_PROBE oauth_state=" + state, flush=True)
    print(f"PRODUCTION_MCP_PROBE RESULT={'PASS' if failed == 0 else 'FAIL'} "
          f"checks_passed={succeeded} checks_failed={failed} "
          "scope=loopback_http_real_cli_no_scientific_accuracy_claim", flush=True)
    return failed == 0
