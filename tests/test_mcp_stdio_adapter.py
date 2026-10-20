"""Unit proofs for the stdio MCP client used by the literature and NomosGuard adapters."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scientific_toolkit_mcp import tools

FAKE_SERVER = r'''
import json, sys, time
behavior = sys.argv[1]
for line in sys.stdin:
    try:
        msg = json.loads(line)
    except Exception:
        continue
    if "id" not in msg:
        continue
    rid = msg["id"]
    if msg.get("method") == "initialize":
        if behavior == "missing_initialize":
            break
        if behavior == "initialize_without_result":
            print(json.dumps({"jsonrpc": "2.0", "id": rid}), flush=True)
            break
        print(json.dumps({"jsonrpc": "2.0", "id": rid,
                          "result": {"protocolVersion": "2025-06-18"}}), flush=True)
        if behavior == "exit_after_initialize":
            break
        continue
    if behavior == "noise":
        print("", flush=True)
        print("not json", flush=True)
        print(json.dumps([1, 2]), flush=True)
        print(json.dumps({"jsonrpc": "2.0"}), flush=True)
    if behavior == "error_object":
        print(json.dumps({"jsonrpc": "2.0", "id": rid,
                          "error": {"code": -32602, "message": "bad args"}}), flush=True)
    elif behavior == "error_string":
        print(json.dumps({"jsonrpc": "2.0", "id": rid,
                          "error": "plain failure"}), flush=True)
    elif behavior == "non_object_result":
        print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": "text"}), flush=True)
    elif behavior == "is_error":
        print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": {
            "isError": True,
            "content": [{"type": "text", "text": "tool failed"}]}}), flush=True)
    elif behavior == "invalid_json_text":
        print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": {
            "content": [{"type": "text", "text": "{not json"}]}}), flush=True)
    elif behavior == "mixed_content":
        print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": {
            "content": [1, {"type": "image"}, {"type": "text", "text": "ok"}]}}), flush=True)
    elif behavior == "stderr":
        print("diagnostic", file=sys.stderr, flush=True)
        print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": {
            "content": [{"type": "text", "text": "ok"}]}}), flush=True)
    elif behavior == "slow":
        time.sleep(10)
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": {
            "content": [{"type": "text",
                         "text": json.dumps({"echo": msg.get("params", {}).get("arguments", {})})}]}}),
            flush=True)
'''


def _server(tmp_path: Path, behavior: str) -> list[str]:
    script = tmp_path / "fake_mcp_server.py"
    script.write_text(FAKE_SERVER, encoding="utf-8")
    return [sys.executable, str(script), behavior]


def test_client_initializes_and_collects_every_call(tmp_path: Path) -> None:
    report = tools._mcp(
        "fake",
        _server(tmp_path, "ok"),
        [("first", {"value": 1}), ("second", {"value": 2})],
        seconds=20,
    )
    assert report["status"] == "COMMAND_SUCCEEDED"
    assert report["exit_code"] == 0
    assert [call["tool"] for call in report["calls"]] == ["first", "second"]
    assert report["calls"][0]["json"] == {"echo": {"value": 1}}
    assert report["calls"][1]["status"] == "COMMAND_SUCCEEDED"
    assert "stderr" not in report


def test_client_ignores_blank_malformed_and_notification_lines(tmp_path: Path) -> None:
    report = tools._mcp("fake", _server(tmp_path, "noise"), [("call", {})], seconds=20)
    assert report["calls"][0]["text"] == '{"echo": {}}'


def test_client_reports_missing_initialize_as_protocol_error(tmp_path: Path) -> None:
    with pytest.raises(tools.ToolFailure, match="did not complete an MCP initialize"):
        tools._mcp("fake", _server(tmp_path, "missing_initialize"), [("call", {})], seconds=20)


def test_client_reports_initialize_without_a_result(tmp_path: Path) -> None:
    with pytest.raises(tools.ToolFailure, match="did not complete an MCP initialize"):
        tools._mcp("fake", _server(tmp_path, "initialize_without_result"),
                   [("call", {})], seconds=20)


def test_client_reports_a_call_the_server_never_answers(tmp_path: Path) -> None:
    with pytest.raises(tools.ToolFailure, match="did not answer tools/call 'call'"):
        tools._mcp("fake", _server(tmp_path, "exit_after_initialize"),
                   [("call", {})], seconds=20)


def test_client_reports_upstream_error_objects(tmp_path: Path) -> None:
    with pytest.raises(tools.ToolFailure, match="UPSTREAM_ERROR: fake call: bad args"):
        tools._mcp("fake", _server(tmp_path, "error_object"), [("call", {})], seconds=20)


def test_client_reports_plain_upstream_error_strings(tmp_path: Path) -> None:
    with pytest.raises(tools.ToolFailure, match="UPSTREAM_ERROR: fake call: plain failure"):
        tools._mcp("fake", _server(tmp_path, "error_string"), [("call", {})], seconds=20)


def test_client_rejects_a_non_object_result(tmp_path: Path) -> None:
    with pytest.raises(tools.ToolFailure, match="returned no result"):
        tools._mcp("fake", _server(tmp_path, "non_object_result"), [("call", {})], seconds=20)


def test_client_marks_an_upstream_tool_error_as_failed(tmp_path: Path) -> None:
    report = tools._mcp("fake", _server(tmp_path, "is_error"), [("call", {})], seconds=20)
    assert report["status"] == "COMMAND_FAILED"
    assert report["calls"][0]["status"] == "COMMAND_FAILED"
    assert report["calls"][0]["text"] == "tool failed"


def test_client_keeps_non_json_text_without_a_parsed_view(tmp_path: Path) -> None:
    report = tools._mcp("fake", _server(tmp_path, "invalid_json_text"), [("call", {})], seconds=20)
    assert report["calls"][0]["text"] == "{not json"
    assert "json" not in report["calls"][0]


def test_client_concatenates_only_text_content_items(tmp_path: Path) -> None:
    report = tools._mcp("fake", _server(tmp_path, "mixed_content"), [("call", {})], seconds=20)
    assert report["calls"][0]["text"] == "ok"


def test_client_preserves_stderr_diagnostics(tmp_path: Path) -> None:
    report = tools._mcp("fake", _server(tmp_path, "stderr"), [("call", {})], seconds=20)
    assert report["stderr"] == "diagnostic"


def test_client_truncates_oversized_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "MAX_OUTPUT", 4)
    report = tools._mcp("fake", _server(tmp_path, "ok"), [("call", {})], seconds=20)
    assert report["calls"][0]["text"] == '{"ec'
    assert report["calls"][0]["truncated"] is True


def test_client_times_out_and_kills_a_silent_server(tmp_path: Path) -> None:
    started = time.monotonic()
    with pytest.raises(tools.ToolFailure, match="TIMEOUT: fake exceeded 1s"):
        tools._mcp("fake", _server(tmp_path, "slow"), [("call", {})], seconds=1)
    assert time.monotonic() - started < 8


def test_client_reports_an_unlaunchable_program() -> None:
    with pytest.raises(tools.ToolFailure, match="EXECUTION_ERROR"):
        tools._mcp("fake", ["/definitely/not/a/program"], [("call", {})], seconds=2)


@pytest.mark.parametrize("seconds", [True, 0, -1, tools.MAX_CALL_TIMEOUT + 1, 1.5, "1"])
def test_client_rejects_unbounded_timeouts(seconds: object) -> None:
    with pytest.raises(tools.ToolFailure, match="timeout must be an integer"):
        tools._mcp("fake", [sys.executable], [("call", {})], seconds=seconds)  # type: ignore[arg-type]


class _BrokenStdin:
    def write(self, _payload: str) -> None:
        raise BrokenPipeError("closed")

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


class _FakeProcess:
    def __init__(self, stdout: list[str], wait_error: bool = False) -> None:
        self.stdin = _BrokenStdin()
        self.stdout = iter(stdout)
        self.returncode = 0
        self.killed = False
        self._wait_error = wait_error

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> int:
        if self._wait_error:
            self._wait_error = False
            raise subprocess.TimeoutExpired("fake", timeout)
        return 0


def test_client_reports_a_broken_stdin_pipe(monkeypatch: pytest.MonkeyPatch) -> None:
    process = _FakeProcess([])
    monkeypatch.setattr(tools.subprocess, "Popen", lambda *a, **k: process)
    with pytest.raises(tools.ToolFailure, match="EXECUTION_ERROR: BrokenPipeError"):
        tools._mcp("fake", [sys.executable], [("call", {})], seconds=5)
    assert process.killed


def test_client_ignores_an_error_while_closing_stdin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replies = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}) + "\n",
        json.dumps({"jsonrpc": "2.0", "id": 2, "result": {
            "content": [{"type": "text", "text": "ok"}]}}) + "\n",
    ]
    process = _FakeProcess(replies)

    class ClosingStdin:
        def write(self, payload: str) -> None:
            pass

        def flush(self) -> None:
            pass

        def close(self) -> None:
            raise OSError("already closed")

    process.stdin = ClosingStdin()
    monkeypatch.setattr(tools.subprocess, "Popen", lambda *a, **k: process)
    report = tools._mcp("fake", [sys.executable], [("call", {})], seconds=5)
    assert report["calls"][0]["text"] == "ok"


def test_client_kills_a_server_that_ignores_eof(monkeypatch: pytest.MonkeyPatch) -> None:
    replies = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}) + "\n",
        json.dumps({"jsonrpc": "2.0", "id": 2, "result": {
            "content": [{"type": "text", "text": "ok"}]}}) + "\n",
    ]
    process = _FakeProcess(replies)
    # Popen is replaced after construction so the real __init__ would never run;
    # wait() is the branch under test, not the process handshake.
    process.stdin = type("Stdin", (), {
        "write": lambda self, payload: None,
        "flush": lambda self: None,
        "close": lambda self: None,
    })()
    process._wait_error = True
    monkeypatch.setattr(tools.subprocess, "Popen", lambda *a, **k: process)
    report = tools._mcp("fake", [sys.executable], [("call", {})], seconds=5)
    assert report["calls"][0]["text"] == "ok"
    assert process.killed


def test_module_argv_uses_the_running_interpreter_for_an_importable_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SCITOOL_NOMOSGUARD_BIN", raising=False)
    monkeypatch.setattr(tools.importlib.util, "find_spec", lambda name: object())
    argv = tools._module_argv("nomosguard")
    assert argv[1:] == ["-m", "nomosguard.mcp_stdio"]
    assert Path(argv[0]).name.startswith("python")


def test_module_argv_accepts_an_explicit_interpreter_without_importing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCITOOL_NOMOSGUARD_BIN", sys.executable)

    def forbidden(name: str) -> object:
        raise AssertionError("an explicit interpreter is the operator's responsibility")

    monkeypatch.setattr(tools.importlib.util, "find_spec", forbidden)
    assert tools._module_argv("nomosguard")[1:] == ["-m", "nomosguard.mcp_stdio"]


@pytest.mark.parametrize("bad", ["", "   "])
def test_module_argv_rejects_an_empty_override(bad: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCITOOL_NOMOSGUARD_BIN", bad)
    with pytest.raises(tools.ToolFailure, match="BAD_CONFIGURATION"):
        tools._module_argv("nomosguard")


def test_module_argv_rejects_a_null_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools.os, "environ", {"SCITOOL_NOMOSGUARD_BIN": "bad\x00python"})
    with pytest.raises(tools.ToolFailure, match="BAD_CONFIGURATION"):
        tools._module_argv("nomosguard")


def test_module_argv_reports_a_missing_interpreter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCITOOL_NOMOSGUARD_BIN", "/definitely/not/a/python")
    with pytest.raises(tools.ToolFailure, match="NOT_INSTALLED"):
        tools._module_argv("nomosguard")


@pytest.mark.parametrize("failure", [None, ImportError("broken"), ValueError("broken")])
def test_module_argv_reports_a_missing_module(
    failure: Exception | None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SCITOOL_NOMOSGUARD_BIN", raising=False)
    if isinstance(failure, Exception):
        def raise_failure(name: str) -> object:
            raise failure

        monkeypatch.setattr(tools.importlib.util, "find_spec", raise_failure)
    else:
        monkeypatch.setattr(tools.importlib.util, "find_spec", lambda name: None)
    with pytest.raises(tools.ToolFailure, match="NOT_INSTALLED: Python module"):
        tools._module_argv("nomosguard")


def test_literature_binary_resolves_and_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools.shutil, "which", lambda name: "/fake/literature-evidence-mcp")
    assert tools._bin("literature-evidence") == "/fake/literature-evidence-mcp"
    monkeypatch.setenv("SCITOOL_LIT_EVIDENCE_BIN", "")
    with pytest.raises(tools.ToolFailure, match="BAD_CONFIGURATION"):
        tools._bin("literature-evidence")
    monkeypatch.setenv("SCITOOL_LIT_EVIDENCE_BIN", "/not/installed")
    monkeypatch.setattr(tools.shutil, "which", lambda name: None)
    with pytest.raises(tools.ToolFailure, match="NOT_INSTALLED"):
        tools._bin("literature-evidence")


def test_literature_search_forwards_a_bounded_request(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple] = []

    def fake_mcp(key, argv, calls, *, seconds=30):
        seen.append((key, argv, calls, seconds))
        return {"status": "COMMAND_SUCCEEDED"}

    monkeypatch.setattr(tools, "_bin", lambda key: "/fake/lit")
    monkeypatch.setattr(tools, "_mcp", fake_mcp)
    assert tools._lit_search({"query": "quantum", "limit_per_source": 3})["status"] == "COMMAND_SUCCEEDED"
    assert tools._lit_search({"query": "quantum"})["status"] == "COMMAND_SUCCEEDED"
    assert seen == [
        ("literature-evidence", ["/fake/lit"],
         [("search_literature", {"query": "quantum", "limit_per_source": 3})], 60),
        ("literature-evidence", ["/fake/lit"],
         [("search_literature", {"query": "quantum", "limit_per_source": 10})], 60),
    ]


@pytest.mark.parametrize("limit", [True, "10", 1.0, 0, 26])
def test_literature_search_rejects_invalid_limits(limit: object) -> None:
    with pytest.raises(tools.ToolFailure, match="limit_per_source"):
        tools._lit_search({"query": "quantum", "limit_per_source": limit})


def test_literature_search_rejects_an_empty_query() -> None:
    with pytest.raises(tools.ToolFailure, match="query must be a nonempty string"):
        tools._lit_search({"query": " "})


def test_quote_verification_forwards_the_exact_request(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple] = []

    def fake_mcp(key, argv, calls, *, seconds=30):
        seen.append((key, argv, calls, seconds))
        return {"status": "COMMAND_SUCCEEDED"}

    monkeypatch.setattr(tools, "_bin", lambda key: "/fake/lit")
    monkeypatch.setattr(tools, "_mcp", fake_mcp)
    request = {"quote": "exact words", "source_text": "the exact words appear here", "source_id": "doc"}
    assert tools._lit_verify(request)["status"] == "COMMAND_SUCCEEDED"
    assert seen == [("literature-evidence", ["/fake/lit"],
                     [("verify_claim", request)], 30)]


def test_quote_verification_enforces_the_encoded_size_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tools, "MAX_INPUT_BYTES", 8)
    with pytest.raises(tools.ToolFailure, match="quote verification input is too large"):
        tools._lit_verify({"quote": "q", "source_text": "s", "source_id": "id"})


@pytest.mark.parametrize("missing", ["quote", "source_text", "source_id"])
def test_quote_verification_requires_all_three_fields(missing: str) -> None:
    request = {"quote": "q", "source_text": "s", "source_id": "id"}
    request.pop(missing)
    with pytest.raises(tools.ToolFailure, match=missing):
        tools._lit_verify(request)


def test_nomosguard_asserts_derives_and_decides_in_one_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple] = []

    def fake_mcp(key, argv, calls, *, seconds=30):
        seen.append((key, argv, calls, seconds))
        return {"status": "COMMAND_SUCCEEDED"}

    monkeypatch.setattr(tools, "_module_argv", lambda key: ["python", "-m", "nomosguard.mcp_stdio"])
    monkeypatch.setattr(tools, "_mcp", fake_mcp)
    claims = [
        {"kind": "exposure", "payload": {"service": "api"}, "evidence": "public ingress"},
        {"kind": "credential", "payload": {"scope": "admin"}, "evidence": "token scope admin"},
    ]
    assert tools._nomos_decide({"claims": claims, "fallback": "ALERT"})["status"] == "COMMAND_SUCCEEDED"
    assert seen == [(
        "nomosguard", ["python", "-m", "nomosguard.mcp_stdio"],
        [("assert_claim", claims[0]), ("assert_claim", claims[1]),
         ("derive_paths", {}), ("decide", {"fallback": "ALERT"})],
        60,
    )]


def test_nomosguard_defaults_to_block(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple] = []
    monkeypatch.setattr(tools, "_module_argv", lambda key: ["python", "-m", "nomosguard.mcp_stdio"])
    monkeypatch.setattr(tools, "_mcp", lambda key, argv, calls, *, seconds=30: seen.append(calls) or {})
    claim = {"kind": "k", "payload": {}, "evidence": "e"}
    tools._nomos_decide({"claims": [claim]})
    assert seen == [[("assert_claim", claim), ("derive_paths", {}), ("decide", {"fallback": "BLOCK"})]]


@pytest.mark.parametrize("fallback", ["ALLOW", "block", "", None, 1])
def test_nomosguard_rejects_a_non_fail_closed_fallback(fallback: object) -> None:
    with pytest.raises(tools.ToolFailure, match="fallback must be BLOCK or ALERT"):
        tools._nomos_decide({"claims": [{"kind": "k", "payload": {}, "evidence": "e"}],
                             "fallback": fallback})


@pytest.mark.parametrize("claims", [None, {}, "x", [], [{}] * 21])
def test_nomosguard_rejects_invalid_claim_lists(claims: object) -> None:
    with pytest.raises(tools.ToolFailure, match="claims must be a list"):
        tools._nomos_decide({"claims": claims})


@pytest.mark.parametrize(
    ("claim", "message"),
    [
        ("not a dict", "needs exactly kind, payload, evidence"),
        ({"kind": "k", "payload": {}}, "needs exactly kind, payload, evidence"),
        ({"kind": "k", "payload": {}, "evidence": "e", "extra": 1}, "needs exactly"),
        ({"kind": "k", "payload": [], "evidence": "e"}, "payload must be an object"),
        ({"kind": " ", "payload": {}, "evidence": "e"}, "kind must be a nonempty string"),
        ({"kind": "k", "payload": {}, "evidence": ""}, "evidence must be a nonempty string"),
    ],
)
def test_nomosguard_rejects_schema_invalid_claims(claim: object, message: str) -> None:
    with pytest.raises(tools.ToolFailure, match=message):
        tools._nomos_decide({"claims": [claim]})


def test_nomosguard_enforces_the_encoded_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "MAX_INPUT_BYTES", 8)
    with pytest.raises(tools.ToolFailure, match="claims are too large"):
        tools._nomos_decide({"claims": [{"kind": "k", "payload": {}, "evidence": "e"}]})


def test_doctor_reports_module_servers_with_their_import_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SCITOOL_NOMOSGUARD_BIN", raising=False)
    monkeypatch.setattr(tools.importlib.util, "find_spec", lambda name: None)
    info = tools._doctor({})["commands"]["nomosguard"]
    assert info == {
        "installed": False,
        "executable": tools.shutil.which(sys.executable),
        "override": "SCITOOL_NOMOSGUARD_BIN",
        "module": "nomosguard.mcp_stdio",
    }


def test_doctor_trusts_an_explicit_interpreter_even_without_the_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCITOOL_NOMOSGUARD_BIN", sys.executable)
    monkeypatch.setattr(tools.importlib.util, "find_spec", lambda name: None)
    assert tools._doctor({})["commands"]["nomosguard"]["installed"] is True


def test_doctor_treats_an_unresolvable_module_as_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SCITOOL_NOMOSGUARD_BIN", raising=False)

    def broken(name: str) -> object:
        raise ValueError("broken spec")

    monkeypatch.setattr(tools.importlib.util, "find_spec", broken)
    assert tools._doctor({})["commands"]["nomosguard"]["installed"] is False


def test_doctor_counts_all_catalogued_repositories(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SCITOOL_NOMOSGUARD_BIN", raising=False)
    monkeypatch.setattr(tools.importlib.util, "find_spec", lambda name: object())
    report = tools._doctor({})
    assert report["repositories"] == 9
    assert report["commands"]["nomosguard"]["installed"] is True
