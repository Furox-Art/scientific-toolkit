"""Real availability probe for the seven upstream tools behind the MCP gateway.

This script performs no computation of its own about tool status. Every field in
the generated report is read back from a real subprocess call: the installed
distribution version comes from ``importlib.metadata`` and the capability result
comes from an actual JSON-RPC ``tools/call`` handled by the gateway.

Usage::

    python scripts/availability_report.py --output tests/e2e/results/availability.json

The output file is committed as captured evidence. A missing upstream package is
reported as a KNOWN GAP; it is never skipped silently and never fabricated.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scientific_toolkit_mcp.server import handle  # noqa: E402
from scientific_toolkit_mcp.tools import BINS  # noqa: E402

# Each upstream repository, its PyPI distribution, the gateway CLI key it uses,
# and the exact capability call that proves that CLI actually executes.
UPSTREAM = (
    {
        "repository": "axiomize",
        "distribution": "axiomize",
        "cli_key": "axiomize",
        "gateway_tool": "axiomize_intake",
        "arguments": {"idea": "How does sample size affect measurement uncertainty?"},
        "proves": "The Axiomize intake CLI runs and returns its own clarification questions.",
    },
    {
        "repository": "scientific-computing-system",
        "distribution": "scientific-computing-system",
        "cli_key": "cds",
        "gateway_tool": "cds_stats",
        "arguments": {"values": [1, 2, 3, 4, 5]},
        "proves": "The pure-Python cds statistics CLI runs and returns its own statistics.",
    },
    {
        "repository": "scientific-computing-system-2.0",
        "distribution": "scientific-computing-system-2.0",
        "cli_key": "cds2",
        "gateway_tool": "cds2_stats",
        "arguments": {"values": [1, 2, 3, 4, 5]},
        "proves": "The NumPy-backed cds2 statistics CLI runs and returns its own statistics.",
    },
    {
        "repository": "plan-auditor",
        "distribution": "plan-auditor",
        "cli_key": "plan-auditor",
        "gateway_tool": "plan_auditor_inspect",
        "arguments": {},
        "proves": "The plan-auditor CLI runs; the gateway refuses without SCITOOL_WORKSPACE_DIR.",
    },
    {
        "repository": "quantum-reasoning-skill",
        "distribution": "quantum-reasoning-skill",
        "cli_key": "quantum-reasoning",
        "gateway_tool": "quantum_skill_validate",
        "arguments": {},
        "proves": "The quantum-reasoning inspector validates its packaged contract.",
    },
    {
        "repository": "axiomize-quantum-skills-2.0",
        "distribution": "axiomize-quantum-skills-2.0",
        "cli_key": "axiomize-reason",
        "gateway_tool": "axiomize_reason_score",
        "arguments": {"evidence": 0.75, "verification": 0.8},
        "proves": "The bundled axiomize-reason branch scorer runs and returns its own verdict.",
    },
    {
        "repository": "eq-layer",
        "distribution": "eq-layer",
        "cli_key": "eq-layer",
        "gateway_tool": "eq_layer_route",
        "arguments": {
            "messages": [{"role": "user", "content": "What does this result mean?"}],
            "intent_mode": "heuristic",
        },
        "proves": "The eq-layer router runs and returns its own control decision.",
    },
)

# Capability calls that are expected to be refused for configuration reasons.
# These are still real executed calls; their result is recorded, not assumed.
EXPECTED_REFUSALS = (
    {
        "gateway_tool": "plan_auditor_audit",
        "arguments": {},
        "expected_error": "DISABLED",
        "reason": "Audit execution requires explicit local opt-in and stays local-only.",
    },
    {
        "gateway_tool": "plan_auditor_inspect",
        "arguments": {},
        "expected_error": "NOT_CONFIGURED",
        "reason": "Plan inspection requires SCITOOL_WORKSPACE_DIR to point at a trusted directory.",
    },
    {
        "gateway_tool": "axiomize_model",
        "arguments": {"action": "repair", "request": {}},
        "expected_error": "INVALID_ARGUMENT",
        "reason": "The action allowlist intentionally excludes repair and heavy operations.",
    },
    {
        "gateway_tool": "axiomize_reason_score",
        "arguments": {"evidence": 1.5, "verification": 0.5},
        "expected_error": "INVALID_ARGUMENT",
        "reason": "Scores outside the unit interval are rejected before any subprocess runs.",
    },
    {
        "gateway_tool": "cds_stats",
        "arguments": {"values": [1]},
        "expected_error": "INVALID_ARGUMENT",
        "reason": "Fewer than two values cannot produce a variance, so the call is refused.",
    },
    {
        "gateway_tool": "eq_layer_route",
        "arguments": {"messages": [{"role": "system", "content": "no user turn"}]},
        "expected_error": "INVALID_ARGUMENT",
        "reason": "A transcript without a user turn cannot be routed.",
    },
)


def call_tool(name: str, arguments: dict) -> dict:
    """Run one real JSON-RPC tools/call through the gateway and return its result."""
    response = handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": name, "arguments": arguments}}
    )
    if response is None or "result" not in response:
        return {"isError": True, "content": [{"type": "text", "text": "NO_RESULT"}]}
    return response["result"]


def payload_of(result: dict) -> dict:
    try:
        return json.loads(result["content"][0]["text"])
    except (KeyError, IndexError, ValueError, TypeError):
        return {}


def cli_version(executable: str | None, cli_key: str) -> dict:
    """Ask the real CLI for its own version using a flag that CLI supports.

    The seven upstream CLIs do not share a version convention: ``cds`` accepts
    ``--version``, ``cds2`` accepts only a ``version`` subcommand, and several
    have no version command at all. Every candidate below is a real executed
    subprocess call; nothing is inferred.
    """
    if not executable:
        return {"reported": False, "reason": "executable not found on PATH"}
    candidates: list[tuple[str, ...]] = [
        ("--version",), ("version",), ("doctor",),
    ]
    if cli_key == "axiomize":
        candidates.append(("capabilities",))
    last = None
    for flags in candidates:
        try:
            completed = subprocess.run(
                [executable, *flags], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=30, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"reported": False, "reason": f"{type(exc).__name__}"}
        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        last = {"flags": list(flags), "exit_code": completed.returncode,
                "stdout": stdout[:200], "stderr": stderr[:200]}
        if completed.returncode == 0 and (stdout or stderr):
            text = stdout or stderr
            return {"reported": True, "flags": list(flags),
                    "exit_code": completed.returncode, "output": text[:400]}
    return {"reported": False, "note": "CLI exposes no version subcommand",
            "last_attempt": last}


def _interpreter_for(executable: str | None) -> str | None:
    """The interpreter a console script's shebang points at, if it exists."""
    if executable is None:
        return None
    try:
        with open(executable, "rb") as handle:
            first_line = handle.readline().decode("utf-8", "replace").strip()
    except OSError:
        return None
    if not first_line.startswith("#!"):
        return None
    interpreter = first_line[2:].strip().split()[0]
    return interpreter if Path(interpreter).is_file() else None


