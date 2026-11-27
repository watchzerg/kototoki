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


class RunTests(ProtocolCase):
    def test_single_file_failure_is_isolated(self) -> None:
        seen = []

        def process(job: p.FileJob) -> None:
            seen.append(job.id)
            if job.id == "b":
                raise ValueError("bad window")

        jobs = self.jobs("a", "b", "c")
        with self.assertLogs("kototoki.workers.protocol", "ERROR") as logs:
            self.assertEqual(p.run_jobs(jobs, process, stream=self.stream), p.EXIT_PARTIAL)
        self.assertEqual([(r.getMessage(), r.exc_info[0]) for r in logs.records],
                         [("[asr] FAILED b: ValueError", ValueError)])
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

        with self.assertLogs("kototoki.workers.protocol", "ERROR") as logs:
            self.assertEqual(p.run_jobs(self.jobs("a", "b", "c"), process, stream=self.stream), p.EXIT_FATAL)
        self.assertEqual([(r.getMessage(), r.exc_info[0]) for r in logs.records],
                         [("[asr] FATAL b: FatalWorkerError", p.FatalWorkerError)])
        self.assertEqual(seen, ["a", "b"])
        self.assertEqual(self.events()[-1], {"event": "fatal", "id": "b", "error_type": "FatalWorkerError"})
        self.assertTrue((self.root / "b" / artifacts.FAILURE).exists())

    def test_run_worker_emits_started_before_file_events(self) -> None:
        jobs_path = self.root / "jobs.json"
        p.write_jobs(jobs_path, self.jobs("a", "b"))
        self.assertEqual(p.run_worker(jobs_path, lambda jobs: (lambda job: None), stream=self.stream), p.EXIT_OK)
        self.assertEqual(self.events(),
                         [{"event": "started"}, {"event": "done", "id": "a"}, {"event": "done", "id": "b"}])


class ClassifyLaunchTests(unittest.TestCase):
    IDS = ("a", "b", "c", "d")

    @staticmethod
    def done(*ids: str) -> list[dict]:
        return [{"event": "done", "id": i, "stage": "asr"} for i in ids]

    def test_partial_failure_reports_failed_ids_without_restart(self) -> None:
        events = [*self.done("a"), {"event": "failed", "id": "b", "error_type": "ValueError"}, *self.done("c"),
                  {"event": "failed", "id": "d", "error_type": "ValueError"}]
        self.assertEqual(p.classify_launch(self.IDS, p.EXIT_PARTIAL, events),
                         p.LaunchOutcome(("b", "d"), None, False, None, (), {"b": "ValueError", "d": "ValueError"}))

    def test_fatal_marks_that_id_and_restarts_after_it(self) -> None:
        events = [*self.done("a"), {"event": "fatal", "id": "b", "error_type": "FatalWorkerError"}]
        self.assertEqual(p.classify_launch(self.IDS, p.EXIT_FATAL, events),
                         p.LaunchOutcome((), "b", True, None, ("c", "d"), {"b": "FatalWorkerError"}))

    def test_crash_blames_the_id_after_the_last_handled_one(self) -> None:
        events = [*self.done("a"), {"event": "failed", "id": "b", "error_type": "ValueError"}]
        self.assertEqual(p.classify_launch(self.IDS, 3, events), p.LaunchOutcome(("b",), "c", False, None, ("d",), {"b": "ValueError"}))

    def test_crash_before_started_is_startup_failure_without_restart(self) -> None:
        self.assertEqual(p.classify_launch(self.IDS, 3, []),
                         p.LaunchOutcome((), None, False, "exited with code 3", ()))

    def test_crash_after_started_without_file_events_blames_first_id(self) -> None:
        self.assertEqual(p.classify_launch(self.IDS, 3, [{"event": "started"}]),
                         p.LaunchOutcome((), "a", False, None, ("b", "c", "d")))


class ProgressEventTests(unittest.TestCase):
    def test_lifecycle_events_are_not_forwarded(self) -> None:
        for name in ("started", "failed", "fatal", "startup_failed"):
            self.assertIsNone(p.progress_event({"event": name, "id": "a", "error_type": "ValueError"}), name)

    def test_done_carries_numeric_counts_but_not_bools_or_text(self) -> None:
        event = {"event": "done", "id": "a", "windows": 3, "ratio": 0.5, "ok": True, "stage": "asr"}
        self.assertEqual(p.progress_event(event), ("done", {"windows": 3, "ratio": 0.5}))

    def test_other_events_are_forwarded_without_counts(self) -> None:
        self.assertEqual(p.progress_event({"event": "tick", "id": "a", "n": 1}), ("tick", {}))


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


if __name__ == "__main__":
    unittest.main()
