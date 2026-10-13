"""Integration tests for MCP protocol + conservative upstream CLI adapters."""

import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from scientific_toolkit_mcp.catalog import catalog
from scientific_toolkit_mcp.server import TOOLS, handle
from scientific_toolkit_mcp import tools


def call(name, args=None):
    r = handle({"jsonrpc": "2.0", "id": 22, "method": "tools/call",
                "params": {"name": name, "arguments": args or {}}})
    assert r is not None
    return r["result"]


class ToolTests(unittest.TestCase):
    def test_catalog_has_seven_distinct_original_repos(self):
        items = catalog()
        self.assertEqual(len(items), 7)
        self.assertEqual(len({i["name"] for i in items}), 7)
        self.assertTrue(all(i["url"].startswith("https://github.com/Furox-Art/") for i in items))
        self.assertEqual(set().union(*(set(i["tools"]) for i in items)) | {"toolkit_catalog", "toolkit_doctor"},
                         {t["name"] for t in TOOLS})

    def test_initialize(self):
        r = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(r["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(r["result"]["serverInfo"]["name"], "furox-scientific-toolkit")

    def test_no_notification_response(self):
        self.assertIsNone(handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_catalog_tool(self):
        r = call("toolkit_catalog")
        self.assertFalse(r["isError"])
        self.assertEqual(json.loads(r["content"][0]["text"])["count"], 7)

    def test_unknown_tool_is_protocol_error(self):
        r = handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "nope"}})
        self.assertEqual(r["error"]["code"], -32602)

    def test_unknown_method(self):
        r = handle({"jsonrpc": "2.0", "id": 1, "method": "nonexistent"})
        self.assertEqual(r["error"]["code"], -32601)

    def test_audit_fails_closed_without_config(self):
        with patch.dict(os.environ, {}, clear=True):
            r = call("plan_auditor_audit")
            self.assertTrue(r["isError"])
            self.assertIn("DISABLED", r["content"][0]["text"])

    def test_inspect_requires_existing_workspace(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIn("NOT_CONFIGURED", call("plan_auditor_inspect")["content"][0]["text"])

    def test_stats_rejects_nonfinite_or_invalid(self):
        for values in [[float("nan"), 2], [True, 1], [1], ["1", 2]]:
            with self.subTest(values=values):
                self.assertTrue(call("cds_stats", {"values": values})["isError"])

    def test_eq_message_contract(self):
        r = call("eq_layer_route", {"messages": [{"role": "system", "content": "not a user"}]})
        self.assertTrue(r["isError"])
        self.assertIn("user turn", r["content"][0]["text"])

    def test_model_deny_unknown_action(self):
        r = call("axiomize_model", {"action": "repair", "request": {}})
        self.assertTrue(r["isError"])
        self.assertIn("allowlist", r["content"][0]["text"])

    def test_reason_enforces_bounded_scores(self):
        r = call("axiomize_reason_score", {"evidence": 1.1, "verification": .3})
        self.assertTrue(r["isError"])

    def test_fails_if_binary_missing(self):
        with patch.dict(os.environ, {"SCITOOL_QUANTUM_BIN": "/not/a/real/executable"}):
            r = call("quantum_skill_validate")
            self.assertTrue(r["isError"])
            self.assertIn("NOT_INSTALLED", r["content"][0]["text"])

    def test_fake_cli_is_invoked_without_shell(self):
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / "fakecli"
            fake.write_text(f"#!{sys.executable}\nimport sys, json\nprint(json.dumps({{'argv': sys.argv[1:]}}))\n", encoding="utf-8")
            fake.chmod(0o755)
            with patch.dict(os.environ, {"SCITOOL_EQ_BIN": str(fake), "SCITOOL_CDS2_BIN": str(fake)}):
                eq = call("eq_layer_route", {"messages": [{"role": "user", "content": "Test me"}]})
                self.assertFalse(eq["isError"])
                x = json.loads(eq["content"][0]["text"])
                argv = x["json"]["argv"]
                self.assertEqual(argv[:3], ["route", "--intent-mode", "heuristic"])
                self.assertEqual(json.loads(argv[4]), [{"role": "user", "content": "Test me"}])
                stats = call("cds2_stats", {"values": [1, 2, 3]})
                self.assertFalse(stats["isError"])
                self.assertEqual(json.loads(stats["content"][0]["text"])["json"]["argv"], ["stats", "1,2,3"])

    def test_fake_cli_nonzero_is_mcp_error(self):
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / "failcli"
            fake.write_text(f"#!{sys.executable}\nimport sys\nprint('UNKNOWN')\nsys.exit(3)\n", encoding="utf-8")
            fake.chmod(0o755)
            with patch.dict(os.environ, {"SCITOOL_REASON_BIN": str(fake)}):
                r = call("axiomize_reason_score", {"evidence": .5, "verification": .7})
                self.assertTrue(r["isError"])
                x = json.loads(r["content"][0]["text"])
                self.assertEqual(x["exit_code"], 3)
                self.assertEqual(x["status"], "COMMAND_FAILED")

    def test_full_stdio_roundtrip(self):
        reqs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "toolkit_catalog", "arguments": {}}},
        ]
        p = subprocess.run([sys.executable, "-m", "scientific_toolkit_mcp"],
                           input="\n".join(json.dumps(x) for x in reqs) + "\n",
                           text=True, capture_output=True, timeout=10)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stderr, "")
        lines = [json.loads(line) for line in p.stdout.splitlines()]
        self.assertEqual(len(lines), 3)
        self.assertEqual(len(lines[1]["result"]["tools"]), 11)
        self.assertEqual(json.loads(lines[2]["result"]["content"][0]["text"])["count"], 7)


