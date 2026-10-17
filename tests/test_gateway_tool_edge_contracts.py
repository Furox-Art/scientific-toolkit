"""Executable protocol proofs for previously untested gateway edge paths."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scientific_toolkit_mcp import tools


@pytest.mark.parametrize("bad", ["", " ", 1, False, [], "x" * 4001])
def test_string_validation_rejects_non_text_and_oversized_input(bad: object) -> None:
    with pytest.raises(tools.ToolFailure, match="nonempty string"):
        tools._str(bad, "prompt")


@pytest.mark.parametrize("bad", ["", " "])
def test_executable_override_does_not_accept_unsafe_path(
    bad: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCITOOL_CDS_BIN", bad)
    with pytest.raises(tools.ToolFailure, match="BAD_CONFIGURATION"):
        tools._bin("cds")


def test_null_in_executable_path_is_refused_even_if_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # POSIX forbids null bytes in real envvars; check the guard by injecting
    # an environment mapping directly, without relaxing OS restrictions.
    monkeypatch.setattr(tools.os, "environ", {"SCITOOL_CDS_BIN": "bad\x00binary"})
    with pytest.raises(tools.ToolFailure, match="BAD_CONFIGURATION"):
        tools._bin("cds")


def test_isolated_reason_executable_is_detected_in_explicit_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SCITOOL_REASON_BIN", raising=False)
    exe = tmp_path / ".reason-env" / "bin" / "axiomize-reason"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\nexit 0\n")
    monkeypatch.setattr(tools.shutil, "which", lambda name: None)
    assert tools._bin("axiomize-reason") == str(exe)
    assert tools._doctor({})["commands"]["axiomize-reason"]["installed"]


def test_module_provider_discovery_detects_file_and_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "unknown_module").mkdir()
    (second / "unknown_module.py").write_text("value = 1\n")
    monkeypatch.setattr(tools.sys, "path", ["", str(first), str(second)])
    assert tools.module_providers("unknown_module") == [
        str(first / "unknown_module"),
        str(second / "unknown_module.py"),
    ]


def test_missing_pinned_distribution_and_explicit_pin_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tools, "module_providers", lambda module: [])
    monkeypatch.setenv("SCITOOL_PIN_AXIOMIZE", "99.99.99")

    def missing(_):
        raise tools.metadata.PackageNotFoundError("axiomize")

    monkeypatch.setattr(tools.metadata, "version", missing)
    with pytest.raises(tools.ToolFailure, match="version mismatch"):
        tools._verify_pinned_distribution("axiomize")


def test_subprocess_results_preserve_truncation_and_missing_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tools, "_bin", lambda _: "/fake/tool")
    monkeypatch.setattr(tools, "MAX_OUTPUT", 12)

    def run(*args, **kwargs):
        return SimpleNamespace(
            stdout='{"incomplete": x' + "extra",
            stderr="diagnostic\n",
            returncode=4,
        )

    monkeypatch.setattr(tools.subprocess, "run", run)
    report = tools._call("cds", ["stats", "1,2"])
    assert report["status"] == "COMMAND_FAILED"
    assert report["exit_code"] == 4
    assert report["truncated"] is True
    assert report["stderr"] == "diagnostic"
    assert "json" not in report


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (OSError("unavailable"), "EXECUTION_ERROR: OSError"),
        (subprocess.TimeoutExpired(["test"], timeout=1), "TIMEOUT"),
    ],
)
def test_subprocess_faults_are_reported_not_swallowed(
    failure: Exception,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tools, "_bin", lambda _: "/fake/tool")

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(tools.subprocess, "run", fail)
    with pytest.raises(tools.ToolFailure, match=expected):
        tools._call("cds", ["stats", "1,2"], seconds=1)


@pytest.mark.parametrize("seconds", [True, 0, -1, 100000, 1.2])
def test_gateway_rejects_invalid_process_timeout(
    seconds: object,
) -> None:
    with pytest.raises(tools.ToolFailure, match="timeout must be"):
        tools._call("cds", ["stats"], seconds=seconds)


def test_conservative_model_builds_structured_file_without_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = []

    def fake_call(name, args, *, seconds=30):
        assert name == "axiomize"
        assert args[:3] == ["model", "--action", "validate"]
        assert args[3] == "--input-json"
        contents = json.loads(Path(args[4]).read_text())
        observed.append((contents, seconds))
        return {"status": "COMMAND_SUCCEEDED"}

    monkeypatch.setattr(tools, "_call", fake_call)
    assert (
        tools._model({"action": "validate", "request": {"alpha": "β"}})["status"]
        == "COMMAND_SUCCEEDED"
    )
    assert observed == [({"alpha": "β"}, 60)]


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "validate", "request": None},
        {"action": "simulate", "request": []},
    ],
)
def test_model_rejects_non_object_request(payload: dict) -> None:
    with pytest.raises(tools.ToolFailure, match="request must be a JSON object"):
        tools._model(payload)


def test_model_rejects_too_large_json_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "MAX_INPUT_BYTES", 2)
    with pytest.raises(tools.ToolFailure, match="too large"):
        tools._model({"action": "validate", "request": {"a": "long text"}})


def test_workspace_validation_does_not_accept_non_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCITOOL_WORKSPACE_DIR", str(tmp_path / "absent"))
    with pytest.raises(tools.ToolFailure, match="does not exist"):
        tools._workspace()
    monkeypatch.setenv("SCITOOL_WORKSPACE_DIR", str(tmp_path))
    assert tools._workspace() == tmp_path


@pytest.mark.parametrize(
    ("message", "error"),
    [
        ({"role": "observer", "content": "valid"}, "unsupported message role"),
        ({"role": "user", "content": "x", "extra": 2}, "exactly role"),
        ("invalid", "exactly role"),
    ],
)
def test_eq_route_rejects_schema_invalid_transcripts(
    message: object,
    error: str,
) -> None:
    with pytest.raises(tools.ToolFailure, match=error):
        tools._eq_route({"messages": [message]})


def test_eq_route_enforces_encoded_bytes_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tools, "MAX_INPUT_BYTES", 2)
    with pytest.raises(tools.ToolFailure, match="transcript is too large"):
        tools._eq_route({"messages": [{"role": "user", "content": "valid"}]})


@pytest.mark.parametrize("mode", ["unsupported", None, 7])
def test_eq_route_rejects_unknown_modes(mode: object) -> None:
    with pytest.raises(tools.ToolFailure, match="intent_mode"):
        tools._eq_route(
            {
                "intent_mode": mode,
                "messages": [{"role": "user", "content": "hi"}],
            }
        )


@pytest.mark.parametrize("bad", [None, [], "not a list", [{}] * 21])
def test_eq_route_rejects_absent_or_excessive_messages(bad: object) -> None:
    with pytest.raises(tools.ToolFailure, match="messages must be a list"):
        tools._eq_route({"messages": bad})


def test_trusted_explicit_audit_switch_reaches_real_handler_only_when_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCITOOL_ALLOW_AUDIT_EXECUTION", "1")
    monkeypatch.setenv("SCITOOL_WORKSPACE_DIR", str(tmp_path))
    calls = []

    def fake_call(key, argv, *, seconds=30):
        calls.append((key, argv, seconds))
        return {"status": "COMMAND_SUCCEEDED"}

    monkeypatch.setattr(tools, "_call", fake_call)
    assert tools._audit({})["status"] == "COMMAND_SUCCEEDED"
    assert calls == [("plan-auditor", ["audit", str(tmp_path)], 120)]
