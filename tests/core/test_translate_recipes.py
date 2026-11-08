"""产品配方 `q2-degrade-v1` 的身份钉子：配方 hash、与研究侧 Q2（`experiments/translation_v3/{qwen,strata}.py`＋
`scene_batching_v6/v12.py::strata_recipe_data`）逐字节一致的切包、邻文、提示与请求体，注入行与研究
`names11.py::product_tables` 的规则一致，回复校验。gap-pack-v2 切包用例移植自 `experiments/scene_batching_v6/test_v7.py`。
产品代码不导入 experiments，测试可以导入作参照。"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest import mock

from kototoki.artifacts import object_hash
from kototoki.srt import format_srt, parse_srt
from kototoki.translate import RECIPE_HASH
from kototoki.translate import recipes as R
from kototoki.translate.batching import (Batch, Cue, Scene, build_batches, cue_positions, gap_pack_cuts, neighbours,
                                         scene_from_document, silence)

Q2_DEGRADE_V1_HASH = "332649cf98662e42cccc31485792104c3ce6303e6cd634ef42ef85839ee9310d"
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


def research_q2(rows: list[dict[str, str]]):
    """研究侧 Q2 配方：Q1（`qwen-wide`＋`filter: window` 注入表）换成 Strata 默认启动，同 ADR-0017。"""
    from experiments.scene_batching_v6.v12 import strata_recipe_data
    from experiments.translation_v3 import recipes as RR

    q1 = {"name": "q1", "base": "qwen-wide", "comment": "x",
          "qwen_options": {"names": {"filter": "window", "tables": {"w": rows}}}}
    data = strata_recipe_data(q1, "q2", "x", launch="default")
    return RR.compose("q2", "qwen-wide", **{k: v for k, v in data.items() if k not in ("name", "base", "comment")})


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
        # ADR-0019：配方任何字段变化都要换 hash、并改这里与 ADR。
        self.assertEqual(R.RECIPE_HASH, Q2_DEGRADE_V1_HASH)
        self.assertEqual(RECIPE_HASH, object_hash(R.RECIPE))
        self.assertEqual(R.RECIPE_NAME, "q2-degrade-v1")

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
        self.assertEqual(recipe["overflow"], "degrade-10-5-1-keep-source")

    def test_packing_is_the_v3_dp10_cut_pack(self) -> None:
        from experiments.translation_v3 import recipes as V
        self.assertEqual(R.DP10_CUT_PACK, V.BUILTIN["dp10-cut"].gap_pack)
        self.assertEqual(R.RECIPE["packing"], {"version": "gap-pack-v2", "target": 10, **V.BUILTIN["dp10-cut"].gap_pack})


class Q2ByteIdentityTests(unittest.TestCase):
    """产品的正常包请求必须与研究侧 Q2 逐字节相同（ADR-0019 第 1 点）。"""

    def test_batches_windows_and_request_bodies_match_research_q2(self) -> None:
        from experiments.translation_v3 import batching as RB, data as RD, qwen, strata as RS

        rows = [{"source": "セイバー", "translation": "Saber"}, {"source": "士郎", "translation": "士郎"},
                {"source": "凛", "translation": "凛"}]
        recipe = research_q2(rows)
        rng = random.Random(7)
        compared = 0
        for _ in range(30):
            cues = random_cues(rng, rng.randint(1, 120))
            rscene = RD.Scene("srt-x", tuple(RD.Cue(*c) for c in cues), "w")
            pscene = Scene("srt-x", tuple(Cue(*c) for c in cues))
            theirs, ours = RB.build_batches(rscene, recipe), build_batches(pscene)
            self.assertEqual([(b.target_ids, b.before_ids, b.after_ids) for b in ours],
                             [(b.target_ids, b.before_ids, b.after_ids) for b in theirs])
            for r, p in zip(theirs, ours):
                window = r.to_window(rscene)
                self.assertEqual(p.to_window(pscene), window)
                for seed in (SEED, SEED + 1):
                    expected = RS.request_body(qwen.messages(window, recipe, "w"), seed)
                    actual = R.request_body(R.messages(window, rows), seed)
                    self.assertEqual(json.dumps(actual, ensure_ascii=False), json.dumps(expected, ensure_ascii=False))
                    compared += 1
        self.assertGreater(compared, 200)

    def test_no_names_means_the_plain_q2_system_message(self) -> None:
        from experiments.translation_v3 import qwen, strata as RS
        recipe = research_q2([])
        scene = scene_from_document(document(5))
        window = build_batches(scene)[0].to_window(scene)
        body = R.request_body(R.messages(window, []), SEED)
        self.assertEqual(body["messages"][0]["content"], R.SYSTEM_TEXT)
        self.assertEqual(json.dumps(body, ensure_ascii=False),
                         json.dumps(RS.request_body(qwen.messages(window, recipe, "w"), SEED), ensure_ascii=False))

    def test_name_rows_follow_the_research_product_table_rule(self) -> None:
        from experiments.scene_batching_v6 import asr10, names11

        def entity(confidence: str, *forms: tuple[str, str]) -> dict:
            return {"entity_ja": forms[0][0], "kind": "person", "confidence": confidence, "zh": forms[0][1],
                    "forms": [{"ja": ja, "zh": zh} for ja, zh in forms], "zh_variants": [], "evidence": []}

        table = {"entries": [entity("high", ("セイバー", "Saber"), ("セイバ", "Saber")), entity("medium", ("士郎", "士郎")),
                             entity("high", ("セイバー", "塞巴"), ("凛", "凛")), entity("low", ("桜", "樱")),
                             entity("high", (" ", "空"), ("遠坂", " "))]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "name-table.json"
            path.write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
            with mock.patch.object(asr10, "FILMS", {"F": {"table": path}}):
                expected = names11.product_tables("high")["F"]
        self.assertEqual(R.name_rows(table), expected)
        self.assertEqual([r["source"] for r in expected], ["セイバー", "セイバ", "凛"])

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
    def test_parse_translation_is_strict(self) -> None:
        self.assertEqual(R.parse_translation('{"translations":{"a":"甲","b":"乙"}}', ["a", "b"]), {"a": "甲", "b": "乙"})
        self.assertEqual(R.parse_translation('﻿ {"translations":{"a":"甲\\n乙"}} ', ["a"]), {"a": "甲\n乙"})
        for bad in ('{"translations":{"a":"甲"}}', '{"translations":{"a":"甲","a":"乙","b":"丙"}}',
                    '{"translations":{"a":" ","b":"乙"}}', '{"translations":{"b":"乙","a":"甲"}}',
                    '{"translations":{"a":"甲\\n\\n续","b":"乙"}}', '{"translations":{"a":"甲","b":"乙"},"x":1}',
                    "not json"):
            with self.assertRaises(ValueError, msg=bad):
                R.parse_translation(bad, ["a", "b"])


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


if __name__ == "__main__":
    unittest.main()
