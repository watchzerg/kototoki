"""Offline fresh-worker task boundary tests."""

from pathlib import Path
import unittest

from experiments.translation_eval.runner import dump, dump_jsonl
from .subagents import export_tasks, import_tasks
from . import test_runner


class SubagentTests(unittest.TestCase):
    setUp = test_runner.JudgeTests.setUp
    tearDown = test_runner.JudgeTests.tearDown
    def metadata(self, task, elapsed=.25):
        dump(Path(task["invocation_metadata"]), {
            "requested_model": "gpt-6.1-sol", "requested_effort": "high", "fork_turns": "none",
            "tool_provenance": "collaboration.spawn_agent", "agent_id": "/root/test/worker",
            "elapsed_seconds": elapsed, "returned_model": None, "returned_effort": None,
        })

    def single_job(self):
        path = self.root / "one-job.jsonl"
        dump_jsonl(path, [self.job])
        return path

    def test_export_import_success(self):
        jobs = self.single_job()
        task = export_tasks(self.root, jobs)[0]
        self.metadata(task)
        dump(Path(task["raw_response"]), {"window_id": "equivalent", "candidate_alias": "candidate-a",
             "semantic": 4, "naturalness": 2, "status": "scored", "errors": [],
             "uncertainties": [], "summary_zh": "表达等价。"})
        states = import_tasks(self.root, self.root / "subagent-execution/one-job-tasks-1.jsonl")
        self.assertEqual(states[0]["status"], "succeeded")
        self.assertEqual(export_tasks(self.root, jobs), [])

    def test_failed_job_allows_one_retry_only(self):
        jobs = self.single_job()
        for attempt in (1, 2):
            task = export_tasks(self.root, jobs, attempt)[0]
            self.metadata(task)
            dump(Path(task["raw_response"]), {"invalid": True})
            states = import_tasks(self.root, self.root / f"subagent-execution/one-job-tasks-{attempt}.jsonl")
            self.assertEqual(states[0]["status"], "judge_failed")
            self.assertEqual(export_tasks(self.root, jobs, attempt), [])
        self.assertEqual(export_tasks(self.root, jobs, 2), [])

    def test_bad_timing_and_pending_identity(self):
        jobs = self.single_job()
        task = export_tasks(self.root, jobs)[0]
        self.metadata(task, True)
        self.assertEqual(export_tasks(self.root, jobs), [])
        # Preserve the original task list while a worker is still pending.
        dump_jsonl(self.root / "original.jsonl", [task])
        states = import_tasks(self.root, self.root / "original.jsonl")
        self.assertEqual(states[0]["status"], "judge_failed")
        self.assertIn("timing", states[0]["error"])
