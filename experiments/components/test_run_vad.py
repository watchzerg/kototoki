"""Offline freeze, failure bookkeeping, and interrupted-evidence validation."""
from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

from experiments.components import run_vad as runner
from experiments.components.run import digest, read, write_new
from experiments.components.separate import read_pcm


class RunVadTests(unittest.TestCase):
    def workspace(self, root):
        sources = ("experiments/run_experiment.py", "experiments/components/run_vad.py",
            "experiments/components/run.py", "experiments/components/separate.py", "experiments/components/vad.py",
            "experiments/components/w0_vad.py", "experiments/components/qwen_vad.py", "experiments/whisper/run.py",
            "experiments/whisper/ctc_audio.py", "experiments/whisper/ctc_forced.py", "experiments/whisper/ctc_transition.py",
            "experiments/qwen/run_qwen.py", "experiments/qwen/run_cross.py",
            "experiments/whisper/requirements-whisperx.lock", "experiments/whisper/requirements-w0.lock",
            "experiments/qwen/requirements.lock")
        for relative in sources:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# offline fixture", encoding="utf-8")
        for environment in ("whisper-latest", "whisper-w0-py312", "qwen-hf-final"):
            path = root / ".local/envs" / environment / "Scripts/python.exe"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"not executable: tests never run inference")
        model = root / ".local/models/checkpoint.bin"
        model.parent.mkdir(parents=True)
        model.write_bytes(b"synthetic checkpoint identity")
        base = root / ".local/components/comp-sep-pilot-v1/plan.json"
        write_new(base, {"model_sha256": {str(model): digest(model)}})
        clips = []
        for film in ("hf-ii", "hf-iii"):
            for index in ("01", "04"):
                clip_id = f"{film}-window-{index}"
                audio = root / ".local/corpus" / f"{clip_id}.wav"
                audio.parent.mkdir(parents=True, exist_ok=True)
                with wave.open(str(audio), "wb") as output:
                    output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                    output.writeframes(b"\x01\x00" * 32)
                _, identity = read_pcm(audio)
                reference = audio.with_suffix(".json")
                write_new(reference, {"spans": []})
                clips.append({"id": clip_id, "film": film, "audio": str(audio),
                    "audio_sha256": identity["file_sha256"], "pcm_sha256": identity["pcm_sha256"],
                    "duration": 32 / 16000, "offset": 120, "reference": str(reference),
                    "reference_sha256": digest(reference), "source_srt": str(reference),
                    "source_srt_sha256": digest(reference)})
        write_new(root / ".local/round2/corpus/manifest.json", {"clips": clips})
        return base, model

    def test_prepare_freezes_original_audio_and_all_sixteen_slots_without_gpu(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base, _ = self.workspace(root)
            with patch.multiple(runner, ROOT=root, LOCAL=root / ".local/components", BASE_PLAN=base):
                plan = runner.prepare("vad-offline-test")
                self.assertEqual(len(plan["tasks"]), 16)
                for task in plan["tasks"]:
                    clip = next(c for c in plan["clips"] if c["id"] == task["clip"])
                    self.assertEqual(task["audio"], clip["audio"])
                    self.assertNotIn("vocals.wav", " ".join(task["command"]))
                self.assertEqual(sum(t["stage"] == "x0" for t in plan["tasks"]), 4)
                for task in (t for t in plan["tasks"] if t["stage"] == "x0"):
                    self.assertIn("--ctc-normalize", task["command"])
                    self.assertIn("--ctc-forced-align", task["command"])
                with self.assertRaises(FileExistsError):
                    runner.prepare("vad-offline-test")

    def test_changed_model_cannot_silently_redefine_a_paired_baseline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base, model = self.workspace(root)
            model.write_bytes(b"changed checkpoint")
            with patch.multiple(runner, ROOT=root, LOCAL=root / ".local/components", BASE_PLAN=base):
                with self.assertRaises(ValueError):
                    runner.prepare("changed-model")
                self.assertFalse((root / ".local/components/changed-model").exists())

    def test_failed_vad_retains_full_denominator_and_blocks_every_dependent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base, _ = self.workspace(root)
            with patch.multiple(runner, ROOT=root, LOCAL=root / ".local/components", BASE_PLAN=base):
                runner.prepare("failure-test")
                with patch.object(runner.subprocess, "run", return_value=SimpleNamespace(returncode=7)) as process:
                    runner.run("failure-test")
                    self.assertEqual(process.call_count, 4)
                records = [read(p) for p in (root / ".local/components/failure-test/progress").glob("*.json")]
                self.assertEqual(len(records), 16)
                self.assertEqual(sum(r["status"] == "failed" for r in records), 4)
                self.assertEqual(sum(r["status"] == "blocked" for r in records), 12)
                with patch.object(runner.subprocess, "run") as process:
                    runner.run("failure-test")
                    process.assert_not_called()

    def test_progress_rejects_tampered_artifacts_and_dependency_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output, dependency = root / "result.json", root / "parent.json"
            write_new(output, {"text": "complete"})
            write_new(dependency, {"status": "completed"})
            task = {"id": "task", "command": ["python", "run.py"], "output": str(output)}
            record = {"status": "completed", "plan_sha256": "frozen-plan", "task_command": task["command"],
                      "output_sha256": digest(output), "artifact_sha256": {str(output): digest(output)},
                      "dependencies": {"parent": {"path": str(dependency), "progress_sha256": digest(dependency)}}}
            runner.verify_progress(task, record, "frozen-plan")
            dependency.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                runner.verify_progress(task, record, "frozen-plan")

    def test_unbound_interrupted_harness_is_retained_and_requires_new_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base, _ = self.workspace(root)
            with patch.multiple(runner, ROOT=root, LOCAL=root / ".local/components", BASE_PLAN=base):
                plan = runner.prepare("interrupted-test")
                occupied = root / ".local/results" / plan["tasks"][0]["id"]
                occupied.mkdir(parents=True)
                (occupied / "partial.log").write_text("retained", encoding="utf-8")
                with patch.object(runner.subprocess, "run") as process:
                    with self.assertRaises(RuntimeError):
                        runner.run("interrupted-test")
                    process.assert_not_called()
                self.assertEqual((occupied / "partial.log").read_text(), "retained")


if __name__ == "__main__":
    unittest.main()
