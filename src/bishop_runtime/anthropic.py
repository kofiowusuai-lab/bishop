"""Native Anthropic Messages adapter for Bishop's provider-neutral tool loop."""
import json
import urllib.error
import urllib.request
from .provider import HTTPProvider, ProviderError, _validate_reply


class AnthropicProvider(HTTPProvider):
    def __init__(self, base_url, model, api_key=None, timeout=30, max_tokens=1024, extra_headers=None):
        super().__init__(base_url, model, api_key, timeout, max_tokens, extra_headers)
        self.url = base_url.rstrip('/') + '/messages'

    def _payload(self, messages, tools):
        system, translated, pending = [], [], set()
        for message in messages:
            role = message['role']
            if role == 'system':
                if not isinstance(message.get('content'), str): raise ValueError()
                system.append(message['content']); continue
            if role == 'tool':
                call_id = message['tool_call_id']
                if call_id not in pending: raise ValueError()
                pending.remove(call_id)
                content = [{'type':'tool_result','tool_use_id':call_id,'content':message['content']}]
                role = 'user'
            elif role in ('user', 'assistant'):
                if pending: raise ValueError()
                content = []
                if message.get('content'):
                    if not isinstance(message['content'],str): raise ValueError()
                    content.append({'type':'text','text':message['content']})
                for call in message.get('tool_calls', []):
                    if role != 'assistant' or call['id'] in pending: raise ValueError()
                    args = json.loads(call['function']['arguments'])
                    if not isinstance(args,dict): raise ValueError()
                    pending.add(call['id'])
                    content.append({'type':'tool_use','id':call['id'],'name':call['function']['name'],'input':args})
                if not content: raise ValueError()
            else: raise ValueError()
            if translated and translated[-1]['role'] == role:
                translated[-1]['content'].extend(content)
            else:
                translated.append({'role':role,'content':content})
        if pending: raise ValueError()
        payload = {'model':self.model,'max_tokens':self.max_tokens,'messages':translated,'stream':False}
        if system: payload['system'] = '\n\n'.join(system)
        if tools:
            payload['tools'] = [{'name':t['function']['name'], 'description':t['function'].get('description',''), 'input_schema':t['function']['parameters']} for t in tools]
        return payload

    def complete(self, messages, tools):
        try:
            body = json.dumps(self._payload(messages,tools), allow_nan=False).encode()
        except (TypeError, ValueError, KeyError, AttributeError, UnicodeError):
            raise ProviderError('invalid model request') from None
        if len(body)>2000000: raise ProviderError('model request too large')
        headers = {**self.request_headers(), 'Content-Type':'application/json','Accept':'application/json','anthropic-version':'2023-06-01'}
        if self.api_key: headers['x-api-key'] = self.api_key
        request = urllib.request.Request(self.url,data=body,headers=headers,method='POST')
        try:
            with self.opener.open(request,timeout=self.timeout) as response:
                raw=response.read(2000001)
            if len(raw)>2000000: raise ProviderError('model response too large')
            decoded=json.loads(raw)
            blocks=decoded['content']
            if not isinstance(blocks,list): raise ValueError()
            texts, calls=[], []
            for block in blocks:
                if block['type']=='text':
                    if not isinstance(block['text'],str): raise ValueError()
                    texts.append(block['text'])
                elif block['type']=='tool_use':
                    calls.append({'id':block['id'],'name':block['name'],'arguments':block['input']})
                else:
                    raise ProviderError('unsupported model response block')
            if decoded.get('stop_reason') in ('max_tokens','pause_turn'):
                raise ProviderError('model response incomplete')
            return _validate_reply({'content':'\n'.join(texts) if texts else None,'tool_calls':calls})
        except urllib.error.HTTPError as exc:
            code=exc.code; exc.close()
            raise ProviderError('model HTTP error '+str(code)) from None
        except ProviderError: raise
        except (OSError,ValueError,TypeError,KeyError,IndexError,AttributeError):
            raise ProviderError('model transport or protocol failure') from None
