"""Integration tests for MCP protocol + conservative upstream CLI adapters."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
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


if __name__ == "__main__":
    unittest.main()
