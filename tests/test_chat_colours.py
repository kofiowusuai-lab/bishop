import io
import unittest
from unittest.mock import patch
from bishop_runtime.terminal import conversation_style

class TTY(io.StringIO):
    def isatty(self):return True

class ChatColourTests(unittest.TestCase):
    def test_roles_are_distinct_and_reset(self):
        with patch.dict('os.environ',{},clear=True):
            values=[conversation_style('hello',role,TTY()) for role in ('user','bishop','system','error','approval')]
            self.assertEqual(len(set(values)),5)
            self.assertTrue(all(v.endswith('\x1b[0m') for v in values))
    def test_plain_output_and_no_color(self):
        self.assertEqual(conversation_style('hello','bishop',io.StringIO()),'hello')
        with patch.dict('os.environ',{'NO_COLOR':''},clear=True):
            self.assertEqual(conversation_style('hello','bishop',TTY()),'hello')

    def test_chat_colours_prompts_and_reply_without_accepting_model_escapes(self):
        from pathlib import Path
        import tempfile
        from bishop_runtime.cli import _runtime
        from bishop_runtime.config import init_home,load_config
        from bishop_runtime.provider import ScriptedProvider
        from bishop_runtime.shell import run_chat
        with tempfile.TemporaryDirectory() as root,patch.dict('os.environ',{},clear=True):
            home=Path(root);init_home(home);config=load_config(home)
            runtime,memory=_runtime(home,config,ScriptedProvider([{'content':'Hello\x1b[31m unsafe colour','tool_calls':[]}]),remote_progress=False)
            output=TTY();prompts=[];replies=iter(['hello','/exit'])
            def answer(prompt):prompts.append(prompt);return next(replies)
            try:run_chat(runtime,home,config,input_fn=answer,output=output)
            finally:runtime.close();memory.close()
            self.assertIn('\x1b[',prompts[0])
            self.assertIn(conversation_style('\nBishop › Hello unsafe colour\n','bishop',output),output.getvalue())
            self.assertNotIn('\x1b[31m',output.getvalue())
            self.assertNotIn('\x01',prompts[0])
