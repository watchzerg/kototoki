"""Offline budget, restart, and failure checks with fake judge transports."""

from pathlib import Path
import tempfile
import unittest

from experiments.translation_eval.runner import dump, dump_jsonl, load_jsonl, read_json, sha
from .judge_loop import TOKENS_PER_ATTEMPT, attempt_counts, orchestrate


class JudgeLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch = Path(__file__).resolve().parents[2] / ".local/translation-judge-loop-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(self.temp.name)
        self.now = 1000.0
        self.invocations = []
        self.failed = False
        self.halt_after_primary = False
        self.build()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def build(self, windows: int = 2) -> None:
        expected, jobs = [], []
        for index in range(windows):
            wid = f"w{index}"
            expected.append({"candidate_alias": "c1", "window_id": wid, "structural_status": "valid"})
            jobs.append({"job_id": f"primary/c1/{wid}", "window_id": wid, "candidate_alias": "c1"})
        dump_jsonl(self.root / "expected.jsonl", expected)
        dump_jsonl(self.root / "jobs.jsonl", jobs)
        dump(self.root / "run.json", {"judge_requested": {"model": "gpt-6.1-sol", "effort": "high"},
                                      "expected_sha256": sha(self.root / "expected.jsonl")})

    def fake_run(self, root: Path, path: Path, executable: str, workers: int, timeout: float) -> dict:
        jobs = load_jsonl(path)
        self.invocations.append((jobs[0]["job_id"].split("/")[0], len(jobs), workers, timeout))
        failed = 0
        for job in jobs:
            target = root / "judge-execution" / job["job_id"]
            state_path = target / "job.json"
            old = read_json(state_path) if state_path.is_file() else {}
            if old.get("status") == "succeeded":
                continue
            attempts = old.get("attempts", [])
            for number in range(len(attempts) + 1, (3 if self.failed else 2)):
                (target / f"attempt-{number}").mkdir(parents=True)
                attempts.append({"attempt": number, "status": "failed" if self.failed else "succeeded"})
            dump(state_path, {"status": "judge_failed" if self.failed else "succeeded", "attempts": attempts})
            failed += self.failed
        self.now += 1
        return {"judge_failed": failed, "not_run": 0}

    def fake_finalize(self, root: Path, selection_only: bool = False) -> None:
        primary = load_jsonl(root / "jobs.jsonl")
        if selection_only:
            dump_jsonl(root / "jobs-review.jsonl", [dict(job, job_id=job["job_id"].replace("primary/", "review/"))
                                                     for job in primary])
            if self.halt_after_primary:
                self.now += 1000
        else:
            dump_jsonl(root / "jobs-adjudication.jsonl", [dict(job, job_id=job["job_id"].replace("primary/", "adjudication/"))
                                                           for job in primary[:1]])

    def execute(self, calls: int = 12, tokens: int = 180000, wall: float = 600, **kwargs) -> dict:
        return orchestrate(self.root, calls, tokens, wall, workers=2, timeout=60,
                           run_fn=self.fake_run, finalize_fn=self.fake_finalize,
                           clock=lambda: self.now, **kwargs)

    def test_complete_reserves_all_phases_and_resume_never_resets_budget(self) -> None:
        state = self.execute()
        self.assertEqual(state["status"], "complete")
        self.assertEqual(state["attempts_accounted"], 5)
        self.assertEqual(state["estimated_tokens_accounted"], 5 * TOKENS_PER_ATTEMPT)
        self.assertEqual([item[0] for item in self.invocations], ["primary", "review", "adjudication"])
        manifest_bytes = (self.root / "judge-loop-budget.json").read_bytes()
        self.now += 1000  # Finished runs remain finished after their dispatch deadline.
        again = self.execute()
        self.assertEqual(again["status"], "complete")
        self.assertEqual(again["attempts_accounted"], 5)
        self.assertEqual(len(self.invocations), 3)
        self.assertEqual((self.root / "judge-loop-budget.json").read_bytes(), manifest_bytes)

    def test_insufficient_downstream_reservation_refuses_before_transport(self) -> None:
        for calls, tokens in ((11, 180000), (12, 179999)):
            with self.subTest(calls=calls, tokens=tokens):
                with self.assertRaisesRegex(ValueError, "worst-case judge reservation"):
                    self.execute(calls, tokens)
                self.assertEqual(self.invocations, [])
                self.assertFalse((self.root / "judge-loop-budget.json").exists())

    def test_deadline_stops_after_primary_without_new_review_attempts(self) -> None:
        self.halt_after_primary = True
        state = self.execute()
        self.assertEqual(state["status"], "budget_stopped")
        self.assertEqual(state["stage"], "review")
        self.assertEqual(state["attempts_accounted"], 2)
        self.assertEqual(len(self.invocations), 1)
        self.assertEqual(self.execute()["attempts_accounted"], 2)
        self.assertEqual(len(self.invocations), 1)

    def test_exhausted_transport_stops_downstream_and_semantic_retries(self) -> None:
        self.failed = True
        state = self.execute()
        self.assertEqual(state["status"], "transport_stopped")
        self.assertEqual(state["stage"], "primary")
        self.assertEqual(state["attempts_accounted"], 4)
        self.assertFalse((self.root / "jobs-review.jsonl").exists())
        self.assertEqual(self.execute()["attempts_accounted"], 4)
        self.assertEqual(set(attempt_counts(self.root).values()), {2})

    def test_immutable_caps_and_deadline_reject_changes(self) -> None:
        self.execute()
        with self.assertRaisesRegex(ValueError, "immutable judge-loop settings"):
            self.execute(calls=13)
        path = self.root / "judge-loop-budget.json"
        manifest = read_json(path)
        manifest["started_at_epoch"] += 100
        manifest["deadline_epoch"] += 100
        dump(path, manifest)
        with self.assertRaisesRegex(ValueError, "start/deadline changed"):
            self.execute()

    def test_deleted_attempt_history_cannot_restore_budget(self) -> None:
        self.execute()
        state = read_json(self.root / "judge-loop-state.json")
        state["attempts_accounted"] = 6
        dump(self.root / "judge-loop-state.json", state)
        with self.assertRaisesRegex(ValueError, "history disappeared"):
            self.execute()

    def test_orphan_attempts_are_counted_without_job_ledger(self) -> None:
        (self.root / "judge-execution/primary/c1/w0/attempt-1").mkdir(parents=True)
        self.assertEqual(attempt_counts(self.root), {"primary/c1/w0": 1})
        (self.root / "judge-execution/primary/c1/w0/attempt-3").mkdir()
        with self.assertRaisesRegex(ValueError, "two-attempt"):
            self.execute()

    def test_timeout_is_bounded_by_remaining_wall_and_worker_limit(self) -> None:
        self.execute(wall=50)
        self.assertTrue(all(item[2] <= 2 and 0 < item[3] <= 9.5 for item in self.invocations))


if __name__ == "__main__":
    unittest.main()
