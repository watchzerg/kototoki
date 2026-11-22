"""产品配方 `q3-translate-v1` 的身份钉子：配方 hash、与研究侧 Q2（归档 tag 中的 `archive/2026-11-18-pre-research-restructure:experiments/translation_v3/`
`qwen.py`、`strata.py` 与 `scene_batching_v6/v12.py::strata_recipe_data`）逐字节一致的切包、邻文、提示与请求体（摘要钉子），注入行与研究
`names11.py::product_tables` 的规则一致（字面量钉子），回复校验。gap-pack-v2 切包用例移植自
`archive/2026-11-18-pre-research-restructure:experiments/scene_batching_v6/test_v7.py`。本文件不导入研究代码。"""

from __future__ import annotations

import hashlib
import itertools
import json
import random
import unittest

from kototoki.artifacts import object_hash
from kototoki.srt import format_srt, parse_srt
from kototoki.translate import RECIPE_HASH
from kototoki.translate import recipes as R
from kototoki.translate.batching import Cue, Scene, build_batches, gap_pack_cuts, scene_from_document, silence

Q3_TRANSLATE_V1_HASH = "1372b37146babf6817ffeacf4d0019af5eec319dc19cf7d62a1d5f1f7fde577d"  # runtime 去掉 Strata 版本前（ADR-0034）为 865bcd1d…
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


def random_cues(rng: random.Random, n: int) -> list[tuple[str, str, float, float]]:
    t, cues = 0.0, []
    for i in range(n):
        start, end = t, t + rng.uniform(0.5, 4)
        t = end + rng.choice([0.1, 0.4, 0.9, 1.5, 3.0, 6.0, 25.0])
        text = f"テキスト{i}セイバー" if i % 7 == 0 else (f"士郎{i}" if i % 11 == 0 else f"台詞{i}")
        cues.append((f"abcd1234-cue-{i + 1}", text, start, end))
    return cues


class RecipeIdentityTests(unittest.TestCase):
    def test_hash_is_pinned_and_exported(self) -> None:
        # ADR-0029：配方任何字段变化都要换 hash、并改这里与 ADR。
        self.assertEqual(R.RECIPE_HASH, Q3_TRANSLATE_V1_HASH)
        self.assertEqual(RECIPE_HASH, object_hash(R.RECIPE))
        self.assertEqual(R.RECIPE_NAME, "q3-translate-v1")


class Q2ByteIdentityTests(unittest.TestCase):
    """产品的正常包请求必须与研究侧 Q2 逐字节相同（ADR-0029「请求规则」）。钉值取自 2026-11-11 的研究实现
    （`archive/2026-11-18-pre-research-restructure:experiments/translation_v3/` 的 batching、qwen、strata 与 `scene_batching_v6/v12.py::strata_recipe_data`
    组出的 Q2）。"""

    BATCHES_SHA256 = "b64af8526604f759934a18efec15f36645464a0018c4070ae326a6ba80944687"
    PLAIN_BODY_SHA256 = "fa3ce2aa14439b779726b49e9ba61b97489611bdfac4fa399aa1ad70152f6a61"

    def test_batches_windows_and_request_bodies_are_pinned(self) -> None:
        rows = [{"source": "セイバー", "translation": "Saber"}, {"source": "士郎", "translation": "士郎"},
                {"source": "凛", "translation": "凛"}]
        rng = random.Random(7)
        observed, compared = [], 0
        for _ in range(30):
            cues = random_cues(rng, rng.randint(1, 120))
            scene = Scene("srt-x", tuple(Cue(*c) for c in cues))
            batches = build_batches(scene)
            observed.append([[(b.target_ids, b.before_ids, b.after_ids) for b in batches]])
            for batch in batches:
                window = batch.to_window(scene)
                bodies = [json.dumps(R.request_body(R.messages(window, rows), seed), ensure_ascii=False)
                          for seed in (SEED, SEED + 1)]
                observed[-1].append([window, bodies])
                compared += 2
        self.assertGreater(compared, 200)
        digest = hashlib.sha256(json.dumps(observed, ensure_ascii=False).encode("utf-8")).hexdigest()
        self.assertEqual(digest, self.BATCHES_SHA256)

    def test_name_rows_follow_the_research_product_table_rule(self) -> None:
        def entity(confidence: str, *forms: tuple[str, str]) -> dict:
            return {"entity_ja": forms[0][0], "kind": "person", "confidence": confidence, "zh": forms[0][1],
                    "forms": [{"ja": ja, "zh": zh} for ja, zh in forms], "zh_variants": [], "evidence": []}

        table = {"entries": [entity("high", ("セイバー", "Saber"), ("セイバ", "Saber")), entity("medium", ("士郎", "士郎")),
                             entity("high", ("セイバー", "塞巴"), ("凛", "凛")), entity("low", ("桜", "樱")),
                             entity("high", (" ", "空"), ("遠坂", " "))]}
        # 取自 2026-11-11 的 `archive/2026-11-18-pre-research-restructure:experiments/scene_batching_v6/names11.py` 中 `product_tables("high")` 在同一张表上的输出。
        self.assertEqual(R.name_rows(table), [{"source": "セイバー", "translation": "Saber"},
                                              {"source": "セイバ", "translation": "Saber"},
                                              {"source": "凛", "translation": "凛"}])



