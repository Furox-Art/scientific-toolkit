"""Allowlisted MCP adapters; never evaluate arbitrary Python or shell commands.

The original upstream distributions are installed separately. Every response
contains the actual subprocess return code; a failed or absent program is never
reported as a successful scientific result.
"""

from __future__ import annotations

import contextlib
from functools import partial
import importlib.metadata as metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

from . import __version__
from .catalog import catalog

MAX_INPUT_BYTES = 65536
MAX_OUTPUT = 32768

# Every upstream subprocess runs with an explicit, bounded execution timeout.
# The bound is absolute: a heavier upstream can never stall a request without a
# limit, and no configuration can disable it. Individual tools declare their own
# per-call timeout inside this range for the tools they invoke.
MIN_CALL_TIMEOUT = 1
DEFAULT_CALL_TIMEOUT = 30
MAX_CALL_TIMEOUT = 600


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
    "literature-evidence": ("SCITOOL_LIT_EVIDENCE_BIN", "literature-evidence-mcp"),
}

# Upstreams that ship an MCP stdio server but no console script are started as
# ``<python> -m <module>``. The module must be importable by the interpreter the
# gateway itself runs under; SCITOOL_*_BIN can point at a different interpreter
# or wrapper, in which case the import check is the operator's responsibility.
MODULE_SERVERS = {
    "nomosguard": ("SCITOOL_NOMOSGUARD_BIN", "nomosguard.mcp_stdio", "nomosguard"),
}

MCP_PROTOCOL_VERSION = "2025-06-18"

