import json
from pathlib import Path
import tempfile
import unittest

from bishop_runtime.cli import _runtime
from bishop_runtime.config import init_home, load_config
from bishop_runtime.provider import ScriptedProvider
from bishop_runtime.telegram import TelegramService


class Client:
    def __init__(self):
        self.updates = []
        self.sent = []
    def get_updates(self, offset, timeout=25):
        updates, self.updates = self.updates, []
        return updates
    def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))
        return {'message_id': len(self.sent)}
    def put(self, ident, text, user=42):
        self.updates = [{'update_id': ident, 'message': {'from': {'id': user}, 'chat': {'id': user, 'type': 'private'}, 'text': text}}]


class IntegrationTests(unittest.TestCase):
    def test_real_runtime_through_telegram_approval_and_audit_privacy(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            init_home(home)
            provider = ScriptedProvider([
                {'content': None, 'tool_calls': [{'id': 'remember', 'name': 'memory_remember', 'arguments': {'text': 'private synthetic project fact'}}]},
                {'content': 'Remembered with approval.', 'tool_calls': []},
            ])
            runtime, memory = _runtime(home, load_config(home), provider)
            client = Client()
            service = TelegramService(home, client, runtime, [42, 43])
            try:
                client.put(1, 'Remember my project fact')
                service.poll_once()
                run = runtime.active('telegram:42', actor='telegram:42')
                self.assertEqual(run['status'], 'awaiting_approval')
                self.assertEqual(memory.search('telegram:42', ''), [])
                client.put(2, f"/approve {run['id']} remember", user=43)
                service.poll_once()
                self.assertFalse(runtime.status(run['id'])['pending'][0]['approved'])
                client.put(3, f"/approve {run['id']} remember")
                service.poll_once()
                client.put(4, f"/resume {run['id']}")
                service.poll_once()
                self.assertEqual(runtime.status(run['id'])['status'], 'completed')
                self.assertEqual(len(memory.search('telegram:42', 'project')), 1)
                self.assertEqual(memory.search('telegram:43', ''), [])
                serialized = json.dumps(runtime.audit.pending_events())
                self.assertNotIn('private synthetic', serialized)
                self.assertNotIn('Remember my project', serialized)
                self.assertNotIn('Remembered with approval', serialized)
                self.assertIn('step_completed', serialized)
                self.assertEqual(len(provider.requests), 2)
            finally:
                service.close(); runtime.close(); memory.close()

class HTTPRuntimeTests(unittest.TestCase):
    def test_http_model_receives_real_tool_results(self):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from bishop_runtime.provider import HTTPProvider

        requests = []
        class Model(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append(payload)
                message = {'content': 'Read the workspace brief.'} if len(requests) > 1 else {
                    'content': None, 'tool_calls': [{'id': 'http-read', 'type': 'function',
                        'function': {'name': 'read_file', 'arguments': '{"path":"brief.txt"}'}}]}
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps({'choices': [{'message': message}]}).encode())
        server = ThreadingHTTPServer(('127.0.0.1', 0), Model)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as root:
                home = Path(root); init_home(home)
                (home / 'workspace' / 'brief.txt').write_text('Real tool content')
                provider = HTTPProvider(f'http://127.0.0.1:{server.server_port}/v1', 'fake-test-model')
                runtime, memory = _runtime(home, load_config(home), provider)
                try:
                    run = runtime.run('http-test', 'Read brief.txt')
                    self.assertEqual(run['status'], 'completed')
                    self.assertEqual(len(requests), 2)
                    messages = requests[1]['messages']
                    self.assertEqual(messages[-1]['role'], 'tool')
                    self.assertEqual(messages[-1]['tool_call_id'], 'http-read')
                    self.assertIn('Real tool content', messages[-1]['content'])
                    self.assertEqual(json.loads(messages[-2]['tool_calls'][0]['function']['arguments']), {'path': 'brief.txt'})
                finally:
                    runtime.close(); memory.close()
        finally:
            server.shutdown(); server.server_close(); thread.join()
