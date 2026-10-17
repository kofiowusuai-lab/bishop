"""Load owner-installed instructions, never execute skill scripts."""
from pathlib import Path
from itertools import islice
import re


class SkillStore:
    def __init__(self, directory):
        self.directory=Path(directory).resolve()
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
        for entry in sorted(islice(self.directory.iterdir(),201)):
            try:
                path=self._path(entry.name)
                if path.is_file():
                    result.append({'name':entry.name})
            except ValueError:
                continue
            if len(result)>=200:
                break
        return result

    def read(self,name,max_chars):
        path=self._path(name)
        try:
            with path.open('r',encoding='utf-8') as handle:
                text=handle.read(max_chars+1)
        except (OSError,UnicodeError):
            raise ValueError('skill unavailable') from None
        return {'name':name,'content':text[:max_chars],'truncated':len(text)>max_chars}
