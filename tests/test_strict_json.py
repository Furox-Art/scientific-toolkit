"""Wire decoder rejects ambiguous JSON consistently across transports."""

from __future__ import annotations

import json
import unittest

from scientific_toolkit_mcp.strict_json import loads


class StrictJSONTests(unittest.TestCase):
    def test_regular_json_is_unchanged(self):
        self.assertEqual(
            loads(b'{"method":"ping","params":{"nested":[true,1.5,null]}}'),
            {"method": "ping", "params": {"nested": [True, 1.5, None]}},
        )

    def test_all_nested_duplicates_are_rejected(self):
        for source in (
            '{"a":1,"a":2}',
            '{"a":{"b":1,"b":2}}',
            '{"a":[{"b":1,"b":2}]}',
            '{"a":1,"\\u0061":2}',
        ):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, "duplicate"):
                loads(source)

    def test_nonfinite_json_is_rejected(self):
        for source in ("NaN", "Infinity", "-Infinity", "1e9999", "-1e9999"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                loads(source)

    def test_malformed_json_raises_decoder_error(self):
        with self.assertRaises(json.JSONDecodeError):
            loads(b'{"a":}')