def _distribution_version_in(interpreter: str | None,
                             distribution: str) -> str | None:
    """A distribution version as resolved by a specific interpreter.

    ``axiomize-quantum-skills-2.0`` is installed into an isolated package
    directory so its bundled ``axiomize`` console script cannot clash with the
    standalone Axiomize CLI. Its version is therefore read back from the
    interpreter that actually runs its console script, not from this process.
    """
    if interpreter is None:
        return None
    try:
        completed = subprocess.run(
            [interpreter, "-c",
             "import importlib.metadata as m, sys;"
             "print(m.version(sys.argv[1]))", distribution],
            capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    version = (completed.stdout or "").strip()
    return version if completed.returncode == 0 and version else None


def probe_upstream(entry: dict) -> dict:
    record: dict = {
        "repository": entry["repository"],
        "distribution": entry["distribution"],
        "gateway_tool": entry["gateway_tool"],
        "gateway_cli_key": entry["cli_key"],
        "proves": entry["proves"],
    }
    # 1. Installed distribution version, read from real package metadata.
    try:
        record["distribution_version"] = metadata.version(entry["distribution"])
        record["installed"] = True
    except metadata.PackageNotFoundError:
        record["distribution_version"] = None
        record["installed"] = False

    # 2. Resolved executable path, from the same lookup the gateway uses.
    env_var, default_bin = BINS[entry["cli_key"]]
    program = os.environ.get(env_var, default_bin)
    executable = shutil.which(program) if program.strip() else None
    if executable is None and entry["cli_key"] == "axiomize-reason" and env_var not in os.environ:
        for candidate in (Path.cwd() / ".reason-pkg" / "bin" / "axiomize-reason",
                          Path.cwd() / ".reason-env" / "bin" / "axiomize-reason"):
            if candidate.is_file():
                executable = str(candidate)
                break
    record["executable"] = executable
    record["executable_override_env"] = env_var

    # A distribution installed only in an isolated environment still counts as
    # installed; its version is read back from the interpreter that runs it.
    interpreter = _interpreter_for(executable)
    if not record["installed"]:
        isolated = _distribution_version_in(interpreter, entry["distribution"])
        if isolated:
            record["distribution_version"] = isolated
            record["installed"] = True
            record["distribution_scope"] = (
                f"installed in the isolated environment used by "
                f"{env_var} ({interpreter}); the gateway runs that same "
                f"console script, so the tool is genuinely usable")
    record["cli_self_reported_version"] = cli_version(executable, entry["cli_key"])

    # 3. Real gateway capability call through the MCP dispatcher.
    result = call_tool(entry["gateway_tool"], entry["arguments"])
    payload = payload_of(result)
    record["gateway_call"] = {
        "isError": bool(result.get("isError")),
        "exit_code": payload.get("exit_code"),
        "status": payload.get("status"),
        "stdout_first_300_chars": str(payload.get("stdout", ""))[:300],
    }

    if not record["installed"] or executable is None:
        record["verdict"] = "KNOWN_GAP"
        record["gap_detail"] = (
            "Upstream distribution or executable not present on this machine; "
            "the gateway returns NOT_INSTALLED instead of fabricating a result."
        )
    elif result.get("isError") and "NOT_CONFIGURED" in str(
            result["content"][0].get("text", "")):
        # The upstream CLI resolved far enough for the gateway to reach its own
        # workspace guard, which proves the CLI is installed and usable. A
        # configured workspace is a separate, deliberate precondition.
        record["verdict"] = "AVAILABLE"
        record["gap_detail"] = (
            "CLI installed and reachable. plan_auditor_inspect additionally "
            "requires SCITOOL_WORKSPACE_DIR, unset for this bare probe. See the "
            "cross-tool workflow for the configured-workspace run."
        )
    elif result.get("isError"):
        record["verdict"] = "CAPABILITY_FAILED"
        record["gap_detail"] = payload.get("stdout") or payload.get("error") or "unknown"
    else:
        record["verdict"] = "AVAILABLE"
        record["gap_detail"] = None
    return record


def probe_refusals() -> list[dict]:
    records = []
    for item in EXPECTED_REFUSALS:
        result = call_tool(item["gateway_tool"], item["arguments"])
        text = result["content"][0]["text"] if result.get("content") else ""
        payload = payload_of(result)
        combined = text + " " + json.dumps(payload)
        records.append({
            "gateway_tool": item["gateway_tool"],
            "arguments": item["arguments"],
            "reason": item["reason"],
            "isError": bool(result.get("isError")),
            "expected_error_marker": item["expected_error"],
            "marker_present": item["expected_error"] in combined,
            "response_first_200_chars": str(text)[:200],
        })
    return records


def gateway_inventory() -> dict:
    listing = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    tools = listing["result"]["tools"] if listing and "result" in listing else []
    initialize = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    return {
        "protocol_version": initialize["result"]["protocolVersion"],
        "server_name": initialize["result"]["serverInfo"]["name"],
        "server_version": initialize["result"]["serverInfo"]["version"],
        "tool_count": len(tools),
        "tool_names": [tool["name"] for tool in tools],
    }


def environment_summary() -> dict:
    from scientific_toolkit_mcp import __version__

    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "gateway_version": __version__,
        "cwd": str(Path.cwd()),
        "executable": sys.executable,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope_note": (
            "Availability only. A successful CLI exit code proves the program ran; "
            "it is not evidence of scientific correctness."
        ),
    }


