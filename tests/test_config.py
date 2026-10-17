import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bishop_runtime.config import init_home, load_config, provider_from_config


class ConfigTests(unittest.TestCase):
    def test_init_is_offline_private_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root) / 'home'
            path = init_home(home)
            config = load_config(home)
            self.assertEqual(config['provider']['base_url'], 'http://127.0.0.1:11434/v1')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertTrue((home / 'workspace').is_dir())
            with self.assertRaises(ValueError):
                provider_from_config(config)
            path.write_text('{"sentinel":true}')
            init_home(home)
            self.assertEqual(json.loads(path.read_text()), {'sentinel': True})

    def test_environment_model_and_key(self):
        with tempfile.TemporaryDirectory() as root:
            init_home(root)
            config = load_config(root)
            with patch.dict('os.environ', {'BISHOP_MODEL': 'test-model', 'BISHOP_MODEL_API_KEY': 'private'}):
                provider = provider_from_config(config)
            self.assertEqual(provider.model, 'test-model')
            self.assertEqual(provider.api_key, 'private')
            self.assertNotIn('private', (Path(root) / 'config.json').read_text())

    def test_invalid_config_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            init_home(root)
            path = Path(root) / 'config.json'
            for change in [{'max_steps': 0}, {'allow_command': 'true'}, {'telegram': {'allowed_users': [True]}}, {'api_key': 'bad'}]:
                path.write_text(json.dumps(change))
                with self.assertRaises(ValueError):
                    load_config(root)
