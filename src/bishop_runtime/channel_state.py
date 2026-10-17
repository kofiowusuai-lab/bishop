"""Private durable Telegram inbox and delivery journal."""
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path

class ChannelState:
    def __init__(self, home):
        home=Path(home); home.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.db=sqlite3.connect(home/'telegram.db'); self.db.row_factory=sqlite3.Row
        os.chmod(home/'telegram.db',0o600)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS inbox(id INTEGER PRIMARY KEY,payload TEXT,status TEXT,run_id TEXT);
        CREATE TABLE IF NOT EXISTS deliveries(id TEXT PRIMARY KEY,update_id INTEGER,chat_id INTEGER,text TEXT,status TEXT);
        ''')
        self.owner=uuid.uuid4().hex
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row=self.db.execute("SELECT value FROM meta WHERE key='lease'").fetchone()
            if row and self._live_lease(json.loads(row[0])):
                raise ValueError('Telegram poller already active')
            self.db.execute("INSERT OR REPLACE INTO meta VALUES('lease',?)",(json.dumps({'owner':self.owner,'pid':os.getpid(),'expires':time.time()+120}),))
            self.db.execute("UPDATE deliveries SET status='uncertain' WHERE status='sending'")
            self.db.execute("UPDATE inbox SET status='recover' WHERE status='processing'")
    @staticmethod
    def _live_lease(lease):
        try:
            os.kill(lease['pid'],0); return True
        except ProcessLookupError: return False
        except (KeyError,PermissionError): return lease['expires']>time.time()
    def renew(self):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row=self.db.execute("SELECT value FROM meta WHERE key='lease'").fetchone()
            if not row or json.loads(row[0])['owner']!=self.owner: raise ValueError('Telegram lease lost')
            self.db.execute("UPDATE meta SET value=? WHERE key='lease'",(json.dumps({'owner':self.owner,'pid':os.getpid(),'expires':time.time()+120}),))
    def offset(self):
        row=self.db.execute("SELECT value FROM meta WHERE key='offset'").fetchone(); return int(row[0]) if row else 0
    def ingest(self, updates, authorize):
        offset=self.offset()
        with self.db:
            for u in updates:
                if not isinstance(u,dict) or type(u.get('update_id')) is not int: continue
                offset=max(offset,u['update_id']+1)
                payload=authorize(u)
                if payload is not None: self.db.execute('INSERT OR IGNORE INTO inbox VALUES(?,?,?,NULL)',(u['update_id'],json.dumps(payload),'pending'))
            self.db.execute("INSERT OR REPLACE INTO meta VALUES('offset',?)",(str(offset),))
    def queued(self): return [dict(r) for r in self.db.execute("SELECT * FROM inbox WHERE status IN ('pending','recover') ORDER BY id LIMIT 100")]
    def mark(self,id,status,run_id=None):
        with self.db: self.db.execute('UPDATE inbox SET status=?,run_id=COALESCE(?,run_id) WHERE id=?',(status,run_id,id))
    def finish(self,id,chat_id,chunks):
        with self.db:
            for text in chunks: self.db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?)',(uuid.uuid4().hex,id,chat_id,text,'pending'))
            self.db.execute("UPDATE inbox SET status='done' WHERE id=?",(id,))
    def authorized_delivery(self,update_id,allowed):
        row=self.db.execute('SELECT payload FROM inbox WHERE id=?',(update_id,)).fetchone()
        return bool(row and json.loads(row[0])['user'] in allowed)
    def delivery_blocked(self,delivery_id,update_id):
        return self.db.execute("SELECT 1 FROM deliveries WHERE update_id=? AND rowid<(SELECT rowid FROM deliveries WHERE id=?) AND status NOT IN ('sent','revoked') LIMIT 1",(update_id,delivery_id)).fetchone() is not None
    def deliveries(self): return [dict(r) for r in self.db.execute('SELECT * FROM deliveries ORDER BY rowid')]
    def delivery_status(self,id,status):
        with self.db: self.db.execute('UPDATE deliveries SET status=? WHERE id=?',(status,id))
    def close(self):
        with self.db:
            row=self.db.execute("SELECT value FROM meta WHERE key='lease'").fetchone()
            if row and json.loads(row[0])['owner']==self.owner: self.db.execute("DELETE FROM meta WHERE key='lease'")
        self.db.close()
