import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from bishop_runtime.cli import main
from bishop_runtime.config import init_home,load_config


class WebCommandTests(unittest.TestCase):
    def invoke(self,home,*args):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):code=main(['--home',str(home),'web',*args])
        return code,json.loads(out.getvalue())

    def test_status_is_offline_and_does_not_initialize(self):
        with tempfile.TemporaryDirectory() as root:
            home=Path(root)/'missing'
            with patch('socket.getaddrinfo',side_effect=AssertionError('network')):
                code,value=self.invoke(home,'status')
            self.assertEqual(code,0);self.assertTrue(value['enabled']);self.assertFalse(home.exists())

    def test_direct_search_joins_query_without_model(self):
        with tempfile.TemporaryDirectory() as root,patch('bishop_runtime.web_commands.WebSearch') as search:
            search.return_value.search.return_value={'ok':True,'results':[]}
            with patch('bishop_runtime.cli._runtime',side_effect=AssertionError('model')):
                code,value=self.invoke(Path(root),'search','Hermes','agent')
            self.assertEqual(code,0)
            search.return_value.search.assert_called_once_with('Hermes agent',limit=5)

    def test_configure_provider_uses_choices(self):
        with tempfile.TemporaryDirectory() as root,patch('bishop_runtime.web_commands.choose',return_value='duckduckgo'):
            home=Path(root);init_home(home)
            self.assertEqual(self.invoke(home,'configure')[0],0)
            self.assertEqual(load_config(home)['web']['provider'],'duckduckgo')

    def test_disabled_web_is_not_called(self):
        with tempfile.TemporaryDirectory() as root,patch('bishop_runtime.web_commands.WebSearch') as search:
            home=Path(root);init_home(home)
            config=json.loads((home/'config.json').read_text());config['web']['enabled']=False
            (home/'config.json').write_text(json.dumps(config))
            code,value=self.invoke(home,'search','query')
            self.assertEqual(code,1);self.assertFalse(value['ok']);search.assert_not_called()

    def test_existing_home_inherits_web_defaults_without_rewrite(self):
        with tempfile.TemporaryDirectory() as root:
            home=Path(root);init_home(home)
            value=json.loads((home/'config.json').read_text());value.pop('web')
            (home/'config.json').write_text(json.dumps(value));before=(home/'config.json').read_bytes()
            self.assertTrue(load_config(home)['web']['enabled'])
            self.assertEqual((home/'config.json').read_bytes(),before)

    def test_invalid_web_configuration_is_rejected(self):
        for key,value in [('enabled','yes'),('provider','unknown'),('max_results',0),('timeout',999),('api_key_env','raw-secret-key!')]:
            with self.subTest(field=key),tempfile.TemporaryDirectory() as root:
                home=Path(root);init_home(home)
                config=json.loads((home/'config.json').read_text());config['web'][key]=value
                (home/'config.json').write_text(json.dumps(config))
                with self.assertRaises(ValueError):load_config(home)
