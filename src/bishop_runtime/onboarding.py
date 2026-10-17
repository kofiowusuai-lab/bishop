"""Choice-driven provider setup. Keys are staged until a model is confirmed."""
import getpass
import os
import sys
from .profiles import PRESETS, ProfileStore, preset_matches
from .terminal import safe_text
from .menu import choose
from .catalog import discover_models


def _say(text, output):
    print(safe_text(text), file=output)


def _preset_for(profile):
    ident = profile.get('preset_id')
    if preset_matches(ident, profile['base_url'], profile['kind']):
        return ident
    if profile['kind'] == 'chatgpt':
        return 'chatgpt'
    for ident, preset in PRESETS.items():
        if preset['base_url'] and profile['base_url'].rstrip('/') == preset['base_url']:
            return ident
    if profile['base_url'].startswith('https://opencode.ai/inference/go/'):
        return 'opencode-go'
    if profile['base_url'].startswith('https://opencode.ai/inference/'):
        return 'opencode'
    return 'custom'


def _profile_name(store, chosen, input_fn, output):
    matches = [p for p in store.list() if _preset_for(p) == chosen]
    if matches:
        options = [(p['name'], f"Edit {p['name']} · {p['model']}") for p in matches]
        options.append(('__new__', 'Add another profile'))
        selected = choose('Select profile', options, input_fn=input_fn, output=output)
        if selected is None:
            return None, None
        if selected != '__new__':
            return selected, store.get(selected)
    used = {p['name'] for p in store.list()}
    name, suffix = chosen, 2
    while name in used:
        name = f'{chosen}-{suffix}'; suffix += 1
    return name, None


def _credentials(existing, preset, store, input_fn, secret_fn, output):
    env = existing.get('api_key_env') if existing else preset.get('api_key_env')
    from_env = os.environ.get(env) if env else None
    saved = store.credential(existing['name'], profile=existing) if existing and not from_env else None
    current = from_env or saved
    if current:
        _say('Credential: configured' + (f' through {env}' if from_env else ' in private storage'), output)
        options = [('keep', 'Keep current key'), ('replace', 'Replace key'), ('clear', 'Clear saved key'), ('cancel', 'Back')]
    else:
        options = [('enter', 'Enter API key privately'), ('environment', 'Use provider environment variable'), ('none', 'Continue without a key'), ('cancel', 'Back')]
    action = choose('API key', options, input_fn=input_fn, output=output)
    if action is None or action == 'cancel':
        return None
    if action in ('replace', 'enter'):
        if secret_fn is None and not sys.stdin.isatty():
            raise ValueError('private key entry requires a terminal')
        key = (secret_fn or getpass.getpass)('API key (hidden) › ').strip()
        if not key:
            raise ValueError('empty API key; choose Back or Continue without a key instead')
        # An explicit replacement selects the entered secret, even if an old env override exists.
        return {'save_key': key, 'catalog_key': key, 'env': None, 'clear': False}
    if action == 'clear':
        if from_env:
            _say(f'Only the saved key will be cleared; {env} still supplies a key.', output)
        return {'save_key': None, 'catalog_key': from_env, 'env': env, 'clear': True}
    if action in ('none', 'environment'):
        key_env = preset.get('api_key_env') if action == 'environment' else None
        return {'save_key': None, 'catalog_key': os.environ.get(key_env) if key_env else None, 'env': key_env, 'clear': action == 'none'}
    return {'save_key': saved, 'catalog_key': current, 'env': env, 'clear': False}


def _pick_model(chosen, preset, key, existing, input_fn, output):
    for _ in range(3):
        _say('Loading available models…', output)
        try:
            models = discover_models(chosen, preset['base_url'], kind=preset['kind'], api_key=key)
            if not models:
                raise RuntimeError('no compatible models in the catalog')
        except (ValueError, RuntimeError, OSError):
            _say('The model catalog is unavailable or has no compatible models.', output)
            options = [('retry', 'Retry catalog'), ('back', 'Back / cancel')]
            if existing:
                options.insert(0, ('keep', f"Keep current model · {existing['model']} (not revalidated)"))
            action = choose('Model catalog', options, input_fn=input_fn, output=output)
            if action == 'retry':
                continue
            return dict(id=existing['model'], label=existing['model'], kind=existing['kind'], base_url=existing['base_url']) if action == 'keep' else None
        options = [(m['id'], f"{m['label']} · {m['id']}" + (' · currently in use' if existing and existing['model'] == m['id'] else '')) for m in models]
        if existing and existing['model'] not in {m['id'] for m in models}:
            options.insert(0, ('__keep__', f"Keep current · {existing['model']} (not in catalog)"))
        selected = choose('Select model', options, input_fn=input_fn, output=output, current=existing['model'] if existing else None)
        if selected == '__keep__':
            return dict(id=existing['model'], label=existing['model'], kind=existing['kind'], base_url=existing['base_url'])
        return next((m for m in models if m['id'] == selected), None)
    _say('Catalog retry limit reached; setup cancelled without changing your profile.', output)
    return None


