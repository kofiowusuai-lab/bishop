"""Actor-scoped, explicitly written local memory."""
import hashlib
from pathlib import Path
import sqlite3


class MemoryStore:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY, scope TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        self.db.commit()
        path.chmod(0o600)

    def remember(self, scope, text):
        if not isinstance(scope,str) or not scope or not isinstance(text,str) or not text.strip() or len(text)>16000:
            raise ValueError('invalid memory')
        ident=hashlib.sha256((scope+'\0'+text).encode()).hexdigest()
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO memories(id,scope,text) VALUES(?,?,?)',(ident,scope,text))
        return dict(self.db.execute('SELECT id,text,created_at FROM memories WHERE id=?',(ident,)).fetchone())

    def search(self, scope, query, limit=10):
        if not isinstance(scope,str) or not isinstance(query,str) or len(query)>16000 or type(limit) is not int or not 1<=limit<=100:
            raise ValueError('invalid memory query')
        # instr performs literal substring search rather than SQL wildcard expansion.
        rows=self.db.execute('SELECT id,text,created_at FROM memories WHERE scope=? AND instr(lower(text),lower(?))>0 ORDER BY created_at DESC,id LIMIT ?', (scope,query,limit))
        return [dict(row) for row in rows]

    def close(self):
        self.db.close()
