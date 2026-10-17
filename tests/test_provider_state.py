import tempfile
import unittest
from pathlib import Path
from bishop_runtime.cli import _runtime
from bishop_runtime.config import init_home, load_config
from bishop_runtime.provider import ScriptedProvider


class StatefulProvider(ScriptedProvider):
    def complete(self, messages, tools):
        result = super().complete(messages, tools)
        if len(self.requests) == 1:
            result['provider_state'] = {'kind': 'openai_responses', 'output': [{'type': 'reasoning', 'encrypted_content': 'opaque-test-state'}]}
        return result


class ProviderStateTests(unittest.TestCase):
    def test_provider_state_survives_approval_restart(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root); init_home(home); config = load_config(home)
            provider = StatefulProvider([{'content': None, 'tool_calls': [{'id': 'write', 'name': 'write_file', 'arguments': {'path': 'a.txt', 'content': 'a'}}]}])
            runtime, memory = _runtime(home, config, provider)
            run = runtime.run('state-test', 'write a file')
            runtime.close(); memory.close()
            provider = ScriptedProvider([{'content': 'done', 'tool_calls': []}])
            runtime, memory = _runtime(home, config, provider)
            try:
                runtime.approve(run['id'], 'write')
                self.assertEqual(runtime.resume(run['id'])['status'], 'completed')
                assistant = next(m for m in provider.requests[0]['messages'] if m.get('tool_calls'))
                self.assertEqual(assistant['provider_state']['output'][0]['encrypted_content'], 'opaque-test-state')
            finally:
                runtime.close(); memory.close()
