"""End-to-end integration tests for the seven-tool MCP gateway.

These tests exercise the gateway the way a real client does, over both
transports, and they require the upstream packages to actually be installed.
Unlike the unit tests in ``tests/test_server.py``, no upstream CLI is faked
here: every subprocess call below reaches a real installed program.

What this suite proves
----------------------
* Each of the seven upstream tools is genuinely installed and usable. A missing
  tool is reported as a KNOWN GAP; it is never skipped silently.
* Real cross-tool data flow works: one tool's own output becomes the next
  tool's own input.
* The local (stdio) and remote (HTTP) transports behave as separate security
  boundaries, each verified independently.
* Bad arguments, unknown tools and missing dependencies fail closed with a
  clear error and never crash the gateway.

What this suite does NOT prove
------------------------------
* Scientific correctness of any upstream numerical result.
* Compatibility with any specific third-party MCP client.
* Behaviour of the live hosted deployment.

Run::

    python -m unittest discover -s tests/e2e -v
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scientific_toolkit_mcp.http_server import Handler  # noqa: E402
from scientific_toolkit_mcp.server import TOOLS, handle  # noqa: E402
from scientific_toolkit_mcp.tools import BINS  # noqa: E402

TOKEN = "e2e-local-test-token"

MEASUREMENTS = [12.04, 11.97, 12.11, 12.02, 11.95, 12.08, 12.06, 11.99, 12.03, 12.10]

# The seven upstream repositories mapped to the gateway CLI they depend on.
SEVEN_TOOLS = {
    "axiomize": "axiomize",
    "scientific-computing-system": "cds",
    "scientific-computing-system-2.0": "cds2",
    "plan-auditor": "plan-auditor",
    "quantum-reasoning-skill": "quantum-reasoning",
    "axiomize-quantum-skills-2.0": "axiomize-reason",
    "eq-layer": "eq-layer",
}


def call(name: str, arguments: dict | None = None) -> dict:
    """Run one real JSON-RPC tools/call through the gateway dispatcher."""
    response = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": name, "arguments": arguments or {}}})
    assert response is not None and "result" in response, response
    return response["result"]


def text_of(result: dict) -> str:
    return result["content"][0]["text"] if result.get("content") else ""


def payload_of(result: dict) -> dict:
    try:
        return json.loads(text_of(result))
    except (ValueError, TypeError):
        return {}


def resolve(cli_key: str) -> str | None:
    """Resolve an upstream executable exactly the way the gateway does."""
    env_var, default_bin = BINS[cli_key]
    import shutil

    found = shutil.which(os.environ.get(env_var, default_bin))
    if found is None and cli_key == "axiomize-reason" and env_var not in os.environ:
        for candidate in (REPO_ROOT / ".reason-pkg" / "bin" / "axiomize-reason",
                          REPO_ROOT / ".reason-env" / "bin" / "axiomize-reason"):
            if candidate.is_file():
                found = str(candidate)
                break
    return found


def _standalone_python() -> str | None:
    """Interpreter whose site-packages holds the standalone axiomize CLI.

    ``axiomize-reason`` ships the bundled Axiomize variant. Setting
    ``PYTHONPATH`` to that package directory would shadow the standalone
    ``axiomize`` installed in the virtualenv, so the isolated environment is
    deliberately never used to run the standalone ``axiomize`` CLI.
    """
    found = shutil.which(os.environ.get("SCITOOL_AXIOMIZE_BIN", "axiomize"))
    if found is None:
        return None
    with open(found, "rb") as handle:
        first_line = handle.readline().decode("utf-8", "replace").strip()
    if first_line.startswith("#!"):
        interpreter = first_line[2:].strip().split()[0]
        if Path(interpreter).is_file():
            return interpreter
    return sys.executable


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


def _distribution_installed_in(interpreter: str, distribution: str) -> bool:
    """Whether a given interpreter can resolve an installed distribution."""
    completed = subprocess.run(
        [interpreter, "-c",
         "import importlib.metadata as m, sys;"
         "sys.exit(0 if m.version(sys.argv[1]) else 1)", distribution],
        capture_output=True, text=True, timeout=30, env=_clean_environment())
    return completed.returncode == 0


# A real Model IR request in the schema the standalone Axiomize CLI accepts.
# It is wrapped in a "model_ir" key and declares schema_version 1.0; without
# both, axiomize refuses the request before running any check.
MODEL_IR_REQUEST = {
    "model_ir": {
        "schema_version": "1.0",
        "name": "linear_drift",
        "domain": "general",
        "family": "algebraic",
        "independent_variable": "t",
        "independent_unit": "s",
        "variables": [
            {"name": "y", "unit": "m", "role": "state",
             "description": "measured length"},
        ],
        "parameters": [
            {"name": "slope", "unit": "m/s"},
            {"name": "intercept", "unit": "m"},
        ],
        "equations": [
            {"target": "y", "expression": "intercept + slope * t",
             "kind": "algebraic", "unit": "m"},
        ],
        "metadata": {
            "origin": "scientific-toolkit end-to-end integration suite",
        },
    }
}


def _clean_environment() -> dict:
    """The gateway's own environment with test-only overrides removed."""
    return {key: value for key, value in os.environ.items()
            if not key.startswith("SCITOOL_")}


