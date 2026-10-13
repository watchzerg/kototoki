from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest

from kototoki import artifacts
from kototoki.workers import protocol as p


class ProtocolCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.stream = io.BytesIO()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def jobs(self, *ids: str) -> p.Jobs:
        files = tuple(p.FileJob(i, self.root / i, {"wav": self.root / i / "audio-16k.wav"}) for i in ids)
        for job in files:
            job.work_dir.mkdir()
        return p.Jobs("asr", "f" * 64, {"engine": "w0"}, files)

    def events(self) -> list[dict]:
        return [json.loads(line) for line in self.stream.getvalue().decode("utf-8").splitlines()]


class JobsFileTests(ProtocolCase):
    def test_round_trip(self) -> None:
        jobs = self.jobs("a1", "b2")
        path = self.root / "batch.json"
        p.write_jobs(path, jobs)
        self.assertEqual(p.read_jobs(path), jobs)

    def test_rejects_malformed_jobs(self) -> None:
        good = {"stage": "vad", "recipe_hash": "x", "config": {},
                "files": [{"id": "a", "work_dir": "w", "inputs": {"wav": "w/a.wav"}}]}
        bad = [
            [],
            {**good, "extra": 1},
            {**good, "stage": ""},
            {**good, "config": []},
            {**good, "files": [{"id": "a", "work_dir": "w"}]},
            {**good, "files": [{"id": "a", "work_dir": "w", "inputs": {"wav": 3}}]},
            {**good, "files": good["files"] * 2},
        ]
        p.parse_jobs(good)
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                p.parse_jobs(value)


class RunTests(ProtocolCase):
    def test_all_done_exits_zero_with_one_utf8_line_per_file(self) -> None:
        code = p.run_jobs(self.jobs("a", "b"), lambda job: {"windows": 3, "note": "完了"}, stream=self.stream)
        self.assertEqual(code, p.EXIT_OK)
        self.assertEqual(self.events(), [{"windows": 3, "note": "完了", "event": "done", "id": "a"},
                                         {"windows": 3, "note": "完了", "event": "done", "id": "b"}])

    def test_single_file_failure_is_isolated(self) -> None:
        seen = []

        def process(job: p.FileJob) -> None:
            seen.append(job.id)
            if job.id == "b":
                raise ValueError("bad window")

        jobs = self.jobs("a", "b", "c")
        self.assertEqual(p.run_jobs(jobs, process, stream=self.stream), p.EXIT_PARTIAL)
        self.assertEqual(seen, ["a", "b", "c"])
        self.assertEqual([(e["event"], e["id"]) for e in self.events()], [("done", "a"), ("failed", "b"), ("done", "c")])
        failure = artifacts.read_json(self.root / "b" / artifacts.FAILURE)
        self.assertEqual((failure["stage"], failure["error_type"]), ("asr", "ValueError"))
        self.assertFalse((self.root / "a" / artifacts.FAILURE).exists())

    def test_fatal_error_stops_with_exit_two(self) -> None:
        seen = []

        def process(job: p.FileJob) -> None:
            seen.append(job.id)
            if job.id == "b":
                raise p.FatalWorkerError("CUDA error: an illegal memory access was encountered")

        self.assertEqual(p.run_jobs(self.jobs("a", "b", "c"), process, stream=self.stream), p.EXIT_FATAL)
        self.assertEqual(seen, ["a", "b"])
        self.assertEqual(self.events()[-1], {"event": "fatal", "id": "b", "error_type": "FatalWorkerError"})
        self.assertTrue((self.root / "b" / artifacts.FAILURE).exists())

    def test_startup_failures_exit_two(self) -> None:
        missing = self.root / "missing.json"
        self.assertEqual(p.run_worker(missing, lambda jobs: lambda job: None, stream=self.stream), p.EXIT_FATAL)
        path = self.root / "batch.json"
        p.write_jobs(path, self.jobs("a"))

        def start(jobs: p.Jobs):
            raise RuntimeError("model load failed")

        self.assertEqual(p.run_worker(path, start, stream=self.stream), p.EXIT_FATAL)
        self.assertEqual([e["event"] for e in self.events()], ["startup_failed", "startup_failed"])

    def test_run_worker_loads_once(self) -> None:
        path = self.root / "batch.json"
        p.write_jobs(path, self.jobs("a", "b"))
        loads = []

        def start(jobs: p.Jobs):
            loads.append(jobs.stage)
            return lambda job: None

        self.assertEqual(p.run_worker(path, start, stream=self.stream), p.EXIT_OK)
        self.assertEqual(loads, ["asr"])


class FailedWindowTests(unittest.TestCase):
    def asr(self) -> dict:
        return {"original_segments": [{"text": "こんにちは"}, {"text": "ああああ…"}, {"text": "さようなら"}],
                "failed_windows": []}

    def test_failed_window_text_is_emptied_and_recorded(self) -> None:
        asr = self.asr()
        p.fail_window(asr, 1, "token_limit_reached")
        self.assertEqual(asr["original_segments"][1]["text"], "")
        self.assertEqual(asr["failed_windows"], [{"chunk_index": 1, "reason": "token_limit_reached", "text": "ああああ…"}])
        self.assertEqual(p.retained_text(asr), "こんにちはさようなら")
        p.validate_failed_windows(asr)

    def test_fail_window_rejects_bad_requests(self) -> None:
        asr = self.asr()
        p.fail_window(asr, 0, "x")
        for index, reason in ((0, "again"), (3, "x"), (-1, "x"), (True, "x"), (2, "")):
            with self.subTest(index=index, reason=reason), self.assertRaises(ValueError):
                p.fail_window(asr, index, reason)

    def test_validate_rejects_inconsistent_records(self) -> None:
        missing = self.asr()
        del missing["failed_windows"]
        nonempty = self.asr()
        nonempty["failed_windows"] = [{"chunk_index": 0, "reason": "x", "text": "t"}]
        duplicate = self.asr()
        duplicate["original_segments"][0]["text"] = ""
        duplicate["failed_windows"] = [{"chunk_index": 0, "reason": "x", "text": ""}] * 2
        for asr in (missing, nonempty, duplicate):
            with self.assertRaises(ValueError):
                p.validate_failed_windows(asr)
        p.validate_failed_windows(self.asr())


if __name__ == "__main__":
    unittest.main()
