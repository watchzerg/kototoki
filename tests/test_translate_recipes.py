"""翻译配方移植的身份钉子：v3 `b10-joint`、`dp10-cut` 原 hash、与冻结 v3 实现逐字节一致的切包、提示／grammar／请求；
产品配方 `dp10-cut-degrade-v1` 只改 `overflow`、另算 hash，批次与请求字节与 `dp10-cut` 相同（旧产品配方
`b10-joint-degrade-v1` 同理对 `b10-joint`，钉子保留）。gap-pack-v2 切包与邻文规则的用例移植自
`experiments/scene_batching_v6/test_v7.py`，不导入 experiments。"""

from __future__ import annotations

import itertools
import json
import random
import unittest

from kototoki.artifacts import sha256_bytes
from kototoki.srt import format_srt, parse_srt
from kototoki.translate import RECIPE_HASH
from kototoki.translate import recipes as R
from kototoki.translate.batching import (Batch, Cue, Scene, build_batches, cue_positions, gap_pack_cuts, neighbours,
                                         scene_from_document, silence)

V3_B10_JOINT_HASH = "2ba680540f055b2ae0c8122faa3ba537418eb12720a552f53c3aa5b652d0969a"
B10_DEGRADE_V1_HASH = "994c0d03ac4c91fec437285b66f597c19ff28f09c2ecad5b0e9541437ca795fe"
V3_DP10_CUT_HASH = "ee72ce6683c89e5a1f83fd7ba99f54f3683966deed0e526c193780ad8c500b70"
DP10_DEGRADE_V1_HASH = "086754ca751365c21840742511bf39eaa621b8fc2f5a630372f22661fc86158e"
SEED = 20261008


def document(n: int):
    """相邻停顿 0.5 s 的均匀场景。"""
    return parse_srt(format_srt([(i * 2.0, i * 2.0 + 1.5, f"台詞{i}ですね") for i in range(n)]))


def scene_from_gaps(gaps: list[float | None], name: str = "S") -> Scene:
    """每条 1 s、按给定停顿排开（None：下一条没有时间戳）。"""
    cues, t = [Cue(f"{name}-J000", "台詞0", 0.0, 1.0)], 1.0
    for i, gap in enumerate(gaps, 1):
        if gap is None:
            cues.append(Cue(f"{name}-J{i:03d}", f"台詞{i}"))
            continue
        t += gap
        cues.append(Cue(f"{name}-J{i:03d}", f"台詞{i}", t, t + 1.0))
        t += 1.0
    return Scene(name, tuple(cues))


def document_from_gaps(gaps: list[float]):
    """同 `scene_from_gaps`，但经 SRT 往返（毫秒取整），用于与 v3 `translate-srt` 的输入逐字节对照。"""
    entries, t = [(0.0, 1.0, "台詞0ですね")], 1.0
    for i, gap in enumerate(gaps, 1):
        t += gap
        entries.append((t, t + 1.0, f"台詞{i}ですね"))
        t += 1.0
    return parse_srt(format_srt(entries))


def random_gaps(rng: random.Random, n: int) -> list[float | None]:
    return [rng.choice([0.2, 0.5, 0.8, 1.5, 3.0, 6.0, 12.0, 40.0, None]) for _ in range(n - 1)]


def cost(scene: Scene, cuts: list[int], pack: dict, target: int = 10) -> float | None:
    """切法的总惩罚（暴力参照）；不可行为 None。"""
    total, bounds = 0.0, cuts + [len(scene.cues)]
    for a, b in zip(bounds, bounds[1:]):
        if b - a > pack["max"]:
            return None
        gaps = [g for i in range(a, b - 1) if (g := silence(scene, i)) is not None]
        if any(g >= pack["hard_gap"] for g in gaps):
            return None
        total += (b - a - target) ** 2 + (pack["small_penalty"] if b - a < pack["min"] else 0)
        total += sum(pack["soft_weight"] * g for g in gaps if g >= pack["soft_gap"])
        if b < len(scene.cues):
            g = silence(scene, b - 1)
            total += next((p for below, p in pack["cut_penalty"] if g is None or g < below), 0.0)
    return total


