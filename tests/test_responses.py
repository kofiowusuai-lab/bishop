import io
import json
import unittest
from bishop_runtime.responses import ResponsesProvider
from bishop_runtime.provider import ProviderError

class ResponseTests(unittest.TestCase):
    def provider(self, events):
        provider=ResponsesProvider('https://api.openai.com/v1','test',lambda:'private')
        stream=io.BytesIO(b''.join(('data: '+json.dumps(e)+'\n\n').encode() for e in events))
        class Opener:
            def open(inner, request, timeout):
                inner.request=request
                return stream
        provider.opener=Opener()
        return provider

    def test_tool_bridge(self):
        provider=self.provider([{'type':'response.completed','response':{'output':[{'type':'function_call','call_id':'c1','name':'read_file','arguments':'{"path":"a"}'}]}}])
        result=provider.complete([{'role':'user','content':'read a'}],[{'type':'function','function':{'name':'read_file','parameters':{'type':'object'}}}])
        self.assertEqual(result['tool_calls'][0]['arguments'], {'path':'a'})
        payload=json.loads(provider.opener.request.data)
        self.assertFalse(payload['store'])
        self.assertTrue(payload['stream'])
        self.assertEqual(payload['tools'][0]['name'],'read_file')

    def test_unfinished_stream_fails(self):
        with self.assertRaises(ProviderError): self.provider([{'type':'response.output_text.delta','delta':'partial'}]).complete([],[])

    def test_failed_stream_fails(self):
        with self.assertRaises(ProviderError): self.provider([{'type':'response.failed','response':{'error':{'message':'private'}}}]).complete([],[])

    def test_no_other_remote_oauth_destination(self):
        with self.assertRaises(ValueError): ResponsesProvider('https://evil.example/v1','test',lambda:'private')

    def test_reasoning_and_function_ids_survive_tool_continuation(self):
        output=[{'type':'reasoning','id':'rs_1','summary':[],'encrypted_content':'opaque'}, {'type':'function_call','id':'fc_1','call_id':'call_1','name':'read_file','arguments':'{"path":"a"}'}]
        first=self.provider([{'type':'response.completed','response':{'output':output}}])
        reply=first.complete([{'role':'user','content':'read'}],[])
        second=self.provider([{'type':'response.completed','response':{'output':[{'type':'message','id':'msg_2','content':[{'type':'output_text','text':'done'}]}]}}])
        second.complete([{'role':'user','content':'read'}, {'role':'assistant','content':None,'tool_calls':[{'id':'call_1','function':{'name':'read_file','arguments':'{"path":"a"}'}}],'provider_state':reply['provider_state']}, {'role':'tool','tool_call_id':'call_1','content':'file text'}],[])
        payload=json.loads(second.opener.request.data)
        self.assertEqual(payload['include'],['reasoning.encrypted_content'])
        self.assertEqual(payload['input'][1:3],output)
        self.assertEqual(len(payload['input']),4)
        self.assertEqual(payload['input'][-1]['type'],'function_call_output')
        reply['provider_state']['output'][0]['encrypted_content']='changed'
        self.assertEqual(payload['input'][1]['encrypted_content'],'opaque')

    def test_production_loopback_oauth_destination_rejected(self):
        with self.assertRaises(ValueError): ResponsesProvider('http://127.0.0.1:9999/v1','test',lambda:'private')
