import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from experiments.translation_v3 import data, status
from experiments.translation_v3.cli import run_finished
from experiments.translation_v3.common import atomic_write_json, atomic_write_jsonl, read_json, replace_with_retry
from experiments.translation_v3.procs import KillOnCloseJob, process_created, process_matches
from experiments.translation_v3.server import GpuLock, LockError, server_command, verify_model
from experiments.translation_v3.test_support import reference_windows, write_fake_run


class LockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "gpu.lock"

    def tearDown(self):
        self.tmp.cleanup()

    def test_acquire_release_and_live_holder(self):
        lock = GpuLock("run-a", self.path, alive=lambda pid, created: True, pid=111)
        lock.acquire()
        self.assertEqual(read_json(self.path)["run_id"], "run-a")
        with self.assertRaises(LockError):
            GpuLock("run-b", self.path, alive=lambda pid, created: True, pid=222).acquire(break_stale=True)
        lock.release()
        self.assertFalse(self.path.exists())

    def test_stale_lock_requires_flag(self):
        GpuLock("old", self.path, alive=lambda pid, created: False, pid=5).acquire()
        with self.assertRaisesRegex(LockError, "break-stale-lock"):
            GpuLock("new", self.path, alive=lambda pid, created: False, pid=6).acquire()
        lock = GpuLock("new", self.path, alive=lambda pid, created: False, pid=6)
        lock.acquire(break_stale=True)
        self.assertEqual(read_json(self.path)["replaced_stale_lock"]["run_id"], "old")
        self.assertEqual(lock.stale["pid"], 5)

    def test_foreign_lock_refused_and_not_released(self):
        self.path.write_text("busy by someone", encoding="utf-8")
        with self.assertRaisesRegex(LockError, "not a v3 lock"):
            GpuLock("x", self.path, alive=lambda pid, created: False).acquire(break_stale=True)
        other = GpuLock("x", self.path, pid=1)
        other.held = True
        other.release()
        self.assertTrue(self.path.exists())


class ServerHelpersTest(unittest.TestCase):
    def test_command_matches_c0_runtime(self):
        cmd = server_command(Path("e.exe"), Path("m.gguf"), 8080, Path("s.log"))
        for flag, value in (("-c", "8192"), ("-np", "1"), ("-ngl", "99"), ("-b", "256"), ("-ub", "128"),
                            ("-t", "8"), ("-tb", "8"), ("-ctk", "f16"), ("-fa", "on"), ("--fit", "off"), ("--cache-ram", "8192")):
            self.assertEqual(cmd[cmd.index(flag) + 1], value)

    def test_model_verification_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "m.gguf"
            model.write_bytes(b"weights")
            calls = []
            hasher = lambda p: calls.append(p) or "abc"
            cache = Path(tmp) / "cache.json"
            self.assertEqual(verify_model(model, "abc", cache, hasher=hasher)["method"], "computed")
            self.assertEqual(verify_model(model, "abc", cache, hasher=hasher)["method"], "cached-size-mtime")
            self.assertEqual(len(calls), 1)
            model.write_bytes(b"changed!")
            with self.assertRaises(ValueError):
                verify_model(model, "zzz", cache, hasher=hasher)


