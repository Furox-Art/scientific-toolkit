"""Tests for the availability report producer (scripts/availability_report.py).

The report is a generated artifact: these tests regenerate it into a temporary
directory (never the committed file) and check the semantics of every field --
in particular that a metadata *listing* is never recorded as a *verification*,
and that the pinned-module provenance is recorded for the capture environment.
No upstream CLI is required; missing tools are recorded as KNOWN GAPs.
"""

import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    location = REPO_ROOT / "scripts" / "availability_report.py"
    spec = importlib.util.spec_from_file_location("availability_report", location)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


report_module = _load_module()
build_report = report_module.build_report


class AvailabilityReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = build_report()

    def test_report_marks_itself_as_a_generated_artifact(self):
        self.assertEqual(self.report["generated_by"], "scripts/availability_report.py")
        self.assertIn("availability_report.py", self.report["regenerate_command"])
        self.assertIn("never hand-edit", self.report["generated_artifact_note"])
        self.assertEqual(self.report["schema"]["version"], 2)
        notes = " ".join(self.report["schema"]["notes"])
        self.assertIn("listing", notes)
        self.assertIn("verification", notes)

    def test_every_upstream_record_splits_listed_from_verified(self):
        records = self.report["upstream_tools"]
        self.assertEqual(len(records), 9)
        for record in records:
            with self.subTest(repository=record["repository"]):
                self.assertIsInstance(record["listed"], bool)
                self.assertIsInstance(record["verified"], bool)
                # The deprecated alias must never disagree with the new field.
                self.assertEqual(record["installed"], record["listed"])
                self.assertIn(record["verdict"], {"AVAILABLE", "KNOWN_GAP", "CAPABILITY_FAILED"})
                call = record["gateway_call"]
                self.assertEqual(isinstance(call["exit_code"], int), record["verified"])
                if record["verdict"] == "KNOWN_GAP":
                    # A known gap can still be listed in package metadata while
                    # its executable is absent: listing is not verification.
                    self.assertFalse(record["verified"])

    def test_summary_counts_match_the_records(self):
        summary = self.report["summary"]
        records = self.report["upstream_tools"]
        self.assertEqual(summary["repositories_total"], len(records))
        self.assertEqual(summary["verified"],
                         sum(1 for r in records if r["verified"]))
        self.assertEqual(summary["verified_repositories"],
                         [r["repository"] for r in records if r["verified"]])
        self.assertEqual(summary["available"] + summary["known_gaps"], len(records))

    def test_environment_records_pinned_module_provenance(self):
        pinned = self.report["environment"]["pinned_distribution_modules"]
        self.assertIn("axiomize", pinned)
        self.assertEqual(pinned["axiomize"]["module"], "axiomize")
        providers = pinned["axiomize"]["sys_path_providers"]
        self.assertIsInstance(providers, list)
        self.assertTrue(all(isinstance(p, str) for p in providers))

    def test_module_server_is_probed_without_claiming_a_cli_version(self):
        records = {record["repository"]: record for record in self.report["upstream_tools"]}
        nomosguard = records["nomosguard"]
        self.assertEqual(nomosguard["module"], "nomosguard.mcp_stdio")
        self.assertIsInstance(nomosguard["module_importable"], bool)
        self.assertFalse(nomosguard["cli_self_reported_version"]["reported"])
        self.assertIn("module server", nomosguard["cli_self_reported_version"]["reason"])
        self.assertIsNone(records["eq-layer"]["module"])

    def test_fail_closed_checks_all_refuse_as_expected(self):
        checks = self.report["fail_closed_checks"]
        self.assertEqual(len(checks), 9)
        for check in checks:
            with self.subTest(tool=check["gateway_tool"]):
                self.assertTrue(check["isError"], check)
                self.assertTrue(check["marker_present"], check)


if __name__ == "__main__":
    unittest.main()
