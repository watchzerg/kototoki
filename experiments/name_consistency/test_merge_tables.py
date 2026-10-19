"""merge_tables 的离线测试：写法取交集、实体 zh 一致性、变体并集、置信度取低、日文规范化。"""

import json
import tempfile
import unittest
from pathlib import Path

from experiments.name_consistency import apply_table, merge_tables


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

    def test_zh_agree_unions_forms(self):
        """实体按日文配对（entity_ja 或任一写法规范化后相同），zh 一致：写法并集、变体／evidence 并集、confidence 取低、kind 取 A。"""
        a = table(entity("エミヤ シロウ", "卫宫士郎", [("エミヤ シロウ", "卫宫士郎"), ("シンジ", "士郎")], ["希罗"],
                         confidence="high", kind="person", evidence=[1, 5]))
        b = table(entity("士郎", "卫宫士郎", [("エミヤシロウ", "卫宫士郎"), ("シロウ", "士郎")], ["白郎", "希罗"],
                         confidence="medium", kind="other", evidence=[5, 9]))  # 靠 エミヤシロウ 的规范化配对
        merged = merge_tables.agree_tables(a, b, "a.json", "b.json")
        (entry,) = merged["entries"]
        self.assertEqual([(f["ja"], f["zh"]) for f in entry["forms"]],
                         [("エミヤ シロウ", "卫宫士郎"), ("シンジ", "士郎"), ("シロウ", "士郎"),
                          ("士郎", "卫宫士郎")])  # 并集；同一规范化日文只留 A 的写法；B 的 entity_ja 隐含一条写法
        self.assertEqual((entry["entity_ja"], entry["kind"], entry["confidence"]), ("エミヤ シロウ", "person", "medium"))
        self.assertEqual((entry["zh_variants"], entry["evidence"]), (["希罗", "白郎"], [1, 5, 9]))
        meta = merged["meta"]
        self.assertEqual((meta["source"], meta["a"], meta["b"]), ("zh-agree", "a.json", "b.json"))
        self.assertEqual((meta["dropped_unmatched"], meta["dropped_zh_disagree"], meta["dropped_form_disagree"]), ([], [], []))
        self.assertEqual(merged["schema"], "name-table-v2")

    def test_zh_agree_drops_entity_pair_when_zh_differs(self):
        a = table(entity("アンリ", "安赫尔", [("アンリ", "安赫尔")]), entity("桜", "樱", [("桜", "樱")]))
        b = table(entity("アンリ", "安哥拉", [("アンリ", "安哥拉")]), entity("桜", "樱", [("桜", "樱")]))
        merged = merge_tables.agree_tables(a, b)
        self.assertEqual([e["entity_ja"] for e in merged["entries"]], ["桜"])
        (item,) = merged["meta"]["dropped_zh_disagree"]
        self.assertEqual((item["entity_ja"], item["a_zh"], item["b_zh"]), ("アンリ", "安赫尔", "安哥拉"))

    def test_zh_agree_drops_unmatched_entities(self):
        a = table(entity("桜", "樱", [("桜", "樱")]), entity("凛", "凛", [("凛", "凛")]))
        b = table(entity("桜", "樱", [("桜", "樱")]), entity("ライダー", "Rider", [("ライダー", "Rider")]))
        merged = merge_tables.agree_tables(a, b)
        self.assertEqual([e["entity_ja"] for e in merged["entries"]], ["桜"])
        self.assertEqual([(d["table"], d["entity_ja"], d["zh"]) for d in merged["meta"]["dropped_unmatched"]],
                         [("a", "凛", "凛"), ("b", "ライダー", "Rider")])

    def test_zh_agree_drops_only_the_conflicting_form(self):
        """同一日文两边 zh 不同：只丢该写法，实体和其他写法保留；entity_ja 的写法被丢时改用保留的写法。"""
        a = table(entity("シロウ", "卫宫士郎", [("シロウ", "士郎"), ("エミヤ", "卫宫")]))
        b = table(entity("エミヤ", "卫宫士郎", [("シロウ", "四郎"), ("エミヤ", "卫宫")]))
        merged = merge_tables.agree_tables(a, b)
        (entry,) = merged["entries"]
        self.assertEqual([(f["ja"], f["zh"]) for f in entry["forms"]], [("エミヤ", "卫宫")])
        self.assertEqual(entry["entity_ja"], "エミヤ")
        (item,) = merged["meta"]["dropped_form_disagree"]
        self.assertEqual((item["form_ja"], item["a_zh"], item["b_zh"]), ("シロウ", "士郎", "四郎"))

    def test_zh_agree_picks_best_overlap_and_cli(self):
        a = table(entity("シロウ", "士郎", [("シロウ", "士郎"), ("エミヤ", "士郎")]))
        b = table(entity("シロウ", "四郎", [("シロウ", "四郎")]), entity("エミヤ", "士郎", [("エミヤ", "士郎"), ("シロウ", "士郎")]))
        merged = merge_tables.agree_tables(a, b)  # 与第二个 B 实体重合 2 个，与第一个只有 1 个
        self.assertEqual([e["zh"] for e in merged["entries"]], ["士郎"])
        self.assertEqual(merged["meta"]["dropped_unmatched"], [{"table": "b", "entity_ja": "シロウ", "zh": "四郎"}])
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for name, tbl in (("a.json", a), ("b.json", b)):
                (tmp / name).write_text(json.dumps(tbl, ensure_ascii=False), encoding="utf-8")
            code = merge_tables.main(["--a", str(tmp / "a.json"), "--b", str(tmp / "b.json"), "--out", str(tmp / "o.json"),
                                      "--mode", "zh-agree"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads((tmp / "o.json").read_text(encoding="utf-8"))["meta"]["source"], "zh-agree")

    def test_zh_agree_forms_fallback(self):
        """--forms-fallback：实体 zh 不同（远坂樱／间桐樱）但有相同写法时，只留相同写法、实体 zh 取 A、变体只取 A；一条都对不上仍丢弃。"""
        a = table(entity("遠坂桜", "远坂樱", [("桜", "樱"), ("サクラ", "樱"), ("遠坂桜", "远坂樱")], ["远坂櫻"], confidence="high"),
                  entity("アンリ", "安赫尔", [("アンリ", "安赫尔")]))
        b = table(entity("間桐桜", "间桐樱", [("桜", "樱"), ("サクラ", "樱"), ("間桐桜", "间桐樱")], ["间桐櫻"], confidence="medium"),
                  entity("アンリ", "安哥拉", [("アンリ", "安哥拉")]))
        plain = merge_tables.agree_tables(a, b)
        self.assertEqual(plain["entries"], [])
        self.assertEqual(len(plain["meta"]["dropped_zh_disagree"]), 2)
        merged = merge_tables.agree_tables(a, b, forms_fallback=True)
        (entry,) = merged["entries"]
        # 远坂樱 不等于任何保留写法的 zh（樱）：实体只是两表一致认可的内容，entity_ja／zh 取第一个保留写法的，变体清空；
        # 否则 apply_table 的隐含写法会拼出 桜→远坂樱
        self.assertEqual((entry["entity_ja"], entry["zh"], entry["confidence"]), ("桜", "樱", "medium"))
        self.assertEqual([(f["ja"], f["zh"]) for f in entry["forms"]], [("桜", "樱"), ("サクラ", "樱")])
        self.assertEqual(entry["zh_variants"], [])
        implicit = {(f["ja"], f["zh"]) for f in apply_table.entity_forms(entry)}
        self.assertEqual(implicit, {("桜", "樱"), ("サクラ", "樱")})
        (item,) = merged["meta"]["kept_forms_only"]
        self.assertEqual((item["entity_ja"], item["a_zh"], item["b_zh"]), ("遠坂桜", "远坂樱", "间桐樱"))
        self.assertEqual(item["forms_kept"], [{"ja": "桜", "zh": "樱"}, {"ja": "サクラ", "zh": "樱"}])
        # 实体 zh 本来就等于某个保留写法的 zh（远坂 / 远坂家 之类的反面）：保持 A 的实体 zh 与变体
        a2 = table(entity("桜", "樱", [("桜", "樱"), ("サクラ", "樱")], ["櫻"]))
        b2 = table(entity("桜", "间桐樱", [("桜", "樱"), ("間桐桜", "间桐樱")], ["间桐櫻"]))
        (kept,) = merge_tables.agree_tables(a2, b2, forms_fallback=True)["entries"]
        self.assertEqual((kept["entity_ja"], kept["zh"], kept["zh_variants"]), ("桜", "樱", ["櫻"]))
        self.assertEqual([f["ja"] for f in kept["forms"]], ["桜"])
        self.assertEqual([d["entity_ja"] for d in merged["meta"]["dropped_zh_disagree"]], ["アンリ"])
        self.assertEqual(merged["meta"]["stats"]["kept_forms_only"], 1)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for name, tbl in (("a.json", a), ("b.json", b)):
                (tmp / name).write_text(json.dumps(tbl, ensure_ascii=False), encoding="utf-8")
            args = ["--a", str(tmp / "a.json"), "--b", str(tmp / "b.json"), "--out", str(tmp / "o.json")]
            self.assertEqual(merge_tables.main([*args, "--mode", "zh-agree", "--forms-fallback"]), 0)
            self.assertEqual(len(json.loads((tmp / "o.json").read_text(encoding="utf-8"))["entries"]), 1)
            with self.assertRaises(SystemExit):
                merge_tables.main([*args, "--forms-fallback"])  # 只对 zh-agree

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
