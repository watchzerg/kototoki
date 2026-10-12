import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments import run_round2 as runner


class Round2RunnerTests(unittest.TestCase):
    def test_template_keeps_inference_options_and_changes_only_input_identity(self):
        command = ["python", "run.py", "--audio", "old.wav", "--offset", "4", "--output", "old.json",
                   "--window-seconds", "30", "--max-new-tokens", "512"]
        clip = {"id": "ii01", "audio": "new.wav", "offset": 1800}
        actual = runner.build_command({"stage": "q0", "template_command": command}, clip, Path("new.json"), {})
        self.assertEqual(actual, ["python", "run.py", "--audio", "new.wav", "--offset", "1800", "--output", "new.json",
                                  "--window-seconds", "30", "--max-new-tokens", "512"])
        self.assertEqual(command[3], "old.wav")

    def test_cross_ctc_consumes_current_round_export(self):
        command = ["python", "run.py", "--audio", "old.wav", "--offset", "4", "--output", "old.json",
                   "--asr-result", "old-asr.json", "--ctc-normalize", "--ctc-forced-align"]
        actual = runner.build_command({"stage": "x0", "template_command": command},
                                      {"id": "ii01", "audio": "new.wav", "offset": 1800}, Path("new.json"),
                                      {"ii01-export": {"output": "new-export.json"}})
        self.assertEqual(actual[actual.index("--asr-result") + 1], "new-export.json")

    def test_backend_failure_is_not_successful_process_evidence(self):
        self.assertFalse(runner.successful_result({"status": "failed"}))
        self.assertFalse(runner.successful_result({"manifest": {"status": "failed"}}))
        self.assertTrue(runner.successful_result({"manifest": {"status": "ok"}}))

    def test_resume_rejects_changed_completed_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "result.json"
            output.write_text(json.dumps({"text": "fixture"}), encoding="utf-8")
            record = {"status": "completed", "output": str(output), "output_sha256": runner.sha256(output)}
            output.write_text(json.dumps({"text": "changed"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "removed or changed"):
                runner.verified_completed(record, {})

    def test_failed_qwen_stage_records_cross_dependency_block(self):
        plan = {"clips": [{"id": "ii01"}], "tasks": [{"id": "ii01-x0", "clip": "ii01", "stage": "x0",
                  "configuration": "X0-Q0-window30-normalized-forced", "depends_on": ["ii01-export"], "stage_cache": {}}]}
        with tempfile.TemporaryDirectory() as temporary, patch.object(runner, "ROUND", Path(temporary)):
            plan_file = Path(temporary) / "plan.json"
            plan_file.write_text("{}", encoding="utf-8")
            progress_file = Path(temporary) / "progress.json"
            runner.write_json(progress_file, {"plan_sha256": runner.sha256(plan_file), "tasks": {"ii01-export": {"status": "failed"}}})
            with patch.object(runner, "verify_freeze"), patch.object(runner, "execute") as execute:
                records = runner.run(plan, None, 1)
            execute.assert_not_called()
            self.assertEqual(records["ii01-x0"]["status"], "blocked")
            self.assertEqual(runner.read_json(progress_file)["tasks"]["ii01-x0"]["depends_on"], ["ii01-export"])
