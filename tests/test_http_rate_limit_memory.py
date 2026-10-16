"""Per-client HTTP throttling must have a bounded memory footprint."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from scientific_toolkit_mcp import http_server as http


class BoundedRateStateTests(unittest.TestCase):
    def setUp(self) -> None:
        with http._lock:
            http._hits.clear()
            http._last_sweep = 0.0

    def tearDown(self) -> None:
        with http._lock:
            http._hits.clear()
            http._last_sweep = 0.0

    def test_unique_addresses_do_not_grow_state_without_limit(self) -> None:
        with patch.object(http, "MAX_CLIENT_BUCKETS", 3), http._lock:
            for index in range(3):
                self.assertTrue(http._record_rate_hit(f"198.51.100.{index}", 100.0))
            self.assertFalse(http._record_rate_hit("198.51.100.3", 100.1))
            self.assertEqual(len(http._hits), 3)

            # On expiry, inactive addresses are removed before admission.
            self.assertTrue(http._record_rate_hit("203.0.113.1", 161.0))
            self.assertEqual(set(http._hits), {"203.0.113.1"})

    def test_changing_addresses_cannot_reset_existing_client_quota(self) -> None:
        with patch.object(http, "MAX_CLIENT_BUCKETS", 2), http._lock:
            for _ in range(http.RATE_LIMIT):
                self.assertTrue(http._record_rate_hit("198.51.100.1", 50.0))
            self.assertFalse(http._record_rate_hit("198.51.100.1", 50.1))
            self.assertTrue(http._record_rate_hit("203.0.113.2", 50.2))
            self.assertFalse(http._record_rate_hit("203.0.113.3", 50.3))
            self.assertFalse(http._record_rate_hit("198.51.100.1", 50.4))
            self.assertTrue(http._record_rate_hit("198.51.100.1", 111.0))

    def test_empty_and_expired_buckets_are_removed(self) -> None:
        with http._lock:
            self.assertTrue(http._record_rate_hit("first", 100.0))
            self.assertTrue(http._record_rate_hit("second", 120.0))
            self.assertTrue(http._record_rate_hit("third", 161.0))
            self.assertNotIn("first", http._hits)
            self.assertIn("second", http._hits)
