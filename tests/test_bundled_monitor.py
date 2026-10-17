import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from bishop_runtime.cli import main
from bishop_runtime.skills import SkillStore


class BundledMonitorTests(unittest.TestCase):
    def test_skill_is_available_without_installing_or_initializing_home(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root) / 'missing'
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(['--home', str(home), 'skills', 'show', 'task-monitor']), 0)
            self.assertIn('native runtime', json.loads(out.getvalue())['content'])
            self.assertFalse(home.exists())

    def test_owner_skill_wins_without_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / 'task-monitor'; directory.mkdir()
            (directory / 'SKILL.md').write_text('Owner instructions')
            store = SkillStore(root)
            self.assertEqual(store.read('task-monitor', 1000)['content'], 'Owner instructions')
            self.assertEqual([s['name'] for s in store.list()].count('task-monitor'), 1)

    def test_default_skill_list_includes_monitor(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertIn('task-monitor', [s['name'] for s in SkillStore(root).list()])