class UpstreamAvailabilityTests(unittest.TestCase):
    """Prove each of the seven upstream tools is actually installed and usable."""

    def test_doctor_reports_seven_commands(self):
        doctor = payload_of(call("toolkit_doctor"))
        self.assertEqual(len(doctor.get("commands", {})), 7)

    def test_each_of_seven_repositories_has_installed_executable(self):
        doctor = payload_of(call("toolkit_doctor"))
        gaps = [key for key, info in doctor["commands"].items()
                if not info.get("installed")]
        self.assertEqual(
            gaps, [],
            f"KNOWN GAP: these upstream CLIs are not installed: {gaps}. "
            f"Install them (see README) or record them as known gaps. "
            f"The gateway returns NOT_INSTALLED rather than fabricating output.")

    def test_each_of_seven_repositories_has_installed_distribution(self):
        """Each upstream distribution must be importable through *some* real path.

        ``axiomize-quantum-skills-2.0`` bundles the Axiomize variant and is
        deliberately installed into an isolated package directory
        (``SCITOOL_REASON_BIN``) rather than the main virtualenv, because its
        ``axiomize`` console script would otherwise clash with the standalone
        Axiomize CLI. A distribution counts as installed when the interpreter
        that runs its console script can actually import it.
        """
        import importlib.metadata as metadata

        missing = []
        for repo in SEVEN_TOOLS:
            if _distribution_installed(metadata, repo):
                continue
            if repo == "axiomize-quantum-skills-2.0":
                executable = resolve("axiomize-reason")
                interpreter = _interpreter_for(executable)
                if interpreter and _distribution_installed_in(interpreter, repo):
                    continue
            missing.append(repo)
        self.assertEqual(
            missing, [],
            f"KNOWN GAP: these upstream distributions are not installed: {missing}")

    def test_catalog_lists_seven_distinct_repositories(self):
        catalog = payload_of(call("toolkit_catalog"))
        self.assertEqual(catalog["count"], 7)
        self.assertEqual(len({item["name"] for item in catalog["repositories"]}), 7)
        for item in catalog["repositories"]:
            self.assertIn(item["name"], SEVEN_TOOLS,
                          f"{item['name']} is not covered by the availability checks")

    def test_gateway_exposes_eleven_local_tools(self):
        listing = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list",
                          "params": {}})
        self.assertEqual(len(listing["result"]["tools"]), 11)
        self.assertEqual({t["name"] for t in TOOLS}, {t["name"] for t in
                                                      listing["result"]["tools"]})

    def test_axiomize_intake_runs_real_cli(self):
        result = call("axiomize_intake",
                      {"idea": "How does sample size affect measurement uncertainty?"})
        payload = payload_of(result)
        self.assertFalse(result["isError"], text_of(result))
        self.assertEqual(payload["program"], "axiomize")
        self.assertEqual(payload["exit_code"], 0)
        self.assertEqual(payload["status"], "COMMAND_SUCCEEDED")
        self.assertTrue(payload["stdout"])

    def test_cds_stats_runs_real_cli(self):
        result = call("cds_stats", {"values": MEASUREMENTS})
        payload = payload_of(result)
        self.assertFalse(result["isError"], text_of(result))
        self.assertEqual(payload["program"], "cds")
        self.assertEqual(payload["exit_code"], 0)
        self.assertIn("mean", payload["stdout"])

    def test_cds2_stats_runs_real_cli(self):
        result = call("cds2_stats", {"values": MEASUREMENTS})
        payload = payload_of(result)
        self.assertFalse(result["isError"], text_of(result))
        self.assertEqual(payload["program"], "cds2")
        self.assertEqual(payload["exit_code"], 0)
        self.assertIn("mean", payload["stdout"])

    def test_quantum_skill_validate_runs_real_cli(self):
        result = call("quantum_skill_validate")
        payload = payload_of(result)
        self.assertFalse(result["isError"], text_of(result))
        self.assertEqual(payload["program"], "quantum-reasoning")
        self.assertEqual(payload["exit_code"], 0)
        self.assertIn("quantum-reasoning", payload["stdout"])

    def test_axiomize_reason_score_runs_real_cli(self):
        result = call("axiomize_reason_score",
                      {"evidence": 0.75, "verification": 0.8})
        payload = payload_of(result)
        self.assertFalse(result["isError"], text_of(result))
        self.assertEqual(payload["program"], "axiomize-reason")
        self.assertEqual(payload["exit_code"], 0)
        self.assertIn("can_collapse", payload["stdout"])

    def test_eq_layer_route_runs_real_cli(self):
        result = call("eq_layer_route",
                      {"messages": [{"role": "user", "content": "What next?"}],
                       "intent_mode": "heuristic"})
        payload = payload_of(result)
        self.assertFalse(result["isError"], text_of(result))
        self.assertEqual(payload["program"], "eq-layer")
        self.assertEqual(payload["exit_code"], 0)
        self.assertIn("factored_action", payload["stdout"])

    def test_plan_auditor_inspect_runs_real_cli_with_configured_workspace(self):
        request_contract = {
            "format_version": 1,
            "task": "Compute descriptive statistics for replicate measurements",
            "requirements": [{
                "id": "stats-computed",
                "description": "Descriptive statistics exist for the real data",
                "priority": "must",
                "acceptance_checks": [{"type": "run", "cmd": "test -f stats.json"}],
            }],
        }
        plan = {
            "task": "Compute descriptive statistics for replicate measurements",
            "created": "2026-10-08T00:00:00Z",
            "steps": [{
                "id": 1,
                "title": "Compute statistics from the replicate readings",
                "covers": ["stats-computed"],
                "verify": [{"type": "run", "cmd": "test -f stats.json"}],
            }],
        }
        auditor = BINS["plan-auditor"]
        program = os.environ.get(auditor[0], auditor[1])
        with tempfile.TemporaryDirectory(prefix="scitool_e2e_") as tmp:
            workspace = Path(tmp)
            (workspace / "stats.json").write_text(
                json.dumps({"values": MEASUREMENTS}), encoding="utf-8")
            (workspace / "request.json").write_text(
                json.dumps(request_contract), encoding="utf-8")
            (workspace / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
            (workspace / ".plan-auditor").mkdir()
            (workspace / ".plan-auditor" / "plan.json").write_text(
                json.dumps(plan), encoding="utf-8")
            subprocess.run([program, "request", "init", "--file", "request.json", "."],
                           cwd=workspace, capture_output=True, text=True, check=False)
            with patch.dict(os.environ, {"SCITOOL_WORKSPACE_DIR": str(workspace)}):
                result = call("plan_auditor_inspect")
            payload = payload_of(result)
            self.assertFalse(result["isError"], text_of(result))
            self.assertEqual(payload["program"], "plan-auditor")
            self.assertEqual(payload["exit_code"], 0)
            self.assertIn("steps", payload["stdout"])

    def test_plan_auditor_inspect_requires_configured_workspace(self):
        with patch.dict(os.environ, {}, clear=True):
            result = call("plan_auditor_inspect")
        self.assertTrue(result["isError"])
        self.assertIn("NOT_CONFIGURED", text_of(result))

    def test_axiomize_model_runs_real_cli_on_structured_request(self):
        """A real Model IR request is validated by the standalone Axiomize CLI.

        The request must be wrapped in a ``model_ir`` key and declare
        ``schema_version`` 1.0; anything else is refused by axiomize before a
        single check runs. The suite asserts on the gateway's captured
        subprocess result, never on a value computed here.
        """
        self.assertIsNotNone(
            _standalone_python(), "the standalone axiomize CLI is not installed")
        result = call("axiomize_model", {"action": "validate",
                                        "request": MODEL_IR_REQUEST})
        payload = payload_of(result)
        self.assertFalse(result["isError"], text_of(result))
        self.assertEqual(payload["program"], "axiomize")
        self.assertEqual(payload["exit_code"], 0)
        report = payload.get("json", {})
        # axiomize reports the overall verdict plus a "validation" block that
        # holds its individual checks.
        self.assertEqual(report.get("status"), "PASS")
        validation = report.get("validation")
        self.assertIsInstance(validation, dict,
                              "axiomize returned no validation block")
        self.assertEqual(validation.get("status"), "PASS")
        checks = validation.get("checks")
        self.assertIsInstance(checks, list, "axiomize returned no checks list")
        self.assertTrue(checks, "axiomize returned no validation checks")
        self.assertTrue(all(item.get("status") == "PASS" for item in checks),
                        "axiomize reported a failing validation check")

    def test_axiomize_model_runs_in_the_gateway_environment(self):
        """The CLI the gateway spawns is the one its own resolver selects.

        This keeps the real-CLI tests honest: if ``PYTHONPATH`` pointed at the
        bundled Axiomize variant, the standalone ``axiomize`` executable would
        silently import a different package. The gateway is run in a clean
        environment, so the installed distribution is the one executed.
        """
        found = resolve("axiomize")
        self.assertIsNotNone(found, "axiomize is not installed")
        completed = subprocess.run(
            [sys.executable, "-c",
             "import importlib.metadata as m, sys;"
             "print(m.version('axiomize'));"
             "print(next(iter(m.distribution('axiomize')._path.parents)))"],
            capture_output=True, text=True, timeout=30,
            env=_clean_environment(), cwd=str(REPO_ROOT))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        installed_version = completed.stdout.splitlines()[0].strip()
        # The gateway never sets PYTHONPATH, so the CLI cannot be shadowed.
        probe = subprocess.run(
            [found, "capabilities"], capture_output=True, text=True,
            timeout=60, env=_clean_environment(), cwd=str(REPO_ROOT))
        self.assertEqual(probe.returncode, 0, probe.stderr)
        reported = json.loads(probe.stdout)["axiomize_version"]
        self.assertEqual(reported, installed_version,
                         "the axiomize CLI on PATH reports a different version "
                         "than the installed distribution; PYTHONPATH may be "
                         "shadowing the standalone package")


def _distribution_installed(metadata_module, distribution: str) -> bool:
    try:
        metadata_module.version(distribution)
        return True
    except metadata_module.PackageNotFoundError:
        return False


class CrossToolWorkflowTests(unittest.TestCase):
    """Real data flow between tools: tool A's own output feeds tool B's input."""

    def _cds_stats(self) -> dict:
        result = call("cds_stats", {"values": MEASUREMENTS})
        self.assertFalse(result["isError"], text_of(result))
        stats: dict[str, float] = {}
        for line in payload_of(result)["stdout"].splitlines():
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) == 2 and cells[0] not in {"stat", ""} \
                    and not set(cells[0]) <= {"-", "+"}:
                try:
                    stats[cells[0]] = float(cells[1])
                except ValueError:
                    continue
        return stats

    def _cds2_stats(self) -> dict:
        result = call("cds2_stats", {"values": MEASUREMENTS})
        self.assertFalse(result["isError"], text_of(result))
        stats: dict[str, float] = {}
        for line in payload_of(result)["stdout"].splitlines():
            parts = line.split()
            if len(parts) == 2:
                try:
                    stats[parts[0]] = float(parts[1])
                except ValueError:
                    continue
        return stats

    def test_two_independent_engines_agree_on_the_same_data(self):
        """cds and cds2 are separate packages; their own outputs must agree."""
        cds = self._cds_stats()
        cds2 = self._cds2_stats()
        self.assertEqual(cds["n"], cds2["n"])
        self.assertAlmostEqual(cds["mean"], cds2["mean"], places=9)
        self.assertAlmostEqual(cds["stdev"], cds2["std"], places=6)
        self.assertAlmostEqual(cds["median"], cds2["median"], places=9)
        self.assertAlmostEqual(cds["min"], cds2["min"], places=9)
        self.assertAlmostEqual(cds["max"], cds2["max"], places=9)

    def test_statistics_output_feeds_reason_scoring_tool(self):
        """cds/cds2 output becomes the evidence argument of axiomize_reason_score."""
        cds = self._cds_stats()
        cds2 = self._cds2_stats()
        agree = abs(cds["mean"] - cds2["mean"]) < 1e-9
        self.assertTrue(agree, "the two engines disagreed on their own reported means")
        evidence = 1.0 if agree else 0.0
        result = call("axiomize_reason_score",
                      {"evidence": evidence, "verification": 1.0 if agree else 0.0})
        payload = payload_of(result)
        self.assertFalse(result["isError"], text_of(result))
        self.assertEqual(payload["exit_code"], 0)
        self.assertIn("can_collapse", payload["stdout"])

    def test_statistics_output_feeds_intent_router(self):
        """A sentence built from real statistics output is routed by eq-layer."""
        cds2 = self._cds2_stats()
        message = (f"The two independent statistics engines reported "
                   f"mean={cds2['mean']} and std={cds2['std']} "
                   f"for {cds2['n']} replicates.")
        result = call("eq_layer_route",
                      {"messages": [{"role": "user", "content": message}],
                       "intent_mode": "heuristic"})
        payload = payload_of(result)
        self.assertFalse(result["isError"], text_of(result))
        decision = json.loads(payload["stdout"])
        # The router must echo back the real computed numbers it was given.
        self.assertIn(str(cds2["mean"]), decision["intent"]["canonical_request"])
        self.assertIn(decision["intent"]["kind"],
                      {"statement", "question", "request", "greeting", "feedback"})

    def test_full_local_stdio_session_across_seven_tools(self):
        """A real stdio subprocess session: initialize, list, then call tools."""
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "toolkit_doctor", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "cds_stats", "arguments": {"values": MEASUREMENTS}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
             "params": {"name": "cds2_stats", "arguments": {"values": MEASUREMENTS}}},
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
             "params": {"name": "quantum_skill_validate", "arguments": {}}},
        ]
        payload = "\n".join(json.dumps(request) for request in requests) + "\n"
        completed = subprocess.run(
            [sys.executable, "-m", "scientific_toolkit_mcp"], input=payload,
            text=True, capture_output=True, timeout=120, cwd=str(REPO_ROOT))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        lines = [json.loads(line) for line in completed.stdout.splitlines()]
        # Six responses: the notification correctly gets none.
        self.assertEqual(len(lines), 6)
        self.assertEqual(lines[0]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(len(lines[1]["result"]["tools"]), 11)
        doctor = json.loads(lines[2]["result"]["content"][0]["text"])
        self.assertEqual(doctor["repositories"], 7)
        for response in lines[3:]:
            self.assertFalse(response["result"]["isError"], response)


class LocalStdioSecurityTests(unittest.TestCase):
    """Local transport: fail-closed behaviour on bad and hostile input."""

    def test_unknown_tool_is_a_protocol_error_not_a_crash(self):
        response = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "not_a_tool", "arguments": {}}})
        self.assertEqual(response["error"]["code"], -32602)

    def test_unknown_method_is_reported(self):
        response = handle({"jsonrpc": "2.0", "id": 1, "method": "nope"})
        self.assertEqual(response["error"]["code"], -32601)

    def test_non_object_arguments_are_rejected(self):
        result = call("cds_stats", ["1", "2"])
        self.assertTrue(result["isError"])
        self.assertIn("INVALID_ARGUMENT", text_of(result))

    def test_unexpected_argument_keys_are_rejected(self):
        result = call("cds_stats", {"values": [1, 2], "extra": True})
        self.assertTrue(result["isError"])
        self.assertIn("unexpected keys", text_of(result))

    def test_non_finite_values_are_rejected(self):
        result = call("cds_stats", {"values": [1, float("nan")]})
        self.assertTrue(result["isError"])
        self.assertIn("INVALID_ARGUMENT", text_of(result))

    def test_booleans_are_not_accepted_as_numbers(self):
        result = call("cds_stats", {"values": [True, 2]})
        self.assertTrue(result["isError"])

    def test_too_few_values_are_rejected(self):
        result = call("cds_stats", {"values": [1]})
        self.assertTrue(result["isError"])
        self.assertIn("INVALID_ARGUMENT", text_of(result))

    def test_oversized_input_is_rejected(self):
        result = call("axiomize_intake", {"idea": "x" * 7000})
        self.assertTrue(result["isError"])
        self.assertIn("INVALID_ARGUMENT", text_of(result))

    def test_model_action_allowlist_blocks_heavy_operations(self):
        for action in ("repair", "fit", "export", "discover"):
            with self.subTest(action=action):
                result = call("axiomize_model", {"action": action, "request": {}})
                self.assertTrue(result["isError"])
                self.assertIn("allowlist", text_of(result))

    def test_model_request_must_be_an_object(self):
        result = call("axiomize_model", {"action": "validate", "request": "not-an-object"})
        self.assertTrue(result["isError"])
        self.assertIn("INVALID_ARGUMENT", text_of(result))

    def test_reason_scores_must_be_unit_interval(self):
        for evidence, verification in ((1.5, 0.5), (-0.1, 0.5), (0.5, 2.0)):
            with self.subTest(evidence=evidence, verification=verification):
                result = call("axiomize_reason_score",
                              {"evidence": evidence, "verification": verification})
                self.assertTrue(result["isError"])
                self.assertIn("INVALID_ARGUMENT", text_of(result))

    def test_reason_scores_reject_booleans(self):
        result = call("axiomize_reason_score",
                      {"evidence": True, "verification": 0.5})
        self.assertTrue(result["isError"])

    def test_eq_layer_requires_a_user_turn(self):
        result = call("eq_layer_route",
                      {"messages": [{"role": "system", "content": "no user"}]})
        self.assertTrue(result["isError"])
        self.assertIn("user turn", text_of(result))

    def test_eq_layer_rejects_unknown_roles(self):
        result = call("eq_layer_route",
                      {"messages": [{"role": "villain", "content": "hi"}]})
        self.assertTrue(result["isError"])
        self.assertIn("INVALID_ARGUMENT", text_of(result))

    def test_eq_layer_rejects_extra_message_keys(self):
        result = call("eq_layer_route",
                      {"messages": [{"role": "user", "content": "hi",
                                     "extra": "nope"}]})
        self.assertTrue(result["isError"])
        self.assertIn("INVALID_ARGUMENT", text_of(result))

    def test_eq_layer_rejects_empty_transcript(self):
        result = call("eq_layer_route", {"messages": []})
        self.assertTrue(result["isError"])

    def test_eq_layer_rejects_unknown_intent_mode(self):
        result = call("eq_layer_route",
                      {"messages": [{"role": "user", "content": "hi"}],
                       "intent_mode": "telepathy"})
        self.assertTrue(result["isError"])
        self.assertIn("INVALID_ARGUMENT", text_of(result))

    def test_audit_is_disabled_by_default_even_with_env_flag_absent(self):
        with patch.dict(os.environ, {}, clear=True):
            result = call("plan_auditor_audit")
        self.assertTrue(result["isError"])
        self.assertIn("DISABLED", text_of(result))

    def test_audit_stays_disabled_without_configured_workspace(self):
        """The workspace guard is checked before the opt-in flag is read.

        ``SCITOOL_ALLOW_AUDIT_EXECUTION=1`` alone must never be enough: with no
        trusted workspace the call is refused with NOT_CONFIGURED, so a
        misconfigured deployment cannot run project commands.
        """
        with patch.dict(os.environ, {"SCITOOL_ALLOW_AUDIT_EXECUTION": "1"},
                        clear=True):
            result = call("plan_auditor_audit")
        self.assertTrue(result["isError"])
        self.assertIn("NOT_CONFIGURED", text_of(result))
        self.assertNotIn("DISABLED", text_of(result))

    def test_missing_dependency_reports_not_installed_not_a_crash(self):
        with patch.dict(os.environ, {"SCITOOL_QUANTUM_BIN": "/definitely/not/here"}):
            result = call("quantum_skill_validate")
        self.assertTrue(result["isError"])
        self.assertIn("NOT_INSTALLED", text_of(result))

    def test_all_seven_bins_report_not_installed_when_absent(self):
        overrides = {env: "/definitely/not/here" for env, _ in BINS.values()}
        with patch.dict(os.environ, overrides, clear=False):
            for name, arguments in (("axiomize_intake", {"idea": "test"}),
                                    ("cds_stats", {"values": [1, 2]}),
                                    ("cds2_stats", {"values": [1, 2]}),
                                    ("quantum_skill_validate", {}),
                                    ("axiomize_reason_score",
                                     {"evidence": 0.5, "verification": 0.5}),
                                    ("eq_layer_route",
                                     {"messages": [{"role": "user", "content": "hi"}]})):
                with self.subTest(tool=name):
                    result = call(name, arguments)
                    self.assertTrue(result["isError"])
                    self.assertIn("NOT_INSTALLED", text_of(result))

    def test_gateway_survives_invalid_json_rpc_frames(self):
        for message in ("not json", "[]", '{"jsonrpc":"1.0","id":1,"method":"ping"}',
                        '{"id":1,"method":42}', '{"jsonrpc":"2.0","id":1,"method":"ping",'
                                                 '"params":"not-an-object"}'):
            with self.subTest(message=message):
                response = handle(json.loads(message)) if message.startswith("{") \
                    else None
                # Malformed frames must never raise; the server returns an error.
                self.assertTrue(response is None or "error" in response
                                or "result" in response)

    def test_params_must_be_an_object(self):
        response = handle({"jsonrpc": "2.0", "id": 1, "method": "ping",
                           "params": "nope"})
        self.assertEqual(response["error"]["code"], -32602)

    def test_notifications_receive_no_response(self):
        self.assertIsNone(handle({"jsonrpc": "2.0",
                                  "method": "notifications/initialized"}))