class ToolRoutingTests(unittest.TestCase):
    """One router: every tool is dispatched through the single TOOL_ROUTES table."""

    def test_routes_cover_every_tool_exactly_once(self):
        names = [t["name"] for t in TOOLS]
        self.assertEqual(sorted(names), sorted(tools.TOOL_ROUTES))
        self.assertEqual(len(names), len(set(names)))

    def test_declared_keys_match_the_mcp_tool_specs(self):
        for spec in TOOLS:
            allowed, handler = tools.TOOL_ROUTES[spec["name"]]
            schema = spec["inputSchema"]
            self.assertTrue(callable(handler), spec["name"])
            self.assertEqual(frozenset(schema["properties"]), allowed, spec["name"])
            self.assertTrue(set(schema.get("required", [])) <= set(allowed), spec["name"])
            self.assertIs(schema.get("additionalProperties"), False, spec["name"])

    def test_each_route_rejects_unexpected_keys(self):
        for name in tools.TOOL_ROUTES:
            with self.subTest(tool=name):
                with self.assertRaises(tools.ToolFailure) as err:
                    tools.dispatch(name, {"unexpected_key": 1})
                self.assertIn("unexpected keys", str(err.exception))

    def test_each_route_rejects_non_object_arguments(self):
        for name in tools.TOOL_ROUTES:
            with self.subTest(tool=name):
                for args in ([], "x", 3, None):
                    with self.assertRaises(tools.ToolFailure) as err:
                        tools.dispatch(name, args)
                    self.assertIn("must be an object", str(err.exception))

    def test_unknown_tool_is_reported_by_the_single_router(self):
        with self.assertRaises(tools.ToolFailure) as err:
            tools.dispatch("definitely_not_a_tool", {})
        self.assertIn("UNKNOWN_TOOL: definitely_not_a_tool", str(err.exception))

    def test_each_passthrough_shape_reaches_its_own_handler(self):
        sample = {
            "toolkit_catalog": {},
            "toolkit_doctor": {},
            "axiomize_intake": {"idea": "x"},
            "axiomize_model": {"action": "validate", "request": {}},
            "cds_stats": {"values": [1, 2]},
            "cds2_stats": {"values": [1, 2]},
            "plan_auditor_inspect": {},
            "plan_auditor_audit": {},
            "quantum_skill_validate": {},
            "axiomize_reason_score": {"evidence": 0.5, "verification": 0.5},
            "eq_layer_route": {"messages": [{"role": "user", "content": "x"}]},
        }
        for name, args in sample.items():
            with self.subTest(tool=name):
                seen = []
                fake = lambda a: seen.append(a) or {"routed": name}  # noqa: E731
                allowed = tools.TOOL_ROUTES[name][0]
                with patch.dict(tools.TOOL_ROUTES, {name: (allowed, fake)}):
                    self.assertEqual(tools.dispatch(name, args), {"routed": name})
                self.assertEqual(seen, [args])

    def test_key_validation_runs_before_every_handler(self):
        # The router owns the key check, so a handler never sees an undeclared key.
        seen = []
        fake = lambda a: seen.append(a) or {}  # noqa: E731
        with patch.dict(tools.TOOL_ROUTES, {"cds_stats": (frozenset({"values"}), fake)}):
            with self.assertRaises(tools.ToolFailure):
                tools.dispatch("cds_stats", {"values": [1, 2], "nested": {"deep": True}})
        self.assertEqual(seen, [])


