"""Offline macroblock visibility, historical defaults and native worker contracts."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from experiments.translation_demo import adapters
from .cli import digest
from .test_worker import FakeClient, budget
from .test_v2_prepare import scene
from .v2_prepare import COMMON_SOURCE_PROTOCOL, pack_scene, prepare
from .v2_recipes import completion_request, render_window
from .v2_worker import load_plan, run_window


# Captured from frozen runtime21 before editing staging. The payload includes
# complete windows/mapping, native C0 prompts and all request fields, not output.
FROZEN_DEFAULTS = {
    (23, 3): "3c67572431368bd11b2ee728353a936c320a72f0e20fab1ce62048373239b5f8",
    (23, 5): "d351a5d69398248db985520ef7e8c8554a2f4194f39992a97f065f3a29020404",
    (23, 20): "4668a78992d6809af4d0eac6b3a1d4651dda3ef469d991d96d04a3cf7c3943d3",
    (135, 3): "9414ffa85cab30bf05780e00b458d733e61b8b9da5ea4b28f9779b82c5d4e7e0",
    (135, 5): "7d8bfa16ee4f0fd52a87601c6a7d973f536fd4239d6c45cdf8a9d52b30de136d",
    (135, 20): "eeaaeb7a4c677e94d81cc39b2debbf1883ecc2f67c832c2e8fb1846423e926e4",
    (160, 3): "6604bf95dec1105ae5edfe0037d7af17e5420d3b5f9abb69754701cbc54be4f3",
    (160, 5): "6b0dce7c8f3ee8ca75a3ce2a9d56a2dc96fcea79b5007792c9d9f5e2a56cf939",
    (160, 20): "60cca386e686362623cd09b5f9ff4523e275e4e7b70a6a6ab5fa1123bd50c4e0",
}


def item():
    return {"recipe": "c0", "sampling": "official", "cache_prompt": True,
            "seed": 20261008, "n_predict": 4096, "max_attempts": 2}


def construction(count, size):
    rows, mapping = pack_scene(scene(count), target_size=size)
    return {"windows": rows, "mapping": mapping,
            "prompts": [render_window("c0", row, item()) for row in rows],
            "requests": [completion_request(item(), [11, 22, 33], row["translate_ids"]) for row in rows]}


def source_fixture(root):
    source = scene(135)
    source["scene_id"] = source["id"]
    manifest = root / "source-manifest.json"
    manifest.write_text(json.dumps({"windows": [{"id": "score-cross-block", "scene_id": source["id"],
                        "split": "screen-a", "scored_ids": [str(i) for i in range(58, 63)]}]}), encoding="utf-8")
    scenes = root / "scenes.jsonl"
    scenes.write_text(json.dumps(source, ensure_ascii=False) + "\n", encoding="utf-8")
    freeze = {"version": "hy30-flow-v2-source-v1", "state": "source_frozen_reference_unreviewed",
              "role": "screening", "artifacts": [{"path": p.name, "sha256": digest(p)} for p in (manifest, scenes)]}
    (root / "freeze-manifest.json").write_text(json.dumps(freeze), encoding="utf-8")
    return {"manifest": manifest, "scenes": scenes, "output": root / "prepared",
            "split": "screen-a", "recipe_id": "common-source-test", "stage": "qualification"}


class CommonSourceTests(unittest.TestCase):
    def test_frozen_defaults_keep_complete_prompt_and_request_bytes(self):
        for key, expected in FROZEN_DEFAULTS.items():
            with self.subTest(count=key[0], target_size=key[1]):
                encoded = json.dumps(construction(*key), ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()
                self.assertEqual(hashlib.sha256(encoded).hexdigest(), expected)
                self.assertEqual(pack_scene(scene(key[0]), target_size=key[1]),
                                 pack_scene(scene(key[0]), target_size=key[1], common_context_block_size=None))

    def test_all_scene_lengths_share_per_cue_ordered_source_and_unchanged_targets(self):
        for count in (1, 23, 59, 60, 61, 80, 120, 121, 135, 160):
            footprints = []
            for size in (3, 5, 20):
                with self.subTest(count=count, target_size=size):
                    original, original_mapping = pack_scene(scene(count), target_size=size)
                    windows, mapping = pack_scene(scene(count), target_size=size, common_context_block_size=60)
                    self.assertEqual([row["translate_ids"] for row in windows],
                                     [row["translate_ids"] for row in original])
                    self.assertEqual([row["id"] for row in windows], [row["id"] for row in original])
                    self.assertEqual([cue for row in windows for cue in row["translate_ids"]], scene(count)["translate_ids"])
                    seen = {}
                    for window, batch, old_batch in zip(windows, mapping, original_mapping, strict=True):
                        adapters.validate_window(window)
                        self.assertEqual(set(window), {"id", "source_language", "target_language", "context", "translate_ids"})
                        for key in ("start_position", "end_position", "full_batch", "warmup"):
                            self.assertEqual(batch[key], old_batch[key])
                        visible = [cue["id"] for cue in window["context"]]
                        geometry = batch["common_source_visibility"]
                        self.assertEqual(geometry["visible_ids"], visible)
                        self.assertEqual(batch["readonly_ids"], [cue for cue in visible if cue not in window["translate_ids"]])
                        self.assertLessEqual(batch["end_position"], geometry["block_end_position"])
                        for cue in window["translate_ids"]:
                            seen[cue] = visible
                    footprints.append(seen)
            self.assertEqual(footprints[0], footprints[1])
            self.assertEqual(footprints[0], footprints[2])

    def test_macroblock_boundaries_outer_context_and_clipped_tail(self):
        windows, mapping = pack_scene(scene(135), target_size=20, common_context_block_size=60)
        self.assertEqual([cue["id"] for cue in windows[0]["context"]], [str(i) for i in range(61)])
        self.assertEqual([cue["id"] for cue in windows[3]["context"]], [str(i) for i in range(59, 121)])
        self.assertEqual([cue["id"] for cue in windows[-1]["context"]], [str(i) for i in range(119, 135)])
        self.assertEqual(windows[-1]["translate_ids"], [str(i) for i in range(120, 135)])
        self.assertEqual(mapping[-1]["common_source_visibility"]["block_end_position"], 135)
        self.assertFalse(mapping[-1]["full_batch"])

    def test_outer_neighbors_are_explicit_asymmetric_and_frozen_scene_only(self):
        windows, _ = pack_scene(scene(135), target_size=5, common_context_block_size=60,
                                context_before=3, context_after=0)
        self.assertEqual([cue["id"] for cue in windows[12]["context"]], [str(i) for i in range(57, 120)])
        self.assertEqual([cue["id"] for cue in windows[-1]["context"]], [str(i) for i in range(117, 135)])

    def test_block20_allows_only_aligned_fixed_targets(self):
        footprints = []
        for size in (5, 20):
            windows, _ = pack_scene(scene(135), target_size=size, common_context_block_size=20)
            footprints.append({cue: row["context"] for row in windows for cue in row["translate_ids"]})
        self.assertEqual(footprints[0], footprints[1])
        with self.assertRaisesRegex(ValueError, "divisible"):
            pack_scene(scene(135), target_size=3, common_context_block_size=20)

    def test_ambiguous_packing_and_invalid_block_types_fail_atomically(self):
        for change in ({"token_target": 400}, {"offset": 1}, {"offset": 60}, {"common_context": True},
                       {"common_context_block_size": 0}, {"common_context_block_size": -1},
                       {"common_context_block_size": True}, {"common_context_block_size": 60.0},
                       {"target_size": 7}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                pack_scene(scene(135), **{"common_context_block_size": 60, **change})

    def test_prepare_binds_policy_geometry_and_cross_block_scoring_without_new_worker_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            args = source_fixture(Path(temp))
            prepare(**args, target_size=3, common_context_block_size=60)
            root = args["output"]
            packed = json.loads((root / "packed-mapping.json").read_text(encoding="utf-8"))
            provenance = json.loads((root / "preparation.json").read_text(encoding="utf-8"))
            policy = packed["source_visibility_policy"]
            self.assertEqual(policy["protocol"], COMMON_SOURCE_PROTOCOL)
            self.assertEqual(policy["block_size"], 60)
            self.assertEqual(provenance["source_visibility_policy"], policy)
            self.assertEqual(provenance["mapping_sha256"], digest(root / "packed-mapping.json"))
            self.assertEqual(packed["packing"]["common_context_block_size"], 60)
            plan, workloads = load_plan(root / "session-plan.json")
            self.assertEqual(workloads[0][0]["packed_mapping_sha256"], provenance["mapping_sha256"])
            self.assertEqual(len(workloads[0][1].read_text(encoding="utf-8").splitlines()), 45)
            audit = json.loads((root / "position-audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["source_cues"], 135)
            self.assertEqual(audit["scoring_windows"], 1)
            self.assertEqual([row["cue_id"] for row in audit["scored_cues"]], [str(i) for i in range(58, 63)])
            self.assertEqual(len({row["batch_id"] for row in audit["scored_cues"]}), 2)
            self.assertNotIn("source_visibility_policy", plan)

    def test_default_preparation_has_no_new_policy_or_geometry(self):
        with tempfile.TemporaryDirectory() as temp:
            args = source_fixture(Path(temp))
            prepare(**args)
            packed = json.loads((args["output"] / "packed-mapping.json").read_text(encoding="utf-8"))
            provenance = json.loads((args["output"] / "preparation.json").read_text(encoding="utf-8"))
            self.assertNotIn("source_visibility_policy", packed)
            self.assertNotIn("source_visibility_policy", provenance)
            self.assertNotIn("common_context_block_size", packed["packing"])
            self.assertTrue(all("common_source_visibility" not in batch for batch in packed["batches"]))

    def test_overlay_and_invalid_geometry_reject_before_artifact_publication(self):
        for changes in ({"source_preparation_path": Path("unused-options.json")},
                        {"source_preparation_sha256": "f" * 64},
                        {"source_preparation_projection": "evidence-scene-card-v1"},
                        {"target_size": 7}, {"common_context": True}, {"token_target": 600}, {"offset": 3}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as temp:
                args = source_fixture(Path(temp))
                with self.assertRaises(ValueError):
                    prepare(**args, common_context_block_size=60, **changes)
                self.assertFalse(args["output"].exists())

    def test_worker_accepts_expanded_readonly_packet_and_native_guard_never_truncates(self):
        windows, _ = pack_scene(scene(135), target_size=3, common_context_block_size=60)
        source = windows[20]
        content = json.dumps({"translations": {cue: "译文" for cue in source["translate_ids"]}}, ensure_ascii=False)
        for tokens, expected in ((4032, "delivered"), (4033, "setup_failed")):
            with self.subTest(tokens=tokens):
                client = FakeClient([{"content": content, "tokens_predicted": 3, "timings": {"cache_n": 0}}], tokens=tokens)
                limits = budget(max_estimated_tokens=100000)
                cache = {"verified": False, "first_response_checked": False}
                row = run_window(client, source, item(), 8192, limits, cache)
                self.assertEqual(row["status"], expected, row)
                prompt = render_window("c0", source, item())
                self.assertEqual(row["attempts"][0]["prompt_sha256"],
                                 hashlib.sha256(json.dumps(prompt, ensure_ascii=False, sort_keys=True,
                                                          separators=(",", ":")).encode()).hexdigest())
                self.assertEqual(len(source["context"]), 62)
                if expected == "delivered":
                    self.assertEqual(set(row["translations"]), set(source["translate_ids"]))
                    self.assertEqual(limits.translation_calls, 1)
                    self.assertEqual(client.requests[0]["n_predict"], 4096)
                    self.assertTrue(cache["verified"])
                else:
                    self.assertEqual(client.requests, [])
                    self.assertEqual(limits.translation_calls, 0)
                    self.assertIn("context_budget", row["reason"])


if __name__ == "__main__":
    unittest.main()
