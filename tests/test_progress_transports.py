import io
import tempfile
import unittest
from unittest.mock import patch
from bishop_runtime.progress_transports import ProgressCards, TerminalProgress, render_progress, DiscordWebhook

class ProgressTransportTests(unittest.TestCase):
    def snapshot(self): return dict(run_id='abc',phase='model_started',status='running',elapsed=10,step=1,prompt='SECRET',tool='read_file')
    def test_reuses_card_across_restart(self):
        with tempfile.TemporaryDirectory() as home:
            sent=[]; edited=[]
            p=ProgressCards(home,lambda text: sent.append(text) or 12,lambda mid,text: edited.append(mid),'telegram','123')
            p(self.snapshot()); p.close()
            p=ProgressCards(home,lambda text: sent.append(text) or 13,lambda mid,text: edited.append(mid),'telegram','123')
            s=self.snapshot(); s['elapsed']=20; p(s); p.close()
            self.assertEqual(len(sent),1); self.assertEqual(edited,[12]); self.assertNotIn('SECRET',sent[0])
    def test_ambiguous_creation_never_retries(self):
        with tempfile.TemporaryDirectory() as home:
            sent=[]
            def fail(text): sent.append(text); raise TimeoutError('SECRET')
            p=ProgressCards(home,fail,lambda *a:None,'discord','secret-url')
            with self.assertRaisesRegex(RuntimeError,'uncertain'): p(self.snapshot())
            p(self.snapshot())
            self.assertEqual(len(sent),1); self.assertEqual(p.deliveries()[0]['state'],'uncertain'); p.close()
    def test_authorization_and_rollover(self):
        with tempfile.TemporaryDirectory() as home:
            sent=[]; allowed=[False]
            p=ProgressCards(home,lambda text: sent.append(text) or len(sent),lambda *a:None,'whatsapp','x',authorized=lambda:allowed[0],rollover_seconds=840)
            with patch('bishop_runtime.progress_transports.time.time',return_value=100): p(self.snapshot())
            self.assertEqual(sent,[]); allowed[0]=True
            with patch('bishop_runtime.progress_transports.time.time',return_value=100): p(self.snapshot())
            with patch('bishop_runtime.progress_transports.time.time',return_value=941): p(self.snapshot())
            self.assertEqual(len(sent),2); p.close()
    def test_safe_render_and_terminal(self):
        s=self.snapshot(); s['tool']='evil\x1b[31m\nSECRET'
        self.assertNotIn('SECRET',render_progress(s)); output=io.StringIO(); TerminalProgress(output)(s)
        self.assertIn('Bishop',output.getvalue()); self.assertNotIn('\x1b',output.getvalue())
    def test_discord_rejects_non_webhooks(self):
        for url in ['http://discord.com/api/webhooks/1/x','https://evil.com/api/webhooks/1/x','https://discord.com/api/webhooks/1/x?foo=bar']:
            with self.assertRaises(ValueError): DiscordWebhook(url)
    def test_explicit_adoption_and_edit_retry(self):
        with tempfile.TemporaryDirectory() as home:
            edits=[]
            def fail(text):raise TimeoutError()
            p=ProgressCards(home,fail,lambda mid,text:edits.append(mid),'telegram','123')
            with self.assertRaises(RuntimeError):p(self.snapshot())
            p.resolve('abc','sent',77)
            s=self.snapshot();s['elapsed']=50;p(s)
            self.assertEqual(edits,[77]);self.assertEqual(p.deliveries()[0]['state'],'sent');p.close()
    def test_discord_suppresses_mentions_and_uses_patch(self):
        from unittest.mock import Mock
        import json
        transport=DiscordWebhook('https://discord.com/api/webhooks/123/token')
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False);response.read=Mock(return_value=b'{"id":"456"}')
        transport.opener=Mock();transport.opener.open.return_value=response
        self.assertEqual(transport.send('hello'), '456');transport.edit('456','done')
        calls=transport.opener.open.call_args_list
        self.assertTrue(calls[0].args[0].full_url.endswith('?wait=true'))
        self.assertEqual(calls[1].args[0].method,'PATCH')
        self.assertEqual(json.loads(calls[0].args[0].data)['allowed_mentions'],{'parse':[]})
    def test_whatsapp_bridge_payload(self):
        from bishop_runtime.progress_transports import WhatsAppBridge
        from unittest.mock import Mock
        transport=WhatsAppBridge('http://127.0.0.1:3000','123@c.us');transport.request=Mock(side_effect=[{'ok':True,'messageId':'abc'},{'ok':True}])
        self.assertEqual(transport.send('hi'),'abc');transport.edit('abc','done')
        self.assertEqual(transport.request.call_args_list[1].args,('http://127.0.0.1:3000/edit',{'chatId':'123@c.us','messageId':'abc','message':'done'}))
    def test_cross_instance_create_claim(self):
        with tempfile.TemporaryDirectory() as home:
            sent=[]
            p2=ProgressCards(home,lambda text:sent.append(text) or 2,lambda *a:None,'telegram','123')
            def send(text):
                p2(self.snapshot());sent.append(text);return 1
            p1=ProgressCards(home,send,lambda *a:None,'telegram','123');p1(self.snapshot())
            self.assertEqual(len(sent),1);p1.close();p2.close()
    def test_coalesces_interim_edits_but_forces_terminal_states(self):
        with tempfile.TemporaryDirectory() as home:
            edits=[]
            p=ProgressCards(home,lambda text:1,lambda mid,text:edits.append(text),'telegram','123')
            with patch('bishop_runtime.progress_transports.time.monotonic',return_value=100):
                p(self.snapshot())
                for step in range(2,20):
                    s=self.snapshot();s['step']=step;p(s)
                self.assertEqual(edits,[])
                s['status']='awaiting_approval';s['phase']='awaiting_approval';p(s)
                self.assertEqual(len(edits),1)
            with patch('bishop_runtime.progress_transports.time.monotonic',return_value=101):
                s=self.snapshot();s['step']=20;p(s)
                self.assertEqual(len(edits),2)
            p.close()
    def test_edit_failure_surfaces_generic_visibility_error(self):
        with tempfile.TemporaryDirectory() as home:
            def edit(*a):raise TimeoutError('SECRET')
            p=ProgressCards(home,lambda text:1,edit,'telegram','123',min_edit_interval=0);p(self.snapshot())
            s=self.snapshot();s['elapsed']=20
            with self.assertRaisesRegex(RuntimeError,'^Progress message edit failed$'):p(s)
            self.assertEqual(p.deliveries()[0]['state'],'edit_failed');p.close()
    def test_terminal_close_finishes_line_and_honors_width(self):
        class TTY(io.StringIO):
            def isatty(self):return True
        output=TTY();sink=TerminalProgress(output)
        import os
        with patch('bishop_runtime.progress_transports.shutil.get_terminal_size',return_value=os.terminal_size((30,20))):sink(self.snapshot())
        self.assertLessEqual(len(output.getvalue().removeprefix('\r\x1b[2K')),29)
        sink.close();self.assertTrue(output.getvalue().endswith('\n'))
        self.assertIn('Interrupted',render_progress(dict(run_id='abc',status='interrupted',phase='interrupted')))
