"""`scripts/with_lock.py::acquire` 主机锁等待入口测试。"""

from __future__ import annotations

import contextlib
import errno
import importlib.util
import io
import itertools
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from kototoki import config

_SPEC = importlib.util.spec_from_file_location("with_lock_script", config.REPO_ROOT / "scripts" / "with_lock.py")
with_lock = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(with_lock)


class WithLockAcquireTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.lock_path = Path(tmp.name) / "gate-full.lock"
        self.lock_path.write_text("pid=101\n", encoding="utf-8")
        self.stream = self.lock_path.open("r+", encoding="utf-8")
        self.addCleanup(self.stream.close)

    def test_non_contention_oserror_fails_fast_with_error_on_stderr(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(with_lock.fcntl, "flock", side_effect=OSError(errno.EIO, "i/o failure")),
            mock.patch.object(with_lock.time, "sleep", side_effect=AssertionError("unexpected retry sleep")),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            with self.assertRaises(OSError):
                with_lock.acquire(self.stream.fileno(), self.lock_path, timeout=None)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("OSError", stderr.getvalue())
        self.assertIn("i/o failure", stderr.getvalue())
        self.assertIn(str(self.lock_path), stderr.getvalue())

    def test_waiting_prints_only_initially_and_when_holder_changes(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        sleep_calls = 0

        def fake_sleep(_seconds: float) -> None:
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls == 3:
                self.lock_path.write_text("pid=202\n", encoding="utf-8")

        flock_results = [
            BlockingIOError(errno.EAGAIN, "busy"),
            BlockingIOError(errno.EAGAIN, "busy"),
            BlockingIOError(errno.EAGAIN, "busy"),
            BlockingIOError(errno.EAGAIN, "busy"),
            None,
        ]
        with (
            mock.patch.object(with_lock.fcntl, "flock", side_effect=flock_results),
            mock.patch.object(with_lock.time, "monotonic", side_effect=itertools.count(0.0, 35.0)),
            mock.patch.object(with_lock.time, "sleep", side_effect=fake_sleep),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            acquired = with_lock.acquire(self.stream.fileno(), self.lock_path, timeout=None)

        self.assertTrue(acquired)
        self.assertEqual(stderr.getvalue(), "")
        lines = stdout.getvalue().splitlines()
        self.assertEqual(len(lines), 2, lines)
        self.assertIn("pid=101", lines[0])
        self.assertIn("pid=202", lines[1])


if __name__ == "__main__":
    unittest.main()
