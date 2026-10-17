"""Bishop-owned OpenAI public-client OAuth; never imports other applications' tokens."""
import base64
import contextlib
import hashlib
import hmac
import http.server
import json
import os
from pathlib import Path
import secrets
import time
import urllib.parse
import urllib.error
import urllib.request
import uuid
import webbrowser
from .provider import _NoRedirect

ISSUER = 'https://auth.openai.com'
RESOURCE = 'https://api.openai.com/v1'
SCOPE = 'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'

class AuthError(RuntimeError):
    pass

class ChatGPTAuth:
    def __init__(self, home, timeout=30):
        self.directory = Path(home).expanduser() / 'auth'
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / 'chatgpt.json'
        self.timeout = timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    @contextlib.contextmanager
    def _lock(self):
        import fcntl
        fd = os.open(self.directory / 'chatgpt.lock', os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        except BlockingIOError:
            raise AuthError('another Bishop sign-in or refresh is in progress') from None
        finally:
            os.close(fd)

    def _load(self):
        if not self.path.exists():
            return {}
        try:
            if self.path.is_symlink() or self.path.stat().st_size > 1000000:
                raise ValueError()
            record = json.loads(self.path.read_text())
            if not isinstance(record, dict):
                raise ValueError()
            return record
        except (OSError, ValueError):
            raise AuthError('invalid Bishop ChatGPT credential file') from None

    def _save(self, record):
        temporary = self.directory / ('credentials-' + secrets.token_hex(8))
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'w') as handle:
                json.dump(record, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def _request(self, url, form=None):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'https' or parsed.netloc != 'auth.openai.com':
            raise AuthError('untrusted OpenAI authorization endpoint')
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        request = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/x-www-form-urlencoded'} if data else {})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(1000001)
            if len(raw) > 1000000:
                raise ValueError()
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            error.close()
            raise AuthError('ChatGPT authorization request failed; retry sign-in if necessary') from None
        except Exception:
            raise AuthError('ChatGPT authorization request failed; retry sign-in if necessary') from None

    def _metadata(self):
        metadata = self._request(ISSUER + '/.well-known/openid-configuration')
        if metadata.get('issuer') != ISSUER:
            raise AuthError('invalid OpenAI issuer')
        return metadata

    def _identity(self, token, client_id, nonce, metadata):
        try:
            import jwt
            keys = self._request(metadata['jwks_uri'])['keys']
            header = jwt.get_unverified_header(token)
            key = next(k for k in keys if k.get('kid') == header.get('kid'))
            if header.get('alg') != 'RS256':
                raise ValueError()
            identity = jwt.decode(token, jwt.PyJWK.from_dict(key).key, algorithms=['RS256'], audience=client_id, issuer=ISSUER, options={'require': ['exp', 'iss', 'aud', 'sub', 'nonce']})
            if not hmac.compare_digest(identity['nonce'], nonce) or not identity['sub']:
                raise ValueError()
            return identity
        except Exception:
            raise AuthError('ChatGPT identity verification failed') from None

    def _tokens(self, record, response):
        if not isinstance(response.get('access_token'), str) or not response['access_token'] or response.get('token_type', '').lower() != 'bearer':
            raise AuthError('invalid ChatGPT token response')
        scopes = response.get('scope', ' '.join(record.get('scopes', []))).split()
        if 'chatgpt.tokens.use.direct' not in scopes:
            raise AuthError('ChatGPT plan usage was not authorized')
        expiry = response.get('expires_in')
        if isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or not 0 < expiry <= 86400:
            raise AuthError('invalid ChatGPT token expiry')
        result = dict(record)
        result.update({k: response[k] for k in ('access_token', 'refresh_token', 'id_token') if k in response})
        result.update(scopes=scopes, expires_at=time.time() + expiry)
        return result

    def login(self, open_browser=True, notify=print):
        with self._lock():
            record = self._load()
            record.setdefault('ext_agent_host_id', 'urn:uuid:' + str(uuid.uuid4()))
            self._save(record)
            metadata = self._metadata()
            state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
            callback = {}
            class Handler(http.server.BaseHTTPRequestHandler):
                def do_GET(inner):
                    parsed = urllib.parse.urlsplit(inner.path)
                    fields = urllib.parse.parse_qs(parsed.query)
                    valid = parsed.path == '/auth/callback' and hmac.compare_digest(fields.get('state', [''])[0], state)
                    if valid:
                        callback.update({k: v[0] for k, v in fields.items() if len(v) == 1})
                    inner.send_response(200 if valid else 400)
                    inner.send_header('Content-Type', 'text/plain')
                    inner.end_headers()
                    inner.wfile.write(b'Return to Bishop in your terminal.' if valid else b'Invalid authorization callback.')
                def log_message(inner, *args):
                    pass
            class CallbackServer(http.server.HTTPServer):
                def get_request(inner):
                    connection, address = super().get_request()
                    connection.settimeout(2)
                    return connection, address
                def handle_error(inner, request, client_address):
                    pass
            with CallbackServer(('127.0.0.1', 0), Handler) as server:
                redirect = 'http://127.0.0.1:%s/auth/callback' % server.server_port
                params = dict(client_id=record.get('client_id', 'dynamic_agent_client'), ext_agent_host_id=record['ext_agent_host_id'], response_type='code', redirect_uri=redirect, scope=SCOPE, resource=RESOURCE, state=state, nonce=nonce, code_challenge_method='S256', code_challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='))
                if 'client_id' not in record:
                    params['agent_name_hint'] = 'Bishop'
                # Do not emit retained ID tokens in authorization URLs.
                url = metadata['authorization_endpoint'] + '?' + urllib.parse.urlencode(params)
                if urllib.parse.urlsplit(metadata['authorization_endpoint']).netloc != 'auth.openai.com' or not metadata['authorization_endpoint'].startswith('https://'):
                    raise AuthError('untrusted authorization endpoint')
                notify('Continue with ChatGPT: ' + url)
                if open_browser:
                    webbrowser.open(url)
                deadline = time.monotonic() + 180
                server.timeout = 1
                while not callback and time.monotonic() < deadline:
                    server.handle_request()
            if not callback or callback.get('error') or not callback.get('code'):
                raise AuthError('ChatGPT sign-in cancelled or timed out')
            client_id = callback.get('client_id', record.get('client_id'))
            if not client_id or client_id == 'dynamic_agent_client' or ('client_id' in record and client_id != record['client_id']):
                raise AuthError('invalid ChatGPT client registration')
            response = self._request(metadata['token_endpoint'], dict(grant_type='authorization_code', client_id=client_id, code=callback['code'], code_verifier=verifier, redirect_uri=redirect, resource=RESOURCE))
            identity = self._identity(response.get('id_token'), client_id, nonce, metadata)
            if record.get('subject') and identity['sub'] != record['subject']:
                raise AuthError('sign-in account does not match the saved Bishop registration')
            record.update(client_id=client_id, subject=identity['sub'], issuer=ISSUER, email=identity.get('email'))
            self._save(self._tokens(record, response))
        return self.status()

    def status(self):
        record = self._load()
        return {'signed_in': bool(record.get('access_token')), 'email': record.get('email'), 'expires_at': record.get('expires_at'), 'plan_authorized': 'chatgpt.tokens.use.direct' in record.get('scopes', [])}

    def access_token(self):
        with self._lock():
            record = self._load()
            if not record.get('access_token'):
                raise AuthError('sign in to ChatGPT in Bishop first')
            if record.get('expires_at', 0) <= time.time() + 60:
                if not record.get('refresh_token'):
                    raise AuthError('ChatGPT session expired; sign in again')
                response = self._request(self._metadata()['token_endpoint'], dict(grant_type='refresh_token', client_id=record['client_id'], refresh_token=record['refresh_token'], resource=RESOURCE))
                if not response.get('refresh_token'):
                    raise AuthError('ChatGPT refresh omitted replacement token; sign in again')
                record = self._tokens(record, response)
                self._save(record)
            return record['access_token']

    def models(self):
        """Fetch the signed-in account's visible model catalog without inference."""
        token = self.access_token()
        if not isinstance(token, str) or not token or '\n' in token or '\r' in token:
            raise AuthError('invalid ChatGPT credential')
        request = urllib.request.Request(RESOURCE + '/models', headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(1000001)
            if len(raw) > 1000000:
                raise ValueError()
            models = json.loads(raw)['models']
            if not isinstance(models, list) or len(models) > 10000:
                raise ValueError()
            result = []
            for model in models:
                if not isinstance(model, dict):
                    raise ValueError()
                if model.get('visibility') != 'list':
                    continue
                slug, label = model.get('slug'), model.get('display_name')
                if not isinstance(slug, str) or not slug.strip() or len(slug) > 200:
                    raise ValueError()
                if not isinstance(label, str) or not label.strip() or len(label) > 300:
                    raise ValueError()
                result.append({'id': slug, 'label': label})
            return result
        except urllib.error.HTTPError as error:
            error.close()
            raise AuthError('ChatGPT model catalog request failed; check sign-in and account access') from None
        except Exception:
            raise AuthError('ChatGPT model catalog request failed; check sign-in and account access') from None

    def logout(self):
        with self._lock():
            record = self._load()
            confirmed = not bool(record.get('refresh_token'))
            if record.get('refresh_token'):
                try:
                    self._request(self._metadata()['revocation_endpoint'], dict(token=record['refresh_token'], token_type_hint='refresh_token', client_id=record['client_id']))
                    confirmed = True
                except AuthError:
                    pass
            for key in ('access_token', 'refresh_token', 'id_token', 'expires_at', 'scopes'):
                record.pop(key, None)
            self._save(record)
        return {'signed_in': False, 'remote_revocation_confirmed': confirmed}
