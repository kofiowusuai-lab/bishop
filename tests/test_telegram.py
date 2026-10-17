import tempfile
import unittest
from pathlib import Path
from bishop_runtime.telegram import TelegramService, TelegramError

class Client:
    def __init__(self, updates=(), fail=False): self.updates=list(updates); self.sent=[]; self.fail=fail
    def get_updates(self, offset, timeout=25): return [u for u in self.updates if u['update_id']>=offset]
    def send_message(self, chat_id, text):
        self.sent.append((chat_id,text))
        if self.fail: raise TimeoutError('secret token')
        return {'message_id':len(self.sent)}
class Runtime:
    def __init__(self): self.runs=[]
    def active(self, session_id, actor='local'): return None
    def run(self, session_id,text,actor='local'):
        self.runs.append((session_id,text,actor)); return {'id':'r1','actor':actor,'status':'completed','output':'answer','pending':[]}
    def status(self,run_id): return {'id':run_id,'actor':'telegram:7','status':'completed','output':'answer','pending':[]}

def update(i,user=7,text='hello',kind='private'):
    return {'update_id':i,'message':{'from':{'id':user},'chat':{'id':user,'type':kind},'text':text}}

class TelegramTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(); self.home=Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def test_deduplicates_and_excludes_denied_content(self):
        c=Client([update(1),update(2,8,'private-secret'),update(3,7,'group-secret','group')]); r=Runtime()
        s=TelegramService(self.home,c,r,[7]); s.poll_once(); s.poll_once(); s.close()
        self.assertEqual(len(r.runs),1); self.assertEqual(c.sent,[(7,'answer')])
        self.assertNotIn(b'private-secret',(self.home/'telegram.db').read_bytes())
    def test_uncertain_send_requires_explicit_retry(self):
        c=Client([update(1)],True); s=TelegramService(self.home,c,Runtime(),[7]); s.poll_once(); s.poll_once()
        self.assertEqual(len(c.sent),1); d=s.deliveries()[0]; self.assertEqual(d['status'],'uncertain')
        c.fail=False; s.resolve_delivery(d['id'],'retry'); s.poll_once(); self.assertEqual(len(c.sent),2); s.close()
    def test_second_poller_refused_and_restart_deduplicates(self):
        c=Client([update(1)]); r=Runtime(); s=TelegramService(self.home,c,r,[7])
        with self.assertRaises(TelegramError): TelegramService(self.home,c,r,[7])
        s.poll_once(); s.close(); s=TelegramService(self.home,c,r,[7]); s.poll_once(); s.close(); self.assertEqual(len(r.runs),1)
    def test_foreign_actor_cannot_resume(self):
        c=Client([update(1,8,'/resume r1')]); r=Runtime(); s=TelegramService(self.home,c,r,[8]); s.poll_once(); s.close()
        self.assertIn('not owned',c.sent[0][1]); self.assertFalse(r.runs)
    def test_long_output_split_without_loss(self):
        r=Runtime(); r.run=lambda *a,**k: {'status':'completed','output':'😀'*5000,'pending':[],'id':'r'}
        c=Client([update(1)]); s=TelegramService(self.home,c,r,[7]); s.poll_once(); s.close()
        self.assertEqual(''.join(text for _,text in c.sent),'😀'*5000)
        self.assertTrue(all(len(t.encode('utf-16-le'))//2<=4096 for _,t in c.sent))

class TelegramHTTPTests(unittest.TestCase):
    def test_http_protocol_redirect_rejection_and_error_secrecy(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from bishop_runtime.telegram import TelegramClient
        class Handler(BaseHTTPRequestHandler):
            redirect=False
            def log_message(self,*args): pass
            def do_POST(self):
                import json
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.server.seen=(self.path,body)
                if self.redirect:
                    self.send_response(302); self.send_header('Location','/leak'); self.end_headers(); return
                result=[] if self.path.endswith('getUpdates') else {'message_id':1}
                self.send_response(200); self.end_headers(); self.wfile.write(json.dumps({'ok':True,'result':result}).encode())
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            client=TelegramClient('123:SECRET',f'http://127.0.0.1:{server.server_port}')
            self.assertEqual(client.get_updates(42),[]); self.assertEqual(server.seen[1]['offset'],42)
            self.assertEqual(client.send_message(7,'hello'),{'message_id':1})
            Handler.redirect=True
            with self.assertRaises(TelegramError) as error: client.send_message(7,'hello')
            self.assertNotIn('SECRET',str(error.exception)); self.assertNotEqual(server.seen[0],'/leak')
        finally: server.shutdown(); server.server_close(); thread.join()

    def test_crashed_send_is_uncertain_after_reopen(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as home:
            c=Client([update(1)],True); s=TelegramService(home,c,Runtime(),[7]); s.poll_once(); d=s.deliveries()[0]; s.close()
            db=sqlite3.connect(Path(home)/'telegram.db'); db.execute("UPDATE deliveries SET status='sending'"); db.commit(); db.close()
            s=TelegramService(home,c,Runtime(),[7]); s.poll_once()
            self.assertEqual(s.deliveries()[0]['status'],'uncertain'); self.assertEqual(len(c.sent),1); s.close()

class TelegramMalformedTests(unittest.TestCase):
    def test_malformed_update_is_discarded_and_cursor_advances(self):
        with tempfile.TemporaryDirectory() as home:
            c=Client([{'update_id':1,'message':None}]); s=TelegramService(home,c,Runtime(),[7])
            self.assertEqual(s.poll_once()['offset'],2); self.assertFalse(s.deliveries()); s.close()

class TelegramRecoveryTests(unittest.TestCase):
    def test_revoked_inbox_and_outbox_never_run_or_deliver(self):
        import json
        with tempfile.TemporaryDirectory() as home:
            c=Client(); r=Runtime(); s=TelegramService(home,c,r,[7])
            s.state.ingest([update(1)],s._authorize)
            s.state.ingest([update(2)],s._authorize)
            s.state.finish(2,7,['revoked response']); s.close()
            s=TelegramService(home,c,r,[8]); s.poll_once()
            self.assertFalse(r.runs); self.assertFalse(c.sent); s.close()
    def test_uncertain_first_part_holds_remaining_parts(self):
        with tempfile.TemporaryDirectory() as home:
            c=Client([update(1)],True); r=Runtime(); r.run=lambda *a,**k: {'status':'completed','output':'x'*5000,'pending':[],'id':'r'}
            s=TelegramService(home,c,r,[7]); s.poll_once(); self.assertEqual(len(c.sent),1)
            c.fail=False; s.poll_once(); self.assertEqual(len(c.sent),1)
            s.resolve_delivery(s.deliveries()[0]['id'],'sent'); s.poll_once(); self.assertEqual(len(c.sent),2); s.close()
    def test_interrupted_inbox_never_replays_user_task(self):
        with tempfile.TemporaryDirectory() as home:
            c=Client(); r=Runtime(); s=TelegramService(home,c,r,[7]); s.state.ingest([update(1)],s._authorize); s.state.mark(1,'processing'); s.close()
            s=TelegramService(home,c,r,[7]); s.poll_once(); self.assertFalse(r.runs); self.assertIn('interrupted',c.sent[0][1]); s.close()

class TelegramStatusTests(unittest.TestCase):
    def test_status_completed_run_checks_owner(self):
        with tempfile.TemporaryDirectory() as home:
            c=Client([update(1,7,'/status r1'),update(2,8,'/status r1')]); s=TelegramService(home,c,Runtime(),[7,8]); s.poll_once(); s.close()
            self.assertEqual(c.sent[0],(7,'answer')); self.assertIn('not owned',c.sent[1][1])
    def test_invalid_http_timeout_rejected(self):
        from bishop_runtime.telegram import TelegramClient
        for timeout in (float('nan'),float('inf'),0,121):
            with self.assertRaises(ValueError): TelegramClient('TOKEN',timeout=timeout)
