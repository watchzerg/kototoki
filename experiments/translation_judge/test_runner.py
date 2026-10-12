"""Offline tests; no subprocess model calls or authentication reads."""

import json
from pathlib import Path
import tempfile
import unittest

from experiments.translation_eval.runner import dump, read_json
from .runner import MODEL, command, event_evidence, local_path, prepare_probe, run_job, run_lock


class JudgeTests(unittest.TestCase):
    def setUp(self):
        self.previous_tempdir = tempfile.tempdir
        # Keep all offline-test writes inside the permitted workspace.
        temp_root = Path(__file__).resolve().parents[2] / ".local/testing-translation-judge"
        temp_root.mkdir(parents=True, exist_ok=True)
        tempfile.tempdir = str(temp_root)
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "run"
        prepare_probe(self.root)
        self.job = json.loads((self.root / "jobs.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.calls = 0

    def tearDown(self):
        self.temporary.cleanup()
        tempfile.tempdir = self.previous_tempdir

    def fake(self, args, prompt, cwd, attempt, timeout):
        self.calls += 1
        self.assertTrue(cwd.exists())
        self.assertFalse((cwd / "AGENTS.md").exists())
        self.assertIn("PACKET:", prompt)
        self.assertNotIn("resume", args)
        dump(attempt / "last-message.txt", {"window_id": "equivalent", "candidate_alias": "candidate-a",
             "semantic": 4, "naturalness": 2, "status": "scored", "errors": [],
             "uncertainties": [], "summary_zh": "含义相同，表达自然。"})
        return {"returncode": 0, "transport_status": "completed", "elapsed_seconds": .1,
                "returned_models": [MODEL], "returned_efforts": ["high"], "tool_events": []}

    def test_success_resume_and_restore(self):
        first = run_job(self.root, self.job, "fake", "test", 1, self.fake)
        self.assertEqual(first["status"], "succeeded")
        Path(first["response"]).unlink()
        second = run_job(self.root, self.job, "fake", "test", 1, self.fake)
        self.assertTrue(second["resumed"])
        self.assertEqual(self.calls, 1)
        self.assertEqual(read_json(Path(first["response"]))["semantic"], 4)

    def test_schema_retry_limit_survives_resume(self):
        def invalid(*args):
            result = self.fake(*args)
            dump(args[3] / "last-message.txt", {"window_id": "wrong"})
            return result
        first = run_job(self.root, self.job, "fake", "test", 1, invalid)
        self.assertEqual(first["status"], "judge_failed")
        self.assertEqual(self.calls, 2)
        second = run_job(self.root, self.job, "fake", "test", 1, invalid)
        self.assertEqual(second["status"], "judge_failed")
        self.assertEqual(self.calls, 2)

    def test_frozen_prompt_change_refused(self):
        run_job(self.root, self.job, "fake", "test", 1, self.fake)
        (self.root / "judge-prompt.txt").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed"):
            run_job(self.root, self.job, "fake", "test", 1, self.fake)

    def test_wrong_returned_identity_refused(self):
        def changed(*args):
            result = self.fake(*args)
            result["returned_models"] = ["different-model"]
            return result
        result = run_job(self.root, self.job, "fake", "test", 1, changed)
        self.assertEqual(result["status"], "judge_failed")
        self.assertFalse(Path(result["response"]).exists())

    def test_events_identity_unknown_and_tool_rejection(self):
        result = event_evidence('{"type":"thread.started"}\n{"type":"turn.completed","usage":{"input_tokens":4}}\n')
        self.assertEqual(result["returned_models"], [])
        self.assertEqual(result["usage_events"], [{"input_tokens": 4}])
        result = event_evidence('{"item":{"type":"mcp_tool_call"}}')
        self.assertEqual(result["tool_events"], ["mcp_tool_call"])

    def test_text_only_command_and_path_scope(self):
        args = command("codex.exe", self.root, self.root / "schema.json", self.root / "raw.txt")
        self.assertIn("--ephemeral", args)
        self.assertIn("--ignore-user-config", args)
        self.assertIn('model_reasoning_effort="high"', args)
        self.assertIn("project_doc_max_bytes=0", args)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", args)
        with self.assertRaises(ValueError):
            local_path(self.root, "../outside.json")

    def test_native_scheduler_lock(self):
        with run_lock(self.root):
            with self.assertRaisesRegex(ValueError, "another judge scheduler"):
                with run_lock(self.root):
                    self.fail("second scheduler acquired lock")
        with run_lock(self.root):
            pass


if __name__ == "__main__":
    unittest.main()
