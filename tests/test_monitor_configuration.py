import json
from pathlib import Path
import tempfile
import unittest
from bishop_runtime.config import init_home, load_config


class MonitorConfigurationTests(unittest.TestCase):
    def test_existing_home_gets_default_monitoring_without_rewrite(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root); init_home(home)
            value = json.loads((home / 'config.json').read_text()); value.pop('monitoring', None)
            (home / 'config.json').write_text(json.dumps(value)); before = (home / 'config.json').read_bytes()
            config = load_config(home)
            self.assertTrue(config['monitoring']['enabled'])
            self.assertTrue(config['monitoring']['terminal'])
            self.assertTrue(config['monitoring']['telegram'])
            self.assertFalse(config['monitoring']['discord'])
            self.assertFalse(config['monitoring']['whatsapp'])
            self.assertEqual(before, (home / 'config.json').read_bytes())

    def test_invalid_monitoring_fields_rejected(self):
        for field, value in [('enabled', 'yes'), ('heartbeat_seconds', 0), ('discord_webhook_env', 'RAW-SECRET-URL')]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as root:
                home = Path(root); init_home(home)
                config = json.loads((home / 'config.json').read_text())
                config.setdefault('monitoring', {})[field] = value
                (home / 'config.json').write_text(json.dumps(config))
                with self.assertRaises(ValueError): load_config(home)
