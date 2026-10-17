import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from bishop_runtime.config import init_home, load_config, provider_from_config
from bishop_runtime.onboarding import setup, list_profiles
from bishop_runtime.profiles import ProfileStore


class OnboardingTests(unittest.TestCase):
    def test_multiple_profiles_secrets_and_selection(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root); init_home(home)
            output = io.StringIO()
            # Select via stable preset IDs in non-TTY mode.
            answers = iter(['opencode', 'zen', 'enter', 'test-model'])
            with patch('bishop_runtime.onboarding.discover_models', return_value=[{'id':'test-model','label':'Test Model','kind':'compatible','base_url':'https://opencode.ai/inference/openai/v1'}]):
                setup(home, input_fn=lambda prompt: next(answers), secret_fn=lambda prompt: 'synthetic-private-key', output=output)
            profiles = ProfileStore(home)
            self.assertEqual(profiles.active()['name'], 'opencode')
            provider = provider_from_config(load_config(home), home=home)
            self.assertEqual(provider.api_key, 'synthetic-private-key')
            answers = iter(['anthropic', 'enter', 'test-claude-model'])
            with patch('bishop_runtime.onboarding.discover_models', return_value=[{'id':'test-claude-model','label':'Test Claude','kind':'anthropic','base_url':'https://api.anthropic.com/v1'}]):
                setup(home, input_fn=lambda prompt: next(answers), secret_fn=lambda prompt: 'second-private-key', output=output)
            self.assertEqual(len(profiles.list()), 2)
            list_profiles(home, output=output)
            self.assertNotIn('synthetic-private-key', output.getvalue())
            self.assertNotIn('second-private-key', output.getvalue())
            self.assertNotIn('private-key', (home / 'config.json').read_text())
            self.assertEqual(profiles.active()['name'], 'anthropic')

    def test_cancel_leaves_no_credentials(self):
        with tempfile.TemporaryDirectory() as root:
            init_home(root)
            setup(Path(root), input_fn=lambda prompt: 'cancel', output=io.StringIO())
            self.assertFalse((Path(root) / 'credentials.json').exists())

    def test_chatgpt_setup_lists_account_models_after_login(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root:
            init_home(root)
            answers = iter(['chatgpt', 'model-one'])
            with patch('bishop_runtime.oauth.ChatGPTAuth') as auth_class:
                auth_class.return_value.status.return_value = {'signed_in': False}
                auth_class.return_value.models.return_value = [{'id': 'model-one', 'label': 'Account Model One'}]
                setup(Path(root), input_fn=lambda prompt: next(answers), output=io.StringIO())
                auth_class.return_value.login.assert_called_once()
                auth_class.return_value.models.assert_called_once()
            self.assertEqual(ProfileStore(root).active()['model'], 'model-one')

    def test_actual_terminal_arrow_navigation_keeps_rapid_keys(self):
        import os
        import pty
        import select
        import subprocess
        import sys
        import time
        master, slave = pty.openpty()
        code = "from bishop_runtime.onboarding import choose; print('SELECTED', choose('Pick', [('a','A'),('b','B'),('c','C')]))"
        process = subprocess.Popen([sys.executable, '-c', code], stdin=slave, stdout=slave, stderr=slave)
        os.close(slave)
        captured = b''
        try:
            deadline = time.monotonic() + 5
            sent = False
            while time.monotonic() < deadline:
                if select.select([master], [], [], .1)[0]:
                    try:
                        captured += os.read(master, 65536)
                    except OSError:
                        break
                if not sent and b'navigate' in captured:
                    # Let raw mode be enabled before sending a burst of arrow keys.
                    time.sleep(.05)
                    os.write(master, b'\x1b[B\x1b[B\r')
                    sent = True
                if b'SELECTED c' in captured:
                    break
            self.assertIn(b'SELECTED c', captured)
            self.assertEqual(process.wait(timeout=2), 0)
        finally:
            if process.poll() is None:
                process.kill(); process.wait()
            os.close(master)


    def test_cancel_model_picker_preserves_key_and_profile(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root); init_home(home)
            store = ProfileStore(home)
            store.save('openrouter','compatible','https://openrouter.ai/api/v1','old',api_key='old-key',preset_id='openrouter')
            before_profiles = store.path.read_bytes(); before_keys = store.secrets_path.read_bytes()
            answers=iter(['openrouter','openrouter','replace','cancel'])
            with patch('bishop_runtime.onboarding.discover_models',return_value=[{'id':'new','label':'New','kind':'compatible','base_url':'https://openrouter.ai/api/v1'}]):
                setup(home,input_fn=lambda prompt: next(answers),secret_fn=lambda prompt:'new-key',output=io.StringIO())
            self.assertEqual(store.path.read_bytes(),before_profiles)
            self.assertEqual(store.secrets_path.read_bytes(),before_keys)

    def test_catalog_failure_is_a_menu_not_manual_entry(self):
        with tempfile.TemporaryDirectory() as root:
            init_home(root)
            answers=iter(['openrouter','none','back'])
            prompts=[]
            def ask(prompt): prompts.append(prompt); return next(answers)
            with patch('bishop_runtime.onboarding.discover_models',side_effect=RuntimeError('catalog unavailable')):
                self.assertIsNone(setup(Path(root),input_fn=ask,output=io.StringIO()))
            self.assertFalse(any('Model ID' in prompt or 'Profile name' in prompt for prompt in prompts))

    def test_clear_key_commits_only_after_model_confirmation(self):
        with tempfile.TemporaryDirectory() as root:
            home=Path(root); init_home(home); store=ProfileStore(home)
            store.save('openrouter','compatible','https://openrouter.ai/api/v1','old',api_key='private',preset_id='openrouter')
            answers=iter(['openrouter','openrouter','clear','new'])
            with patch('bishop_runtime.onboarding.discover_models',return_value=[{'id':'new','label':'New','kind':'compatible','base_url':'https://openrouter.ai/api/v1'}]):
                setup(home,input_fn=lambda prompt:next(answers),output=io.StringIO())
            self.assertIsNone(store.credential('openrouter'))
            self.assertEqual(store.active()['model'],'new')

    def test_every_supported_provider_uses_model_choices(self):
        cases = [
            ('ollama', ['ollama'], 'compatible', 'http://127.0.0.1:11434/v1'),
            ('lmstudio', ['lmstudio'], 'compatible', 'http://127.0.0.1:1234/v1'),
            ('openrouter', ['openrouter','none'], 'compatible', 'https://openrouter.ai/api/v1'),
            ('openai', ['openai','none'], 'responses', 'https://api.openai.com/v1'),
            ('anthropic', ['anthropic','none'], 'anthropic', 'https://api.anthropic.com/v1'),
            ('opencode', ['opencode','zen','none'], 'responses', 'https://opencode.ai/inference/openai/v1'),
            ('opencode-go', ['opencode','go','none'], 'anthropic', 'https://opencode.ai/inference/go/anthropic/v1'),
            ('opencode-free', ['opencode','free','none'], 'compatible', 'https://opencode.ai/inference/openai/v1'),
        ]
        for provider, selections, kind, url in cases:
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {}, clear=True):
                init_home(root)
                answers=iter(selections+['listed-model']); prompts=[]
                def ask(prompt): prompts.append(prompt); return next(answers)
                with patch('bishop_runtime.onboarding.discover_models',return_value=[{'id':'listed-model','label':'Listed Model','kind':kind,'base_url':url}]) as discover:
                    profile=setup(Path(root),input_fn=ask,output=io.StringIO())
                self.assertEqual(profile['model'],'listed-model')
                self.assertEqual(profile['kind'],kind)
                self.assertEqual(profile['preset_id'],provider)
                self.assertEqual(discover.call_args.args[0],provider)
                self.assertFalse(any('Model ID' in p or 'Profile name' in p for p in prompts))

    def test_model_switch_is_also_a_picker(self):
        from bishop_runtime.onboarding import select_profile
        with tempfile.TemporaryDirectory() as root:
            init_home(root); store=ProfileStore(root)
            store.save('work','compatible','https://openrouter.ai/api/v1','old',api_key='key',preset_id='openrouter')
            answers=iter(['work','model','new'])
            with patch('bishop_runtime.onboarding.discover_models',return_value=[{'id':'new','label':'New','kind':'compatible','base_url':'https://openrouter.ai/api/v1'}]):
                profile=select_profile(Path(root),input_fn=lambda prompt:next(answers),output=io.StringIO())
            self.assertEqual(profile['model'],'new')
            self.assertEqual(store.credential('work'),'key')

    def test_custom_supported_protocols_still_choose_model(self):
        for kind in ('compatible','anthropic','responses'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as root:
                init_home(root)
                answers=iter(['custom',kind,'https://custom.example/v1','none','listed'])
                with patch('bishop_runtime.onboarding.discover_models',return_value=[{'id':'listed','label':'Listed','kind':kind,'base_url':'https://custom.example/v1'}]):
                    result=setup(Path(root),input_fn=lambda prompt:next(answers),output=io.StringIO())
                self.assertEqual(result['model'],'listed')
                self.assertEqual(result['kind'],kind)


class DirectModelPickerTests(unittest.TestCase):
    def test_active_profile_opens_catalog_without_provider_menu(self):
        from bishop_runtime.onboarding import select_model
        with tempfile.TemporaryDirectory() as root:
            store = ProfileStore(root)
            store.save('work', 'compatible', 'https://openrouter.ai/api/v1', 'old', api_key='synthetic-key', preset_id='openrouter')
            output = io.StringIO(); prompts = []
            def answer(prompt):
                prompts.append(prompt)
                return 'new'
            models = [{'id': 'new', 'label': 'New', 'kind': 'compatible', 'base_url': 'https://openrouter.ai/api/v1'}]
            with patch('bishop_runtime.onboarding.discover_models', return_value=models):
                result = select_model(Path(root), input_fn=answer, output=output)
            self.assertEqual(result['model'], 'new')
            self.assertNotIn('Select saved provider', output.getvalue())
            self.assertNotIn('Provider action', output.getvalue())
            self.assertIn('Select model', output.getvalue())
            self.assertEqual(len(prompts), 1)
            self.assertEqual(store.credential('work'), 'synthetic-key')

    def test_direct_cancel_preserves_profile(self):
        from bishop_runtime.onboarding import select_model
        with tempfile.TemporaryDirectory() as root:
            store = ProfileStore(root)
            store.save('work', 'compatible', 'https://openrouter.ai/api/v1', 'old', preset_id='openrouter')
            with patch('bishop_runtime.onboarding._pick_model', return_value=None):
                self.assertIsNone(select_model(Path(root), output=io.StringIO()))
            self.assertEqual(store.active()['model'], 'old')

    def test_direct_chatgpt_catalog_uses_profile_home(self):
        from bishop_runtime.onboarding import select_model
        with tempfile.TemporaryDirectory() as root:
            store = ProfileStore(root)
            store.save('account', 'chatgpt', 'https://api.openai.com/v1', 'old', preset_id='chatgpt')
            with patch('bishop_runtime.oauth.ChatGPTAuth') as auth:
                auth.return_value.models.return_value = [{'id': 'new', 'label': 'New'}]
                result = select_model(Path(root), input_fn=lambda prompt: 'new', output=io.StringIO())
                auth.assert_called_once_with(Path(root))
            self.assertEqual(result['model'], 'new')
