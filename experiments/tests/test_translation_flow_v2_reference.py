"""Offline configurable reference quotas, provenance, review and sealing tests."""
from pathlib import Path
import tempfile
import unittest

from experiments.translation_corpus import flow_v2_reference as flow
from experiments.translation_corpus import prepare as legacy
from experiments.translation_reference_judge import run_job


class FlowReferenceTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[2] / ".local/testing-flow-reference"
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.temp.name)
        self.mapping = self.root / "mapping.json"
        tracks = {}
        for lang, text in (("ja", "三人です。"), ("zh", "三个人。")):
            tracks[lang] = [{"SRT序号": i, "开始毫秒": i * 1000, "结束毫秒": i * 1000 + 500,
                             "文本": text, "源事件": [{"Dialogue序号": i}], "标记": []} for i in range(1, 10)]
        legacy.write_json(self.mapping, {"语言轨": tracks})
        self.srt = self.root / "source.srt"
        self.srt.write_text("synthetic identity", encoding="utf-8")
        self.source = self.root / "source-manifest.json"
        self.out = self.root / "evaluation-only/reference"
        self.selected = [self.row("w1", 1), self.row("w2", 4)]
        self.reserve = [self.row("w3", 7)]
        legacy.write_json(self.source, {"windows": self.selected, "reserve_windows": self.reserve})
        flow.prepare([self.source], self.out, {"screening|W01|0|screening|representative": 2})

    def tearDown(self):
        self.temp.cleanup()

    def row(self, wid, start, split="screening"):
        units = [{"id": f"{wid}-{i}", "ja_srt_index": i, "zh_srt_index": i, "start": i,
                  "end": i + .5, "source_events": {"ja": [{"Dialogue序号": i}], "zh": [{"Dialogue序号": i}]},
                  "score": i == start + 1} for i in range(start, start + 3)]
        return {"id": wid, "window_id": wid, "scene_id": wid, "work_id": "W01", "work": "synthetic",
                "category": "anime_series", "episode_id": "e1", "source_sha256": "synthetic",
                "source_mapping": str(self.mapping), "source_srt": str(self.srt), "split": split,
                "selection_type": "representative", "selection_group": "screening|W01|0",
                "scored_ids": [f"{wid}-{start + 1}"], "units": units,
                "source_event_keys": [f"synthetic|{lang}|{i}" for lang in ("ja", "zh") for i in range(start, start + 3)]}

    def review(self, wid, exclude=False, edited=False, phase=None):
        rows = {r["id"]: r for r in legacy.read_jsonl(self.out / "staging/selected-candidates.jsonl")}
        row = rows[wid]
        uid = row["scored_ids"][0]
        result = {"window_id": wid, "status": "exclude" if exclude else "edit" if edited else "accept",
                  "translations": {} if exclude else {uid: "共有三个人。" if edited else "三个人。"},
                  "changes": [{"id": uid, "original_zh": "三个人。", "revised_zh": "共有三个人。", "source_evidence": "三人", "reason_zh": "合成修改。"}] if edited else [],
                  "reason_zh": "合成审核。", "diagnostic_tags": ["number"]}
        for job in legacy.read_jsonl(self.out / "review-jobs.jsonl"):
            if job["window_id"] != wid or phase and job["phase"] != phase:
                continue
            def fake(args, prompt, cwd, attempt, timeout):
                legacy.write_json(attempt / "last-message.txt", result)
                return {"returncode": 0, "transport_status": "completed", "elapsed_seconds": .01,
                        "returned_models": [], "returned_efforts": [], "tool_events": [], "usage_events": []}
            run_job(self.out, job, row, "fake", "fake", 1, fake)

    def test_configurable_freeze_and_no_unscored_chinese(self):
        for row in self.selected:
            self.review(row["id"])
        frozen = flow.freeze(self.out)
        self.assertEqual(frozen["windows"], 2)
        self.assertEqual(frozen["scored_ids"], 2)
        self.assertTrue(frozen["confirmation_sealed"])
        safe_source = legacy.read_json(self.out / "source-manifest-screening.json")
        self.assertEqual(safe_source["windows"][0]["source_mapping"], "mapping.json")
        self.assertEqual(safe_source["windows"][0]["source_srt"], "source.srt")
        for ref in legacy.read_jsonl(self.out / "reference/windows.jsonl"):
            self.assertEqual([u["zh"] for u in ref["units"] if u["score"]], ["三个人。"])
            self.assertTrue(all("zh" not in u and u["original_zh"] == "" for u in ref["units"] if not u["score"]))
        for packet in (self.out / "review-packets").glob("*.json"):
            value = legacy.read_json(packet)
            self.assertTrue(all("original_zh" not in u for u in value["context"] if u["id"] not in value["scored_ids"]))
        for request in legacy.read_jsonl(self.out / "model-input/windows.jsonl"):
            self.assertEqual(set(request), {"id", "source_language", "target_language", "context", "translate_ids"})
        with self.assertRaisesRegex(ValueError, "overwritten"):
            flow.freeze(self.out)

    def test_same_group_replacement_preserves_history_and_reject_rate(self):
        self.review("w1", exclude=True)
        self.review("w2")
        self.assertEqual(flow.replace_excluded(self.out)["replaced"], 1)
        self.assertEqual([r["id"] for r in flow.validate(self.out)[1]], ["w3", "w2"])
        self.review("w3")
        rate = flow.freeze(self.out)["rejection_by_group"]["screening|W01|0|screening|representative"]
        self.assertEqual(rate["rejected"], 1)
        self.assertAlmostEqual(rate["rejection_rate"], 1 / 3)
        self.assertTrue((self.out / "reviews/primary/w1.json").exists())

    def test_pending_dispute_and_missing_transport_block_freeze(self):
        self.review("w1", phase="primary")
        self.review("w1", edited=True, phase="review")
        self.assertEqual(flow.reconcile(self.out)["counts"], {"dispute": 1, "pending": 1})
        with self.assertRaisesRegex(ValueError, "incomplete"):
            flow.freeze(self.out)
        path = self.out / "reference-execution/primary/w1/job.json"
        path.unlink()
        with self.assertRaisesRegex(ValueError, "Missing exact-model"):
            flow.reconcile(self.out)

    def test_adjudicated_exclusion_survives_replacement_with_raw_proof(self):
        self.review("w1", phase="primary")
        self.review("w1", edited=True, phase="review")
        self.review("w2")
        flow.reconcile(self.out)
        job = legacy.read_jsonl(self.out / "adjudication-jobs.jsonl")[0]
        row = next(r for r in legacy.read_jsonl(self.out / "staging/selected-candidates.jsonl") if r["id"] == "w1")
        result = {"window_id": "w1", "status": "exclude", "translations": {}, "changes": [],
                  "reason_zh": "合成未决排除。", "diagnostic_tags": [], "resolved": False, "resolution_zh": "无法裁决。"}
        def fake(args, prompt, cwd, attempt, timeout):
            legacy.write_json(attempt / "last-message.txt", result)
            return {"returncode": 0, "transport_status": "completed", "elapsed_seconds": .01,
                    "returned_models": [], "returned_efforts": [], "tool_events": [], "usage_events": []}
        run_job(self.out, job, row, "fake", "fake", 1, fake)
        self.assertEqual(flow.replace_excluded(self.out)["replaced"], 1)
        self.review("w3")
        self.assertEqual(flow.freeze(self.out)["windows"], 2)

    def test_representative_and_risk_reserves_cannot_trade_roles(self):
        source = self.root / "role-source.json"
        selected = [self.row("r1", 1)]
        selected[0].update(split="screen-a", selection_type="risk")
        wrong_role = self.row("r2", 4)
        correct_role = self.row("r3", 7)
        correct_role["selection_type"] = "risk"
        legacy.write_json(source, {"windows": selected, "reserve_windows": [wrong_role, correct_role]})
        self.out = self.root / "role-reference"
        flow.prepare([source], self.out)
        self.review("r1", exclude=True)
        flow.replace_excluded(self.out)
        rows = flow.validate(self.out)[1]
        self.assertEqual(rows[0]["id"], "r3")
        self.assertEqual(rows[0]["selection_type"], "risk")
        self.assertEqual(rows[0]["split"], "screen-a")

    def test_frozen_sources_packets_and_reserves_detect_tampering(self):
        packet = self.out / "review-packets/w1.json"
        value = legacy.read_json(packet)
        value["context"][0]["ja"] = "changed"
        legacy.write_json(packet, value)
        with self.assertRaisesRegex(ValueError, "packet differs"):
            flow.validate(self.out)
        legacy.write_json(packet, legacy.packet(flow.hydrate(self.selected[0])))
        self.srt.write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "external source"):
            flow.validate(self.out)

    def test_cross_split_overlap_rejected_and_quota_shortfall(self):
        rows = [flow.hydrate(self.selected[0]), flow.hydrate({**self.selected[0], "split": "confirmation"})]
        with self.assertRaisesRegex(ValueError, "overlap"):
            flow.check_scope(rows)
        with self.assertRaisesRegex(ValueError, "quotas"):
            flow.prepare([self.source], self.root / "bad", {"screening|W01|0": 3})


if __name__ == "__main__":
    unittest.main()

