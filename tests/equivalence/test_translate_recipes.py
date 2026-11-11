"""产品翻译配方 `q2-degrade-v1` 与研究侧 Q2（`experiments/translation_v3/{recipes,batching,data,qwen,strata}.py`＋
`scene_batching_v6/v12.py::strata_recipe_data`、`names11.py::product_tables`）的实时对照：切包参数、邻文窗口、
提示与请求体逐字节一致，注入行规则一致。core 侧只钉字面量与摘要（`tests/core/test_translate_recipes.py`）。"""

from __future__ import annotations

import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest import mock

from experiments.scene_batching_v6 import asr10, names11
from experiments.scene_batching_v6.v12 import strata_recipe_data
from experiments.translation_v3 import batching as RB, data as RD, qwen, recipes as RR, strata as RS
from kototoki.translate import recipes as R
from kototoki.translate.batching import Cue, Scene, build_batches, scene_from_document
from tests.core.test_translate_recipes import SEED, document, random_cues


def research_q2(rows: list[dict[str, str]]):
    """研究侧 Q2 配方：Q1（`qwen-wide`＋`filter: window` 注入表）换成 Strata 默认启动，同 ADR-0017。"""
    q1 = {"name": "q1", "base": "qwen-wide", "comment": "x",
          "qwen_options": {"names": {"filter": "window", "tables": {"w": rows}}}}
    data = strata_recipe_data(q1, "q2", "x", launch="default")
    return RR.compose("q2", "qwen-wide", **{k: v for k, v in data.items() if k not in ("name", "base", "comment")})


class RecipeEquivalenceTests(unittest.TestCase):
    def test_packing_is_the_v3_dp10_cut_pack(self) -> None:
        self.assertEqual(R.DP10_CUT_PACK, RR.BUILTIN["dp10-cut"].gap_pack)
        self.assertEqual(R.RECIPE["packing"], {"version": "gap-pack-v2", "target": 10, **RR.BUILTIN["dp10-cut"].gap_pack})


class Q2ByteIdentityTests(unittest.TestCase):
    """产品的正常包请求必须与研究侧 Q2 逐字节相同（ADR-0019 第 1 点）。"""

    def test_batches_windows_and_request_bodies_match_research_q2(self) -> None:
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
        recipe = research_q2([])
        scene = scene_from_document(document(5))
        window = build_batches(scene)[0].to_window(scene)
        body = R.request_body(R.messages(window, []), SEED)
        self.assertEqual(body["messages"][0]["content"], R.SYSTEM_TEXT)
        self.assertEqual(json.dumps(body, ensure_ascii=False),
                         json.dumps(RS.request_body(qwen.messages(window, recipe, "w"), SEED), ensure_ascii=False))

    def test_name_rows_follow_the_research_product_table_rule(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
