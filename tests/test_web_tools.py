import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from bishop_runtime.tools import ToolRegistry


class WebToolTests(unittest.TestCase):
    def make(self,home,**kwargs):return ToolRegistry(Path(home)/'workspace',None,Path(home)/'skills',**kwargs)

    def test_web_tools_enabled_by_default_and_read_only(self):
        with tempfile.TemporaryDirectory() as root:
            tools=self.make(root)
            names=[t['function']['name'] for t in tools.definitions()]
            self.assertIn('web_search',names);self.assertIn('web_read',names)
            self.assertEqual(tools.describe('web_search'),{'risk':'read','idempotent':True})

    def test_search_and_page_keep_sources(self):
        with tempfile.TemporaryDirectory() as root:
            search=Mock();client=Mock()
            search.search.return_value={'ok':True,'results':[{'title':'Primary source','url':'https://example.com/report','snippet':'Result'}]}
            client.read.return_value={'ok':True,'url':'https://example.com/report','title':'Primary source','content':'Evidence','truncated':False}
            tools=self.make(root,web_search=search,web_client=client)
            result=json.loads(tools.invoke('web_search',{'query':'topic'}))
            self.assertEqual(result['results'][0]['url'],'https://example.com/report')
            result=json.loads(tools.invoke('web_read',{'url':'https://example.com/report'}))
            self.assertEqual(result['content'],'Evidence')

    def test_web_failure_is_tool_data_not_runtime_exception(self):
        from bishop_runtime.web import WebError
        with tempfile.TemporaryDirectory() as root:
            client=Mock();client.read.side_effect=WebError('blocked','Page access blocked',retryable=False)
            tools=self.make(root,web_client=client)
            result=json.loads(tools.invoke('web_read',{'url':'https://example.com/page'}))
            self.assertFalse(result['ok']);self.assertEqual(result['error'],'blocked')

    def test_disabled_tools_hidden_and_invocation_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            tools=self.make(root,allow_web=False)
            self.assertNotIn('web_read',[t['function']['name'] for t in tools.definitions()])
            with self.assertRaises(ValueError):tools.invoke('web_search',{'query':'topic'})

    def test_citation_metadata_over_budget_returns_explicit_error(self):
        with tempfile.TemporaryDirectory() as root:
            client=Mock();client.read.return_value={'ok':True,'url':'https://example.com/'+('p'*300),'title':'T'*100,'content':'Evidence','truncated':False}
            tools=self.make(root,web_client=client,max_output_chars=256)
            result=json.loads(tools.invoke('web_read',{'url':'https://example.com/page'}))
            self.assertFalse(result['ok'])
            self.assertEqual(result['error'],'web_output_limit')

    def test_long_page_trims_text_but_keeps_citation(self):
        with tempfile.TemporaryDirectory() as root:
            client=Mock();client.read.return_value={'ok':True,'url':'https://example.com/report','title':'Report','content':'é'*2000,'truncated':False}
            tools=self.make(root,web_client=client,max_output_chars=500)
            raw=tools.invoke('web_read',{'url':'https://example.com/report'})
            result=json.loads(raw)
            self.assertLessEqual(len(raw),500)
            self.assertEqual(result['url'],'https://example.com/report')
            self.assertTrue(result['truncated'])
