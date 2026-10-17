"""Local provider menu and private key entry; no test inference is performed."""
import getpass
import sys
from .profiles import PRESETS, ProfileStore
from .terminal import safe_text


def choose(title, options, input_fn=None, output=None):
    """Arrow navigation on POSIX terminals, numbered/ID selection elsewhere."""
    output = output or sys.stdout
    if input_fn is None and sys.stdin.isatty() and output.isatty():
        import os
        import select
        import termios
        import tty
        fd = sys.stdin.fileno()
        before = termios.tcgetattr(fd)
        selected = 0
        def draw():
            print(safe_text(title), file=output)
            print('  ↑↓ navigate · Enter select · Esc cancel', file=output)
            for index, (_, label) in enumerate(options):
                print(('  › ' if index == selected else '    ') + safe_text(label), file=output)
            output.flush()
        draw()
        try:
            tty.setraw(fd, when=termios.TCSANOW)
            while True:
                key = os.read(fd, 1)
                if key in (b'\r', b'\n', b' '):
                    return options[selected][0]
                if key in (b'\x03', b'\x04'):
                    return None
                if key == b'\x1b':
                    if not select.select([fd], [], [], .1)[0]:
                        return None
                    tail = os.read(fd, 2)
                    if tail == b'[A': selected = (selected - 1) % len(options)
                    elif tail == b'[B': selected = (selected + 1) % len(options)
                    else: continue
                elif key in (b'j', b'k'):
                    selected = (selected + (1 if key == b'j' else -1)) % len(options)
                else:
                    continue
                # Restore cooked output for clean newlines while redrawing menu.
                termios.tcsetattr(fd, termios.TCSADRAIN, before)
                output.write(f'\x1b[{len(options) + 2}A\r\x1b[J')
                draw()
                tty.setraw(fd, when=termios.TCSANOW)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, before)
            print(file=output)
    input_fn = input_fn or input
    print(safe_text(title), file=output)
    for index, (ident, label) in enumerate(options, 1):
        print(f'  {index}. {safe_text(label)} [{ident}]', file=output)
    answer = input_fn('Provider number or ID (Enter cancels) › ').strip()
    if not answer or answer.lower() in ('cancel', 'q', 'exit'):
        return None
    if answer.isdigit() and 1 <= int(answer) <= len(options):
        return options[int(answer) - 1][0]
    if answer in {ident for ident, _ in options}:
        return answer
    raise ValueError('choose a listed provider number or ID')


def setup(home, input_fn=None, secret_fn=None, output=None):
    output = output or sys.stdout
    entries = [(ident, preset['label']) for ident, preset in PRESETS.items()]
    entries.append(('chatgpt', 'Continue with ChatGPT (OAuth · your plan)'))
    chosen = choose('Select provider', entries, input_fn=input_fn, output=output)
    if chosen is None:
        return None
    ask = input_fn or input
    secret_fn = secret_fn or getpass.getpass
    name = ask(f'Profile name [{chosen}] › ').strip() or chosen
    store = ProfileStore(home)
    if chosen == 'chatgpt':
        from .oauth import ChatGPTAuth
        auth = ChatGPTAuth(home)
        auth.login(notify=lambda message: print(safe_text(message), file=output))
        model = choose_chatgpt_model(auth, input_fn=input_fn, output=output)
        if model is None:
            return None
        profile = store.save(name, 'chatgpt', 'https://api.openai.com/v1', model)
    else:
        model = ask('Model ID (explicit, from your provider) › ').strip()
        if not model:
            raise ValueError('configure an explicit model')
        preset = PRESETS[chosen]
        base_url = preset['base_url'] or ask('Base URL (including /v1 if required) › ').strip()
        key = None
        if chosen not in ('ollama', 'lmstudio'):
            if secret_fn is getpass.getpass and not sys.stdin.isatty():
                raise ValueError('private key entry requires a terminal; use the provider environment variable instead')
            key = secret_fn('API key (hidden; Enter uses environment or existing saved key) › ').strip() or None
        profile = store.save(name, preset['kind'], base_url, model, api_key=key, api_key_env=preset['api_key_env'])
    print('Saved and selected ' + safe_text(profile['name']) + '. No model request was made.', file=output)
    return profile


def list_profiles(home, output=None):
    output = output or sys.stdout
    profiles = ProfileStore(home).list()
    if not profiles:
        print('No saved profiles. Run bishop setup to add one.', file=output)
    for profile in profiles:
        label = f"{'›' if profile['selected'] else ' '} {profile['name']} · {profile['kind']} · {profile['model']} · auth: {profile['auth']}"
        print(safe_text(label), file=output)
    return profiles


def select_profile(home, input_fn=None, output=None):
    store = ProfileStore(home)
    profiles = store.list()
    if not profiles:
        return setup(home, input_fn=input_fn, output=output)
    choices = [(p['name'], f"{p['name']} · {p['model']}" + (' · active' if p['selected'] else '')) for p in profiles]
    selected = choose('Select saved provider', choices, input_fn=input_fn, output=output)
    return store.select(selected) if selected else None


def choose_chatgpt_model(auth, input_fn=None, output=None):
    models = auth.models()
    if not models:
        raise ValueError('no visible ChatGPT models are available for this account')
    return choose('Select ChatGPT model', [(item['id'], item['label']) for item in models], input_fn=input_fn, output=output)
