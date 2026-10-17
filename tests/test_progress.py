import json
import tempfile
import time
import unittest
from pathlib import Path
from bishop_runtime.progress import ProgressMonitor
from bishop_runtime.runtime import Runtime
from test_runtime import Provider, Tools, answer, call


class ProgressTests(unittest.TestCase):
    def test_journal_scope_failure_and_unsubscribe(self):
        with tempfile.TemporaryDirectory() as home:
            monitor = ProgressMonitor(home, heartbeat_interval=.02)
            seen = []
            run = dict(id='r', actor='alice', session_id='s', status='running', steps=1,
                       created=time.time(), input='SECRET', output='SECRET', arguments='SECRET')
            with monitor.subscribe(seen.append, actor='alice', session_id='s'):
                with monitor.subscribe(lambda value: (_ for _ in ()).throw(ValueError('SECRET'))):
                    monitor.emit(run, 'model_started')
                    self.assertTrue(monitor.flush())
                time.sleep(.06)
                self.assertTrue(monitor.flush())
            count = len(seen)
            monitor.emit(run, 'tool_started', tool='read_file')
            monitor.flush()
            self.assertEqual(len(seen), count)
            self.assertTrue(any(s['phase'] == 'heartbeat' for s in seen))
            self.assertNotIn('SECRET', json.dumps(monitor.events('r')))
            run['status'] = 'completed'
            monitor.emit(run, 'completed')
            monitor.flush()
            before = len(monitor.events('r'))
            time.sleep(.05)
            self.assertEqual(len(monitor.events('r')), before)
            monitor.close()

    def test_runtime_approval_resume_and_audit_order(self):
        with tempfile.TemporaryDirectory() as home:
            runtime = Runtime(home, Provider(call('write_file'), answer()), Tools())
            seen = []
            with runtime.progress.subscribe(seen.append):
                run = runtime.run('s', 'SECRET')
                runtime.progress.flush()
                self.assertEqual(seen[-1]['status'], 'awaiting_approval')
                runtime.approve(run['id'], 'call1')
                runtime.resume(run['id'])
                runtime.progress.flush()
                self.assertEqual(seen[-1]['phase'], 'completed')
                self.assertTrue(runtime.status(run['id'])['audit_complete'])
            runtime.close()

    def test_audit_failure_does_not_claim_success(self):
        with tempfile.TemporaryDirectory() as home:
            runtime = Runtime(home, Provider(answer()), Tools())
            runtime.audit.complete = lambda *a, **k: (_ for _ in ()).throw(ValueError('SECRET'))
            with self.assertRaises(ValueError):
                runtime.run('s', 'hello')
            runtime.progress.flush()
            snapshots = runtime.progress.runs()
            self.assertEqual(snapshots[0]['phase'], 'interrupted')
            self.assertNotEqual(snapshots[0]['status'], 'completed')
            runtime.close()

    def test_disabled(self):
        with tempfile.TemporaryDirectory() as home:
            runtime = Runtime(home, Provider(answer()), Tools(), progress=False)
            runtime.run('s', 'hello')
            runtime.close()
            self.assertFalse((Path(home) / 'progress.db').exists())

    def test_blocked_provider_heartbeat_and_scope(self):
        import threading
        entered, release = threading.Event(), threading.Event()
        class Blocking:
            def complete(self, messages, tools):
                entered.set()
                release.wait(2)
                return answer()
        with tempfile.TemporaryDirectory() as home:
            monitor = ProgressMonitor(home, heartbeat_interval=.02)
            def work():
                runtime = Runtime(home, Blocking(), Tools(), progress=monitor)
                try:
                    runtime.run("s", "SECRET")
                finally:
                    runtime.close()
            seen, other = [], []
            with monitor.subscribe(seen.append, actor='local', session_id='s'), monitor.subscribe(other.append, actor='other'):
                thread = threading.Thread(target=work)
                thread.start()
                self.assertTrue(entered.wait(1))
                time.sleep(.08)
                monitor.flush()
                self.assertTrue(any(s['phase'] == 'heartbeat' for s in seen))
                self.assertEqual(other, [])
                release.set()
                thread.join(2)
                monitor.flush()
            self.assertFalse(monitor._closed, 'injected monitor is not owned by runtime')
            cleaned = []
            monitor.add_cleanup(lambda: cleaned.append(True))
            monitor.close()
            self.assertEqual(cleaned, [True])
            self.assertFalse(monitor._thread.is_alive())

    def test_read_only_helpers_and_bounds(self):
        from bishop_runtime.progress import read_runs, read_events
        with tempfile.TemporaryDirectory() as parent:
            home = Path(parent) / 'absent'
            self.assertEqual(read_runs(home), [])
            self.assertFalse(home.exists())
            monitor = ProgressMonitor(home)
            run = dict(id='r', actor='local', session_id='s', status='failed', steps=0, created=time.time())
            for _ in range(5):
                monitor.emit(run, 'failed')
            monitor.close()
            self.assertEqual(len(read_events(home, 'r', limit=2)), 2)
            self.assertEqual(len(read_runs(home)), 1)

    def test_retention_and_failure_warning_are_bounded(self):
        with tempfile.TemporaryDirectory() as home:
            monitor = ProgressMonitor(home)
            run = dict(id='r', actor='local', session_id='s', status='failed', steps=0, created=time.time())
            def broken(snapshot):
                raise ValueError('SECRET')
            with monitor.subscribe(broken):
                with self.assertLogs('bishop_runtime.progress', level='WARNING') as logs:
                    for _ in range(3):
                        monitor.emit(run, 'failed')
                        monitor.flush()
                self.assertEqual(len(logs.output), 1)
            for _ in range(1002):
                monitor.emit(run, 'failed')
            monitor.flush()
            self.assertEqual(len(monitor.events('r', limit=100000)), 1000)
            monitor.close()

    def test_runtime_accepts_heartbeat_interval_and_rejects_invalid_early(self):
        with tempfile.TemporaryDirectory() as home:
            runtime = Runtime(home, Provider(answer()), Tools(), progress_heartbeat_interval=.02)
            runtime.run('s', 'hello')
            runtime.close()
            with self.assertRaises(ValueError):
                Runtime(home, Provider(answer()), Tools(), progress_heartbeat_interval=float('nan'))

    def test_failed_audit_resume_never_exposes_completed_before_verification(self):
        with tempfile.TemporaryDirectory() as home:
            runtime = Runtime(home, Provider(answer()), Tools())
            runtime.audit.complete = lambda *a, **k: (_ for _ in ()).throw(ValueError('SECRET'))
            with self.assertRaises(ValueError):
                runtime.run('s', 'hello')
            run_id = runtime.progress.runs()[0]['run_id']
            with self.assertRaises(ValueError):
                runtime.resume(run_id)
            runtime.progress.flush()
            self.assertFalse(any(s['status'] == 'completed' for s in runtime.progress.events(run_id)))
            runtime.close()

    def test_detach_does_not_wait_forever_for_observer(self):
        import threading
        entered, release = threading.Event(), threading.Event()
        def blocked(snapshot):
            entered.set()
            release.wait(2)
        with tempfile.TemporaryDirectory() as home:
            monitor = ProgressMonitor(home)
            original_flush = monitor.flush
            monitor.flush = lambda timeout=5: original_flush(timeout=.02)
            start = time.monotonic()
            with monitor.subscribe(blocked):
                monitor.emit(dict(id='r', status='failed'), 'failed')
                self.assertTrue(entered.wait(1))
            self.assertLess(time.monotonic() - start, 1)
            self.assertEqual(monitor._listeners, [])
            release.set()
            monitor.close()

    def test_journal_failure_warns_once_without_secret_or_task_failure(self):
        class BrokenJournal:
            def emit(self, *args, **kwargs):
                raise ValueError('SECRET-TOKEN')
        with tempfile.TemporaryDirectory() as home:
            runtime = Runtime(home, Provider(answer()), Tools(), progress=BrokenJournal())
            with self.assertLogs('bishop_runtime.runtime', level='WARNING') as logs:
                run = runtime.run('s', 'hello')
            self.assertEqual(run['status'], 'completed')
            self.assertEqual(len(logs.output), 1)
            self.assertNotIn('SECRET', logs.output[0])
            runtime.close()

    def test_corrupt_optional_journal_does_not_brick_runtime(self):
        with tempfile.TemporaryDirectory() as home:
            (Path(home) / 'progress.db').write_bytes(b'not a sqlite database SECRET-TOKEN')
            with self.assertLogs('bishop_runtime.runtime', level='WARNING') as logs:
                runtime = Runtime(home, Provider(answer()), Tools())
                run = runtime.run('s', 'hello')
            self.assertIsNone(runtime.progress)
            self.assertEqual(run['status'], 'completed')
            self.assertEqual(len(logs.output), 1)
            self.assertNotIn('SECRET', logs.output[0])
            runtime.close()

    def test_new_run_starts_without_claiming_resume(self):
        with tempfile.TemporaryDirectory() as home:
            runtime = Runtime(home, Provider(answer()), Tools())
            run = runtime.run('s', 'hello')
            phases = [snapshot['phase'] for snapshot in runtime.progress.events(run['id'])]
            self.assertEqual(phases[0], 'started')
            self.assertNotIn('resumed', phases)
            self.assertIn('model_started', phases)
            self.assertEqual(phases[-1], 'completed')
            runtime.close()