class RecipeIdentityTests(unittest.TestCase):
    def test_b10_joint_hash_is_the_v3_hash(self) -> None:
        # ADR-0006：已采纳流程基线的身份不得因移植改变；加入 `gap_pack` 字段后也不变。
        recipe = R.B10_JOINT
        self.assertEqual((recipe.batch_count, recipe.context_before, recipe.context_after, recipe.prompt, recipe.gap_pack),
                         (10, 1, 1, "joint", None))
        self.assertEqual(recipe.recipe_hash, V3_B10_JOINT_HASH)
        self.assertEqual(R.B10_JOINT_DEGRADE_V1.recipe_hash, B10_DEGRADE_V1_HASH)
        self.assertNotIn("gap_pack", recipe.spec()["recipe"])
        self.assertNotIn("gap_pack", recipe.spec()["versions"])

    def test_dp10_cut_hash_is_the_v3_hash(self) -> None:
        # ADR-0010：dp10-cut 的身份与 v3 `BUILTIN["dp10-cut"]` 相同。
        recipe = R.DP10_CUT
        self.assertEqual((recipe.batch_count, recipe.context_before, recipe.context_after, recipe.prompt), (10, 1, 1, "joint"))
        self.assertEqual((recipe.gap_pack["max"], recipe.gap_pack["max_visible"], recipe.gap_pack["hard_gap"]), (10, 12, 20.0))
        self.assertEqual(recipe.spec()["versions"]["gap_pack"], "gap-pack-v2")
        self.assertEqual(recipe.recipe_hash, V3_DP10_CUT_HASH)

    def test_product_recipe_hash_is_exported(self) -> None:
        self.assertIs(R.PRODUCT, R.DP10_CUT_DEGRADE_V1)
        self.assertEqual(RECIPE_HASH, R.PRODUCT.recipe_hash)
        self.assertEqual(RECIPE_HASH, DP10_DEGRADE_V1_HASH)
        self.assertEqual(len({R.B10_JOINT.recipe_hash, R.B10_JOINT_DEGRADE_V1.recipe_hash, R.DP10_CUT.recipe_hash,
                              RECIPE_HASH}), 4)

    def test_degrade_recipes_differ_from_their_base_only_in_overflow(self) -> None:
        for ours, base in ((R.DP10_CUT_DEGRADE_V1, R.DP10_CUT), (R.B10_JOINT_DEGRADE_V1, R.B10_JOINT)):
            ours, base = ours.spec(), base.spec()
            self.assertEqual(ours["fixed"].pop("overflow"), "degrade-10-5-1-keep-source")
            self.assertEqual(base["fixed"].pop("overflow"), "recorded-failure-no-truncation-no-auto-shrink")
            self.assertEqual(ours, base)

    def test_degrade_recipes_batch_like_their_base(self) -> None:
        # 提示、grammar 与请求的构造函数不取配方，字节由 RequestBytesTests 钉住；配方只经批次计划起作用。
        rng = random.Random(5)
        for _ in range(30):
            scene = scene_from_gaps(random_gaps(rng, rng.randint(1, 40)))
            self.assertEqual(build_batches(scene, R.DP10_CUT_DEGRADE_V1), build_batches(scene, R.DP10_CUT))
            self.assertEqual(build_batches(scene, R.B10_JOINT_DEGRADE_V1), build_batches(scene, R.B10_JOINT))


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

    def assert_byte_identical_to_v3(self, doc, ours_recipe, v3_name: str, expected_batches: int) -> None:
        from experiments.translation_v3 import recipes as V
        from experiments.translation_v3.batching import build_batches as v3_batches
        from experiments.translation_v3.data import Cue as V3Cue, Scene as V3Scene

        scene = scene_from_document(doc)
        # v3 `translate-srt`（cli.py）同样以 `start_ms / 1000` 建场景。
        v3_scene = V3Scene(scene.scene_id, tuple(V3Cue(c.id, c.text, c.start_ms / 1000, c.end_ms / 1000) for c in doc.cues))
        v3_recipe = V.BUILTIN[v3_name]
        ours = build_batches(scene, ours_recipe)
        theirs = v3_batches(v3_scene, v3_recipe)
        self.assertEqual(len(ours), expected_batches)
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
        self.assertEqual(ours_recipe.spec(), v3_recipe.spec())

    def test_b10_joint_byte_identical_to_frozen_v3(self) -> None:
        self.assert_byte_identical_to_v3(document(23), R.B10_JOINT, "b10-joint", 3)

    def test_dp10_cut_byte_identical_to_frozen_v3(self) -> None:
        # 不均匀停顿：切点、邻文取舍与请求都要和 v3 一致。
        gaps = [0.2, 0.6, 1.5, 0.3, 0.3, 4.0, 0.2, 0.9, 25.0, 0.1, 0.1, 2.5, 0.4, 0.4, 0.4, 7.0, 0.2, 0.2, 1.2, 0.3,
                0.3, 0.3, 12.0, 0.2, 0.5, 0.5, 3.0, 0.2]
        doc = document_from_gaps(gaps)
        self.assert_byte_identical_to_v3(doc, R.DP10_CUT, "dp10-cut", 3)  # 25 s 硬切；12 s 停顿留在包内
        rng = random.Random(29)
        for _ in range(10):
            doc = document_from_gaps([g for g in random_gaps(rng, rng.randint(2, 40)) if g is not None])
            self.assert_byte_identical_to_v3(doc, R.DP10_CUT, "dp10-cut", len(build_batches(scene_from_document(doc), R.DP10_CUT)))

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


