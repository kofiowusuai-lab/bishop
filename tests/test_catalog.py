import unittest
from unittest.mock import patch
from bishop_runtime.catalog import discover_models, CatalogError, _routes

class CatalogTests(unittest.TestCase):
    def get(self, provider, rows, **kw):
        with patch('bishop_runtime.catalog._get', return_value={'data':rows}):
            return discover_models(provider, 'https://example.com/v1', **kw)
    def test_local_and_custom(self):
        for provider in ('ollama','lmstudio','custom'):
            self.assertEqual(self.get(provider,[{'id':'local-model'}])[0]['id'],'local-model')
    def test_openrouter_tools_text(self):
        rows=[{'id':'yes','supported_parameters':['tools'],'architecture':{'output_modalities':['text']}}, {'id':'no','supported_parameters':[]}, {'id':'image','supported_parameters':['tools'],'architecture':{'output_modalities':['image']}}, {'id':'mixed','supported_parameters':['tools'],'architecture':{'output_modalities':['text','image']}}, {'id':'voice','supported_parameters':['tools'],'architecture':{'output_modalities':['text','audio']}}]
        self.assertEqual([x['id'] for x in self.get('openrouter',rows)],['yes'])
    def test_openai_families(self):
        result=self.get('openai',[{'id':x} for x in ['gpt-6-sol','o3','text-embedding-3-large','gpt-image-1','gpt-4o-audio-preview','whisper-1','gpt-3.5-turbo-instruct']])
        self.assertEqual([x['id'] for x in result],['gpt-6-sol','o3'])
    def test_anthropic_headers_and_pagination(self):
        with patch('bishop_runtime.catalog._get',side_effect=[{'data':[{'id':'claude-a','display_name':'Claude A'}],'has_more':True,'last_id':'claude-a'},{'data':[{'id':'claude-b'}],'has_more':False}]) as get:
            result=discover_models('anthropic','https://api.anthropic.com/v1',kind='anthropic',api_key='secret')
        self.assertEqual(len(result),2)
        self.assertEqual(get.call_args_list[0].args[1]['x-api-key'],'secret')
        self.assertIn('after_id=claude-a',get.call_args_list[1].args[0])
    def test_opencode_routes_and_free(self):
        html='<table><tr><td>Claude</td><td>claude-new</td><td><code>https://opencode.ai/inference/anthropic/v1/messages</code></td></tr><tr><td>Free</td><td>beam-free</td><td>https://opencode.ai/inference/openai/v1/chat/completions</td></tr><tr><td>GPT</td><td>gpt-new</td><td>https://opencode.ai/inference/openai/v1/responses</td></tr><tr><td>Gemini</td><td>gemini-new</td><td>https://opencode.ai/inference/google/v1beta/models/gemini-new</td></tr></table>'
        data={'data':[{'id':x} for x in ['claude-new','beam-free','gpt-new','gemini-new','unknown']]}
        for provider in ('opencode','opencode-claude','opencode-go','opencode-free'):
            with patch('bishop_runtime.catalog._get',side_effect=[data,html]):
                result=discover_models(provider,'https://opencode.ai/inference/openai/v1')
            expected=['beam-free'] if provider=='opencode-free' else ['claude-new'] if provider=='opencode-claude' else ['claude-new','beam-free','gpt-new']
            self.assertEqual([x['id'] for x in result],expected)
        self.assertEqual(_routes(html)['gpt-new']['kind'],'responses')
    def test_malformed_catalog(self):
        with patch('bishop_runtime.catalog._get',return_value={'data':'bad'}):
            with self.assertRaises(CatalogError): discover_models('custom','https://example.com/v1')
    def test_route_host_cannot_redirect_credentials(self):
        self.assertEqual(_routes('<tr><td>X</td><td>x</td><td>https://evil.test/inference/openai/v1/responses</td></tr>'),{})

