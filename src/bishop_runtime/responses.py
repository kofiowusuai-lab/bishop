"""Streaming public Responses transport for Bishop's independent tool loop."""
import copy
import json
import time
import urllib.error
import urllib.request
from .provider import HTTPProvider, ProviderError, _validate_reply

class ResponsesProvider(HTTPProvider):
    def __init__(self, base_url, model, token_source, timeout=30, max_tokens=1024):
        super().__init__(base_url, model, timeout=timeout, max_tokens=max_tokens)
        self.url = base_url.rstrip('/') + '/responses'
        self.token_source = token_source
        # OAuth tokens must never be routed to configurable remote providers.
        if self.url != 'https://api.openai.com/v1/responses':
            raise ValueError('ChatGPT OAuth requires the public OpenAI endpoint')

    @staticmethod
    def _state_output(output):
        if not isinstance(output, list) or len(output) > 128:
            raise ProviderError('invalid Responses continuation state')
        try:
            encoded = json.dumps(output, allow_nan=False).encode()
            if len(encoded) > 1000000:
                raise ValueError()
            for item in output:
                if not isinstance(item, dict) or item.get('type') not in ('message', 'function_call', 'reasoning'):
                    raise ValueError()
                if 'id' in item and not isinstance(item['id'], str):
                    raise ValueError()
                if item['type'] == 'reasoning':
                    if 'encrypted_content' in item and not isinstance(item['encrypted_content'], str):
                        raise ValueError()
                    if not isinstance(item.get('summary', []), list):
                        raise ValueError()
                elif item['type'] == 'function_call':
                    if not all(isinstance(item.get(k), str) for k in ('call_id', 'name', 'arguments')):
                        raise ValueError()
                    if not isinstance(json.loads(item['arguments']), dict):
                        raise ValueError()
                elif not isinstance(item.get('content'), list):
                    raise ValueError()
            return copy.deepcopy(output)
        except (ValueError, TypeError, UnicodeError):
            raise ProviderError('invalid Responses continuation state') from None

    def complete(self, messages, tools):
        items = []
        for message in messages:
            role = message['role']
            if role == 'tool':
                items.append({'type': 'function_call_output', 'call_id': message['tool_call_id'], 'output': message['content']})
            else:
                state = message.get('provider_state')
                if role == 'assistant' and isinstance(state, dict) and state.get('kind') == 'openai_responses':
                    items.extend(self._state_output(state.get('output')))
                    continue
                if message.get('content'):
                    items.append({'role': role, 'content': message['content']})
                for call in message.get('tool_calls', []):
                    items.append({'type': 'function_call', 'call_id': call['id'], 'name': call['function']['name'], 'arguments': call['function']['arguments']})
        payload = {'model': self.model, 'input': items, 'store': False, 'stream': True, 'max_output_tokens': self.max_tokens, 'include': ['reasoning.encrypted_content']}
        if tools:
            payload['tools'] = [{'type': 'function', **tool['function']} for tool in tools]
        body = json.dumps(payload, allow_nan=False).encode()
        if len(body) > 2000000:
            raise ProviderError('model request too large')
        token = self.token_source()
        if not isinstance(token, str) or not token or '\r' in token or '\n' in token:
            raise ProviderError('invalid ChatGPT credential')
        request = urllib.request.Request(self.url, data=body, headers={'Content-Type': 'application/json', 'Accept': 'text/event-stream', 'Authorization': 'Bearer ' + token})
        try:
            completed = None
            with self.opener.open(request, timeout=self.timeout) as response:
                total = 0
                data, buffer = [], b''
                deadline = time.monotonic() + self.timeout
                while True:
                    if time.monotonic() >= deadline:
                        raise ProviderError('ChatGPT stream exceeded total time limit')
                    chunk = response.read1(65536)
                    total += len(chunk)
                    if total > 2000000:
                        raise ProviderError('model response too large')
                    if not chunk:
                        break
                    buffer += chunk
                    while b'\n' in buffer:
                        line, buffer = buffer.split(b'\n', 1)
                        line = line.rstrip(b'\r')
                        if not line:
                            if data:
                                event = json.loads('\n'.join(data))
                                kind = event.get('type')
                                if kind in ('response.failed', 'response.incomplete', 'error'):
                                    raise ProviderError('ChatGPT response failed or was incomplete')
                                if kind == 'response.completed':
                                    completed = event['response']
                                data = []
                        elif line.startswith(b'data:'):
                            value = line[5:].decode().strip()
                            if value != '[DONE]':
                                data.append(value)
                    if completed is not None:
                        break
            if completed is None:
                raise ProviderError('ChatGPT stream ended without completion')
            text, calls = [], []
            output = self._state_output(completed['output'])
            for item in output:
                if item.get('type') == 'message':
                    text.extend(part['text'] for part in item.get('content', []) if part.get('type') == 'output_text')
                elif item.get('type') == 'function_call':
                    calls.append({'id': item['call_id'], 'name': item['name'], 'arguments': json.loads(item['arguments'])})
            result = _validate_reply({'content': ''.join(text) or None, 'tool_calls': calls})
            result['provider_state'] = {'kind': 'openai_responses', 'output': output}
            return result
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            raise ProviderError('ChatGPT HTTP error ' + str(status)) from None
        except ProviderError:
            raise
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            raise ProviderError('ChatGPT transport or protocol failure') from None
