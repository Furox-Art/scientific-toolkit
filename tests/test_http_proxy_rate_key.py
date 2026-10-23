"""Rate-limit identity must not be spoofable when a proxy is trusted."""

from __future__ import annotations

import pytest

from scientific_toolkit_mcp import http_server


def test_proxy_header_is_ignored_without_explicit_trust(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SCITOOL_TRUST_PROXY", raising=False)
    assert http_server._rate_key("192.0.2.9", ["203.0.113.7"]) == "192.0.2.9"


def test_trusted_proxy_uses_the_rightmost_valid_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCITOOL_TRUST_PROXY", "1")
    assert (
        http_server._rate_key("10.0.0.1", ["198.51.100.4, 203.0.113.8"])
        == "203.0.113.8"
    )


def test_trusted_proxy_needs_exactly_one_header_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCITOOL_TRUST_PROXY", "1")
    assert http_server._rate_key("10.0.0.1", None) == "10.0.0.1"
    assert http_server._rate_key("10.0.0.1", []) == "10.0.0.1"
    assert (
        http_server._rate_key("10.0.0.1", ["203.0.113.8", "198.51.100.4"])
        == "10.0.0.1"
    )


def test_trusted_proxy_skips_malformed_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCITOOL_TRUST_PROXY", "1")
    assert (
        http_server._rate_key("10.0.0.1", ["not-an-ip, 2001:db8::1"])
        == "2001:db8::1"
    )
    assert http_server._rate_key("10.0.0.1", ["nope, still-nope"]) == "10.0.0.1"