class TransportTests(unittest.TestCase):
    def test_errors_never_include_body_url_or_key(self):
        import urllib.error
        from bishop_runtime.catalog import _get
        with patch('bishop_runtime.catalog.urllib.request.build_opener') as factory:
            factory.return_value.open.side_effect=urllib.error.URLError('secret-token https://private.test')
            with self.assertRaises(CatalogError) as error:
                _get('https://example.com/models',{'Authorization':'Bearer secret-token'},1)
        self.assertNotIn('secret-token',str(error.exception))
        self.assertNotIn('private.test',str(error.exception))
    def test_unsafe_cleartext_endpoint_rejected(self):
        from bishop_runtime.catalog import _get
        with self.assertRaises(CatalogError): _get('http://example.com/models',{},1)
    def test_redirect_handler_refuses_follow(self):
        from bishop_runtime.catalog import _NoRedirect
        self.assertIsNone(_NoRedirect().redirect_request(None,None,302,'',{},'https://evil.test'))
    def test_oversized_response_rejected(self):
        from bishop_runtime.catalog import _get, MAX_BYTES
        with patch('bishop_runtime.catalog.urllib.request.build_opener') as factory:
            factory.return_value.open.return_value.__enter__.return_value.read.return_value=b'x'*(MAX_BYTES+1)
            with self.assertRaises(CatalogError): _get('https://example.com/models',{},1)
    def test_pagination_bounded(self):
        with patch('bishop_runtime.catalog._get',return_value={'data':[],'has_more':True,'last_id':'cursor'}):
            with self.assertRaises(CatalogError): discover_models('anthropic','https://example.com/v1')

class PolicyTests(unittest.TestCase):
    def test_credentials_and_endpoint_validated_before_any_get(self):
        for url,key in [('https://example.com/v1?secret=x',None),('https://u:p@example.com/v1',None),('https://example.com/v1#fragment',None),('https://example.com/v1',23),('https://example.com/v1','key\r\nheader')]:
            with patch('bishop_runtime.catalog._get') as get:
                with self.assertRaises(CatalogError): discover_models('opencode',url,api_key=key)
                get.assert_not_called()
    def test_model_id_length_matches_provider_validation(self):
        with patch('bishop_runtime.catalog._get',return_value={'data':[{'id':'x'*201},{'id':'x'*200}]}):
            self.assertEqual(len(discover_models('custom','https://example.com/v1')),1)
    def test_responses_transport_for_current_openai_families(self):
        with patch('bishop_runtime.catalog._get',return_value={'data':[{'id':x} for x in ['gpt-6-sol','gpt-5.4','gpt-4.1','gpt-4o','o3-pro','o4-mini','gpt-3.5-turbo']]}):
            models=discover_models('openai','https://api.openai.com/v1')
        self.assertTrue(all(m['kind']=='responses' for m in models[:-1]))
        self.assertEqual(models[-1]['kind'],'compatible')
    def test_transport_disables_ambient_proxy(self):
        from bishop_runtime.catalog import _get
        with patch('bishop_runtime.catalog.urllib.request.ProxyHandler') as proxy, patch('bishop_runtime.catalog.urllib.request.build_opener') as factory:
            factory.return_value.open.return_value.__enter__.return_value.read.return_value=b'{"data":[]}'
            _get('https://example.com/models',{},1)
            proxy.assert_called_once_with({})

class OutputCompatibilityTests(unittest.TestCase):
    def test_batch_variants_excluded_vision_inputs_allowed(self):
        rows=[{'id':'chat:batch','supported_parameters':['tools'],'architecture':{'output_modalities':['text']}}, {'id':'vision-chat','supported_parameters':['tools'],'architecture':{'input_modalities':['text','image'],'output_modalities':['text']}}]
        with patch('bishop_runtime.catalog._get',return_value={'data':rows}):
            result=discover_models('openrouter','https://openrouter.ai/api/v1')
        self.assertEqual([m['id'] for m in result],['vision-chat'])
