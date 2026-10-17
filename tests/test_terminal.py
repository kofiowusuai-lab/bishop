import io
import unittest
from unittest.mock import patch

from bishop_runtime.terminal import print_boot, render_boot, safe_text


class TerminalTests(unittest.TestCase):
    def test_plain_boot_shows_identity_and_details(self):
        result = render_boot({'profile': 'work', 'model': 'model-x', 'tools': 8,
                              'skills': 3, 'home': '/tmp/bishop', 'session': 'abc',
                              'version': '0.1.0'}, width=100, color=False)
        for expected in ['BISHOP', 'work', 'model-x', '8', '3', '/tmp/bishop', 'abc', '0.1.0']:
            self.assertIn(expected, result)
        self.assertNotIn('\x1b', result)
        self.assertTrue(all(len(line) <= 100 for line in result.splitlines()))

    def test_narrow_and_tiny_widths_never_overflow(self):
        for width in [1, 12, 24, 40, 60, 80, 120]:
            result = render_boot({'model': 'x' * 200, 'home': '/long/' * 100}, width=width, color=False)
            self.assertTrue(all(len(line) <= width for line in result.splitlines()), width)

    def test_inventory_names_wrap_without_hiding_capabilities(self):
        names = ['list_files', 'read_file', 'write_file', 'memory_search',
                 'memory_remember', 'list_skills', 'read_skill']
        result = render_boot({'tools': names, 'skills': ['research', 'code-review']},
                             width=80, color=False)
        self.assertIn('Available tools (7)', result)
        self.assertIn('Installed skills (2)', result)
        for name in names + ['research', 'code-review']:
            self.assertIn(name, result)
        self.assertTrue(all(len(row) == 80 for row in result.splitlines() if row.startswith('│')))

    def test_compact_visual_layout(self):
        result = render_boot({'tools': ['read_file'], 'skills': []}, width=42, color=False)
        rows = result.splitlines()
        self.assertEqual(rows[0], 'BISHOP · independent agent runtime')
        # The silhouette's diagonal mitre cut and broad base are identity landmarks.
        self.assertIn('      ●●●● ●●      ', rows)
        self.assertIn('   ●●●●●●●●●●●●●   ', rows)
        self.assertIn('Available tools (1)', rows)
        self.assertIn('read_file', rows)
        self.assertIn('Installed skills (0)', rows)
        self.assertEqual(rows[-1], 'Your workspace. Your models. Your Bishop.')

    def test_hostile_metadata_is_sanitized(self):
        value = '\x1b[31mred\x1b[0m\x1b]0;evil\x07\n\r\t\x00\u202eBAD'
        self.assertEqual(safe_text(value), 'red BAD')
        result = render_boot({'model': value}, width=80, color=False)
        self.assertNotIn('\x1b', result)
        self.assertNotIn('\u202e', result)
        self.assertNotIn('evil', result)

    def test_colors_explicit_and_no_color_override(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertIn('\x1b[', render_boot({}, width=80, color=True))
        with patch.dict('os.environ', {'NO_COLOR': ''}, clear=True):
            self.assertNotIn('\x1b', render_boot({}, width=80, color=True))

    def test_non_tty_print_is_plain(self):
        stream = io.StringIO()
        print_boot({'model': 'none'}, stream=stream)
        self.assertIn('BISHOP', stream.getvalue())
        self.assertNotIn('\x1b', stream.getvalue())