# BINS key -> upstream distribution whose top-level import module must not be
# shadowed. The bundled axiomize-quantum-skills-2.0 distribution installs its
# own top-level ``axiomize`` package, so when an isolated install directory
# reaches sys.path (``PYTHONPATH=.reason-pkg``, an editable install, or a
# vendored copy in the working directory), ``import axiomize`` and
# ``importlib.metadata`` resolve that other distribution instead of the pinned
# standalone one -- silently. Each pinned module must therefore have exactly one
# provider on sys.path, and an operator can demand an exact version with
# ``SCITOOL_PIN_AXIOMIZE``. A mismatch fails the call loud instead of letting a
# different distribution than the pinned one run.
PINNED_DISTRIBUTIONS = {
    "axiomize": "axiomize",
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
    # Verify the pinned distribution before invoking it: once the executable
    # resolves, the import path decides which distribution actually runs.
    pinned = PINNED_DISTRIBUTIONS.get(key)
    if pinned is not None:
        _verify_pinned_distribution(pinned)
    return found


def module_providers(module: str) -> list[str]:
    """Every sys.path entry that provides a top-level module, in import order.

    This mirrors the interpreter's own resolution for ``import <module>``: the
    first provider wins silently, so more than one provider means the import
    path is shadowed and which distribution actually runs depends on sys.path
    order instead of on what the operator installed and pinned.
    """
    providers: list[str] = []
    for entry in sys.path:
        if not entry:
            continue
        package = Path(entry) / module
        single = Path(entry) / f"{module}.py"
        if package.is_dir():
            providers.append(str(package))
        elif single.is_file():
            providers.append(str(single))
    return providers


def _verify_pinned_distribution(distribution: str) -> None:
    """Refuse to invoke an upstream CLI whose pinned module is shadowed.

    Raises a loud configuration error instead of silently executing a
    different distribution than the pinned one. An exact expected version can
    be pinned with ``SCITOOL_PIN_<DISTRIBUTION>`` (for example
    ``SCITOOL_PIN_AXIOMIZE=1.12.5``).
    """
    module = PINNED_DISTRIBUTIONS[distribution]
    providers = module_providers(module)
    if len(providers) > 1:
        raise ToolFailure(
            f"BAD_CONFIGURATION: pinned distribution {distribution!r} is shadowed: "
            f"module {module!r} is provided by {len(providers)} sys.path entries "
            f"({', '.join(providers)}) and the first one wins silently. Isolate the "
            "colliding package so the pinned distribution is the only provider")
    try:
        resolved = metadata.version(distribution)
    except metadata.PackageNotFoundError:
        resolved = None
    pin = os.environ.get(f"SCITOOL_PIN_{distribution.upper().replace('-', '_')}", "").strip()
    if pin and resolved != pin:
        raise ToolFailure(
            f"BAD_CONFIGURATION: pinned {distribution} version mismatch: sys.path "
            f"resolves {resolved!r} but SCITOOL_PIN_{distribution.upper().replace('-', '_')} "
            f"pins {pin!r}")


def _call(key: str, argv: list[str], *, seconds: int = DEFAULT_CALL_TIMEOUT) -> dict:
    if (isinstance(seconds, bool) or not isinstance(seconds, int)
            or not MIN_CALL_TIMEOUT <= seconds <= MAX_CALL_TIMEOUT):
        raise ToolFailure(
            "INVALID_ARGUMENT: timeout must be an integer between "
            f"{MIN_CALL_TIMEOUT} and {MAX_CALL_TIMEOUT} seconds")
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
            # Not JSON; keep the raw stdout without a parsed view.
            pass
    return result


def _module_argv(key: str) -> list[str]:
    env, module, import_name = MODULE_SERVERS[key]
    program = os.environ.get(env, sys.executable)
    if not program.strip() or "\x00" in program:
        raise ToolFailure(f"BAD_CONFIGURATION: {env} is invalid")
    found = shutil.which(program)
    if found is None:
        raise ToolFailure(f"NOT_INSTALLED: {program!r} is not available (override with {env})")
    if env not in os.environ:
        try:
            available = importlib.util.find_spec(import_name) is not None
        except (ImportError, ValueError):
            available = False
        if not available:
            raise ToolFailure(
                f"NOT_INSTALLED: Python module {import_name!r} is not available "
                f"(install the upstream package or override {env})")
    return [found, "-m", module]


def _mcp(key: str, argv: list[str], calls: list[tuple[str, dict]],
         *, seconds: int = DEFAULT_CALL_TIMEOUT) -> dict:
    """Drive one bounded upstream MCP stdio session: initialize, then call tools.

    Each call spawns a fresh server process. Responses are collected before
    stdin is closed: an MCP server may stop reading as soon as it sees EOF, so
    closing stdin immediately after writing the requests would drop replies
    that were still being produced. The session enforces the same absolute
    timeout bound as the CLI adapters and never reports an upstream tool error
    as a successful result.
    """
    if (isinstance(seconds, bool) or not isinstance(seconds, int)
            or not MIN_CALL_TIMEOUT <= seconds <= MAX_CALL_TIMEOUT):
        raise ToolFailure(
            "INVALID_ARGUMENT: timeout must be an integer between "
            f"{MIN_CALL_TIMEOUT} and {MAX_CALL_TIMEOUT} seconds")
    messages: list[dict] = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": MCP_PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": "furox-scientific-toolkit", "version": __version__},
        }},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    ]
    for index, (tool, arguments) in enumerate(calls, start=2):
        messages.append({"jsonrpc": "2.0", "id": index, "method": "tools/call",
                         "params": {"name": tool, "arguments": arguments}})
    payload = "".join(
        json.dumps(message, ensure_ascii=False, allow_nan=False) + "\n"
        for message in messages)
    deadline = time.monotonic() + seconds
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as errlog:
        try:
            process = subprocess.Popen(
                argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errlog,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
            )
        except OSError as exc:
            raise ToolFailure(f"EXECUTION_ERROR: {type(exc).__name__}: {exc}") from exc
        lines: queue.Queue[str | None] = queue.Queue()

        def _pump() -> None:
            try:
                for line in process.stdout:
                    lines.put(line)
            finally:
                lines.put(None)

        threading.Thread(target=_pump, daemon=True).start()
        replies: dict[Any, dict] = {}
        expected = set(range(1, len(calls) + 2))

        def _timed_out() -> ToolFailure:
            process.kill()
            process.wait()
            return ToolFailure(f"TIMEOUT: {key} exceeded {seconds}s")

        try:
            try:
                process.stdin.write(payload)
                process.stdin.flush()
            except (OSError, ValueError) as exc:
                process.kill()
                process.wait()
                raise ToolFailure(
                    f"EXECUTION_ERROR: {type(exc).__name__}: {exc}") from exc
            while expected - replies.keys():
                remaining = deadline - time.monotonic()
                try:
                    line = lines.get(timeout=max(0.0, remaining))
                except queue.Empty:
                    raise _timed_out() from None
                if line is None:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(message, dict) and "id" in message:
                    replies[message["id"]] = message
        finally:
            with contextlib.suppress(OSError):
                process.stdin.close()
            try:
                process.wait(timeout=max(1.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                # All expected replies are collected or the failure is already
                # raised; a server that ignores EOF must not hold the gateway.
                process.kill()
                process.wait()
        errlog.seek(0)
        stderr = errlog.read().strip()
    initialized = replies.get(1)
    if not isinstance(initialized, dict) or "result" not in initialized:
        raise ToolFailure(
            f"PROTOCOL_ERROR: {key} did not complete an MCP initialize "
            f"(exit {process.returncode})")
    output: list[dict] = []
    failed = False
    for index, (tool, _arguments) in enumerate(calls, start=2):
        reply = replies.get(index)
        if not isinstance(reply, dict):
            raise ToolFailure(f"PROTOCOL_ERROR: {key} did not answer tools/call {tool!r}")
        error = reply.get("error")
        if error is not None:
            message = error.get("message") if isinstance(error, dict) else error
            raise ToolFailure(f"UPSTREAM_ERROR: {key} {tool}: {str(message)[:2000]}")
        result = reply.get("result")
        if not isinstance(result, dict):
            raise ToolFailure(f"PROTOCOL_ERROR: {key} returned no result for {tool!r}")
        text = "\n".join(
            item.get("text", "") for item in result.get("content", [])
            if isinstance(item, dict) and item.get("type") == "text")
        entry: dict[str, Any] = {"tool": tool, "status": "COMMAND_SUCCEEDED"}
        if result.get("isError"):
            failed = True
            entry["status"] = "COMMAND_FAILED"
        elif text.startswith("{"):
            try:
                entry["json"] = json.loads(text)
            except json.JSONDecodeError:
                # Not JSON; keep the raw text without a parsed view.
                pass
        entry["text"] = text[:MAX_OUTPUT]
        if len(text) > MAX_OUTPUT:
            entry["truncated"] = True
        output.append(entry)
    response: dict[str, Any] = {
        "program": key,
        "exit_code": process.returncode,
        "status": "COMMAND_FAILED" if failed else "COMMAND_SUCCEEDED",
        "calls": output,
    }
    if stderr:
        response["stderr"] = stderr[:4000]
    return response


def _stats(args: dict, key: str) -> dict:
    values = args.get("values")
    if not isinstance(values, list) or not 2 <= len(values) <= 1000:
        raise ToolFailure("INVALID_ARGUMENT: values must be an array of 2..1000 numbers")
    csv = ",".join(format(_number(x, f"values[{i}]"), ".12g") for i, x in enumerate(values))
    # NumPy/SciPy cold imports can exceed 30s on the 0.1-CPU Render Free tier.
    # This is an execution timeout only; no scientific acceptance criteria change.
    return _call(key, ["stats", csv], seconds=90 if key == "cds2" else 30)


def _model(args: dict) -> dict:
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
    commands: dict[str, dict] = {}
    for key, (env, default) in BINS.items():
        exe = os.environ.get(env, default)
        where = shutil.which(exe) if exe.strip() and "\x00" not in exe else None
        if where is None and key == "axiomize-reason" and env not in os.environ:
            isolated = Path.cwd() / ".reason-env" / "bin" / "axiomize-reason"
            if isolated.is_file():
                where = str(isolated)
        commands[key] = {"installed": bool(where), "executable": where, "override": env}
    for key, (env, module, import_name) in MODULE_SERVERS.items():
        exe = os.environ.get(env, sys.executable)
        where = shutil.which(exe) if exe.strip() and "\x00" not in exe else None
        try:
            module_available = importlib.util.find_spec(import_name) is not None
        except (ImportError, ValueError):
            module_available = False
        commands[key] = {
            "installed": bool(where) and (env in os.environ or module_available),
            "executable": where,
            "override": env,
            "module": module,
        }
    return {
        "status": "AVAILABLE_TOOLS_REQUIRE_INSTALLED_UPSTREAM_PACKAGES",
        "repositories": len(catalog()),
        "commands": commands,
        "plan_auditor_audit_enabled": os.environ.get("SCITOOL_ALLOW_AUDIT_EXECUTION") == "1",
        "workspace_configured": bool(os.environ.get("SCITOOL_WORKSPACE_DIR")),
        "note": "Inspecting availability does not demonstrate model correctness or deployment.",
    }


def _catalog(args: dict) -> dict:
    return {"count": len(catalog()), "repositories": catalog(),
            "integration_note": "Original repositories are unchanged; bundled Axiomize variant is not registered twice."}


def _intake(args: dict) -> dict:
    return _call("axiomize", ["intake", _str(args.get("idea"), "idea", 6000)])


def _inspect(args: dict) -> dict:
    return _call("plan-auditor", ["plan", "inspect", str(_workspace())])


def _audit(args: dict) -> dict:
    if os.environ.get("SCITOOL_ALLOW_AUDIT_EXECUTION") != "1":
        raise ToolFailure("DISABLED: plan-auditor audit can execute project commands; set SCITOOL_ALLOW_AUDIT_EXECUTION=1 only for a trusted workspace")
    return _call("plan-auditor", ["audit", str(_workspace())], seconds=120)


def _quantum(args: dict) -> dict:
    return _call("quantum-reasoning", ["--validate", "--json"])


def _reason_score(args: dict) -> dict:
    evidence = _unit(args.get("evidence"), "evidence")
    verification = _unit(args.get("verification"), "verification")
    return _call("axiomize-reason", ["score", "--evidence", str(evidence), "--verification", str(verification)])


def _lit_search(args: dict) -> dict:
    query = _str(args.get("query"), "query", 1000)
    limit = args.get("limit_per_source", 10)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 25:
        raise ToolFailure("INVALID_ARGUMENT: limit_per_source must be an integer between 1 and 25")
    return _mcp(
        "literature-evidence", [_bin("literature-evidence")],
        [("search_literature", {"query": query, "limit_per_source": limit})],
        seconds=60,
    )


def _lit_verify(args: dict) -> dict:
    request = {
        "quote": _str(args.get("quote"), "quote", 4000),
        "source_text": _str(args.get("source_text"), "source_text", 50000),
        "source_id": _str(args.get("source_id"), "source_id", 500),
    }
    encoded = json.dumps(request, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ToolFailure("INVALID_ARGUMENT: quote verification input is too large")
    return _mcp(
        "literature-evidence", [_bin("literature-evidence")],
        [("verify_claim", request)], seconds=30,
    )


def _nomos_decide(args: dict) -> dict:
    claims = args.get("claims")
    fallback = args.get("fallback", "BLOCK")
    if fallback not in {"BLOCK", "ALERT"}:
        raise ToolFailure("INVALID_ARGUMENT: fallback must be BLOCK or ALERT")
    if not isinstance(claims, list) or not 1 <= len(claims) <= 20:
        raise ToolFailure("INVALID_ARGUMENT: claims must be a list of 1..20 claim objects")
    normalized: list[dict] = []
    for i, item in enumerate(claims):
        if not isinstance(item, dict) or set(item) != {"kind", "payload", "evidence"}:
            raise ToolFailure(f"INVALID_ARGUMENT: claims[{i}] needs exactly kind, payload, evidence")
        if not isinstance(item["payload"], dict):
            raise ToolFailure(f"INVALID_ARGUMENT: claims[{i}].payload must be an object")
        normalized.append({
            "kind": _str(item["kind"], f"claims[{i}].kind", 200),
            "payload": item["payload"],
            "evidence": _str(item["evidence"], f"claims[{i}].evidence", 4000),
        })
    encoded = json.dumps(normalized, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ToolFailure("INVALID_ARGUMENT: claims are too large")
    calls = [("assert_claim", claim) for claim in normalized]
    calls.append(("derive_paths", {}))
    calls.append(("decide", {"fallback": fallback}))
    return _mcp("nomosguard", _module_argv("nomosguard"), calls, seconds=60)


# One routing table for every tool: the exact argument keys the tool accepts and
# the single handler that runs it. ``dispatch`` validates the keys against this
# table and then calls the handler, so a tool can never accept an argument it
# does not declare, and no second, divergent router can drift from this one.
# ``tests/test_server.py`` asserts this table stays in sync with the MCP tool
# specs in ``server.py`` (properties and additionalProperties).
TOOL_ROUTES: dict[str, tuple[frozenset[str], Any]] = {
    "toolkit_catalog": (frozenset(), _catalog),
    "toolkit_doctor": (frozenset(), _doctor),
    "axiomize_intake": (frozenset({"idea"}), _intake),
    "axiomize_model": (frozenset({"action", "request"}), _model),
    "cds_stats": (frozenset({"values"}), partial(_stats, key="cds")),
    "cds2_stats": (frozenset({"values"}), partial(_stats, key="cds2")),
    "plan_auditor_inspect": (frozenset(), _inspect),
    "plan_auditor_audit": (frozenset(), _audit),
    "quantum_skill_validate": (frozenset(), _quantum),
    "axiomize_reason_score": (frozenset({"evidence", "verification"}), _reason_score),
    "eq_layer_route": (frozenset({"messages", "intent_mode"}), _eq_route),
    "literature_evidence_search": (frozenset({"query", "limit_per_source"}), _lit_search),
    "literature_evidence_verify_quote": (frozenset({"quote", "source_text", "source_id"}), _lit_verify),
    "nomosguard_decide": (frozenset({"claims", "fallback"}), _nomos_decide),
}


def dispatch(name: str, args: dict) -> dict:
    allowed, handler = TOOL_ROUTES.get(name, (None, None))
    if handler is None:
        raise ToolFailure(f"UNKNOWN_TOOL: {name}")
    _check_only(args, allowed)
    return handler(args)
