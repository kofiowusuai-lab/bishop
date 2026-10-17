"""Private lifecycle journal and isolated, scoped progress dispatch.

Only lifecycle facts are admitted. Provider text and tool arguments never enter
this database or callbacks. A failed observer never retries the underlying task.
"""
from contextlib import contextmanager
import json
import logging
import math
import os
from pathlib import Path
import re
import sqlite3
import threading
import time

_LOG = logging.getLogger(__name__)
_PHASES = frozenset(('started', 'resumed', 'model_started', 'tool_started',
    'tool_completed', 'awaiting_approval', 'needs_reconciliation', 'completed',
    'failed', 'step_limit', 'interrupted', 'heartbeat'))
_ACTIVE = frozenset(('started', 'resumed', 'model_started', 'tool_started', 'tool_completed', 'heartbeat'))


class ProgressMonitor:
    def __init__(self, home, heartbeat_interval=10):
        if type(heartbeat_interval) not in (int, float) or not math.isfinite(heartbeat_interval) or heartbeat_interval <= 0:
            raise ValueError('invalid heartbeat interval')
        home = Path(home)
        home.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = home / 'progress.db'
        if path.is_symlink():
            raise ValueError('progress journal must not be a symlink')
        self._db = sqlite3.connect(path, check_same_thread=False)
        try:
            os.chmod(path, 0o600)
            self._db.execute('CREATE TABLE IF NOT EXISTS events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, snapshot TEXT)')
            self._db.execute('CREATE INDEX IF NOT EXISTS events_run_sequence ON events(run_id,sequence)')
            self._db.commit()
        except Exception:
            self._db.close()
            raise
        self._condition = threading.Condition(threading.RLock())
        self._listeners = []
        self._cleanups = []
        self._pending = {}
        self._latest = {}
        self._warned = set()
        self._dispatching = False
        self._closed = False
        self._heartbeat_interval = heartbeat_interval
        self._thread = threading.Thread(target=self._dispatch, name='bishop-progress', daemon=True)
        self._thread.start()

    def _record(self, snapshot):
        prior = self._latest.get(snapshot['run_id'], {})
        if prior.get('visibility_failed'):
            snapshot['visibility_failed'] = True
        cursor = self._db.execute('INSERT INTO events(run_id,snapshot) VALUES (?,?)', (snapshot['run_id'], json.dumps(snapshot)))
        snapshot['sequence'] = cursor.lastrowid
        self._db.execute('UPDATE events SET snapshot=? WHERE sequence=?', (json.dumps(snapshot), cursor.lastrowid))
        # Bound disk history even for long-running processes. Keep the most
        # recent 1,000 facts per run and 100,000 facts across the installation.
        self._db.execute('DELETE FROM events WHERE run_id=? AND sequence NOT IN (SELECT sequence FROM events WHERE run_id=? ORDER BY sequence DESC LIMIT 1000)', (snapshot['run_id'], snapshot['run_id']))
        self._db.execute('DELETE FROM events WHERE sequence <= ?', (snapshot['sequence'] - 100000,))
        self._db.commit()
        self._latest[snapshot['run_id']] = snapshot
        if len(self._latest) > 1000:
            for run_id, prior in list(self._latest.items()):
                if run_id != snapshot['run_id'] and prior['phase'] not in _ACTIVE:
                    self._latest.pop(run_id)
                    self._warned = {key for key in self._warned if key[1] != run_id}
                    if len(self._latest) <= 1000:
                        break
        self._pending[snapshot['run_id']] = snapshot
        self._condition.notify_all()

    def emit(self, run, phase, tool=None):
        if phase not in _PHASES:
            raise ValueError('invalid progress phase')
        now = time.time()
        snapshot = dict(run_id=str(run['id'])[:256], actor=str(run.get('actor', 'local'))[:256],
            session_id=str(run.get('session_id', 'local'))[:256], status=str(run.get('status', 'running'))[:40],
            phase=phase, step=int(run.get('steps', 0)), created=float(run.get('created', now)),
            updated=now, elapsed=max(0, now - float(run.get('created', now))))
        if tool is not None and isinstance(tool, str) and re.fullmatch(r'[a-zA-Z0-9_.-]{1,128}', tool):
            snapshot['tool'] = tool
        with self._condition:
            if not self._closed:
                self._record(snapshot)

    @contextmanager
    def subscribe(self, callback, actor=None, session_id=None):
        if not callable(callback):
            raise ValueError('invalid progress callback')
        listener = dict(callback=callback, actor=actor, session=session_id, active=True, working=False)
        with self._condition:
            if self._closed:
                raise RuntimeError('progress monitor is closed')
            self._listeners.append(listener)
        try:
            yield callback
        finally:
            self.flush()
            with self._condition:
                listener['active'] = False
                # A callback already executing may finish after detachment.
                # Never hang task completion on an unresponsive observer.
                # Remote sinks must recheck authorization before each effect.
                self._listeners.remove(listener)
                self._warned = {key for key in self._warned if key[0] != id(listener)}

    def add_cleanup(self, callback):
        if not callable(callback):
            raise ValueError('invalid cleanup callback')
        with self._condition:
            if self._closed:
                raise RuntimeError('progress monitor is closed')
            self._cleanups.append(callback)

    def _dispatch(self):
        try:
            self._dispatch_loop()
        finally:
            for callback in self._cleanups:
                try:
                    callback()
                except Exception:
                    _LOG.warning('Bishop progress cleanup failed')
            self._db.close()

    def _dispatch_loop(self):
        while True:
            with self._condition:
                now = time.time()
                if self._closed and not self._pending:
                    return
                for snapshot in list(self._latest.values()):
                    if not self._closed and snapshot['phase'] in _ACTIVE and snapshot['status'] == 'running' and now - snapshot['updated'] >= self._heartbeat_interval:
                        heartbeat = dict(snapshot, phase='heartbeat', updated=now, elapsed=max(0, now - snapshot['created']))
                        heartbeat.pop('sequence', None)
                        self._record(heartbeat)
                if not self._pending:
                    self._condition.wait(min(self._heartbeat_interval, .5))
                    continue
                snapshots = list(self._pending.values())
                self._pending.clear()
                self._dispatching = True
            for snapshot in snapshots:
                with self._condition:
                    listeners = list(self._listeners)
                for listener in listeners:
                    with self._condition:
                        if not listener['active'] or listener['actor'] not in (None, snapshot['actor']) or listener['session'] not in (None, snapshot['session_id']):
                            continue
                        listener['working'] = True
                    try:
                        listener['callback'](dict(snapshot))
                    except Exception:
                        # Never log exception text: transport errors can contain tokens.
                        with self._condition:
                            warning_key = (id(listener), snapshot['run_id'])
                            if warning_key not in self._warned:
                                _LOG.warning('Bishop progress visibility failed; task execution continues')
                                self._warned.add(warning_key)
                            latest = self._latest.get(snapshot['run_id'])
                            if latest:
                                latest['visibility_failed'] = True
                                self._db.execute('UPDATE events SET snapshot=? WHERE sequence=?', (json.dumps(latest), latest['sequence']))
                                self._db.commit()
                    finally:
                        with self._condition:
                            listener['working'] = False
                            self._condition.notify_all()
            with self._condition:
                self._dispatching = False
                self._condition.notify_all()

    def flush(self, timeout=5):
        if threading.current_thread() is self._thread:
            return False
        deadline = time.monotonic() + max(0, timeout)
        with self._condition:
            while self._pending or self._dispatching:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    @staticmethod
    def _limit(limit):
        return max(1, min(1000, int(limit)))

    def events(self, run_id, limit=100):
        with self._condition:
            rows = self._db.execute('SELECT snapshot FROM events WHERE run_id=? ORDER BY sequence DESC LIMIT ?', (run_id, self._limit(limit))).fetchall()
        return [json.loads(row[0]) for row in reversed(rows)]

    def runs(self, limit=100):
        with self._condition:
            rows = self._db.execute('SELECT snapshot FROM events WHERE sequence IN (SELECT MAX(sequence) FROM events GROUP BY run_id) ORDER BY sequence DESC LIMIT ?', (self._limit(limit),)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def close(self):
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._condition.notify_all()
        self._thread.join(timeout=5)
        # A slow observer finishes cleanup on the dispatcher after it returns.


def _read(home, run_id, limit):
    path = Path(home).expanduser().resolve() / 'progress.db'
    if not path.exists():
        return []
    if path.is_symlink():
        raise ValueError('progress journal must not be a symlink')
    from urllib.parse import quote
    connection = sqlite3.connect('file:' + quote(str(path), safe='/') + '?mode=ro', uri=True)
    try:
        if run_id is None:
            rows = connection.execute('SELECT snapshot FROM events WHERE sequence IN (SELECT MAX(sequence) FROM events GROUP BY run_id) ORDER BY sequence DESC LIMIT ?', (ProgressMonitor._limit(limit),)).fetchall()
        else:
            rows = connection.execute('SELECT snapshot FROM events WHERE run_id=? ORDER BY sequence DESC LIMIT ?', (run_id, ProgressMonitor._limit(limit))).fetchall()
            rows.reverse()
        return [json.loads(row[0]) for row in rows]
    finally:
        connection.close()


def read_runs(home, limit=100):
    """Read latest snapshots without starting a monitor or creating files."""
    return _read(home, None, limit)


def read_events(home, run_id, limit=100):
    """Read bounded lifecycle history without starting a monitor."""
    return _read(home, run_id, limit)
