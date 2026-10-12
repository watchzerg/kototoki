"""Native Windows process tests with local Python only; no Codex/model calls."""
from concurrent.futures import ThreadPoolExecutor
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from . import v2_judge_dispatch as dispatch


@unittest.skipUnless(os.name == "nt", "Native Windows containment only")
class NativeDispatchTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[2] / ".local" / "native-judge-dispatch-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cwd = self.root / "空 目录"
        self.cwd.mkdir()
        self.receipt = self.root / "terminal.json"
        self.receipt.write_text(json.dumps({"schema": "hy30-judge-core-terminal-receipt-v1",
            "owner": "evaluation_custodian", "core_pipeline_terminal": True,
            "native_children_drained": True, "owned_cli_batches": []}), encoding="utf-8")
        self.digest = hashlib.sha256(self.receipt.read_bytes()).hexdigest()

    def guard(self, workers=1):
        return dispatch.CustodyGuard(self.root, workers, self.receipt, self.digest)

    def attempt(self, name="attempt"):
        path = self.root / name
        path.mkdir()
        return path

    def open_process(self, pid):
        k = dispatch._kernel()
        k.OpenProcess.argtypes, k.OpenProcess.restype = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE
        handle = k.OpenProcess(0x100000, False, pid)
        self.assertTrue(handle, ctypes.get_last_error())
        self.addCleanup(k.CloseHandle, handle)
        return handle

    def test_roundtrip_utf8_stdin_and_exact_binary_logs_hidden_native_root(self):
        out = b'{"type":"turn.completed","model":"gpt-6.1-sol","reasoning_effort":"high"}\n\xff\n'
        err = b'synthetic stderr\r\n\xfe'
        stdin_copy = self.root / "stdin-copy.bin"
        code = f"import os,sys,pathlib; pathlib.Path({str(stdin_copy)!r}).write_bytes(sys.stdin.buffer.read()); os.write(1,{out!r}); os.write(2,{err!r}); sys.exit(7)"
        attempt = self.attempt()
        with self.guard() as guard:
            result = guard.execute([sys.executable, "-B", "-c", code], "合成输入🌧️", self.cwd, attempt, 5)
        self.assertEqual(result["transport_status"], "completed")
        self.assertEqual(result["returncode"], 7)
        self.assertEqual((attempt / "stdout.jsonl").read_bytes(), out)
        self.assertEqual((attempt / "stderr.txt").read_bytes(), err)
        self.assertEqual(stdin_copy.read_bytes(), "合成输入🌧️".encode())
        self.assertEqual(result["returned_models"], ["gpt-6.1-sol"])
        self.assertEqual(result["native_active_processes_after_drain"], 0)
        self.assertTrue(result["native_drain_proven"])
        owner = json.loads(guard.owner_record.read_text(encoding="utf-8"))
        self.assertEqual(owner["state"], "drained_released")
        self.assertEqual(owner["active_callbacks"], 0)

    def tree_code(self, *, root_sleep):
        ready = self.root / "tree-ready.json"
        child = self.root / "child.py"
        child.write_text("import json,os,pathlib,subprocess,sys,time\n"
            "grand = subprocess.Popen([sys.executable,'-B','-c','import time; time.sleep(120)'])\n"
            f"pathlib.Path({str(ready)!r}).write_text(json.dumps({{'child':os.getpid(),'grandchild':grand.pid}}))\n"
            "time.sleep(120)\n", encoding="utf-8")
        code = "import os,pathlib,subprocess,sys,time\n" + f"child=subprocess.Popen([sys.executable,'-B',{str(child)!r}])\n"
        code += f"ready=pathlib.Path({str(ready)!r})\nwhile not ready.exists(): time.sleep(.01)\n"
        code += "os.write(1,b'native-tree-ready\\n'); os.write(2,b'tree-stderr\\n')\n"
        code += f"time.sleep({root_sleep})\n"
        return code, ready

    def test_timeout_kills_exact_owned_parent_child_grandchild_and_retains_logs(self):
        code, ready = self.tree_code(root_sleep=120)
        attempt = self.attempt()
        k = dispatch._kernel()
        unrelated = subprocess.Popen([sys.executable, "-B", "-c", "import time; time.sleep(120)"],
                                     creationflags=subprocess.CREATE_NO_WINDOW)
        def cleanup_unrelated():
            if unrelated.poll() is None:
                unrelated.terminate()
            unrelated.wait(timeout=5)
        self.addCleanup(cleanup_unrelated)
        with self.guard() as guard, ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(guard.execute, [sys.executable, "-B", "-c", code], "", self.cwd, attempt, 2)
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(ready.exists())
            pids = json.loads(ready.read_text())
            child_handle = self.open_process(pids["child"])
            grand_handle = self.open_process(pids["grandchild"])
            self.assertEqual(k.WaitForSingleObject(grand_handle, 0), 258)
            result = future.result(timeout=5)
            self.assertEqual(k.WaitForSingleObject(child_handle, 0), 0)
            self.assertEqual(k.WaitForSingleObject(grand_handle, 0), 0)
            self.assertEqual(guard.active_callbacks, 0)
            self.assertIsNone(unrelated.poll(), "An unrelated owned test process was incorrectly terminated")
        self.assertEqual(result["transport_status"], "timeout")
        self.assertIsNone(result["returncode"])
        self.assertEqual(result["native_active_processes_after_drain"], 0)
        self.assertEqual((attempt / "stdout.jsonl").read_bytes(), b"native-tree-ready\n")
        self.assertEqual((attempt / "stderr.txt").read_bytes(), b"tree-stderr\n")

    def test_normal_root_exit_drains_lingering_children_before_return(self):
        code, ready = self.tree_code(root_sleep=.3)
        attempt = self.attempt()
        k = dispatch._kernel()
        with self.guard() as guard, ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(guard.execute, [sys.executable, "-B", "-c", code], "", self.cwd, attempt, 5)
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            pids = json.loads(ready.read_text())
            grand_handle = self.open_process(pids["grandchild"])
            result = future.result(timeout=5)
            self.assertEqual(k.WaitForSingleObject(grand_handle, 0), 0)
        self.assertEqual(result["transport_status"], "completed")
        self.assertEqual(result["returncode"], 0)
        self.assertTrue(result["native_drain_proven"])

    def test_assignment_failure_never_resumes_root(self):
        sentinel = self.root / "must-not-run"
        code = f"import pathlib; pathlib.Path({str(sentinel)!r}).write_text('ran')"
        with self.guard() as guard, patch.object(dispatch._NativeJob, "_assign", side_effect=OSError("synthetic assignment failure")):
            result = guard.execute([sys.executable, "-B", "-c", code], "", self.cwd, self.attempt(), 5)
        self.assertEqual(result["transport_status"], "spawn_failed")
        self.assertFalse(sentinel.exists())
        self.assertTrue(result["native_drain_proven"])
        self.assertEqual(result["native_active_processes_after_drain"], 0)

    def test_invalid_spawn_and_shell_shims_return_explicit_transport_failure(self):
        with self.guard() as guard:
            for index, args in enumerate(([str(self.root / "missing.exe")], ["unexpected.cmd"], [])):
                result = guard.execute(args, "", self.cwd, self.attempt(f"invalid-{index}"), 5)
                self.assertEqual(result["transport_status"], "spawn_failed")
                self.assertIsNone(result["returncode"])
                self.assertTrue((self.root / f"invalid-{index}/stderr.txt").read_bytes())

    def test_second_guard_same_process_rejected_and_exception_releases(self):
        with self.assertRaisesRegex(RuntimeError, "synthetic owner error"):
            with self.guard():
                with self.assertRaises(ValueError):
                    with self.guard(6):
                        self.fail("Concurrent second six-slot reservation accepted")
                raise RuntimeError("synthetic owner error")
        with self.guard(6) as guard:
            self.assertTrue(guard.entered)

    def test_owner_exception_drains_live_descendants_before_guard_release(self):
        code, ready = self.tree_code(root_sleep=120)
        attempt = self.attempt()
        k = dispatch._kernel()
        guard = self.guard()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.assertRaisesRegex(RuntimeError, "synthetic owner interruption"):
                with guard:
                    future = pool.submit(guard.execute, [sys.executable, "-B", "-c", code], "", self.cwd, attempt, 20)
                    deadline = time.monotonic() + 5
                    while not ready.exists() and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertTrue(ready.exists())
                    grand_handle = self.open_process(json.loads(ready.read_text())["grandchild"])
                    raise RuntimeError("synthetic owner interruption")
            self.assertTrue(future.done())
            self.assertEqual(k.WaitForSingleObject(grand_handle, 0), 0)
            self.assertEqual(guard.active_callbacks, 0)
            self.assertFalse(guard.jobs)
        with self.guard():
            pass

    def test_callback_overflow_rejected_while_exact_reserved_slot_busy(self):
        ready = self.root / "slot-ready"
        code = f"import pathlib,time; pathlib.Path({str(ready)!r}).write_text('ready'); time.sleep(.5)"
        with self.guard() as guard, ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(guard.execute, [sys.executable, "-B", "-c", code], "", self.cwd, self.attempt("busy"), 5)
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(ready.exists())
            with self.assertRaisesRegex(ValueError, "exceeds reserved global slots"):
                guard.execute([sys.executable, "-B", "-c", "pass"], "", self.cwd, self.attempt("overflow"), 5)
            self.assertEqual(future.result(timeout=5)["returncode"], 0)

    def test_receipt_change_after_entry_blocks_next_dispatch(self):
        with self.guard() as guard:
            self.receipt.write_bytes(self.receipt.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "receipt bytes changed"):
                guard.execute([sys.executable, "-B", "-c", "pass"], "", self.cwd, self.attempt(), 5)

    def test_cross_process_shared_lock_rejects_independent_six_slot_guard(self):
        repo = Path(__file__).resolve().parents[2]
        code = ("import sys;sys.dont_write_bytecode=True;sys.path.insert(0," + repr(str(repo)) + ");"
                "from pathlib import Path;from experiments.translation_flow.v2_judge_dispatch import CustodyGuard;"
                "g=CustodyGuard(Path(" + repr(str(self.root)) + "),6,Path(" + repr(str(self.receipt)) + ")," + repr(self.digest) + ");"
                "g.__enter__()")
        with self.guard():
            result = subprocess.run([sys.executable, "-B", "-c", code], cwd=self.cwd, capture_output=True,
                                    timeout=5, creationflags=subprocess.CREATE_NO_WINDOW, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"Shared global six-slot reservation", result.stderr)

    def test_guard_rejects_nonterminal_core_owned_batch_or_changed_receipt(self):
        for field, value in (("core_pipeline_terminal", False), ("native_children_drained", False),
                             ("owned_cli_batches", [{"pid": 1}])):
            receipt = json.loads(self.receipt.read_text())
            receipt[field] = value
            self.receipt.write_text(json.dumps(receipt))
            digest = hashlib.sha256(self.receipt.read_bytes()).hexdigest()
            with self.subTest(field=field), self.assertRaises(ValueError):
                with dispatch.CustodyGuard(self.root, 1, self.receipt, digest):
                    self.fail("Nonterminal core accepted")
        with self.assertRaises(ValueError):
            with self.guard():
                self.fail("Changed terminal receipt accepted")

    def test_reserved_limit_and_execute_outside_guard(self):
        for workers in (0, 7, True):
            with self.assertRaises(ValueError):
                self.guard(workers)
        with self.assertRaises(ValueError):
            dispatch.execute([sys.executable], "", self.cwd, self.attempt(), 1)
        guard = self.guard()
        with self.assertRaises(ValueError):
            guard.execute([sys.executable], "", self.cwd, self.attempt("outside"), 1)


if __name__ == "__main__":
    unittest.main()