def setup(home, input_fn=None, secret_fn=None, output=None):
    output = output or sys.stdout
    entries = []
    for ident, preset in PRESETS.items():
        if ident.startswith('opencode'):
            if ident == 'opencode': entries.append(('opencode', 'OpenCode · Zen / Go / Free'))
            continue
        entries.append((ident, preset['label']))
    entries.append(('chatgpt', 'Continue with ChatGPT (OAuth · your plan)'))
    chosen = choose('Select provider', entries, input_fn=input_fn, output=output)
    if chosen is None:
        return None
    if chosen == 'opencode':
        plan = choose('Select OpenCode plan', [('zen', 'OpenCode Zen'), ('go', 'OpenCode Go'), ('free', 'OpenCode Free')], input_fn=input_fn, output=output)
        if plan is None: return None
        chosen = {'zen': 'opencode', 'go': 'opencode-go', 'free': 'opencode-free'}[plan]
    store = ProfileStore(home)
    name, existing = _profile_name(store, chosen, input_fn, output)
    if name is None:
        return None
    if chosen == 'chatgpt':
        from .oauth import ChatGPTAuth
        auth = ChatGPTAuth(home)
        if auth.status()['signed_in']:
            action = choose('ChatGPT account', [('keep', 'Keep signed-in account'), ('login', 'Sign in again'), ('cancel', 'Back')], input_fn=input_fn, output=output)
            if action is None or action == 'cancel': return None
        else: action = 'login'
        if action == 'login': auth.login(notify=lambda message: _say(message, output))
        model = choose_chatgpt_model(auth, input_fn=input_fn, output=output)
        if model is None: return None
        profile = store.save(name, 'chatgpt', 'https://api.openai.com/v1', model, preset_id='chatgpt')
    else:
        preset = dict(PRESETS[chosen])
        if chosen == 'custom':
            if existing: preset.update(base_url=existing['base_url'], kind=existing['kind'])
            else:
                protocol = choose('Custom endpoint protocol', [('compatible', 'Chat completions'), ('anthropic', 'Anthropic Messages'), ('responses', 'Responses API')], input_fn=input_fn, output=output)
                if protocol is None: return None
                preset['kind'] = protocol
                preset['base_url'] = (input_fn or input)('Custom endpoint base URL › ').strip()
        if chosen in ('ollama', 'lmstudio'):
            keys = {'save_key': None, 'catalog_key': None, 'env': preset.get('api_key_env'), 'clear': False}
        else:
            keys = _credentials(existing, preset, store, input_fn, secret_fn, output)
            if keys is None: return None
        model = _pick_model(chosen, preset, keys['catalog_key'], existing, input_fn, output)
        if model is None: return None
        profile = store.save(name, model['kind'], model['base_url'], model['id'], api_key=keys['save_key'], api_key_env=keys['env'], clear_key=keys['clear'], preset_id=chosen)
    _say(f"Saved and selected {profile['name']} · {profile['model']}. No inference request was made.", output)
    return profile


def list_profiles(home, output=None):
    output = output or sys.stdout
    profiles = ProfileStore(home).list()
    if not profiles:
        _say('No saved profiles. Run bishop setup to add one.', output)
    for profile in profiles:
        _say(f"{'›' if profile['selected'] else ' '} {profile['name']} · {profile['kind']} · {profile['model']} · auth: {profile['auth']}", output)
    return profiles


def select_profile(home, input_fn=None, output=None):
    output = output or sys.stdout
    store = ProfileStore(home)
    profiles = store.list()
    if not profiles:
        return setup(home, input_fn=input_fn, output=output)
    choices = [(p['name'], f"{p['name']} · {p['model']}" + (' · active' if p['selected'] else '')) for p in profiles]
    selected = choose('Select saved provider', choices, input_fn=input_fn, output=output)
    if selected is None: return None
    profile = store.get(selected)
    action = choose('Provider action', [('use', 'Use saved model'), ('model', 'Choose another model'), ('back', 'Back')], input_fn=input_fn, output=output)
    if action == 'use': return store.select(selected)
    if action != 'model': return None
    ident = _preset_for(profile)
    if ident == 'chatgpt':
        from .oauth import ChatGPTAuth
        model_id = choose_chatgpt_model(ChatGPTAuth(home), input_fn=input_fn, output=output)
        return store.save(selected, 'chatgpt', profile['base_url'], model_id, preset_id=ident) if model_id else None
    preset = dict(PRESETS[ident])
    if ident == 'custom': preset.update(base_url=profile['base_url'], kind=profile['kind'])
    key = store.credential(selected, profile=profile)
    model = _pick_model(ident, preset, key, profile, input_fn, output)
    if model is None: return None
    saved_key = key if profile['auth'] == 'saved' else None
    return store.save(selected, model['kind'], model['base_url'], model['id'], api_key=saved_key, api_key_env=profile['api_key_env'], preset_id=ident)


def choose_chatgpt_model(auth, input_fn=None, output=None):
    for _ in range(3):
        try:
            models = auth.models()
            if not models: raise RuntimeError('empty catalog')
        except (ValueError, RuntimeError, OSError):
            action = choose('ChatGPT model catalog unavailable', [('retry', 'Retry'), ('back', 'Back / cancel')], input_fn=input_fn, output=output)
            if action != 'retry': return None
            continue
        return choose('Select ChatGPT model', [(item['id'], item['label']) for item in models], input_fn=input_fn, output=output)
    return None
