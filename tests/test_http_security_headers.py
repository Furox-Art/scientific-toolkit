"""HTTP response headers must reject content sniffing and framing."""

from __future__ import annotations

import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen

from scientific_toolkit_mcp.http_server import Handler


class HttpSecurityHeadersTests(unittest.TestCase):
    def test_public_and_error_responses_set_security_headers(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            for path in ("/health", "/missing"):
                with self.subTest(path=path):
                    try:
                        response = urlopen(base + path, timeout=3)
                    except HTTPError as exc:
                        response = exc
                    try:
                        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
                        self.assertEqual(response.headers["Cache-Control"], "no-store")
                    finally:
                        response.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=3)
