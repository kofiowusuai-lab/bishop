"""Bounded, public-internet-only HTTP reads. Remote text is untrusted data."""
from datetime import datetime, timezone
from html.parser import HTMLParser
import codecs
import http.client
import ipaddress
import re
import socket
import ssl
import time
import threading
from urllib.parse import urlsplit, urlunsplit, urljoin


class WebError(Exception):
    def __init__(self, code, message, retryable=False):
        self.code, self.message, self.retryable = code, message, bool(retryable)
        super().__init__(message)


def _clean(text):
    return ''.join(c for c in text if c in '\n\t' or (ord(c) >= 32 and ord(c) != 127 and not 0x80 <= ord(c) <= 0x9f and not 0x202a <= ord(c) <= 0x202e and not 0x2066 <= ord(c) <= 0x2069))


def _public(address):
    try:
        ip = ipaddress.ip_address(address)
        return ip.is_global and not ip.is_multicast and not ip.is_unspecified and not getattr(ip, 'ipv4_mapped', None) and '%' not in address
    except ValueError:
        return False


def _target(url):
    try:
        if not isinstance(url, str) or len(url) > 8192 or any(ord(c) <= 32 or ord(c) == 127 for c in url):
            raise ValueError()
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username is not None or parts.password is not None:
            raise ValueError()
        port = parts.port or (443 if parts.scheme == 'https' else 80)
        if port != (443 if parts.scheme == 'https' else 80) or '%' in parts.hostname:
            raise ValueError()
        host = parts.hostname.encode('idna').decode('ascii')
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not _public(host):
                raise ValueError()
        normalized = urlunsplit((parts.scheme, parts.netloc, parts.path or '/', parts.query, ''))
        return parts.scheme, host, port, (parts.path or '/') + ('?' + parts.query if parts.query else ''), normalized
    except (ValueError, UnicodeError):
        raise WebError('unsafe_url', 'Only public HTTP(S) URLs on standard ports are allowed.') from None


class _PinnedConnection(http.client.HTTPConnection):
    def __init__(self, host, port, record, secure, deadline):
        super().__init__(host, port, timeout=max(.001, deadline-time.monotonic()))
        self.record, self.secure, self.deadline = record, secure, deadline
        self._timer = None
        self._transport_socket = None
        self.expired = False

    def connect(self):
        family, socktype, proto, _, address = self.record
        sock = socket.socket(family, socktype, proto)
        try:
            sock.settimeout(max(.001, self.deadline-time.monotonic()))
            self.sock = sock
            self._transport_socket = sock
            self._timer = threading.Timer(max(.001, self.deadline-time.monotonic()), self._expire)
            self._timer.daemon = True
            self._timer.start()
            sock.connect(address)
            if self.secure:
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host, do_handshake_on_connect=False)
                self._transport_socket = sock
                self.sock = sock
                sock.settimeout(max(.001, self.deadline-time.monotonic()))
                sock.do_handshake()
            self.sock = sock
        except BaseException:
            self.finish()
            raise

    def _expire(self):
        self.expired = True
        sock = self._transport_socket
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    def finish(self):
        """End request ownership; HTTPConnection.close may run before body reads."""
        if self._timer is not None:
            self._timer.cancel()
        super().close()
        if self._transport_socket is not None:
            self._transport_socket.close()
            self._transport_socket = None


class _Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.in_title = False
        self.title = []
        self.text = []
        self.primary = {"main": [], "article": []}
        self.depth = {"main": 0, "article": 0}

    def _append(self, text):
        self.text.append(text)
        for name in self.primary:
            if self.depth[name]:
                self.primary[name].append(text)

    def handle_starttag(self, tag, attrs):
        if tag in self.depth:
            self.depth[tag] += 1
        if tag in ('script', 'style', 'form', 'noscript', 'template'):
            self.hidden += 1
        if tag == 'title':
            self.in_title = True
        if tag in ('p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'tr', 'section', 'article') and not self.hidden:
            self._append('\n')

    def handle_endtag(self, tag):
        if tag in self.depth:
            self.depth[tag] = max(0, self.depth[tag]-1)
        if tag in ('script', 'style', 'form', 'noscript', 'template'):
            self.hidden = max(0, self.hidden-1)
        if tag == 'title':
            self.in_title = False
        if tag in ('p', 'div', 'li', 'h1', 'h2', 'h3', 'tr') and not self.hidden:
            self._append('\n')

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)
        elif not self.hidden:
            self._append(data)


