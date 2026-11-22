"""按条解决的伪客户端测试（batch-run-fixes 08，ADR-0029）：结构合法的回复按条收下、未解决的 cue 按连续段追问、
零收下与结构失败对半拆、单条仍失败不出中文、超出 context 直接拆、续跑复用已记录的节点、未翻译终态、改 seed 重试、
追问中途的基础设施失败、`report.json`／`scene.json` 内容，以及经编排器写进 `published.json` 的未翻译计数。
不启动 Strata，不占 GPU。"""

from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
from typing import Any
import unittest

from kototoki import artifacts
from kototoki.artifacts import read_json
from kototoki.translate import generate
from kototoki.translate import recipes as R
from kototoki.translate.batching import build_batches, scene_from_document
from kototoki.translate.resolve import halves, runs
from tests.core.test_job import JobCase
from tests.core.test_translate import SEED, Harness, document


class NodeTests(unittest.TestCase):
    def test_halves_and_runs_use_the_batch_neighbour_rule(self) -> None:
        scene = scene_from_document(document(23))
        ids = scene.ids
        batch = build_batches(scene)[1]  # ids[10:20]；wide-context-v1 只按条数取邻文，不看停顿
        self.assertEqual((batch.before_ids, batch.after_ids), (tuple(ids[0:10]), tuple(ids[20:23])))
        a, b = halves(scene, batch)
        self.assertEqual((a.batch_id, b.batch_id), (batch.batch_id + ".a", batch.batch_id + ".b"))
        self.assertEqual((a.target_ids, a.before_ids, a.after_ids),
                         (tuple(ids[10:15]), tuple(ids[0:10]), tuple(ids[15:20])))
        self.assertEqual((b.target_ids, b.before_ids, b.after_ids),
                         (tuple(ids[15:20]), tuple(ids[0:15]), tuple(ids[20:23])))
        self.assertEqual([len(n.target_ids) for n in halves(scene, a)], [3, 2])  # 奇数条前半多 1 条
        (single,) = runs(scene, a, [ids[11]])
        self.assertEqual(halves(scene, single), [])
        # 未解决的 cue 按场景顺序切成最大连续段（传入顺序无关）。
        first, second = runs(scene, batch, [ids[16], ids[12], ids[13]])
        self.assertEqual((first.batch_id, first.target_ids, first.before_ids, first.after_ids),
                         (batch.batch_id + ".1", (ids[12], ids[13]), tuple(ids[0:12]), tuple(ids[14:19])))
        self.assertEqual((second.batch_id, second.target_ids), (batch.batch_id + ".2", (ids[16],)))
        self.assertEqual(runs(scene, batch, []), [])


class ResolveTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.h = Harness(Path(tmp.name))

    def root(self, doc) -> Path:
        return self.h.run_root(doc)

    def lines(self, doc, name: str) -> list[dict[str, Any]]:
        path = self.root(doc) / name
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []

    def targets(self, start: int = 0) -> list[list[str]]:
        """每个请求的待译 ID（从第 `start` 个请求起）。"""
        result = []
        for request in self.h.requests[start:]:
            user = request["messages"][1]["content"]
            target, _ = json.JSONDecoder().raw_decode(user.split("【待译 JSON】\n", 1)[1])
            result.append(list(target["translations"]))
        return result

    def test_unresolved_cues_are_asked_again_in_runs(self) -> None:
        doc = document(12)
        ids = [cue.id for cue in doc.cues]
        self.h.empty = {ids[3]: 1}
        self.h.drop = {ids[6]: 1, ids[7]: 1}
        with self.assertLogs("kototoki.translate", level="INFO") as logs:
            result = self.h.translate(doc)
        self.assertEqual(result.untranslated_count, 0)
        self.assertEqual(result.translations, {k: "译" + k for k in ids})
        # 原批次 1 次（收下 7 条），两段各 1 次，然后第 1 批；合格的 7 条不再请求。
        self.assertEqual(self.targets(), [ids[0:10], [ids[3]], [ids[6], ids[7]], ids[10:12]])
        scene = scene_from_document(doc)
        first_run = runs(scene, build_batches(scene)[0], [ids[3]])[0]
        expected = R.request_body(R.messages(first_run.to_window(scene), []), SEED)
        self.assertEqual(json.dumps(self.h.requests[1], ensure_ascii=False), json.dumps(expected, ensure_ascii=False))

        row = self.lines(doc, "batches.jsonl")[0]
        b = row["batch_id"]
        nodes = row["resolution"]["nodes"]
        self.assertEqual([(n["batch_id"], n["depth"], n["status"], n["attempts"]) for n in nodes],
                         [(b, 0, "partial", 1), (b + ".1", 1, "accepted", 1), (b + ".2", 1, "accepted", 1)])
        self.assertEqual(nodes[0]["unresolved"], {ids[3]: "empty", ids[6]: "missing", ids[7]: "missing"})
        self.assertEqual(row["resolution"]["untranslated"], [])
        self.assertNotIn("request", row)
        self.assertNotIn("resolution", self.lines(doc, "batches.jsonl")[1])
        self.assertEqual([r["batch_id"] for r in self.lines(doc, "nodes.jsonl")], [b, b + ".1", b + ".2"])
        warnings = [r.getMessage() for r in logs.records if r.levelname == "WARNING"]
        self.assertEqual(warnings, [f"[translate] batch {b}: 3 cue(s) unresolved (empty 1, missing 2); "
                                    f"asking again in 2 sub-batch(es)"])
        self.assertIn("[translate] batch 1/2: 10 cue(s), followed up (3 request(s), 0 untranslated)",
                      [r.getMessage() for r in logs.records])
        self.assertEqual(result.report["counts"], {"batches": 2, "followup_batches": 1, "untranslated_cues": 0,
                                                   "followup_requests": 2})

    def test_cue_that_stays_empty_is_left_untranslated(self) -> None:
        doc = document(12)
        ids = [cue.id for cue in doc.cues]
        self.h.empty = {ids[3]: 99}
        with self.assertLogs("kototoki.translate", level="INFO") as logs:
            result = self.h.translate(doc)
        self.assertEqual(result.untranslated_count, 1)
        self.assertIsNone(result.translations[ids[3]])
        self.assertEqual({k: v for k, v in result.translations.items() if k != ids[3]},
                         {k: "译" + k for k in ids if k != ids[3]})
        # 单条节点两次都一条没收下（seed、seed＋1），不再拆。
        self.assertEqual(self.targets(), [ids[0:10], [ids[3]], [ids[3]], ids[10:12]])
        self.assertEqual([r["seed"] for r in self.h.requests[1:3]], [SEED, SEED + 1])
        row = self.lines(doc, "batches.jsonl")[0]
        b = row["batch_id"]
        node = row["resolution"]["nodes"][1]
        self.assertEqual((node["batch_id"], node["status"], node["error_kind"]), (b + ".1", "failed", "unresolved"))
        self.assertEqual(row["resolution"]["untranslated"],
                         [{"id": ids[3], "batch_id": b + ".1", "reason": "empty",
                           "error": node["request"]["attempts"][-1]["error"], "attempts": 3}])
        self.assertEqual(node["request"]["attempts"][-1]["error"], "no cue accepted: 1 unresolved (empty 1)")
        messages = [r.getMessage() for r in logs.records if r.levelname == "WARNING"]
        self.assertEqual([m.split(": no cue")[0] for m in messages if " attempt " in m],
                         [f"[translate] batch {b}.1 attempt {n}/2 failed (unresolved)" for n in (1, 2)])
        self.assertIn(f"[translate] batch {b}: 1 cue(s) left untranslated: {ids[3]} (empty)", messages)

        report = read_json(self.root(doc) / "report.json")
        self.assertEqual(report, result.report)
        self.assertEqual(report["schema"], "kototoki-translate-report-v2")
        self.assertEqual(report["counts"], {"batches": 2, "followup_batches": 1, "untranslated_cues": 1,
                                            "followup_requests": 1})
        (followed,) = report["followup_batches"]
        self.assertEqual((followed["batch_id"], followed["requests"], followed["attempts"], followed["untranslated_ids"]),
                         (b, 2, 3, [ids[3]]))
        scene_json = read_json(self.root(doc) / "scene.json")
        self.assertEqual((scene_json["untranslated_ids"], scene_json["translations"][ids[3]]), ([ids[3]], None))
        self.assertEqual((scene_json["totals"]["requests"], scene_json["totals"]["attempts"]), (3, 4))

    def test_structural_failures_halve_down_to_a_single_cue(self) -> None:
        doc = document(12)
        ids = [cue.id for cue in doc.cues]
        self.h.poison = {ids[3]}
        result = self.h.translate(doc)
        self.assertEqual(result.untranslated_count, 1)
        self.assertIsNone(result.translations[ids[3]])
        self.assertEqual(self.targets(), [ids[0:10]] * 2 + [ids[0:5]] * 2 + [ids[0:3]] + [ids[3:5]] * 2
                         + [[ids[3]]] * 2 + [[ids[4]], ids[5:10], ids[10:12]])
        self.assertEqual(self.h.events, ["start:1", "stop:1"])  # 终态失败不重启 Strata
        row = self.lines(doc, "batches.jsonl")[0]
        b = row["batch_id"]
        self.assertEqual([(n["batch_id"], n["depth"], n["status"]) for n in row["resolution"]["nodes"]],
                         [(b, 0, "failed"), (b + ".a", 1, "failed"), (b + ".a.a", 2, "accepted"),
                          (b + ".a.b", 2, "failed"), (b + ".a.b.a", 3, "failed"), (b + ".a.b.b", 3, "accepted"),
                          (b + ".b", 1, "accepted")])
        (item,) = row["resolution"]["untranslated"]
        self.assertEqual((item["batch_id"], item["reason"], item["attempts"]), (b + ".a.b.a", "parse", 8))
        self.assertEqual(result.report["counts"]["followup_requests"], 6)

    def test_context_overflow_halves_after_one_attempt(self) -> None:
        doc = document(10)
        self.h.max_targets = 9  # 服务对 10 条的原批次回 HTTP 400（超出 context）
        result = self.h.translate(doc)
        self.assertEqual(result.untranslated_count, 0)
        self.assertEqual([len(t) for t in self.targets()], [10, 5, 5])  # 原批次不换 seed 重试，两个半批各一次
        node = self.lines(doc, "batches.jsonl")[0]["resolution"]["nodes"][0]
        self.assertEqual((node["error_kind"], node["attempts"]), ("context", 1))

    def test_resume_reuses_recorded_nodes(self) -> None:
        doc = document(10)
        ids = [cue.id for cue in doc.cues]
        self.h.poison = {ids[3]}
        # 原批次 2 次、.a 2 次、.a.a 1 次之后，在 .a.b 的第二次请求里中断。
        self.h.plans = [{7: KeyboardInterrupt()}]
        with self.assertRaises(KeyboardInterrupt):
            self.h.translate(doc)
        self.assertEqual([r["batch_id"].rsplit("-", 1)[1] for r in self.lines(doc, "nodes.jsonl")],
                         ["b0001", "b0001.a", "b0001.a.a"])
        self.assertEqual(self.lines(doc, "batches.jsonl"), [])
        with (self.root(doc) / "nodes.jsonl").open("ab") as stream:
            stream.write(b'{"parent_index": 0, "batch_id": "tor')  # 写了一半的一行：截掉
        self.h.requests.clear()
        result = self.h.translate(doc)
        self.assertEqual(result.untranslated_count, 1)
        self.assertEqual(self.targets(), [ids[3:5]] * 2 + [[ids[3]]] * 2 + [[ids[4]], ids[5:10]])
        row = self.lines(doc, "batches.jsonl")[0]
        self.assertEqual([n["session"] for n in row["resolution"]["nodes"]], [1, 1, 1, 2, 2, 2, 2])
        self.assertEqual(row["session"], 2)

    def test_untranslated_is_terminal_for_recipe_and_seed(self) -> None:
        doc = document(12)
        ids = [cue.id for cue in doc.cues]
        self.h.empty = {ids[3]: 99}
        first = self.h.translate(doc)
        self.h.empty = {}
        self.h.events.clear()
        self.h.requests.clear()
        again = self.h.translate(doc)  # 同配方同 seed 同注入行：不启动 Strata、不再尝试
        self.assertEqual((again.untranslated_count, again.translations), (1, first.translations))
        self.assertEqual((self.h.events, self.h.requests), ([], []))
        self.assertEqual(again.report["untranslated"], first.report["untranslated"])
        # 改 seed 即另一个 run，未翻译的 cue 重新翻译。
        self.h.config.translate.seed = SEED + 1
        retried = self.h.translate(doc)
        self.assertEqual(retried.untranslated_count, 0)
        self.assertEqual(retried.translations[ids[3]], "译" + ids[3])


