"""Fail-closed integrity gate for full toolkit and seven adapter test suites."""

from __future__ import annotations

import pytest


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Any skip is a provisioning or test gap, not a green release."""
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:
        return
    skipped = reporter.stats.get("skipped", ())
    if skipped:
        reporter.write_sep("!", f"QUALITY GATE FAILED: {len(skipped)} skipped test(s)")
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
