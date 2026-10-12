"""Offline orchestration failure and evidence checks without models or GPU."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import run_cross


class CrossTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        for relative in run_cross.SOURCE_FILES:
            source = self.project / relative
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("# synthetic " + relative, encoding="utf-8")
        self.audio = self.project / "input.wav"
        self.audio.write_bytes(b"synthetic audio identity")
        self.interpreter = self.project / "python.exe"
        self.interpreter.touch()
        self.output = self.project / ".local/run/result.json"
        self.args = run_cross.parser().parse_args(["--audio", str(self.audio), "--output", str(self.output),
            "--qwen-python", str(self.interpreter), "--whisper-python", str(self.interpreter)])
        self.commands = []
        self.bad_asr_identity = False
        self.fail_ctc = False
        self.ctc_fault = None
        self.text = "文字"

    def fake_process(self, command, **kwargs):
        self.commands.append(command)
        artifact = Path(command[command.index("--output") + 1])
        if command[1].endswith("run_qwen.py"):
            result = {"adapter_sha256": "bad" if self.bad_asr_identity else run_cross.sha256(Path(command[1])),
                "config": {"asr_only": True, "window_seconds": 30., "language": "ja", "dtype": "bfloat16",
                           "attention": "sdpa", "max_new_tokens": 4096, "do_sample": False,
                           "batch_size": 1, "offline": True, "alignment_only": None},
                "cache_reused": False, "stage_execution": {"asr": "executed", "aligner": "not_requested_asr_only"},
                "windows": [{"token_limit_reached": False}], "text": self.text,
                "environment": {"devices": {"asr": {"output_device": "cuda:0"}}}}
        elif command[1].endswith("export_ctc_input.py"):
            asr_path = Path(command[command.index("--asr-result") + 1])
            result = {"provenance": {"source_result_sha256": run_cross.sha256(asr_path),
                                      "exporter_sha256": run_cross.sha256(Path(command[1]))}}
        else:
            result = {"text": self.text, "input": {"file_sha256": run_cross.sha256(self.audio)},
                "implementation": {"sha256": run_cross.sha256(Path(command[1]))},
                "devices": {"aligner": {"model": "cuda:0", "forward_observation": ["cuda:0"]}},
                "effective_parameters": {"asr_reused": True, "ctc_normalize": True},
                "experimental_alignment": {"time_semantics": "ctc_nonblank_token_span", "records": [
                    {"segment_index": 0, "failure": None, "decoder_input_device": "cuda:0", "decoder_output_device": "cuda:0"}]},
                "experimental_preprocessing": {"records": [{"segment_index": 0, "actual_input_device": "cuda:0"}]},
                "cached_inference": False}
            if self.ctc_fault == "decoder_cpu":
                result["experimental_alignment"]["records"][0]["decoder_output_device"] = "cpu"
            elif self.ctc_fault == "normalization_cpu":
                result["experimental_preprocessing"]["records"][0]["actual_input_device"] = "cpu"
            elif self.ctc_fault == "decoder_failed":
                result["experimental_alignment"]["records"][0]["failure"] = "RuntimeError: synthetic decoder failure"
            elif self.ctc_fault == "no_forward":
                result["devices"]["aligner"]["forward_observation"] = []
                result["experimental_alignment"]["records"] = []
                result["experimental_preprocessing"]["records"] = []
            if self.fail_ctc:
                result = {"status": "failed", "error": "synthetic stage failure"}
        run_cross.write_json(artifact, result)
        return subprocess.CompletedProcess(command, 1 if self.fail_ctc and Path(command[1]).parent.name == "whisper" else 0)

    def execute(self):
        with patch.object(run_cross, "PROJECT", self.project), patch.object(run_cross.subprocess, "run", self.fake_process):
            return run_cross.run_pipeline(self.args)

    def test_bad_asr_source_identity_stops_before_export(self):
        self.bad_asr_identity = True
        with self.assertRaisesRegex(ValueError, "source identity"):
            self.execute()
        self.assertEqual(len(self.commands), 1)
        failure = json.loads(self.output.read_text(encoding="utf-8"))
        manifest = json.loads(Path(failure["pipeline_manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "failed")
        self.assertTrue(Path(manifest["stages"][0]["output"]).is_file())

    def test_failed_ctc_preserves_fresh_asr_bridge_and_partial_ctc(self):
        self.fail_ctc = True
        with self.assertRaisesRegex(RuntimeError, "ctc failed"):
            self.execute()
        manifest_path = self.output.parent / "result-stages/pipeline-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual([s["stage"] for s in manifest["stages"]], ["asr", "export", "ctc"])
        self.assertEqual(manifest["stages"][-1]["status"], "failed")
        for stage in manifest["stages"]:
            self.assertTrue(Path(stage["output"]).is_file())
            self.assertTrue(Path(stage["log"]).is_file())
        with self.assertRaises(FileExistsError):
            self.execute()

    def test_success_runs_frozen_copies_and_records_actual_pipeline_wall(self):
        result = self.execute()
        self.assertEqual(result["route"], "X0")
        self.assertFalse(result["cached_inference"])
        self.assertTrue(result["pipeline"]["new_asr_inference"])
        self.assertTrue(result["pipeline"]["new_alignment_inference"])
        self.assertEqual(result["pipeline"]["stage_cache"]["ctc_asr_input"], "reused_from_this_run_fresh_asr")
        self.assertEqual(len(self.commands), 3)
        for command in self.commands:
            self.assertIn("result-stages", Path(command[1]).parts)
        self.assertIn("--asr-only", self.commands[0])
        self.assertIn("--ctc-normalize", self.commands[2])
        self.assertIn("--ctc-forced-align", self.commands[2])
        self.assertGreaterEqual(result["pipeline"]["wall_seconds"], sum(s["wall_seconds"] for s in result["pipeline"]["stages"]))

    def test_ctc_evidence_failures_override_success_exit_and_preserve_stage_results(self):
        for fault, reason in [("decoder_cpu", "decoder_device_unverified"),
                              ("normalization_cpu", "normalization_input_device_unverified"),
                              ("decoder_failed", "decoder_failed"),
                              ("no_forward", "model_forward_device_unverified")]:
            with self.subTest(fault=fault):
                self.args.output = self.output.parent / (fault + ".json")
                self.ctc_fault = fault
                with self.assertRaises(run_cross.AlignmentEvidenceError):
                    self.execute()
                failure = json.loads(self.args.output.read_text(encoding="utf-8"))
                self.assertEqual(failure["failure_classification"], "alignment_failure")
                manifest = json.loads(Path(failure["pipeline_manifest"]).read_text(encoding="utf-8"))
                self.assertEqual(manifest["alignment_evidence"]["reason"], reason)
                self.assertEqual(manifest["stages"][-1]["returncode"], 0)
                for stage in manifest["stages"]:
                    self.assertTrue(Path(stage["output"]).is_file())

    def test_empty_recognized_text_does_not_claim_alignment_execution(self):
        self.text = ""
        self.ctc_fault = "no_forward"
        result = self.execute()
        self.assertFalse(result["pipeline"]["new_alignment_inference"])
        self.assertEqual(result["pipeline"]["alignment_evidence"]["status"], "no_forward_empty_or_nonlexical_text")
        self.assertEqual(result["pipeline"]["stage_cache"]["ctc_alignment"], "no_forward_observed")


if __name__ == "__main__":
    unittest.main()