class ParseTests(unittest.TestCase):
    def test_cues_are_judged_one_by_one(self) -> None:
        self.assertEqual(R.parse_translation('{"translations":{"a":"甲","b":"乙"}}', ["a", "b"]),
                         R.Parsed({"a": "甲", "b": "乙"}, {}, 0))
        self.assertEqual(R.parse_translation('﻿ {"translations":{"a":"甲\\n乙"}} ', ["a"]),
                         R.Parsed({"a": "甲\n乙"}, {}, 0))
        # 顺序不看；缺失、空串、非字符串、含空行（含末尾换行）各自未解决；多出的 ID 只计数。
        parsed = R.parse_translation('{"translations":{"e":"戊","d":"甲\\n\\n续","c":" ","x":"多","b":3,'
                                     '"f":"己\\n"}}', ["a", "b", "c", "d", "e", "f"])
        self.assertEqual(parsed, R.Parsed({"e": "戊"}, {"a": "missing", "b": "empty", "c": "empty", "d": "blank_line",
                                                        "f": "blank_line"}, 1))
        self.assertEqual(list(parsed.unresolved), ["a", "b", "c", "d", "f"])


class BatchingTests(unittest.TestCase):
    def test_wide_context_counts_cues_and_ignores_pauses(self) -> None:
        # 每 10 条之间隔 20 s（`tests.core.test_translate.document`）：dp10-cut 硬切出 10/10/3，邻文只按条数取。
        from tests.core.test_translate import document as paused
        scene = scene_from_document(paused(23))
        batches = build_batches(scene)
        self.assertEqual([len(b.target_ids) for b in batches], [10, 10, 3])
        self.assertEqual([(len(b.before_ids), len(b.after_ids)) for b in batches], [(0, 5), (10, 3), (20, 0)])


class GapPackTests(unittest.TestCase):
    """gap-pack-v2（ADR-0021「dp10-cut 切包」）：dp10-cut 的切包规则。"""

    PACK = R.DP10_CUT_PACK

    def test_dp_matches_brute_force(self) -> None:
        rng = random.Random(13)
        for trial in range(150):
            n = rng.randint(1, 15)
            scene = scene_from_gaps(random_gaps(rng, n))
            best = min(c for r in range(n) for inner in itertools.combinations(range(1, n), r)
                       if (c := cost(scene, [0, *inner], self.PACK)) is not None)
            self.assertAlmostEqual(cost(scene, gap_pack_cuts(scene, 10, self.PACK), self.PACK), best, msg=f"trial {trial}")

    def test_hard_gap_always_cuts_and_short_batches_only_inside_short_segments(self) -> None:
        rng = random.Random(17)
        for _ in range(200):
            scene = scene_from_gaps(random_gaps(rng, rng.randint(1, 80)))
            batches = build_batches(scene)
            self.assertEqual([k for b in batches for k in b.target_ids], scene.ids)
            hard = [i + 1 for i in range(len(scene.cues) - 1) if (g := silence(scene, i)) is not None and g >= 20]
            self.assertTrue(set(hard) <= {b.start for b in batches})
            edges = [0, *hard, len(scene.cues)]
            for b in batches:
                self.assertLessEqual(len(b.target_ids), 10)
                self.assertLessEqual(len(b.before_ids) + len(b.target_ids) + len(b.after_ids), 35)
                if len(b.target_ids) < 6:  # 短包只出现在被硬切夹出的 <6 条段，或只能拆成 6＋5 的 11 条段
                    segment = next(e2 - e1 for e1, e2 in zip(edges, edges[1:]) if e1 <= b.start < e2)
                    self.assertIn(segment, (1, 2, 3, 4, 5, 11))

    def test_uniform_scene_prefers_even_batches_over_a_short_tail(self) -> None:
        # 23 条、停顿 0.5 s：10/10/3 要付 1000 分的短包罚，8/8/7 不用。
        scene = scene_from_document(document(23))
        self.assertEqual(sorted(len(b.target_ids) for b in build_batches(scene)), [7, 8, 8])




if __name__ == "__main__":
    unittest.main()
