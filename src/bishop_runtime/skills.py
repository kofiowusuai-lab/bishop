"""Load owner-installed instructions, never execute skill scripts."""
from pathlib import Path
from itertools import islice
import re
from importlib.resources import files


def bundled_skill(name):
    if name != 'task-monitor':
        return None
    return files('bishop_runtime').joinpath('builtin_skills', 'task-monitor', 'SKILL.md')


class SkillStore:
    def __init__(self, directory, create=True):
        if Path(directory).is_symlink():
            raise ValueError('skill directory cannot be a symlink')
        self.directory=Path(directory).resolve()
        if create:
            self.directory.mkdir(parents=True,exist_ok=True)

    def _path(self,name):
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',name):
            raise ValueError('invalid skill name')
        directory=self.directory/name
        path=directory/'SKILL.md'
        if directory.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(self.directory):
            raise ValueError('skill path rejected')
        return path

    def list(self):
        result=[]
        for entry in sorted(islice(self.directory.iterdir() if self.directory.is_dir() else (),201)):
            try:
                path=self._path(entry.name)
                if path.is_file():
                    result.append({'name':entry.name})
            except ValueError:
                continue
            if len(result)>=200:
                break
        if not any(item['name'] == 'task-monitor' for item in result):
            result.append({'name': 'task-monitor', 'source': 'bundled'})
        return sorted(result, key=lambda item: item['name'])

    def read(self,name,max_chars):
        path=self._path(name)
        try:
            source = path if path.exists() else bundled_skill(name)
            if source is None:
                raise ValueError('skill unavailable')
            with source.open('r',encoding='utf-8') as handle:
                text=handle.read(max_chars+1)
        except (OSError,UnicodeError):
            raise ValueError('skill unavailable') from None
        return {'name':name,'content':text[:max_chars],'truncated':len(text)>max_chars}
