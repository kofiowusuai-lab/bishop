"""Named provider settings and private, local credentials. No implicit calls."""
import copy
import contextlib
import functools
import json
import os
import re
import tempfile
from pathlib import Path
from .provider import HTTPProvider

# Endpoint references: official Ollama, LM Studio, OpenCode Zen, OpenRouter,
# OpenAI and Anthropic API documentation. Models must be chosen explicitly.
PRESETS = {
    'ollama': {'label': 'Ollama (local)', 'kind': 'compatible', 'base_url': 'http://127.0.0.1:11434/v1', 'api_key_env': 'OLLAMA_API_KEY'},
    'lmstudio': {'label': 'LM Studio (local)', 'kind': 'compatible', 'base_url': 'http://127.0.0.1:1234/v1', 'api_key_env': 'LM_STUDIO_API_KEY'},
    'opencode': {'label': 'OpenCode Zen (chat-compatible models)', 'kind': 'compatible', 'base_url': 'https://opencode.ai/inference/openai/v1', 'api_key_env': 'OPENCODE_API_KEY'},
    'opencode-claude': {'label': 'OpenCode Claude (Messages API)', 'kind': 'anthropic', 'base_url': 'https://opencode.ai/inference/anthropic/v1', 'api_key_env': 'OPENCODE_API_KEY'},
    'openrouter': {'label': 'OpenRouter', 'kind': 'compatible', 'base_url': 'https://openrouter.ai/api/v1', 'api_key_env': 'OPENROUTER_API_KEY'},
    'openai': {'label': 'OpenAI API', 'kind': 'compatible', 'base_url': 'https://api.openai.com/v1', 'api_key_env': 'OPENAI_API_KEY'},
    'anthropic': {'label': 'Claude API', 'kind': 'anthropic', 'base_url': 'https://api.anthropic.com/v1', 'api_key_env': 'ANTHROPIC_API_KEY'},
    'custom': {'label': 'Custom compatible endpoint', 'kind': 'compatible', 'base_url': '', 'api_key_env': 'BISHOP_MODEL_API_KEY'},
}


def _name(name):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', name):
        raise ValueError('profile name must use letters, numbers, underscores or hyphens')


def _locked(method):
    @functools.wraps(method)
    def call(self, *args, **kwargs):
        with self._lock():
            return method(self, *args, **kwargs)
    return call


class ProfileStore:
    def __init__(self, home):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.home / 'profiles.json'
        self.secrets_path = self.home / 'credentials.json'

    @contextlib.contextmanager
    def _lock(self):
        import fcntl
        flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(self.home / 'profiles.lock', flags, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def _bound_secret(self, profile):
        saved = self._read(self.secrets_path, {}).get(profile['name'])
        if not isinstance(saved, dict):
            return None
        if saved.get('kind') != profile.get('kind') or saved.get('base_url') != profile.get('base_url'):
            return None
        return saved.get('api_key')

    def _read(self, path, default):
        if path.is_symlink():
            raise ValueError('profile files cannot be symlinks')
        if not path.exists():
            return copy.deepcopy(default)
        try:
            if path.stat().st_size > 1000000:
                raise ValueError()
            value = json.loads(path.read_text())
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, OSError):
            raise ValueError('invalid provider profile file') from None

    def _write(self, path, value):
        if path.is_symlink():
            raise ValueError('profile files cannot be symlinks')
        fd, temp = tempfile.mkstemp(prefix='.' + path.name, dir=self.home)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(value, stream, indent=2, allow_nan=False)
                stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
            os.chmod(temp, 0o600)
            os.replace(temp, path)
        finally:
            if os.path.exists(temp): os.unlink(temp)

    def _data(self):
        data = self._read(self.path, {'active': None, 'profiles': {}})
        if not isinstance(data.get('profiles'), dict):
            raise ValueError('invalid provider profile file')
        return data

    def _public(self, profile):
        result = {key: copy.deepcopy(profile.get(key)) for key in ('name', 'kind', 'base_url', 'model', 'api_key_env')}
        env = result.get('api_key_env')
        secret = self._bound_secret(result)
        result['auth'] = 'environment' if env and os.environ.get(env) else ('saved' if secret else ('oauth' if result['kind'] == 'chatgpt' else 'none'))
        result['has_credential'] = bool((env and os.environ.get(env)) or secret)
        return result

    def list(self):
        data = self._data()
        return [dict(self._public(p), selected=(name == data.get('active'))) for name, p in sorted(data['profiles'].items())]

    def get(self, name):
        _name(name)
        profile = self._data()['profiles'].get(name)
        if profile is None: raise ValueError('provider profile not found')
        return self._public(profile)

    @_locked
    def save(self, name, kind, base_url, model, api_key=None, api_key_env=None, select=True):
        _name(name)
        if kind not in ('compatible', 'anthropic', 'chatgpt'):
            raise ValueError('unsupported provider kind')
        if kind == 'chatgpt' and (base_url != 'https://api.openai.com/v1' or api_key is not None or api_key_env is not None):
            raise ValueError('ChatGPT uses its own OAuth credentials and the public OpenAI endpoint')
        # Reuse the transport URL/model/credential policy without making a request.
        HTTPProvider(base_url, model, api_key=api_key)
        if api_key is not None and (not api_key.strip() or len(api_key) > 16384):
            raise ValueError('invalid provider credential')
        if api_key_env is not None and (not isinstance(api_key_env, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', api_key_env)):
            raise ValueError('invalid credential environment variable')
        data = self._data()
        secrets = self._read(self.secrets_path, {})
        data['profiles'][name] = {'name':name, 'kind':kind, 'base_url':base_url.rstrip('/'), 'model':model, 'api_key_env':api_key_env}
        if api_key is not None:
            secrets[name] = {'kind':kind, 'base_url':base_url.rstrip('/'), 'api_key':api_key}
        elif not self._bound_secret(data['profiles'][name]):
            secrets.pop(name, None)
        self._write(self.secrets_path, secrets)
        if select: data['active'] = name
        self._write(self.path, data)
        return self.get(name)

    @_locked
    def select(self, name):
        self.get(name)
        data = self._data(); data['active'] = name; self._write(self.path, data)
        return self.get(name)

    def active(self):
        name = self._data().get('active')
        return self.get(name) if name else None

    @_locked
    def remove(self, name):
        self.get(name)
        data = self._data(); del data['profiles'][name]
        if data.get('active') == name: data['active'] = None
        self._write(self.path, data)
        secrets = self._read(self.secrets_path, {}); secrets.pop(name, None)
        self._write(self.secrets_path, secrets)

    def credential(self, name, profile=None):
        profile = self.get(name) if profile is None else profile
        if profile.get("name") != name: raise ValueError("profile identity mismatch")
        if profile.get("kind") == "chatgpt": return None
        env = profile.get('api_key_env')
        value = os.environ.get(env) if env else None
        if not value: value = self._bound_secret(profile)
        if value is not None and (not isinstance(value, str) or '\n' in value or '\r' in value):
            raise ValueError('invalid provider credential')
        return value
