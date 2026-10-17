"""Bounded chat-completions transport, with no implicit retries or redirects."""
import copy
import ipaddress
import json
import math
import urllib.error
import urllib.parse
import urllib.request


class ProviderError(RuntimeError):
    """A sanitized transport or protocol failure."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _validate_reply(reply):
    if not isinstance(reply, dict):
        raise ProviderError('invalid model response')
    content = reply.get('content')
    calls = reply.get('tool_calls', [])
    if content is not None and (not isinstance(content, str) or len(content) > 100000):
        raise ProviderError('invalid model content')
    if not isinstance(calls, list) or len(calls) > 32:
        raise ProviderError('invalid model tool calls')
    seen = set()
    normalized = []
    for call in calls:
        if not isinstance(call, dict):
            raise ProviderError('invalid model tool call')
        call_id, name, args = call.get('id'), call.get('name'), call.get('arguments')
        if not isinstance(call_id, str) or not call_id or len(call_id) > 200 or call_id in seen:
            raise ProviderError('invalid model tool id')
        if not isinstance(name, str) or not name or len(name) > 100 or not isinstance(args, dict):
            raise ProviderError('invalid model tool arguments')
        seen.add(call_id)
        normalized.append({'id': call_id, 'name': name, 'arguments': args})
    if not normalized and (content is None or not content.strip()):
        raise ProviderError('empty model response')
    try:
        json.dumps({'content': content, 'tool_calls': normalized}, ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (UnicodeError, ValueError, TypeError):
        raise ProviderError('invalid model encoding') from None
    return copy.deepcopy({'content': content, 'tool_calls': normalized})


class ScriptedProvider:
    """Explicit offline responses for demos/tests; never used as a live fallback."""
    def __init__(self, responses):
        self.responses = copy.deepcopy(list(responses))
        self.requests = []

    def complete(self, messages, tools):
        self.requests.append(copy.deepcopy({'messages': messages, 'tools': tools}))
        if not self.responses:
            raise ProviderError('offline script exhausted')
        return _validate_reply(self.responses.pop(0))


class HTTPProvider:
    def __init__(self, base_url, model, api_key=None, timeout=30, max_tokens=1024):
        parsed = urllib.parse.urlsplit(base_url)
        local = parsed.hostname == 'localhost'
        try:
            local = local or ipaddress.ip_address(parsed.hostname or '').is_loopback
        except ValueError:
            pass
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or (parsed.scheme == 'http' and not local)):
            raise ValueError('provider URL requires HTTPS or loopback HTTP, without credentials or query')
        if not isinstance(model, str) or not model.strip() or len(model) > 200:
            raise ValueError('configure an explicit model')
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ValueError('timeout must be between zero and 120 seconds')
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 32768:
            raise ValueError('invalid max_tokens')
        if api_key is not None and (not isinstance(api_key, str) or '\n' in api_key or '\r' in api_key):
            raise ValueError('invalid provider credential')
        self.url = base_url.rstrip('/') + '/chat/completions'
        self.model, self.api_key = model, api_key
        self.timeout, self.max_tokens = timeout, max_tokens
        # Explicit provider routing; environment proxy credentials cannot be sent accidentally.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def complete(self, messages, tools):
        payload = {'model': self.model, 'messages': messages, 'stream': False, 'max_tokens': self.max_tokens}
        if tools:
            payload['tools'] = tools
            payload['tool_choice'] = 'auto'
        try:
            body = json.dumps(payload, allow_nan=False).encode()
        except (TypeError, ValueError) as exc:
            raise ProviderError('invalid model request') from None
        if len(body) > 2000000:
            raise ProviderError('model request too large')
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        if self.api_key:
            headers['Authorization'] = 'Bearer ' + self.api_key
        request = urllib.request.Request(self.url, data=body, headers=headers, method='POST')
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(2000001)
            if len(raw) > 2000000:
                raise ProviderError('model response too large')
            decoded = json.loads(raw)
            message = decoded['choices'][0]['message']
            calls = []
            for call in message.get('tool_calls', []):
                function = call['function']
                arguments = json.loads(function['arguments'])
                calls.append({'id': call['id'], 'name': function['name'], 'arguments': arguments})
            return _validate_reply({'content': message.get('content'), 'tool_calls': calls})
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            raise ProviderError('model HTTP error ' + str(code)) from None
        except ProviderError:
            raise
        except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
            raise ProviderError('model transport or protocol failure') from None
