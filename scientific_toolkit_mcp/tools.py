"""Allowlisted MCP adapters; never evaluate arbitrary Python or shell commands.

The original upstream distributions are installed separately. Every response
contains the actual subprocess return code; a failed or absent program is never
reported as a successful scientific result.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

from .catalog import catalog

MAX_INPUT_BYTES = 65536
MAX_OUTPUT = 32768


class ToolFailure(Exception):
    """Expected fail-closed adapter error."""


BINS = {
    "axiomize": ("SCITOOL_AXIOMIZE_BIN", "axiomize"),
    "cds": ("SCITOOL_CDS_BIN", "cds"),
    "cds2": ("SCITOOL_CDS2_BIN", "cds2"),
    "plan-auditor": ("SCITOOL_AUDITOR_BIN", "plan-auditor"),
    "quantum-reasoning": ("SCITOOL_QUANTUM_BIN", "quantum-reasoning"),
    "axiomize-reason": ("SCITOOL_REASON_BIN", "axiomize-reason"),
    "eq-layer": ("SCITOOL_EQ_BIN", "eq-layer"),
}


def _check_only(args: dict, allowed: set[str]) -> None:
    if not isinstance(args, dict):
        raise ToolFailure("INVALID_ARGUMENT: tool arguments must be an object")
    unknown = set(args) - allowed
    if unknown:
        raise ToolFailure(f"INVALID_ARGUMENT: unexpected keys: {sorted(unknown)}")


def _str(value: Any, label: str, limit: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ToolFailure(f"INVALID_ARGUMENT: {label} must be a nonempty string <= {limit} characters")
    return value


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ToolFailure(f"INVALID_ARGUMENT: {label} must be numeric")
    n = float(value)
    if not math.isfinite(n):
        raise ToolFailure(f"INVALID_ARGUMENT: {label} must be finite")
    return n


def _unit(value: Any, label: str) -> float:
    n = _number(value, label)
    if n < 0 or n > 1:
        raise ToolFailure(f"INVALID_ARGUMENT: {label} must be between 0 and 1")
    return n


def _bin(key: str) -> str:
    env, name = BINS[key]
    program = os.environ.get(env, name)
    # Do not interpret an environment override as shell arguments.
    if not program.strip() or "\x00" in program:
        raise ToolFailure(f"BAD_CONFIGURATION: {env} is invalid")
    found = shutil.which(program)
    if found is None and key == "axiomize-reason" and env not in os.environ:
        isolated = Path.cwd() / ".reason-env" / "bin" / "axiomize-reason"
        if isolated.is_file():
            found = str(isolated)
    if found is None:
        raise ToolFailure(f"NOT_INSTALLED: {name} is not available (override with {env})")
    return found


def _call(key: str, argv: list[str], *, seconds: int = 30) -> dict:
    program = _bin(key)
    try:
        completed = subprocess.run(
            [program, *argv], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=seconds, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolFailure(f"TIMEOUT: {key} exceeded {seconds}s") from exc
    except OSError as exc:
        raise ToolFailure(f"EXECUTION_ERROR: {type(exc).__name__}: {exc}") from exc
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    # Distinguish success/UNKNOWN/failure from tools' own exit codes. Never
    # relabel exit=0 as audit PASS for commands that only inspect or validate.
    result: dict[str, Any] = {
        "program": key,
        "exit_code": completed.returncode,
        "status": "COMMAND_SUCCEEDED" if completed.returncode == 0 else "COMMAND_FAILED",
        "stdout": stdout[:MAX_OUTPUT],
    }
    if stderr:
        result["stderr"] = stderr[:4000]
    if len(stdout) > MAX_OUTPUT:
        result["truncated"] = True
    if stdout.startswith("{"):
        try:
            result["json"] = json.loads(stdout)
        except json.JSONDecodeError:
            pass
    return result


def _stats(args: dict, key: str) -> dict:
    _check_only(args, {"values"})
    values = args.get("values")
    if not isinstance(values, list) or not 2 <= len(values) <= 1000:
        raise ToolFailure("INVALID_ARGUMENT: values must be an array of 2..1000 numbers")
    csv = ",".join(format(_number(x, f"values[{i}]"), ".12g") for i, x in enumerate(values))
    # NumPy/SciPy cold imports can exceed 30s on the 0.1-CPU Render Free tier.
    # This is an execution timeout only; no scientific acceptance criteria change.
    return _call(key, ["stats", csv], seconds=90 if key == "cds2" else 30)


def _model(args: dict) -> dict:
    _check_only(args, {"action", "request"})
    action = args.get("action")
    # Intentionally exclude repair/heavy/export with surprising side effects.
    if action not in {"validate", "simulate", "validity", "uncertainty", "stability", "numerical-verify"}:
        raise ToolFailure("INVALID_ARGUMENT: action is not in the conservative allowlist")
    request = args.get("request")
    if not isinstance(request, dict):
        raise ToolFailure("INVALID_ARGUMENT: request must be a JSON object")
    encoded = json.dumps(request, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ToolFailure("INVALID_ARGUMENT: request is too large")
    # Create a temporary file for the already-structured Model IR request.
    # Never pass a user-selected filesystem path or shell command.
    with tempfile.TemporaryDirectory(prefix="scitool_") as td:
        inp = Path(td) / "model.json"
        inp.write_text(encoded, encoding="utf-8")
        return _call("axiomize", ["model", "--action", action, "--input-json", str(inp)], seconds=60)


def _workspace() -> Path:
    raw = os.environ.get("SCITOOL_WORKSPACE_DIR")
    if not raw:
        raise ToolFailure("NOT_CONFIGURED: set SCITOOL_WORKSPACE_DIR to a trusted local project directory")
    p = Path(raw).expanduser().resolve()
    if not p.is_dir():
        raise ToolFailure("NOT_CONFIGURED: configured workspace directory does not exist")
    return p


def _eq_route(args: dict) -> dict:
    _check_only(args, {"messages", "intent_mode"})
    messages = args.get("messages")
    mode = args.get("intent_mode", "heuristic")
    if mode not in {"auto", "heuristic", "learned"}:
        raise ToolFailure("INVALID_ARGUMENT: intent_mode must be auto, heuristic or learned")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 20:
        raise ToolFailure("INVALID_ARGUMENT: messages must be a list of 1..20 messages")
    normalized: list[dict] = []
    for i, item in enumerate(messages):
        if not isinstance(item, dict) or set(item) != {"role", "content"}:
            raise ToolFailure(f"INVALID_ARGUMENT: messages[{i}] needs exactly role, content")
        if item["role"] not in {"user", "assistant", "system"}:
            raise ToolFailure("INVALID_ARGUMENT: unsupported message role")
        normalized.append({"role": item["role"], "content": _str(item["content"], "content", 4000)})
    if not any(m["role"] == "user" for m in normalized):
        raise ToolFailure("INVALID_ARGUMENT: messages require a user turn")
    encoded = json.dumps(normalized, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ToolFailure("INVALID_ARGUMENT: transcript is too large")
    return _call("eq-layer", ["route", "--intent-mode", mode, "--messages-json", encoded])


def _doctor(_args: dict) -> dict:
    _check_only(_args, set())
    commands: dict[str, dict] = {}
    for key, (env, default) in BINS.items():
        exe = os.environ.get(env, default)
        where = shutil.which(exe) if exe.strip() and "\x00" not in exe else None
        if where is None and key == "axiomize-reason" and env not in os.environ:
            isolated = Path.cwd() / ".reason-env" / "bin" / "axiomize-reason"
            if isolated.is_file():
                where = str(isolated)
        commands[key] = {"installed": bool(where), "executable": where, "override": env}
    return {
        "status": "AVAILABLE_TOOLS_REQUIRE_INSTALLED_UPSTREAM_PACKAGES",
        "repositories": 7,
        "commands": commands,
        "plan_auditor_audit_enabled": os.environ.get("SCITOOL_ALLOW_AUDIT_EXECUTION") == "1",
        "workspace_configured": bool(os.environ.get("SCITOOL_WORKSPACE_DIR")),
        "note": "Inspecting availability does not demonstrate model correctness or deployment.",
    }


def dispatch(name: str, args: dict) -> dict:
    if name == "toolkit_catalog":
        _check_only(args, set())
        return {"count": len(catalog()), "repositories": catalog(),
                "integration_note": "Original repositories are unchanged; bundled Axiomize variant is not registered twice."}
    if name == "toolkit_doctor":
        return _doctor(args)
    if name == "axiomize_intake":
        _check_only(args, {"idea"})
        return _call("axiomize", ["intake", _str(args.get("idea"), "idea", 6000)])
    if name == "axiomize_model":
        return _model(args)
    if name == "cds_stats":
        return _stats(args, "cds")
    if name == "cds2_stats":
        return _stats(args, "cds2")
    if name == "plan_auditor_inspect":
        _check_only(args, set())
        return _call("plan-auditor", ["plan", "inspect", str(_workspace())])
    if name == "plan_auditor_audit":
        _check_only(args, set())
        if os.environ.get("SCITOOL_ALLOW_AUDIT_EXECUTION") != "1":
            raise ToolFailure("DISABLED: plan-auditor audit can execute project commands; set SCITOOL_ALLOW_AUDIT_EXECUTION=1 only for a trusted workspace")
        return _call("plan-auditor", ["audit", str(_workspace())], seconds=120)
    if name == "quantum_skill_validate":
        _check_only(args, set())
        return _call("quantum-reasoning", ["--validate", "--json"])
    if name == "axiomize_reason_score":
        _check_only(args, {"evidence", "verification"})
        evidence = _unit(args.get("evidence"), "evidence")
        verification = _unit(args.get("verification"), "verification")
        return _call("axiomize-reason", ["score", "--evidence", str(evidence), "--verification", str(verification)])
    if name == "eq_layer_route":
        return _eq_route(args)
    raise ToolFailure(f"UNKNOWN_TOOL: {name}")
