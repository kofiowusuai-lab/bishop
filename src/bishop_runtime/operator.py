"""Offline operator reports: no model construction, home creation or credentials."""
import copy
import json
import os
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

from .config import DEFAULTS
from .provider import validate_provider_settings
from .terminal import safe_text, _ESCAPE


def _configuration(home):
    path = home / 'config.json'
    config = copy.deepcopy(DEFAULTS)
    if not path.exists():
        return config
    try:
        if path.is_symlink() or path.stat().st_size > 65536:
            raise ValueError()
        incoming = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(incoming, dict) or set(incoming) - set(config):
            raise ValueError()
        for key, value in incoming.items():
            if isinstance(config[key], dict):
                if not isinstance(value, dict) or set(value) - set(config[key]):
                    raise ValueError()
                config[key].update(value)
            else:
                config[key] = value
        for key in ('max_steps', 'history_turns'):
            if type(config[key]) is not int or not 1 <= config[key] <= 100:
                raise ValueError()
        if any(type(config[k]) is not bool for k in ('allow_write', 'allow_command')):
            raise ValueError()
        allowed = config['telegram']['allowed_users']
        if not isinstance(allowed, list) or any(type(v) is not int or v <= 0 for v in allowed):
            raise ValueError()
        for section, key in [('provider', 'api_key_env'), ('telegram', 'token_env'), ('audit', 'token_env')]:
            value = config[section][key]
            if not isinstance(value, str) or not value.isidentifier():
                raise ValueError()
        provider = config['provider']
        if (not isinstance(provider['model'], str) or len(provider['model']) > 200
                or (provider['model'] and not provider['model'].strip())):
            raise ValueError()
        validate_provider_settings(provider['base_url'], provider['model'] or 'configuration-check',
                                   provider['timeout'], provider['max_tokens'])
        if not isinstance(config['audit']['hub_url'], str):
            raise ValueError()
    except (ValueError, TypeError, UnicodeError, OSError, OverflowError):
        raise ValueError('invalid configuration; inspect config.json locally') from None
    return config


def _origin(value):
    """Display only the origin; even URL paths can contain credentials."""
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            return 'not configured' if not value else '[redacted endpoint]'
        host = parsed.hostname
        if ':' in host:
            host = '[' + host + ']'
        return safe_text(parsed.scheme + '://' + host + (':' + str(parsed.port) if parsed.port else ''))
    except (ValueError, TypeError):
        return '[redacted endpoint]'


def _profile(home):
    if not home.is_dir():
        return None
    from .profiles import ProfileStore
    try:
        value = ProfileStore(home).active()
        if value is None:
            return None
        if not isinstance(value.get('model'), str) or value.get('kind') not in ('compatible', 'anthropic', 'responses', 'chatgpt'):
            raise ValueError()
        validate_provider_settings(value.get('base_url'), value['model'])
        if value['kind'] == 'chatgpt' and value['base_url'] != 'https://api.openai.com/v1':
            raise ValueError()
        return {'name': safe_text(value['name']), 'kind': value['kind'],
                'model': safe_text(value['model']), 'endpoint_origin': _origin(value.get('base_url')),
                'auth': value['auth']}
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError('invalid provider profile configuration') from None


def _skills(home):
    directory = home / 'skills'
    if directory.is_symlink():
        raise ValueError('skill directory cannot be a symlink')
    if not directory.is_dir():
        return []
    from .skills import SkillStore
    return SkillStore(directory).list()


def _tools(config):
    from .tools import _SCHEMAS
    return [{'name': name, 'risk': risk, 'idempotent': idempotent}
            for name, (_, _, risk, idempotent) in _SCHEMAS.items()
            if not (risk == 'write' and not config['allow_write'])
            and not (risk == 'command' and not config['allow_command'])]


def report(home, command, skill_name=None):
    home = Path(home)
    network = 'not checked (offline report)'
    initialized = (home / 'config.json').is_file()
    if command == 'doctor':
        checks = [{'name': 'home', 'status': 'pass' if initialized else 'warn',
                   'message': 'Home initialized' if initialized else 'Run bishop init or bishop setup'}]
        try:
            config = _configuration(home)
            profile = _profile(home)
            checks.append({'name': 'configuration', 'status': 'pass', 'message': 'Local configuration valid'})
            selected = bool(profile or os.environ.get('BISHOP_MODEL') or config['provider']['model'])
            checks.append({'name': 'model', 'status': 'pass' if selected else 'warn',
                           'message': 'Model configured; availability not checked' if selected else 'Choose a model with bishop model'})
        except ValueError:
            checks.append({'name': 'configuration', 'status': 'fail', 'message': 'Invalid local configuration'})
        ok = not any(item['status'] == 'fail' for item in checks)
        return {'ok': ok, 'checks': checks, 'network': network}, 0 if ok else 1
    config = _configuration(home)
    if command == 'tools':
        return {'tools': _tools(config), 'network': network}, 0
    if command == 'skills':
        if skill_name is not None:
            # Validate names even if the skill directory does not exist.
            import re
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', skill_name):
                raise ValueError('invalid skill name')
            if (home / 'skills').is_symlink():
                raise ValueError('skill directory cannot be a symlink')
            if not (home / 'skills').is_dir():
                raise ValueError('skill unavailable')
            from .skills import SkillStore
            value = SkillStore(home / 'skills').read(skill_name, 16000)
            value['content'] = ''.join(c for c in _ESCAPE.sub('', value['content'])
                                       if c in '\n\t' or unicodedata.category(c) not in ('Cc', 'Cf', 'Cs', 'Zl', 'Zp'))
            return value, 0
        return {'skills': _skills(home), 'network': network}, 0
    profile = _profile(home)
    provider = config['provider']
    if command == 'status':
        from . import __version__
        return {'version': __version__, 'initialized': initialized, 'configuration': 'valid',
                'profile': profile, 'model_configured': bool(profile or os.environ.get('BISHOP_MODEL') or provider['model']),
                'tools_enabled': len(_tools(config)), 'skills_installed': len(_skills(home)), 'network': network}, 0
    return {'initialized': initialized, 'runtime': {k: config[k] for k in ('max_steps', 'history_turns', 'allow_write', 'allow_command')},
            'provider': {'endpoint_origin': _origin(provider['base_url']), 'model': safe_text(provider['model']),
                         'api_key_env': provider['api_key_env'], 'timeout': provider['timeout'], 'max_tokens': provider['max_tokens']},
            'profile': profile, 'telegram': {'token_env': config['telegram']['token_env'], 'allowed_user_count': len(config['telegram']['allowed_users'])},
            'audit': {'endpoint_origin': _origin(config['audit']['hub_url']), 'token_env': config['audit']['token_env']},
            'network': network}, 0
