"""Bishop configuration stores credential references, never credential values."""
import copy
import json
import os
from pathlib import Path
from .provider import HTTPProvider

DEFAULTS = {
    'provider': {'base_url': 'http://127.0.0.1:11434/v1', 'model': '',
                 'api_key_env': 'BISHOP_MODEL_API_KEY', 'timeout': 30, 'max_tokens': 1024},
    'max_steps': 12, 'history_turns': 8, 'allow_write': True, 'allow_command': False,
    'telegram': {'token_env': 'BISHOP_TELEGRAM_TOKEN', 'allowed_users': []},
    'audit': {'hub_url': '', 'token_env': 'BISHOP_AUDIT_TOKEN'},
}


def init_home(home):
    home = Path(home).expanduser().resolve()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in ('workspace', 'skills'):
        (home / name).mkdir(mode=0o700, exist_ok=True)
    path = home / 'config.json'
    try:
        with path.open('x', encoding='utf-8') as stream:
            os.chmod(path, 0o600)
            json.dump(DEFAULTS, stream, indent=2)
            stream.write('\n')
    except FileExistsError:
        pass
    return path


def load_config(home):
    path = Path(home).expanduser() / 'config.json'
    if not path.exists():
        raise ValueError('Bishop home is not initialized; run bishop init')
    if path.stat().st_size > 65536:
        raise ValueError('configuration too large')
    try:
        incoming = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError):
        raise ValueError('invalid configuration JSON') from None
    if not isinstance(incoming, dict) or set(incoming) - set(DEFAULTS):
        raise ValueError('unknown configuration fields')
    config = copy.deepcopy(DEFAULTS)
    for key, value in incoming.items():
        if isinstance(config[key], dict):
            if not isinstance(value, dict) or set(value) - set(config[key]):
                raise ValueError('unknown configuration fields')
            config[key].update(value)
        else:
            config[key] = value
    for key, maximum in [('max_steps', 100), ('history_turns', 100)]:
        if type(config[key]) is not int or not 1 <= config[key] <= maximum:
            raise ValueError('invalid runtime limit')
    for key in ('allow_write', 'allow_command'):
        if type(config[key]) is not bool:
            raise ValueError('tool flags must be booleans')
    allowed = config['telegram']['allowed_users']
    if not isinstance(allowed, list) or any(type(v) is not int or v <= 0 for v in allowed):
        raise ValueError('Telegram allowlist must contain positive numeric user IDs')
    for section, name in [('provider', 'api_key_env'), ('telegram', 'token_env'), ('audit', 'token_env')]:
        value = config[section][name]
        if not isinstance(value, str) or not value.isidentifier():
            raise ValueError('credential environment variable name is invalid')
    for section, names in [('provider', ('base_url', 'model')), ('audit', ('hub_url',))]:
        if any(not isinstance(config[section][name], str) for name in names):
            raise ValueError('configuration text field is invalid')
    # Validate transport even when no model is selected; no network is performed.
    HTTPProvider(config['provider']['base_url'], config['provider']['model'] or 'configuration-check',
                 timeout=config['provider']['timeout'], max_tokens=config['provider']['max_tokens'])
    return config


def provider_from_config(config, home=None):
    if home is not None:
        from .profiles import ProfileStore, required_api_key_provider
        store = ProfileStore(home)
        profile = store.active()
        if profile:
            model = profile['model']
            p = config['provider']
            if profile['kind'] == 'chatgpt':
                from .oauth import ChatGPTAuth
                from .responses import ResponsesProvider
                return ResponsesProvider('https://api.openai.com/v1', model, ChatGPTAuth(home).access_token,
                                         timeout=p['timeout'], max_tokens=p['max_tokens'])
            credential = store.credential(profile['name'], profile=profile)
            required = required_api_key_provider(profile)
            if required and not credential:
                raise ValueError(required + ' requires an API key. Run bishop setup, select this provider, edit its profile and enter the key privately.')
            if profile['kind'] == 'responses':
                from .responses import APIResponsesProvider
                return APIResponsesProvider(profile['base_url'], model, credential,
                                            timeout=p['timeout'], max_tokens=p['max_tokens'])
            if profile['kind'] == 'anthropic':
                from .anthropic import AnthropicProvider
                return AnthropicProvider(profile['base_url'], model, credential,
                                         timeout=p['timeout'], max_tokens=p['max_tokens'])
            return HTTPProvider(profile['base_url'], model, credential,
                                timeout=p['timeout'], max_tokens=p['max_tokens'])
    p = config['provider']
    return HTTPProvider(p['base_url'], os.environ.get('BISHOP_MODEL') or p['model'],
                        api_key=os.environ.get(p['api_key_env']), timeout=p['timeout'], max_tokens=p['max_tokens'])
