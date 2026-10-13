"""Distribution packaging tests: what ships must include every package module.

The release/health verification helper lives inside the package
(``scientific_toolkit_mcp/production_probe.py``), so a published wheel must
carry it; a helper that only exists in the repository checkout is missing
downstream. The wheel is built here from a pristine copy of the declared
sources with the build backend pyproject.toml declares, so the assertion
needs no network access, no extra tooling, and no repository state.
"""

import importlib.resources
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from scientific_toolkit_mcp import __version__

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = REPO_ROOT / "scientific_toolkit_mcp"
RELEASE_PROBE = "scientific_toolkit_mcp/production_probe.py"
# Exactly the sources the declared build backend needs for the distribution.
BUILD_SOURCES = ("pyproject.toml", "README.md", "LICENSE", "scientific_toolkit_mcp")


class PackagingTests(unittest.TestCase):
    def setUp(self):
        try:
            from setuptools import build_meta
        except ImportError as exc:  # pragma: no cover - declared build backend
            self.skipTest(f"declared build backend unavailable: {exc}")
        self.build_meta = build_meta

    def _build_wheel(self) -> tuple[str, list[str]]:
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "src"
            for name in BUILD_SOURCES:
                origin = REPO_ROOT / name
                target = source / name
                if origin.is_dir():
                    shutil.copytree(origin, target)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(origin, target)
            output = Path(td) / "dist"
            output.mkdir()
            previous = Path.cwd()
            os.chdir(source)
            try:
                name = self.build_meta.build_wheel(str(output))
            finally:
                os.chdir(previous)
            with zipfile.ZipFile(output / name) as wheel:
                return name, wheel.namelist()

    def test_wheel_carries_every_package_module(self):
        _, contents = self._build_wheel()
        expected = {
            f"scientific_toolkit_mcp/{path.name}"
            for path in PACKAGE.glob("*.py")
        }
        self.assertTrue(expected)
        for name in sorted(expected):
            self.assertIn(name, contents, f"{name} is missing from the wheel")

    def test_wheel_contains_the_release_probe_helper(self):
        # The deployed startup/production probe is part of the package, not of
        # the repository scripts, so it must be present in the wheel content.
        self.assertTrue((PACKAGE / "production_probe.py").is_file())
        _, contents = self._build_wheel()
        self.assertIn(RELEASE_PROBE, contents)
        self.assertTrue(
            importlib.resources.files("scientific_toolkit_mcp")
            .joinpath("production_probe.py").is_file())

    def test_wheel_is_named_after_the_package_version(self):
        name, _ = self._build_wheel()
        self.assertIn(f"furox_scientific_toolkit_mcp-{__version__}-", name)
        self.assertTrue(name.endswith(".whl"))


if __name__ == "__main__":
    unittest.main()
