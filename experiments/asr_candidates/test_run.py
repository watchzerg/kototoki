"""Offline controller checks with real immutable fixtures and fake stage processes."""
from __future__ import annotations

from contextlib import ExitStack, redirect_stdout
import io
import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import run


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.folder = self.root / ".local/fullfilm-comparison/candidates-test"
        self.baseline_path = self.root / "controls/study.json"
        self.provision_root = self.root / "provision"
        self.stack.enter_context(patch.object(run, "ROOT", self.root))
        self.stack.enter_context(patch.object(run, "source_paths", return_value=[]))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.calls = []
        self.asr_code = 0
        self.align_status = "ok"
        self.stack.enter_context(patch.object(run, "execute", side_effect=self.fake_execute))
        clips = []
        for name in ("film-ii", "film-iii"):
            clip = {"id": name, "pcm_sha256": "pcm-" + name, "samples": 32000, "offset": 0}
            for key in ("audio", "reference", "source_audio", "source_srt"):
                file = self.root / "inputs" / f"{name}-{key}.txt"
                file.parent.mkdir(exist_ok=True)
                file.write_text(f"fixture {name} {key}", encoding="utf-8")
                clip[key] = str(file)
                clip[f"{key}_sha256"] = run.sha256(file)
            clips.append(clip)
        corpus = self.root / "corpus.json"
        candidate = self.root / "vad.json"
        run.write(corpus, {"clips": clips})
        run.write(candidate, {"status": "ready"})
        segments = {}
        for clip in clips:
            plan_path = self.root / "controls/segmentation" / clip["id"] / "plan.json"
            run.write(plan_path, {"clip_id": clip["id"], "segmentation": "pyannote-current",
                "source_sha256": {}, "offset_s": 0,
                "input": {"path": clip["audio"], "file_sha256": clip["audio_sha256"],
                          "pcm_sha256": clip["pcm_sha256"], "samples": clip["samples"]},
                "chunks": [{"start_sample": 16, "end_sample": 32000}]})
            segments[f"pyannote-current-{clip['id']}"] = {"status": "completed", "wall_s": 4.0,
                "manifest_path": str(plan_path), "manifest_sha256": run.sha256(plan_path)}
        routes = []
        for family in ("w0", "x0"):
            slots = []
            for clip in clips:
                result = self.root / "controls/runs" / f"{family}-{clip['id']}" / "alignment.json"
                run.write(result, {"status": "ok", "text": "fixture"})
                segment = segments[f"pyannote-current-{clip['id']}"]
                slots.append({"clip_id": clip["id"], "status": "completed", "result_path": str(result),
                    "result_sha256": run.sha256(result), "plan_path": segment["manifest_path"],
                    "plan_sha256": segment["manifest_sha256"], "processes": {"asr": {"wall_s": 2.0}}})
            routes.append({"id": f"{family}-pyannote-current", "family": family,
                           "segmentation": "pyannote-current", "runs": slots})
            routes.append({"id": f"{family}-cut-merge", "family": family, "segmentation": "cut-merge",
                           "runs": [{"clip_id": c["id"], "status": "pending"} for c in clips]})
        self.baseline = {"terminal": False, "source_sha256": {}, "clips": clips, "routes": routes,
            "candidate": {"status": "ready", "device": "cuda:0"},
            "corpus_plan_path": str(corpus), "corpus_plan_sha256": run.sha256(corpus),
            "candidate_path": str(candidate), "candidate_sha256": run.sha256(candidate),
            "segmentation_runs": segments}
        run.write(self.baseline_path, self.baseline)
        for name in run.MODELS:
            self.ready(name)

    def ready(self, name):
        model = self.root / "models" / name
        model.mkdir(parents=True, exist_ok=True)
        file = model / "weights.bin"
        file.write_bytes(name.encode())
        model_id, revision = run.MODELS[name]
        run.write(self.provision_root / f"{name}-ready.json", {"status": "ready", "model_id": model_id,
            "model_revision": revision, "path": str(model), "files_sha256": {"weights.bin": run.sha256(file)}})

    def invoke(self, *extra):
        with patch.object(sys, "argv", ["candidates", "--study-id", "candidates-test",
            "--baseline-study", str(self.baseline_path), "--provision-root", str(self.provision_root), *extra]):
            run.main()

    def fake_execute(self, command, prefix, environment):
        lock = run.read(self.root / ".local/gpu.lock")
        self.assertEqual(lock["pid"], os.getpid())
        self.assertEqual(environment["KOTOTOKI_FULLFILM_PARENT_PID"], str(os.getpid()))
        self.assertEqual(environment["HF_HUB_OFFLINE"], "1")
        self.assertTrue(Path(environment["HF_HOME"]).is_relative_to(self.folder))
        phase = command[3]
        job = run.read(Path(command[command.index("--job") + 1]))
        out = Path(command[command.index("--out") + 1])
        self.assertEqual(run.sha256(Path(job["plan_path"])), job["plan_sha256"])
        self.assertEqual(run.read(Path(job["plan_path"]))["source_sha256"], job["source_sha256"])
        self.assertEqual(job["model_revision"], run.MODELS[job["candidate_id"]][1])
        manifest = run.read(self.provision_root / f"{job['candidate_id']}-ready.json")
        self.assertEqual(job["model_files_sha256"], manifest["files_sha256"])
        self.calls.append((phase, job, out))
        code = self.asr_code if phase == "asr" else 0
        if phase == "asr" and code in {0, 2}:
            run.write(out / "asr.json", {"status": "partial" if code else "ok"})
        elif phase == "align":
            self.assertEqual(run.sha256(Path(job["asr_stage_path"])), job["asr_stage_sha256"])
            run.write(out / "alignment.json", {"status": self.align_status})
        else:
            run.write(out / "failure.json", {"status": "failed", "stage": phase,
                "failure_kind": "model_initialization_failed", "exception": "ValueError", "message": "fake init failed"})
        return {"command": command, "pid": 1234, "exit_code": code, "wall_s": 0.1}

    def study(self):
        return run.read(self.folder / "study.json")

    def test_imports_only_selected_controls_and_candidates_share_exact_fresh_plan(self):
        self.invoke()
        study = self.study()
        self.assertTrue(study["terminal"])
        self.assertTrue(study["all_models_tested"])
        self.assertEqual(len(study["routes"]), 5)
        self.assertEqual([c[0] for c in self.calls], ["asr", "align"] * 6)
        self.assertEqual(len(study["segmentation_runs"]), 2)
        for name in run.CONTROL_IDS:
            original = next(r for r in self.baseline["routes"] if r["id"] == name)
            imported = next(r for r in study["routes"] if r["id"] == name)
            for old, new in zip(original["runs"], imported["runs"]):
                self.assertEqual({k: v for k, v in new.items() if k != "import_provenance"}, old)
        for segment in study["segmentation_runs"].values():
            original = run.read(Path(segment["origin_plan_path"]))
            derived = run.read(Path(segment["manifest_path"]))
            self.assertEqual(original["chunks"], derived["chunks"])
            self.assertEqual(original["input"], derived["input"])
        self.assertFalse((self.root / ".local/gpu.lock").exists())

    def test_partial_asr_still_aligns_and_preserves_partial_result(self):
        self.asr_code, self.align_status = 2, "partial"
        self.invoke()
        slots = [s for r in self.study()["routes"] if r["family"] in run.MODELS for s in r["runs"]]
        self.assertEqual({s["status"] for s in slots}, {"partial"})
        self.assertEqual(len(self.calls), 12)

    def test_model_failure_never_retries_and_continues_remaining_models_and_films(self):
        self.asr_code = 1
        self.invoke()
        self.assertEqual(len(self.calls), 6)
        study = self.study()
        self.assertTrue(study["all_model_slots_attempted"])
        self.assertFalse(study["all_models_tested"])
        slots = [s for r in study["routes"] if r["family"] in run.MODELS for s in r["runs"]]
        self.assertEqual({s["failure_kind"] for s in slots}, {"model_initialization_failed"})
        for slot in slots:
            self.assertEqual(slot["failure_stage"], "asr")
            self.assertEqual(run.sha256(Path(slot["failure_path"])), slot["failure_sha256"])
        before = {p: p.read_bytes() for p in self.folder.glob("runs/*/asr-job.json")}
        self.calls.clear()
        self.invoke()
        self.assertEqual(self.calls, [])
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_missing_access_records_both_full_film_slots_and_resumes_only_blocked_model(self):
        (self.provision_root / "cohere-ready.json").unlink()
        self.invoke()
        study = self.study()
        cohere = next(r for r in study["routes"] if r["family"] == "cohere")
        self.assertEqual([s["status"] for s in cohere["runs"]], ["blocked_access"] * 2)
        self.assertTrue(study["terminal"])
        self.assertFalse(study["all_models_tested"])
        self.assertTrue(study["resumable"])
        self.ready("cohere")
        self.calls.clear()
        self.invoke()
        self.assertEqual([job["candidate_id"] for _, job, _ in self.calls], ["cohere"] * 4)
        self.assertTrue(self.study()["all_models_tested"])

    def test_filter_leaves_unselected_models_pending_without_fabricating_results(self):
        self.invoke("--candidates", "granite")
        self.assertFalse(self.study()["terminal"])
        self.assertEqual(len(self.calls), 4)
        self.calls.clear()
        self.invoke("--candidates", "nemotron")
        self.assertEqual([job["candidate_id"] for _, job, _ in self.calls], ["nemotron"] * 4)

    def test_source_registry_can_change_unselected_pending_routes_after_import(self):
        self.invoke("--candidates", "granite")
        self.baseline["terminal"] = True
        run.write(self.baseline_path, self.baseline)
        self.calls.clear()
        self.invoke("--candidates", "nemotron")
        self.assertEqual(len(self.calls), 4)

    def test_mutated_frozen_evidence_prevents_inference(self):
        self.invoke("--candidates", "granite")
        original = next(iter(self.baseline["segmentation_runs"].values()))
        Path(original["manifest_path"]).write_bytes(b"changed")
        self.calls.clear()
        with self.assertRaisesRegex(ValueError, "changed"):
            self.invoke("--candidates", "nemotron")
        self.assertEqual(self.calls, [])

    def test_mutated_model_weight_prevents_resume_and_wrong_revision_rejected(self):
        self.invoke("--candidates", "granite")
        (self.root / "models/granite/weights.bin").write_bytes(b"changed")
        self.calls.clear()
        with self.assertRaisesRegex(ValueError, "model file changed"):
            self.invoke("--candidates", "nemotron")
        self.assertEqual(self.calls, [])
        manifest = run.read(self.provision_root / "cohere-ready.json")
        manifest["model_revision"] = "other"
        with self.assertRaisesRegex(ValueError, "pinned"):
            run.verify_provision("cohere", manifest)

    def test_running_control_is_refused_despite_other_completed_slots(self):
        self.baseline["routes"][0]["runs"][0]["status"] = "running"
        run.write(self.baseline_path, self.baseline)
        with self.assertRaisesRegex(ValueError, "not terminal"):
            self.invoke()
        self.assertFalse((self.folder / "study.json").exists())
        self.assertEqual(self.calls, [])

    def test_running_candidate_requires_inspection_without_registry_mutation(self):
        self.invoke("--candidates", "granite")
        study = self.study()
        study["routes"][-1]["runs"][0]["status"] = "running"
        run.write(self.folder / "study.json", study)
        before = (self.folder / "study.json").read_bytes()
        self.calls.clear()
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            self.invoke()
        self.assertEqual(before, (self.folder / "study.json").read_bytes())
        self.assertEqual(self.calls, [])

    def test_active_gpu_lock_prevents_even_initial_registry_creation(self):
        with run.gpu_lock(self.root / ".local/gpu.lock", "other"):
            with self.assertRaises(FileExistsError):
                self.invoke()
        self.assertFalse(self.folder.exists())


if __name__ == "__main__":
    unittest.main()
