"""HTTP negotiation and startup tests for security-critical edge branches."""

from __future__ import annotations

import pytest

from scientific_toolkit_mcp import http_server


@pytest.mark.parametrize(
    ("accept", "permitted"),
    [
        (["", "application/json, text/event-stream"], True),
        (["text/event-stream;q=1", "application/json;q=0.9"], True),
        (["application/json; q=abc,text/event-stream"], False),
        (["application/json; q=1;q=0.9,text/event-stream"], False),
        (["application/json; q=1; no-value,text/event-stream"], False),
        (["application/json; q=nan,text/event-stream"], False),
        (["application/json; q=0,text/event-stream"], False),
        (["application/json,text/event-stream;q=0"], False),
    ],
)
def test_accept_negotiation_refuses_incompatible_and_ambiguous_media(
    accept: list[str],
    permitted: bool,
) -> None:
    assert http_server._accepts_mcp(accept) is permitted


@pytest.mark.parametrize(
    ("media", "allowed"),
    [
        ("application/json", True),
        ("application/json; charset=utf-8", True),
        ('APPLICATION/JSON; charset="UTF-8"', True),
        ("application/json; charset=utf-16", False),
        ("application/json; charset=utf-8; charset=utf-8", False),
        ("application/json; boundary=anything", False),
        ("text/plain", False),
    ],
)
def test_json_wire_contract_restricts_content_type(media: str, allowed: bool) -> None:
    assert http_server._valid_json_content_type(media) == allowed


def test_same_ip_rate_bucket_expires_without_full_global_sweep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with http_server._lock:
        http_server._hits.clear()
        http_server._last_sweep = 100.0
        monkeypatch.setattr(http_server, "WINDOW_SECONDS", 60)
        assert http_server._record_rate_hit("192.0.2.1", 111.0)
        http_server._hits["192.0.2.1"].appendleft(1.0)
        assert http_server._record_rate_hit("192.0.2.1", 113.0)
        assert list(http_server._hits["192.0.2.1"]) == [111.0, 113.0]
        http_server._hits.clear()
        http_server._last_sweep = 0.0


def test_http_main_denies_unconfigured_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SCITOOL_MCP_BEARER_TOKEN", raising=False)
    monkeypatch.setattr(http_server.oauth, "settings", lambda: None)
    with pytest.raises(RuntimeError, match="Configure either a bearer"):
        http_server.main()


@pytest.mark.parametrize("startup_probe", [False, True])
def test_http_main_starts_with_trusted_binding_and_optional_probe(
    monkeypatch: pytest.MonkeyPatch,
    startup_probe: bool,
) -> None:
    observed = []
    monkeypatch.setenv("SCITOOL_MCP_BEARER_TOKEN", "test-only")
    monkeypatch.setenv("PORT", "8036")
    monkeypatch.setenv("SCITOOL_STARTUP_PROBE", "1" if startup_probe else "0")
    monkeypatch.setattr(http_server.oauth, "settings", lambda: None)

    class FakeServer:
        def __init__(self, address, handler):
            observed.append(("bind", address, handler))
            self.daemon_threads = False

        def serve_forever(self, poll_interval):
            observed.append(("serve", poll_interval, self.daemon_threads))

    monkeypatch.setattr(http_server, "ThreadingHTTPServer", FakeServer)

    class StubThread:
        def __init__(self, *, target, name, daemon):
            observed.append(("thread", name, daemon))
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(http_server.threading, "Thread", StubThread)
    monkeypatch.setattr(
        http_server.time, "sleep", lambda _: observed.append(("sleep",))
    )

    from scientific_toolkit_mcp import production_probe

    monkeypatch.setattr(
        production_probe,
        "probe",
        lambda port: observed.append(("probe", port)) or True,
    )
    http_server.main()
    assert observed[0][0] == "bind"
    assert observed[0][1] == ("0.0.0.0", 8036)
    assert observed[-1] == ("serve", 0.2, True)
    assert (
        ("probe", 8036) in observed
        if startup_probe
        else ("probe", 8036) not in observed
    )
