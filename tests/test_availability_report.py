"""Tests for the availability report producer (scripts/availability_report.py).

The report is a generated artifact: these tests regenerate it into a temporary
directory (never the committed file) and check the semantics of every field --
in particular that a metadata *listing* is never recorded as a *verification*,
and that the pinned-module provenance is recorded for the capture environment.

Hermetic by construction
------------------------
The report probes the *real* machine, so an unisolated run would let whatever
upstream CLIs happen to be installed on the host (or exported through
``SCITOOL_*_BIN``, ``SCITOOL_WORKSPACE_DIR`` or ``PYTHONPATH``) decide the
outcome. ``setUpClass`` therefore builds the report inside a fixed, synthetic
"nothing upstream is installed" environment:

* ``PATH`` is replaced with an empty temporary directory and the process
  ``chdir``s into it, so neither ``shutil.which`` nor the gateway's
  ``.reason-env``/``.reason-pkg`` working-directory fallbacks can resolve a
  real executable.
* Every ``SCITOOL_*`` variable is removed, then each executable override
  (``BINS`` and ``MODULE_SERVERS``) is pointed at a sentinel program name that
  cannot exist. This also neutralises the module-server default of
  ``sys.executable`` (an absolute path that ``shutil.which`` would find even
  with an empty ``PATH``) and any override CI exports.
* ``PYTHONPATH`` is removed so no isolated install directory leaks in.
* The report module's ``importlib.metadata`` handle is replaced with a stub
  whose ``version()`` always raises ``PackageNotFoundError``, so the
  ``listed`` flag cannot depend on which distributions the running
  interpreter happens to have registered.

Under that environment every upstream record must be a KNOWN GAP with no
executed call (``verified`` false), and every fail-closed check must still be
refused in-process with its documented marker. No upstream CLI, network call
or subprocess is required or reached; the assertions below pin both the
scenario and the report semantics, so the result is identical on a bare
machine, on a developer host full of upstream CLIs, and in CI.

The real-machine capture remains the job of ``scripts/availability_report.py``
itself and of ``tests/e2e`` (which deliberately drives the installed tools).
"""

import importlib.util
import os
import tempfile
import unittest
from importlib import metadata
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    location = REPO_ROOT / "scripts" / "availability_report.py"
    spec = importlib.util.spec_from_file_location("availability_report", location)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


report_module = _load_module()
build_report = report_module.build_report

# A program name that cannot resolve: the isolated PATH and working directory
# are empty, so no PATHEXT variant of this name exists anywhere the lookup can
# reach. Pointing every override at it makes "absent" the deterministic state.
ABSENT_SENTINEL = "scitool-hermetic-absent-upstream"


class _AbsentDistributionMetadata:
    """Stub of the report module's ``importlib.metadata`` handle.

    Every distribution looks unregistered, so ``listed`` is decided by the
    test environment, not by the host interpreter's site-packages.
    """

    PackageNotFoundError = metadata.PackageNotFoundError

    @staticmethod
    def version(distribution: str) -> str:
        raise metadata.PackageNotFoundError(distribution)


class AvailabilityReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._isolated = tempfile.TemporaryDirectory(prefix="scitool_availability_")
        cls._mp = pytest.MonkeyPatch()
        try:
            # Drop every gateway override and opt-in (workspace, audit
            # execution, pins, executable overrides) plus PYTHONPATH.
            for key in list(os.environ):
                if key.startswith("SCITOOL_") or key == "PYTHONPATH":
                    cls._mp.delenv(key, raising=False)
            # Empty PATH and an empty working directory: no real executable
            # and no .reason-env/.reason-pkg fallback can resolve.
            cls._mp.setenv("PATH", cls._isolated.name)
            cls._mp.chdir(cls._isolated.name)
            # Pin every executable override -- including the module-server
            # interpreter default -- to the absent sentinel.
            for env_var, _default in report_module.BINS.values():
                cls._mp.setenv(env_var, ABSENT_SENTINEL)
            for env_var, _module, _import_name in report_module.MODULE_SERVERS.values():
                cls._mp.setenv(env_var, ABSENT_SENTINEL)
            # Package metadata is host state too: make every distribution
            # look unregistered so `listed` is deterministic.
            cls._mp.setattr(report_module, "metadata", _AbsentDistributionMetadata)
            cls.report = build_report()
        except BaseException:
            cls._mp.undo()
            cls._isolated.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls._mp.undo()
        cls._isolated.cleanup()

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
        self.assertEqual(len(records), 10)
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
                # Hermetic scenario: the isolated environment must have held.
                # No host CLI, override or metadata listing may leak through.
                self.assertIsNone(record["executable"])
                self.assertFalse(record["listed"])
                self.assertFalse(record["verified"])
                self.assertEqual(record["verdict"], "KNOWN_GAP")

    def test_summary_counts_match_the_records(self):
        summary = self.report["summary"]
        records = self.report["upstream_tools"]
        self.assertEqual(summary["repositories_total"], len(records))
        self.assertEqual(summary["verified"],
                         sum(1 for r in records if r["verified"]))
        self.assertEqual(summary["verified_repositories"],
                         [r["repository"] for r in records if r["verified"]])
        self.assertEqual(summary["available"] + summary["known_gaps"], len(records))
        # Hermetic scenario: nothing upstream resolves, so the summary must
        # report ten known gaps and zero verifications on every machine.
        self.assertEqual(summary["available"], 0)
        self.assertEqual(summary["known_gaps"], 10)
        self.assertEqual(summary["verified"], 0)
        self.assertEqual(summary["verified_repositories"], [])

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
        # The sentinel override must also neutralise the module-server
        # interpreter default (sys.executable resolves even with empty PATH).
        self.assertIsNone(nomosguard["executable"])

    def test_fail_closed_checks_all_refuse_as_expected(self):
        checks = self.report["fail_closed_checks"]
        self.assertEqual(len(checks), 9)
        for check in checks:
            with self.subTest(tool=check["gateway_tool"]):
                self.assertTrue(check["isError"], check)
                self.assertTrue(check["marker_present"], check)


if __name__ == "__main__":
    unittest.main()
