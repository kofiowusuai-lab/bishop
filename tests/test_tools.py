import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from bishop_runtime.memory import MemoryStore
from bishop_runtime.tools import ToolRegistry


class ToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.skills = self.root / 'skills'
        self.skills.mkdir()
        self.memory = MemoryStore(self.root / 'memory.db')
        self.tools = ToolRegistry(self.workspace, self.memory, self.skills)

    def tearDown(self):
        self.memory.close()
        self.tmp.cleanup()

    def test_workspace_write_read_and_list(self):
        self.tools.invoke('write_file', {'path':'notes/a.txt', 'content':'hello'})
        self.assertEqual(json.loads(self.tools.invoke('read_file', {'path':'notes/a.txt'}))['content'], 'hello')
        self.assertIn('notes', self.tools.invoke('list_files', {}))
        self.assertEqual(self.tools.describe('write_file'), {'risk':'write', 'idempotent':False})

    def test_paths_cannot_escape_or_expose_hidden_files(self):
        (self.root / 'secret').write_text('secret')
        (self.workspace / 'outside').symlink_to(self.root)
        for path in ['../secret', str(self.root / 'secret'), 'outside/secret', '.env', '.bishop/runtime.db', 'a/../b']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.tools.invoke('read_file', {'path':path})
        (self.workspace / '.env').write_text('secret')
        self.assertNotIn('.env', self.tools.invoke('list_files', {}))
        self.assertNotIn('outside', self.tools.invoke('list_files', {}))

    def test_symlink_cannot_alias_hidden_files_or_directories(self):
        (self.workspace/'.env').write_text('secret')
        (self.workspace/'.private').mkdir()
        (self.workspace/'.private'/'data').write_text('secret')
        (self.workspace/'public.txt').symlink_to(self.workspace/'.env')
        (self.workspace/'public-dir').symlink_to(self.workspace/'.private')
        for path in ['public.txt','public-dir/data']:
            with self.assertRaises(ValueError):
                self.tools.invoke('read_file',{'path':path})
        listing=self.tools.invoke('list_files',{})
        self.assertNotIn('public.txt',listing)
        self.assertNotIn('public-dir',listing)

    def test_schema_strict_and_disabled_tools_hidden(self):
        for args in [{'path':1}, {'path':'a','extra':True}, []]:
            with self.assertRaises(ValueError):
                self.tools.validate('read_file', args)
        tools = ToolRegistry(self.workspace,self.memory,self.skills,allow_write=False)
        names = [t['function']['name'] for t in tools.definitions()]
        self.assertNotIn('write_file',names)
        self.assertNotIn('memory_remember',names)
        self.assertNotIn('run_command',names)
        with self.assertRaises(ValueError):
            tools.invoke('write_file',{'path':'a','content':'a'})

    def test_memory_is_persistent_scoped_and_idempotent(self):
        first = self.memory.remember('alice','prefer Python')
        self.assertEqual(first['id'], self.memory.remember('alice','prefer Python')['id'])
        self.assertEqual(self.memory.search('bob','Python'),[])
        self.memory.close()
        self.memory = MemoryStore(self.root / 'memory.db')
        self.assertEqual(self.memory.search('alice','Python')[0]['text'],'prefer Python')
        self.tools.memory = self.memory
        self.tools.invoke('memory_remember',{'text':'likes tea'},scope='bob')
        self.assertIn('likes tea',self.tools.invoke('memory_search',{'query':'tea'},scope='bob'))

    def test_skills_load_only_named_skill_files(self):
        (self.skills / 'writer').mkdir()
        (self.skills / 'writer' / 'SKILL.md').write_text('# Write clearly')
        self.assertIn('writer',self.tools.invoke('list_skills',{}))
        self.assertIn('Write clearly',self.tools.invoke('read_skill',{'name':'writer'}))
        for name in ['../writer','.hidden','writer/SKILL.md']:
            with self.assertRaises(ValueError):
                self.tools.invoke('read_skill',{'name':name})
        (self.skills / 'escape').symlink_to(self.root)
        self.assertNotIn('escape',self.tools.invoke('list_skills',{}))

    def test_output_bounded_and_command_environment_stripped(self):
        tools = ToolRegistry(self.workspace,self.memory,self.skills,allow_command=True,max_output_chars=500,command_timeout=.2)
        os.environ['BISHOP_MODEL_API_KEY']='do-not-inherit'
        try:
            out=json.loads(tools.invoke('run_command',{'argv':[sys.executable,'-c','import os; print(os.environ.get("BISHOP_MODEL_API_KEY", "absent"))']}))
        finally:
            del os.environ['BISHOP_MODEL_API_KEY']
        self.assertEqual(out['stdout'].strip(),'absent')
        result=tools.invoke('run_command',{'argv':[sys.executable,'-c','print("x"*100000)']})
        self.assertLessEqual(len(result),500)
        json.loads(result)
        timeout=json.loads(tools.invoke('run_command',{'argv':[sys.executable,'-c','import time; time.sleep(5)']}))
        self.assertTrue(timeout['timed_out'])

    def test_output_unicode_remains_valid_json_and_validations_detach(self):
        args={'argv':['echo','hello']}
        tools=ToolRegistry(self.workspace,self.memory,self.skills,allow_command=True,max_output_chars=256)
        detached=tools.validate('run_command',args)
        args['argv'].append('changed')
        self.assertEqual(detached['argv'],['echo','hello'])
        for argv in [[],[1],['echo',True],['echo','a\0b']]:
            with self.assertRaises(ValueError):
                tools.validate('run_command',{'argv':argv})
        (self.workspace/'unicode.txt').write_text('😀'*1000)
        output=tools.invoke('read_file',{'path':'unicode.txt'})
        self.assertLessEqual(len(output),256)
        self.assertTrue(json.loads(output)['truncated'])

    def test_directory_scans_stop_before_materializing_all_entries(self):
        from unittest.mock import patch
        def entries(path):
            cap=501 if path==self.workspace.resolve() else 201
            for i in range(cap):
                yield path/('item'+str(i))
            raise AssertionError('directory enumeration exceeded cap')
        with patch.object(Path,'iterdir',entries):
            self.tools.invoke('list_files',{})
            self.tools.invoke('list_skills',{})

    def test_skill_symlink_file_is_rejected(self):
        (self.skills/'writer').mkdir()
        (self.root/'instructions').write_text('secret')
        (self.skills/'writer'/'SKILL.md').symlink_to(self.root/'instructions')
        with self.assertRaises(ValueError):
            self.tools.invoke('read_skill',{'name':'writer'})

    def test_large_reads_are_bounded_and_binary_rejected(self):
        (self.workspace/'large.txt').write_text('x'*100000)
        tools=ToolRegistry(self.workspace,self.memory,self.skills,max_output_chars=500)
        result=tools.invoke('read_file',{'path':'large.txt'})
        self.assertLessEqual(len(result),500)
        self.assertTrue(json.loads(result)['truncated'])
        (self.workspace/'binary').write_bytes(b'\xff\x00')
        with self.assertRaises(ValueError):
            tools.invoke('read_file',{'path':'binary'})

if __name__ == '__main__':
    unittest.main()
