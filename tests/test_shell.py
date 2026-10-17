import io
from pathlib import Path
import tempfile
import unittest
from bishop_runtime.cli import _runtime
from bishop_runtime.config import init_home, load_config
from bishop_runtime.provider import ScriptedProvider
from bishop_runtime.shell import run_chat


class ShellTests(unittest.TestCase):
    def test_interactive_real_tool_approval_without_json_dump(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root); init_home(home); config = load_config(home)
            provider = ScriptedProvider([
                {'content': None, 'tool_calls': [{'id': 'save', 'name': 'write_file', 'arguments': {'path': 'note.txt', 'content': 'hello'}}]},
                {'content': 'Saved your note.', 'tool_calls': []}])
            runtime, memory = _runtime(home, config, provider)
            replies = iter(['Save a note', 'y', '/exit'])
            output = io.StringIO()
            try:
                run_chat(runtime, home, config, input_fn=lambda prompt: next(replies), output=output)
                self.assertEqual((home / 'workspace' / 'note.txt').read_text(), 'hello')
                self.assertIn('Saved your note.', output.getvalue())
                self.assertIn('write_file', output.getvalue())
                self.assertNotIn('"audit_complete"', output.getvalue())
            finally:
                runtime.close(); memory.close()

    def test_later_preserves_pending_and_commands_can_approve(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root); init_home(home); config = load_config(home)
            provider = ScriptedProvider([
                {'content': None, 'tool_calls': [{'id': 'save', 'name': 'write_file', 'arguments': {'path': 'note.txt', 'content': 'hello'}}]},
                {'content': 'done', 'tool_calls': []}])
            runtime, memory = _runtime(home, config, provider)
            replies = iter(['Save a note', 'l', '/status', '/approve save', '/resume', '/exit'])
            try:
                run_chat(runtime, home, config, input_fn=lambda prompt: next(replies), output=io.StringIO())
                self.assertTrue((home / 'workspace' / 'note.txt').exists())
            finally:
                runtime.close(); memory.close()
