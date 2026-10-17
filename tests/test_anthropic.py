import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from bishop_runtime.anthropic import AnthropicProvider
from bishop_runtime.provider import ProviderError

class Handler(BaseHTTPRequestHandler):
    status = 200
    response = {'content': [{'type':'text','text':'hello'}], 'stop_reason':'end_turn'}
    received = None
    def log_message(self, *args): pass
    def do_POST(self):
        type(self).received = (self.path, dict(self.headers), json.loads(self.rfile.read(int(self.headers['Content-Length']))))
        self.send_response(self.status)
        if self.status == 302: self.send_header('Location', 'https://example.invalid')
        self.end_headers()
        self.wfile.write(json.dumps(self.response).encode())

class AnthropicTests(unittest.TestCase):
    def setUp(self):
        Handler.status = 200
        Handler.response = {'content': [{'type':'text','text':'hello'}], 'stop_reason':'end_turn'}
        self.server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        self.p = AnthropicProvider(f'http://127.0.0.1:{self.server.server_port}/v1','chosen',api_key='secret')
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
    def test_tool_round_trip(self):
        messages = [{'role':'system','content':'policy'}, {'role':'user','content':'read'}, {'role':'assistant','content':None,'tool_calls':[{'id':'a','function':{'name':'read_file','arguments':'{"path":"a"}'}},{'id':'b','function':{'name':'read_file','arguments':'{"path":"b"}'}}]}, {'role':'tool','tool_call_id':'a','content':'one'}, {'role':'tool','tool_call_id':'b','content':'two'}]
        self.assertEqual(self.p.complete(messages,[{'type':'function','function':{'name':'read_file','description':'Read','parameters':{'type':'object'}}}])['content'],'hello')
        path, headers, payload = Handler.received
        self.assertEqual(path,'/v1/messages')
        self.assertEqual({k.lower():v for k,v in headers.items()}['x-api-key'],'secret')
        self.assertEqual(payload['system'],'policy')
        self.assertEqual([b['tool_use_id'] for b in payload['messages'][-1]['content']],['a','b'])
        self.assertEqual(payload['tools'][0]['input_schema'],{'type':'object'})
        Handler.response = {'content':[{'type':'tool_use','id':'c','name':'read_file','input':{'path':'c'}}]}
        self.assertEqual(self.p.complete(messages,[])['tool_calls'][0]['arguments'],{'path':'c'})
    def test_errors_and_redirects_sanitized(self):
        for status in [302,401,500]:
            Handler.status=status
            with self.assertRaises(ProviderError) as cm: self.p.complete([{'role':'user','content':'hi'}],[])
            self.assertNotIn('secret',str(cm.exception))
    def test_invalid_response_and_history(self):
        Handler.response={'content':[{'type':'tool_use','id':'a','name':'x','input':[]}]}
        with self.assertRaises(ProviderError): self.p.complete([],[])
        with self.assertRaises(ProviderError): self.p.complete([{'role':'tool','tool_call_id':'missing','content':'x'}],[])

    def test_truncated_response_is_not_recorded_as_success(self):
        Handler.response={'content':[{'type':'text','text':'partial'}], 'stop_reason':'max_tokens'}
        with self.assertRaises(ProviderError):
            self.p.complete([{'role':'user','content':'hi'}], [])
