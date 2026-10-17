import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bishop_runtime.cli import main, parser
from bishop_runtime.config import init_home


class OperatorCommandsTests(unittest.TestCase):
    def call(self, home, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(['--home', str(home), *args])
        return code, out.getvalue(), err.getvalue()

    def test_read_commands_do_not_initialize_home_or_construct_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / 'missing'
            with patch('bishop_runtime.cli._runtime', side_effect=AssertionError('runtime')), patch('bishop_runtime.provider.HTTPProvider.__init__', side_effect=AssertionError('provider')):
                for args in [('status',), ('doctor',), ('config',), ('config', 'show'), ('tools',), ('tools', 'list'), ('skills',), ('skills', 'list')]:
                    with self.subTest(args=args):
                        code, out, err = self.call(home, *args)
                        self.assertEqual(code, 0, err)
                        self.assertIsInstance(json.loads(out), dict)
                        self.assertFalse(home.exists())

    def test_doctor_warns_missing_model_and_fails_malformed_config(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); init_home(home)
            code, out, _ = self.call(home, 'doctor')
            self.assertEqual(code, 0)
            self.assertIn('warn', out)
            (home / 'config.json').write_text('{broken secret-value')
            code, out, err = self.call(home, 'doctor')
            self.assertEqual(code, 1)
            self.assertIn('fail', out)
            self.assertNotIn('secret-value', out + err)

    def test_config_redacts_url_components_and_saved_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); init_home(home)
            config = json.loads((home / 'config.json').read_text())
            config['audit']['hub_url'] = 'https://user:password@example.com/private-secret?token=query-secret#fragment-secret'
            (home / 'config.json').write_text(json.dumps(config))
            (home / 'profiles.json').write_text(json.dumps({'active': 'test', 'profiles': {'test': {'name': 'test', 'kind': 'compatible', 'base_url': 'https://example.com/path-secret', 'model': 'model', 'api_key_env': None}}}))
            (home / 'credentials.json').write_text(json.dumps({'test': {'api_key': 'saved-secret'}}))
            for command in ('config', 'status', 'doctor'):
                code, out, err = self.call(home, command)
                self.assertEqual(code, 0, err)
                for secret in ('password', 'private-secret', 'query-secret', 'fragment-secret', 'path-secret', 'saved-secret'):
                    self.assertNotIn(secret, out + err)
                self.assertIn('network', out)

    def test_tools_obey_flags_and_skills_are_bounded_and_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); init_home(home)
            config = json.loads((home / 'config.json').read_text()); config['allow_write'] = False
            (home / 'config.json').write_text(json.dumps(config))
            code, out, _ = self.call(home, 'tools', 'list')
            self.assertEqual(code, 0); self.assertNotIn('write_file', out); self.assertNotIn('run_command', out)
            skill = home / 'skills' / 'example'; skill.mkdir(); (skill / 'SKILL.md').write_text('Instructions')
            self.assertIn('example', self.call(home, 'skills', 'list')[1])
            self.assertEqual(json.loads(self.call(home, 'skills', 'show', 'example')[1])['content'], 'Instructions')
            self.assertEqual(self.call(home, 'skills', 'show', '../config')[0], 1)
            self.assertEqual(self.call(home, 'skills', 'show', 'missing')[0], 1)

    def test_skill_show_preserves_markdown_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); init_home(home)
            skill = home / 'skills' / 'formatted'; skill.mkdir()
            (skill / 'SKILL.md').write_text('# Guide\n\n```sh\necho first\necho second\n```\n')
            code, out, err = self.call(home, 'skills', 'show', 'formatted')
            self.assertEqual(code, 0, err)
            self.assertIn('```sh\necho first\necho second\n```', json.loads(out)['content'])

    def test_doctor_rejects_invalid_url_type_and_active_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); init_home(home)
            config = json.loads((home / 'config.json').read_text())
            config['provider']['base_url'] = 123
            (home / 'config.json').write_text(json.dumps(config))
            self.assertEqual(self.call(home, 'doctor')[0], 1)
            config['provider']['base_url'] = 'http://localhost:11434/v1'
            (home / 'config.json').write_text(json.dumps(config))
            for model, url in [('', 'https://example.com'), ('model', 'http://evil.com')]:
                (home / 'profiles.json').write_text(json.dumps({'active': 'test', 'profiles': {'test': {
                    'name': 'test', 'kind': 'compatible', 'base_url': url, 'model': model, 'api_key_env': None}}}))
                code, out, _ = self.call(home, 'doctor')
                self.assertEqual(code, 1)
                self.assertIn('fail', out)

    def test_skill_root_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / 'home'; init_home(home)
            external = Path(directory) / 'external'; external.mkdir()
            skill = external / 'secret'; skill.mkdir(); (skill / 'SKILL.md').write_text('outside-content')
            (home / 'skills').rmdir(); (home / 'skills').symlink_to(external)
            code, out, err = self.call(home, 'skills', 'show', 'secret')
            self.assertEqual(code, 1)
            self.assertNotIn('outside-content', out + err)

    def test_model_dispatches_existing_picker(self):
        with tempfile.TemporaryDirectory() as directory, patch('bishop_runtime.onboarding.select_profile') as pick:
            home = Path(directory)
            self.assertEqual(self.call(home, 'model')[0], 0)
            pick.assert_called_once_with(home.resolve())

    def test_initialized_reports_leave_filesystem_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); init_home(home)
            before = {str(p.relative_to(home)): (p.read_bytes() if p.is_file() else None) for p in home.rglob('*')}
            with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network')), patch('bishop_runtime.provider.HTTPProvider.__init__', side_effect=AssertionError('provider')):
                for command in ('status', 'doctor', 'config', 'tools', 'skills'):
                    self.assertEqual(self.call(home, command)[0], 0)
            after = {str(p.relative_to(home)): (p.read_bytes() if p.is_file() else None) for p in home.rglob('*')}
            self.assertEqual(before, after)

    def test_symlink_skill_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); init_home(home)
            outside = home / 'outside'; outside.mkdir(); (outside / 'SKILL.md').write_text('private')
            (home / 'skills' / 'linked').symlink_to(outside, target_is_directory=True)
            self.assertEqual(self.call(home, 'skills', 'show', 'linked')[0], 1)
            self.assertNotIn('linked', self.call(home, 'skills')[1])

    def test_login_alias_forwards_options(self):
        with tempfile.TemporaryDirectory() as directory, patch('bishop_runtime.oauth.ChatGPTAuth') as auth, patch('bishop_runtime.profiles.ProfileStore') as store, patch('bishop_runtime.onboarding.choose_chatgpt_model') as picker:
            home = Path(directory)
            code, out, err = self.call(home, 'login', '--model', 'chosen', '--name', 'mine', '--no-browser')
            self.assertEqual(code, 0, err)
            self.assertFalse(auth.return_value.login.call_args.kwargs['open_browser'])
            store.return_value.save.assert_called_once_with('mine', 'chatgpt', 'https://api.openai.com/v1', 'chosen')
            picker.assert_not_called()

    def test_auth_alias_dispatches_existing_logout(self):
        with tempfile.TemporaryDirectory() as directory, patch('bishop_runtime.oauth.ChatGPTAuth') as auth:
            auth.return_value.logout.return_value = {'logged_out': True}
            self.assertEqual(self.call(Path(directory), 'logout')[0], 0)
            auth.return_value.logout.assert_called_once_with()

    def test_auth_alias_options_and_legacy_status_parse(self):
        args = parser().parse_args(['login', '--model', 'chosen', '--name', 'mine', '--no-browser'])
        self.assertEqual(args.model, 'chosen'); self.assertTrue(args.no_browser)
        self.assertEqual(parser().parse_args(['logout']).command, 'logout')
        self.assertEqual(parser().parse_args(['status', 'run-id']).run, 'run-id')
