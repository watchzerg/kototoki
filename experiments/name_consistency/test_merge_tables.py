"""merge_tables 的离线测试：写法取交集、实体 zh 一致性、变体并集、置信度取低、日文规范化。"""

import json
import tempfile
import unittest
from pathlib import Path

from experiments.name_consistency import merge_tables


def entity(entity_ja, zh, forms, zh_variants=(), confidence="high", kind="person", evidence=()):
    return {"entity_ja": entity_ja, "kind": kind, "confidence": confidence, "zh": zh,
            "forms": [{"ja": ja, "zh": target} for ja, target in forms],
            "zh_variants": list(zh_variants), "evidence": list(evidence)}


def table(*entities):
    return {"schema": "name-table-v2", "work": "t", "entries": list(entities)}


class MergeTablesTest(unittest.TestCase):
    def test_form_intersection_and_entity_aggregation(self):
        a = table(entity("衛宮士郎", "卫宫士郎", [("衛宮士郎", "卫宫士郎"), ("シロウ", "士郎"), ("シンジ", "士郎")],
                         ["希罗"], confidence="high", evidence=[1, 5]))
        b = table(entity("衛宮士郎", "卫宫士郎", [("衛宮士郎", "卫宫士郎"), ("シロウ", "士郎"), ("四郎", "士郎")],
                         ["白郎", "希罗"], confidence="medium", evidence=[5, 9]))
        merged = merge_tables.merge_tables(a, b, "a.json", "b.json")
        (entry,) = merged["entries"]
        self.assertEqual([(f["ja"], f["zh"]) for f in entry["forms"]], [("衛宮士郎", "卫宫士郎"), ("シロウ", "士郎")])
        self.assertEqual(entry["zh_variants"], ["希罗", "白郎"])  # 并集，A 在前
        self.assertEqual(entry["confidence"], "medium")  # 取较低者
        self.assertEqual(entry["evidence"], [1, 5, 9])
        dropped = {(d["table"], d["form_ja"], d["reason"]) for d in merged["meta"]["dropped"]}
        self.assertEqual(dropped, {("a", "シンジ", "not_in_other"), ("b", "四郎", "not_in_other")})
        self.assertEqual(merged["meta"]["source"], "intersection")
        self.assertEqual((merged["meta"]["a"], merged["meta"]["b"]), ("a.json", "b.json"))
        self.assertEqual(merged["schema"], "name-table-v2")

    def test_same_ja_with_different_zh_is_dropped(self):
        a = table(entity("造剣", "言峰绮礼", [("造剣", "言峰绮礼")]), entity("ライダー", "Rider", [("ライダー", "Rider")]))
        b = table(entity("ゾウケン", "脏砚", [("造剣", "脏砚")]), entity("ライダー", "Rider", [("ライダー", "Rider")]))
        merged = merge_tables.merge_tables(a, b)
        self.assertEqual([e["entity_ja"] for e in merged["entries"]], ["ライダー"])
        reasons = {(d["table"], d["reason"]) for d in merged["meta"]["dropped"]}
        self.assertIn(("a", "entity_no_common_form"), reasons)
        self.assertIn(("a", "zh_mismatch"), reasons)
        self.assertIn(("b", "zh_mismatch"), reasons)

    def test_entity_zh_must_agree(self):
        """form 一致但实体的 zh 不一致：整个实体丢弃并记录。"""
        a = table(entity("桜", "远坂樱", [("サクラ", "樱")]))
        b = table(entity("桜", "樱", [("サクラ", "樱")]))
        merged = merge_tables.merge_tables(a, b)
        self.assertEqual(merged["entries"], [])
        (item,) = [d for d in merged["meta"]["dropped"] if d["reason"] == "entity_zh_mismatch"]
        self.assertEqual((item["zh"], item["other_zh"]), ("远坂樱", ["樱"]))

    def test_ja_normalization(self):
        """全角半角统一、去空白；长音 ー 保留原样（ライダー 与 ライダ 不同）。"""
        self.assertEqual(merge_tables.norm_ja("エミヤ　シロウ"), merge_tables.norm_ja("エミヤ シロウ"))
        self.assertEqual(merge_tables.norm_ja("ｾｲﾊﾞｰ"), "セイバー")
        self.assertEqual(merge_tables.norm_ja("Ｒｉｄｅｒ"), "Rider")
        self.assertNotEqual(merge_tables.norm_ja("ライダー"), merge_tables.norm_ja("ライダ"))
        a = table(entity("エミヤ シロウ", "卫宫士郎", [("エミヤ シロウ", "卫宫士郎"), ("ライダー", "Rider")]))
        b = table(entity("エミヤシロウ", "卫宫士郎", [("エミヤシロウ", "卫宫士郎"), ("ライダ", "Rider")]))
        merged = merge_tables.merge_tables(a, b)
        (entry,) = merged["entries"]
        self.assertEqual([f["ja"] for f in entry["forms"]], ["エミヤ シロウ"])  # 输出保留 A 的写法

    def test_entity_ja_not_kept_is_replaced_by_a_kept_form(self):
        """entity_ja 对应的 form 被去掉时，改用保留的 form，避免 apply_table 把被去掉的写法补回来。"""
        a = table(entity("シンジ", "士郎", [("シロウ", "士郎")]))
        b = table(entity("シロウ", "士郎", [("シロウ", "士郎")]))
        a["entries"][0]["forms"] = [{"ja": "シロウ", "zh": "士郎"}]  # 没有 entity_ja 自己的 form
        merged = merge_tables.merge_tables(a, b)
        (entry,) = merged["entries"]
        self.assertEqual(entry["entity_ja"], "シロウ")

    def test_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "a.json").write_text(json.dumps(table(entity("桜", "樱", [("桜", "樱")])), ensure_ascii=False), encoding="utf-8")
            (tmp / "b.json").write_text(json.dumps(table(entity("桜", "樱", [("桜", "樱")])), ensure_ascii=False), encoding="utf-8")
            code = merge_tables.main(["--a", str(tmp / "a.json"), "--b", str(tmp / "b.json"), "--out", str(tmp / "o" / "both.json")])
            self.assertEqual(code, 0)
            merged = json.loads((tmp / "o" / "both.json").read_text(encoding="utf-8"))
            self.assertEqual(len(merged["entries"]), 1)
            self.assertEqual(merged["meta"]["stats"]["forms_kept"], 1)
            (tmp / "bad.json").write_text(json.dumps({"schema": "name-table-v1", "entries": []}), encoding="utf-8")
            with self.assertRaises(SystemExit):
                merge_tables.main(["--a", str(tmp / "bad.json"), "--b", str(tmp / "b.json"), "--out", str(tmp / "x.json")])


if __name__ == "__main__":
    unittest.main()
