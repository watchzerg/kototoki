"""进程原语（`kototoki.procs`）离线测试：`ProcessLock` 的取锁、残留锁、破锁、并发、`update` 与 `release`。

持有者是否存活经 `alive=` 注入，不启动真实进程；进程身份只读本进程的 `/proc`。子进程随编排器退出的真实路径在
`tests/full/test_procs_children.py`。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

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
        self.alive_calls: list[tuple] = []

    def lock(self, alive=never_alive, info=None) -> ProcessLock:
        def recorded(pid, created) -> bool:
            self.alive_calls.append((pid, created))
            return alive(pid, created)
        return ProcessLock(self.path, "GPU lock", info, alive=recorded)

    def write(self, content: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(content, encoding="utf-8")

    def read(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_acquire_writes_the_owner_payload(self) -> None:
        lock = self.lock(info={"input_dir": "in"})
        lock.acquire()
        self.assertTrue(lock.held)
        payload = self.read()
        self.assertEqual(list(payload), ["pid", "pid_created", "input_dir", "owner", "created_at_utc",
                                         "replaced_stale_lock"])
        self.assertEqual((payload["pid"], payload["pid_created"], payload["owner"], payload["replaced_stale_lock"]),
                         (os.getpid(), lock.created, "kototoki", None))
        self.assertEqual(self.alive_calls, [])

    def test_empty_or_unparseable_lock_is_stale_without_an_owner(self) -> None:
        for content in ("", "{not json", "[1, 2]"):
            with self.subTest(content=content):
                self.write(content)
                with self.assertRaisesRegex(LockError, r"Stale GPU lock .* with no owner pid \(empty or unparseable\); "
                                                       r"set KOTOTOKI_BREAK_STALE_LOCK=1"):
                    self.lock().acquire()
                self.assertEqual(self.path.read_text(encoding="utf-8"), content)  # 默认不动残留锁
                lock = self.lock()
                lock.acquire(break_stale=True)
                self.assertEqual(self.read()["replaced_stale_lock"], {"unparseable": True})
                self.assertEqual(lock.stale, {"unparseable": True})
                self.path.unlink()
        self.assertEqual(self.alive_calls, [])  # 没有 pid 就不问存活

    def test_external_lock_without_pid_created_is_checked_by_pid_alone(self) -> None:
        # 研究侧写入方只记 pid：存活检查拿到 created=None，存活即拒绝，从不抢占。
        text = json.dumps({"pid": OTHER_PID, "owner": "research"})
        self.write(text)
        for break_stale in (False, True):
            with self.subTest(break_stale=break_stale):
                with self.assertRaisesRegex(LockError, rf"held by live pid {OTHER_PID}; not starting"):
                    self.lock(alive=lambda pid, created: True).acquire(break_stale=break_stale)
                self.assertEqual(self.path.read_text(encoding="utf-8"), text)
        self.assertEqual(self.alive_calls, [(OTHER_PID, None)] * 2)

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
        self.assertEqual(self.alive_calls, [(OTHER_PID, 7)] * 2)

    def test_non_integer_pid_counts_as_no_owner(self) -> None:
        self.write(json.dumps({"pid": "123"}))
        with self.assertRaisesRegex(LockError, "with no owner pid"):
            self.lock(alive=lambda pid, created: True).acquire()
        self.assertEqual(self.alive_calls, [])

    def test_concurrent_take_is_a_lock_error(self) -> None:
        lock = self.lock()
        with mock.patch("kototoki.procs.os.open", side_effect=FileExistsError):
            with self.assertRaisesRegex(LockError, "was taken concurrently"):
                lock.acquire()
        self.assertFalse(lock.held)

    def test_update_only_when_held_and_still_ours(self) -> None:
        lock = self.lock()
        lock.update(worker_pid=1)  # 未持有：不建文件
        self.assertFalse(self.path.exists())
        lock.acquire()
        lock.update(worker_pid=1, worker_stage="vad")
        self.assertEqual((self.read()["worker_pid"], self.read()["worker_stage"]), (1, "vad"))
        lock.update(worker_pid=None)
        self.assertIsNone(self.read()["worker_pid"])
        foreign = json.dumps({"pid": OTHER_PID})
        self.write(foreign)  # 锁文件已换了主人：不改别人的锁
        lock.update(server_pid=2)
        self.assertEqual(self.path.read_text(encoding="utf-8"), foreign)

    def test_release_only_deletes_its_own_lock(self) -> None:
        lock = self.lock()
        lock.release()  # 未持有：无事发生
        self.assertFalse(self.path.exists())

        for other in ({"pid": OTHER_PID, "pid_created": lock.created},     # 别的进程
                      {"pid": os.getpid(), "pid_created": "reused"}):      # 同 pid、不同创建时间
            with self.subTest(other=other):
                lock.acquire()
                text = json.dumps(other)
                self.write(text)  # 持有期间锁文件被换掉
                lock.release()
                self.assertFalse(lock.held)
                self.assertEqual(self.path.read_text(encoding="utf-8"), text)
                self.path.unlink()

        lock.acquire()
        lock.release()
        self.assertFalse(self.path.exists())
        self.assertFalse(lock.held)



class ProcessIdentityTests(unittest.TestCase):
    def test_start_time_identifies_this_process(self) -> None:
        created = procs.process_created(os.getpid())
        self.assertIsInstance(created, int)
        self.assertTrue(procs.process_matches(os.getpid(), created))
        self.assertFalse(procs.process_matches(os.getpid(), created + 1))  # 同 pid、不同启动时间：pid 被复用

    def test_comm_with_spaces_and_parens_is_skipped(self) -> None:
        stat = "4242 (a) b (c) S 1 4242 4242 0 -1 4194560 0 0 0 0 0 0 0 0 20 0 1 0 777 0 0"
        with mock.patch.object(procs.Path, "read_text", return_value=stat):
            self.assertEqual(procs.process_created(4242), 777)

    def test_missing_or_invalid_pid_has_no_identity(self) -> None:
        for pid in (0, -1, "1", None):
            self.assertIsNone(procs.process_created(pid))
            self.assertFalse(procs.pid_alive(pid))

    def test_contained_prefixes_setpriv(self) -> None:
        self.assertEqual(procs.contained(["ffmpeg", "-version"]),
                         ["setpriv", "--pdeathsig", "KILL", "--", "ffmpeg", "-version"])


if __name__ == "__main__":
    unittest.main()
