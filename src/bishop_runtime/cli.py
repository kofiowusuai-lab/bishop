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


def _runtime(home, config, provider=None):
    from .memory import MemoryStore
    from .runtime import Runtime
    from .tools import ToolRegistry
    selected_provider = provider if provider is not None else provider_from_config(config)
    memory = MemoryStore(home / 'memory.db')
    tools = ToolRegistry(home / 'workspace', memory, home / 'skills',
                         allow_write=config['allow_write'], allow_command=config['allow_command'])
    runtime = Runtime(home, selected_provider, tools,
                      max_steps=config['max_steps'], history_turns=config['history_turns'])
    return runtime, memory


def _offline_runtime(home, config):
    # Read/admin commands must never require live credentials or invoke the model.
    return _runtime(home, config, ScriptedProvider([]))


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
    runtime, memory = _runtime(home, config, provider)
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
    commands = p.add_subparsers(dest='command', required=True)
    commands.add_parser('init', help='initialize private local configuration; no network')
    commands.add_parser('demo', help='run deterministic offline tool/approval/audit demo')
    chat = commands.add_parser('chat', help='send one turn to the configured model, or interactive chat')
    chat.add_argument('text', nargs='?')
    chat.add_argument('--session', default='local')
    commands.add_parser('sessions', help='list local sessions')
    status = commands.add_parser('status'); status.add_argument('run')
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


def main(argv=None):
    args = parser().parse_args(argv)
    home = (args.home or Path('~/.bishop')).expanduser().resolve()
    runtime = memory = service = None
    try:
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
                _emit(runtime.run(args.session, args.text, actor=args.actor))
            else:
                print('Bishop interactive chat. /exit quits. Approval commands are run from a separate terminal.')
                while True:
                    try:
                        text = input('You> ')
                    except EOFError:
                        break
                    if text.strip() == '/exit':
                        break
                    if text.strip():
                        result = runtime.run(args.session, text, actor=args.actor)
                        _emit(result)
                        if result['status'] != 'completed':
                            break
        elif args.command == 'sessions':
            _emit(runtime.sessions())
        elif args.command == 'status':
            _emit(runtime.status(args.run))
        elif args.command in ('approve', 'deny'):
            _emit(getattr(runtime, args.command)(args.run, args.call, actor=args.actor))
        elif args.command == 'resume':
            _emit(runtime.resume(args.run, actor=args.actor))
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
            service = TelegramService(home, client, runtime, config['telegram']['allowed_users'])
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
    except (ValueError, RuntimeError, OSError) as exc:
        # Known errors are operator-safe; OS error text can contain paths/content.
        message = 'local operation failed' if isinstance(exc, OSError) else str(exc)
        print('Bishop: ' + message, file=sys.stderr)
        return 1
    finally:
        if service is not None:
            service.close()
        if runtime is not None:
            runtime.close()
        if memory is not None:
            memory.close()
