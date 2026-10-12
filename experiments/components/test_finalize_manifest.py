"""Synthetic finalizer qualification and immutable manifest migration tests."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments.components import finalize_manifest as finalizer


class FinalizerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.local = self.root / ".local/components"
        self.name = "synthetic"
        self.audio = self.root / "audio.wav"
        self.audio.write_bytes(b"synthetic input")
        self.clip = {"id": "clip", "audio": str(self.audio), "audio_sha256": finalizer.digest(self.audio), "offset": 10, "duration": 5}
        self.result_path = self.root / ".local/results/one/result.json"
        self.result = {"schema_version": 1, "text": "PRIVATE", "units": [], "cues": [],
            "source_start_seconds": 10, "duration_seconds": 5, "input_sha256": self.clip["audio_sha256"]}
        self.save(self.result_path, self.result)
        self.harness = {"status": "completed", "returncode": 0, "reference_unchanged": True, "audio_sha256": self.clip["audio_sha256"]}
        self.harness_path = self.result_path.parent / "manifest.json"
        self.save(self.harness_path, self.harness)
        self.task = {"id": "one", "clip": "clip", "stage": "w0", "audio": str(self.audio), "output": str(self.result_path)}
        self.plan = {"clips": [self.clip], "tasks": [self.task], "source_sha256": {}}
        self.plan_path = self.local / self.name / "plan.json"
        self.save(self.plan_path, self.plan)
        self.progress = {"status": "completed", "plan_sha256": finalizer.digest(self.plan_path),
            "output_sha256": finalizer.digest(self.result_path), "harness_sha256": finalizer.digest(self.harness_path)}
        self.progress_path = self.local / self.name / "progress/one.json"
        self.save(self.progress_path, self.progress)
        self.save(self.root / ".local/round2/progress.json", {"tasks": {}})
        self.original = {"schema_version": 1, "manifest_id": self.name, "frozen": True,
            "source_sha256": {}, "clips": [self.clip], "configurations": [{"id": "w0-vocals", "model_metadata": {"base": "w0"},
                "runs": [{"clip_id": "clip", "run_id": "one", "status": "completed", "execution_verified": False,
                    "result_path": str(self.result_path), "result_sha256": finalizer.digest(self.result_path),
                    "input_audio_sha256": self.clip["audio_sha256"]}]}]}
        self.output = self.local / self.name / "evaluation.json"
        self.addCleanup(patch.stopall)
        patch.object(finalizer, "ROOT", self.root).start()
        patch.object(finalizer, "LOCAL", self.local).start()
        patch.object(finalizer.frozen_builder, "build", side_effect=lambda name, output: finalizer.write_new(output, self.original)).start()

    def save(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_migration_preserves_staging_and_result_identity_after_independent_audit(self):
        original_sha = finalizer.digest(self.result_path)
        with patch.object(finalizer, "gpu_verified", return_value=True) as gpu, \
                patch.object(finalizer, "upstream_evidence", return_value=(True, {}, [])):
            final = finalizer.finalize(self.name, self.output)
        self.assertEqual(final["configurations"][0]["configuration_id"], "w0-vocals")
        run = final["configurations"][0]["runs"][0]
        self.assertEqual(run["result_sha256"], original_sha)
        self.assertEqual(finalizer.digest(self.result_path), original_sha)
        self.assertTrue(run["execution_verified"])
        self.assertEqual(gpu.call_count, 1)
        staging = self.output.with_name("evaluation-builder-staging.json")
        self.assertEqual(finalizer.read(staging), self.original)
        self.assertNotIn("configuration_id", finalizer.read(staging)["configurations"][0])
        self.assertEqual(final["finalization"]["builder_staging"]["sha256"], finalizer.digest(staging))
        self.assertNotIn("PRIVATE", json.dumps(final))

    def test_incomplete_batch_rejected_before_builder_staging(self):
        self.progress_path.unlink()
        with self.assertRaisesRegex(ValueError, "not terminal"):
            finalizer.finalize(self.name, self.output)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_name("evaluation-builder-staging.json").exists())

    def test_gpu_audit_failure_never_promotes_builder_claim(self):
        self.original["configurations"][0]["runs"][0]["execution_verified"] = True
        with patch.object(finalizer, "gpu_verified", return_value=False), \
                patch.object(finalizer, "upstream_evidence", return_value=(True, {}, [])), \
                self.assertRaisesRegex(ValueError, "GPU evidence invalid"):
            finalizer.finalize(self.name, self.output)
        self.assertFalse(self.output.exists())
        self.assertTrue(self.output.with_name("evaluation-builder-staging.json").exists())

    def test_status_only_failure_retained_as_evidence_without_transcript_input(self):
        self.save(self.result_path, {"status": "failed", "error": "no transcript"})
        self.progress.update(status="failed", output_sha256=finalizer.digest(self.result_path))
        self.save(self.progress_path, self.progress)
        run = self.original["configurations"][0]["runs"][0]
        run.update(status="invocation_failed", result_sha256=finalizer.digest(self.result_path))
        final = finalizer.finalize(self.name, self.output)
        run = final["configurations"][0]["runs"][0]
        self.assertNotIn("result_path", run)
        self.assertNotIn("result_sha256", run)
        self.assertFalse(run["execution_verified"])
        self.assertIn({"path": str(self.result_path), "sha256": finalizer.digest(self.result_path)}, run["evidence"]["finalizer_artifacts"])


if __name__ == "__main__":
    unittest.main()
