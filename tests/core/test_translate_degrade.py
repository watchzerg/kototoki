"""翻译降级伪客户端测试（票据 09）：三级降级、单条回退、超出 context 进入降级、续跑识别已降级的节点与批次、
回退终态、改 seed 重试、降级中途的基础设施失败、`report.json`／`scene.json` 内容，以及经编排器写进
`published.json` 的回退计数。不启动 llama-server，不占 GPU。"""

from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import types
from typing import Any
import unittest
from unittest import mock

from kototoki import artifacts
from kototoki.artifacts import read_json
from kototoki.translate import generate
from kototoki.translate import recipes as R
from kototoki.translate.batching import build_batches, scene_from_document
from kototoki.translate.degrade import children
from tests.core.test_job import JobCase
from tests.core.test_translate import SEED, Harness, document


class DegradeTests(unittest.TestCase):
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
            prompt = "".join(chr(t) for t in request["prompt"])
            target, _ = json.JSONDecoder().raw_decode(prompt.split("【待译 JSON】\n", 1)[1])
            result.append(list(target["translations"]))
        return result

    def test_children_split_halves_then_singles_with_the_batch_neighbour_rule(self) -> None:
        scene = scene_from_document(document(23))
        ids = scene.ids
        batch = build_batches(scene, R.PRODUCT)[1]  # ids[10:20]；与前一批之间隔 20 s，前邻不可见
        self.assertEqual((batch.before_ids, batch.after_ids), ((), ()))
        a, b = children(scene, batch, 0, R.PRODUCT)
        self.assertEqual((a.batch_id, b.batch_id), (batch.batch_id + ".a", batch.batch_id + ".b"))
        self.assertEqual((a.target_ids, a.before_ids, a.after_ids), (tuple(ids[10:15]), (), (ids[15],)))
        self.assertEqual((b.target_ids, b.before_ids, b.after_ids), (tuple(ids[15:20]), (ids[14],), ()))
        singles = children(scene, a, 1, R.PRODUCT)
        self.assertEqual([s.batch_id for s in singles], [f"{a.batch_id}.{n}" for n in range(1, 6)])
        self.assertEqual((singles[0].before_ids, singles[0].target_ids, singles[0].after_ids),
                         ((), (ids[10],), (ids[11],)))
        self.assertEqual((singles[1].before_ids, singles[1].target_ids, singles[1].after_ids),
                         ((ids[10],), (ids[11],), (ids[12],)))
        self.assertEqual(children(scene, singles[0], 2, R.PRODUCT), [])
        last = build_batches(scene, R.PRODUCT)[2]  # 3 条：前半 2 条
        self.assertEqual([len(c.target_ids) for c in children(scene, last, 0, R.PRODUCT)], [2, 1])
        self.assertEqual(children(scene, last, 0, R.PRODUCT)[1].after_ids, ())
        # dp10-cut 的批次不一定满 10 条：7 条拆成 4＋3。
        scene = scene_from_document(document(7))
        (batch,) = build_batches(scene, R.PRODUCT)
        self.assertEqual([len(c.target_ids) for c in children(scene, batch, 0, R.PRODUCT)], [4, 3])

    def test_three_level_degrade_and_single_fallback(self) -> None:
        doc = document(12)
        ids = [cue.id for cue in doc.cues]
        self.h.poison = {ids[3]}
        result = self.h.translate(doc)
        self.assertEqual(result.fallback_count, 1)
        self.assertEqual(result.translations[ids[3]], doc.cues[3].text)  # 回退 = 日文原文
        self.assertEqual({k: v for k, v in result.translations.items() if k != ids[3]},
                         {k: "译" + k for k in ids if k != ids[3]})
        # 原批次 2 次、.a 2 次、.a.1–.a.5（.a.4 两次）、.b 1 次，然后第 1 批。
        self.assertEqual(self.targets(), [ids[0:10]] * 2 + [ids[0:5]] * 2
                         + [[ids[0]], [ids[1]], [ids[2]], [ids[3]], [ids[3]], [ids[4]], ids[5:10], ids[10:12]])
        self.assertEqual(self.h.events, ["start:1", "stop:1"])  # 终态失败不重启 server
        # 子批次请求与按冻结配方构造的请求逐字节相同（同一 seed）。
        scene = scene_from_document(doc)
        half = children(scene, build_batches(scene, R.PRODUCT)[0], 0, R.PRODUCT)[1]
        window = half.to_window(scene)
        prompt = R.render_translation(window)
        expected = R.completion_request([ord(ch) for ch in prompt], SEED, R.translation_grammar(window["translate_ids"]))
        self.assertEqual(json.dumps(self.h.requests[10], ensure_ascii=False), json.dumps(expected, ensure_ascii=False))

        row = self.lines(doc, "batches.jsonl")[0]
        b = row["batch_id"]
        self.assertEqual([(n["batch_id"], n["level"], n["status"]) for n in row["degrade"]["nodes"]],
                         [(b, 0, "failed"), (b + ".a", 1, "failed")]
                         + [(f"{b}.a.{n}", 2, "failed" if n == 4 else "accepted") for n in range(1, 6)]
                         + [(b + ".b", 1, "accepted")])
        self.assertEqual(row["degrade"]["fallback"],
                         [{"id": ids[3], "batch_id": b + ".a.4", "reason": "parse",
                           "error": row["degrade"]["nodes"][5]["request"]["attempts"][-1]["error"], "attempts": 6}])
        self.assertNotIn("request", row)  # 原批次请求只记在 nodes[0]
        self.assertNotIn("degrade", self.lines(doc, "batches.jsonl")[1])

        report = read_json(self.root(doc) / "report.json")
        self.assertEqual(report, result.report)
        self.assertEqual(report["counts"], {"batches": 2, "degraded_batches": 1, "fallback_cues": 1,
                                            "degrade_requests": 7})
        (degraded,) = report["degraded_batches"]
        self.assertEqual((degraded["batch_id"], degraded["requests"], degraded["attempts"], degraded["fallback_ids"]),
                         (b, 8, 11, [ids[3]]))
        self.assertEqual([item["id"] for item in report["fallback"]], [ids[3]])
        self.assertEqual(report["completion"]["state"], "complete")
        scene_json = read_json(self.root(doc) / "scene.json")
        self.assertEqual(scene_json["fallback_ids"], [ids[3]])
        self.assertEqual(scene_json["degradation"][0]["batch_id"], b)
        self.assertEqual(scene_json["totals"]["requests"], 9)
        self.assertEqual(scene_json["totals"]["attempts"], 12)

    def test_degrade_and_fallback_log_warnings(self) -> None:
        doc = document(12)
        ids = [cue.id for cue in doc.cues]
        self.h.poison = {ids[3]}
        with self.assertLogs("kototoki.translate", level="INFO") as logs:
            self.h.translate(doc)
        b = self.lines(doc, "batches.jsonl")[0]["batch_id"]
        warnings = [r.getMessage() for r in logs.records if r.levelname == "WARNING"]
        self.assertEqual(warnings, [f"[translate] batch {b} failed (parse) at level 0; splitting into 2 sub-batch(es)",
                                    f"[translate] batch {b}.a failed (parse) at level 1; splitting into 5 sub-batch(es)",
                                    f"[translate] batch {b}: 1 cue(s) kept in Japanese (fallback)"])
        self.assertIn("[translate] batch 1/2: 10 cue(s), 12 tok, cache 5, degraded (8 request(s), 1 fallback)",
                      [r.getMessage() for r in logs.records])

    def test_single_cue_batch_falls_back_without_splitting(self) -> None:
        doc = document(11)
        ids = [cue.id for cue in doc.cues]
        self.h.poison = {ids[10]}
        result = self.h.translate(doc)
        self.assertEqual(result.fallback_count, 1)
        self.assertEqual(self.targets()[1:], [[ids[10]], [ids[10]]])
        row = self.lines(doc, "batches.jsonl")[1]
        self.assertEqual([n["batch_id"] for n in row["degrade"]["nodes"]], [row["batch_id"]])
        self.assertEqual(row["degrade"]["fallback"][0]["batch_id"], row["batch_id"])

    def test_context_overflow_degrades_after_one_attempt(self) -> None:
        doc = document(10)
        scene = scene_from_document(doc)
        full = len(R.render_translation(build_batches(scene, R.PRODUCT)[0].to_window(scene)))
        with mock.patch.object(R, "MAX_INPUT_TOKENS", full - 1):
            result = self.h.translate(doc)
        self.assertEqual(result.fallback_count, 0)
        self.assertEqual(len(self.h.requests), 2)  # 原批次未发出 completion；两个半批各一次
        node = self.lines(doc, "batches.jsonl")[0]["degrade"]["nodes"][0]
        self.assertEqual((node["error_kind"], node["attempts"]), ("context", 1))

    def test_resume_reuses_recorded_degrade_nodes(self) -> None:
        doc = document(10)
        ids = [cue.id for cue in doc.cues]
        self.h.poison = {ids[3]}
        # 原批次 2 次、.a 2 次、.a.1 1 次之后，在 .a.2 的请求里中断。
        self.h.plans = [{6: KeyboardInterrupt()}]
        with self.assertRaises(KeyboardInterrupt):
            self.h.translate(doc)
        self.assertEqual([r["batch_id"].rsplit("-", 1)[1] for r in self.lines(doc, "degrade.jsonl")],
                         ["b0001", "b0001.a", "b0001.a.1"])
        self.assertEqual(self.lines(doc, "batches.jsonl"), [])
        with (self.root(doc) / "degrade.jsonl").open("ab") as stream:
            stream.write(b'{"parent_index": 0, "batch_id": "tor')  # 写了一半的一行：截掉
        self.h.requests.clear()
        result = self.h.translate(doc)
        self.assertEqual(result.fallback_count, 1)
        self.assertEqual(self.targets(), [[ids[1]], [ids[2]], [ids[3]], [ids[3]], [ids[4]], ids[5:10]])
        row = self.lines(doc, "batches.jsonl")[0]
        self.assertEqual([n["session"] for n in row["degrade"]["nodes"]], [1, 1, 1, 2, 2, 2, 2, 2])
        self.assertEqual(row["session"], 2)

    def test_infra_failure_during_degrade_restarts_and_continues(self) -> None:
        doc = document(10)
        ids = [cue.id for cue in doc.cues]
        self.h.poison = {ids[3]}
        self.h.plans = [{5: "oom"}]  # .a.1 的请求 OOM
        result = self.h.translate(doc)
        self.assertEqual(result.fallback_count, 1)
        self.assertEqual(self.h.events, ["start:1", "stop:1", "start:2", "stop:2"])
        self.assertEqual(self.targets()[4:6], [[ids[0]], [ids[0]]])  # OOM 后只重做 .a.1
        run = read_json(self.root(doc) / "run.json")
        self.assertEqual([s["stop_reason"] for s in run["sessions"]], ["oom", None])
        self.assertTrue(run["resumed"])
        self.assertEqual(len(list((self.root(doc) / "infra-failures").glob("*.a.1--session-01.json"))), 1)

    def test_infra_failure_on_the_original_batch_is_not_degraded(self) -> None:
        doc = document(10)
        self.h.plans = [{1: "oom"}]
        result = self.h.translate(doc)
        self.assertEqual(result.fallback_count, 0)
        self.assertEqual(self.lines(doc, "degrade.jsonl"), [])
        self.assertNotIn("degrade", self.lines(doc, "batches.jsonl")[0])
        self.assertEqual(self.h.events, ["start:1", "stop:1", "start:2", "stop:2"])

    def test_recorded_single_failure_is_rebuilt_as_fallback_on_resume(self) -> None:
        doc = document(10)
        ids = [cue.id for cue in doc.cues]
        self.h.poison = {ids[3]}
        # .a.4 第二次失败已记录后，在 .a.5 的请求里中断。
        self.h.plans = [{10: KeyboardInterrupt()}]
        with self.assertRaises(KeyboardInterrupt):
            self.h.translate(doc)
        self.assertEqual(self.lines(doc, "degrade.jsonl")[-1]["batch_id"].rsplit(".", 1)[1], "4")
        self.h.requests.clear()
        result = self.h.translate(doc)
        self.assertEqual(self.targets(), [[ids[4]], ids[5:10]])
        self.assertEqual(result.fallback_count, 1)
        self.assertEqual(result.report["fallback"][0]["attempts"], 6)

    def test_fallback_is_terminal_for_recipe_and_seed(self) -> None:
        doc = document(12)
        ids = [cue.id for cue in doc.cues]
        self.h.poison = {ids[3]}
        first = self.h.translate(doc)
        self.h.poison = set()
        self.h.events.clear()
        self.h.requests.clear()
        again = self.h.translate(doc)  # 同配方同 seed：不启动 server、不再尝试
        self.assertEqual((again.fallback_count, again.translations), (1, first.translations))
        self.assertEqual((self.h.events, self.h.requests), ([], []))
        self.assertEqual(again.report["fallback"], first.report["fallback"])
        # 改 seed 即另一个 run，回退的 cue 重新翻译。
        self.h.config.translate.seed = SEED + 1
        retried = self.h.translate(doc)
        self.assertEqual(retried.fallback_count, 0)
        self.assertEqual(retried.translations[ids[3]], "译" + ids[3])

    def test_empty_scene_writes_an_empty_report(self) -> None:
        doc = document(0)
        result = self.h.translate(doc)
        self.assertEqual(result.fallback_count, 0)
        self.assertEqual(read_json(self.root(doc) / "report.json")["counts"]["fallback_cues"], 0)

    def test_degrade_journal_row_outside_the_plan_is_rejected(self) -> None:
        doc = document(12)
        self.h.translate(doc)
        root = self.root(doc)
        (root / "batches.jsonl").write_bytes((root / "batches.jsonl").read_bytes().splitlines(keepends=True)[0])
        (root / "degrade.jsonl").write_text(json.dumps({"parent_index": 1, "batch_id": "other-b0009.a"}) + "\n",
                                            encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "degrade row"):
            self.h.translate(doc)