class TimeoutTests(unittest.TestCase):
    """Every upstream call has an explicit, bounded execution timeout."""

    def test_every_declared_timeout_stays_within_the_bound(self):
        source = (Path(tools.__file__).resolve()).read_text(encoding="utf-8")
        declared = [int(v) for v in re.findall(r"seconds=(\d+)", source)]
        self.assertTrue(declared, "no declared per-call timeouts found")
        for value in declared:
            self.assertGreaterEqual(value, tools.MIN_CALL_TIMEOUT, value)
            self.assertLessEqual(value, tools.MAX_CALL_TIMEOUT, value)
        self.assertLessEqual(tools.DEFAULT_CALL_TIMEOUT, tools.MAX_CALL_TIMEOUT)

    def test_per_call_timeout_must_be_a_bounded_integer(self):
        for seconds in (0, -1, tools.MAX_CALL_TIMEOUT + 1, 30.5, True, "30", None):
            with self.subTest(seconds=seconds):
                with self.assertRaises(tools.ToolFailure) as err:
                    tools._call("cds", ["stats", "1,2"], seconds=seconds)
                self.assertIn("timeout must be an integer", str(err.exception))

    def test_timeout_expiry_is_a_tool_failure_not_a_crash(self):
        with patch.dict(os.environ, {"SCITOOL_CDS_BIN": sys.executable}):
            start = time.monotonic()
            with self.assertRaises(tools.ToolFailure) as err:
                tools._call("cds", ["-c", "import time; time.sleep(30)"], seconds=1)
            self.assertIn("TIMEOUT: cds exceeded 1s", str(err.exception))
            self.assertLess(time.monotonic() - start, 20)

    def test_boundary_timeouts_are_accepted(self):
        for seconds in (tools.MIN_CALL_TIMEOUT, tools.MAX_CALL_TIMEOUT):
            with self.subTest(seconds=seconds):
                with patch.dict(os.environ, {"SCITOOL_CDS_BIN": "/not/a/real/executable"}):
                    with self.assertRaises(tools.ToolFailure) as err:
                        tools._call("cds", ["stats", "1,2"], seconds=seconds)
                self.assertIn("NOT_INSTALLED", str(err.exception))


def _fake_distribution(root: Path, version: str) -> Path:
    """An installed-looking distribution: top-level module plus dist-info."""
    package = root / "axiomize"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    info = root / f"axiomize-{version}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: axiomize\nVersion: {version}\n",
        encoding="utf-8")
    return root


