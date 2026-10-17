"""Loopback HTTP error contracts and OAuth JWT failure-injection cases."""

from __future__ import annotations

import http.client
import json
import runpy
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from scientific_toolkit_mcp import http_server, oauth


@pytest.fixture
def loopback():
    server = ThreadingHTTPServer(("127.0.0.1", 0), http_server.Handler)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def _request(port, method, path, *, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    conn.request(method, path, body=body, headers=headers or {})
    response = conn.getresponse()
    code, payload = response.status, response.read()
    conn.close()
    return code, payload


def _auth_headers(**extras):
    return {
        "Authorization": "Bearer test",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        **extras,
    }


def test_http_unsupported_endpoints_refuse_without_hitting_a_tool(
    loopback: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCITOOL_MCP_BEARER_TOKEN", "test")
    assert (
        _request(loopback, "POST", "/wrong", body=b"{}", headers=_auth_headers())[0]
        == 404
    )
    assert _request(loopback, "OPTIONS", "/wrong")[0] == 404
    assert _request(loopback, "DELETE", "/mcp")[0] == 405


@pytest.mark.parametrize("content_length", ["0", "131073"])
def test_http_rejects_empty_and_oversized_json_before_read(
    loopback: int,
    monkeypatch: pytest.MonkeyPatch,
    content_length: str,
) -> None:
    monkeypatch.setenv("SCITOOL_MCP_BEARER_TOKEN", "test")
    headers = _auth_headers(**{"Content-Length": content_length})
    assert _request(loopback, "POST", "/mcp", body=b"", headers=headers)[0] == 413


def test_http_returns_429_when_client_budget_exhausted(
    loopback: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCITOOL_MCP_BEARER_TOKEN", "test")
    monkeypatch.setattr(http_server, "_record_rate_hit", lambda client, now: False)
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode()
    assert (
        _request(loopback, "POST", "/mcp", body=body, headers=_auth_headers())[0] == 429
    )


def test_http_returns_503_when_no_concurrent_slot_is_available(
    loopback: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCITOOL_MCP_BEARER_TOKEN", "test")
    fake_semaphore = SimpleNamespace(acquire=lambda **kwargs: False)
    monkeypatch.setattr(http_server, "_semaphore", fake_semaphore)
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode()
    assert (
        _request(loopback, "POST", "/mcp", body=body, headers=_auth_headers())[0] == 503
    )


def test_resource_metadata_returns_404_if_provider_not_configured(
    loopback: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(http_server.oauth, "settings", lambda: None)
    assert _request(loopback, "GET", "/.well-known/oauth-protected-resource")[0] == 404


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_incomplete_oauth_provider_fails_closed_on_http(
    loopback: int,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
) -> None:
    def invalid():
        raise ValueError("incomplete provider")

    monkeypatch.delenv("SCITOOL_MCP_BEARER_TOKEN", raising=False)
    monkeypatch.setattr(http_server.oauth, "settings", invalid)
    if method == "GET":
        code, _ = _request(loopback, "GET", "/.well-known/oauth-protected-resource")
    else:
        code, _ = _request(loopback, "POST", "/mcp", body=b"{}", headers={})
    assert code == 503


def test_http_resource_metadata_reports_configured_provider(
    loopback: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = oauth.OAuthConfig(
        "https://issuer.test",
        "https://issuer.test/keys",
        "https://resource.test/mcp",
        "mcp:tools",
    )
    monkeypatch.setattr(http_server.oauth, "settings", lambda: config)
    code, body = _request(loopback, "GET", "/.well-known/oauth-protected-resource/mcp")
    assert code == 200
    assert json.loads(body)["resource"] == "https://resource.test/mcp"


def test_unrecognized_accept_extension_does_not_displace_required_types() -> None:
    assert http_server._accepts_mcp(
        ["application/json; extension=custom, text/event-stream"]
    )


def test_invalid_scope_configuration_is_explicitly_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCITOOL_OAUTH_ISSUER", "https://issuer.test")
    monkeypatch.setenv("SCITOOL_OAUTH_JWKS_URI", "https://issuer.test/keys")
    monkeypatch.setenv("SCITOOL_OAUTH_RESOURCE_URI", "https://resource.test/mcp")
    for bad in ("", "scope contains whitespace", "s" * 129):
        monkeypatch.setenv("SCITOOL_OAUTH_REQUIRED_SCOPE", bad)
        with pytest.raises(ValueError, match="Invalid scope"):
            oauth.settings()


def test_oauth_jwt_non_list_non_string_scope_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = oauth.OAuthConfig(
        "https://issuer.test",
        "https://issuer.test/keys",
        "https://resource.test/mcp",
        "mcp:tools",
    )
    monkeypatch.delenv("SCITOOL_MCP_BEARER_TOKEN", raising=False)
    monkeypatch.setattr(oauth, "settings", lambda: config)
    monkeypatch.setattr(oauth, "_JWKS_CACHE", {})
    import jwt

    class FakeClient:
        def __init__(self, uri, **kwargs):
            self.uri = uri

        def get_signing_key_from_jwt(self, token):
            return SimpleNamespace(key="fake-key")

    monkeypatch.setattr(jwt, "PyJWKClient", FakeClient)
    monkeypatch.setattr(jwt, "decode", lambda *a, **k: {"scope": 42})
    assert oauth.authorized("Bearer signed-content") is False
    monkeypatch.setattr(jwt, "decode", lambda *a, **k: {"scope": "mcp:tools"})
    assert oauth.authorized("Bearer signed-content") is True
    monkeypatch.setattr(jwt, "decode", lambda *a, **k: {"scope": ["mcp:tools"]})
    assert oauth.authorized("Bearer signed-content") is True


def test_oauth_header_byte_validation_rejects_non_text() -> None:
    assert oauth._credential_bytes(object()) is None


def test_http_module_main_guard_starts_server_only_with_correct_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from http import server as builtin_http

    calls = []

    class DummyServer:
        def __init__(self, address, handler):
            calls.append(("bind", address))
            self.daemon_threads = False

        def serve_forever(self, poll_interval):
            calls.append(("run", poll_interval))

    monkeypatch.setattr(builtin_http, "ThreadingHTTPServer", DummyServer)
    monkeypatch.setattr(oauth, "settings", lambda: None)
    monkeypatch.setenv("SCITOOL_MCP_BEARER_TOKEN", "fixture")
    monkeypatch.setenv("SCITOOL_STARTUP_PROBE", "0")
    monkeypatch.setenv("PORT", "0")
    runpy.run_module("scientific_toolkit_mcp.http_server", run_name="__main__")
    assert calls == [("bind", ("0.0.0.0", 0)), ("run", 0.2)]
