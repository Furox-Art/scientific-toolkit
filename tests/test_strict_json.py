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

    def test_unpaired_surrogates_and_non_utf8_wire_encodings_are_rejected(self):
        for source in (
            r'{"id":"\ud800","method":"ping"}',
            r'{"nested":{"text":"\udfff"}}',
            r'{"list":["\ud800"]}',
            '{"id":1}'.encode('utf-16'),
        ):
            with self.subTest(source=source), self.assertRaises((ValueError, UnicodeError)):
                loads(source)

    def test_valid_multilingual_utf8_and_surrogate_pairs_are_preserved(self):
        for source in (
            '{"id":"Türkçe 日本語 😀"}',
            r'{"id":"\ud83d\ude00"}',
        ):
            parsed = loads(source)
            self.assertIn('id', parsed)
            self.assertEqual(loads(json.dumps(parsed).encode('utf-8')), parsed)

    def test_malformed_json_raises_decoder_error(self):
        with self.assertRaises(json.JSONDecodeError):
            loads(b'{"a":}')
