import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bishop_runtime.profiles import ProfileStore

class ProfileTests(unittest.TestCase):
    def test_multiple_private_profiles_and_environment_override(self):
        with tempfile.TemporaryDirectory() as d:
            s = ProfileStore(d)
            s.save('claude', 'anthropic', 'https://api.anthropic.com/v1', 'chosen', api_key='private-test-key', api_key_env='BISHOP_TEST_KEY')
            s.save('zen', 'compatible', 'https://opencode.ai/zen/v1', 'chosen2', api_key='other-key')
            self.assertEqual(s.active()['name'], 'zen')
            s.select('claude')
            self.assertEqual(s.credential('claude'), 'private-test-key')
            with patch.dict(os.environ, {'BISHOP_TEST_KEY': 'override'}):
                self.assertEqual(s.credential('claude'), 'override')
            self.assertNotIn('private-test-key', json.dumps(s.list()))
            self.assertNotIn('private-test-key', Path(d, 'profiles.json').read_text())
            self.assertEqual(Path(d, 'credentials.json').stat().st_mode & 0o777, 0o600)
            s.remove('claude')
            self.assertIsNone(s.active())
            self.assertNotIn('private-test-key', Path(d, 'credentials.json').read_text())

    def test_validation_and_failed_save_preserves_state(self):
        with tempfile.TemporaryDirectory() as d:
            s = ProfileStore(d)
            for name, kind, url in [('../oops', 'compatible', 'https://x.test/v1'), ('a', 'invalid', 'https://x.test'), ('a', 'compatible', 'http://remote.test'), ('a','compatible','https://user:secret@x.test')]:
                with self.assertRaises(ValueError):
                    s.save(name, kind, url, 'model')
            self.assertEqual(s.list(), [])
            with self.assertRaises(ValueError):
                s.select('missing')

    def test_update_preserves_saved_key_and_other_instances_see_selection(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = ProfileStore(d), ProfileStore(d)
            a.save('one', 'compatible', 'http://localhost:1234/v1', 'first', api_key='retained')
            a.save('two', 'anthropic', 'https://api.anthropic.com/v1', 'second', select=False)
            self.assertEqual(b.active()['name'], 'one')
            b.select('two')
            self.assertEqual(a.active()['name'], 'two')
            a.save('one', 'compatible', 'http://localhost:1234/v1', 'changed', select=False)
            self.assertEqual(a.credential('one'), 'retained')
            self.assertEqual(a.get('one')['model'], 'changed')

    def test_secret_file_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d, 'target'); target.write_text('{}')
            Path(d, 'credentials.json').symlink_to(target)
            with self.assertRaises(ValueError):
                ProfileStore(d).save('x', 'compatible', 'https://example.com/v1', 'm', api_key='secret')
            self.assertEqual(target.read_text(), '{}')

    def test_endpoint_or_kind_change_clears_credential(self):
        with tempfile.TemporaryDirectory() as d:
            s = ProfileStore(d)
            s.save('a','compatible','https://first.example/v1','m',api_key='first')
            s.save('a','compatible','https://second.example/v1','m')
            self.assertIsNone(s.credential('a'))
            self.assertNotIn('first',Path(d,'credentials.json').read_text())
            s.save('a','compatible','https://second.example/v1','m',api_key='second')
            s.save('a','anthropic','https://second.example/v1','m')
            self.assertIsNone(s.credential('a'))

    def test_crash_after_secret_write_cannot_attach_new_key_to_old_endpoint(self):
        with tempfile.TemporaryDirectory() as d:
            s = ProfileStore(d)
            s.save('a','compatible','https://first.example/v1','m',api_key='first-key')
            write = s._write
            def crash(path,value):
                if path == s.path: raise OSError('simulated crash')
                write(path,value)
            with patch.object(s,'_write',side_effect=crash):
                with self.assertRaises(OSError):
                    s.save('a','compatible','https://second.example/v1','m',api_key='second-key')
            self.assertEqual(s.get('a')['base_url'],'https://first.example/v1')
            self.assertIsNone(s.credential('a'))
            self.assertFalse(s.get('a')['has_credential'])

    def test_chatgpt_rejects_other_endpoints_and_api_keys(self):
        with tempfile.TemporaryDirectory() as d:
            s = ProfileStore(d)
            for url,key,env in [('http://localhost:9999/v1',None,None),('https://evil.example/v1',None,None),('https://api.openai.com/v1','key',None),('https://api.openai.com/v1',None,'OPENAI_API_KEY')]:
                with self.assertRaises(ValueError):
                    s.save('gpt','chatgpt',url,'m',api_key=key,api_key_env=env)
            s.save('gpt','chatgpt','https://api.openai.com/v1','m')
            self.assertIsNone(s.credential('gpt'))

    def test_profile_snapshot_cannot_receive_new_destination_key(self):
        with tempfile.TemporaryDirectory() as d:
            s = ProfileStore(d)
            s.save('a','compatible','https://first.example/v1','m',api_key='first')
            old = s.active()
            s.save('a','compatible','https://second.example/v1','m',api_key='second')
            self.assertIsNone(s.credential('a',profile=old))
            self.assertEqual(s.credential('a'),'second')

    def test_staged_clear_and_preset_identity(self):
        with tempfile.TemporaryDirectory() as d:
            store = ProfileStore(d)
            store.save('router', 'compatible', 'https://openrouter.ai/api/v1', 'm', api_key='secret', preset_id='openrouter')
            self.assertEqual(store.get('router')['preset_id'], 'openrouter')
            store.save('router', 'compatible', 'https://openrouter.ai/api/v1', 'n', clear_key=True, preset_id='openrouter')
            self.assertIsNone(store.credential('router'))
            self.assertEqual(store.get('router')['model'], 'n')

    def test_api_responses_profile_works(self):
        with tempfile.TemporaryDirectory() as d:
            store = ProfileStore(d)
            store.save('gpt', 'responses', 'https://opencode.ai/inference/openai/v1', 'm', api_key='private')
            self.assertEqual(store.get('gpt')['kind'], 'responses')

    def test_stale_preset_is_removed_on_destination_change(self):
        from bishop_runtime.onboarding import _preset_for
        with tempfile.TemporaryDirectory() as d:
            store = ProfileStore(d)
            store.save('work','compatible','https://openrouter.ai/api/v1','m',api_key='old',preset_id='openrouter')
            store.save('work','compatible','https://other.example/v1','m',api_key='new')
            profile = store.get('work')
            self.assertIsNone(profile['preset_id'])
            self.assertEqual(_preset_for(profile),'custom')
            with self.assertRaises(ValueError):
                store.save('other','compatible','https://other.example/v1','m',api_key='new',preset_id='openrouter')

    def test_opencode_preset_accepts_only_its_own_plan_routes(self):
        with tempfile.TemporaryDirectory() as d:
            store = ProfileStore(d)
            store.save('go','anthropic','https://opencode.ai/inference/go/anthropic/v1','m',api_key='key',preset_id='opencode-go')
            with self.assertRaises(ValueError):
                store.save('go','compatible','https://opencode.ai/inference/openai/v1','m',preset_id='opencode-go')
