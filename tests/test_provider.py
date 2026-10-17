import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bishop_runtime.provider import HTTPProvider, ProviderError, ScriptedProvider


class Handler(BaseHTTPRequestHandler):
    response = {"choices": [{"message": {"content": "hello"}}]}
    status = 200
    received = None

    def log_message(self, *args):
        pass

    def do_POST(self):
        type(self).received = (self.path, json.loads(self.rfile.read(int(self.headers['Content-Length']))))
        self.send_response(type(self).status)
        if type(self).status == 302:
            self.send_header('Location', 'http://example.invalid/secret')
        self.end_headers()
        self.wfile.write(json.dumps(type(self).response).encode())


class ProviderTests(unittest.TestCase):
    def setUp(self):
        Handler.status = 200
        Handler.response = {"choices": [{"message": {"content": "hello"}}]}
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.provider = HTTPProvider(f'http://127.0.0.1:{self.server.server_port}/v1', 'test', api_key='secret')

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_wire_and_text(self):
        self.assertEqual(self.provider.complete([{'role': 'user', 'content': 'hi'}], []), {'content': 'hello', 'tool_calls': []})
        path, payload = Handler.received
        self.assertEqual(path, '/v1/chat/completions')
        self.assertEqual(payload['model'], 'test')
        self.assertFalse(payload['stream'])

    def test_tool_response(self):
        Handler.response = {'choices': [{'message': {'content': None, 'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {'name': 'read_file', 'arguments': '{"path":"a.txt"}'}}]}}]}
        reply = self.provider.complete([], [])
        self.assertEqual(reply['tool_calls'][0]['arguments'], {'path': 'a.txt'})

    def test_malformed_and_duplicate_calls(self):
        for arguments in ['not json', '[]']:
            Handler.response = {'choices': [{'message': {'tool_calls': [{'id': 'c', 'function': {'name': 'x', 'arguments': arguments}}]}}]}
            with self.assertRaises(ProviderError):
                self.provider.complete([], [])
        Handler.response = {'choices': []}
        with self.assertRaises(ProviderError):
            self.provider.complete([], [])

    def test_redirect_and_error_are_sanitized(self):
        for status in [302, 401, 500]:
            Handler.status = status
            Handler.response = {'error': 'secret sensitive body'}
            with self.assertRaises(ProviderError) as caught:
                self.provider.complete([], [])
            self.assertNotIn('secret', str(caught.exception))
            self.assertNotIn('http', str(caught.exception))

    def test_invalid_unicode_is_rejected(self):
        Handler.response = {'choices': [{'message': {'content': '\ud800'}}]}
        with self.assertRaises(ProviderError):
            self.provider.complete([], [])

    def test_url_and_model(self):
        for url in ['https://user:secret@example.com/v1', 'ftp://localhost/v1', 'http://remote.example/v1', 'https://example.com/v1?key=secret']:
            with self.assertRaises(ValueError):
                HTTPProvider(url, 'test')
        with self.assertRaises(ValueError):
            HTTPProvider('http://localhost:11434/v1', '')

    def test_scripted_is_detached_and_exhaustion_fails(self):
        provider = ScriptedProvider([{'content': 'offline', 'tool_calls': []}])
        self.assertEqual(provider.complete([], [])['content'], 'offline')
        with self.assertRaises(ProviderError):
            provider.complete([], [])


if __name__ == '__main__':
    unittest.main()
