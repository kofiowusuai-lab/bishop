import io
import socket
import unittest
from unittest.mock import patch

from bishop_runtime.web import WebClient, WebError


class WebTests(unittest.TestCase):
    def test_private_and_invalid_urls_rejected(self):
        for url in ('file:///etc/passwd', 'http://127.0.0.1', 'http://[::1]', 'http://169.254.169.254', 'https://user:pass@example.com', 'https://example.com:8443', 'http://[::ffff:8.8.8.8]', 'http://[fe80::1%25en0]'):
            with self.subTest(url=url), self.assertRaises(WebError):
                WebClient().fetch(url)

    def test_mixed_dns_rejected_before_connect(self):
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443)), (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]
        with patch('bishop_runtime.web.socket.getaddrinfo', return_value=records), patch('bishop_runtime.web.socket.socket') as dial:
            with self.assertRaises(WebError) as err:
                WebClient().fetch('https://example.com')
            self.assertEqual(err.exception.code, 'unsafe_url')
            dial.assert_not_called()

    def test_read_visible_html_and_bound_text(self):
        data = {'url': 'https://example.com/', 'status': 200, 'content_type': 'text/html; charset=utf-8', 'body': b'<html><title>Example &amp; Title</title><script>secret</script><style>hide</style><form>password</form><p>Hello world</p><p>Second</p></html>'}
        with patch.object(WebClient, 'fetch', return_value=data):
            result = WebClient().read('https://example.com/', max_chars=12)
        self.assertEqual(result['title'], 'Example & Title')
        self.assertEqual(result['content'], 'Hello world\n')
        self.assertTrue(result['truncated'])

    def test_binary_rejected(self):
        with patch.object(WebClient, 'fetch', return_value={'url':'https://example.com','status':200,'content_type':'application/pdf','body':b'%PDF'}):
            with self.assertRaises(WebError) as err:
                WebClient().read('https://example.com')
        self.assertEqual(err.exception.code, 'unsupported_content')

    def test_redirect_private_is_validated(self):
        class Response:
            status = 302
            def getheader(self, name, default=None):
                return 'http://127.0.0.1/admin' if name == 'Location' else default
        class Connection:
            def __init__(self, *args): pass
            def request(self, *args, **kwargs): pass
            def getresponse(self): return Response()
            def close(self): pass
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]
        with patch('bishop_runtime.web.socket.getaddrinfo', return_value=records), patch('bishop_runtime.web._PinnedConnection', Connection):
            with self.assertRaises(WebError) as err:
                WebClient().fetch('https://example.com')
        self.assertEqual(err.exception.code, 'unsafe_url')

    def test_tls_pins_ip_preserves_hostname(self):
        from bishop_runtime.web import _PinnedConnection
        import time
        from unittest.mock import Mock
        raw = Mock()
        context = Mock()
        record = (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))
        with patch('bishop_runtime.web.socket.socket', return_value=raw), patch('bishop_runtime.web.ssl.create_default_context', return_value=context):
            connection = _PinnedConnection('example.com', 443, record, True, time.monotonic()+3)
            connection.connect()
            raw.connect.assert_called_once_with(('8.8.8.8', 443))
            context.wrap_socket.assert_called_once_with(raw, server_hostname='example.com', do_handshake_on_connect=False)
            connection.finish()

    def test_sensitive_header_redirect_not_forwarded(self):
        class Response:
            status = 302
            def getheader(self, name, default=None): return 'https://other.example/'
        from unittest.mock import Mock
        connection = Mock()
        connection.getresponse.return_value = Response()
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]
        with patch('bishop_runtime.web.socket.getaddrinfo', return_value=records), patch('bishop_runtime.web._PinnedConnection', return_value=connection):
            with self.assertRaises(WebError) as err:
                WebClient().fetch('https://example.com', {'X-Subscription-Token':'private'})
        self.assertEqual(err.exception.code, 'redirect_failed')

    def test_size_limit_without_content_length(self):
        from unittest.mock import Mock
        response = Mock(status=200)
        response.getheader.side_effect = lambda name, default=None: default
        response.read1.side_effect = [b'abcdef', b'']
        connection = Mock()
        connection.getresponse.return_value = response
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]
        with patch('bishop_runtime.web.socket.getaddrinfo', return_value=records), patch('bishop_runtime.web._PinnedConnection', return_value=connection):
            with self.assertRaises(WebError) as err:
                WebClient(max_bytes=5).fetch('https://example.com')
        self.assertEqual(err.exception.code, 'response_too_large')

    def test_connection_deadline_installs_watchdog(self):
        from bishop_runtime.web import _PinnedConnection
        import time
        from unittest.mock import Mock
        raw = Mock()
        record = (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8',80))
        with patch('bishop_runtime.web.socket.socket', return_value=raw), patch('bishop_runtime.web.threading.Timer') as timer:
            connection = _PinnedConnection('example.com',80,record,False,time.monotonic()+1)
            connection.connect()
            timer.return_value.start.assert_called_once()
            connection.finish()
            timer.return_value.cancel.assert_called_once()

    def test_total_deadline_stops_dripping_body_after_connection_close_header(self):
        import threading
        import time
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Type','text/plain')
                self.send_header('Connection','close')
                self.end_headers()
                for _ in range(20):
                    try:
                        self.wfile.write(b'x')
                        self.wfile.flush()
                    except OSError:
                        break
                    time.sleep(.04)
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        public_record = (socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',80))
        real_socket = socket.socket
        def local_dial(*args, **kwargs):
            sock = real_socket(*args, **kwargs)
            class Dial:
                def connect(self, ignored): return sock.connect(server.server_address)
                def __getattr__(self, name): return getattr(sock,name)
            return Dial()
        started = time.monotonic()
        try:
            with patch('bishop_runtime.web.socket.getaddrinfo',return_value=[public_record]), patch('bishop_runtime.web.socket.socket',side_effect=local_dial):
                with self.assertRaises(WebError) as err:
                    WebClient(timeout=.15).fetch('http://example.com')
            self.assertEqual(err.exception.code, 'web_timeout')
            self.assertLess(time.monotonic()-started,.6)
        finally:
            server.shutdown()
            server.server_close()

    def test_transform_codec_cannot_escape_page_reader(self):
        with patch.object(WebClient, 'fetch', return_value={'url':'https://example.com','status':200,'content_type':'text/plain; charset=idna','body':b'hello'}):
            self.assertEqual(WebClient().read('https://example.com')['content'],'hello')

    def test_watchdog_retains_socket_after_http_connection_detaches(self):
        from bishop_runtime.web import _PinnedConnection
        from unittest.mock import Mock
        import time
        raw = Mock()
        record = (socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',80))
        with patch('bishop_runtime.web.socket.socket',return_value=raw), patch('bishop_runtime.web.threading.Timer'):
            connection = _PinnedConnection('example.com',80,record,False,time.monotonic()+1)
            connection.connect()
            connection.sock = None  # HTTPConnection detaches when response says close.
            connection._expire()
            raw.shutdown.assert_called_once_with(socket.SHUT_RDWR)
            connection.finish()

    def test_deadline_stops_dripping_chunk_header_with_connection_close(self):
        import threading
        import time
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Type','text/plain')
                self.send_header('Connection','close')
                self.send_header('Transfer-Encoding','chunked')
                self.end_headers()
                for byte in b'00000000000000000001\r\nx\r\n0\r\n\r\n':
                    try:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                    except OSError:
                        break
                    time.sleep(.04)
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        real_socket = socket.socket
        def local_dial(*args, **kwargs):
            sock = real_socket(*args, **kwargs)
            class Dial:
                def connect(self, ignored): return sock.connect(server.server_address)
                def __getattr__(self,name): return getattr(sock,name)
            return Dial()
        record=(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',80))
        started=time.monotonic()
        try:
            with patch('bishop_runtime.web.socket.getaddrinfo',return_value=[record]), patch('bishop_runtime.web.socket.socket',side_effect=local_dial):
                with self.assertRaises(WebError) as err:
                    WebClient(timeout=.15).fetch('http://example.com')
            self.assertEqual(err.exception.code,'web_timeout')
            self.assertLess(time.monotonic()-started,.4)
        finally:
            server.shutdown()
            server.server_close()

    def test_substantive_article_preferred_over_large_navigation(self):
        article='Verified research findings and primary source evidence. '*5
        body=('<title>Research</title><nav>'+('Navigation '*2000)+'</nav><main><article><p>'+article+'</p></article></main><footer>footer links</footer>').encode()
        with patch.object(WebClient,'fetch',return_value={'url':'https://example.com','status':200,'content_type':'text/html','body':body}):
            result=WebClient().read('https://example.com',max_chars=200)
        self.assertTrue(result['content'].startswith('Verified research'))
        self.assertNotIn('Navigation',result['content'])
        self.assertEqual(result['title'],'Research')
        self.assertEqual(result['url'],'https://example.com')

    def test_empty_script_only_page_has_controlled_error(self):
        with patch.object(WebClient,'fetch',return_value={'url':'https://example.com','status':200,'content_type':'text/html','body':b'<title>App</title><script>app()</script>'}):
            with self.assertRaises(WebError) as err:
                WebClient().read('https://example.com')
        self.assertEqual(err.exception.code,'empty_content')

    def test_main_preferred_over_unrelated_sidebar_article(self):
        body=('<title>Official requirements</title><main><p>'+('Primary evidence requirements. '*30)+'</p></main><aside><article>'+('Related story teaser. '*8)+'</article></aside>').encode()
        with patch.object(WebClient,'fetch',return_value={'url':'https://example.com','status':200,'content_type':'text/html','body':body}):
            result=WebClient().read('https://example.com')
        self.assertIn('Primary evidence requirements.',result['content'])
        self.assertNotIn('Related story teaser.',result['content'])
