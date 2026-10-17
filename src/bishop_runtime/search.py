"""Bounded, source-preserving public search; never bypass provider challenges."""
from datetime import datetime, timezone
from html.parser import HTMLParser
import ipaddress
import json
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from .web import WebClient, WebError


def _text(value, maximum):
    if not isinstance(value, str):
        return ''
    return re.sub(r'\s+', ' ', ''.join(c for c in value if c.isprintable() or c.isspace())).strip()[:maximum]


def _source_url(value):
    if not isinstance(value, str) or len(value) > 8192:
        return None
    value = urljoin('https://lite.duckduckgo.com/', value)
    try:
        parsed = urlsplit(value)
        if parsed.hostname in ('duckduckgo.com', 'www.duckduckgo.com', 'lite.duckduckgo.com'):
            if parsed.path != '/l/':
                return None
            value = parse_qs(parsed.query).get('uddg', [''])[0]
            parsed = urlsplit(value)
        host = parsed.hostname
        if (parsed.scheme not in ('http', 'https') or not host or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 80, 443)
                or any(ord(c) < 33 for c in value) or '\\' in value):
            return None
        normalized = host.rstrip('.').lower()
        if normalized == 'localhost' or normalized.endswith(('.localhost', '.local', '.internal')) or '.' not in normalized and ':' not in normalized:
            return None
        try:
            if not ipaddress.ip_address(normalized).is_global:
                return None
        except ValueError:
            pass
        return value
    except (ValueError, UnicodeError):
        return None


class _LiteParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self.current = None
        self.capture = None
        self.parts = []
        self.no_results = False
        self.challenge = False
        self.in_row = False
        self.row_ad = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get('class', '').split()
        if attrs.get('id') == 'challenge-form' or any('anomaly' in c for c in classes):
            self.challenge = True
        if 'no-results' in classes or 'no-results__message' in classes:
            self.no_results = True
        if tag == 'tr':
            self.in_row = True
            self.row_ad = False
        if 'badge--ad' in classes or 'result-sponsored' in classes:
            self.row_ad = True
        if tag == 'a' and 'result-link' in classes:
            self.current = {'title': '', 'url': _source_url(attrs.get('href')), 'snippet': ''}
            self.results.append(self.current)
            self.capture, self.parts = 'title', []
        elif tag == 'td' and 'result-snippet' in classes and self.current is not None:
            self.capture, self.parts = 'snippet', []

    def handle_endtag(self, tag):
        if self.capture and ((self.capture == 'title' and tag == 'a') or (self.capture == 'snippet' and tag == 'td')):
            self.current[self.capture] = _text(''.join(self.parts), 300 if self.capture == 'title' else 1200)
            self.capture = None
        if tag == 'tr':
            if self.row_ad and self.current:
                self.current['url'] = None
            self.in_row = False

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)


class WebSearch:
    def __init__(self, client=None, provider='duckduckgo', api_key=None):
        self.client = client if client is not None else WebClient()
        self.provider = provider
        self.api_key = api_key

    def search(self, query, limit=5):
        if not isinstance(query, str) or not query.strip() or len(query) > 1000 or any(ord(c) < 32 for c in query):
            raise WebError('search_invalid_query', 'Search requires a nonempty query of at most 1000 characters.')
        if type(limit) is not int or not 1 <= limit <= 10:
            raise WebError('search_invalid_limit', 'Search limit must be between 1 and 10.')
        query = query.strip()
        if self.provider == 'duckduckgo':
            response = self.client.fetch('https://lite.duckduckgo.com/lite/?' + urlencode({'q': query}))
            body = response['body'].decode('utf-8', errors='replace')
            parser = _LiteParser()
            parser.feed(body)
            if response['status'] in (202, 403, 429) or parser.challenge:
                raise WebError('search_challenged', 'The search provider requires a human challenge or is limiting requests.', retryable=True)
            if response['status'] != 200:
                raise WebError('search_unavailable', 'The search provider is unavailable.', retryable=True)
            if parser.no_results:
                raise WebError('search_no_results', 'The search provider found no results.')
            if not parser.results:
                raise WebError('search_invalid_response', 'The search provider returned unrecognized result markup.')
            candidates = parser.results
        elif self.provider == 'brave':
            if not isinstance(self.api_key, str) or not self.api_key or any(ord(c) < 32 or ord(c) > 126 for c in self.api_key):
                raise WebError('search_missing_key', 'Brave search requires an operator-configured API key.')
            response = self.client.fetch('https://api.search.brave.com/res/v1/web/search?' + urlencode({'q': query, 'count': limit}), headers={'Accept': 'application/json', 'X-Subscription-Token': self.api_key})
            if response['status'] != 200:
                raise WebError('search_unavailable', 'The configured search provider rejected the request.', retryable=response['status'] in (429, 500, 502, 503, 504))
            try:
                data = json.loads(response['body'])
                raw = data.get('web', {}).get('results', [])
                if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
                    raise ValueError()
                candidates = [{'title': _text(item.get('title'), 300), 'url': _source_url(item.get('url')), 'snippet': _text(item.get('description'), 1200)} for item in raw[:100]]
            except (ValueError, TypeError, AttributeError):
                raise WebError('search_invalid_response', 'The search provider returned invalid result data.') from None
        else:
            raise WebError('search_invalid_provider', 'Choose a supported search provider.')
        results, seen = [], set()
        for candidate in candidates:
            if not candidate['url'] or not candidate['title'] or candidate['url'] in seen:
                continue
            seen.add(candidate['url'])
            results.append(candidate)
            if len(results) >= limit:
                break
        if not results:
            raise WebError('search_no_results', 'No supported public search results were returned.')
        return {'ok': True, 'provider': self.provider, 'query': query, 'results': results, 'retrieved_at': datetime.now(timezone.utc).isoformat()}
