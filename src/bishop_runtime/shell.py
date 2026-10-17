"""Human terminal conversation UI over the independent Bishop runtime."""
import json
import sys
from .terminal import safe_text

HELP = '''/help                  Show commands
/status [RUN]          Inspect current or selected run
/approve [RUN] CALL     Record approval of the exact call
/deny [RUN] CALL        Reject a pending call
/resume [RUN]          Continue the run
/providers             List saved providers
/model                 Choose from the active provider model catalog
/setup                 Add another provider/key
/new SESSION           Change session
/exit                  Leave Bishop'''


def run_chat(runtime, home, config, session='local', actor='local', input_fn=None, output=None):
    menu_input = input_fn
    input_fn = input_fn or input
    output = output or sys.stdout
    def say(text):
        print('\n'.join(safe_text(line) for line in str(text).split('\n')), file=output)
    def present(run):
        if run['status'] == 'completed':
            say('\nBishop › ' + (run['output'] or '(Empty answer)') + '\n')
        else:
            say(f"Run {run['id']} · {run['status']}")
            if run.get('error'):
                say(run['error'])
                if run['error'] == 'provider_failed':
                    say('Check the selected model, key and endpoint. No automatic retry was made.')
            for call in run.get('pending', []):
                say(f"  {call['id']} · {call['name']} · {call['risk']}")
                say('  ' + json.dumps(call['arguments'], ensure_ascii=False))
    def settle(run):
        while run['status'] == 'awaiting_approval':
            pending = [call for call in run['pending'] if not call.get('approved') and call['state'] == 'pending']
            if not pending:
                break
            call = pending[0]
            say(f"\nApproval needed: {call['name']} ({call['id']})")
            say(json.dumps(call['arguments'], indent=2, ensure_ascii=False))
            answer = input_fn('[y] approve · [n] deny · [l/Enter] later › ').strip().lower()
            if answer not in ('y', 'yes', 'n', 'no'):
                present(run)
                return run
            action = runtime.approve if answer in ('y', 'yes') else runtime.deny
            action(run['id'], call['id'], actor=actor)
            say('Continuing…')
            run = runtime.resume(run['id'], actor=actor)
        present(run)
        return run

    say('Send a task. /help shows commands; /exit quits.\n')
    last = runtime.active(session, actor=actor)
    if last:
        present(last)
    while True:
        try:
            text = input_fn('You › ').strip()
        except (EOFError, StopIteration):
            break
        if not text:
            continue
        try:
            if text.startswith('/'):
                parts = text.split()
                command = parts[0]
                if command in ('/exit', '/quit'):
                    break
                if command == '/help':
                    say(HELP); continue
                if command == '/new':
                    if len(parts) != 2:
                        raise ValueError('Usage: /new SESSION')
                    session = parts[1]
                    last = runtime.active(session, actor=actor)
                    say('Session: ' + session)
                    if last: present(last)
                    continue
                if command in ('/providers', '/model', '/setup'):
                    from .onboarding import list_profiles, select_model, setup
                    from .config import provider_from_config
                    if command == '/providers':
                        list_profiles(home, output=output)
                    else:
                        (select_model if command == '/model' else setup)(home, input_fn=menu_input, output=output)
                        runtime.provider = provider_from_config(config, home=home)
                        say('Provider selection updated for the next model request.')
                    continue
                if command not in ('/status', '/approve', '/deny', '/resume'):
                    say('Unknown command. Use /help.'); continue
                if command in ('/approve', '/deny'):
                    if len(parts) == 2 and last:
                        run_id, call_id = last['id'], parts[1]
                    elif len(parts) == 3:
                        run_id, call_id = parts[1:]
                    else:
                        raise ValueError('Usage: ' + command + ' [RUN] CALL')
                    last = getattr(runtime, command[1:])(run_id, call_id, actor=actor)
                    say('Recorded. Use /resume to continue.'); continue
                if len(parts) > 2:
                    raise ValueError('Usage: ' + command + ' [RUN]')
                run_id = parts[1] if len(parts) == 2 else (last['id'] if last else None)
                if not run_id:
                    say('No run selected.'); continue
                if command == '/status':
                    last = runtime.status(run_id)
                    if last['actor'] != actor:
                        raise ValueError('run belongs to another actor')
                    present(last)
                else:
                    last = settle(runtime.resume(run_id, actor=actor))
            else:
                say('Bishop is working…')
                last = settle(runtime.run(session, text, actor=actor))
        except (ValueError, RuntimeError) as exc:
            say('Bishop: ' + str(exc))
    say('Bishop stopped. Your conversation and checkpoints are saved.')
