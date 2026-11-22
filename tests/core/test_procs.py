"""进程原语（`kototoki.procs`）离线测试：`ProcessLock` 的存活持有者拒绝、残留锁默认不破、只删自己的锁，以及进程身份。

持有者是否存活经 `alive=` 注入，不启动真实进程。子进程随编排器退出的真实路径在 `tests/full/test_procs_children.py`。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from kototoki import procs
from kototoki.procs import LockError, ProcessLock

OTHER_PID = 424242


def never_alive(pid, created) -> bool:
    return False


class ProcessLockTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "sub" / "gpu.lock"

    def lock(self, alive=never_alive) -> ProcessLock:
        return ProcessLock(self.path, "GPU lock", None, alive=alive)

    def write(self, content: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(content, encoding="utf-8")

    def read(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_live_owner_is_never_preempted(self) -> None:
        text = json.dumps({"pid": OTHER_PID, "owner": "research"})
        self.write(text)
        for break_stale in (False, True):
            with self.subTest(break_stale=break_stale):
                with self.assertRaisesRegex(LockError, rf"held by live pid {OTHER_PID}; not starting"):
                    self.lock(alive=lambda pid, created: True).acquire(break_stale=break_stale)
                self.assertEqual(self.path.read_text(encoding="utf-8"), text)

    def test_dead_owner_is_refused_unless_break_stale(self) -> None:
        old = {"pid": OTHER_PID, "pid_created": 7, "owner": "kototoki"}
        self.write(json.dumps(old))
        with self.assertRaisesRegex(LockError, rf"Stale GPU lock .* from dead pid {OTHER_PID}"):
            self.lock().acquire()
        self.assertEqual(self.read(), old)
        lock = self.lock()
        lock.acquire(break_stale=True)
        self.assertTrue(lock.held)
        self.assertEqual((self.read()["pid"], self.read()["replaced_stale_lock"]), (os.getpid(), old))

    def test_release_only_deletes_its_own_lock(self) -> None:
        lock = self.lock()
        lock.acquire()
        text = json.dumps({"pid": OTHER_PID, "pid_created": lock.created})
        self.write(text)  # 持有期间锁文件被换成别的进程
        lock.release()
        self.assertEqual(self.path.read_text(encoding="utf-8"), text)
        self.path.unlink()
        lock.acquire()
        lock.release()
        self.assertFalse(self.path.exists())


class ProcessIdentityTests(unittest.TestCase):
    def test_start_time_identifies_this_process(self) -> None:
        created = procs.process_created(os.getpid())
        self.assertIsInstance(created, int)
        self.assertTrue(procs.process_matches(os.getpid(), created))
        self.assertFalse(procs.process_matches(os.getpid(), created + 1))  # 同 pid、不同启动时间：pid 被复用


if __name__ == "__main__":
    unittest.main()
