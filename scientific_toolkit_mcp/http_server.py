"""Restricted stateless Streamable HTTP transport for the scientific toolkit.

Provider-neutral MCP transport for clients supporting stateless Streamable HTTP
and explicit bearer-token headers. HTTPS is provided by the reverse proxy.
Browser Origins require explicit configuration; no vendor is privileged.
"""
from __future__ import annotations

from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import time
from urllib.parse import urlsplit

from .server import handle
from . import oauth

MAX_REQUEST = 131072
RATE_LIMIT = 20
WINDOW_SECONDS = 60
MAX_CONCURRENT = 4
LOCAL_ONLY_TOOLS = frozenset({"plan_auditor_audit", "plan_auditor_inspect"})
_lock = threading.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)
_semaphore = threading.BoundedSemaphore(MAX_CONCURRENT)


def _authorized(request: BaseHTTPRequestHandler) -> bool:
    return oauth.authorized(request.headers.get('Authorization', ''))


class Handler(BaseHTTPRequestHandler):
    server_version = 'ScientificToolkitMCP'
    sys_version = ''

    def log_message(self, fmt, *args):
        # Do not accidentally log bearer tokens or client-supplied raw bodies.
        return

    def _allowed_origins(self) -> set[str]:
        return {origin.strip() for origin in
                os.environ.get('SCITOOL_ALLOWED_ORIGINS', '').split(',') if origin.strip()}

    def _origin_allowed(self) -> bool:
        origin = self.headers.get('Origin')
        return not origin or origin in self._allowed_origins()

    def _reply(self, code: int, payload=None, *, mcp=False, headers=None):
        raw = b'' if payload is None else json.dumps(payload, ensure_ascii=False,
                  allow_nan=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Cache-Control', 'no-store')
        origin = self.headers.get('Origin')
        if origin and origin in self._allowed_origins():
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers',
                             'Authorization, Content-Type, Accept, MCP-Protocol-Version, '
                             'Mcp-Session-Id, Last-Event-ID')
        self.send_header('Content-Length', str(len(raw)))
        if payload is not None:
            self.send_header('Content-Type', 'application/json' if mcp else 'application/json; charset=utf-8')
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if raw:
            self.wfile.write(raw)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ('/.well-known/oauth-protected-resource',
                    '/.well-known/oauth-protected-resource/mcp'):
            try:
                config = oauth.settings()
            except ValueError:
                self._reply(503, {'error': 'invalid OAuth configuration'})
                return
            if config is None:
                self._reply(404, {'error': 'OAuth not configured'})
            else:
                self._reply(200, oauth.resource_metadata(config))
        elif path == '/health':
            self._reply(200, {'status': 'ok', 'service': 'scientific-toolkit-mcp',
                              'transport': 'streamable-http'})
        elif urlsplit(self.path).path == '/mcp':
            # The Streamable HTTP spec permits 405 when SSE GET is unsupported.
            self._reply(405, {'error': 'SSE GET not supported; use JSON-RPC POST'})
        else:
            self._reply(404, {'error': 'not found'})

    def do_OPTIONS(self):
        if urlsplit(self.path).path != '/mcp':
            self._reply(404, {'error': 'not found'})
        elif not self._origin_allowed():
            self._reply(403, {'error': 'origin not allowed'})
        else:
            self._reply(204)

    def do_DELETE(self):
        self._reply(405, {'error': 'stateless endpoint; no MCP session to delete'})

    def do_POST(self):
        if urlsplit(self.path).path != '/mcp':
            self._reply(404, {'error': 'not found'})
            return
        if not self._origin_allowed():
            self._reply(403, {'error': 'origin not allowed'})
            return
        if not _authorized(self):
            challenge = 'Bearer realm="scientific-toolkit"'
            try:
                config = oauth.settings()
                if config is not None:
                    challenge += f', resource_metadata="{oauth.metadata_url(config)}"'
            except ValueError:
                self._reply(503, {'error': 'invalid OAuth configuration'})
                return
            self._reply(401, {'error': 'authentication required'}, headers={
                'WWW-Authenticate': challenge})
            return
        if self.headers.get('Content-Type', '').split(';', 1)[0].strip().lower() != 'application/json':
            self._reply(415, {'error': 'application/json required'})
            return
        accept = self.headers.get('Accept', '')
        if 'application/json' not in accept or 'text/event-stream' not in accept:
            self._reply(406, {'error': 'Accept must include application/json and text/event-stream'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            length = 0
        if not 0 < length <= MAX_REQUEST:
            self._reply(413, {'error': 'body must be between 1 and 131072 bytes'})
            return
        client = self.client_address[0]
        now = time.monotonic()
        with _lock:
            times = _hits[client]
            while times and now - times[0] > WINDOW_SECONDS:
                times.popleft()
            if len(times) >= RATE_LIMIT:
                self._reply(429, {'error': 'rate limit exceeded'})
                return
            times.append(now)
        if not _semaphore.acquire(blocking=False):
            self._reply(503, {'error': 'server busy'})
            return
        try:
            body = self.rfile.read(length)
            try:
                message = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._reply(400, {'jsonrpc': '2.0', 'id': None, 'error': {
                    'code': -32700, 'message': 'Parse error'}}, mcp=True)
                return
            if isinstance(message, dict) and message.get('method') == 'tools/call':
                params = message.get('params')
                if isinstance(params, dict) and params.get('name') in LOCAL_ONLY_TOOLS:
                    self._reply(200, {'jsonrpc': '2.0', 'id': message.get('id'),
                        'result': {'content': [{'type': 'text',
                        'text': 'DISABLED: plan workspace actions are local-only'}],
                        'isError': True}}, mcp=True)
                    return
            output = handle(message)
            # Do not advertise tools that are intentionally unavailable remotely.
            if (isinstance(message, dict) and message.get('method') == 'tools/list'
                    and output and 'result' in output):
                output['result']['tools'] = [
                    tool for tool in output['result']['tools']
                    if tool['name'] not in LOCAL_ONLY_TOOLS]
            if output is None:
                self._reply(202)
            else:
                self._reply(200, output, mcp=True)
        finally:
            _semaphore.release()


def main():
    if not os.environ.get('SCITOOL_MCP_BEARER_TOKEN') and oauth.settings() is None:
        raise RuntimeError('Configure either a bearer secret or an OAuth provider')
    oauth.settings()  # Incomplete optional OAuth settings must not start the server.
    port = int(os.environ.get('PORT', '8000'))
    server = ThreadingHTTPServer(('0.0.0.0', port), Handler)
    server.daemon_threads = True
    server.serve_forever(poll_interval=.2)


if __name__ == '__main__':
    main()