class PublishedFallbackCountTests(JobCase):
    """编排器 + 真实 `translate_document`（伪 server／伪客户端）：回退计数进 `published.json` 与控制台汇总。"""

    _translate_plan = staticmethod(generate.plan)  # 真实计划：run 目录与 needs_model 由子系统决定

    def _translate_document(self, plan, session):
        harness = Harness(self.root)
        harness.poison = {cue.id for cue in plan.document.cues}
        with harness.session() as own:
            return generate.translate_document(plan, own)

    def test_published_record_counts_fallback_cues(self) -> None:
        self.make_inputs("a.mkv")
        console = io.StringIO()
        summary = self.run_job(console=console)
        self.assertEqual((summary.published, summary.fallback_cues), (["a.mkv"], 1))
        record = artifacts.read_published(self.work_dir("a.mkv"))
        self.assertEqual(record["sources"]["translate_fallback_cues"], 1)
        self.assertTrue(record["translate_dir"].endswith(f"/{R.PRODUCT.name}__s{self.config.translate.seed}"))
        report = read_json(self.work_dir("a.mkv") / record["translate_dir"] / "report.json")
        self.assertEqual(report["counts"]["fallback_cues"], 1)
        self.assertIn("1 fallback cue(s)", console.getvalue())


if __name__ == "__main__":
    unittest.main()
