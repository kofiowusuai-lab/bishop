import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class CLITests(unittest.TestCase):
    def command(self, home, *args):
        env = dict(os.environ)
        env.pop('BISHOP_MODEL', None)
        return subprocess.run([sys.executable, '-m', 'bishop_runtime', '--home', str(home), *args], capture_output=True, text=True, env=env, timeout=20)

    def test_offline_demo_approval_persistence_and_audit(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root) / 'demo'
            result = self.command(home, 'demo')
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report['status'], 'completed')
            self.assertTrue(report['approval_verified'])
            self.assertTrue(report['persistence_verified'])
            self.assertGreater(report['audit_pending'], 0)
            self.assertTrue((home / 'workspace' / 'bishop-note.txt').exists())
            status = self.command(home, 'status', report['run_id'])
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertEqual(json.loads(status.stdout)['status'], 'completed')
            second = self.command(home, 'demo')
            self.assertNotEqual(second.returncode, 0)

    def test_init_help_and_unconfigured_chat(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertEqual(self.command(home, 'init').returncode, 0)
            result = self.command(home, 'chat', 'hello')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('explicit model', result.stderr)
            result = self.command(home, '--help')
            self.assertEqual(result.returncode, 0)
            self.assertIn('telegram', result.stdout)

    def test_default_launch_explains_setup_and_preview(self):
        with tempfile.TemporaryDirectory() as home:
            result = self.command(home)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('BISHOP', result.stdout)
            self.assertIn('setup', result.stdout)
            result = self.command(home, 'preview')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Available tools', result.stdout)

    def test_profile_commands_no_credentials_printed(self):
        from bishop_runtime.profiles import ProfileStore
        with tempfile.TemporaryDirectory() as home:
            self.command(home, 'init')
            ProfileStore(home).save('test', 'compatible', 'http://localhost:11434/v1', 'fake-model', api_key='private-synthetic')
            result = self.command(home, 'providers', 'list')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('fake-model', result.stdout)
            self.assertNotIn('private-synthetic', result.stdout)
            result = self.command(home, 'auth', 'status')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('private-synthetic', result.stdout)
