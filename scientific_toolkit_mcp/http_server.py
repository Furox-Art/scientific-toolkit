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
import re
import threading
import time
from urllib.parse import urlsplit

from .server import handle
from .strict_json import loads as strict_json_loads
from . import oauth

MAX_REQUEST = 131072
RATE_LIMIT = 20
WINDOW_SECONDS = 60
MAX_CLIENT_BUCKETS = 4096
MAX_CONCURRENT = 4
# Bounded reads prevent stalled clients from holding all worker slots forever.
BODY_READ_TIMEOUT_SECONDS = 5.0
# Read-only plan inspection is allowed for authenticated clients. Running an
# audit executes commands from project plans; keep that action local-only.
LOCAL_ONLY_TOOLS = frozenset({"plan_auditor_audit"})
_lock = threading.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)
_last_sweep = 0.0
_semaphore = threading.BoundedSemaphore(MAX_CONCURRENT)


def _record_rate_hit(client: str, now: float) -> bool:
    """Caller holds _lock. Keep per-client buckets bounded and expire idle IPs.

    Without eviction, each one-off source address remains in _hits forever;
    a rotating set of addresses can grow the dictionary without limit.
    Reject a new address when the table is full rather than evicting
    active clients and resetting their rate-limit budget.
    """
    global _last_sweep
    if now - _last_sweep >= WINDOW_SECONDS or (
        client not in _hits and len(_hits) >= MAX_CLIENT_BUCKETS
    ):
        for address, times in list(_hits.items()):
            while times and now - times[0] > WINDOW_SECONDS:
                times.popleft()
            if not times:
                del _hits[address]
        _last_sweep = now

    if client not in _hits and len(_hits) >= MAX_CLIENT_BUCKETS:
        return False

    times = _hits[client]
    while times and now - times[0] > WINDOW_SECONDS:
        times.popleft()
    if len(times) >= RATE_LIMIT:
        return False
    times.append(now)
    return True


def _accepts_mcp(accept_headers: list[str]) -> bool:
    """Require both real media types with positive HTTP quality weights.

    String substring searches incorrectly accept fake MIME types and q=0
    entries, causing unsupported clients to pass protocol negotiation.
    """
    available: set[str] = set()
    for header in accept_headers:
        for entry in header.split(","):
            fields = [field.strip() for field in entry.split(";")]
            media_type = fields[0].lower()
            if not media_type:
                continue
            quality = 1.0
            quality_seen = False
            for parameter in fields[1:]:
                name, separator, value = parameter.partition("=")
                if not separator:
                    return False
                if name.strip().lower() == "q":
                    if quality_seen:
                        return False
                    quality_seen = True
                    try:
                        quality = float(value.strip().strip('"'))
                    except ValueError:
                        return False
                    if not 0.0 <= quality <= 1.0:
                        return False
            if quality > 0.0:
                available.add(media_type)
    return {"application/json", "text/event-stream"} <= available


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
        # More than one Origin has no unambiguous security interpretation.
        origins = self.headers.get_all('Origin', [])
        return len(origins) == 0 or (
            len(origins) == 1 and origins[0] in self._allowed_origins()
        )

    def _reply(self, code: int, payload=None, *, mcp=False, headers=None):
        raw = b'' if payload is None else json.dumps(payload, ensure_ascii=False,
                  allow_nan=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        origins = self.headers.get_all('Origin', [])
        origin = origins[0] if len(origins) == 1 else None
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
        # A reverse proxy may interpret duplicate Authorization fields
        # differently. Never authenticate an ambiguous credential.
        if len(self.headers.get_all('Authorization', [])) > 1:
            self.close_connection = True
            self._reply(400, {'error': 'ambiguous authorization headers'},
                        headers={'Connection': 'close'})
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
        if not _accepts_mcp(self.headers.get_all('Accept', [])):
            self._reply(406, {'error': 'Accept must include application/json and text/event-stream'})
            return
        # Conflicting framing is unsafe across reverse proxies: the proxy
        # and this handler may disagree which bytes belong to this request.
        # No chunked request decoding is implemented here.
        lengths = self.headers.get_all('Content-Length', [])
        if (
            self.headers.get_all('Transfer-Encoding', [])
            or len(lengths) != 1
            or re.fullmatch(r'[0-9]+', lengths[0].strip()) is None
        ):
            self.close_connection = True
            self._reply(400, {'error': 'ambiguous or unsupported request framing'},
                        headers={'Connection': 'close'})
            return
        raw_length = lengths[0].strip()
        # Also cap decimal digits: Python refuses excessively long integer
        # literals, so the header must not reach int() unchecked.
        if len(raw_length) > len(str(MAX_REQUEST)):
            self.close_connection = True
            self._reply(413, {'error': 'request body too large'},
                        headers={'Connection': 'close'})
            return
        length = int(raw_length)
        if not 0 < length <= MAX_REQUEST:
            self._reply(413, {'error': 'body must be between 1 and 131072 bytes'})
            return
        client = self.client_address[0]
        now = time.monotonic()
        with _lock:
            admitted = _record_rate_hit(client, now)
        if not admitted:
            self._reply(429, {'error': 'rate limit exceeded'})
            return
        if not _semaphore.acquire(blocking=False):
            self._reply(503, {'error': 'server busy'})
            return
        try:
            self.connection.settimeout(BODY_READ_TIMEOUT_SECONDS)
            try:
                body = self.rfile.read(length)
            except TimeoutError:
                self.close_connection = True
                self._reply(408, {'error': 'request body timeout'}, headers={
                    'Connection': 'close',
                })
                return
            if len(body) != length:
                self.close_connection = True
                self._reply(400, {'error': 'incomplete request body'}, headers={
                    'Connection': 'close',
                })
                return
            try:
                message = strict_json_loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
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
    # Diagnostic is disabled by default; never expose a public diagnostic route.
    if os.environ.get('SCITOOL_STARTUP_PROBE') == '1':
        from .production_probe import probe
        def run_probe():
            time.sleep(.5)
            probe(port)
        threading.Thread(target=run_probe, name='mcp-production-probe',
                         daemon=True).start()
    server.serve_forever(poll_interval=.2)


if __name__ == '__main__':
    main()
