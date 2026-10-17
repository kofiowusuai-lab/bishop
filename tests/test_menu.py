import io
import os
import pty
import select
import struct
import subprocess
import sys
import time
import unittest

from bishop_runtime.menu import choose


class MenuTests(unittest.TestCase):
    def test_fallback_search_number_and_sanitization(self):
        answers = iter(['/beta', '1'])
        output = io.StringIO()
        self.assertEqual(choose('Pick', [('a', 'Alpha'), ('b', '\x1b[31mBeta')], input_fn=lambda _: next(answers), output=output), 'b')
        self.assertNotIn('\x1b', output.getvalue())

    def test_current_and_cancel(self):
        self.assertIsNone(choose('Pick', [('a', 'Alpha')], input_fn=lambda _: '', output=io.StringIO(), current='a'))
        self.assertIsNone(choose('Empty', [], output=io.StringIO()))

    @unittest.skipUnless(os.name == 'posix', 'POSIX terminal')
    def test_pty_search_paging_and_rapid_arrows(self):
        self.assert_pty(b'\x1b[B\x1b[B\r', 'm2')
        self.assert_pty(b'/Model 77\r', 'm77')
        self.assert_pty(b'\x1b[6~\r', 'm4')
        self.assert_pty(b'\x1b[F\r', 'm99')
        self.assert_pty(b'\x1b', 'None')
        self.assert_pty(b'\x1b[B\x1b[B\r', 'm2', size=(0, 0))

    def assert_pty(self, keys, expected, size=(8, 32)):
        import fcntl
        import termios
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', *size, 0, 0))
        script = "from bishop_runtime.menu import choose; print('RESULT='+str(choose('Pick', [('m'+str(i),'Model '+str(i)) for i in range(100)])))"
        process = subprocess.Popen([sys.executable, '-c', script], stdin=slave, stdout=slave, stderr=slave)
        os.close(slave)
        data = b''
        try:
            deadline = time.monotonic() + 5
            while b'navigate' not in data and time.monotonic() < deadline:
                if select.select([master], [], [], .1)[0]:
                    data += os.read(master, 65536)
            self.assertIn(b'navigate', data)
            from bishop_runtime.terminal import _cells
            initial = data.decode('utf-8', errors='replace').replace('\r', '').splitlines()
            self.assertLessEqual(len(initial), size[0] or 24)
            self.assertTrue(all(_cells(line) <= (size[1] or 80) - 1 for line in initial))
            self.assertNotIn(b'Model 99', data)
            os.write(master, keys)
            while process.poll() is None and time.monotonic() < deadline:
                if select.select([master], [], [], .1)[0]:
                    try:
                        data += os.read(master, 65536)
                    except OSError:
                        break
            process.wait(timeout=2)
            try:
                while select.select([master], [], [], .05)[0]:
                    chunk = os.read(master, 65536)
                    if not chunk:
                        break
                    data += chunk
            except OSError:
                pass
            self.assertIn(('RESULT='+expected).encode(), data)
            # The initial viewport never prints the entire catalog.
            self.assertNotIn(b'    Model 99', data.split(b'\x1b[')[0])
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)
