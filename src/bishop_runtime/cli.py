"""Local operator interface. Init and demo never contact a model or Telegram."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

from .config import init_home, load_config, provider_from_config
from .provider import ScriptedProvider


def _emit(value):
    print(json.dumps(value, indent=2, ensure_ascii=False))


def _runtime(home, config, provider=None, remote_progress=True):
    from .memory import MemoryStore
    from .runtime import Runtime
    from .tools import ToolRegistry
    selected_provider = provider if provider is not None else provider_from_config(config, home=home)
    memory = MemoryStore(home / 'memory.db')
    tools = ToolRegistry(home / 'workspace', memory, home / 'skills',
                         allow_write=config['allow_write'], allow_command=config['allow_command'],
                         allow_web=config['web']['enabled'], web_settings=config['web'])
    runtime = Runtime(home, selected_provider, tools,
                      max_steps=config['max_steps'], history_turns=config['history_turns'],
                      progress=None if config['monitoring']['enabled'] else False,
                      progress_heartbeat_interval=config['monitoring']['heartbeat_seconds'])
    if remote_progress:
        from .monitor_integration import configure_remote
        configure_remote(runtime, home, config)
    return runtime, memory


def _offline_runtime(home, config):
    # Read/admin commands must never require live credentials or invoke the model.
    return _runtime(home, config, ScriptedProvider([]), remote_progress=False)


def demo(home=None):
    """Exercise real persistence, read/write approval and AEK, without credentials."""
    if home is None:
        home = Path(tempfile.mkdtemp(prefix='bishop-demo-'))
    home = Path(home).expanduser().resolve()
    if home.exists() and any(home.iterdir()):
        raise ValueError('demo requires an empty home directory')
    init_home(home)
    (home / 'workspace' / 'brief.txt').write_text('Bishop is an independent runtime with durable approvals.\n')
    provider = ScriptedProvider([
        {'content': None, 'tool_calls': [{'id': 'read-brief', 'name': 'read_file', 'arguments': {'path': 'brief.txt'}}]},
        {'content': 'I will save a note after your approval.', 'tool_calls': [{'id': 'save-note', 'name': 'write_file', 'arguments': {'path': 'bishop-note.txt', 'content': 'Bishop owns its agent loop, tools and state.\n'}}]},
        {'content': 'Saved bishop-note.txt after operator approval.', 'tool_calls': []},
    ])
    config = load_config(home)
    runtime, memory = _runtime(home, config, provider, remote_progress=False)
    try:
        run = runtime.run('offline-demo', 'Read the brief and save a note about Bishop.')
        if run['status'] != 'awaiting_approval' or (home / 'workspace' / 'bishop-note.txt').exists():
            raise RuntimeError('offline approval verification failed')
        runtime.approve(run['id'], 'save-note')
        run = runtime.resume(run['id'])
        if run['status'] != 'completed':
            raise RuntimeError('offline completion verification failed')
        run_id = run['id']
    finally:
        runtime.close()
        memory.close()
    runtime, memory = _offline_runtime(home, config)
    try:
        persisted = runtime.status(run_id)
        if persisted['status'] != 'completed' or persisted['output'] != run['output']:
            raise RuntimeError('offline persistence verification failed')
        from agent_experience_kit.store import Store
        audit = Store(home / 'audit.db')
        try:
            pending = audit.pending_count()
        finally:
            audit.close()
        if not pending:
            raise RuntimeError('offline audit verification failed')
        return {'home': str(home), 'run_id': run_id, 'status': persisted['status'],
                'output': persisted['output'], 'approval_verified': True,
                'persistence_verified': True, 'audit_pending': pending,
                'provider': 'offline scripted demo; no live model called'}
    finally:
        runtime.close()
        memory.close()


def parser():
    p = argparse.ArgumentParser(prog='bishop', description='Bishop independent agent runtime')
    p.add_argument('--actor', default='local', help='local operator identity; privileged host recovery can specify telegram:USER_ID')
    p.add_argument('--home', type=Path, default=None, help='state directory (default ~/.bishop; demo defaults to fresh temporary directory)')
    p.add_argument('--no-color', action='store_true', help='disable terminal colors')
    commands = p.add_subparsers(dest='command')
    commands.add_parser('setup', help='add a saved provider with private key entry')
    commands.add_parser('model', help='choose a provider or model from searchable menus')
    commands.add_parser('doctor', help='check local configuration without network access')
    q = commands.add_parser('config', help='show sanitized local configuration')
    q.add_argument('config_command', nargs='?', choices=('show',), default='show')
    q = commands.add_parser('tools', help='list enabled runtime tools')
    q.add_argument('tools_command', nargs='?', choices=('list',), default='list')
    q = commands.add_parser('skills', help='list or read owner-installed skills')
    subs = q.add_subparsers(dest='skills_command')
    subs.add_parser('list')
    q = subs.add_parser('show'); q.add_argument('name')
    q = commands.add_parser('web', help='configure or diagnose independent public web research')
    subs = q.add_subparsers(dest='web_command')
    subs.add_parser('status')
    subs.add_parser('configure')
    q = subs.add_parser('search'); q.add_argument('query', nargs='+')
    q = subs.add_parser('read'); q.add_argument('url')
    q = commands.add_parser('monitor', aliases=['monitoring'], help='inspect or configure default task monitoring')
    subs = q.add_subparsers(dest='monitor_command')
    subs.add_parser('status')
    subs.add_parser('configure')
    subs.add_parser('deliveries')
    for operation in ('runs', 'events'):
        sub = subs.add_parser(operation)
        if operation == 'events': sub.add_argument('run')
        sub.add_argument('--limit', type=int, default=100)
    sub = subs.add_parser('resolve', help='explicitly reconcile an uncertain progress card')
    sub.add_argument('run')
    sub.add_argument('--channel', choices=('telegram','discord','whatsapp'), required=True)
    sub.add_argument('--destination', required=True, help='destination hash from monitor deliveries')
    sub.add_argument('--action', choices=('sent','retry'), required=True)
    sub.add_argument('--message-id')
    commands.add_parser('preview', help='show the Bishop startup screen without model calls')
    profiles = commands.add_parser('providers', help='manage multiple saved providers and keys')
    profile_commands = profiles.add_subparsers(dest='profile_command', required=True)
    profile_commands.add_parser('list')
    profile_commands.add_parser('add')
    profile_commands.add_parser('select', help='choose a saved provider interactively')
    for operation in ('use', 'remove'):
        sub = profile_commands.add_parser(operation); sub.add_argument('name')
    auth = commands.add_parser('auth', help='Bishop-owned ChatGPT account OAuth')
    auth_commands = auth.add_subparsers(dest='auth_command', required=True)
    auth_login = auth_commands.add_parser('login')
    login = commands.add_parser('login', help='log in with Bishop-owned ChatGPT OAuth')
    commands.add_parser('logout', help='clear Bishop-owned ChatGPT OAuth credentials')
    for login_parser in (auth_login, login):
        login_parser.add_argument('--model', help='model available to your ChatGPT account')
        login_parser.add_argument('--name', default='chatgpt')
        login_parser.add_argument('--no-browser', action='store_true')
    auth_commands.add_parser('status')
    auth_commands.add_parser('logout')
    commands.add_parser('init', help='initialize private local configuration; no network')
    commands.add_parser('demo', help='run deterministic offline tool/approval/audit demo')
    chat = commands.add_parser('chat', help='send one turn to the configured model, or interactive chat')
    chat.add_argument('text', nargs='?')
    chat.add_argument('--session', default='local')
    commands.add_parser('sessions', help='list local sessions')
    status = commands.add_parser('status', help='show offline readiness, or inspect a persisted run'); status.add_argument('run', nargs='?')
    for name in ('approve', 'deny'):
        q = commands.add_parser(name); q.add_argument('run'); q.add_argument('call')
    q = commands.add_parser('resume'); q.add_argument('run')
    q = commands.add_parser('reconcile', help='supply an inspected result for an ambiguous tool call')
    q.add_argument('run'); q.add_argument('call'); q.add_argument('--result-file', type=Path, required=True)
    q = commands.add_parser('review', help='attach an explicit independent QA report to audit history')
    q.add_argument('run'); q.add_argument('--report', type=Path, required=True)
    commands.add_parser('audit', help='inspect pending sanitized audit events')
    commands.add_parser('sync', help='explicitly send one bounded audit batch to configured hub')
    telegram = commands.add_parser('telegram', help='poll a separately configured Telegram bot')
    telegram.add_argument('--once', action='store_true')
    telegram.add_argument('--deliveries', action='store_true')
    telegram.add_argument('--resolve', metavar='DELIVERY')
    telegram.add_argument('--action', choices=('sent', 'retry'))
    return p


def _read_bounded(path, size=100000):
    with path.open(encoding='utf-8') as stream:
        content = stream.read(size + 1)
    if len(content) > size:
        raise ValueError('operator input file too large')
    return content



def _boot(home, config, session='local'):
    from . import __version__
    from .profiles import ProfileStore
    from .skills import SkillStore
    from .tools import ToolRegistry
    from .terminal import print_boot
    profile = ProfileStore(home).active()
    tools = ToolRegistry(home / 'workspace', None, home / 'skills',
                         allow_write=config['allow_write'], allow_command=config['allow_command'],
                         allow_web=config['web']['enabled'], web_settings=config['web'])
    print_boot({'version': __version__, 'profile': profile['name'] if profile else 'not configured',
                'provider': profile['kind'] if profile else 'local compatible',
                'model': profile['model'] if profile else (os.environ.get('BISHOP_MODEL') or config['provider']['model'] or 'choose with bishop setup'),
                'tools': [tool['function']['name'] for tool in tools.definitions()],
                'skills': [skill['name'] for skill in SkillStore(home / 'skills').list()],
                'home': str(home), 'session': session})


def main(argv=None):
    args = parser().parse_args(argv)
    home = (args.home or Path('~/.bishop')).expanduser().resolve()
    runtime = memory = service = None
    try:
        if args.no_color:
            os.environ['NO_COLOR'] = '1'
        if args.command == 'web':
            from .web_commands import execute
            value, code = execute(home, args)
            _emit(value)
            return code
        if args.command in ('monitor', 'monitoring'):
            from .monitor_commands import execute
            _emit(execute(home, args))
            return 0
        if args.command in ('doctor', 'config', 'tools', 'skills') or (args.command == 'status' and args.run is None):
            from .operator import report
            value, code = report(home, args.command, getattr(args, 'name', None) if args.command == 'skills' else None)
            _emit(value)
            return code
        if args.command in ('login', 'logout'):
            args.auth_command = args.command
            args.command = 'auth'
        if args.command in (None, 'preview', 'setup', 'model', 'providers', 'auth'):
            init_home(home)
            config = load_config(home)
            if args.command in (None, 'preview'):
                _boot(home, config)
                if args.command == 'preview':
                    return 0
                if not sys.stdin.isatty() or not sys.stdout.isatty():
                    print('Run bishop setup to add a provider, then bishop in an interactive terminal.')
                    return 0
                from .profiles import ProfileStore
                if not ProfileStore(home).active() and not (os.environ.get('BISHOP_MODEL') or config['provider']['model']):
                    from .onboarding import setup
                    if setup(home) is None:
                        return 0
                    _boot(home, config)
                runtime, memory = _runtime(home, config)
                from .shell import run_chat
                run_chat(runtime, home, config, actor=args.actor)
                return 0
            if args.command == 'model':
                from .onboarding import select_model
                select_model(home)
                return 0
            if args.command == 'setup':
                from .onboarding import setup
                setup(home)
                return 0
            if args.command == 'providers':
                from .onboarding import list_profiles, select_profile, setup
                from .profiles import ProfileStore
                if args.profile_command == 'list': list_profiles(home)
                elif args.profile_command == 'add': setup(home)
                elif args.profile_command == 'select': select_profile(home)
                else:
                    getattr(ProfileStore(home), 'select' if args.profile_command == 'use' else 'remove')(args.name)
                    print('Provider profile ' + args.profile_command + ' completed.')
                return 0
            if args.command == 'auth':
                from .oauth import ChatGPTAuth
                from .profiles import ProfileStore
                from .terminal import safe_text
                auth = ChatGPTAuth(home)
                if args.auth_command == 'status': _emit(auth.status())
                elif args.auth_command == 'logout': _emit(auth.logout())
                else:
                    auth.login(open_browser=not args.no_browser, notify=lambda message: print(safe_text(message)))
                    from .onboarding import choose_chatgpt_model
                    model = args.model or choose_chatgpt_model(auth)
                    if model is None:
                        return 0
                    ProfileStore(home).save(args.name, 'chatgpt', 'https://api.openai.com/v1', model)
                    print('ChatGPT profile saved. Run bishop to begin.')
                return 0
        if args.command == 'init':
            _emit({'config': str(init_home(home)), 'network': 'not contacted'})
            return 0
        if args.command == 'demo':
            _emit(demo(args.home))
            return 0
        config = load_config(home)
        live = args.command in ('chat', 'resume') or (args.command == 'telegram' and not (args.deliveries or args.resolve))
        runtime, memory = _runtime(home, config) if live else _offline_runtime(home, config)
        if args.command == 'chat':
            if args.text is not None:
                from .monitor_integration import terminal_watch
                with terminal_watch(runtime, config, sys.stderr, args.actor, args.session):
                    result = runtime.run(args.session, args.text, actor=args.actor)
                _emit(result)
            else:
                from .shell import run_chat
                _boot(home, config, session=args.session)
                run_chat(runtime, home, config, session=args.session, actor=args.actor)
        elif args.command == 'sessions':
            _emit(runtime.sessions())
        elif args.command == 'status':
            _emit(runtime.status(args.run))
        elif args.command in ('approve', 'deny'):
            _emit(getattr(runtime, args.command)(args.run, args.call, actor=args.actor))
        elif args.command == 'resume':
            from .monitor_integration import terminal_watch
            with terminal_watch(runtime, config, sys.stderr, args.actor):
                result = runtime.resume(args.run, actor=args.actor)
            _emit(result)
        elif args.command == 'reconcile':
            _emit(runtime.reconcile(args.run, args.call, _read_bounded(args.result_file), actor=args.actor))
        elif args.command in ('audit', 'sync', 'review'):
            from agent_experience_kit.store import Store
            from agent_experience_kit.sync import sync_once
            audit = Store(home / 'audit.db')
            try:
                if args.command == 'audit':
                    _emit({'pending': audit.pending_count(), 'events': audit.pending_events(100)})
                elif args.command == 'review':
                    run = runtime.status(args.run)
                    report = json.loads(_read_bounded(args.report))
                    _emit(audit.record_review(run.get('audit_run_id', run['id']), report))
                else:
                    token = os.environ.get(config['audit']['token_env'])
                    if not config['audit']['hub_url'] or not token:
                        raise ValueError('configure audit hub_url and audit token environment variable')
                    try:
                        result = sync_once(audit, config['audit']['hub_url'], token)
                    except Exception:
                        raise ValueError('audit sync failed; outbox preserved') from None
                    _emit(result)
            finally:
                audit.close()
        elif args.command == 'telegram':
            from .telegram import TelegramClient, TelegramService
            token = os.environ.get(config['telegram']['token_env'])
            if not token and not (args.deliveries or args.resolve):
                raise ValueError('configure Bishop Telegram token environment variable')
            client = TelegramClient(token or 'offline-admin')
            service = TelegramService(home, client, runtime, config['telegram']['allowed_users'],
                                      progress_enabled=config['monitoring']['telegram'])
            if args.deliveries:
                _emit(service.deliveries())
            elif args.resolve:
                if not args.action:
                    raise ValueError('--resolve requires --action sent or retry')
                _emit(service.resolve_delivery(args.resolve, args.action))
            elif args.once:
                _emit(service.poll_once())
            else:
                service.serve()
        return 0
    except KeyboardInterrupt:
        print('Bishop stopped; durable state preserved.', file=sys.stderr)
        return 130
    except EOFError:
        print('Bishop setup cancelled.', file=sys.stderr)
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        # Known errors are operator-safe; OS error text can contain paths/content.
        message = 'local operation failed' if isinstance(exc, OSError) else str(exc)
        from .terminal import safe_text
        print('Bishop: ' + safe_text(message), file=sys.stderr)
        return 1
    finally:
        if service is not None:
            service.close()
        if runtime is not None:
            runtime.close()
        if memory is not None:
            memory.close()
