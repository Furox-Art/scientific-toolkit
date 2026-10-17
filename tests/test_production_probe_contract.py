"""Offline tests for the real production probe's strict status contract.

Remote endpoints are emulated at the HTTP boundary. These tests make no
claim that upstream tool executables or Render production are available.
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from scientific_toolkit_mcp import production_probe


def _success(name: str, arguments: dict) -> dict:
    if name == "toolkit_catalog":
        return {"content": [{"text": json.dumps({"count": 7})}]}
    if name == "toolkit_doctor":
        return {
            "content": [
                {
                    "text": json.dumps(
                        {"commands": {str(i): {"installed": True} for i in range(7)}}
                    )
                }
            ]
        }
    if name == "plan_auditor_audit":
        return {"isError": True, "content": [{"text": "workspace operations denied"}]}
    return {
        "content": [
            {
                "text": json.dumps(
                    {
                        "status": "COMMAND_SUCCEEDED",
                        "exit_code": 0,
                    }
                )
            }
        ],
        "isError": False,
    }


def _fake_post(url, method, params, token, timeout=110.0):
    assert url == "http://127.0.0.1:8035/mcp"
    if not token:
        raise urllib.error.HTTPError(url, 401, "unauthorized", {}, None)
    if method == "initialize":
        return {"serverInfo": {"name": "furox-scientific-toolkit"}}
    if method == "tools/list":
        return {
            "tools": [
                {"name": "plan_auditor_inspect"},
                *({"name": f"tool_{i}"} for i in range(9)),
            ]
        }
    assert method == "tools/call"
    return _success(params["name"], params["arguments"])


def test_production_probe_fails_closed_without_secret(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("SCITOOL_MCP_BEARER_TOKEN", raising=False)
    assert not production_probe.probe(8035)
    assert "RESULT=BLOCKED reason=no_static_secret" in capsys.readouterr().out


def test_successful_probe_checks_real_adapter_contract_offline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SCITOOL_MCP_BEARER_TOKEN", "probe-secret-not-to-print")
    monkeypatch.setattr(production_probe, "_post", _fake_post)
    monkeypatch.setattr("scientific_toolkit_mcp.oauth.settings", lambda: None)
    assert production_probe.probe(8035)
    output = capsys.readouterr().out
    assert "RESULT=PASS checks_passed=12 checks_failed=0" in output
    assert "oauth_state=PROVIDER_NOT_CONFIGURED" in output
    assert "probe-secret-not-to-print" not in output


@pytest.mark.parametrize(
    ("target", "bad_response", "expected"),
    [
        ("initialize", {"serverInfo": {"name": "unknown"}}, "initialize=FAIL"),
        (
            "tools/list",
            {"tools": [{"name": "plan_auditor_audit"}] * 10},
            "remote_tool_inventory=FAIL",
        ),
        (
            "toolkit_catalog",
            {"content": [{"text": '{"count":8}'}]},
            "seven_repository_catalog=FAIL",
        ),
        (
            "toolkit_doctor",
            {"content": [{"text": '{"commands":{}}'}]},
            "seven_upstream_cli_paths=FAIL",
        ),
        ("plan_auditor_audit", {"isError": False}, "remote_audit_denied=FAIL"),
        (
            "cds_stats",
            {"isError": True, "content": [{"text": "garbled"}]},
            "cds_stats=FAIL",
        ),
        (
            "cds_stats",
            {
                "isError": False,
                "content": [
                    {
                        "text": json.dumps(
                            {
                                "status": "COMMAND_FAILED",
                                "exit_code": 2,
                                "stderr": "ImportError",
                            }
                        )
                    }
                ],
            },
            "cds_stats=FAIL",
        ),
    ],
)
def test_probe_never_reports_pass_on_broken_remote_contract(
    target,
    bad_response,
    expected,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SCITOOL_MCP_BEARER_TOKEN", "secret")
    monkeypatch.setattr("scientific_toolkit_mcp.oauth.settings", lambda: None)

    def intercepted(url, method, params, token, timeout=110):
        name = (
            params["name"] if isinstance(params, dict) and "name" in params else method
        )
        if name == target:
            return bad_response
        return _fake_post(url, method, params, token, timeout)

    monkeypatch.setattr(production_probe, "_post", intercepted)
    assert not production_probe.probe(8035)
    output = capsys.readouterr().out
    assert expected in output
    assert "RESULT=FAIL" in output
    assert "secret" not in output


@pytest.mark.parametrize(
    "bad",
    [
        {"exit_code": 5, "stderr": "No module named example"},
        {"exit_code": 8, "stderr": "Permission denied"},
        {"exit_code": "not a number", "stdout": "Traceback"},
        {"exit_code": 300, "stdout": "other"},
        {"exit_code": 1, "stdout": "SyntaxError"},
        {"exit_code": 1, "stdout": "MemoryError"},
        {"exit_code": 1, "stdout": "usage:"},
    ],
)
def test_probe_only_prints_safe_error_categories(
    bad: dict,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SCITOOL_MCP_BEARER_TOKEN", "secret")
    monkeypatch.setattr("scientific_toolkit_mcp.oauth.settings", lambda: None)
    original = "malicious-secret-in-stderr"
    bad = {**bad, "stderr": bad.get("stderr", "") + original}

    def intercepted(url, method, params, token, timeout=110):
        if isinstance(params, dict) and params.get("name") == "cds_stats":
            return {"isError": True, "content": [{"text": json.dumps(bad)}]}
        return _fake_post(url, method, params, token, timeout)

    monkeypatch.setattr(production_probe, "_post", intercepted)
    assert not production_probe.probe(8035)
    output = capsys.readouterr().out
    assert "cds_stats=FAIL" in output
    assert original not in output
    assert "RESULT=FAIL" in output


@pytest.mark.parametrize("state", ["configured", "bad"])
def test_probe_reports_provider_configuration_without_leaking_details(
    state: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SCITOOL_MCP_BEARER_TOKEN", "secret")
    monkeypatch.setattr(production_probe, "_post", _fake_post)

    def settings():
        if state == "bad":
            raise ValueError("secret value should remain private")
        return {"provider": "configured"}

    monkeypatch.setattr("scientific_toolkit_mcp.oauth.settings", settings)
    assert production_probe.probe(8035)
    output = capsys.readouterr().out
    assert (
        "INVALID_CONFIGURATION"
        if state == "bad"
        else "PROVIDER_CONFIGURED_NOT_LIVE_TESTED"
    ) in output
    assert "secret value" not in output


def test_probe_http_post_uses_utf8_authorization_and_jsonrpc_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"result": {"ok": True}}).encode("utf-8")

    def open_request(req, timeout):
        captured.append((req, timeout))
        return FakeResponse()

    monkeypatch.setattr(production_probe.urllib.request, "urlopen", open_request)
    assert production_probe._post(
        "http://127.0.0.1:8035/mcp",
        "ping",
        {"x": 1},
        "test-token",
        timeout=3.0,
    ) == {"ok": True}
    request, timeout = captured[0]
    assert timeout == 3.0
    assert request.get_header("Authorization") == "Bearer test-token"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data)["params"] == {"x": 1}


@pytest.mark.parametrize(
    ("result", "error", "token"),
    [
        (
            {"error": {"code": -32600, "message": "invalid"}},
            "JSON-RPC server",
            "secret",
        ),
        ({"result": {"ok": True}}, "unexpected HTTP", "secret"),
    ],
)
def test_http_post_rejects_nonstandard_status_and_rpc_errors(
    result,
    error,
    token,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status = 503 if error == "unexpected HTTP" else 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(result).encode()

    monkeypatch.setattr(
        production_probe.urllib.request, "urlopen", lambda *a, **k: Response()
    )
    with pytest.raises(AssertionError, match=error):
        production_probe._post("http://127.0.0.1:8035/mcp", "ping", None, token)


def test_http_post_unauthenticated_request_never_adds_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"result":{}}'

    def urlopen(request, timeout):
        captured.append(request)
        return Response()

    monkeypatch.setattr(production_probe.urllib.request, "urlopen", urlopen)
    assert production_probe._post("http://127.0.0.1:8035/mcp", "ping", None, None) == {}
    assert captured[0].get_header("Authorization") is None
    assert "params" not in json.loads(captured[0].data)


def test_probe_rejects_non401_anonymous_response(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SCITOOL_MCP_BEARER_TOKEN", "secret")

    def no_unauthorized(url, method, params, token, timeout=110):
        if token is None:
            raise urllib.error.HTTPError(url, 403, "forbidden", {}, None)
        return _fake_post(url, method, params, token, timeout)

    monkeypatch.setattr(production_probe, "_post", no_unauthorized)
    monkeypatch.setattr("scientific_toolkit_mcp.oauth.settings", lambda: None)
    assert not production_probe.probe(8035)
    assert "unauthenticated_denied=FAIL" in capsys.readouterr().out


def test_probe_reports_missing_upstream_command_in_doctor(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SCITOOL_MCP_BEARER_TOKEN", "secret")
    monkeypatch.setattr("scientific_toolkit_mcp.oauth.settings", lambda: None)

    def partial_doctor(url, method, params, token, timeout=110):
        if isinstance(params, dict) and params.get("name") == "toolkit_doctor":
            data = {str(n): {"installed": n != 0} for n in range(7)}
            return {"content": [{"text": json.dumps({"commands": data})}]}
        return _fake_post(url, method, params, token, timeout)

    monkeypatch.setattr(production_probe, "_post", partial_doctor)
    assert not production_probe.probe(8035)
    assert "seven_upstream_cli_paths=FAIL" in capsys.readouterr().out
