"""apply_table 的离线测试：合成 ja/zh SRT 与专名表，覆盖变体层、已规范、统计层、未命中、重叠与非锚定 cue。"""

import json
import tempfile
import unittest
from pathlib import Path

from experiments.name_consistency import apply_table

# (日文, 中文)；第 12 条故意不含任何锚点，但中文里有 "真次"，必须原样保留
CUES = [
    ("真次はどこだ", "真次在哪里"),                  # 1 变体层 真次->真嗣
    ("桜が来た", "樱来了"),                          # 2 已规范
    ("ルヴィアが笑った", "鲁维娅在笑"),              # 3 统计层
    ("ルヴィアが来た", "鲁维娅来了"),                # 4 统计层
    ("ルヴィアは行く", "鲁维娅要去了"),              # 5 统计层
    ("ルヴィアだけ残る", "是鲁维娅啊"),          # 6 统计层
    ("ルヴィアの声", "鲁薇娅的声音"),                # 7 统计层，近形变体
    ("遠坂がいる", "她在这里"),                      # 8 代词，未命中
    ("遠坂の家", "远阪的家"),                        # 9 变体层 远阪->远坂
    ("間桐慎二が来た", "闻桐慎司来了"),              # 10 两个条目重叠
    ("間桐の家だ", "闻桐的家到了"),                    # 11 只有间桐命中
    ("朝が来た", "真次的早晨"),                      # 12 非锚定
    ("真次が来た", "真次来了"),                      # 13–15 让 真次 的特异性达标：a=4, b=1（cue 12）
    ("真次だ", "真次啊"),
    ("真次です", "真次吗"),
]

def entity(entity_ja, zh, forms, zh_variants=(), confidence="high", kind="person"):
    """name-table-v2 的一个条目；forms 是 (日文, 中文目标) 列表。"""
    return {"entity_ja": entity_ja, "kind": kind, "confidence": confidence, "zh": zh,
            "forms": [{"ja": ja, "zh": target} for ja, target in forms],
            "zh_variants": list(zh_variants), "evidence": []}


def table(*entities):
    return {"schema": "name-table-v2", "work": "test", "entries": list(entities)}


TABLE = table(
    entity("真嗣", "真嗣", [("真嗣", "真嗣"), ("真次", "真嗣")], ["真次", "镇司"]),
    entity("桜", "樱", [("桜", "樱")], ["桜"]),
    entity("ルヴィア", "卢薇娅", [("ルヴィア", "卢薇娅")], ["卢维亚"]),
    entity("遠坂", "远坂", [("遠坂", "远坂"), ("東坂", "远坂")], ["东坂", "远阪"]),
    entity("間桐", "间桐", [("間桐", "间桐")], ["闻桐"]),
    entity("間桐慎二", "间桐慎二", [("間桐慎二", "间桐慎二")], ["闻桐慎司"]),
)

# 期望的译文；未列出的条目不变
EXPECTED = {1: "真嗣在哪里", 3: "卢薇娅在笑", 4: "卢薇娅来了", 5: "卢薇娅要去了", 6: "是卢薇娅啊",
            7: "卢薇娅的声音", 9: "远坂的家", 11: "间桐的家到了",
            13: "真嗣来了", 14: "真嗣啊", 15: "真嗣吗"}


def srt(texts: list[str], eol: str = "\n") -> str:
    blocks = [f"{n}{eol}00:00:{n:02d},000 --> 00:00:{n:02d},900{eol}{text}{eol}" for n, text in enumerate(texts, 1)]
    return eol.join(blocks)


class ApplyTableTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        (self.dir / "table.json").write_text(json.dumps(TABLE, ensure_ascii=False), encoding="utf-8")
        (self.dir / "ja.srt").write_text(srt([c[0] for c in CUES]), encoding="utf-8")
        self.zh_original = srt([c[1] for c in CUES])
        (self.dir / "zh.srt").write_text(self.zh_original, encoding="utf-8")

    def run_apply(self, zh_name: str = "zh.srt", extra: list[str] | None = None) -> Path:
        """extra 默认为空，即脚本默认（不核对目标名）。"""
        out = self.dir / "out"
        code = apply_table.main(["--table", str(self.dir / "table.json"), "--ja", str(self.dir / "ja.srt"),
                                 "--zh", str(self.dir / zh_name), "--out-dir", str(out),
                                 *(extra or [])])
        self.assertEqual(code, 0)
        return out

    @staticmethod
    def read_jsonl(path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_replacement_and_structure(self):
        out = self.run_apply()
        new = (out / "zh.replaced.srt").read_text(encoding="utf-8")
        old_lines, new_lines = self.zh_original.split("\n"), new.split("\n")
        self.assertEqual(len(old_lines), len(new_lines))
        text_lines = {(n - 1) * 4 + 2: n for n in range(1, len(CUES) + 1)}  # 每块 4 行：序号、时间、文本、空行
        for line, number in text_lines.items():
            expected = EXPECTED.get(number, CUES[number - 1][1])
            self.assertEqual(new_lines[line], expected, f"cue {number}")
        changed_lines = {i for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b}
        self.assertEqual(changed_lines, {line for line, number in text_lines.items() if number in EXPECTED})
        self.assertIn("真次的早晨", new)  # 非锚定 cue 不动

    def test_changes_unresolved_and_summary(self):
        out = self.run_apply()
        changes = self.read_jsonl(out / "changes.jsonl")
        self.assertEqual(sorted(c["index"] for c in changes), sorted(EXPECTED))
        by_index = {c["index"]: c for c in changes}
        self.assertEqual(by_index[1]["layer"], "variant")
        self.assertEqual(by_index[1]["span"], "真次")
        self.assertEqual((by_index[1]["zh_before"], by_index[1]["zh_after"]), ("真次在哪里", "真嗣在哪里"))
        self.assertEqual(by_index[3]["layer"], "stat")
        self.assertEqual(by_index[7]["span"], "鲁薇娅")
        self.assertEqual(by_index[7]["layer"], "stat")
        self.assertEqual(by_index[9]["layer"], "variant")
        self.assertEqual(by_index[1]["ja"], "真次はどこだ")

        unresolved = {(u["index"], u["entry"]): u["reason"] for u in self.read_jsonl(out / "unresolved.jsonl")}
        self.assertEqual(unresolved, {(8, "遠坂"): "not_found", (10, "間桐"): "overlap", (10, "間桐慎二"): "overlap"})

        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        rows = {row["entity_ja"]: row for row in summary["entries"]}
        self.assertEqual((rows["真嗣"]["anchored"], rows["真嗣"]["replaced_variant"]), (4, 4))
        self.assertEqual((rows["桜"]["already_canonical"], rows["桜"]["replaced_variant"]), (1, 0))
        self.assertEqual((rows["ルヴィア"]["anchored"], rows["ルヴィア"]["replaced_stat"]), (5, 5))
        stat_form = rows["ルヴィア"]["forms"][0]
        self.assertIsNotNone(stat_form["stat_rendering"])  # 单字与多字候选同族时取锚定 cue 最多者，并列不保证是哪个
        self.assertIn({"text": "鲁维娅", "anchored": 4, "other": 0}, stat_form["stat_candidates_kept"])
        self.assertEqual(stat_form["stat_candidates_dropped"], [])
        self.assertEqual(rows["ルヴィア"]["unresolved_compound"], 0)
        self.assertEqual((rows["遠坂"]["replaced_variant"], rows["遠坂"]["unresolved_not_found"]), (1, 1))
        self.assertEqual((rows["間桐"]["replaced_variant"], rows["間桐"]["unresolved_overlap"]), (1, 1))
        self.assertEqual(rows["間桐慎二"]["unresolved_overlap"], 1)
        totals = summary["totals"]
        self.assertEqual((totals["replaced_variant"], totals["replaced_stat"], totals["already_canonical"]), (6, 5, 1))
        self.assertEqual((totals["unresolved_not_found"], totals["unresolved_overlap"]), (1, 2))
        self.assertEqual(totals["cues_changed"], len(EXPECTED))

    def test_forms_targets_and_precedence(self):
        """每个 form 以自己的 zh 为目标：名字不补全成全名，全名不缩短，姓的误识别归到姓；最长 form 优先锚定。"""
        (self.dir / "table.json").write_text(json.dumps(table(
            entity("衛宮士郎", "卫宫士郎", [("衛宮士郎", "卫宫士郎"), ("シロウ", "士郎"), ("四郎", "士郎"), ("エミヤ", "卫宫")],
                   ["希罗", "白郎"]),
            entity("遠坂凛", "远坂凛", [("遠坂凛", "远坂凛"), ("遠坂", "远坂"), ("東坂", "远坂")], ["东坂"])),
            ensure_ascii=False), encoding="utf-8")
        pairs = [("衛宮士郎が来た", "卫宫士郎来了"),      # 1 全名已规范
                 ("シロウが来た", "士郎来了"),            # 2 名字已规范
                 ("シロウが笑う", "卫宫士郎笑了"),        # 3 名字 cue 里是全名：包含目标，不缩短
                 ("シロウは行く", "希罗要去了"),          # 4 变体 -> 士郎（不是全名）
                 ("シロウです", "白郎啊"),                # 5 变体 -> 士郎
                 ("エミヤが来た", "卫宫来了"),            # 6 姓已规范
                 ("東坂が来た", "东坂来了"),              # 7 姓的误识别 -> 远坂（不是远坂凛）
                 ("遠坂凛です", "远坂来了"),              # 8 全名 cue 里只有姓：省略形，不补全
                 ("遠坂凛だ", "远坂凛だ"),                # 9 全名已规范
                 ("遠坂が来た", "远坂来了")]              # 10 姓已规范
        (self.dir / "ja.srt").write_text(srt([p[0] for p in pairs]), encoding="utf-8")
        (self.dir / "zh.srt").write_text(srt([p[1] for p in pairs]), encoding="utf-8")
        out = self.run_apply()
        new = apply_table.parse_srt((out / "zh.replaced.srt").read_text(encoding="utf-8"))
        self.assertEqual([c.text for c in new],
                         ["卫宫士郎来了", "士郎来了", "卫宫士郎笑了", "士郎要去了", "士郎啊", "卫宫来了",
                          "远坂来了", "远坂来了", "远坂凛だ", "远坂来了"])
        changes = {c["index"]: c for c in self.read_jsonl(out / "changes.jsonl")}
        self.assertEqual(sorted(changes), [4, 5, 7])
        self.assertEqual((changes[4]["form_ja"], changes[4]["target"], changes[4]["span"]), ("シロウ", "士郎", "希罗"))
        self.assertEqual((changes[7]["form_ja"], changes[7]["target"], changes[7]["span"]), ("東坂", "远坂", "东坂"))
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        rows = {row["entity_ja"]: row for row in summary["entries"]}
        forms = {entity: {f["form_ja"]: f for f in row["forms"]} for entity, row in rows.items()}
        shirou = forms["衛宮士郎"]["シロウ"]
        self.assertEqual((shirou["anchored"], shirou["already_canonical"], shirou["replaced_variant"]), (4, 2, 2))
        self.assertEqual(rows["衛宮士郎"]["already_canonical"], 4)
        # 最长 form 优先：遠坂凛 的两个 cue 不会再被 遠坂 处理
        rin = forms["遠坂凛"]
        self.assertEqual((rin["遠坂凛"]["anchored"], rin["遠坂"]["anchored"], rin["東坂"]["anchored"]), (2, 1, 1))
        self.assertEqual((rin["遠坂凛"]["partial_canonical"], rin["遠坂凛"]["already_canonical"]), (1, 1))
        self.assertEqual(rin["東坂"]["replaced_variant"], 1)
        self.assertEqual(summary["totals"]["partial_canonical"], 1)
        self.assertEqual(summary["entries_skipped_confidence"], [])

    def test_disjoint_form_zh_is_not_a_candidate(self):
        """其他 form 的 zh 与目标互不包含时不是候选：士郎 的 cue 里的 卫宫 不会被改成 士郎。"""
        (self.dir / "table.json").write_text(json.dumps(table(
            entity("衛宮士郎", "卫宫士郎", [("シロウ", "士郎"), ("エミヤ", "卫宫")])), ensure_ascii=False), encoding="utf-8")
        (self.dir / "ja.srt").write_text(srt(["シロウはどこ"]), encoding="utf-8")
        (self.dir / "zh.srt").write_text(srt(["卫宫，士郎在哪"]), encoding="utf-8")
        out = self.run_apply()
        texts = [c.text for c in apply_table.parse_srt((out / "zh.replaced.srt").read_text(encoding="utf-8"))]
        self.assertEqual(texts, ["卫宫，士郎在哪"])
        self.assertEqual(self.read_jsonl(out / "changes.jsonl"), [])

    def test_stat_layer_is_per_form(self):
        """统计层只看本 form 锚定的 cue，各 form 的主译法互不干扰。"""
        (self.dir / "table.json").write_text(json.dumps(table(
            entity("ルヴィアゼリッタ", "卢薇娅泽莉塔", [("ルヴィア", "卢薇娅"), ("ゼリッタ", "泽莉塔")])),
            ensure_ascii=False), encoding="utf-8")
        pairs = [("ルヴィアが来た", "鲁维娅来了"), ("ルヴィアが笑う", "鲁维娅在笑"), ("ルヴィアは行く", "鲁维娅去了"),
                 ("ゼリッタが来た", "泽丽塔来了"), ("ゼリッタが笑う", "泽丽塔在笑"), ("ゼリッタは行く", "泽丽塔去了"),
                 ("朝", "早上好"), ("夜", "晚上好")]
        (self.dir / "ja.srt").write_text(srt([p[0] for p in pairs]), encoding="utf-8")
        (self.dir / "zh.srt").write_text(srt([p[1] for p in pairs]), encoding="utf-8")
        out = self.run_apply()
        new = apply_table.parse_srt((out / "zh.replaced.srt").read_text(encoding="utf-8"))
        self.assertEqual([c.text for c in new],
                         ["卢薇娅来了", "卢薇娅在笑", "卢薇娅去了", "泽莉塔来了", "泽莉塔在笑", "泽莉塔去了", "早上好", "晚上好"])
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        forms = {f["form_ja"]: f for f in summary["entries"][0]["forms"]}
        self.assertEqual((forms["ルヴィア"]["stat_rendering"], forms["ゼリッタ"]["stat_rendering"]), ("鲁维娅", "泽丽塔"))
        self.assertEqual((forms["ルヴィア"]["replaced_stat"], forms["ゼリッタ"]["replaced_stat"]), (3, 3))

    def test_min_confidence_skips_entities(self):
        (self.dir / "table.json").write_text(json.dumps(table(
            entity("シンジ", "慎二", [("シンジ", "慎二")], ["新治"], confidence="high"),
            entity("シロウ", "士郎", [("シロウ", "士郎")], ["希罗"], confidence="low")), ensure_ascii=False), encoding="utf-8")
        (self.dir / "ja.srt").write_text(srt(["シンジが来た", "シロウが来た"]), encoding="utf-8")
        (self.dir / "zh.srt").write_text(srt(["新治来了", "希罗来了"]), encoding="utf-8")
        out = self.run_apply()  # 默认 low：全部应用
        texts = [c.text for c in apply_table.parse_srt((out / "zh.replaced.srt").read_text(encoding="utf-8"))]
        self.assertEqual(texts, ["慎二来了", "士郎来了"])
        shutil_out = self.dir / "out_medium"
        code = apply_table.main(["--table", str(self.dir / "table.json"), "--ja", str(self.dir / "ja.srt"),
                                 "--zh", str(self.dir / "zh.srt"), "--out-dir", str(shutil_out),
                                 "--min-confidence", "medium"])
        self.assertEqual(code, 0)
        texts = [c.text for c in apply_table.parse_srt((shutil_out / "zh.replaced.srt").read_text(encoding="utf-8"))]
        self.assertEqual(texts, ["慎二来了", "希罗来了"])
        summary = json.loads((shutil_out / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["entries_skipped_confidence"], [{"entity_ja": "シロウ", "confidence": "low"}])
        self.assertEqual([row["entity_ja"] for row in summary["entries"]], ["シンジ"])

    def test_compound_adjacency_is_skipped(self):
        """落点紧邻 ·／・ 或拉丁字母时不替换并记 compound；两侧、两层都适用，普通 cue 照常替换。"""
        (self.dir / "table.json").write_text(json.dumps(table(
            entity("アンリマユ", "安哥拉", [("アンリマユ", "安哥拉")], ["玛尤"]),
            entity("シロウ", "卫宫士郎", [("シロウ", "卫宫士郎")])), ensure_ascii=False), encoding="utf-8")
        ja = ["アンリマユ1", "アンリマユ2", "アンリマユ3", "アンリマユ4",
              "シロウ1", "シロウ2", "シロウ3", "シロウ4", "朝が来た"]
        zh = ["安里·玛尤", "玛尤·英弥", "玛尤来了", "Saber玛尤",
              "希罗来了", "希罗去吧", "艾米亚·希罗", "希罗·英弥", "早上好"]
        (self.dir / "ja.srt").write_text(srt(ja), encoding="utf-8")
        (self.dir / "zh.srt").write_text(srt(zh), encoding="utf-8")
        out = self.run_apply()
        new = apply_table.parse_srt((out / "zh.replaced.srt").read_text(encoding="utf-8"))
        self.assertEqual([c.text for c in new],
                         ["安里·玛尤", "玛尤·英弥", "安哥拉来了", "Saber玛尤",
                          "卫宫士郎来了", "卫宫士郎去吧", "艾米亚·希罗", "希罗·英弥", "早上好"])
        unresolved = {(u["index"], u["reason"]) for u in self.read_jsonl(out / "unresolved.jsonl")}
        self.assertEqual(unresolved, {(1, "compound"), (2, "compound"), (4, "compound"),
                                      (7, "compound"), (8, "compound")})
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        rows = {row["entity_ja"]: row for row in summary["entries"]}
        self.assertEqual((rows["アンリマユ"]["unresolved_compound"], rows["アンリマユ"]["replaced_variant"]), (3, 1))
        self.assertEqual((rows["シロウ"]["unresolved_compound"], rows["シロウ"]["replaced_stat"]), (2, 2))
        self.assertEqual(summary["totals"]["unresolved_compound"], 5)

    def test_stat_candidate_filter(self):
        """短语 n-gram 因特异性不足被丢弃；音译写法（锚定 3 次、别处 0 次）保留；形状不合格的丢弃。"""
        zh_texts = ["希罗来了", "希罗想要保护", "希罗去吧",   # 0–2 锚定
                    "我想要保护你", "想要保护的人", "还想要保护", "樱战斗的武器", "路上"]
        stat = apply_table.StatLayer("卫宫士郎", zh_texts, [0, 1, 2])
        self.assertTrue(stat.accept("希罗"))
        self.assertFalse(stat.accept("想要保护"))
        self.assertFalse(stat.accept("樱的"))            # 尾字是虚词
        self.assertFalse(stat.accept("希罗卫宫士郎"))    # zh 的超串
        self.assertFalse(stat.accept("路上"))            # 锚定 cue 内 0 次
        self.assertFalse(stat.accept("希罗, 来"))        # 含非 CJK 字符
        reasons = {d["text"]: d["reason"] for d in stat.dropped}
        self.assertEqual(reasons["想要保护"], "specificity")
        self.assertEqual(reasons["樱的"], "edge_stop")
        self.assertEqual(reasons["希罗卫宫士郎"], "superstring_of_zh")
        self.assertEqual(reasons["希罗, 来"], "shape")
        self.assertIn({"text": "希罗", "anchored": 3, "other": 0}, stat.kept)
        # 相对支持度：锚定 100 条时至少要 4 次，只出现 2 次的语境短语不够
        many = apply_table.StatLayer("间桐樱", ["樱花开了"] * 2 + ["路过"] * 98, list(range(100)))
        self.assertEqual(many.min_anchored, 4)
        self.assertFalse(many.accept("樱花"))
        self.assertEqual(many.dropped[-1]["reason"], "specificity")
        dropped = {d["text"]: (d["anchored"], d["other"]) for d in stat.dropped}
        self.assertEqual(dropped["想要保护"], (1, 3))

    def test_stat_span_extension(self):
        """统计层落点向外扩展到有支持的最长超串；超串没有支持就保持原落点；扩展后再查 compound。"""
        (self.dir / "table.json").write_text(json.dumps(table(
            entity("アインツベルン", "爱因兹贝伦", [("アインツベルン", "爱因兹贝伦")]),
            entity("シンジ", "慎二", [("シンジ", "慎二")])), ensure_ascii=False), encoding="utf-8")
        ja = ["アインツベルン1", "アインツベルン2", "アインツベルン3", "アインツベルン4",
              "シンジ1", "シンジ2", "シンジ3", "シンジ4", "朝が来た", "夜が来た"]
        zh = ["艾因茨贝伦来了", "艾因茨贝伦在笑", "艾因茨贝伦去了", "埃因茨贝伦到了",
              "阿新治来了", "阿新治在笑", "新治去了", "安·阿新治到了", "早上好", "晚上好"]
        (self.dir / "ja.srt").write_text(srt(ja), encoding="utf-8")
        (self.dir / "zh.srt").write_text(srt(zh), encoding="utf-8")
        out = self.run_apply()
        new = apply_table.parse_srt((out / "zh.replaced.srt").read_text(encoding="utf-8"))
        self.assertEqual([c.text for c in new],
                         ["爱因兹贝伦来了", "爱因兹贝伦在笑", "爱因兹贝伦去了",
                          "埃因茨贝伦到了",  # 爱因茨贝伦 只在 1 个 cue：超串没有支持，落点紧邻 埃 不在清单里 -> boundary，不动
                          "慎二来了", "慎二在笑", "慎二去了",
                          "安·阿新治到了",  # 扩展成 阿新治 后紧邻 ·，按 compound 跳过
                          "早上好", "晚上好"])
        changes = {c["index"]: c for c in self.read_jsonl(out / "changes.jsonl")}
        self.assertEqual(changes[1]["span"], "艾因茨贝伦")
        self.assertIn(changes[1]["extended_from"], ("艾", "因茨贝伦"))  # 从哪个片段起扩展取决于排序，结果都是整名
        self.assertNotIn(4, changes)
        self.assertEqual(changes[5]["span"], "阿新治")
        self.assertIn(changes[5]["extended_from"], ("阿", "新治"))
        self.assertEqual(changes[7]["span"], "新治")
        self.assertNotIn("extended_from", changes[7])
        unresolved = {(u["index"], u["reason"]) for u in self.read_jsonl(out / "unresolved.jsonl")}
        self.assertEqual(unresolved, {(4, "boundary"), (8, "compound")})
        # 超串不能以间隔点开头或结尾（"安里·" 之类）
        stat = apply_table.StatLayer("安徒生", ["安里·玛伊", "安里·真由", "安里玛尤"], [0, 1, 2])
        self.assertEqual(stat.extend("安里·玛伊", 0, 2), (0, 2))

    def test_dotted_run_must_be_covered_whole(self):
        """含间隔点的扩展必须覆盖整段连续串：不把 艾米亚·希罗 截成 米亚·希罗。"""
        texts = ["埃米亚·希罗", "埃米亚·希罗", "艾米亚·希罗", "路过"]
        stat = apply_table.StatLayer("卫宫士郎", texts, [0, 1, 2])
        self.assertEqual(stat.extend(texts[0], 4, 6), (0, 6))  # 整段 埃米亚·希罗：支持 2 次，通过
        self.assertEqual(stat.extend(texts[2], 4, 6), (4, 6))  # 只有被截的 米亚·希罗 有支持，拒绝
        # 整段连续串比 MAX_EXTEND 还长，含点的超串到不了整段边界，同样拒绝
        texts = ["我的使命就是保护埃米亚·希罗", "我的使命就是保护埃米亚·希罗", "路过"]
        stat = apply_table.StatLayer("卫宫士郎", texts, [0, 1])
        self.assertEqual(stat.extend(texts[0], 12, 14), (12, 14))

    def test_zh_variants_are_filtered(self):
        """模型列的 zh_variants 也要过特异性：别名／无关词不替换；单次出现的真变体仍可替换；落选的记入 summary。"""
        (self.dir / "table.json").write_text(json.dumps(table(
            entity("ライダー", "Rider", [("ライダー", "Rider")], ["骑士", "美杜莎", "未曾现身", "Rider骑"], kind="role")),
            ensure_ascii=False), encoding="utf-8")
        ja = ["ライダー1", "ライダー2", "朝", "昼", "夜"]
        zh = ["骑士来了", "美杜莎在笑", "美杜莎笑了", "美杜莎去了", "晚安"]
        (self.dir / "ja.srt").write_text(srt(ja), encoding="utf-8")
        (self.dir / "zh.srt").write_text(srt(zh), encoding="utf-8")
        out = self.run_apply()
        new = apply_table.parse_srt((out / "zh.replaced.srt").read_text(encoding="utf-8"))
        self.assertEqual([c.text for c in new], ["Rider来了", "美杜莎在笑", "美杜莎笑了", "美杜莎去了", "晚安"])
        change = self.read_jsonl(out / "changes.jsonl")
        self.assertEqual([(c["index"], c["layer"]) for c in change], [(1, "variant")])
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        dropped = {d["text"]: (d["reason"], d["anchored"], d["other"]) for d in summary["entries"][0]["forms"][0]["zh_variants_dropped"]}
        self.assertEqual(dropped, {"美杜莎": ("specificity", 1, 2), "未曾现身": ("specificity", 0, 0),
                                   "Rider骑": ("superstring_of_zh", 0, 0)})
        unresolved = [(u["index"], u["reason"]) for u in self.read_jsonl(out / "unresolved.jsonl")]
        self.assertEqual(unresolved, [(2, "not_found")])

    def write_pairs(self, tbl: dict, pairs: list[tuple[str, str]]) -> None:
        (self.dir / "table.json").write_text(json.dumps(tbl, ensure_ascii=False), encoding="utf-8")
        (self.dir / "ja.srt").write_text(srt([p[0] for p in pairs]), encoding="utf-8")
        (self.dir / "zh.srt").write_text(srt([p[1] for p in pairs]), encoding="utf-8")

    def result_texts(self, out: Path) -> list[str]:
        return [c.text for c in apply_table.parse_srt((out / "zh.replaced.srt").read_text(encoding="utf-8"))]

    def test_single_char_base_beats_context_phrase_and_boundary(self):
        """单字 白 是主候选，不会用 叫白 之类语境串；落点紧邻清单外的汉字（如白、白色）时不动。"""
        a_cues = [("我叫白", "我叫白"), ("白来了", "白来了"), ("白在笑", "白在笑"), ("白去了", "白去了"),
                  ("我叫白艾米也叫白", "我叫白，艾米也叫白"), ("如果白去了", "如果白去了"), ("白色的花", "白色的花"),
                  ("是白啊", "是白啊")]
        fillers = [("朝", "他叫了人来去"), ("昼", "叫去又来"), ("夜", "去叫"), ("夕", "白天到了")]
        pairs = [("シロ" + ja, zh) for ja, zh in a_cues] + fillers
        self.write_pairs(table(entity("シロ", "士郎", [("シロ", "士郎")])), pairs)
        out = self.run_apply()
        self.assertEqual(self.result_texts(out),
                         ["我叫士郎", "士郎来了", "士郎在笑", "士郎去了", "我叫士郎，艾米也叫士郎",
                          "如果白去了", "白色的花", "是士郎啊"] + [f[1] for f in fillers])
        unresolved = {(u["index"], u["reason"]) for u in self.read_jsonl(out / "unresolved.jsonl")}
        self.assertEqual(unresolved, {(6, "boundary"), (7, "boundary")})
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        form = summary["entries"][0]["forms"][0]
        self.assertEqual(form["stat_rendering"], "白")
        self.assertEqual((form["replaced_stat"], form["unresolved_boundary"]), (6, 2))
        self.assertEqual(summary["totals"]["unresolved_boundary"], 2)

    def test_prefix_fragment_extends_only_with_support(self):
        """托萨 + 托萨克（支持足够）整名替换；托萨卡（只出现一次）不扩展，紧邻 卡 -> boundary 不动。"""
        pairs = [("トウサカ1", "托萨克来了"), ("トウサカ2", "托萨克去了"), ("トウサカ3", "托萨克在笑"), ("トウサカ4", "托萨卡去了"),
                 ("朝", "克服了困难去"), ("昼", "我克服了"), ("夜", "克制自己")]
        self.write_pairs(table(entity("遠坂", "远坂", [("トウサカ", "远坂")])), pairs)
        out = self.run_apply()
        self.assertEqual(self.result_texts(out),
                         ["远坂来了", "远坂去了", "远坂在笑", "托萨卡去了", "克服了困难去", "我克服了", "克制自己"])
        changes = self.read_jsonl(out / "changes.jsonl")
        self.assertEqual({c["span"] for c in changes}, {"托萨克"})
        self.assertTrue(all(c["extended_from"] for c in changes))
        unresolved = {(u["index"], u["reason"]) for u in self.read_jsonl(out / "unresolved.jsonl")}
        self.assertEqual(unresolved, {(4, "boundary")})

    def test_variant_inside_longer_word_is_not_replaced(self):
        """变体层同样查边界：真次 在 真次郎 里不替换。"""
        self.write_pairs(table(entity("真嗣", "真嗣", [("真次", "真嗣")], ["真次"])),
                         [("真次が来た", "真次来了"), ("真次郎", "真次郎来了")])
        out = self.run_apply()
        self.assertEqual(self.result_texts(out), ["真嗣来了", "真次郎来了"])
        self.assertEqual([(u["index"], u["reason"]) for u in self.read_jsonl(out / "unresolved.jsonl")], [(2, "boundary")])

    NAME_CHECK_PAIRS = [
        ("衛宮士郎が来た", "卫宫士郎来了"), ("エミヤが来た", "司郎来了"),                       # 1–2 appears（同目标的兄弟 form 里出现）
        ("イリヤ1", "伊莉亚来了"), ("イリヤ2", "伊莉亚在笑"), ("イリヤ3", "伊莉亚去了"),          # 3–5 near
        ("セイバー", "剑士来了"),                                                              # 6 class_ascii
        ("ゾウケン1", "脏砚来了"), ("ゾウケン2", "脏砚在笑"), ("ゾウケン3", "脏砚去了"),          # 7–9 unverified
    ]

    def name_check_table(self) -> dict:
        return table(
            entity("衛宮士郎", "卫宫士郎", [("衛宮士郎", "卫宫士郎"), ("エミヤ", "卫宫士郎")], ["司郎"]),
            entity("イリヤ", "伊莉雅", [("イリヤ", "伊莉雅")]),
            entity("セイバー", "Saber", [("セイバー", "Saber")], ["剑士"], kind="class"),
            entity("ゾウケン", "言峰绮礼", [("ゾウケン", "言峰绮礼")]))

    def test_name_check_outcomes(self):
        self.write_pairs(self.name_check_table(), self.NAME_CHECK_PAIRS)
        out = self.run_apply(extra=["--name-check"])
        self.assertEqual(self.result_texts(out),
                         ["卫宫士郎来了", "卫宫士郎来了", "伊莉雅来了", "伊莉雅在笑", "伊莉雅去了", "Saber来了",
                          "脏砚来了", "脏砚在笑", "脏砚去了"])
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        checks = {(e["entity_ja"], f["form_ja"]): f["name_check"] for e in summary["entries"] for f in e["forms"]}
        self.assertEqual(checks[("衛宮士郎", "エミヤ")], "appears")
        self.assertEqual(checks[("衛宮士郎", "衛宮士郎")], "appears")
        self.assertEqual(checks[("イリヤ", "イリヤ")], "near")
        self.assertEqual(checks[("セイバー", "セイバー")], "class_ascii")
        self.assertEqual(checks[("ゾウケン", "ゾウケン")], "unverified")
        self.assertEqual([(u["index"], u["reason"]) for u in self.read_jsonl(out / "unresolved.jsonl")],
                         [(7, "unverified_name"), (8, "unverified_name"), (9, "unverified_name")])
        (unverified,) = summary["unverified_forms"]
        self.assertEqual((unverified["form_ja"], unverified["target"], unverified["dominant_rendering"]),
                         ("ゾウケン", "言峰绮礼", "脏砚"))
        self.assertEqual(summary["totals"]["unresolved_unverified_name"], 3)

    def test_name_check_off_by_default(self):
        self.write_pairs(self.name_check_table(), self.NAME_CHECK_PAIRS)
        out = self.run_apply()  # 默认关闭核对
        self.assertEqual(self.result_texts(out)[6:], ["言峰绮礼来了", "言峰绮礼在笑", "言峰绮礼去了"])
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual({f["name_check"] for e in summary["entries"] for f in e["forms"]}, {"disabled"})
        self.assertEqual(summary["unverified_forms"], [])

    ISOLATED_PAIRS = [("シロ1", "白来了"), ("シロ2", "我叫白"), ("シロ3", "白在笑"), ("シロ4", "小白来了"),
                      ("シロ5", "他叫白啊"), ("シロ6", "你叫白呀"),
                      ("朝", "明白了"), ("昼", "明白吗"), ("夜", "白色的花"), ("夕", "白色来了")]

    def test_isolated_singles(self):
        """白 在 明白／白色 里到处出现，但孤立的 白 只在锚定 cue 里：默认（孤立单字开）被接受；叫白 保留 叫；小白 不动。"""
        self.write_pairs(table(entity("シロ", "士郎", [("シロ", "士郎")])), self.ISOLATED_PAIRS)
        fillers = [p[1] for p in self.ISOLATED_PAIRS[6:]]
        out = self.run_apply()  # 孤立单字默认开
        self.assertEqual(self.result_texts(out),
                         ["士郎来了", "我叫士郎", "士郎在笑", "小白来了", "他叫士郎啊", "你叫士郎呀"] + fillers)
        self.assertEqual([(u["index"], u["reason"]) for u in self.read_jsonl(out / "unresolved.jsonl")], [(4, "boundary")])
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        form = summary["entries"][0]["forms"][0]
        self.assertEqual(form["stat_rendering"], "白")
        self.assertIn({"text": "白", "anchored": 5, "other": 0}, form["stat_candidates_kept"])  # 只数孤立出现
        # --no-isolated-singles：白 的 b 把特异性拉到 0.6 以下，只剩 叫白 这个语境串被当成译法，叫 被吞掉（修复前的行为）
        texts = self.result_texts(self.run_apply(extra=["--no-isolated-singles"]))
        self.assertEqual([texts[1], texts[4], texts[5]], ["我士郎", "他士郎啊", "你士郎呀"])

    def test_extension_edges_respect_boundary_chars_when_isolated(self):
        texts = ["我叫白", "他叫白啊", "你叫白呀", "白来了", "白在笑", "路过"]
        self.assertEqual(apply_table.StatLayer("士郎", texts, [0, 1, 2, 3, 4]).extend(texts[0], 2, 3), (1, 3))
        stat = apply_table.StatLayer("士郎", texts, [0, 1, 2, 3, 4], isolated_singles=True)
        self.assertEqual(stat.extend(texts[0], 2, 3), (2, 3))
        self.assertTrue(apply_table.isolated_in("我叫白", "白"))
        self.assertTrue(apply_table.isolated_in("白，", "白"))
        self.assertFalse(apply_table.isolated_in("明白", "白"))
        self.assertFalse(apply_table.isolated_in("白色", "白"))
        self.assertFalse(apply_table.isolated_in("小白", "白"))

    ITERATE_PAIRS = [("ライダー1", "骑士来了"), ("ライダー2", "骑士在笑"), ("ライダー3", "骑士去了"),
                     ("ライダー4", "骑手来了"), ("ライダー5", "骑手去了"), ("朝", "早上好"), ("夜", "晚上好"),
                     ("昼", "手机坏了"), ("夕", "拍手叫好"), ("暮", "手套在桌上")]  # 手 在别处常见，不能单独当候选

    def test_iterate_reaches_fixpoint(self):
        """第一遍 骑士 -> Rider 后，骑 的支持只剩 骑手，第二遍 骑手 才过扩展的支持度；第三遍 0 改动停止。"""
        FILLER = ["手机坏了", "拍手叫好", "手套在桌上"]
        self.write_pairs(table(entity("ライダー", "Rider", [("ライダー", "Rider")], kind="class")), self.ITERATE_PAIRS)
        # 本测试的前提是旧口径（孤立单字改变了 手 这类碎片的支持度，骑手 第一遍就会被替换），所以显式关闭
        out = self.run_apply(extra=["--no-isolated-singles"])  # 默认 1 遍：骑手 因支持不足被 boundary 挡住
        self.assertEqual(self.result_texts(out), ["Rider来了", "Rider在笑", "Rider去了", "骑手来了", "骑手去了", "早上好", "晚上好"] + FILLER)
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["passes"], [3])
        self.assertEqual(summary["totals"]["unresolved_boundary"], 2)

        out = self.run_apply(extra=["--no-isolated-singles", "--iterate", "5"])
        self.assertEqual(self.result_texts(out), ["Rider来了", "Rider在笑", "Rider去了", "Rider来了", "Rider去了", "早上好", "晚上好"] + FILLER)
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["passes"], [3, 2, 0])
        changes = self.read_jsonl(out / "changes.jsonl")
        self.assertEqual(sorted((c["pass"], c["index"]) for c in changes), [(1, 1), (1, 2), (1, 3), (2, 4), (2, 5)])
        second = [c for c in changes if c["pass"] == 2]
        self.assertEqual({c["zh_before"] for c in second}, {"骑手来了", "骑手去了"})
        totals = summary["totals"]
        # 终态口径：被替换过的 cue 只算 replaced（一次），第二、三遍里"已规范"不重复计入，第一遍的 boundary 也随之消除
        self.assertEqual((totals["replaced_stat"], totals["already_canonical"], totals["unresolved_boundary"]), (5, 0, 0))
        self.assertEqual(totals["cues_changed"], 5)
        self.assertEqual(self.read_jsonl(out / "unresolved.jsonl"), [])

    def test_pool_by_target(self):
        """两个 form 同目标、各自支持不足（a=1）合并后够（a=2）；不同目标（卫宫）仍分开。"""
        self.write_pairs(
            table(entity("衛宮士郎", "卫宫士郎", [("シロウ", "士郎"), ("シロ", "士郎"), ("エミヤ", "卫宫")])),
            [("シロウ1", "希罗来了"), ("シロ1", "希罗去了"), ("エミヤ1", "艾米亚在笑"), ("朝", "早上好"), ("夜", "晚上好")])
        out = self.run_apply()
        self.assertEqual(self.result_texts(out), ["希罗来了", "希罗去了", "艾米亚在笑", "早上好", "晚上好"])  # 单个 form 撑不起
        out = self.run_apply(extra=["--pool-by-target"])
        self.assertEqual(self.result_texts(out), ["士郎来了", "士郎去了", "艾米亚在笑", "早上好", "晚上好"])
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        forms = {f["form_ja"]: f for f in summary["entries"][0]["forms"]}
        self.assertEqual((forms["シロウ"]["stat_pooled_cues"], forms["シロ"]["stat_pooled_cues"]), (2, 2))
        self.assertEqual(forms["エミヤ"]["stat_pooled_cues"], 1)  # 目标不同，另算
        self.assertEqual(forms["エミヤ"]["unresolved_not_found"], 1)

    def test_bigram_isolation(self):
        """单字孤立按语料判断：找白聊（找白、白聊 在别处不出现）算孤立；小白（别处 3 次）是词，不动。"""
        anchored = [("シロ1", "找白聊"), ("シロ2", "白来了"), ("シロ3", "白在笑"), ("シロ4", "小白啊")]
        fillers = [("朝", "明白了"), ("昼", "明白吗"), ("夜", "我明白"), ("夕", "小白兔"), ("暮", "小白龙"), ("暗", "小白鞋")]
        self.write_pairs(table(entity("シロ", "士郎", [("シロ", "士郎")])), anchored + fillers)
        tail = [p[1] for p in fillers]
        out = self.run_apply(extra=["--bigram-isolation"])
        self.assertEqual(self.result_texts(out), ["找士郎聊", "士郎来了", "士郎在笑", "小白啊"] + tail)
        self.assertEqual([(u["index"], u["reason"]) for u in self.read_jsonl(out / "unresolved.jsonl")], [(4, "boundary")])
        # 默认的清单口径下 聊／笑 不在 BOUNDARY_CHARS，白 的孤立出现不够，什么都不替换
        out = self.run_apply()
        self.assertEqual(self.result_texts(out)[0], "找白聊")

    def test_crlf_preserved(self):
        (self.dir / "zh.srt").write_bytes(srt([c[1] for c in CUES], "\r\n").encode("utf-8"))
        (self.dir / "ja.srt").write_bytes(srt([c[0] for c in CUES], "\r\n").encode("utf-8"))
        out = self.run_apply()
        data = (out / "zh.replaced.srt").read_bytes()
        self.assertNotIn(b"\r\r", data)
        self.assertEqual(data.count(b"\r\n"), data.count(b"\n"))
        self.assertIn("真嗣在哪里".encode("utf-8"), data)

    def test_cue_count_mismatch_exits_nonzero(self):
        (self.dir / "short.srt").write_text(srt([c[1] for c in CUES[:-1]]), encoding="utf-8")
        with self.assertRaises(SystemExit) as raised:
            self.run_apply("short.srt")
        self.assertNotIn(raised.exception.code, (0, None))
        self.assertFalse((self.dir / "out" / "zh.replaced.srt").exists())

    def test_measure_writes_report(self):
        out = self.dir / "measure.json"
        code = apply_table.main(["measure", "--pair", "synthetic", str(self.dir / "ja.srt"), str(self.dir / "zh.srt"),
                                 "--out", str(out)])
        self.assertEqual(code, 0)
        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertIn("synthetic", report)
        self.assertIn("inconsistency", report["synthetic"])


if __name__ == "__main__":
    unittest.main()
