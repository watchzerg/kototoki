"""翻译配方移植的身份钉子：v3 `b10-joint` 原 hash、与冻结 v3 实现逐字节一致的提示／grammar／请求。"""

from __future__ import annotations

import json
import unittest

from kototoki.artifacts import sha256_bytes
from kototoki.srt import format_srt, parse_srt
from kototoki.translate import RECIPE_HASH
from kototoki.translate import recipes as R
from kototoki.translate.batching import build_batches, cue_positions
from kototoki.translate.data import scene_from_document

V3_B10_JOINT_HASH = "2ba680540f055b2ae0c8122faa3ba537418eb12720a552f53c3aa5b652d0969a"
SEED = 20261008


def document(n: int):
    return parse_srt(format_srt([(i * 2.0, i * 2.0 + 1.5, f"台詞{i}ですね") for i in range(n)]))


class RecipeIdentityTests(unittest.TestCase):
    def test_b10_joint_hash_is_the_v3_hash(self) -> None:
        # ADR-0006：已采纳流程基线的身份不得因移植改变。
        recipe = R.B10_JOINT
        self.assertEqual((recipe.batch_count, recipe.context_before, recipe.context_after, recipe.prompt),
                         (10, 1, 1, "joint"))
        self.assertEqual(recipe.recipe_hash, V3_B10_JOINT_HASH)

    def test_product_recipe_hash_is_exported(self) -> None:
        self.assertEqual(RECIPE_HASH, R.PRODUCT.recipe_hash)


class RequestBytesTests(unittest.TestCase):
    """请求字节钉子：独立于 experiments 的 SHA256，加上与冻结 v3 函数的直接对照。"""

    def batch_request(self, index: int = 1):
        scene = scene_from_document(document(23))
        batch = build_batches(scene, R.B10_JOINT)[index]
        window = batch.to_window(scene)
        prompt = R.render_translation(window)
        grammar = R.translation_grammar(window["translate_ids"])
        request = R.completion_request([ord(ch) for ch in prompt], SEED, grammar)
        return scene, window, prompt, grammar, request

    def test_pinned_prompt_grammar_request_sha256(self) -> None:
        _, _, prompt, grammar, request = self.batch_request()
        self.assertEqual(sha256_bytes(prompt.encode()), "2f563a0295fae7291f5728c571f0fcc9f6832f77dfbe09e30584f24d0a66351a")
        self.assertEqual(sha256_bytes(grammar.encode()), "49e31814fa687888a239e0c56da51d05e80c5e873029bf6d22df859377e452ec")
        self.assertEqual(sha256_bytes(json.dumps(request, ensure_ascii=False).encode()),
                         "11845aedeb44eabc40043c3c018c44a2148691fa377f86f75706a9acbade6fa2")

    def test_byte_identical_to_frozen_v3(self) -> None:
        from experiments.translation_v3 import recipes as V
        from experiments.translation_v3.batching import build_batches as v3_batches
        from experiments.translation_v3.data import Cue as V3Cue, Scene as V3Scene

        scene = scene_from_document(document(23))
        v3_scene = V3Scene(scene.scene_id, tuple(V3Cue(cue.id, cue.text) for cue in scene.cues))
        v3_recipe = V.BUILTIN["b10-joint"]
        ours = build_batches(scene, R.B10_JOINT)
        theirs = v3_batches(v3_scene, v3_recipe)
        self.assertEqual(len(ours), 3)
        self.assertEqual([b.record() for b in ours],
                         [{k: v for k, v in b.record().items() if k in ours[0].record()} for b in theirs])
        for a, b in zip(ours, theirs):
            window = a.to_window(scene)
            self.assertEqual(window, b.to_window(v3_scene))
            prompt = R.render_translation(window)
            self.assertEqual(prompt, V.render_translation(v3_recipe, window))
            ids = window["translate_ids"]
            tokens = [ord(ch) for ch in prompt]
            ours_request = R.completion_request(tokens, SEED, R.translation_grammar(ids))
            v3_request = V.completion_request(tokens, SEED, V.translation_grammar(v3_recipe, ids))
            self.assertEqual(json.dumps(ours_request, ensure_ascii=False), json.dumps(v3_request, ensure_ascii=False))
        self.assertEqual(R.B10_JOINT.spec(), v3_recipe.spec())

    def test_joint_changes_only_the_independence_instruction(self) -> None:
        from kototoki.translate import adapters

        _, window, prompt, _, _ = self.batch_request(0)
        self.assertEqual(prompt, adapters.render(window).replace(R.C0_INSTRUCTION, R.JOINT_INSTRUCTION))
        self.assertNotIn(R.C0_INSTRUCTION, prompt)

    def test_parse_translation_is_strict(self) -> None:
        self.assertEqual(R.parse_translation('{"translations":{"a":"甲","b":"乙"}}', ["a", "b"]), {"a": "甲", "b": "乙"})
        for bad in ('{"translations":{"a":"甲"}}', '{"translations":{"a":"甲","a":"乙","b":"丙"}}',
                    '{"translations":{"a":" ","b":"乙"}}', "not json"):
            with self.assertRaises(ValueError):
                R.parse_translation(bad, ["a", "b"])


class BatchingTests(unittest.TestCase):
    def test_batches_of_ten_with_one_neighbour_each_side(self) -> None:
        scene = scene_from_document(document(23))
        batches = build_batches(scene, R.B10_JOINT)
        self.assertEqual([len(b.target_ids) for b in batches], [10, 10, 3])
        self.assertEqual(batches[0].before_ids, ())
        self.assertEqual(batches[1].before_ids, (scene.ids[9],))
        self.assertEqual(batches[1].after_ids, (scene.ids[20],))
        self.assertEqual(batches[2].after_ids, ())
        self.assertEqual(batches[0].batch_id, f"{scene.scene_id}-b0001")
        positions = cue_positions(batches)
        self.assertEqual(set(positions), set(scene.ids))
        self.assertEqual(positions[scene.ids[19]], {"batch_index": 1, "position": "last", "offset": 9, "batch_size": 10})

    def test_scene_id_and_cue_ids_follow_the_ja_srt(self) -> None:
        doc = document(3)
        scene = scene_from_document(doc)
        self.assertEqual(scene.scene_id, f"srt-{doc.source_sha256[:12]}")
        self.assertEqual(scene.ids, [cue.id for cue in doc.cues])


if __name__ == "__main__":
    unittest.main()
