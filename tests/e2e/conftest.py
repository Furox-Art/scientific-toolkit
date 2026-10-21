"""Deterministic rate-limit isolation for the end-to-end HTTP suite.

``scientific_toolkit_mcp.http_server`` charges every POST -- authenticated or
not -- to a module-global, per-client bucket keyed by source address, and all
end-to-end requests originate from ``127.0.0.1``. Buckets survive across test
cases, classes, and even earlier ``pytest`` invocations in the same process,
so once ``RATE_LIMIT`` requests have accumulated the server answers 429 and an
assertion that expects 401 (for example
``RemoteHttpSecurityTests::test_wrong_token_is_rejected``) becomes order- and
history-dependent.

Clearing the bucket before each test restores a fresh per-test budget without
touching the production ``RATE_LIMIT`` / ``WINDOW_SECONDS`` values or the
rate-limiting behaviour itself.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from scientific_toolkit_mcp import http_server


@pytest.fixture(autouse=True)
def _clear_http_rate_limit_bucket() -> Iterator[None]:
    """Drop accumulated hits so every test starts with a full rate budget."""
    with http_server._lock:
        http_server._hits.clear()
    yield
