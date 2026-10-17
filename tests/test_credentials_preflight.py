import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bishop_runtime.cli import main
from bishop_runtime.config import init_home, load_config, provider_from_config
from bishop_runtime.profiles import PRESETS, ProfileStore


class CredentialPreflightTests(unittest.TestCase):
    def test_paid_profiles_require_key_before_client_construction(self):
        for ident in ('opencode-go', 'opencode', 'openrouter', 'anthropic', 'openai'):
            with self.subTest(provider=ident), tempfile.TemporaryDirectory() as root:
                home = Path(root); init_home(home); store = ProfileStore(home)
                preset = PRESETS[ident]
                store.save('work', preset['kind'], preset['base_url'], 'test-model', preset_id=ident)
                config = load_config(home)
                with patch('bishop_runtime.config.HTTPProvider', side_effect=AssertionError('client constructed')):
                    with self.assertRaisesRegex(ValueError, 'requires an API key.*bishop setup'):
                        provider_from_config(config, home)

    def test_saved_key_and_local_keyless_provider_still_work(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root); init_home(home); store = ProfileStore(home)
            store.save('go', 'compatible', PRESETS['opencode-go']['base_url'], 'm', api_key='synthetic', preset_id='opencode-go')
            self.assertEqual(provider_from_config(load_config(home), home).api_key, 'synthetic')
            store.save('local', 'compatible', PRESETS['ollama']['base_url'], 'm', preset_id='ollama')
            self.assertIsNone(provider_from_config(load_config(home), home).api_key)

    def test_doctor_explains_missing_key_without_exposing_credentials(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root); init_home(home)
            ProfileStore(home).save('go', 'compatible', PRESETS['opencode-go']['base_url'], 'm', preset_id='opencode-go')
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(['--home', str(home), 'doctor']), 0)
            report = json.loads(out.getvalue())
            credential = next(c for c in report['checks'] if c['name'] == 'credential')
            self.assertEqual(credential['status'], 'warn')
            self.assertIn('bishop setup', credential['message'])

    def test_free_and_custom_keyless_profiles_are_not_blocked(self):
        for ident, url in [('opencode-free', PRESETS['opencode-free']['base_url']), ('custom', 'https://keyless.example/v1')]:
            with self.subTest(provider=ident), tempfile.TemporaryDirectory() as root:
                home = Path(root); init_home(home)
                ProfileStore(home).save('work', 'compatible', url, 'm', preset_id=ident)
                self.assertIsNone(provider_from_config(load_config(home), home).api_key)