class WebClient:
    def __init__(self, timeout=12, max_bytes=2000000):
        if not isinstance(timeout, (int, float)) or not 0 < timeout <= 120 or not isinstance(max_bytes, int) or not 1 <= max_bytes <= 10000000:
            raise ValueError('Invalid web request limits')
        self.timeout, self.max_bytes = timeout, max_bytes

    def fetch(self, url, headers=None):
        deadline = time.monotonic() + self.timeout
        supplied = dict(headers or {})
        for key, value in supplied.items():
            if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9-]+', key) or not isinstance(value, str) or any(ord(c)<32 or ord(c)==127 for c in value) or key.lower() in ('host','cookie','connection','content-length','transfer-encoding'):
                raise WebError('invalid_headers', 'Invalid web request headers.')
        sensitive = any(k.lower() not in ('accept', 'user-agent', 'accept-language') for k in supplied)
        for redirect in range(4):
            scheme, host, port, path, normalized = _target(url)
            connection = None
            try:
                # OS resolver latency is not bounded by socket deadlines. The deadline
                # is checked immediately after resolution; no connection starts late.
                records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
                if not records or any(not _public(r[4][0]) for r in records):
                    raise WebError('unsafe_url', 'The host resolves to a non-public address.')
                if time.monotonic() >= deadline:
                    raise TimeoutError()
                connection = _PinnedConnection(host, port, records[0], scheme == 'https', deadline)
                request_headers = {'User-Agent':'Bishop/0.4 web-research', 'Accept':'text/html, text/plain, application/json', 'Accept-Encoding':'identity', **supplied}
                connection.request('GET', path, headers=request_headers)
                response = connection.getresponse()
                if response.status in (301,302,303,307,308):
                    location = response.getheader('Location')
                    if sensitive or not location or redirect == 3:
                        raise WebError('redirect_failed', 'The web redirect could not be followed safely.')
                    url = urljoin(normalized, location)
                    continue
                length = response.getheader('Content-Length')
                if length and (not length.isdigit() or int(length) > self.max_bytes):
                    raise WebError('response_too_large', 'The response exceeds the configured size limit.')
                if response.getheader('Content-Encoding', 'identity').lower() not in ('identity', ''):
                    raise WebError('unsupported_content', 'Compressed responses are not supported.')
                chunks, total = [], 0
                while True:
                    remaining = deadline-time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError()
                    if connection.sock is not None:
                        connection.sock.settimeout(remaining)
                    chunk = response.read1(min(16384, self.max_bytes-total+1))
                    if time.monotonic() >= deadline or getattr(connection, 'expired', False) is True:
                        raise TimeoutError()
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > self.max_bytes:
                        raise WebError('response_too_large', 'The response exceeds the configured size limit.')
                return {'url': normalized, 'status': response.status, 'content_type': response.getheader('Content-Type', ''), 'body': b''.join(chunks)}
            except WebError:
                raise
            except (TimeoutError, socket.timeout):
                raise WebError('web_timeout', 'The web request timed out.', True) from None
            except (OSError, http.client.HTTPException, ValueError):
                if connection is not None and getattr(connection, 'expired', False) is True:
                    raise WebError('web_timeout', 'The web request timed out.', True) from None
                raise WebError('web_unavailable', 'The web request could not be completed.', True) from None
            finally:
                if connection is not None:
                    getattr(connection, 'finish', connection.close)()

    def read(self, url, max_chars=12000):
        if not isinstance(max_chars, int) or not 1 <= max_chars <= 100000:
            raise ValueError('Invalid page text limit')
        result = self.fetch(url)
        if result['status'] >= 400:
            raise WebError('http_error', 'The source returned an HTTP error.', result['status'] >= 500 or result['status'] == 429)
        content_type = result['content_type']
        mime = content_type.split(';')[0].strip().lower()
        if not (mime.startswith('text/') or mime in ('application/json', 'application/xhtml+xml') or mime.endswith('+json')):
            raise WebError('unsupported_content', 'This source is not a supported text page.')
        charset = re.search(r'charset\s*=\s*[\"\']?([^\s;\"\']+)', content_type, re.I)
        encoding = charset.group(1) if charset else 'utf-8'
        try:
            canonical = codecs.lookup(encoding).name
            allowed = (canonical.startswith(('utf-', 'iso8859-', 'cp125')) or canonical in ('ascii', 'latin-1', 'shift_jis', 'euc_jp', 'euc_kr', 'gb2312', 'gbk', 'gb18030', 'big5', 'koi8-r', 'koi8-u', 'mac-roman'))
            if not allowed:
                encoding = 'utf-8'
            text = result['body'].decode(encoding, errors='replace')
        except (LookupError, UnicodeError):
            text = result['body'].decode('utf-8', errors='replace')
        title = ''
        if mime in ('text/html', 'application/xhtml+xml'):
            parser = _Visible()
            parser.feed(text)
            title = ' '.join(_clean(''.join(parser.title)).split())[:500]
            selected = parser.text
            for name in ('main', 'article'):
                if len(' '.join(''.join(parser.primary[name]).split())) > 80:
                    selected = parser.primary[name]
                    break
            text = '\n'.join(' '.join(line.split()) for line in ''.join(selected).splitlines() if line.strip())
        text = _clean(text).strip()
        if not text:
            raise WebError('empty_content', 'This source has no readable text; it may require JavaScript or access authorization.')
        return {'ok':True, 'url':result['url'], 'title':title, 'content':text[:max_chars], 'content_type':content_type, 'truncated':len(text)>max_chars, 'retrieved_at':datetime.now(timezone.utc).isoformat()}
