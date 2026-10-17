import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from bishop_runtime.cli import _runtime
from bishop_runtime.config import init_home,load_config
from bishop_runtime.provider import ScriptedProvider
from bishop_runtime.shell import run_chat
from bishop_runtime.skills import SkillStore


class ResearchIntegrationTests(unittest.TestCase):
    def test_independent_search_read_answer_loop_and_bundled_guidance(self):
        with tempfile.TemporaryDirectory() as root:
            home=Path(root);init_home(home);config=load_config(home)
            provider=ScriptedProvider([
                {'content':None,'tool_calls':[{'id':'search','name':'web_search','arguments':{'query':'Hermes agent'}}]},
                {'content':None,'tool_calls':[{'id':'read','name':'web_read','arguments':{'url':'https://example.com/hermes'}}]},
                {'content':'Findings from [source](https://example.com/hermes).','tool_calls':[]}])
            runtime,memory=_runtime(home,config,provider,remote_progress=False)
            runtime.tools.web_search=Mock();runtime.tools.web_client=Mock()
            runtime.tools.web_search.search.return_value={'ok':True,'results':[{'title':'Source','url':'https://example.com/hermes','snippet':'Discovery'}]}
            runtime.tools.web_client.read.return_value={'ok':True,'url':'https://example.com/hermes','title':'Source','content':'Primary evidence'}
            try:
                run=runtime.run('research','Research Hermes independently')
                self.assertEqual(run['status'],'completed')
                self.assertEqual(len(provider.requests),3)
                self.assertIn('Primary evidence',json.dumps(provider.requests[-1]))
                self.assertIn('web-research',[s['name'] for s in SkillStore(home/'skills').list()])
            finally:runtime.close();memory.close()

    def test_shell_exposes_version_and_actual_capabilities_without_model(self):
        with tempfile.TemporaryDirectory() as root:
            home=Path(root);init_home(home);config=load_config(home)
            runtime,memory=_runtime(home,config,ScriptedProvider([]),remote_progress=False)
            answers=iter(['/version','/tools','/skills','/exit']);out=io.StringIO()
            try:
                run_chat(runtime,home,config,input_fn=lambda prompt:next(answers),output=out)
                self.assertIn('web_search',out.getvalue())
                self.assertIn('web_read',out.getvalue())
                self.assertIn('web-research',out.getvalue())
                self.assertIn('Bishop runtime',out.getvalue())
            finally:runtime.close();memory.close()