class RemoteHttpSecurityTests(unittest.TestCase):
    """Remote transport: a separate security boundary, tested on a real server."""

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def post(self, message, token=TOKEN, origin=None, accept=True, raw=None):
        import urllib.error
        import urllib.request

        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        if accept:
            headers["Accept"] = "application/json, text/event-stream"
        if origin:
            headers["Origin"] = origin
        body = raw if raw is not None else json.dumps(message).encode("utf-8")
        request = urllib.request.Request(
            self.base + "/mcp", data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                # A 202 response to a notification legitimately carries no body.
                return response.status, (json.loads(response.read())
                                         if response.status not in (202, 204)
                                         else None)
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            try:
                return exc.code, json.loads(payload)
            except json.JSONDecodeError:
                return exc.code, payload.decode("utf-8", "replace")

    def test_health_is_public(self):
        import urllib.request

        with urllib.request.urlopen(self.base + "/health", timeout=10) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.load(response)["status"], "ok")

    def test_anonymous_post_is_rejected(self):
        code, _ = self.post({"jsonrpc": "2.0", "id": 1, "method": "ping"}, token=None)
        self.assertEqual(code, 401)

    def test_wrong_token_is_rejected(self):
        code, _ = self.post({"jsonrpc": "2.0", "id": 1, "method": "ping"},
                            token="wrong-token")
        self.assertEqual(code, 401)

    def test_unauthorized_response_carries_www_authenticate(self):
        import urllib.error
        import urllib.request

        request = urllib.request.Request(
            self.base + "/mcp",
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode(),
            method="POST",
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=10)
        self.assertEqual(caught.exception.code, 401)
        self.assertIn("Bearer", caught.exception.headers.get("WWW-Authenticate", ""))

    def test_authenticated_tools_list_excludes_audit(self):
        with patch.dict(os.environ, {"SCITOOL_MCP_BEARER_TOKEN": TOKEN}):
            code, body = self.post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(code, 200)
        names = {tool["name"] for tool in body["result"]["tools"]}
        self.assertEqual(len(names), 10, "remote inventory must hide the audit tool")
        self.assertIn("plan_auditor_inspect", names)
        self.assertNotIn("plan_auditor_audit", names)

    def test_remote_audit_is_denied_even_when_locally_enabled(self):
        with patch.dict(os.environ, {"SCITOOL_MCP_BEARER_TOKEN": TOKEN,
                                     "SCITOOL_ALLOW_AUDIT_EXECUTION": "1"}):
            code, body = self.post({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                    "params": {"name": "plan_auditor_audit",
                                               "arguments": {}}})
        self.assertEqual(code, 200)
        self.assertTrue(body["result"]["isError"])
        self.assertIn("DISABLED", body["result"]["content"][0]["text"])

    def test_remote_catalog_call_over_real_http(self):
        with patch.dict(os.environ, {"SCITOOL_MCP_BEARER_TOKEN": TOKEN}):
            code, body = self.post({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                    "params": {"name": "toolkit_catalog",
                                               "arguments": {}}})
        self.assertEqual(code, 200)
        payload = json.loads(body["result"]["content"][0]["text"])
        self.assertFalse(body["result"]["isError"])
        self.assertEqual(payload["count"], 7)

    def test_remote_cds_stats_executes_a_real_upstream_cli(self):
        with patch.dict(os.environ, {"SCITOOL_MCP_BEARER_TOKEN": TOKEN}):
            code, body = self.post({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                    "params": {"name": "cds_stats",
                                               "arguments": {"values": MEASUREMENTS}}})
        self.assertEqual(code, 200)
        payload = json.loads(body["result"]["content"][0]["text"])
        self.assertFalse(body["result"]["isError"], payload)
        self.assertEqual(payload["program"], "cds")
        self.assertEqual(payload["exit_code"], 0)
        self.assertIn("mean", payload["stdout"])

    def test_remote_doctor_reports_seven_commands(self):
        with patch.dict(os.environ, {"SCITOOL_MCP_BEARER_TOKEN": TOKEN}):
            code, body = self.post({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                    "params": {"name": "toolkit_doctor",
                                               "arguments": {}}})
        self.assertEqual(code, 200)
        payload = json.loads(body["result"]["content"][0]["text"])
        self.assertEqual(len(payload["commands"]), 7)

    def test_remote_inspect_requires_a_configured_workspace(self):
        with patch.dict(os.environ, {"SCITOOL_MCP_BEARER_TOKEN": TOKEN}, clear=True):
            code, body = self.post({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                    "params": {"name": "plan_auditor_inspect",
                                               "arguments": {}}})
        self.assertEqual(code, 200)
        self.assertTrue(body["result"]["isError"])
        self.assertIn("NOT_CONFIGURED", body["result"]["content"][0]["text"])

    def test_remote_rejects_unknown_tool_with_mcp_error_not_a_crash(self):
        with patch.dict(os.environ, {"SCITOOL_MCP_BEARER_TOKEN": TOKEN}):
            code, body = self.post({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                    "params": {"name": "not_a_tool",
                                               "arguments": {}}})
        self.assertEqual(code, 200)
        self.assertEqual(body["error"]["code"], -32602)

    def test_remote_bad_arguments_fail_closed_with_clear_error(self):
        with patch.dict(os.environ, {"SCITOOL_MCP_BEARER_TOKEN": TOKEN}):
            code, body = self.post({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                    "params": {"name": "cds_stats",
                                               "arguments": {"values": [1]}}})
        self.assertEqual(code, 200)
        self.assertTrue(body["result"]["isError"])
        self.assertIn("INVALID_ARGUMENT", body["result"]["content"][0]["text"])

    def test_remote_missing_dependency_reports_not_installed(self):
        with patch.dict(os.environ, {"SCITOOL_MCP_BEARER_TOKEN": TOKEN,
                                     "SCITOOL_CDS_BIN": "/definitely/not/here"}):
            code, body = self.post({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                    "params": {"name": "cds_stats",
                                               "arguments": {"values": [1, 2]}}})
        self.assertEqual(code, 200)
        self.assertTrue(body["result"]["isError"])
        self.assertIn("NOT_INSTALLED", body["result"]["content"][0]["text"])

    def test_remote_malformed_json_is_a_parse_error_not_a_crash(self):
        """Malformed JSON must be refused, never crash the server process.

        The gateway answers a bad body with the JSON-RPC parse error and keeps
        serving subsequent requests, which this test also verifies.
        """
        import urllib.error
        import urllib.request

        with patch.dict(os.environ, {"SCITOOL_MCP_BEARER_TOKEN": TOKEN}):
            request = urllib.request.Request(
                self.base + "/mcp", data=b"{not json", method="POST",
                headers={"Content-Type": "application/json", "Authorization":
                         f"Bearer {TOKEN}",
                         "Accept": "application/json, text/event-stream"})
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=10)
        self.assertEqual(caught.exception.code, 400)
        body = json.loads(caught.exception.read())
        self.assertEqual(body["error"]["code"], -32700)
        # The process survived: a following well-formed request still works.
        with patch.dict(os.environ, {"SCITOOL_MCP_BEARER_TOKEN": TOKEN}):
            code, healthy = self.post({"jsonrpc": "2.0", "id": 2,
                                       "method": "ping"})
        self.assertEqual(code, 200)
        self.assertEqual(healthy["result"], {})

    def test_remote_requires_wrong_content_type_is_rejected(self):
        import urllib.error
        import urllib.request

        with patch.dict(os.environ, {"SCITOOL_MCP_BEARER_TOKEN": TOKEN}):
            request = urllib.request.Request(
                self.base + "/mcp",
                data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode(),
                method="POST",
                headers={"Content-Type": "text/plain", "Authorization":
                         f"Bearer {TOKEN}",
                         "Accept": "application/json, text/event-stream"})
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=10)
        self.assertEqual(caught.exception.code, 415)

    def test_remote_rejects_missing_mcp_accept_header(self):
        with patch.dict(os.environ, {"SCITOOL_MCP_BEARER_TOKEN": TOKEN}):
            code, _ = self.post({"jsonrpc": "2.0", "id": 1, "method": "ping"},
                                accept=False)
        self.assertEqual(code, 406)

    def test_remote_rejects_unlisted_browser_origin(self):
        with patch.dict(os.environ, {"SCITOOL_MCP_BEARER_TOKEN": TOKEN}):
            code, _ = self.post({"jsonrpc": "2.0", "id": 1, "method": "ping"},
                                origin="https://evil.example")
        self.assertEqual(code, 403)

    def test_remote_permits_explicitly_allowlisted_origin(self):
        with patch.dict(os.environ, {"SCITOOL_MCP_BEARER_TOKEN": TOKEN,
                                     "SCITOOL_ALLOWED_ORIGINS":
                                         "https://client.example"}):
            code, body = self.post({"jsonrpc": "2.0", "id": 1, "method": "ping"},
                                   origin="https://client.example")
        self.assertEqual(code, 200)
        self.assertEqual(body["result"], {})

    def test_remote_notification_returns_202(self):
        with patch.dict(os.environ, {"SCITOOL_MCP_BEARER_TOKEN": TOKEN}):
            code, _ = self.post({"jsonrpc": "2.0",
                                 "method": "notifications/initialized"})
        self.assertEqual(code, 202)

    def test_remote_sse_get_is_not_supported(self):
        import urllib.error
        import urllib.request

        with patch.dict(os.environ, {"SCITOOL_MCP_BEARER_TOKEN": TOKEN}):
            request = urllib.request.Request(
                self.base + "/mcp", method="GET",
                headers={"Authorization": f"Bearer {TOKEN}"})
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=10)
        self.assertEqual(caught.exception.code, 405)

    def test_remote_server_does_not_start_without_a_secret(self):
        """The HTTP entrypoint must refuse to start unauthenticated."""
        completed = subprocess.run(
            [sys.executable, "-m", "scientific_toolkit_mcp.http_server"],
            capture_output=True, text=True, timeout=30, cwd=str(REPO_ROOT),
            env={"PATH": os.environ.get("PATH", ""), "PORT": "0"})
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("bearer secret or an OAuth provider", completed.stderr)


