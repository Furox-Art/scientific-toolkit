"""Local end-to-end HTTP transport checks, including unauthorized traffic."""
import json
import os
import socket
import threading
import tempfile
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from scientific_toolkit_mcp.http_server import Handler, _hits, _lock

TOKEN = 'test-token-not-for-production'

class HttpTest(unittest.TestCase):
    def setUp(self):
        # Rate limits are process-global. A previous integration suite must
        # not consume the next independent test's per-client quota.
        with _lock:
            _hits.clear()

    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.srv.daemon_threads = True
        cls.t = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.t.start()
        cls.base = f'http://127.0.0.1:{cls.srv.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.t.join(timeout=2)

    def send(self, method, path, payload=None, token=TOKEN, accept=True, origin=None):
        headers = {'Content-Type': 'application/json'}
        if token is not None:
            headers['Authorization'] = f'Bearer {token}'
        if accept:
            headers['Accept'] = 'application/json, text/event-stream'
        if origin:
            headers['Origin'] = origin
        body = json.dumps(payload).encode('utf-8') if payload is not None else None
        req = Request(self.base + path, method=method, data=body, headers=headers)
        try:
            with urlopen(req, timeout=3) as r:
                return r.status, json.loads(r.read()) if r.status not in (202, 204) else None
        except HTTPError as e:
            return e.code, json.loads(e.read())

    def test_health(self):
        self.assertEqual(self.send('GET', '/health', token=None)[0], 200)

    def test_no_anonymous_post(self):
        req = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}
        self.assertEqual(self.send('POST', '/mcp', req, token=None)[0], 401)

    def test_wrong_token(self):
        self.assertEqual(self.send('POST', '/mcp', {}, token='wrong')[0], 401)

    def test_tools_list_authenticated(self):
        req = {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}
        with patch.dict(os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN}):
            code, result = self.send('POST', '/mcp', req)
        self.assertEqual(code, 200)
        self.assertEqual(len(result['result']['tools']), 10)
        names = {tool['name'] for tool in result['result']['tools']}
        self.assertIn('plan_auditor_inspect', names)
        self.assertNotIn('plan_auditor_audit', names)

    def test_call_catalog(self):
        req = {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
               'params': {'name': 'toolkit_catalog', 'arguments': {}}}
        with patch.dict(os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN}):
            code, result = self.send('POST', '/mcp', req)
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(result['result']['content'][0]['text'])['count'], 7)

    def test_remote_inspect_requires_configured_workspace(self):
        req = {'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call',
               'params': {'name': 'plan_auditor_inspect', 'arguments': {}}}
        with patch.dict(os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN}, clear=True):
            code, result = self.send('POST', '/mcp', req)
        self.assertEqual(code, 200)
        self.assertTrue(result['result']['isError'])
        self.assertIn('NOT_CONFIGURED', result['result']['content'][0]['text'])

    def test_remote_inspect_calls_only_fixed_readonly_command(self):
        req = {'jsonrpc': '2.0', 'id': 6, 'method': 'tools/call',
               'params': {'name': 'plan_auditor_inspect', 'arguments': {}}}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN,
                                         'SCITOOL_WORKSPACE_DIR': tmp}, clear=True):
                with patch('scientific_toolkit_mcp.tools._call',
                           return_value={'status': 'COMMAND_SUCCEEDED', 'exit_code': 0,
                                         'stdout': '{"plan": "inspected"}'}) as invoke:
                    code, result = self.send('POST', '/mcp', req)
            self.assertEqual(code, 200)
            self.assertFalse(result['result']['isError'])
            invoke.assert_called_once_with(
                'plan-auditor', ['plan', 'inspect', str(Path(tmp).resolve())])

    def test_remote_audit_forbidden(self):
        req = {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call',
               'params': {'name': 'plan_auditor_audit', 'arguments': {}}}
        with patch.dict(os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN,
                                     'SCITOOL_ALLOW_AUDIT_EXECUTION': '1'}):
            _, result = self.send('POST', '/mcp', req)
        self.assertTrue(result['result']['isError'])
        self.assertIn('DISABLED', result['result']['content'][0]['text'])

    def test_bad_origin(self):
        with patch.dict(os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN}):
            code, _ = self.send('POST', '/mcp', {'jsonrpc': '2.0', 'id': 1,
                                                  'method': 'ping'}, origin='https://evil.example')
        self.assertEqual(code, 403)

    def test_custom_client_origin_permitted(self):
        request = {'jsonrpc': '2.0', 'id': 14, 'method': 'ping'}
        with patch.dict(os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN,
                                     'SCITOOL_ALLOWED_ORIGINS': 'https://client.example'}):
            code, result = self.send('POST', '/mcp', request, origin='https://client.example')
        self.assertEqual(code, 200)
        self.assertEqual(result['result'], {})

    def test_custom_origin_denied_by_default(self):
        with patch.dict(os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN,
                                     'SCITOOL_ALLOWED_ORIGINS': ''}):
            code, _ = self.send('POST', '/mcp',
                                {'jsonrpc': '2.0', 'id': 1, 'method': 'ping'},
                                origin='https://claude.ai')
        self.assertEqual(code, 403)

    def test_preflight_permitted_client(self):
        with patch.dict(os.environ, {'SCITOOL_ALLOWED_ORIGINS': 'https://client.example'}):
            code, _ = self.send('OPTIONS', '/mcp', token=None,
                                origin='https://client.example')
        self.assertEqual(code, 204)

    def test_preflight_denies_unlisted_origin(self):
        with patch.dict(os.environ, {'SCITOOL_ALLOWED_ORIGINS': 'https://client.example'}):
            code, _ = self.send('OPTIONS', '/mcp', token=None,
                                origin='https://other.example')
        self.assertEqual(code, 403)

    def test_accept_header_requires_real_positive_quality_media_types(self):
        from scientific_toolkit_mcp.http_server import _accepts_mcp

        invalid = (
            ['application/json-fake, text/event-stream'],
            ['application/json, text/event-stream-fake'],
            ['application/json;q=0, text/event-stream'],
            ['application/json, text/event-stream;q=0'],
            ['application/json, text/event-stream;q=NaN'],
            ['application/json, text/event-stream;q=1.1'],
            ['application/json, text/event-stream;q=1;q=0'],
            ['application/json, text/event-stream; q'],
            [],
        )
        for headers in invalid:
            with self.subTest(headers=headers):
                self.assertFalse(_accepts_mcp(headers))
        for headers in (
            ['application/json, text/event-stream'],
            ['application/json;q=0.8', 'text/event-stream;q=0.6'],
            ['APPLICATION/JSON, TEXT/EVENT-STREAM'],
        ):
            with self.subTest(headers=headers):
                self.assertTrue(_accepts_mcp(headers))

    def test_invalid_accept_is_denied_before_mcp_dispatch(self):
        payload = b'{"jsonrpc":"2.0","id":9,"method":"ping"}'
        for accept, expected in (
            ('application/json-fake, text/event-stream', b' 406 '),
            ('application/json, text/event-stream;q=0', b' 406 '),
            ('application/json;q=0.9, text/event-stream;q=0.8', b' 200 '),
        ):
            with self.subTest(accept=accept), patch.dict(os.environ, {
                'SCITOOL_MCP_BEARER_TOKEN': TOKEN,
            }):
                req = Request(
                    self.base + '/mcp', data=payload, method='POST',
                    headers={
                        'Authorization': f'Bearer {TOKEN}',
                        'Content-Type': 'application/json',
                        'Accept': accept,
                    },
                )
                try:
                    with urlopen(req, timeout=3) as reply:
                        status = reply.status
                except HTTPError as exc:
                    status = exc.code
                    exc.close()
                self.assertEqual(status, int(expected.strip().split()[0]))

    def test_unpaired_unicode_in_request_id_is_a_parse_error(self):
        invalid = b'{"jsonrpc":"2.0","id":"\\ud800","method":"ping"}'
        with patch.dict(os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN}):
            req = Request(
                self.base + '/mcp', data=invalid, method='POST',
                headers={
                    'Authorization': f'Bearer {TOKEN}',
                    'Content-Type': 'application/json',
                    'Accept': 'application/json, text/event-stream',
                },
            )
            with self.assertRaises(HTTPError) as exc:
                urlopen(req, timeout=3)
            self.assertEqual(exc.exception.code, 400)
            reply = json.loads(exc.exception.read())
        self.assertEqual(reply['error']['code'], -32700)

    def test_requires_mcp_accept(self):
        with patch.dict(os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN}):
            code, _ = self.send('POST', '/mcp', {'jsonrpc': '2.0', 'id': 1,
                                                  'method': 'ping'}, accept=False)
        self.assertEqual(code, 406)

    def test_duplicate_authorization_headers_cannot_authorize_a_request(self):
        body = b'{"jsonrpc":"2.0","id":1,"method":"ping"}'
        prefix = (
            b'POST /mcp HTTP/1.1\r\nHost: localhost\r\n'
            b'Content-Type: application/json\r\n'
            b'Accept: application/json, text/event-stream\r\n'
            + f'Content-Length: {len(body)}\r\n'.encode()
        )
        credentials = (
            b'Authorization: Bearer ' + TOKEN.encode() + b'\r\n'
            b'Authorization: Bearer wrong\r\n',
            b'Authorization: Bearer wrong\r\n'
            + b'Authorization: Bearer ' + TOKEN.encode() + b'\r\n',
            (b'Authorization: Bearer ' + TOKEN.encode() + b'\r\n') * 2,
        )
        for headers in credentials:
            with self.subTest(headers=headers):
                with patch.dict(os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN}):
                    with socket.create_connection(
                        ('127.0.0.1', self.srv.server_port), timeout=3
                    ) as sock:
                        sock.settimeout(3)
                        sock.sendall(prefix + headers + b'Connection: close\r\n\r\n' + body)
                        response = sock.makefile('rb').read()
                self.assertIn(b' 400 ', response.split(b'\r\n', 1)[0])
                self.assertIn(b'ambiguous authorization headers', response)

    def test_multiple_origins_never_receive_access_control_allow_origin(self):
        raw_origins = (
            b'Origin: https://client.example\r\nOrigin: https://evil.example\r\n',
            b'Origin: https://evil.example\r\nOrigin: https://client.example\r\n',
            b'Origin: https://client.example\r\nOrigin: https://client.example\r\n',
        )
        for origins in raw_origins:
            with self.subTest(origins=origins):
                raw = (
                    b'OPTIONS /mcp HTTP/1.1\r\nHost: localhost\r\n'
                    + origins + b'Connection: close\r\n\r\n'
                )
                with patch.dict(os.environ, {
                    'SCITOOL_ALLOWED_ORIGINS': 'https://client.example',
                }):
                    with socket.create_connection(
                        ('127.0.0.1', self.srv.server_port), timeout=3
                    ) as sock:
                        sock.settimeout(3)
                        sock.sendall(raw)
                        response = sock.makefile('rb').read()
                headers = response.split(b'\r\n\r\n', 1)[0]
                self.assertIn(b' 403 ', headers.split(b'\r\n', 1)[0])
                self.assertNotIn(b'Access-Control-Allow-Origin:', headers)

    def test_ambiguous_hosts_are_rejected_on_all_http_methods(self):
        for method, path in (('GET', '/health'), ('OPTIONS', '/mcp'),
                             ('DELETE', '/mcp'), ('POST', '/mcp')):
            body = b'{"jsonrpc":"2.0","id":1,"method":"ping"}' if method == 'POST' else b''
            extra = (
                b'Content-Type: application/json\r\n'
                b'Accept: application/json, text/event-stream\r\n'
                + f'Authorization: Bearer {TOKEN}\r\n'.encode()
                + f'Content-Length: {len(body)}\r\n'.encode()
            )
            for hosts in (
                b'Host: localhost\r\nHost: attacker.example\r\n',
                b'Host: attacker.example\r\nHost: localhost\r\n',
                b'Host: localhost\r\nHost: localhost\r\n',
                b'',
            ):
                with self.subTest(method=method, hosts=hosts), patch.dict(
                    os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN}
                ):
                    raw = (
                        f'{method} {path} HTTP/1.1\r\n'.encode() + hosts + extra
                        + b'Connection: close\r\n\r\n' + body
                    )
                    with socket.create_connection(
                        ('127.0.0.1', self.srv.server_port), timeout=3
                    ) as sock:
                        sock.settimeout(3)
                        sock.sendall(raw)
                        response = sock.makefile('rb').read()
                self.assertIn(b' 400 ', response.split(b'\r\n', 1)[0])
                self.assertIn(b'Connection: close', response)

    def test_invalid_json_charset_is_denied_before_mcp_dispatch(self):
        body = b'{"jsonrpc":"2.0","id":1,"method":"ping"}'
        prefix = (
            b'POST /mcp HTTP/1.1\r\nHost: localhost\r\n'
            + f'Authorization: Bearer {TOKEN}\r\n'.encode()
            + b'Accept: application/json, text/event-stream\r\n'
            + f'Content-Length: {len(body)}\r\n'.encode()
        )
        for header in (
            b'Content-Type: application/json; charset=utf-16\r\n',
            b'Content-Type: application/json; charset=latin-1\r\n',
            b'Content-Type: application/json; charset=utf-8; charset=utf-16\r\n',
            b'Content-Type: application/json; charset\r\n',
            b'Content-Type: application/json; boundary=abc\r\n',
        ):
            with self.subTest(header=header), patch.dict(
                os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN}
            ):
                with socket.create_connection(
                    ('127.0.0.1', self.srv.server_port), timeout=3
                ) as sock:
                    sock.settimeout(3)
                    sock.sendall(prefix + header + b'Connection: close\r\n\r\n' + body)
                    response = sock.makefile('rb').read()
                self.assertIn(b' 415 ', response.split(b'\r\n', 1)[0])
        from scientific_toolkit_mcp.http_server import _valid_json_content_type

        self.assertTrue(_valid_json_content_type('application/json'))
        self.assertTrue(_valid_json_content_type('APPLICATION/JSON; CHARSET="UTF-8"'))
        self.assertFalse(_valid_json_content_type('application/json; charset= UTF-16'))
        with patch.dict(os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN}):
            code, response = self.send(
                'POST', '/mcp', {'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}
            )
        self.assertEqual(code, 200)
        self.assertEqual(response['result'], {})

    def test_conflicting_content_type_headers_are_rejected(self):
        body = b'{"jsonrpc":"2.0","id":1,"method":"ping"}'
        base = (
            b'POST /mcp HTTP/1.1\r\nHost: localhost\r\n'
            + f'Authorization: Bearer {TOKEN}\r\n'.encode()
            + b'Accept: application/json, text/event-stream\r\n'
            + f'Content-Length: {len(body)}\r\n'.encode()
        )
        for media_types in (
            b'Content-Type: application/json\r\nContent-Type: text/plain\r\n',
            b'Content-Type: text/plain\r\nContent-Type: application/json\r\n',
            b'Content-Type: application/json\r\nContent-Type: application/json\r\n',
        ):
            with self.subTest(media_types=media_types), patch.dict(
                os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN}
            ):
                with socket.create_connection(
                    ('127.0.0.1', self.srv.server_port), timeout=3
                ) as sock:
                    sock.settimeout(3)
                    sock.sendall(base + media_types + b'Connection: close\r\n\r\n' + body)
                    response = sock.makefile('rb').read()
                self.assertIn(b' 400 ', response.split(b'\r\n', 1)[0])
                self.assertIn(b'Connection: close', response)
                self.assertIn(b'ambiguous content-type headers', response)

        with patch.dict(os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN}):
            code, data = self.send(
                'POST', '/mcp', {'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}
            )
        self.assertEqual(code, 200)
        self.assertEqual(data['result'], {})

    def test_malformed_tool_names_never_crash_http_worker(self):
        with patch.dict(os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN}):
            for bad_name in ([], ['plan_auditor_audit'], {}, {'audit': True}, 123, None):
                with self.subTest(bad_name=bad_name):
                    request = {
                        'jsonrpc': '2.0', 'id': 15, 'method': 'tools/call',
                        'params': {'name': bad_name, 'arguments': {}},
                    }
                    code, response = self.send('POST', '/mcp', request)
                    self.assertEqual(code, 200)
                    self.assertEqual(response['error']['code'], -32602)
            request = {'jsonrpc': '2.0', 'id': 16, 'method': 'ping'}
            code, response = self.send('POST', '/mcp', request)
            self.assertEqual(code, 200)
            self.assertEqual(response['result'], {})

    def test_conflicting_http_request_lengths_are_rejected(self):
        body = b'{"jsonrpc":"2.0","id":2,"method":"ping"}'
        base = (
            b'POST /mcp HTTP/1.1\r\n'
            b'Host: localhost\r\n'
            b'Content-Type: application/json\r\n'
            b'Accept: application/json, text/event-stream\r\n'
            + f'Authorization: Bearer {TOKEN}\r\n'.encode()
        )
        for framing in (
            b'Content-Length: 1\r\nContent-Length: 37\r\n',
            b'Content-Length: 37\r\nTransfer-Encoding: chunked\r\n',
            b'Transfer-Encoding: chunked\r\n',
            b'Content-Length: +37\r\n',
            b'Content-Length: 1,37\r\n',
            b'Content-Length: -1\r\n',
        ):
            with self.subTest(framing=framing), patch.dict(
                os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN}
            ):
                with socket.create_connection(('127.0.0.1', self.srv.server_port), timeout=3) as sock:
                    sock.settimeout(3)
                    sock.sendall(base + framing + b'Connection: close\r\n\r\n' + body)
                    response = sock.makefile('rb').read()
                self.assertIn(b' 400 ', response.split(b'\r\n', 1)[0])
                self.assertIn(b'Connection: close', response)
                self.assertIn(b'ambiguous or unsupported request framing', response)

        huge_length = b'9' * 5000
        with patch.dict(os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN}):
            with socket.create_connection(('127.0.0.1', self.srv.server_port), timeout=3) as sock:
                sock.settimeout(3)
                sock.sendall(
                    base + b'Content-Length: ' + huge_length
                    + b'\r\nConnection: close\r\n\r\n'
                )
                response = sock.makefile('rb').read()
            self.assertIn(b' 413 ', response.split(b'\r\n', 1)[0])

        # Valid framing remains interoperable with ordinary MCP clients.
        with patch.dict(os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN}):
            code, reply = self.send('POST', '/mcp', {'jsonrpc': '2.0', 'id': 1, 'method': 'ping'})
        self.assertEqual(code, 200)
        self.assertEqual(reply['result'], {})

    def test_duplicate_json_object_keys_are_rejected_at_every_depth(self):
        for raw in (
            b'{"jsonrpc":"2.0","id":1,"method":"ping","method":"tools/list"}',
            b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"toolkit_catalog","name":"plan_auditor_audit"}}',
            b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{"nested":{"a":1,"a":2}}}',
            b'{"jsonrpc":"2.0","id":1,"method":"ping","method":"\\u0070ing"}',
        ):
            with self.subTest(raw=raw):
                request = Request(
                    self.base + '/mcp', data=raw, method='POST',
                    headers={
                        'Authorization': f'Bearer {TOKEN}',
                        'Content-Type': 'application/json',
                        'Accept': 'application/json, text/event-stream',
                    },
                )
                with patch.dict(os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN}):
                    with self.assertRaises(HTTPError) as raised:
                        urlopen(request, timeout=3)
                self.assertEqual(raised.exception.code, 400)
                response = json.loads(raised.exception.read())
                self.assertEqual(response['error']['code'], -32700)

    def test_truncated_body_is_rejected_even_if_prefix_is_valid_json(self):
        with patch.dict(os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN}):
            with socket.create_connection(('127.0.0.1', self.srv.server_port), timeout=3) as sock:
                sock.settimeout(3)
                body = b'{"jsonrpc":"2.0","id":1,"method":"ping"}'
                sock.sendall(
                    b'POST /mcp HTTP/1.1\r\n'
                    b'Host: localhost\r\n'
                    + f'Content-Length: {len(body) + 8}\r\n'.encode()
                    + b'Content-Type: application/json\r\n'
                    + b'Accept: application/json, text/event-stream\r\n'
                    + f'Authorization: Bearer {TOKEN}\r\n'.encode()
                    + b'Connection: close\r\n\r\n'
                    + body
                )
                sock.shutdown(socket.SHUT_WR)
                response = sock.makefile('rb').read()
        self.assertIn(b' 400 ', response.split(b'\r\n', 1)[0])
        self.assertIn(b'incomplete request body', response)

    def test_incomplete_body_times_out_instead_of_holding_a_worker_forever(self):
        with patch('scientific_toolkit_mcp.http_server.BODY_READ_TIMEOUT_SECONDS', 0.4):
            with patch.dict(os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN}):
                with socket.create_connection(('127.0.0.1', self.srv.server_port), timeout=3) as sock:
                    sock.settimeout(3)
                    sock.sendall(
                        b'POST /mcp HTTP/1.1\r\n'
                        b'Host: localhost\r\n'
                        b'Content-Length: 100\r\n'
                        b'Content-Type: application/json\r\n'
                        b'Accept: application/json, text/event-stream\r\n'
                        + f'Authorization: Bearer {TOKEN}\r\n'.encode()
                        + b'Connection: close\r\n\r\n'
                        + b'{"jsonrpc":"2.0","id":1'
                    )
                    response = sock.makefile('rb').read()
        self.assertIn(b' 408 ', response.split(b'\r\n', 1)[0])
        self.assertIn(b'request body timeout', response)
        with patch.dict(os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN}):
            code, result = self.send('POST', '/mcp', {
                'jsonrpc': '2.0', 'id': 2, 'method': 'ping',
            })
        self.assertEqual(code, 200)
        self.assertEqual(result['result'], {})

    def test_nonfinite_json_numbers_are_rejected_as_parse_errors(self):
        # The default Python JSON decoder silently accepts NaN and Infinity
        # (including valid exponent syntax that overflows to infinity).
        for invalid in (b'NaN', b'Infinity', b'-Infinity', b'1e9999'):
            with self.subTest(invalid=invalid):
                data = b'{"jsonrpc":"2.0","id":' + invalid + b',"method":"ping"}'
                req = Request(
                    self.base + '/mcp', data=data, method='POST',
                    headers={
                        'Authorization': f'Bearer {TOKEN}',
                        'Content-Type': 'application/json',
                        'Accept': 'application/json, text/event-stream',
                    },
                )
                with patch.dict(os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN}):
                    with self.assertRaises(HTTPError) as raised:
                        urlopen(req, timeout=3)
                self.assertEqual(raised.exception.code, 400)
                response = json.loads(raised.exception.read())
                self.assertEqual(response['error']['code'], -32700)

    def test_notification_202(self):
        with patch.dict(os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN}):
            code, _ = self.send('POST', '/mcp', {'jsonrpc': '2.0',
                                                 'method': 'notifications/initialized'})
        self.assertEqual(code, 202)

    def test_get_mcp_405(self):
        self.assertEqual(self.send('GET', '/mcp')[0], 405)

if __name__ == '__main__':
    unittest.main()
