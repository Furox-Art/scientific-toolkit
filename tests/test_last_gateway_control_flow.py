"""Exhaust the entrypoint and bounded parser branches with controlled stdio."""

from __future__ import annotations

import io
import json
import runpy
from types import SimpleNamespace

import pytest

from scientific_toolkit_mcp import server, tools


def _stdin_bytes(data: bytes, monkeypatch: pytest.MonkeyPatch):
    output = io.StringIO()
    monkeypatch.setattr(server.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(data)))
    monkeypatch.setattr(server.sys, "stdout", output)
    monkeypatch.setattr(server, "MAX_STDIO_FRAME", 130)
    server.main()
    return [json.loads(line) for line in output.getvalue().splitlines()]


def test_oversized_single_readline_with_newline_still_rejects_then_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Exactly limit+1 bytes, with the newline inside the first bounded read.
    frame = b"{" + b" " * 129 + b"\n"
    assert len(frame) == 131
    messages = _stdin_bytes(
        frame + b'{"jsonrpc":"2.0","id":5,"method":"ping"}\n',
        monkeypatch,
    )
    assert messages[0]["error"]["code"] == -32600
    assert messages[1]["result"] == {}


def test_multichunk_rejection_drains_entire_single_frame_then_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = b"{" + b" " * (130 * 4) + b"\n"
    messages = _stdin_bytes(
        frame + b'{"jsonrpc":"2.0","id":5,"method":"ping"}\n',
        monkeypatch,
    )
    assert len(messages) == 2
    assert messages[0]["error"]["code"] == -32600
    assert messages[1]["result"] == {}


def test_runpy_module_import_does_not_start_cli_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = []
    monkeypatch.setattr(server, "main", lambda: called.append("not expected"))
    runpy.run_module("scientific_toolkit_mcp.__main__", run_name="imported_not_main")
    assert called == []


def test_stdio_server_direct_module_entrypoint_exits_on_eof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"")))
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    runpy.run_module("scientific_toolkit_mcp.server", run_name="__main__")


def test_missing_isolated_reason_executable_fails_closed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SCITOOL_REASON_BIN", raising=False)
    monkeypatch.setattr(tools.shutil, "which", lambda executable: None)
    with pytest.raises(tools.ToolFailure, match="NOT_INSTALLED"):
        tools._bin("axiomize-reason")
    assert tools._doctor({})["commands"]["axiomize-reason"]["installed"] is False
