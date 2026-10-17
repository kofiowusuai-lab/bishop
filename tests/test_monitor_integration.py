import contextlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from bishop_runtime.cli import main, _runtime
from bishop_runtime.config import init_home, load_config
from bishop_runtime.provider import ScriptedProvider
from bishop_runtime.shell import run_chat
from bishop_runtime.telegram import TelegramService


class MonitorIntegrationTests(unittest.TestCase):
    def test_shell_progress_is_default_and_skill_visible(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root); init_home(home); config = load_config(home)
            runtime, memory = _runtime(home, config, ScriptedProvider([{'content':'answer','tool_calls':[]}]))
            out = io.StringIO(); replies = iter(['hello','/exit'])
            try:
                run_chat(runtime, home, config, input_fn=lambda prompt:next(replies), output=out)
                self.assertIn('elapsed', out.getvalue())
                self.assertIn('Completed', out.getvalue())
                self.assertIn('Bishop › answer', out.getvalue())
            finally: runtime.close(); memory.close()

    def test_one_shot_json_stdout_progress_stderr(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root); init_home(home)
            out, err = io.StringIO(), io.StringIO()
            provider = ScriptedProvider([{'content':'answer','tool_calls':[]}])
            with patch('bishop_runtime.cli.provider_from_config', return_value=provider), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(main(['--home',str(home),'chat','hello']), 0)
            self.assertEqual(json.loads(out.getvalue())['output'],'answer')
            self.assertIn('elapsed',err.getvalue())

    def test_disabled_monitoring_does_not_create_journal(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root); init_home(home); config = load_config(home)
            config['monitoring']['enabled'] = False
            runtime, memory = _runtime(home,config,ScriptedProvider([{'content':'answer','tool_calls':[]}]))
            try: runtime.run('s','hello')
            finally: runtime.close(); memory.close()
            self.assertFalse((home/'progress.db').exists())

    def test_telegram_progress_arrives_during_blocking_model(self):
        class Client:
            def __init__(self): self.sent=[]; self.edits=[]; self.notified=threading.Event()
            def get_updates(self,offset,timeout=25):
                return [{'update_id':1,'message':{'from':{'id':7},'chat':{'id':7,'type':'private'},'text':'PRIVATE_PROMPT'}}] if offset<=1 else []
            def send_message(self,chat,text):
                self.sent.append((chat,text)); self.notified.set(); return {'message_id':len(self.sent)}
            def edit_message(self,chat,message_id,text): self.edits.append((chat,message_id,text)); return {'message_id':message_id}
        client=Client()
        class Provider:
            def complete(self,*args):
                if not client.notified.wait(2): raise RuntimeError('no live card')
                return {'content':'final answer','tool_calls':[]}
        with tempfile.TemporaryDirectory() as root:
            home=Path(root); init_home(home); config=load_config(home)
            runtime,memory=_runtime(home,config,Provider()); service=TelegramService(home,client,runtime,[7])
            try:
                service.poll_once()
                self.assertEqual(client.sent[-1],(7,'final answer'))
                self.assertTrue(any('Completed' in text for _,_,text in client.edits))
                progress=[text for _,text in client.sent if text!='final answer']+[text for _,_,text in client.edits]
                self.assertTrue(progress)
                self.assertNotIn('PRIVATE_PROMPT',''.join(progress))
                service.poll_once()
                self.assertEqual(len(client.sent),2)
            finally: service.close(); runtime.close(); memory.close()

    def test_telegram_approval_resume_reuses_card_and_failure_does_not_retry_task(self):
        class Client:
            def __init__(self): self.updates=[];self.sent=[];self.edits=[]
            def get_updates(self,offset,timeout=25):return [u for u in self.updates if u['update_id']>=offset]
            def send_message(self,chat,text):self.sent.append((chat,text));return {'message_id':len(self.sent)}
            def edit_message(self,chat,message,text):self.edits.append((chat,message,text));return {'message_id':message}
            def update(self,ident,text):self.updates.append({'update_id':ident,'message':{'from':{'id':7},'chat':{'id':7,'type':'private'},'text':text}})
        with tempfile.TemporaryDirectory() as root:
            home=Path(root);init_home(home);config=load_config(home);client=Client()
            provider=ScriptedProvider([
                {'content':None,'tool_calls':[{'id':'save','name':'write_file','arguments':{'path':'note.txt','content':'PRIVATE_RESULT'}}]},
                {'content':'saved','tool_calls':[]}])
            runtime,memory=_runtime(home,config,provider);service=TelegramService(home,client,runtime,[7])
            try:
                client.update(1,'save note');service.poll_once()
                run=runtime.active('telegram:7',actor='telegram:7')
                client.update(2,f"/approve {run['id']} save");service.poll_once()
                client.update(3,f"/resume {run['id']}");service.poll_once()
                cards=[t for _,t in client.sent if t.startswith('Bishop ·')]
                self.assertEqual(len(cards),1)
                self.assertEqual({mid for _,mid,_ in client.edits},{1})
                self.assertEqual((home/'workspace'/'note.txt').read_text(),'PRIVATE_RESULT')
                self.assertNotIn('PRIVATE_RESULT',''.join(cards+[t for _,_,t in client.edits]))
                self.assertEqual(len(provider.requests),2)
            finally:service.close();runtime.close();memory.close()

    def test_progress_transport_failure_preserves_final_answer_and_no_model_retry(self):
        class Client:
            def __init__(self):self.sent=[]
            def get_updates(self,offset,timeout=25):
                return [{'update_id':1,'message':{'from':{'id':7},'chat':{'id':7,'type':'private'},'text':'hello'}}] if offset<=1 else []
            def send_message(self,chat,text):
                if text.startswith('Bishop ·'):raise TimeoutError('SECRET-TOKEN')
                self.sent.append((chat,text));return {'message_id':1}
            def edit_message(self,*args):raise AssertionError('uncertain card should not edit')
        with tempfile.TemporaryDirectory() as root:
            home=Path(root);init_home(home);config=load_config(home);client=Client()
            provider=ScriptedProvider([{'content':'final answer','tool_calls':[]}])
            runtime,memory=_runtime(home,config,provider);service=TelegramService(home,client,runtime,[7])
            try:
                with self.assertLogs('bishop_runtime.progress',level='WARNING') as logs:service.poll_once()
                self.assertEqual(client.sent,[(7,'final answer')])
                self.assertEqual(len(provider.requests),1)
                self.assertNotIn('SECRET-TOKEN',' '.join(logs.output))
                self.assertEqual(service._progress_cards[(7,7)].deliveries()[0]['state'],'uncertain')
            finally:service.close();runtime.close();memory.close()

    def test_telegram_edit_wire_and_already_current_is_success(self):
        from unittest.mock import Mock
        import urllib.error
        from bishop_runtime.telegram import TelegramClient
        client=TelegramClient('synthetic-token')
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        response.read.return_value=b'{"ok":true,"result":{"message_id":12}}'
        client.opener=Mock();client.opener.open.return_value=response
        client.edit_message(7,12,'progress',timeout=5)
        request=client.opener.open.call_args.args[0]
        self.assertTrue(request.full_url.endswith('/editMessageText'))
        self.assertEqual(json.loads(request.data),{'chat_id':7,'message_id':12,'text':'progress'})
        self.assertEqual(client.opener.open.call_args.kwargs['timeout'],5)
        error=urllib.error.HTTPError('https://example.invalid/SECRET',400,'secret',{},io.BytesIO(b'{"ok":false,"description":"Bad Request: message is not modified"}'))
        client.opener.open.side_effect=error
        self.assertEqual(client.edit_message(7,12,'progress',timeout=5),{'message_id':12})
        self.assertTrue(error.fp.closed)
