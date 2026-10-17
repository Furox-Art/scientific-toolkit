"""Stdio handler fault isolation, notification, frame size and entrypoint tests."""

from __future__ import annotations

import io
import json
import runpy
from types import SimpleNamespace

import pytest

from scientific_toolkit_mcp import server
from scientific_toolkit_mcp.tools import ToolFailure


def _msg(method: str, *, params: object = None) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 4,
        "method": method,
        "params": {} if params is None else params,
    }


@pytest.mark.parametrize(
    ("message", "code"),
    [
        (None, -32600),
        ({"jsonrpc": "2.0", "id": "a"}, -32600),
        ({"jsonrpc": "1.0", "method": "ping", "id": 1}, -32600),
        ({"jsonrpc": "2.0", "method": True, "id": 1}, -32600),
        (_msg("ping", params=[]), -32602),
        (_msg("tools/call", params={"name": 100}), -32602),
        (_msg("tools/call", params={"name": "injected"}), -32602),
        (_msg("unknown"), -32601),
    ],
)
def test_invalid_rpc_requests_do_not_crash_dispatcher(message, code: int) -> None:
    assert server.handle(message)["error"]["code"] == code


def test_standard_rpc_results_and_notification_contract() -> None:
    assert server.handle(_msg("ping"))["result"] == {}
    assert server.handle(_msg("tools/list"))["result"]["tools"] == server.TOOLS
    assert (
        server.handle(_msg("initialize"))["result"]["protocolVersion"] == server.PROTO
    )
    assert server.handle({"jsonrpc": "2.0", "method": "ping"}) is None


@pytest.mark.parametrize(
    "failure",
    [
        ToolFailure("validation failure"),
        ValueError("invalid schema"),
        TypeError("unsupported argument"),
        OverflowError("not finite"),
    ],
)
def test_expected_tool_failures_return_iserror_without_process_crash(
    failure: Exception,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(name, arguments):
        raise failure

    monkeypatch.setattr(server, "dispatch", fail)
    reply = server.handle(_msg("tools/call", params={"name": "cds_stats"}))
    assert reply["result"]["isError"] is True
    assert str(failure) in reply["result"]["content"][0]["text"]


def test_unexpected_tool_exceptions_are_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(name, arguments):
        raise RuntimeError("private token do not print")

    monkeypatch.setattr(server, "dispatch", fail)
    reply = server.handle(_msg("tools/call", params={"name": "cds_stats"}))
    assert reply["result"]["isError"] is True
    assert reply["result"]["content"][0]["text"] == "INTERNAL_ERROR: RuntimeError"


def test_upstream_returned_command_failure_is_not_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        server,
        "dispatch",
        lambda name, args: {"status": "COMMAND_FAILED", "exit_code": 3},
    )
    reply = server.handle(_msg("tools/call", params={"name": "cds_stats"}))
    assert reply["result"]["isError"] is True
    assert json.loads(reply["result"]["content"][0]["text"])["exit_code"] == 3


def _run_stdio(
    frames: bytes,
    monkeypatch: pytest.MonkeyPatch,
    *,
    limit: int = 128,
) -> list[dict]:
    out = io.StringIO()
    monkeypatch.setattr(server, "MAX_STDIO_FRAME", limit)
    monkeypatch.setattr(server.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(frames)))
    monkeypatch.setattr(server.sys, "stdout", out)
    server.main()
    return [json.loads(x) for x in out.getvalue().splitlines()]


def test_stdio_ignores_blank_frames_and_recovers_after_broken_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = _run_stdio(
        b"\n \n"
        b'{"jsonrpc":"2.0","id":1,"method":"ping",}\n'
        b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
        b'{"jsonrpc":"2.0","id":2,"method":"ping"}\n',
        monkeypatch,
    )
    assert len(responses) == 2
    assert responses[0]["error"]["code"] == -32700
    assert responses[1]["result"] == {}


@pytest.mark.parametrize("newline", [b"\n", b""])
def test_stdio_oversize_frame_is_rejected_and_bounded(
    newline: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oversize = b"{" + b" " * 160 + newline
    frames = oversize + b'{"jsonrpc":"2.0","id":2,"method":"ping"}\n'
    responses = _run_stdio(frames, monkeypatch, limit=130)
    assert responses[0]["error"]["code"] == -32600
    if newline:
        assert responses[1]["result"] == {}
    else:
        # Without a newline the later bytes belong to the rejected frame.
        assert len(responses) == 1


def test_stdio_broken_pipe_does_not_crash_or_continue_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NoOutput:
        def write(self, text):
            raise BrokenPipeError

    monkeypatch.setattr(server.sys, "stdout", NoOutput())
    monkeypatch.setattr(
        server.sys,
        "stdin",
        SimpleNamespace(
            buffer=io.BytesIO(b'{"jsonrpc":"2.0","id":2,"method":"ping"}\n')
        ),
    )
    server.main()


def test_python_module_entrypoint_routes_to_stdio_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    monkeypatch.setattr(server, "main", lambda: calls.append("started"))
    runpy.run_module("scientific_toolkit_mcp.__main__", run_name="__main__")
    assert calls == ["started"]