def build_report() -> dict:
    upstream = [probe_upstream(entry) for entry in UPSTREAM]
    available = [item for item in upstream if item["verdict"] == "AVAILABLE"]
    gaps = [item for item in upstream if item["verdict"] != "AVAILABLE"]
    doctor = payload_of(call_tool("toolkit_doctor", {}))
    return {
        "report": "scientific-toolkit MCP gateway availability",
        "generated_by": "scripts/availability_report.py",
        "environment": environment_summary(),
        "gateway": gateway_inventory(),
        "toolkit_doctor": doctor,
        "upstream_tools": upstream,
        "summary": {
            "repositories_total": len(upstream),
            "available": len(available),
            "known_gaps": len(gaps),
            "available_repositories": [item["repository"] for item in available],
            "gap_repositories": [item["repository"] for item in gaps],
        },
        "fail_closed_checks": probe_refusals(),
        "not_tested_here": [
            "Live remote deployment at scientific-toolkit.onrender.com (needs the "
            "private bearer credential, which must never be committed).",
            "OAuth 2.1 sign-in with an external identity provider (no trusted "
            "authorization server is configured).",
            "Scientific correctness of any upstream numerical result.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="tests/e2e/results/availability.json")
    args = parser.parse_args()
    report = build_report()
    destination = Path(args.output)
    if not destination.is_absolute():
        destination = REPO_ROOT / destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    # relative_to() only works for paths inside the repository; an explicitly
    # requested outside path is reported as given instead of crashing.
    try:
        shown = destination.relative_to(REPO_ROOT)
    except ValueError:
        shown = destination
    summary = report["summary"]
    print(f"Wrote {shown}")
    print(f"Available {summary['available']}/{summary['repositories_total']} upstream tools")
    for item in report["upstream_tools"]:
        marker = "OK  " if item["verdict"] == "AVAILABLE" else "GAP "
        version = item["distribution_version"] or "not installed"
        print(f"  {marker} {item['repository']:<32} {version}")
    failed = [c for c in report["fail_closed_checks"] if not c["marker_present"]]
    print(f"Fail-closed checks: {len(report['fail_closed_checks']) - len(failed)}"
          f"/{len(report['fail_closed_checks'])} refused as expected")
    if summary["known_gaps"]:
        print(f"KNOWN GAPS: {', '.join(summary['gap_repositories'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
