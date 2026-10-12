"""Synthetic cached scoring-only derivation checks; no inference or references."""

from copy import deepcopy
from pathlib import Path
import unittest

from experiments.translation_eval.runner import dump, dump_jsonl, load_jsonl, read_json, sha
from . import test_v2_delivery
from .v2_reproject import reproject_scoring, validate_derivation


class ReprojectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = test_v2_delivery.DeliveryTests()
        self.fixture.setUp()
        # Screening halves belong to scoring windows, not the shared JA scene.
        self.fixture.windows[0]["split"] = "screen-a"
        self.fixture.windows[1]["split"] = "screen-b"
        dump(self.fixture.manifest, {"windows": self.fixture.windows})
        self.fixture.packed["source_manifest"]["sha256"] = sha(self.fixture.manifest)
        dump(self.fixture.mapping, self.fixture.packed)
        run = read_json(self.fixture.run / "run.json")
        run.update(source_manifest_sha256=sha(self.fixture.manifest), packed_mapping_sha256=sha(self.fixture.mapping))
        dump(self.fixture.run / "run.json", run)
        self.fixture.execute()
        self.root = self.fixture.root
        self.original = self.root / "delivery"
        self.qualified = self.root / "qualified"
        self.manifest = self.qualified / "source-manifest.json"
        self.scenes = self.qualified / "scenes.jsonl"
        self.freeze = self.qualified / "freeze-manifest.json"
        self.output = self.root / "reprojected"
        dump(self.root / "freeze-manifest.json", {"state": "source_frozen_reference_unreviewed", "role": "screening",
             "artifacts": [{"path": self.fixture.manifest.name, "sha256": sha(self.fixture.manifest)}]})
        accepted = deepcopy(self.fixture.windows)
        for window, ids, wid in zip(accepted, [["source-0"], ["source-4"]], ["reserve1", "reserve2"]):
            window.update(id=wid, window_id=wid, scored_ids=ids, reserve_rank=7)
            for unit in window["units"]:
                unit["score"] = unit["id"] in ids
        dump(self.manifest, {"windows": accepted})
        self.scenes.write_bytes(self.fixture.scene_path.read_bytes())
        self.refreeze()
        self.original_hashes = {path: sha(path) for path in self.original.rglob("*") if path.is_file()}

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def refreeze(self) -> None:
        dump(self.freeze, {"state": "source_frozen_reference_qualified", "role": "screening",
             "reference_qualification": {"path": "DO-NOT-READ-reference.json", "sha256": "f" * 64},
             "original_source_freeze": {"path": str(self.root / "freeze-manifest.json"),
                                        "sha256": sha(self.root / "freeze-manifest.json")},
             "artifacts": [{"path": path.name, "sha256": sha(path)} for path in (self.manifest, self.scenes)]})

    def execute(self) -> dict:
        return reproject_scoring(self.original, self.manifest, self.scenes, self.output)

    def test_reserve_scoring_changes_without_new_samples_or_timing(self) -> None:
        report = self.execute()
        results = load_jsonl(self.output / "results.jsonl")
        self.assertEqual([row["id"] for row in results], ["reserve1", "reserve2"])
        self.assertEqual(results[0]["translations"], {"source-0": "中文source-0。"})
        self.assertTrue(all(row["elapsed_seconds"] is None for row in results))
        self.assertEqual(report["seed"], self.fixture.packed["seed"])
        self.assertEqual(report["costs"], read_json(self.original / "costs.json"))
        self.assertEqual(report["derivation"]["new_inference_calls"], 0)
        self.assertEqual(report["derivation"]["new_generated_samples"], 0)
        self.assertEqual(read_json(self.output / "incremental-costs.json")["generated_samples"], 0)
        self.assertEqual(report["derivation"]["original_packed_mapping"]["sha256"], sha(self.fixture.mapping))
        self.assertEqual(report["derivation"]["original_source_manifest"]["sha256"], sha(self.fixture.manifest))
        self.assertEqual((self.output / "scenes/scene1/chn.srt").read_bytes(),
                         (self.original / "scenes/scene1/chn.srt").read_bytes())
        self.assertEqual({path: sha(path) for path in self.original_hashes}, self.original_hashes)
        validate_derivation(report, self.output)

    def test_changed_japanese_scene_is_rejected(self) -> None:
        scene = deepcopy(self.fixture.scene)
        scene["context"][0]["text"] = "変更"
        dump_jsonl(self.scenes, [scene])
        self.refreeze()
        with self.assertRaisesRegex(ValueError, "changed text"):
            self.execute()
        self.assertFalse(self.output.exists())

    def test_changed_scene_order_or_serialization_is_rejected(self) -> None:
        scene = deepcopy(self.fixture.scene)
        scene["context"].reverse()
        scene["translate_ids"].reverse()
        dump_jsonl(self.scenes, [scene])
        self.refreeze()
        with self.assertRaisesRegex(ValueError, "scope or order"):
            self.execute()

    def test_changed_full_source_timing_is_rejected(self) -> None:
        accepted = read_json(self.manifest)
        accepted["windows"][0]["units"][0]["start_ms"] += 1
        dump(self.manifest, accepted)
        self.refreeze()
        with self.assertRaisesRegex(ValueError, "provenance"):
            self.execute()

    def test_targets_outside_generated_cues_are_rejected(self) -> None:
        accepted = read_json(self.manifest)
        accepted["windows"][0]["scored_ids"] = ["never-generated"]
        dump(self.manifest, accepted)
        self.refreeze()
        with self.assertRaisesRegex(ValueError, "generated source cues"):
            self.execute()

    def test_unqualified_source_freeze_is_rejected(self) -> None:
        freeze = read_json(self.freeze)
        freeze["state"] = "source_frozen_reference_unreviewed"
        dump(self.freeze, freeze)
        with self.assertRaisesRegex(ValueError, "qualified"):
            self.execute()

    def test_original_cached_translation_mutation_is_rejected(self) -> None:
        rows = load_jsonl(self.fixture.run / "results.jsonl")
        rows[0]["translations"]["source-0"] = "Changed cached output"
        dump_jsonl(self.fixture.run / "results.jsonl", rows)
        with self.assertRaisesRegex(ValueError, "hash changed"):
            self.execute()

    def test_original_scene_state_mutation_is_rejected(self) -> None:
        sidecar_path = self.original / "scenes/scene1/sidecar.json"
        sidecar = read_json(sidecar_path)
        sidecar["coverage"]["cue_states"]["source-0"]["text"] = "Changed"
        dump(sidecar_path, sidecar)
        with self.assertRaisesRegex(ValueError, "cue states"):
            self.execute()

    def test_derived_batch_sequence_mutation_is_rejected(self) -> None:
        report = self.execute()
        packed = read_json(self.output / "packed-mapping.json")
        packed["batches"].reverse()
        dump(self.output / "packed-mapping.json", packed)
        report["packed_mapping"]["sha256"] = sha(self.output / "packed-mapping.json")
        with self.assertRaisesRegex(ValueError, "more than"):
            validate_derivation(report, self.output)

    def test_cross_seed_reuse_is_rejected(self) -> None:
        report = self.execute()
        report["seed"] += 1
        with self.assertRaisesRegex(ValueError, "seed identity"):
            validate_derivation(report, self.output)

    def test_other_original_source_authority_is_rejected(self) -> None:
        other = self.root / "other-source/freeze-manifest.json"
        dump(other, {"role": "screening"})
        freeze = read_json(self.freeze)
        freeze["original_source_freeze"] = {"path": str(other), "sha256": sha(other)}
        dump(self.freeze, freeze)
        with self.assertRaisesRegex(ValueError, "original source authority"):
            self.execute()


if __name__ == "__main__":
    unittest.main()
