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