class PinnedDistributionTests(unittest.TestCase):
    """A same-named module must never silently replace a pinned distribution."""

    def test_shadowed_module_fails_the_call_loud(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pinned = _fake_distribution(root / "site-packages", "1.12.5")
            shadow = _fake_distribution(root / ".reason-pkg", "1.2.1")
            # Only the two controlled providers remain on sys.path.
            keep = [p for p in sys.path if p and not (Path(p) / "axiomize").is_dir()]
            with patch.object(sys, "path", [str(shadow), str(pinned), *keep]):
                with patch.dict(os.environ, {"SCITOOL_AXIOMIZE_BIN": sys.executable}):
                    r = call("axiomize_intake", {"idea": "idea"})
            self.assertTrue(r["isError"])
            text = r["content"][0]["text"]
            self.assertIn("BAD_CONFIGURATION", text)
            self.assertIn("shadowed", text)
            self.assertIn(str(pinned / "axiomize"), text)
            self.assertIn(str(shadow / "axiomize"), text)

    def test_unshadowed_module_proceeds_past_the_pin_gate(self):
        with tempfile.TemporaryDirectory() as td:
            pinned = _fake_distribution(Path(td), "1.12.5")
            keep = [p for p in sys.path if p and not (Path(p) / "axiomize").is_dir()]
            with patch.object(sys, "path", [str(pinned), *keep]):
                with patch.dict(os.environ, {"SCITOOL_AXIOMIZE_BIN": sys.executable}):
                    r = call("axiomize_intake", {"idea": "idea"})
            self.assertTrue(r["isError"])
            text = r["content"][0]["text"]
            self.assertNotIn("BAD_CONFIGURATION", text)

    def test_missing_executable_still_reports_not_installed(self):
        # NOT_INSTALLED stays the informative error when nothing is installed,
        # even in an environment whose import path is shadowed.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pinned = _fake_distribution(root / "site-packages", "1.12.5")
            shadow = _fake_distribution(root / ".reason-pkg", "1.2.1")
            keep = [p for p in sys.path if p and not (Path(p) / "axiomize").is_dir()]
            with patch.object(sys, "path", [str(shadow), str(pinned), *keep]):
                with patch.dict(os.environ, {"SCITOOL_AXIOMIZE_BIN": "/definitely/not/here"}):
                    r = call("axiomize_intake", {"idea": "idea"})
            self.assertTrue(r["isError"])
            self.assertIn("NOT_INSTALLED", r["content"][0]["text"])

    def test_unpinned_tools_are_not_blocked_by_an_axiomize_shadow(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pinned = _fake_distribution(root / "site-packages", "1.12.5")
            shadow = _fake_distribution(root / ".reason-pkg", "1.2.1")
            keep = [p for p in sys.path if p and not (Path(p) / "axiomize").is_dir()]
            with patch.object(sys, "path", [str(shadow), str(pinned), *keep]):
                with patch.dict(os.environ, {"SCITOOL_QUANTUM_BIN": "/not/a/real/executable"}):
                    r = call("quantum_skill_validate")
            self.assertTrue(r["isError"])
            self.assertIn("NOT_INSTALLED", r["content"][0]["text"])

    def test_version_pin_mismatch_fails_loud(self):
        with tempfile.TemporaryDirectory() as td:
            pinned = _fake_distribution(Path(td), "1.2.1")
            keep = [p for p in sys.path if p and not (Path(p) / "axiomize").is_dir()]
            with patch.object(sys, "path", [str(pinned), *keep]):
                with patch.dict(os.environ, {"SCITOOL_AXIOMIZE_BIN": sys.executable,
                                             "SCITOOL_PIN_AXIOMIZE": "1.12.5"}):
                    r = call("axiomize_intake", {"idea": "idea"})
            self.assertTrue(r["isError"])
            text = r["content"][0]["text"]
            self.assertIn("BAD_CONFIGURATION", text)
            self.assertIn("version mismatch", text)
            self.assertIn("1.2.1", text)
            self.assertIn("1.12.5", text)

    def test_version_pin_match_proceeds(self):
        with tempfile.TemporaryDirectory() as td:
            pinned = _fake_distribution(Path(td), "1.12.5")
            keep = [p for p in sys.path if p and not (Path(p) / "axiomize").is_dir()]
            with patch.object(sys, "path", [str(pinned), *keep]):
                with patch.dict(os.environ, {"SCITOOL_AXIOMIZE_BIN": sys.executable,
                                             "SCITOOL_PIN_AXIOMIZE": "1.12.5"}):
                    r = call("axiomize_intake", {"idea": "idea"})
            self.assertTrue(r["isError"])
            text = r["content"][0]["text"]
            self.assertNotIn("BAD_CONFIGURATION", text)

    def test_pin_for_a_distribution_that_is_not_installed_fails_loud(self):
        with tempfile.TemporaryDirectory() as td:
            empty = Path(td)
            keep = [p for p in sys.path if p and not (Path(p) / "axiomize").is_dir()]
            with patch.object(sys, "path", [str(empty), *keep]):
                with patch.dict(os.environ, {"SCITOOL_AXIOMIZE_BIN": sys.executable,
                                             "SCITOOL_PIN_AXIOMIZE": "1.12.5"}):
                    r = call("axiomize_intake", {"idea": "idea"})
            self.assertTrue(r["isError"])
            self.assertIn("BAD_CONFIGURATION", r["content"][0]["text"])


class DocumentedInventoryTests(unittest.TestCase):
    """Docs must state the tool inventory the code actually exposes."""

    def test_documented_tool_counts_match_the_code(self):
        local = len(TOOLS)
        remote = local - 1  # plan_auditor_audit is local-only by design
        self.assertEqual(local, 11)
        self.assertEqual(remote, 10)
        self.assertEqual(len(catalog()), 7)
        readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(
            encoding="utf-8")
        self.assertIn(f"{remote} remote tools out of {local} local tools", readme)

    def test_methodology_documents_the_same_inventory(self):
        docs = (Path(__file__).resolve().parents[1] / "docs"
                / "integration-test-methodology.md").read_text(encoding="utf-8")
        self.assertIn("eleven tool names", docs)
        self.assertIn("ten remote-safe tools", docs)


if __name__ == "__main__":
    unittest.main()
