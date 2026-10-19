"""kototoki.names.apply 的离线测试：合成 ja/zh cue 与专名表，覆盖变体层、已规范、统计层、未命中、重叠与非锚定 cue。

用例移植自 `experiments/name_consistency/test_apply_table.py` 的默认路径，期望值沿用研究期测试，不导入
`experiments.*`；针对研究期已删开关（`--name-check`、`--pool-by-target`、`--bigram-isolation`、`--iterate`、
`--weak-name-check`、`--min-confidence`、`--no-isolated-singles`）以及 SRT 文本读写、`measure` 的用例不移植
（研究期 `test_modifier_is_not_swallowed` 的期望依赖 `--pool-by-target`，默认路径下结果不同，同样不移植）。
小样本触发不了统计层的全部分支，与研究脚本逐字节相同的整片等价校验在产品路径验收里做。
"""

from __future__ import annotations

import copy
import unittest

from kototoki.names.apply import ApplyResult, StatLayer, apply, isolated_in
from kototoki.srt import SourceDocument, format_srt, parse_srt

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

# 期望的译文；键是 SRT 序号，未列出的条目不变
EXPECTED = {1: "真嗣在哪里", 3: "卢薇娅在笑", 4: "卢薇娅来了", 5: "卢薇娅要去了", 6: "是卢薇娅啊",
            7: "卢薇娅的声音", 9: "远坂的家", 11: "间桐的家到了",
            13: "真嗣来了", 14: "真嗣啊", 15: "真嗣吗"}


def run(tbl: dict, pairs: list[tuple[str, str]]) -> tuple[SourceDocument, dict[str, str], ApplyResult]:
    """pairs 是 (日文, 中文)；返回日文文档、输入译文（cue id → 中文）与 apply 的结果。"""
    document = parse_srt(format_srt([(n, n + 0.9, ja) for n, (ja, _) in enumerate(pairs)]))
    translations = {cue.id: zh for cue, (_, zh) in zip(document.cues, pairs)}
    return document, translations, apply(tbl, document, translations)


def texts(document: SourceDocument, result: ApplyResult) -> list[str]:
    return [result.translations[cue.id] for cue in document.cues]


