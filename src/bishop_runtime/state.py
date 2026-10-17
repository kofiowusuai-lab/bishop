"""Durable run snapshots and short SQLite transactions, never network locks."""
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

ACTIVE = ('running', 'awaiting_approval', 'needs_reconciliation')


class RuntimeBusyError(ValueError):
    """Another turn or worker currently owns this session/run."""


class State:
    LEASE_SECONDS = 600

    def __init__(self, path):
        path = Path(path)
        self.connection = sqlite3.connect(path, isolation_level=None, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute('PRAGMA journal_mode=WAL')
        self.connection.execute('PRAGMA synchronous=FULL')
        self.connection.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, actor TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL, data TEXT NOT NULL, lease_owner TEXT, lease_until REAL NOT NULL DEFAULT 0)')
        self.connection.execute('CREATE INDEX IF NOT EXISTS run_sessions ON runs(actor,session_id,created)')
        os.chmod(path, 0o600)

    @contextmanager
    def transaction(self):
        self.connection.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.connection.execute('COMMIT')
        except BaseException:
            self.connection.execute('ROLLBACK')
            raise

    def load(self, run_id):
        row = self.connection.execute('SELECT data FROM runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            raise ValueError('unknown run')
        return json.loads(row['data'])

    def create(self, run, owner):
        with self.transaction():
            if self.active(run['session_id'], run['actor']) is not None:
                raise RuntimeBusyError('session has an active run')
            self.connection.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)',
                (run['id'], run['session_id'], run['actor'], run['status'], run['created'], json.dumps(run), owner, time.time() + self.LEASE_SECONDS))

    def acquire(self, run_id, actor, owner):
        with self.transaction():
            row = self.connection.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
            if row is None:
                raise ValueError('unknown run')
            if row['actor'] != actor:
                raise ValueError('run belongs to another actor')
            if row['lease_owner'] and row['lease_owner'] != owner and row['lease_until'] > time.time():
                raise RuntimeBusyError('run is owned by another worker')
            self.connection.execute('UPDATE runs SET lease_owner=?,lease_until=? WHERE id=?', (owner, time.time() + self.LEASE_SECONDS, run_id))
            return json.loads(row['data'])

    def save(self, run, owner):
        with self.transaction():
            updated = self.connection.execute('UPDATE runs SET data=?,status=?,lease_until=? WHERE id=? AND lease_owner=? AND lease_until>?',
                (json.dumps(run), run['status'], time.time() + self.LEASE_SECONDS, run['id'], owner, time.time()))
            if updated.rowcount != 1:
                raise RuntimeBusyError('run lease expired or changed')

    def release(self, run_id, owner):
        self.connection.execute('UPDATE runs SET lease_owner=NULL,lease_until=0 WHERE id=? AND lease_owner=?', (run_id, owner))

    def active(self, session_id, actor):
        row = self.connection.execute('SELECT data FROM runs WHERE session_id=? AND actor=? AND status IN (?,?,?) ORDER BY created DESC LIMIT 1', (session_id, actor, *ACTIVE)).fetchone()
        return json.loads(row['data']) if row else None

    def history(self, session_id, actor, limit):
        if not limit:
            return []
        rows = self.connection.execute("SELECT data FROM runs WHERE session_id=? AND actor=? AND status='completed' ORDER BY created DESC LIMIT ?", (session_id, actor, limit)).fetchall()
        return [json.loads(row['data']) for row in reversed(rows)]

    def sessions(self):
        rows = self.connection.execute('SELECT session_id,actor,MAX(created) AS updated,COUNT(*) AS runs FROM runs GROUP BY session_id,actor ORDER BY updated DESC').fetchall()
        return [dict(row) for row in rows]

    def close(self):
        self.connection.close()
