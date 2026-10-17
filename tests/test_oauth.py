import json

import tempfile
import time
import unittest
from pathlib import Path
from bishop_runtime.oauth import ChatGPTAuth, AuthError

class OAuthTests(unittest.TestCase):
    def test_status_contains_no_tokens_and_private_permissions(self):
        with tempfile.TemporaryDirectory() as home:
            auth = ChatGPTAuth(home)
            auth._save({'access_token': 'private', 'refresh_token': 'other', 'expires_at': time.time()+3600})
            self.assertTrue(auth.status()['signed_in'])
            self.assertNotIn('private', str(auth.status()))
            self.assertEqual(auth.path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(auth.access_token(), 'private')

    def test_refresh_rotates_and_persists(self):
        with tempfile.TemporaryDirectory() as home:
            auth = ChatGPTAuth(home)
            auth._save({'access_token':'old','refresh_token':'old-refresh','client_id':'own-client','expires_at':0,'scopes':['chatgpt.tokens.use.direct']})
            auth._metadata = lambda: {'token_endpoint':'https://auth.openai.com/token'}
            captured=[]
            def request(url, form):
                captured.append(form)
                return {'access_token':'new','refresh_token':'new-refresh','expires_in':3600,'token_type':'Bearer'}
            auth._request=request
            self.assertEqual(auth.access_token(), 'new')
            self.assertEqual(auth._load()['refresh_token'],'new-refresh')
            self.assertEqual(captured[0]['client_id'],'own-client')

    def test_logout_clears_tokens_even_if_remote_unavailable(self):
        with tempfile.TemporaryDirectory() as home:
            auth=ChatGPTAuth(home)
            auth._save({'access_token':'secret','refresh_token':'secret','client_id':'own','subject':'user','ext_agent_host_id':'host'})
            def fail(): raise AuthError('offline')
            auth._metadata=fail
            self.assertFalse(auth.logout()['remote_revocation_confirmed'])
            self.assertEqual(auth._load(), {'client_id':'own','subject':'user','ext_agent_host_id':'host'})

    def test_scope_and_endpoint_rejected(self):
        with tempfile.TemporaryDirectory() as home:
            auth=ChatGPTAuth(home)
            with self.assertRaises(AuthError): auth._tokens({}, {'access_token':'x','expires_in':3600,'token_type':'Bearer','scope':'openid'})
            with self.assertRaises(AuthError): auth._request('https://evil.example/token')

    def test_identity_checks_signature_audience_and_nonce(self):
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        jwk=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        jwk['kid']='test'
        with tempfile.TemporaryDirectory() as home:
            auth=ChatGPTAuth(home)
            auth._request=lambda url: {'keys':[jwk]}
            claims={'iss':'https://auth.openai.com','aud':'bishop-client','sub':'user','nonce':'expected','exp':time.time()+300}
            token=jwt.encode(claims,key,algorithm='RS256',headers={'kid':'test'})
            self.assertEqual(auth._identity(token,'bishop-client','expected',{'jwks_uri':'https://auth.openai.com/jwks'})['sub'],'user')
            with self.assertRaises(AuthError): auth._identity(token,'other-client','expected',{'jwks_uri':'https://auth.openai.com/jwks'})
            with self.assertRaises(AuthError): auth._identity(token,'bishop-client','wrong',{'jwks_uri':'https://auth.openai.com/jwks'})

    def test_login_dynamic_callback_uses_issued_client_and_pkce(self):
        import urllib.parse
        import urllib.request
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as home:
            auth=ChatGPTAuth(home)
            auth._metadata=lambda: {'authorization_endpoint':'https://auth.openai.com/api/accounts/authorize','token_endpoint':'https://auth.openai.com/token'}
            requests=[]
            auth._identity=lambda token,client,nonce,metadata: {'sub':'test-account','email':'test@example.invalid'}
            def request(url, form):
                requests.append(form)
                return {'access_token':'own-token','refresh_token':'own-refresh','id_token':'signed-token','scope':'openid chatgpt.tokens.use.direct','expires_in':3600,'token_type':'Bearer'}
            auth._request=request
            threads=[]
            def browser(url):
                import threading
                query=urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
                self.assertEqual(query['client_id'],['dynamic_agent_client'])
                self.assertEqual(query['agent_name_hint'],['Bishop'])
                callback=query['redirect_uri'][0]+'?'+urllib.parse.urlencode({'state':query['state'][0],'code':'fresh-code','client_id':'bishop-issued-client'})
                def send():
                    with urllib.request.urlopen(callback,timeout=5) as response: response.read()
                thread=threading.Thread(target=send)
                thread.start()
                threads.append(thread)
                return True
            with patch('bishop_runtime.oauth.webbrowser.open',browser):
                result=auth.login(notify=lambda message: None)
            for thread in threads: thread.join(5)
            self.assertTrue(result['signed_in'])
            self.assertEqual(requests[0]['client_id'],'bishop-issued-client')
            self.assertEqual(requests[0]['code'],'fresh-code')
            self.assertGreater(len(requests[0]['code_verifier']),40)
            self.assertEqual(auth._load()['subject'],'test-account')

    def test_account_model_catalog_preserves_visible_order(self):
        import io
        with tempfile.TemporaryDirectory() as home:
            auth=ChatGPTAuth(home)
            auth.access_token=lambda: 'private-token'
            catalog={'models':[{'slug':'b','display_name':'Second','visibility':'list'}, {'slug':'hidden','display_name':'Hidden','visibility':'hidden'}, {'slug':'a','display_name':'First','visibility':'list'}]}
            class Opener:
                def open(inner, request, timeout):
                    inner.request=request
                    return io.BytesIO(json.dumps(catalog).encode())
            auth.opener=Opener()
            self.assertEqual(auth.models(),[{'id':'b','label':'Second'},{'id':'a','label':'First'}])
            self.assertEqual(auth.opener.request.full_url,'https://api.openai.com/v1/models')
            self.assertEqual(auth.opener.request.get_header('Authorization'),'Bearer private-token')

    def test_corrupted_credentials_and_catalog_are_sanitized(self):
        import io
        with tempfile.TemporaryDirectory() as home:
            auth=ChatGPTAuth(home)
            auth.path.write_text('[]')
            with self.assertRaises(AuthError): auth.status()
            auth.access_token=lambda: 'private-token'
            class Opener:
                def open(inner, request, timeout): return io.BytesIO(b'{"models": "private-token"}')
            auth.opener=Opener()
            with self.assertRaises(AuthError) as error: auth.models()
            self.assertNotIn('private-token',str(error.exception))

    def test_authorization_http_errors_close_response_and_hide_body(self):
        import io
        import urllib.error
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as home:
            auth = ChatGPTAuth(home)
            for operation in ('request', 'catalog'):
                body = io.BytesIO(b'private error body')
                failure = urllib.error.HTTPError('https://auth.openai.com/private', 401, 'private', {}, body)
                auth.opener = Mock()
                auth.opener.open.side_effect = failure
                auth.access_token = lambda: 'synthetic-private'
                with self.assertRaises(AuthError) as caught:
                    auth._request('https://auth.openai.com/token') if operation == 'request' else auth.models()
                self.assertTrue(body.closed)
                self.assertNotIn('private', str(caught.exception))
