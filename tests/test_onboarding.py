import io
from pathlib import Path
import tempfile
import unittest
from bishop_runtime.config import init_home, load_config, provider_from_config
from bishop_runtime.onboarding import setup, list_profiles
from bishop_runtime.profiles import ProfileStore


class OnboardingTests(unittest.TestCase):
    def test_multiple_profiles_secrets_and_selection(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root); init_home(home)
            output = io.StringIO()
            # Select via stable preset IDs in non-TTY mode.
            answers = iter(['opencode', 'work', 'test-model'])
            setup(home, input_fn=lambda prompt: next(answers), secret_fn=lambda prompt: 'synthetic-private-key', output=output)
            profiles = ProfileStore(home)
            self.assertEqual(profiles.active()['name'], 'work')
            provider = provider_from_config(load_config(home), home=home)
            self.assertEqual(provider.api_key, 'synthetic-private-key')
            answers = iter(['anthropic', 'claude', 'test-claude-model'])
            setup(home, input_fn=lambda prompt: next(answers), secret_fn=lambda prompt: 'second-private-key', output=output)
            self.assertEqual(len(profiles.list()), 2)
            list_profiles(home, output=output)
            self.assertNotIn('synthetic-private-key', output.getvalue())
            self.assertNotIn('second-private-key', output.getvalue())
            self.assertNotIn('private-key', (home / 'config.json').read_text())
            self.assertEqual(profiles.active()['name'], 'claude')

    def test_cancel_leaves_no_credentials(self):
        with tempfile.TemporaryDirectory() as root:
            init_home(root)
            setup(Path(root), input_fn=lambda prompt: 'cancel', output=io.StringIO())
            self.assertFalse((Path(root) / 'credentials.json').exists())

    def test_chatgpt_setup_lists_account_models_after_login(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root:
            init_home(root)
            answers = iter(['chatgpt', 'chatgpt', 'model-one'])
            with patch('bishop_runtime.oauth.ChatGPTAuth') as auth_class:
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
