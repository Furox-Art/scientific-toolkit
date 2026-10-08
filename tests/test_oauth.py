"""OAuth token authorization tests with a local RSA signing key, no IdP traffic."""
import json
import os
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from scientific_toolkit_mcp import oauth
from scientific_toolkit_mcp.http_server import Handler

ENV={
  'SCITOOL_MCP_BEARER_TOKEN':'test-only-secret',
  'SCITOOL_OAUTH_ISSUER':'https://idp.example/tenant',
  'SCITOOL_OAUTH_JWKS_URI':'https://idp.example/jwks',
  'SCITOOL_OAUTH_RESOURCE_URI':'https://scientific-toolkit.onrender.com/mcp',
  'SCITOOL_OAUTH_REQUIRED_SCOPE':'mcp:tools',
}

class OAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        cls.public=type('Key',(),{'key':cls.key.public_key()})()

    def setUp(self):
        config=patch.dict(os.environ,ENV,clear=True)
        config.start()
        self.addCleanup(config.stop)
        verify=patch('jwt.PyJWKClient.get_signing_key_from_jwt',return_value=self.public)
        verify.start()
        self.addCleanup(verify.stop)
        oauth._JWKS_CACHE.clear()

    def token(self,**updates):
        claims={'iss':ENV['SCITOOL_OAUTH_ISSUER'],'aud':ENV['SCITOOL_OAUTH_RESOURCE_URI'],
                'sub':'user','exp':int(time.time())+600,'scope':'mcp:tools'}
        claims.update(updates)
        return 'Bearer '+jwt.encode(claims,self.key,algorithm='RS256',headers={'kid':'test'})

    def test_valid(self):
        self.assertTrue(oauth.authorized(self.token()))
    def test_original_secret(self):
        self.assertTrue(oauth.authorized('Bearer test-only-secret'))
    def test_wrong_issuer(self):
        self.assertFalse(oauth.authorized(self.token(iss='https://attacker.example')))
    def test_wrong_audience(self):
        self.assertFalse(oauth.authorized(self.token(aud='https://attacker.example/mcp')))
    def test_wrong_scope(self):
        self.assertFalse(oauth.authorized(self.token(scope='wrong:scope')))
    def test_expired(self):
        self.assertFalse(oauth.authorized(self.token(exp=int(time.time())-120)))
    def test_no_subject(self):
        self.assertFalse(oauth.authorized(self.token(sub=None)))
    def test_forged_signature(self):
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        token=jwt.encode({'iss':ENV['SCITOOL_OAUTH_ISSUER'],'aud':ENV['SCITOOL_OAUTH_RESOURCE_URI'],
                          'sub':'user','exp':int(time.time())+100,'scope':'mcp:tools'},
                         key,algorithm='RS256',headers={'kid':'test'})
        self.assertFalse(oauth.authorized('Bearer '+token))
    def test_disabled_by_default(self):
        with patch.dict(os.environ,{'SCITOOL_MCP_BEARER_TOKEN':'test-only-secret'},clear=True):
            self.assertIsNone(oauth.settings())
            self.assertFalse(oauth.authorized(self.token()))
    def test_partial_config(self):
        with patch.dict(os.environ,{'SCITOOL_OAUTH_JWKS_URI':''}):
            with self.assertRaises(ValueError):
                oauth.settings()
    def test_unsafe_jwks(self):
        with patch.dict(os.environ,{'SCITOOL_OAUTH_JWKS_URI':'http://idp.example/jwks'}):
            with self.assertRaises(ValueError):
                oauth.settings()
    def test_discovery_url(self):
        cfg=oauth.settings()
        self.assertEqual(oauth.metadata_url(cfg),
           'https://scientific-toolkit.onrender.com/.well-known/oauth-protected-resource/mcp')
        self.assertEqual(oauth.resource_metadata(cfg)['authorization_servers'],
                         [ENV['SCITOOL_OAUTH_ISSUER']])
    def test_http_discovery(self):
        s=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        t=threading.Thread(target=s.serve_forever,daemon=True)
        t.start()
        try:
            base=f'http://127.0.0.1:{s.server_port}'
            with urlopen(base+'/.well-known/oauth-protected-resource/mcp',timeout=3) as r:
                metadata=json.load(r)
            self.assertEqual(metadata['resource'],ENV['SCITOOL_OAUTH_RESOURCE_URI'])
            req=Request(base+'/mcp',
                data=b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
                method='POST',headers={'Content-Type':'application/json',
                'Accept':'application/json, text/event-stream'})
            with self.assertRaises(HTTPError) as err:
                urlopen(req,timeout=3)
            self.assertEqual(err.exception.code,401)
            self.assertIn('resource_metadata=',err.exception.headers['WWW-Authenticate'])
        finally:
            s.shutdown()
            s.server_close()
            t.join(timeout=3)