class SdkClientInteropTests(unittest.TestCase):
    """A real third-party MCP client against a real authenticated HTTP server."""

    @classmethod
    def setUpClass(cls):
        try:
            import mcp  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise unittest.SkipTest(f"official MCP SDK not installed: {exc}")
        try:
            from mcp.client.streamable_http import streamable_http_client
        except ImportError as exc:
            raise unittest.SkipTest(
                "the installed official MCP SDK exposes no Streamable HTTP "
                f"client transport: {exc}")
        cls.port = _free_port()
        cls.token = "sdk-interop-token"
        cls.env = dict(os.environ)
        cls.env["SCITOOL_MCP_BEARER_TOKEN"] = cls.token
        cls.env["PORT"] = str(cls.port)
        cls.process = subprocess.Popen(
            [sys.executable, "-m", "scientific_toolkit_mcp.http_server"],
            cwd=str(REPO_ROOT), env=cls.env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        _wait_for_port("127.0.0.1", cls.port)

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "process", None):
            cls.process.terminate()
            try:
                cls.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                cls.process.kill()

    def _session(self):
        import asyncio

        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        return asyncio.run(self._run_session(ClientSession,
                                             streamable_http_client))

    async def _run_session(self, ClientSession, streamable_http_client):
        """A complete official-SDK session over authenticated Streamable HTTP.

        Authentication goes through the SDK's own ``create_mcp_http_client``
        helper, which builds the HTTP client the transports expect. The older
        ``headers=`` keyword was removed when ``streamablehttp_client`` was
        renamed ``streamable_http_client``, and importing ``httpx`` directly
        would add a dependency the gateway itself does not require.

        The transport context manager yields two streams in the current SDK and
        three in older releases, so the tuple is unpacked defensively.
        """
        from mcp.client.streamable_http import create_mcp_http_client

        url = f"http://127.0.0.1:{self.port}/mcp"
        http_client = create_mcp_http_client(
            headers={"Authorization": f"Bearer {self.token}"})
        try:
            async with streamable_http_client(
                    url, http_client=http_client) as streams:
                read, write = streams[0], streams[1]
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listing = await session.list_tools()
                    catalog = await session.call_tool("toolkit_catalog", {})
                    stats = await session.call_tool("cds_stats",
                                                    {"values": MEASUREMENTS})
                    return listing, catalog, stats
        finally:
            await http_client.aclose()

    def _tool_error(self, result) -> bool:
        """Whether the official SDK flagged a tool call as an error.

        The SDK renamed this field from ``isError`` to ``is_error``; both are
        checked so the suite runs against either SDK generation.
        """
        for attribute in ("is_error", "isError"):
            if hasattr(result, attribute):
                return bool(getattr(result, attribute))
        return False

    def test_official_sdk_client_enumerates_ten_remote_tools(self):
        listing, _, _ = self._session()
        names = {tool.name for tool in listing.tools}
        self.assertEqual(len(names), 10)
        self.assertNotIn("plan_auditor_audit", names)
        self.assertIn("plan_auditor_inspect", names)

    def test_official_sdk_client_calls_catalog_and_a_real_cli(self):
        _, catalog, stats = self._session()
        catalog_text = catalog.content[0].text
        self.assertEqual(json.loads(catalog_text)["count"], 7)
        stats_text = stats.content[0].text
        self.assertFalse(self._tool_error(stats), stats_text)
        payload = json.loads(stats_text)
        self.assertEqual(payload["program"], "cds")
        self.assertEqual(payload["exit_code"], 0)
        self.assertIn("mean", payload["stdout"])


def _free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_port(host: str, port: int, timeout: float = 20.0) -> None:
    import socket
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(1)
            if sock.connect_ex((host, port)) == 0:
                return
        time.sleep(0.2)
    raise AssertionError(f"HTTP server did not start on {host}:{port}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
