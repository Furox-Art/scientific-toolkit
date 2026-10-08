"""Local end-to-end HTTP transport checks, including unauthorized traffic."""
import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from scientific_toolkit_mcp.http_server import Handler

TOKEN = 'test-token-not-for-production'

class HttpTest(unittest.TestCase):
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

    def test_requires_mcp_accept(self):
        with patch.dict(os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN}):
            code, _ = self.send('POST', '/mcp', {'jsonrpc': '2.0', 'id': 1,
                                                  'method': 'ping'}, accept=False)
        self.assertEqual(code, 406)

    def test_notification_202(self):
        with patch.dict(os.environ, {'SCITOOL_MCP_BEARER_TOKEN': TOKEN}):
            code, _ = self.send('POST', '/mcp', {'jsonrpc': '2.0',
                                                 'method': 'notifications/initialized'})
        self.assertEqual(code, 202)

    def test_get_mcp_405(self):
        self.assertEqual(self.send('GET', '/mcp')[0], 405)

if __name__ == '__main__':
    unittest.main()