class PublishedUntranslatedCountTests(JobCase):
    """编排器 + 真实 `translate_document`（伪 Strata／伪客户端）：未翻译计数进 `published.json` 与控制台汇总，
    未翻译的 cue 在发布的字幕里只有日文一行。"""

    _translate_plan = staticmethod(generate.plan)  # 真实计划：run 目录与 needs_model 由子系统决定

    def _translate_document(self, plan, session, *, relative):
        harness = Harness(self.root)
        harness.poison = {cue.id for cue in plan.document.cues}
        with harness.session() as own:
            return generate.translate_document(plan, own, relative=relative)

    def test_published_record_counts_untranslated_cues(self) -> None:
        self.make_inputs("a.mkv")
        console = io.StringIO()
        summary = self.run_job(console=console)
        self.assertEqual((summary.published, summary.untranslated_cues), (["a.mkv"], 1))
        record = read_json(self.work_dir("a.mkv") / artifacts.PUBLISHED)
        self.assertEqual(record["sources"]["translate_untranslated_cues"], 1)
        self.assertRegex(record["translate_dir"],
                         rf"/{R.RECIPE_NAME}__s{self.config.translate.seed}__n[0-9a-f]{{12}}$")
        report = read_json(self.work_dir("a.mkv") / record["translate_dir"] / "report.json")
        self.assertEqual(report["counts"]["untranslated_cues"], 1)
        self.assertIn("1 untranslated cue(s)", console.getvalue())
        (block,) = Path(record["final"]).read_text(encoding="utf-8").strip().split("\n\n")
        self.assertEqual(len(block.split("\n")), 3)  # 编号、时间、日文一行


if __name__ == "__main__":
    unittest.main()
