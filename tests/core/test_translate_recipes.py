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
from unittest import mock

from kototoki.artifacts import object_hash
from kototoki.srt import format_srt, parse_srt
from kototoki.translate import RECIPE_HASH
from kototoki.translate import recipes as R
from kototoki.translate.batching import (Batch, Cue, Scene, build_batches, cue_positions, gap_pack_cuts, neighbours,
                                         scene_from_document, silence)

Q3_TRANSLATE_V1_HASH = "865bcd1d06f0cc7af83a02f90d0ff2ae5c1fca012695d28e1dbbe4b4f0325964"
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

    def test_recipe_records_the_q2_identity(self) -> None:
        recipe = R.RECIPE
        self.assertEqual(recipe["model"], "qwen3.8-flash-next-iq3_s")
        self.assertEqual(recipe["neighbours"], {"version": "wide-context-v1", "before": 20, "after": 5, "max_visible": 35})
        self.assertEqual((recipe["prompt"]["version"], recipe["names"]["version"], recipe["names"]["filter"]),
                         ("qwen-joint-v1", "qwen-name-table-v1", "window"))
        self.assertEqual(recipe["runtime"]["resolved"]["drafting"], "dflash2")
        self.assertEqual((recipe["runtime"]["strata"], recipe["runtime"]["engine_build"]), ("0.2.12", "0.1.58"))
        self.assertIsNone(recipe["request"]["grammar"])
        self.assertEqual(recipe["request"]["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual(recipe["attempts"], {"max": 2, "seed_step": 1})
        self.assertEqual(recipe["overflow"], "unresolved-runs+halve-after-structural-failures+untranslated")
        self.assertTrue(recipe["validation"].startswith("strict-json+one-translations-object; per-cue "))

    def test_packing_is_the_v3_dp10_cut_pack(self) -> None:
        # 取自 2026-11-11 的 `archive/2026-11-18-pre-research-restructure:experiments/translation_v3/recipes.py` 中 `BUILTIN["dp10-cut"].gap_pack`。
        pack = {"min": 6, "max": 10, "soft_gap": 2.0, "hard_gap": 20.0, "soft_weight": 1.0, "small_penalty": 1000.0,
                "group_gap": None, "group_max": 10, "context_both_below": 1.0, "context_before_below": 5.0,
                "max_visible": 12, "cut_penalty": [[0.5, 6.0], [1.0, 3.0], [2.0, 1.0]]}
        self.assertEqual(R.DP10_CUT_PACK, pack)
        self.assertEqual(R.RECIPE["packing"], {"version": "gap-pack-v2", "target": 10, **pack})


class Q2ByteIdentityTests(unittest.TestCase):
    """产品的正常包请求必须与研究侧 Q2 逐字节相同（ADR-0019 第 1 点）。钉值取自 2026-11-11 的研究实现
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

    def test_no_names_means_the_plain_q2_system_message(self) -> None:
        scene = scene_from_document(document(5))
        window = build_batches(scene)[0].to_window(scene)
        body = R.request_body(R.messages(window, []), SEED)
        self.assertEqual(body["messages"][0]["content"], R.SYSTEM_TEXT)
        text = json.dumps(body, ensure_ascii=False)
        self.assertEqual(hashlib.sha256(text.encode("utf-8")).hexdigest(), self.PLAIN_BODY_SHA256)

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

    def test_request_body_shape(self) -> None:
        scene = scene_from_document(document(3))
        body = R.request_body(R.messages(build_batches(scene)[0].to_window(scene), []), SEED)
        self.assertEqual(list(body), ["model", "messages", "temperature", "top_p", "top_k", "min_p", "presence_penalty",
                                      "seed", "max_tokens", "chat_template_kwargs", "stream"])
        self.assertNotIn("grammar", body)
        for bad in (0, -1, 1.0, True):
            with self.assertRaises(ValueError):
                R.request_body(body["messages"], bad)


class NamesTests(unittest.TestCase):
    def test_window_filter_uses_every_visible_cue(self) -> None:
        rows = [{"source": "セイバー", "translation": "Saber"}, {"source": "凛", "translation": "凛"}]
        window = {"context": [{"id": "a", "text": "前のセイバー"}, {"id": "b", "text": "はい"}], "translate_ids": ["b"]}
        self.assertEqual(R.names_for_window(rows, window), [rows[0]])  # 只出现在邻文里也注入
        system = R.messages(window, rows)[0]["content"]
        self.assertTrue(system.endswith("\n\n" + R.NAMES_HEADER + "セイバー → Saber"))

    def test_names_sha_depends_only_on_the_rows(self) -> None:
        a = [{"source": "セイバー", "translation": "Saber"}]
        self.assertEqual(R.names_sha256(a), R.names_sha256([dict(a[0])]))
        self.assertNotEqual(R.names_sha256(a), R.names_sha256([{"source": "セイバー", "translation": "塞巴"}]))
        self.assertNotEqual(R.names_sha256(a), R.names_sha256([]))

    def test_table_without_entries_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            R.name_rows({})


class ParseTests(unittest.TestCase):
    def test_structure_is_strict(self) -> None:
        for bad in ('{"translations":{"a":"甲","a":"乙","b":"丙"}}', '{"translations":{"a":"甲","b":"乙"},"x":1}',
                    '{"translations":["甲","乙"]}', '["甲"]', "not json"):
            with self.assertRaises(ValueError, msg=bad):
                R.parse_translation(bad, ["a", "b"])

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
    def test_scene_id_cue_ids_and_times_follow_the_ja_srt(self) -> None:
        doc = document(3)
        scene = scene_from_document(doc)
        self.assertEqual(scene.scene_id, f"srt-{doc.source_sha256[:12]}")
        self.assertEqual(scene.ids, [cue.id for cue in doc.cues])
        self.assertEqual([(c.start, c.end) for c in scene.cues], [(0.0, 1.5), (2.0, 3.5), (4.0, 5.5)])
        self.assertEqual([silence(scene, i) for i in range(2)], [0.5, 0.5])

    def test_positions_cover_every_cue(self) -> None:
        scene = scene_from_document(document(23))
        batches = build_batches(scene)
        positions = cue_positions(batches)
        self.assertEqual(set(positions), set(scene.ids))
        self.assertEqual(batches[0].batch_id, f"{scene.scene_id}-b0001")

    def test_wide_context_counts_cues_and_ignores_pauses(self) -> None:
        # 每 10 条之间隔 20 s（`tests.core.test_translate.document`）：dp10-cut 硬切出 10/10/3，邻文只按条数取。
        from tests.core.test_translate import document as paused
        scene = scene_from_document(paused(23))
        batches = build_batches(scene)
        self.assertEqual([len(b.target_ids) for b in batches], [10, 10, 3])
        self.assertEqual([(len(b.before_ids), len(b.after_ids)) for b in batches], [(0, 5), (10, 3), (20, 0)])

    def test_visible_cap_drops_after_side_first(self) -> None:
        scene = scene_from_gaps([0.1] * 99)
        self.assertEqual(neighbours(scene, 30, 40), (10, 45))  # 20＋10＋5 = 35，恰好不截
        self.assertEqual(neighbours(scene, 0, 10), (0, 15))
        self.assertEqual(neighbours(scene, 95, 100), (75, 100))
        with mock.patch.dict(R.WIDE_CONTEXT, {"max_visible": 32}):
            self.assertEqual(neighbours(scene, 30, 40), (10, 42))  # 先去 3 条后邻
            self.assertEqual(neighbours(scene, 30, 33), (10, 38))
        with mock.patch.dict(R.WIDE_CONTEXT, {"max_visible": 12}):
            self.assertEqual(neighbours(scene, 30, 40), (28, 40))  # 后邻去光后再去前邻

    def test_empty_or_duplicate_scene_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_batches(Scene("S", ()))
        with self.assertRaises(ValueError):
            build_batches(Scene("S", (Cue("a", "x", 0.0, 1.0), Cue("a", "y", 1.0, 2.0))))

    def test_records_keep_their_shape(self) -> None:
        scene = scene_from_gaps([0.2, 30.0, 0.2])
        (first, second) = build_batches(scene)
        self.assertIsInstance(first, Batch)
        self.assertEqual(set(first.record()), {"index", "batch_id", "target_ids", "before_ids", "after_ids", "start", "stop"})
        self.assertEqual((first.record()["stop"], second.record()["start"]), (2, 2))
        self.assertEqual((second.before_ids, first.after_ids), (tuple(scene.ids[:2]), tuple(scene.ids[2:])))


class GapPackTests(unittest.TestCase):
    """gap-pack-v2（ADR-0010）：dp10-cut 的切包规则。"""

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



class PromptShapePinTests(unittest.TestCase):
    """专名行格式与窗口 JSON 形状影响请求体却不在 `RECIPE` hash 里（计划 docs/plans/architecture-cleanup.md §6）：
    用一个固定输出钉住，改动它们必须同时有意升级翻译配方。值取自 2026-11-11 的产品实现。"""

    def test_window_shape_name_rows_and_user_message_are_pinned(self) -> None:
        scene = scene_from_document(parse_srt(format_srt([(0.0, 1.5, "東坂が来た"), (2.0, 3.5, "ほう")])))
        (batch,) = build_batches(scene)
        window = batch.to_window(scene)
        self.assertEqual(window, {
            "id": "srt-818bf926ecef-b0001", "source_language": "ja", "target_language": "zh-Hans",
            "context": [{"id": "818bf926-cue-1", "text": "東坂が来た"}, {"id": "818bf926-cue-2", "text": "ほう"}],
            "translate_ids": ["818bf926-cue-1", "818bf926-cue-2"]})
        rows = [{"source": "東坂", "translation": "东坂"}, {"source": "碇", "translation": "碇"}]
        system, user = R.messages(window, rows)
        self.assertEqual(system, {"role": "system", "content": (
            R.SYSTEM_TEXT + "\n\n本作品专名的固定中文译法（日文写法 → 中文）。原文出现这些写法时使用对应译法：\n東坂 → 东坂")})
        self.assertEqual(user, {"role": "user", "content": (
            '【只读日文上下文】\n[{"id": "818bf926-cue-1", "text": "東坂が来た"}, {"id": "818bf926-cue-2", "text": "ほう"}]\n'
            '【待译 JSON】\n{"translations": {"818bf926-cue-1": "東坂が来た", "818bf926-cue-2": "ほう"}}')})


if __name__ == "__main__":
    unittest.main()