class StatusTest(unittest.TestCase):
    def test_status_is_derived_from_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, scenes = reference_windows()
            write_fake_run(root, "c0__s20261008__screening", scenes)
            partial = write_fake_run(root, "tok400__s20261008__screening", scenes)
            (partial / "scenes" / f"{scenes[0].scene_id}.json").unlink()
            status.add_job(root, "c0", 20261008, "screening")
            status.add_job(root, "tok400", 20261008, "screening")
            status.add_job(root, "tok400", 20261008, "screening")
            atomic_write_json(root / "judge-blocked.json", {"at_utc": "x"})
            lock = root / "gpu.lock"
            lock.write_text(json.dumps({"pid": 4242, "pid_created": 9, "run_id": "tok400__s20261008__screening",
                                        "server_pid": 5151, "server_created": 10}), encoding="utf-8")
            (root / "judge-queue-confirmation").mkdir()
            (root / "judge-queue-confirmation" / "p0.md").write_text("secret reference text", encoding="utf-8")
            alive = lambda pid, created: pid == 5151 and created == 10
            result = status.derive_status(root, lock_path=lock, alive=alive, list_servers=lambda: [5151])
            self.assertEqual([j["state"] for j in result["queue"]], ["complete", "partial"])
            runs = {r["run_id"]: r for r in result["runs"]}
            self.assertEqual(runs["tok400__s20261008__screening"]["scenes_missing"], 1)
            self.assertFalse(result["gpu_lock"]["pid_alive"])
            self.assertTrue(result["gpu_lock"]["server_alive"])
            self.assertEqual([o["pid"] for o in result["orphan_llama_servers"]], [5151])
            self.assertEqual(result["confirmation_judge_queue_files"], 1)
            self.assertNotIn("secret reference text", json.dumps(result, ensure_ascii=False))
            text = "\n".join(result["next_actions"])
            self.assertIn("stale gpu.lock", text)
            self.assertIn("not owned by a live v3 process", text)
            self.assertIn("judge blocked", text)
            self.assertIn("run-queue", text)
            self.assertIn("judge --run c0__s20261008__screening", text)
            # A live owner owns its server: no orphan reported.
            owner_alive = lambda pid, created: True
            result = status.derive_status(root, lock_path=lock, alive=owner_alive, list_servers=lambda: [5151])
            self.assertEqual(result["orphan_llama_servers"], [])

    def test_pid_reuse_is_not_a_live_owner(self):
        me = os.getpid()
        self.assertTrue(process_matches(me, process_created(me)))
        if sys.platform == "win32":
            self.assertFalse(process_matches(me, (process_created(me) or 0) + 1))

    def test_run_queue_retries_legacy_infra_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, scenes = reference_windows()
            run = write_fake_run(root, "c0__s1__screening", scenes)
            self.assertTrue(run_finished(run))
            path = run / "scenes" / f"{scenes[0].scene_id}.json"
            atomic_write_json(path, read_json(path) | {"status": "failed", "failure": {"kind": "server", "fatal": True}})
            self.assertFalse(run_finished(run))
            self.assertEqual(status.run_state(run)["state"], "partial")


class AtomicWriteTest(unittest.TestCase):
    def test_permission_error_is_retried(self):
        calls, sleeps = [], []
        def flaky(source, target):
            calls.append(1)
            if len(calls) < 4:
                raise PermissionError("sharing violation")
            os.replace(source, target)
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "a", Path(tmp) / "b"
            source.write_text("x", encoding="utf-8")
            replace_with_retry(source, target, replace=flaky, sleep=sleeps.append)
            self.assertEqual(target.read_text(encoding="utf-8"), "x")
            self.assertEqual(len(sleeps), 3)
            source.write_text("y", encoding="utf-8")
            def always(source, target):
                raise PermissionError("locked")
            with self.assertRaises(PermissionError):
                replace_with_retry(source, target, replace=always, sleep=lambda s: None)


@unittest.skipUnless(sys.platform == "win32", "Windows Job Objects")
class JobObjectTest(unittest.TestCase):
    def test_closing_job_kills_assigned_child(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            job = KillOnCloseJob()
            self.assertTrue(job.assign(child))
            job.close()
            self.assertIsNotNone(child.wait(timeout=10))
        finally:
            if child.poll() is None:
                child.kill()


class FreezeReferenceTest(unittest.TestCase):
    def build(self, root: Path, drop: bool = False) -> None:
        units = [{"id": f"J{i}", "ja": f"日{i}", "zh": f"中{i}", "original_zh": f"原{i}", "score": 3 <= i < 8,
                  "start": float(i), "end": i + 0.5} for i in range(20)]
        window = {"window_id": "W-Q1", "scene_id": "W-S1", "work_id": "W01", "work": "w", "category": "anime_series",
                  "split": "screen-a", "selection_type": "representative", "risk_tags": [], "scored_ids": [f"J{i}" for i in range(3, 8)],
                  "units": units}
        atomic_write_jsonl(root / "v1/reference/windows.jsonl", [window])
        rows = [{"window_id": "W-Q1", "unit_id": f"J{i}", "split": "screen-a", "ja": f"日{i}", "original_zh": f"原{i}",
                 "zh_v1": f"中{i}", "zh_v3": f"新{i}", "changed": i == 4, "change_type": None, "confidence": "high",
                 "confidence_reason_zh": "r", "ambiguity_zh": None} for i in range(3, 8 - drop)]
        atomic_write_jsonl(root / "reference-review/shard-1.jsonl", rows)

    def test_freeze_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build(root)
            summary = data.freeze_reference(root, root / "v1")
            self.assertEqual(summary["counts"]["units"], 5)
            self.assertEqual(summary["counts"]["changed"], 1)
            self.assertTrue(data.freeze_reference(root, root / "v1")["already_frozen"])
            loaded = data.load_reference_v3(root)["W-Q1"]
            self.assertEqual([u["zh"] for u in loaded.units][0], "新3")
            self.assertEqual(len(loaded.context), 16)  # 3..7 scored, +-8 clipped at 0

    def test_missing_unit_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build(root, drop=True)
            with self.assertRaisesRegex(ValueError, "lack a review row"):
                data.freeze_reference(root, root / "v1")


if __name__ == "__main__":
    unittest.main()