class CountBatchingTests(unittest.TestCase):
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

    def test_scene_id_cue_ids_and_times_follow_the_ja_srt(self) -> None:
        doc = document(3)
        scene = scene_from_document(doc)
        self.assertEqual(scene.scene_id, f"srt-{doc.source_sha256[:12]}")
        self.assertEqual(scene.ids, [cue.id for cue in doc.cues])
        self.assertEqual([(c.start, c.end) for c in scene.cues], [(0.0, 1.5), (2.0, 3.5), (4.0, 5.5)])
        self.assertEqual([silence(scene, i) for i in range(2)], [0.5, 0.5])


class GapPackTests(unittest.TestCase):
    """gap-pack-v2（ADR-0010）：dp10-cut 的切包与邻文规则。"""

    PACK = R.DP10_CUT_PACK

    def test_dp_matches_brute_force(self) -> None:
        rng = random.Random(13)
        for trial in range(150):
            n = rng.randint(1, 15)
            scene = scene_from_gaps(random_gaps(rng, n))
            best = min(c for r in range(n) for inner in itertools.combinations(range(1, n), r)
                       if (c := cost(scene, [0, *inner], self.PACK)) is not None)
            self.assertAlmostEqual(cost(scene, gap_pack_cuts(scene, 10, self.PACK), self.PACK), best, msg=f"trial {trial}")

    def test_cut_moves_to_longer_pause(self) -> None:
        # 18 条：不按停顿加罚时最优为 9/9（切在 0.2 s 停顿）；加罚后为 10/8，切在 1.5 s 停顿。
        scene = scene_from_gaps([0.2] * 9 + [1.5] + [0.2] * 7)
        self.assertEqual(gap_pack_cuts(scene, 10, self.PACK | {"cut_penalty": [[0.0001, 1.0]]}), [0, 9])
        self.assertEqual(gap_pack_cuts(scene, 10, self.PACK), [0, 10])

    def test_hard_gap_always_cuts_and_short_batches_only_inside_short_segments(self) -> None:
        rng = random.Random(17)
        for _ in range(200):
            scene = scene_from_gaps(random_gaps(rng, rng.randint(1, 80)))
            batches = build_batches(scene, R.DP10_CUT)
            self.assertEqual([k for b in batches for k in b.target_ids], scene.ids)
            hard = [i + 1 for i in range(len(scene.cues) - 1) if (g := silence(scene, i)) is not None and g >= 20]
            self.assertTrue(set(hard) <= {b.start for b in batches})
            edges = [0, *hard, len(scene.cues)]
            for b in batches:
                self.assertLessEqual(len(b.target_ids), 10)
                self.assertLessEqual(len(b.before_ids) + len(b.target_ids) + len(b.after_ids), 12)
                if len(b.target_ids) < 6:  # 短包只出现在被硬切夹出的 <6 条段，或只能拆成 6＋5 的 11 条段
                    segment = next(e2 - e1 for e1, e2 in zip(edges, edges[1:]) if e1 <= b.start < e2)
                    self.assertIn(segment, (1, 2, 3, 4, 5, 11))

    def test_neighbour_rules(self) -> None:
        # 两批各 10 条，批间停顿决定邻文：前邻 <5 s 可见，后邻 <1 s 可见，缺时间戳按无停顿。
        for gap, expected in ((0.9, (1, 1)), (1.0, (1, 0)), (4.9, (1, 0)), (5.0, (0, 0)), (None, (1, 1))):
            scene = scene_from_gaps([0.1] * 9 + [gap] + [0.1] * 9)
            first, second = build_batches(scene, R.DP10_CUT)
            self.assertEqual([len(b.target_ids) for b in (first, second)], [10, 10])
            self.assertEqual((len(second.before_ids), len(first.after_ids)), expected, gap)
        # 可见上限 12：先去后邻、再去前邻（dp10-cut 本身 ≤10 条，用更宽的上限直接测规则）。
        wide = R.Recipe("wide", context_before=3, context_after=3, gap_pack=self.PACK)
        scene = scene_from_gaps([0.1] * 29)
        for batch in build_batches(scene, wide):
            self.assertLessEqual(len(batch.before_ids) + len(batch.target_ids) + len(batch.after_ids), 12)
        self.assertEqual(neighbours(scene, 10, 20, wide), (8, 20))  # 16 可见 → 先去掉 3 条后邻，再去 1 条前邻
        self.assertEqual(neighbours(scene, 10, 20, R.DP10_CUT), (9, 21))
        self.assertEqual(neighbours(scene, 10, 20, R.B10_JOINT), (9, 21))

    def test_uniform_scene_prefers_even_batches_over_a_short_tail(self) -> None:
        # 23 条、停顿 0.5 s：10/10/3 要付 1000 分的短包罚，8/8/7 不用。
        scene = scene_from_document(document(23))
        self.assertEqual(sorted(len(b.target_ids) for b in build_batches(scene, R.DP10_CUT)), [7, 8, 8])
        # 每 10 条之间隔 20 s（`tests.test_translate.document`）：硬切出 10/10/3。
        from tests.test_translate import document as paused
        scene = scene_from_document(paused(23))
        self.assertEqual([len(b.target_ids) for b in build_batches(scene, R.DP10_CUT)], [10, 10, 3])
        self.assertEqual([(len(b.before_ids), len(b.after_ids)) for b in build_batches(scene, R.DP10_CUT)],
                         [(0, 0), (0, 0), (0, 0)])

    def test_empty_or_duplicate_scene_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_batches(Scene("S", ()), R.DP10_CUT)
        with self.assertRaises(ValueError):
            build_batches(Scene("S", (Cue("a", "x", 0.0, 1.0), Cue("a", "y", 1.0, 2.0))), R.DP10_CUT)

    def test_records_keep_their_shape(self) -> None:
        scene = scene_from_gaps([0.2, 30.0, 0.2])
        (first, second) = build_batches(scene, R.DP10_CUT)
        self.assertIsInstance(first, Batch)
        self.assertEqual(set(first.record()), {"index", "batch_id", "target_ids", "before_ids", "after_ids", "start", "stop"})
        self.assertEqual((first.record()["stop"], second.record()["start"]), (2, 2))


if __name__ == "__main__":
    unittest.main()
