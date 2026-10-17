import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from bishop_runtime.cli import main
from bishop_runtime.config import init_home, load_config


class MonitorCommandTests(unittest.TestCase):
    def call(self,home,*args):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            code=main(['--home',str(home),'monitor',*args])
        return code,json.loads(out.getvalue())

    def test_inspection_does_not_initialize_or_send(self):
        with tempfile.TemporaryDirectory() as root:
            home=Path(root)/'missing'
            with patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('network')):
                code,value=self.call(home,'status')
                self.assertEqual(code,0);self.assertTrue(value['enabled'])
                self.assertTrue(value['bundled_skill'])
                self.assertEqual(self.call(home,'runs')[1],[])
                self.assertEqual(self.call(home,'events','missing')[1],[])
                self.assertEqual(self.call(home,'deliveries')[1],[])
            self.assertFalse(home.exists())

    def test_configure_is_choice_based_and_does_not_send(self):
        with tempfile.TemporaryDirectory() as root:
            home=Path(root);init_home(home)
            out=io.StringIO()
            with patch('bishop_runtime.monitor_commands.choose',return_value='disable'), contextlib.redirect_stdout(out):
                self.assertEqual(main(['--home',str(home),'monitor','configure']),0)
            self.assertFalse(load_config(home)['monitoring']['enabled'])

    def test_status_never_exposes_webhook_secret(self):
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ',{'BISHOP_DISCORD_WEBHOOK_URL':'https://discord.com/api/webhooks/1/PRIVATE_WEBHOOK_TOKEN'}):
            _,value=self.call(Path(root),'status')
            self.assertNotIn('PRIVATE_WEBHOOK_TOKEN',json.dumps(value))

    def test_uncertain_card_can_be_adopted_but_confirmed_card_cannot_be_reset(self):
        from bishop_runtime.progress_transports import ProgressCards
        with tempfile.TemporaryDirectory() as root:
            home=Path(root)
            def fail(text):raise TimeoutError('private-token')
            cards=ProgressCards(home,fail,lambda *a:None,'telegram','7')
            with self.assertRaises(RuntimeError):cards({'run_id':'run-1','phase':'started','status':'running'})
            cards.close()
            row=self.call(home,'deliveries')[1][0]
            code,value=self.call(home,'resolve','run-1','--channel','telegram','--destination',row['destination'],'--action','sent','--message-id','42')
            self.assertEqual(code,0);self.assertTrue(value['resolved'])
            self.assertEqual(self.call(home,'deliveries')[1][0]['message_id'],42)
            out,err=io.StringIO(),io.StringIO()
            with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
                code=main(['--home',str(home),'monitor','resolve','run-1','--channel','telegram','--destination',row['destination'],'--action','retry'])
            self.assertEqual(code,1)
            self.assertEqual(self.call(home,'deliveries')[1][0]['state'],'sent')
