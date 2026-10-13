"""Optional OAuth resource-server verification for signed JWT access tokens.
The real authorization server and end-user consent must be configured separately.

Credentials are handled as RFC 7235 header bytes. ``hmac.compare_digest`` raises
``TypeError`` for non-ASCII ``str`` operands, so a non-ASCII ``Authorization``
header -- or a non-ASCII bearer secret -- must never reach it as ``str`` input:
a hostile header could otherwise crash the request path instead of being
refused. A credential that cannot be represented as latin-1 header bytes is
malformed and is rejected (fail closed); the comparison can neither raise nor
fail open.
"""
from __future__ import annotations
import hmac
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

@dataclass(frozen=True)
class OAuthConfig:
    issuer: str
    jwks_uri: str
    resource: str
    scope: str

_JWKS_CACHE = {}

def settings() -> OAuthConfig | None:
    values = [os.environ.get(k, '').strip() for k in (
        'SCITOOL_OAUTH_ISSUER', 'SCITOOL_OAUTH_JWKS_URI',
        'SCITOOL_OAUTH_RESOURCE_URI')]
    if not any(values):
        return None
    if not all(values):
        raise ValueError('Incomplete OAuth configuration')
    for value in values:
        url = urlsplit(value)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.fragment:
            raise ValueError('OAuth URLs must use HTTPS without credentials or fragments')
    scope = os.environ.get('SCITOOL_OAUTH_REQUIRED_SCOPE', 'mcp:tools').strip()
    if not scope or len(scope)>128 or any(c.isspace() for c in scope):
        raise ValueError('Invalid scope')
    return OAuthConfig(*values, scope)

def metadata_url(config: OAuthConfig) -> str:
    p = urlsplit(config.resource)
    return f'{p.scheme}://{p.netloc}/.well-known/oauth-protected-resource{p.path}'

def resource_metadata(config: OAuthConfig) -> dict:
    return {'resource':config.resource,'authorization_servers':[config.issuer],
            'bearer_methods_supported':['header'],'scopes_supported':[config.scope]}

def _credential_bytes(value: object) -> bytes | None:
    """RFC 7235 header bytes for a credential, or None when unrepresentable.

    HTTP header values are latin-1 encoded on the wire. ``hmac.compare_digest``
    accepts bytes of any content, but raises ``TypeError`` when either ``str``
    operand contains a non-ASCII character, so both sides are encoded before
    the comparison. Anything that is not a string, or that cannot be encoded as
    a header value, is malformed: it can never appear on the wire and must never
    match a secret.
    """
    if not isinstance(value, str):
        return None
    try:
        return value.encode('latin-1')
    except UnicodeEncodeError:
        return None


def _same_bearer(header: str, secret: str) -> bool:
    """Constant-time Bearer equality that never raises on hostile input."""
    actual = _credential_bytes(header)
    expected = _credential_bytes('Bearer ' + secret)
    return (actual is not None and expected is not None
            and hmac.compare_digest(actual, expected))


def authorized(header: str) -> bool:
    """Whether an Authorization header value authenticates this resource.

    A non-ASCII or otherwise unencodable credential is a malformed header value
    per RFC 7235: it is rejected cleanly (fail closed, HTTP 401) instead of
    raising inside the request path.
    """
    if not isinstance(header, str):
        return False
    secret = os.environ.get('SCITOOL_MCP_BEARER_TOKEN', '')
    if secret and _same_bearer(header, secret):
        return True
    if not header.startswith('Bearer '):
        return False
    try:
        config = settings()
        if config is None:
            return False
        import jwt
        client = _JWKS_CACHE.get(config.jwks_uri)
        if client is None:
            client = jwt.PyJWKClient(config.jwks_uri, cache_keys=True, lifespan=300)
            _JWKS_CACHE[config.jwks_uri] = client
        access_token = header[7:]
        key = client.get_signing_key_from_jwt(access_token)
        claims = jwt.decode(access_token, key.key, algorithms=['RS256'],
            audience=config.resource, issuer=config.issuer,
            options={'require':['iss','aud','exp','sub']}, leeway=30)
        scope = claims.get('scope', '')
        if isinstance(scope, str):
            scope = scope.split()
        elif not isinstance(scope, list):
            return False
        return config.scope in scope
    except Exception:
        return False
