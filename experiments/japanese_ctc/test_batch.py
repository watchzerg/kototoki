"""Offline identity, complete-registry and failure-accounting checks."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments.japanese_ctc import batch


class BatchTests(unittest.TestCase):
    def setUp(self):
        private = batch.ROOT / ".local"
        self.temp = tempfile.TemporaryDirectory(prefix="jctc-batch-test-", dir=private)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.local = self.root / ".local/japanese-ctc"
        self.base = self.root / ".local/baseline.json"
        self.bridges = self.root / ".local/bridges"
        for attr, value in (("ROOT", self.root), ("LOCAL", self.local), ("BASE", self.base), ("BRIDGES", self.bridges)):
            context = patch.object(batch, attr, value)
            context.start()
            self.addCleanup(context.stop)
        for filename in ("experiments/run_experiment.py", "experiments/japanese_ctc/run.py",
                         "experiments/japanese_ctc/batch.py"):
            path = self.root / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# synthetic source\n", encoding="utf-8")
        self.clips = []
        configurations = [{"id": c, "configuration_id": c, "runs": []} for c in batch.BASELINES]
        for film in ("hf-ii", "hf-iii"):
            for index in range(1, 7):
                clip_id = f"{film}-window-{index:02d}"
                audio = self.root / ".local/audio" / f"{clip_id}.wav"
                audio.parent.mkdir(parents=True, exist_ok=True)
                audio.write_bytes(b"synthetic audio no inference")
                reference = self.save(f".local/ref/{clip_id}.json", {
                    "schema_version": 1, "reference_kind": "srt_display", "corpus_revision": "synthetic",
                    "spans": [{"id": f"{clip_id}-cue", "text": "AB", "start": 12, "end": 13}]})
                source_srt = self.root / ".local/source.srt"
                source_srt.write_bytes(b"synthetic subtitle")
                clip = {"id": clip_id, "film": film, "offset": 10, "duration": 20,
                        "audio": str(audio), "audio_sha256": batch.digest(audio), "pcm_sha256": "synthetic-pcm",
                        "reference": str(reference), "reference_sha256": batch.digest(reference),
                        "source_srt": str(source_srt), "source_srt_sha256": batch.digest(source_srt)}
                self.clips.append(clip)
                result = self.result(clip)
                bridge = self.save(f".local/bridges/{clip_id}.json", result)
                for config in configurations:
                    path = self.save(f".local/cache/{clip_id}-{config['id']}.json", result)
                    slot = {"clip_id": clip_id, "run_id": f"cache-{clip_id}-{config['id']}", "status": "completed",
                            "execution_verified": True, "result_path": str(path), "result_sha256": batch.digest(path)}
                    if config["id"] == "w0-ctc":
                        slot["evidence"] = {"artifacts": [batch.identity(bridge)]}
                    config["runs"].append(slot)
        self.save(".local/baseline.json", {"frozen": True, "strict_hashes": True,
                                          "configurations": configurations, "clips": self.clips})
        for candidate, folder in batch.CANDIDATES.items():
            asset = self.root / ".local/models" / folder / "model.bin"
            asset.parent.mkdir(parents=True)
            asset.write_bytes(b"synthetic weights")
            self.save(f".local/manifests/model-{folder}.json", {
                "complete": True, "repo": f"test/{folder}", "revision": "synthetic",
                "files": [{"path": str(asset), "sha256": batch.digest(asset)}]})

    def save(self, relative, document):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def result(self, clip):
        return {"schema_version": 1, "status": "ok", "text": "AB", "source_start_seconds": 10,
                "duration_seconds": 20, "offset_s": 10,
                "input": {"file_sha256": clip["audio_sha256"], "pcm_sha256": clip["pcm_sha256"], "duration_s": 20},
                "original_segments": [{"text": "AB", "start": 2, "end": 3}],
                "units": [{"char_start": 0, "char_end": 2, "start": 12, "end": 13,
                           "granularity": "word", "status": "ok", "time_source": "api"}], "cues": [],
                "devices": {"aligner": {"model": "cuda:0", "forward_observation": ["cuda:0"]}},
                "experimental_alignment": {"records": [{"segment_index": 0, "failure": None,
                    "decoder_input_device": "cuda:0", "decoder_output_device": "cuda:0"}]},
                "experimental_preprocessing": {"records": [{"segment_index": 0, "actual_input_device": "cuda:0"}]}}

    def test_prepare_preserves_exact_sources_and_complete_arm_registry(self):
        plan = batch.prepare("pilot", ["reazon", "jonatas"])
        self.assertEqual(len(plan["clips"]), 4)
        self.assertEqual(len(plan["tasks"]), 24)
        self.assertEqual([c["id"] for c in plan["baselines"]], list(batch.BASELINES))
        for task in plan["tasks"]:
            upstream = batch.read(task["upstream"]["path"])
            saved = batch.read(task["cached_result"]["path"])
            self.assertEqual(upstream["text"], saved["text"])
            self.assertEqual(upstream["original_segments"], saved["original_segments"])
            self.assertEqual(task["upstream"]["sha256"], batch.digest(task["upstream"]["path"]))
        batch.verify_plan("pilot")
        with self.assertRaises(FileExistsError):
            batch.prepare("pilot", ["reazon"])

    def test_incomplete_assets_and_changed_sources_are_rejected(self):
        manifest = self.root / ".local/manifests/model-mms-1b-all.json"
        value = batch.read(manifest)
        value["complete"] = False
        manifest.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "provisioned"):
            batch.prepare("missing-model", ["mms"])
        self.assertFalse((self.local / "missing-model").exists())
        batch.prepare("frozen", ["reazon"])
        (self.root / "experiments/japanese_ctc/run.py").write_text("# changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "SHA256 changed"):
            batch.verify_plan("frozen")

    def test_explicit_full_and_padding_arms_and_runner_cli(self):
        with self.assertRaises(ValueError):
            batch.prepare("none", [])
        with self.assertRaises(ValueError):
            batch.prepare("bad-pad", ["jonatas"], zero_pad_seconds=.5)
        plan = batch.prepare("full", ["reazon"], routes=("w1",), scope="full", zero_pad_seconds=.5)
        self.assertEqual(len(plan["tasks"]), 12)
        task, clip = plan["tasks"][0], plan["clips"][0]
        command = batch.command(task, clip, plan)
        self.assertEqual(command[command.index("--asr-result") + 1], task["upstream"]["path"])
        self.assertEqual(command[command.index("--route") + 1], "W1")
        self.assertEqual(command[command.index("--zero-pad-seconds") + 1], "0.5")

    def test_gpu_partial_segment_failure_retains_valid_units(self):
        result = self.result(self.clips[0])
        result["experimental_alignment"]["records"].append({"segment_index": 1, "failure": "short waveform"})
        batch.validate_gpu(result)
        for key in ("model", "forward_observation"):
            broken = deepcopy(result)
            broken["devices"]["aligner"][key] = "cpu" if key == "model" else ["cpu"]
            with self.assertRaises(ValueError):
                batch.validate_gpu(broken)

    def test_score_failure_preserves_cached_text_and_all_denominators(self):
        plan = batch.prepare("scoring", ["reazon"], routes=("w1",))
        plan_hash = batch.digest(self.local / "scoring/plan.json")
        for task in plan["tasks"]:
            record = {"plan_sha256": plan_hash, "task_id": task["id"], "status": "failed", "artifacts": {}}
            batch.write_new(self.local / "scoring/progress" / f"{task['id']}.json", record)
        report = batch.score("scoring", bootstrap=False)
        route = next(r for r in report["pooled"]["routes"] if r["route_id"] == "w1-reazon")
        summary = route["summary"]
        self.assertEqual(summary["alignment_failure_count"], 4)
        self.assertEqual(summary["text"]["CER"], 0)
        self.assertEqual(summary["text"]["candidate_characters"], 8)
        self.assertEqual(summary["timing"]["denominator"], 4)
        manifest = batch.read(self.local / "scoring/evaluation.json")
        self.assertEqual(len(manifest["configurations"]), 5)
        failed = batch.read(manifest["configurations"][-1]["runs"][0]["result_path"])
        self.assertEqual(failed["text"], "AB")
        self.assertEqual(failed["units"], [])

    def test_nonterminal_registry_cannot_be_scored(self):
        batch.prepare("pending", ["reazon"])
        with self.assertRaisesRegex(ValueError, "not terminal"):
            batch.score("pending", bootstrap=False)

    def test_parity_detects_actual_interval_changes(self):
        original = self.result(self.clips[0])
        self.assertTrue(batch.parity(original, original)["units_equal"])
        changed = deepcopy(original)
        changed["units"][0]["start"] += .01
        self.assertFalse(batch.parity(changed, original)["units_equal"])


if __name__ == "__main__":
    unittest.main()
