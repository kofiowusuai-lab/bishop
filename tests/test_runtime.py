import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

try:
    from bishop_runtime.runtime import Runtime
except ImportError:
    Runtime = None


class Provider:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.messages = []
    def complete(self, messages, tools):
        self.messages.append(json.loads(json.dumps(messages)))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def answer(text='done'):
    return {'content': text, 'tool_calls': []}


def call(name='read_file', arguments=None, ident='call1'):
    return {'content': None, 'tool_calls': [{'id': ident, 'name': name, 'arguments': arguments or {'path': 'note.txt'}}]}


class Tools:
    def __init__(self):
        self.calls = []
        self.crash = None
    def definitions(self):
        return []
    def describe(self, name):
        if name not in ('read_file', 'write_file'):
            raise ValueError('unknown tool')
        return {'risk': 'read' if name == 'read_file' else 'write', 'idempotent': name == 'read_file'}
    def validate(self, name, arguments):
        self.describe(name)
        if not isinstance(arguments, dict):
            raise ValueError('invalid arguments')
        return json.loads(json.dumps(arguments))
    def invoke(self, name, arguments, scope='local'):
        self.calls.append((name, arguments, scope))
        if self.crash:
            raise self.crash
        return 'file content'


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.tools = Tools()
        self.instances = []
    def tearDown(self):
        for runtime in self.instances:
            runtime.close()
        self.temp.cleanup()
    def runtime(self, provider, **kwargs):
        self.assertIsNotNone(Runtime, 'Runtime implementation is missing')
        runtime = Runtime(self.home, provider, self.tools, **kwargs)
        self.instances.append(runtime)
        return runtime
    def test_tool_loop_persists_output_and_audit(self):
        provider = Provider(call(), answer())
        runtime = self.runtime(provider)
        run = runtime.run('chat', 'read the note')
        self.assertEqual(run['status'], 'completed')
        self.assertEqual(run['output'], 'done')
        self.assertEqual(len(self.tools.calls), 1)
        self.assertEqual(provider.messages[1][-1]['role'], 'tool')
        self.assertEqual(provider.messages[1][-1]['tool_call_id'], 'call1')
        self.assertEqual(runtime.status(run['id'])['output'], 'done')
        from agent_experience_kit.store import Store
        with Store(self.home / 'audit.db') as audit:
            self.assertTrue(audit.status(run['id'])['complete'])
    def test_write_requires_owner_approval_then_resumes_once(self):
        runtime = self.runtime(Provider(call('write_file'), answer()))
        run = runtime.run('chat', 'write')
        self.assertEqual(run['status'], 'awaiting_approval')
        self.assertEqual(self.tools.calls, [])
        with self.assertRaises(ValueError):
            runtime.approve(run['id'], 'call1', actor='other')
        runtime.approve(run['id'], 'call1')
        self.assertEqual(self.tools.calls, [])
        self.assertEqual(runtime.resume(run['id'])['status'], 'completed')
        self.assertEqual(runtime.resume(run['id'])['status'], 'completed')
        self.assertEqual(len(self.tools.calls), 1)
    def test_restart_preserves_approval_and_history(self):
        first = self.runtime(Provider(call('write_file')))
        run = first.run('chat', 'write', actor='alice')
        first.approve(run['id'], 'call1', actor='alice')
        second_provider = Provider(answer('saved'), answer('remembered'))
        second = self.runtime(second_provider)
        self.assertEqual(second.resume(run['id'], actor='alice')['output'], 'saved')
        second.run('chat', 'next', actor='alice')
        history = second_provider.messages[-1]
        self.assertEqual([m['role'] for m in history], ['system', 'user', 'assistant', 'user'])
        self.assertEqual(history[2]['content'], 'saved')
    def test_ambiguous_write_requires_reconciliation_without_reexecution(self):
        runtime = self.runtime(Provider(call('write_file'), answer()))
        run = runtime.run('chat', 'write')
        runtime.approve(run['id'], 'call1')
        self.tools.crash = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            runtime.resume(run['id'])
        self.tools.crash = None
        self.assertEqual(runtime.resume(run['id'])['status'], 'needs_reconciliation')
        self.assertEqual(len(self.tools.calls), 1)
        runtime.reconcile(run['id'], 'call1', 'operator verified file saved')
        self.assertEqual(runtime.resume(run['id'])['status'], 'completed')
        self.assertEqual(len(self.tools.calls), 1)
    def test_read_after_crash_can_resume_safely(self):
        runtime = self.runtime(Provider(call(), answer()))
        self.tools.crash = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            runtime.run('chat', 'read')
        run = runtime.active('chat')
        self.tools.crash = None
        self.assertEqual(runtime.resume(run['id'])['status'], 'completed')
        self.assertEqual(len(self.tools.calls), 2)
    def test_budget_is_durable_and_does_not_reset_on_resume(self):
        runtime = self.runtime(Provider(call()), max_steps=1)
        run = runtime.run('chat', 'read')
        self.assertEqual(run['status'], 'step_limit')
        self.assertEqual(runtime.resume(run['id'])['status'], 'step_limit')
    def test_session_excludes_pending_run_but_actors_are_separate(self):
        runtime = self.runtime(Provider(call('write_file'), answer()))
        runtime.run('chat', 'write')
        with self.assertRaises(ValueError):
            runtime.run('chat', 'another')
        self.assertEqual(runtime.run('chat', 'other actor', actor='alice')['status'], 'completed')
    def test_denial_is_supplied_to_model_and_never_invokes_tool(self):
        provider = Provider(call('write_file'), answer('denied'))
        runtime = self.runtime(provider)
        run = runtime.run('chat', 'write')
        runtime.deny(run['id'], 'call1')
        self.assertEqual(runtime.resume(run['id'])['output'], 'denied')
        self.assertEqual(self.tools.calls, [])
        self.assertIn('denied', provider.messages[-1][-1]['content'])
    def test_provider_error_is_sanitized_and_not_automatically_retried(self):
        runtime = self.runtime(Provider(RuntimeError('secret-token=xyz')))
        run = runtime.run('chat', 'hi')
        self.assertEqual(run['status'], 'failed')
        self.assertNotIn('xyz', json.dumps(run))
        self.assertEqual(runtime.resume(run['id'])['status'], 'failed')
    def test_approval_hash_tampering_blocks_side_effect(self):
        runtime = self.runtime(Provider(call('write_file'), answer()))
        run = runtime.run('chat', 'write')
        runtime.approve(run['id'], 'call1')
        db = sqlite3.connect(self.home / 'runtime.db')
        data = json.loads(db.execute('SELECT data FROM runs WHERE id=?', (run['id'],)).fetchone()[0])
        data['calls'][0]['arguments']['path'] = 'different.txt'
        db.execute('UPDATE runs SET data=? WHERE id=?', (json.dumps(data), run['id']))
        db.commit()
        db.close()
        result = runtime.resume(run['id'])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.tools.calls, [])
    def test_inflight_model_after_crash_is_not_blindly_repeated(self):
        runtime = self.runtime(Provider(KeyboardInterrupt()))
        with self.assertRaises(KeyboardInterrupt):
            runtime.run('chat', 'hi')
        run = runtime.active('chat')
        self.assertEqual(runtime.resume(run['id'])['status'], 'failed')
    def test_provider_failure_is_audited_once_even_after_resume(self):
        runtime = self.runtime(Provider(RuntimeError('private error')))
        run = runtime.run('chat', 'hi')
        status = runtime.audit.status(run['id'])
        self.assertEqual(status['steps'][0]['state'], 'failed')
        self.assertEqual(status['steps'][0]['reason'], 'provider_failed')
        runtime.resume(run['id'])
        self.assertEqual(runtime.audit.status(run['id'])['steps'][0]['attempts'], 1)

    def test_failure_audit_crash_reconciles_without_duplicate_attempt(self):
        runtime = self.runtime(Provider(RuntimeError('failed')))
        original = runtime._save
        def save(run):
            if run.get('failure_audited'):
                raise KeyboardInterrupt()
            original(run)
        runtime._save = save
        with self.assertRaises(KeyboardInterrupt):
            runtime.run('chat', 'hi')
        run_id = runtime.state.connection.execute('SELECT id FROM runs').fetchone()[0]
        runtime._save = original
        runtime.resume(run_id)
        self.assertEqual(runtime.audit.status(run_id)['steps'][0]['attempts'], 1)

    def test_surrogate_model_content_fails_before_completion(self):
        runtime = self.runtime(Provider(answer('bad\ud800text')))
        run = runtime.run('chat', 'hi')
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(run['error'], 'provider_failed')
        self.assertEqual(list((self.home / 'responses').iterdir()), [])

    def test_surrogate_input_is_rejected_without_creating_a_run(self):
        runtime = self.runtime(Provider(answer()))
        with self.assertRaises(ValueError):
            runtime.run('chat', 'bad\ud800input')
        self.assertEqual(runtime.sessions(), [])

    def test_surrogate_tool_arguments_fail_before_dispatch(self):
        runtime = self.runtime(Provider(call(arguments={'path': 'bad\ud800path'})))
        run = runtime.run('chat', 'hi')
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(self.tools.calls, [])

    def test_step_budget_failure_is_audited(self):
        runtime = self.runtime(Provider(call()), max_steps=1)
        run = runtime.run('chat', 'read')
        self.assertEqual(runtime.audit.status(run['id'])['steps'][0]['state'], 'failed')
        self.assertEqual(runtime.audit.status(run['id'])['steps'][0]['reason'], 'model_step_budget_exhausted')

    def test_second_worker_cannot_take_live_lease(self):
        second = self.runtime(Provider(answer()))
        outer = self
        class BlockingProvider:
            def complete(self, messages, tools):
                active = second.active('chat')
                with outer.assertRaises(ValueError):
                    second.resume(active['id'])
                with outer.assertRaises(ValueError):
                    second.run('chat', 'overlap')
                return answer()
        first = self.runtime(BlockingProvider())
        self.assertEqual(first.run('chat', 'start')['status'], 'completed')

    def test_expired_lease_recovers_without_replaying_ambiguous_write(self):
        runtime = self.runtime(Provider(call('write_file'), answer()))
        run = runtime.run('chat', 'write')
        runtime.approve(run['id'], 'call1')
        self.tools.crash = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            runtime.resume(run['id'])
        db = sqlite3.connect(self.home / 'runtime.db')
        db.execute("UPDATE runs SET lease_owner='dead-worker',lease_until=1 WHERE id=?", (run['id'],))
        db.commit()
        db.close()
        second = self.runtime(Provider(answer()))
        self.assertEqual(second.resume(run['id'])['status'], 'needs_reconciliation')
        self.assertEqual(len(self.tools.calls), 1)

    def test_invalid_tool_response_is_rejected_before_any_call_executes(self):
        response = call()
        response['tool_calls'].append({'id': 'call2', 'name': 'nonexistent', 'arguments': {}})
        runtime = self.runtime(Provider(response))
        self.assertEqual(runtime.run('chat', 'do things')['status'], 'failed')
        self.assertEqual(self.tools.calls, [])

    def test_audit_reconciles_after_output_saved_before_audit_completion(self):
        runtime = self.runtime(Provider(answer()))
        original = runtime._finish_audit
        runtime._finish_audit = lambda run: (_ for _ in ()).throw(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            runtime.run('chat', 'hi')
        run_id = runtime.state.connection.execute('SELECT id FROM runs').fetchone()[0]
        self.assertFalse(runtime.status(run_id)['audit_complete'])
        runtime._finish_audit = original
        self.assertTrue(runtime.resume(run_id)['audit_complete'])
        self.assertTrue(runtime.audit.status(run_id)['complete'])

    def test_audit_outbox_does_not_include_conversation_content(self):
        runtime = self.runtime(Provider(answer('private output marker')))
        runtime.run('chat', 'private input marker')
        payloads = runtime.audit.connection.execute('SELECT payload FROM outbox').fetchall()
        wire = json.dumps(payloads)
        self.assertNotIn('private output marker', wire)
        self.assertNotIn('private input marker', wire)

    def test_history_is_actor_scoped_and_limited(self):
        provider = Provider(answer('one'), answer('two'), answer('three'), answer('other'))
        runtime = self.runtime(provider, history_turns=1)
        runtime.run('chat', '1')
        runtime.run('chat', '2')
        runtime.run('chat', '3')
        self.assertEqual(len(provider.messages[-1]), 4)
        self.assertEqual(provider.messages[-1][1]['content'], '2')
        runtime.run('chat', '4', actor='other')
        self.assertEqual(len(provider.messages[-1]), 2)

if __name__ == '__main__':
    unittest.main()
