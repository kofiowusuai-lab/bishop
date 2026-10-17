import hashlib
import io
import json
import unittest
from bishop_runtime.provider import HTTPProvider
from bishop_runtime.anthropic import AnthropicProvider
from bishop_runtime.responses import APIResponsesProvider, ResponsesProvider

class Capture:
    def __init__(self, body): self.body=body
    def open(self, request, timeout):
        self.request=request
        return io.BytesIO(self.body)

class TransportV3Tests(unittest.TestCase):
    def test_api_responses_bridge_and_headers(self):
        p=APIResponsesProvider('https://opencode.ai/zen/v1','gpt-test','secret')
        p.set_session('private/session')
        output=[{'type':'function_call','call_id':'c1','name':'read_file','arguments':'{"path":"a"}'}]
        p.opener=Capture(('data: '+json.dumps({'type':'response.completed','response':{'output':output}})+'\n\n').encode())
        result=p.complete([{'role':'user','content':'hello'}],[])
        self.assertEqual(result['tool_calls'][0]['arguments'],{'path':'a'})
        self.assertEqual(result['provider_state']['kind'],'openai_responses')
        headers=dict((k.lower(),v) for k,v in p.opener.request.header_items())
        self.assertEqual(headers['authorization'],'Bearer secret')
        self.assertEqual(headers['x-opencode-session'],hashlib.sha256(b'private/session').hexdigest())
        self.assertTrue(headers['user-agent'].startswith('bishop-runtime/'))
        self.assertNotIn('private/session',str(headers))

    def test_headers_all_adapters_and_no_non_opencode_session(self):
        variants=[(HTTPProvider,{'choices':[{'message':{'content':'ok'}}]}),(AnthropicProvider,{'content':[{'type':'text','text':'ok'}]})]
        for cls,reply in variants:
            p=cls('https://opencode.ai/zen/v1','model','secret',extra_headers={'X-Test':'value'})
            p.set_session('one')
            p.opener=Capture(json.dumps(reply).encode())
            p.complete([{'role':'user','content':'hi'}],[])
            h=dict((k.lower(),v) for k,v in p.opener.request.header_items())
            self.assertIn('x-opencode-session',h)
            self.assertEqual(h['x-test'],'value')
        p=HTTPProvider('https://example.com/v1','m')
        p.set_session('one')
        self.assertNotIn('X-Opencode-Session',p.request_headers())

    def test_oauth_stays_public_only(self):
        for url in ['https://opencode.ai/zen/v1','http://127.0.0.1:1234/v1','https://api.openai.com.evil/v1']:
            with self.assertRaises(ValueError): ResponsesProvider(url,'m',lambda:'secret')

    def test_headers_cannot_override_credentials_or_inject(self):
        for headers in [{'Authorization':'other'},{'X-Test':'a\nb'},{'Bad Header':'x'},{'User-Agent':'Hermes'}]:
            with self.assertRaises(ValueError): HTTPProvider('https://example.com/v1','m',extra_headers=headers)

    def test_generic_continuation_preserves_tool_state(self):
        p=APIResponsesProvider('https://gateway.example/v1','m')
        output=[{'type':'reasoning','id':'r1','summary':[],'encrypted_content':'opaque'}, {'type':'function_call','id':'f1','call_id':'c1','name':'read_file','arguments':'{}'}]
        final=[{'type':'message','content':[{'type':'output_text','text':'done'}]}]
        p.opener=Capture(('data: '+json.dumps({'type':'response.completed','response':{'output':final}})+'\n\n').encode())
        result=p.complete([{'role':'assistant','provider_state':{'kind':'openai_responses','output':output}}, {'role':'tool','tool_call_id':'c1','content':'result'}],[])
        self.assertEqual(result['content'],'done')
        self.assertEqual(json.loads(p.opener.request.data)['input'][:2],output)
        self.assertIsNone(p.opener.request.get_header('Authorization'))

    def test_opencode_hostname_is_exact(self):
        for host in ['opencode.ai.evil.example','evil-opencode.ai','gateway.example']:
            p=APIResponsesProvider('https://'+host+'/v1','m')
            p.set_session('one')
            self.assertEqual(p.request_headers(),{})

    def test_generic_errors_do_not_echo_provider_or_key(self):
        from bishop_runtime.provider import ProviderError
        p=APIResponsesProvider('https://gateway.example/v1','m','private-key')
        class Failed:
            def open(self,request,timeout): raise OSError('private-key provider response')
        p.opener=Failed()
        with self.assertRaisesRegex(ProviderError,'model transport or protocol failure'):
            p.complete([],[])