class ApplyTest(unittest.TestCase):
    def test_replacement_and_structure(self):
        document, translations, result = run(TABLE, CUES)
        self.assertEqual(list(result.translations), [cue.id for cue in document.cues])  # 覆盖全部 cue，顺序同文档
        for number, (_, zh) in enumerate(CUES, 1):
            self.assertEqual(texts(document, result)[number - 1], EXPECTED.get(number, zh), f"cue {number}")
        self.assertIn("真次的早晨", result.translations[document.cues[11].id])  # 非锚定 cue 不动
        self.assertEqual(translations, {cue.id: CUES[i][1] for i, cue in enumerate(document.cues)})  # 输入不被修改

    def test_changes_unresolved_and_summary(self):
        document, _, result = run(TABLE, CUES)
        changes = result.changes
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
        self.assertEqual({c["index"]: c["cue_id"] for c in changes},
                         {cue.index: cue.id for cue in document.cues if cue.index in EXPECTED})

        unresolved = {(u["index"], u["entry"]): u["reason"] for u in result.unresolved}
        self.assertEqual(unresolved, {(8, "遠坂"): "not_found", (10, "間桐"): "overlap", (10, "間桐慎二"): "overlap"})
        self.assertEqual({u["index"]: u["cue_id"] for u in result.unresolved},
                         {cue.index: cue.id for cue in document.cues if cue.index in (8, 10)})

        summary = result.summary
        self.assertEqual(summary["cues"], len(CUES))
        self.assertNotIn("passes", summary)
        self.assertTrue(all("_e" not in row for row in summary["entries"]))
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
        tbl = table(
            entity("衛宮士郎", "卫宫士郎", [("衛宮士郎", "卫宫士郎"), ("シロウ", "士郎"), ("四郎", "士郎"), ("エミヤ", "卫宫")],
                   ["希罗", "白郎"]),
            entity("遠坂凛", "远坂凛", [("遠坂凛", "远坂凛"), ("遠坂", "远坂"), ("東坂", "远坂")], ["东坂"]))
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
        document, _, result = run(tbl, pairs)
        self.assertEqual(texts(document, result),
                         ["卫宫士郎来了", "士郎来了", "卫宫士郎笑了", "士郎要去了", "士郎啊", "卫宫来了",
                          "远坂来了", "远坂来了", "远坂凛だ", "远坂来了"])
        changes = {c["index"]: c for c in result.changes}
        self.assertEqual(sorted(changes), [4, 5, 7])
        self.assertEqual((changes[4]["form_ja"], changes[4]["target"], changes[4]["span"]), ("シロウ", "士郎", "希罗"))
        self.assertEqual((changes[7]["form_ja"], changes[7]["target"], changes[7]["span"]), ("東坂", "远坂", "东坂"))
        rows = {row["entity_ja"]: row for row in result.summary["entries"]}
        forms = {name: {f["form_ja"]: f for f in row["forms"]} for name, row in rows.items()}
        shirou = forms["衛宮士郎"]["シロウ"]
        self.assertEqual((shirou["anchored"], shirou["already_canonical"], shirou["replaced_variant"]), (4, 2, 2))
        self.assertEqual(rows["衛宮士郎"]["already_canonical"], 4)
        # 最长 form 优先：遠坂凛 的两个 cue 不会再被 遠坂 处理
        rin = forms["遠坂凛"]
        self.assertEqual((rin["遠坂凛"]["anchored"], rin["遠坂"]["anchored"], rin["東坂"]["anchored"]), (2, 1, 1))
        self.assertEqual((rin["遠坂凛"]["partial_canonical"], rin["遠坂凛"]["already_canonical"]), (1, 1))
        self.assertEqual(rin["東坂"]["replaced_variant"], 1)
        self.assertEqual(result.summary["totals"]["partial_canonical"], 1)
        self.assertEqual(result.summary["entries_skipped_confidence"], [])

    def test_disjoint_form_zh_is_not_a_candidate(self):
        """其他 form 的 zh 与目标互不包含时不是候选：士郎 的 cue 里的 卫宫 不会被改成 士郎。"""
        tbl = table(entity("衛宮士郎", "卫宫士郎", [("シロウ", "士郎"), ("エミヤ", "卫宫")]))
        document, _, result = run(tbl, [("シロウはどこ", "卫宫，士郎在哪")])
        self.assertEqual(texts(document, result), ["卫宫，士郎在哪"])
        self.assertEqual(result.changes, [])

    def test_stat_layer_is_per_form(self):
        """统计层只看本 form 锚定的 cue，各 form 的主译法互不干扰。"""
        tbl = table(entity("ルヴィアゼリッタ", "卢薇娅泽莉塔", [("ルヴィア", "卢薇娅"), ("ゼリッタ", "泽莉塔")]))
        pairs = [("ルヴィアが来た", "鲁维娅来了"), ("ルヴィアが笑う", "鲁维娅在笑"), ("ルヴィアは行く", "鲁维娅去了"),
                 ("ゼリッタが来た", "泽丽塔来了"), ("ゼリッタが笑う", "泽丽塔在笑"), ("ゼリッタは行く", "泽丽塔去了"),
                 ("朝", "早上好"), ("夜", "晚上好")]
        document, _, result = run(tbl, pairs)
        self.assertEqual(texts(document, result),
                         ["卢薇娅来了", "卢薇娅在笑", "卢薇娅去了", "泽莉塔来了", "泽莉塔在笑", "泽莉塔去了", "早上好", "晚上好"])
        forms = {f["form_ja"]: f for f in result.summary["entries"][0]["forms"]}
        self.assertEqual((forms["ルヴィア"]["stat_rendering"], forms["ゼリッタ"]["stat_rendering"]), ("鲁维娅", "泽丽塔"))
        self.assertEqual((forms["ルヴィア"]["replaced_stat"], forms["ゼリッタ"]["replaced_stat"]), (3, 3))

    def test_confidence_does_not_skip_entities(self):
        """研究期的 --min-confidence 已删：低置信度条目照常应用，summary 里的跳过清单恒为空。"""
        tbl = table(entity("シンジ", "慎二", [("シンジ", "慎二")], ["新治"], confidence="high"),
                    entity("シロウ", "士郎", [("シロウ", "士郎")], ["希罗"], confidence="low"))
        document, _, result = run(tbl, [("シンジが来た", "新治来了"), ("シロウが来た", "希罗来了")])
        self.assertEqual(texts(document, result), ["慎二来了", "士郎来了"])
        self.assertEqual(result.summary["entries_skipped_confidence"], [])
        self.assertEqual([row["entity_ja"] for row in result.summary["entries"]], ["シンジ", "シロウ"])

    def test_compound_adjacency_is_skipped(self):
        """落点紧邻 ·／・ 或拉丁字母时不替换并记 compound；两侧、两层都适用，普通 cue 照常替换。"""
        tbl = table(entity("アンリマユ", "安哥拉", [("アンリマユ", "安哥拉")], ["玛尤"]),
                    entity("シロウ", "卫宫士郎", [("シロウ", "卫宫士郎")]))
        ja = ["アンリマユ1", "アンリマユ2", "アンリマユ3", "アンリマユ4",
              "シロウ1", "シロウ2", "シロウ3", "シロウ4", "朝が来た"]
        zh = ["安里·玛尤", "玛尤·英弥", "玛尤来了", "Saber玛尤",
              "希罗来了", "希罗去吧", "艾米亚·希罗", "希罗·英弥", "早上好"]
        document, _, result = run(tbl, list(zip(ja, zh)))
        self.assertEqual(texts(document, result),
                         ["安里·玛尤", "玛尤·英弥", "安哥拉来了", "Saber玛尤",
                          "卫宫士郎来了", "卫宫士郎去吧", "艾米亚·希罗", "希罗·英弥", "早上好"])
        unresolved = {(u["index"], u["reason"]) for u in result.unresolved}
        self.assertEqual(unresolved, {(1, "compound"), (2, "compound"), (4, "compound"),
                                      (7, "compound"), (8, "compound")})
        rows = {row["entity_ja"]: row for row in result.summary["entries"]}
        self.assertEqual((rows["アンリマユ"]["unresolved_compound"], rows["アンリマユ"]["replaced_variant"]), (3, 1))
        self.assertEqual((rows["シロウ"]["unresolved_compound"], rows["シロウ"]["replaced_stat"]), (2, 2))
        self.assertEqual(result.summary["totals"]["unresolved_compound"], 5)

    def test_stat_candidate_filter(self):
        """短语 n-gram 因特异性不足被丢弃；音译写法（锚定 3 次、别处 0 次）保留；形状不合格的丢弃。"""
        zh_texts = ["希罗来了", "希罗想要保护", "希罗去吧",   # 0–2 锚定
                    "我想要保护你", "想要保护的人", "还想要保护", "樱战斗的武器", "路上"]
        stat = StatLayer("卫宫士郎", zh_texts, [0, 1, 2])
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
        many = StatLayer("间桐樱", ["樱花开了"] * 2 + ["路过"] * 98, list(range(100)))
        self.assertEqual(many.min_anchored, 4)
        self.assertFalse(many.accept("樱花"))
        self.assertEqual(many.dropped[-1]["reason"], "specificity")
        dropped = {d["text"]: (d["anchored"], d["other"]) for d in stat.dropped}
        self.assertEqual(dropped["想要保护"], (1, 3))

    def test_stat_span_extension(self):
        """统计层落点向外扩展到有支持的最长超串；超串没有支持就保持原落点；扩展后再查 compound。"""
        tbl = table(entity("アインツベルン", "爱因兹贝伦", [("アインツベルン", "爱因兹贝伦")]),
                    entity("シンジ", "慎二", [("シンジ", "慎二")]))
        ja = ["アインツベルン1", "アインツベルン2", "アインツベルン3", "アインツベルン4",
              "シンジ1", "シンジ2", "シンジ3", "シンジ4", "朝が来た", "夜が来た"]
        zh = ["艾因茨贝伦来了", "艾因茨贝伦在笑", "艾因茨贝伦去了", "埃因茨贝伦到了",
              "阿新治来了", "阿新治在笑", "新治去了", "安·阿新治到了", "早上好", "晚上好"]
        document, _, result = run(tbl, list(zip(ja, zh)))
        self.assertEqual(texts(document, result),
                         ["爱因兹贝伦来了", "爱因兹贝伦在笑", "爱因兹贝伦去了",
                          "埃因茨贝伦到了",  # 爱因茨贝伦 只在 1 个 cue：超串没有支持，落点紧邻 埃 不在清单里 -> boundary，不动
                          "慎二来了", "慎二在笑", "慎二去了",
                          "安·阿新治到了",  # 扩展成 阿新治 后紧邻 ·，按 compound 跳过
                          "早上好", "晚上好"])
        changes = {c["index"]: c for c in result.changes}
        self.assertEqual(changes[1]["span"], "艾因茨贝伦")
        self.assertIn(changes[1]["extended_from"], ("艾", "因茨贝伦"))  # 从哪个片段起扩展取决于排序，结果都是整名
        self.assertNotIn(4, changes)
        self.assertEqual(changes[5]["span"], "阿新治")
        self.assertIn(changes[5]["extended_from"], ("阿", "新治"))
        self.assertEqual(changes[7]["span"], "新治")
        self.assertNotIn("extended_from", changes[7])
        unresolved = {(u["index"], u["reason"]) for u in result.unresolved}
        self.assertEqual(unresolved, {(4, "boundary"), (8, "compound")})
        # 超串不能以间隔点开头或结尾（"安里·" 之类）
        stat = StatLayer("安徒生", ["安里·玛伊", "安里·真由", "安里玛尤"], [0, 1, 2])
        self.assertEqual(stat.extend("安里·玛伊", 0, 2), (0, 2))

    def test_dotted_run_must_be_covered_whole(self):
        """含间隔点的扩展必须覆盖整段连续串：不把 艾米亚·希罗 截成 米亚·希罗。"""
        zh_texts = ["埃米亚·希罗", "埃米亚·希罗", "艾米亚·希罗", "路过"]
        stat = StatLayer("卫宫士郎", zh_texts, [0, 1, 2])
        self.assertEqual(stat.extend(zh_texts[0], 4, 6), (0, 6))  # 整段 埃米亚·希罗：支持 2 次，通过
        self.assertEqual(stat.extend(zh_texts[2], 4, 6), (4, 6))  # 只有被截的 米亚·希罗 有支持，拒绝
        # 整段连续串比 MAX_EXTEND 还长，含点的超串到不了整段边界，同样拒绝
        zh_texts = ["我的使命就是保护埃米亚·希罗", "我的使命就是保护埃米亚·希罗", "路过"]
        stat = StatLayer("卫宫士郎", zh_texts, [0, 1])
        self.assertEqual(stat.extend(zh_texts[0], 12, 14), (12, 14))

    def test_zh_variants_are_filtered(self):
        """模型列的 zh_variants 也要过特异性：别名／无关词不替换；单次出现的真变体仍可替换；落选的记入 summary。"""
        tbl = table(entity("ライダー", "Rider", [("ライダー", "Rider")], ["骑士", "美杜莎", "未曾现身", "Rider骑"], kind="role"))
        ja = ["ライダー1", "ライダー2", "朝", "昼", "夜"]
        zh = ["骑士来了", "美杜莎在笑", "美杜莎笑了", "美杜莎去了", "晚安"]
        document, _, result = run(tbl, list(zip(ja, zh)))
        self.assertEqual(texts(document, result), ["Rider来了", "美杜莎在笑", "美杜莎笑了", "美杜莎去了", "晚安"])
        self.assertEqual([(c["index"], c["layer"]) for c in result.changes], [(1, "variant")])
        dropped = {d["text"]: (d["reason"], d["anchored"], d["other"])
                   for d in result.summary["entries"][0]["forms"][0]["zh_variants_dropped"]}
        self.assertEqual(dropped, {"美杜莎": ("specificity", 1, 2), "未曾现身": ("specificity", 0, 0),
                                   "Rider骑": ("superstring_of_zh", 0, 0)})
        self.assertEqual([(u["index"], u["reason"]) for u in result.unresolved], [(2, "not_found")])

    def test_single_char_base_beats_context_phrase_and_boundary(self):
        """单字 白 是主候选，不会用 叫白 之类语境串；落点紧邻清单外的汉字（如白、白色）时不动。"""
        a_cues = [("我叫白", "我叫白"), ("白来了", "白来了"), ("白在笑", "白在笑"), ("白去了", "白去了"),
                  ("我叫白艾米也叫白", "我叫白，艾米也叫白"), ("如果白去了", "如果白去了"), ("白色的花", "白色的花"),
                  ("是白啊", "是白啊")]
        fillers = [("朝", "他叫了人来去"), ("昼", "叫去又来"), ("夜", "去叫"), ("夕", "白天到了")]
        pairs = [("シロ" + ja, zh) for ja, zh in a_cues] + fillers
        document, _, result = run(table(entity("シロ", "士郎", [("シロ", "士郎")])), pairs)
        self.assertEqual(texts(document, result),
                         ["我叫士郎", "士郎来了", "士郎在笑", "士郎去了", "我叫士郎，艾米也叫士郎",
                          "如果白去了", "白色的花", "是士郎啊"] + [f[1] for f in fillers])
        self.assertEqual({(u["index"], u["reason"]) for u in result.unresolved}, {(6, "boundary"), (7, "boundary")})
        form = result.summary["entries"][0]["forms"][0]
        self.assertEqual(form["stat_rendering"], "白")
        self.assertEqual((form["replaced_stat"], form["unresolved_boundary"]), (6, 2))
        self.assertEqual(result.summary["totals"]["unresolved_boundary"], 2)

    def test_prefix_fragment_extends_only_with_support(self):
        """托萨 + 托萨克（支持足够）整名替换；托萨卡（只出现一次）不扩展，紧邻 卡 -> boundary 不动。"""
        pairs = [("トウサカ1", "托萨克来了"), ("トウサカ2", "托萨克去了"), ("トウサカ3", "托萨克在笑"), ("トウサカ4", "托萨卡去了"),
                 ("朝", "克服了困难去"), ("昼", "我克服了"), ("夜", "克制自己")]
        document, _, result = run(table(entity("遠坂", "远坂", [("トウサカ", "远坂")])), pairs)
        self.assertEqual(texts(document, result),
                         ["远坂来了", "远坂去了", "远坂在笑", "托萨卡去了", "克服了困难去", "我克服了", "克制自己"])
        self.assertEqual({c["span"] for c in result.changes}, {"托萨克"})
        self.assertTrue(all(c["extended_from"] for c in result.changes))
        self.assertEqual({(u["index"], u["reason"]) for u in result.unresolved}, {(4, "boundary")})

    def test_variant_inside_longer_word_is_not_replaced(self):
        """变体层同样查边界：真次 在 真次郎 里不替换。"""
        document, _, result = run(table(entity("真嗣", "真嗣", [("真次", "真嗣")], ["真次"])),
                                  [("真次が来た", "真次来了"), ("真次郎", "真次郎来了")])
        self.assertEqual(texts(document, result), ["真嗣来了", "真次郎来了"])
        self.assertEqual([(u["index"], u["reason"]) for u in result.unresolved], [(2, "boundary")])

    def test_name_check_is_not_applied(self):
        """研究期的 --name-check 已删：目标名得不到译者用法佐证也照常替换，name_check 恒为 disabled。"""
        tbl = table(entity("ゾウケン", "言峰绮礼", [("ゾウケン", "言峰绮礼")]))
        document, _, result = run(tbl, [("ゾウケン1", "脏砚来了"), ("ゾウケン2", "脏砚在笑"), ("ゾウケン3", "脏砚去了")])
        self.assertEqual(texts(document, result), ["言峰绮礼来了", "言峰绮礼在笑", "言峰绮礼去了"])
        self.assertEqual({f["name_check"] for e in result.summary["entries"] for f in e["forms"]}, {"disabled"})
        self.assertEqual(result.summary["unverified_forms"], [])
        self.assertEqual(result.summary["entries_skipped_unverified"], [])

    ISOLATED_PAIRS = [("シロ1", "白来了"), ("シロ2", "我叫白"), ("シロ3", "白在笑"), ("シロ4", "小白来了"),
                      ("シロ5", "他叫白啊"), ("シロ6", "你叫白呀"),
                      ("朝", "明白了"), ("昼", "明白吗"), ("夜", "白色的花"), ("夕", "白色来了")]

    def test_isolated_singles(self):
        """白 在 明白／白色 里到处出现，但孤立的 白 只在锚定 cue 里：被接受；叫白 保留 叫；小白 不动。"""
        document, _, result = run(table(entity("シロ", "士郎", [("シロ", "士郎")])), self.ISOLATED_PAIRS)
        fillers = [p[1] for p in self.ISOLATED_PAIRS[6:]]
        self.assertEqual(texts(document, result),
                         ["士郎来了", "我叫士郎", "士郎在笑", "小白来了", "他叫士郎啊", "你叫士郎呀"] + fillers)
        self.assertEqual([(u["index"], u["reason"]) for u in result.unresolved], [(4, "boundary")])
        form = result.summary["entries"][0]["forms"][0]
        self.assertEqual(form["stat_rendering"], "白")
        self.assertIn({"text": "白", "anchored": 5, "other": 0}, form["stat_candidates_kept"])  # 只数孤立出现

    def test_extension_edges_respect_boundary_chars(self):
        zh_texts = ["我叫白", "他叫白啊", "你叫白呀", "白来了", "白在笑", "路过"]
        stat = StatLayer("士郎", zh_texts, [0, 1, 2, 3, 4])
        self.assertEqual(stat.extend(zh_texts[0], 2, 3), (2, 3))  # 叫白 保留 叫
        self.assertTrue(isolated_in("我叫白", "白"))
        self.assertTrue(isolated_in("白，", "白"))
        self.assertFalse(isolated_in("明白", "白"))
        self.assertFalse(isolated_in("白色", "白"))
        self.assertFalse(isolated_in("小白", "白"))

    def test_extension_must_not_swallow_stronger_candidate(self):
        """单看 笨蛋（2 个 cue）的支持度，超串 笨蛋伊莉亚（同样 2 个 cue）总能过 EXTEND_SHARE；超串里的强落点要一并比。"""
        zh_texts = ["伊莉亚来了"] * 6 + ["笨蛋伊莉亚", "笨蛋伊莉亚来了", "早上好", "晚上好"]
        stat = StatLayer("伊莉雅", zh_texts, list(range(8)))
        text = "笨蛋伊莉亚"
        self.assertEqual(stat.extend(text, 0, 2), (0, 5))  # 不带对手：被吞
        self.assertEqual(stat.extend(text, 0, 2, [(2, 5, 8)]), (0, 2))  # 带上强落点：不吞

    def test_fallback_cue_is_skipped(self):
        """译文与日文原文相同的 cue（翻译回退）不参与锚定与替换，原样返回；其余 cue 照常。"""
        tbl = table(entity("真嗣", "真嗣", [("真次", "真嗣")], ["真次"]))
        pairs = [("真次が来た", "真次来了"), ("真次が笑う", "真次在笑"), ("真次が来た", "真次が来た")]  # 第 3 条回退
        document, _, result = run(tbl, pairs)
        self.assertEqual(texts(document, result), ["真嗣来了", "真嗣在笑", "真次が来た"])
        self.assertEqual(sorted(c["index"] for c in result.changes), [1, 2])
        self.assertEqual(result.unresolved, [])  # 回退 cue 不记 not_found
        row = result.summary["entries"][0]["forms"][0]
        self.assertEqual((row["anchored"], row["replaced_variant"]), (2, 2))
        self.assertEqual(result.summary["cues"], 3)
        self.assertEqual(list(result.translations), [cue.id for cue in document.cues])

    def test_fallback_cue_does_not_enter_statistics(self):
        """回退 cue 不算非锚定 cue：它的日文汉字不会拉低候选的特异性。"""
        tbl = table(entity("ルヴィア", "卢薇娅", [("ルヴィア", "卢薇娅")]))
        anchored = [("ルヴィア1", "鲁维娅来了"), ("ルヴィア2", "鲁维娅在笑"), ("ルヴィア3", "鲁维娅去了")]
        document, _, result = run(tbl, anchored + [("朝", "早上好")])
        self.assertEqual(texts(document, result)[:3], ["卢薇娅来了", "卢薇娅在笑", "卢薇娅去了"])
        stat_form = result.summary["entries"][0]["forms"][0]
        self.assertIn({"text": "鲁维娅", "anchored": 3, "other": 0}, stat_form["stat_candidates_kept"])
        # 一条回退 cue（日文原文里恰好含 鲁维娅）：若算作非锚定 cue，other 会变成 1，特异性降到 0.75 以下被丢弃
        document, _, result = run(tbl, anchored + [("鲁维娅", "鲁维娅")])
        self.assertEqual(texts(document, result)[:3], ["卢薇娅来了", "卢薇娅在笑", "卢薇娅去了"])
        stat_form = result.summary["entries"][0]["forms"][0]
        self.assertIn({"text": "鲁维娅", "anchored": 3, "other": 0}, stat_form["stat_candidates_kept"])

    def test_empty_entries_returns_translations_unchanged(self):
        document, translations, result = run(table(), CUES)
        self.assertEqual(result.translations, translations)
        self.assertEqual((result.changes, result.unresolved), ([], []))
        self.assertEqual(result.summary["entries"], [])
        self.assertEqual(result.summary["totals"]["cues_changed"], 0)

    def test_schema_errors(self):
        document = parse_srt(format_srt([(0, 1, "真次が来た")]))
        translations = {document.cues[0].id: "真次来了"}
        wrong = copy.deepcopy(TABLE)
        wrong["schema"] = "name-table-v1"
        with self.assertRaisesRegex(ValueError, "schema"):
            apply(wrong, document, translations)
        with self.assertRaisesRegex(ValueError, "schema"):
            apply({"entries": []}, document, translations)
        with self.assertRaisesRegex(ValueError, "entries"):
            apply({"schema": "name-table-v2"}, document, translations)


if __name__ == "__main__":
    unittest.main()
