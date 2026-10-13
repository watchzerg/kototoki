"""Synthetic sidecar contract checks; no actual subtitles, judges or inference."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from experiments.translation_flow import v2_fluency as fluency


class FluencySidecarTests(unittest.TestCase):
    def setUp(self):
        self.source = {"id": "synthetic-scene", "source_language": "ja", "target_language": "zh-Hans",
                       "context": [{"id": "before", "text": "誰？"}, {"id": "a", "text": "早く。"},
                                   {"id": "b", "text": "出発しよう。"}],
                       "translate_ids": ["before", "a", "b"]}
        self.metadata = {"id": "synthetic-window", "window_id": "synthetic-window",
                         "scene_id": self.source["id"], "work_id": "W01", "category": "anime_series",
                         "split": "screen-a", "selection_type": "representative", "scored_ids": ["a", "b"],
                         "units": [{"id": uid, "score": uid != "before"} for uid in self.source["translate_ids"]]}
        self.delivery = {"status": "delivered", "translations": {"before": "谁？", "a": "快快点。", "b": "出发吧。"}}
        self.alias = "anon-0123456789abcdef"
        self.packet = self.build()

    def build(self, delivery=None, metadata=None, source=None):
        return fluency.build_packet(self.source if source is None else source,
                                    self.metadata if metadata is None else metadata,
                                    self.delivery if delivery is None else delivery,
                                    anonymous_alias=self.alias, source_manifest_sha256="1" * 64)

    def response(self, packet=None):
        p = self.packet if packet is None else packet
        return {"profile": fluency.PROFILE, "window_id": p["window_id"], "candidate_alias": p["candidate_alias"],
                "status": "assessed", "defects": [], "preferences": [], "uncertainties": [],
                "summary_zh": "合成流程检查；不表示真实裁判准确率。"}

    def claim(self):
        return {"ids": ["a"], "type": "grammar", "source_evidence": [{"id": "a", "quote": "早く"}],
                "candidate_evidence": [{"id": "a", "quote": "快快点"}], "reason_zh": "合成的可见重复。",
                "observable_effect_zh": "该重复使短句阅读不顺。"}

    def record(self, alias, seed, *, defects=False, metadata=None):
        p = self.build(metadata=metadata)
        response = self.response(p)
        if defects:
            response["defects"] = [self.claim()]
        return {"candidate_alias": alias, "window_id": p["window_id"], "seed": seed,
                "status": "assessed", "packet": p, "response": response}

    def test_packet_scored_scope_preserved_and_no_readonly_chinese(self):
        self.assertEqual(self.packet["scored_ids"], ["a", "b"])
        self.assertEqual(self.packet["translations"], {"a": "快快点。", "b": "出发吧。"})
        self.assertNotIn("谁？", json.dumps(self.packet, ensure_ascii=False))
        self.assertEqual(self.packet["source_context"], self.source["context"])
        self.assertEqual(self.packet["binding"]["delivery_view_sha256"], fluency.object_hash(self.delivery))
        self.packet["translations"]["a"] = "modified"
        self.assertEqual(self.delivery["translations"]["a"], "快快点。")

    def test_rejects_reference_score_feedback_or_identity_contamination(self):
        for field in ("reference", "naturalness", "semantic", "judge_feedback", "candidate_name"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.build(delivery=dict(self.delivery, **{field: "forbidden"}))
            with self.assertRaises(ValueError):
                self.build(source=dict(self.source, **{field: "forbidden"}))
            packet = dict(self.packet, **{field: "forbidden"})
            with self.assertRaises(ValueError):
                fluency.validate_response(packet, self.response())
        with self.assertRaises(ValueError):
            fluency.build_packet(self.source, self.metadata, self.delivery, anonymous_alias="F7-style",
                                 source_manifest_sha256="1" * 64)

    def test_rejects_window_scene_id_score_order_and_flag_drift(self):
        for field, value in (("scene_id", "other"), ("window_id", "other"), ("scored_ids", ["b", "a"]),
                             ("scored_ids", ["a", "a"]), ("scored_ids", ["unknown"])):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.build(metadata=dict(self.metadata, **{field: value}))
        metadata = deepcopy(self.metadata)
        metadata["units"][0]["score"] = True
        with self.assertRaises(ValueError):
            self.build(metadata=metadata)

    def test_nonexecution_missing_and_mapping_failures_remain_unknown(self):
        for status in ("not_run", "translation_failed", "mapping_unjudgeable"):
            with self.subTest(status=status), self.assertRaises(LookupError):
                self.build(delivery={"status": status, "reason": "合成失败"})
        with self.assertRaises(LookupError):
            self.build(delivery={"status": "delivered", "translations": {"a": "快点。"}})

    def test_native_unit_mapping_cannot_change_or_copy_joint_text(self):
        delivery = deepcopy(self.delivery)
        delivery["semantic_plan"] = {"units": [{"id": "u0", "source_ids": ["before"],
                                               "evidence_ids": ["before"], "uncertain": False},
                                              {"id": "u1", "source_ids": ["a", "b"],
                                               "evidence_ids": ["a", "b"], "uncertain": False}]}
        delivery["native_unit_translations"] = {"u0": "谁？", "u1": "快快点。出发吧。"}
        delivery["source_span_to_target_span"] = [{"unit_id": "u0", "source_ids": ["before"], "target_spans": [[0, 2]]},
                                                   {"unit_id": "u1", "source_ids": ["a"], "target_spans": [[0, 4]]},
                                                   {"unit_id": "u1", "source_ids": ["b"], "target_spans": [[4, 8]]}]
        self.assertEqual(self.build(delivery)["translations"], self.packet["translations"])
        changed = deepcopy(delivery)
        changed["translations"]["a"] = "快快点！"
        with self.assertRaises(ValueError):
            self.build(changed)
        changed = deepcopy(delivery)
        changed["source_span_to_target_span"][2]["target_spans"] = [[0, 8]]
        with self.assertRaises(ValueError):
            self.build(changed)
        changed = deepcopy(delivery)
        del changed["native_unit_translations"]
        with self.assertRaises(ValueError):
            self.build(changed)

    def grouped(self):
        mapping = [{"group_id": "g0", "source_ids": ["before"], "scored": False,
                    "target_spans": [[0, 2]], "text": "谁？"},
                   {"group_id": "g1", "source_ids": ["a", "b"], "scored": True,
                    "target_spans": [[2, 10]], "text": "快快点。出发吧。"}]
        projection = [{k: mapping[1][k] for k in ("source_ids", "text", "target_spans")}]
        return {"status": "delivered", "native_text": "谁？快快点。出发吧。", "mapping_groups": mapping,
                "translation_groups": projection,
                "source_span_to_target_span": [{k: g[k] for k in ("group_id", "source_ids", "scored", "target_spans")}
                                                for g in mapping]}

    def test_group_shared_scope_preserves_native_text_without_false_cue_alignment(self):
        packet = self.build(self.grouped())
        self.assertEqual(packet["translations"], {})
        self.assertEqual(packet["translation_groups"][0]["source_ids"], ["a", "b"])
        self.assertNotIn("谁？", json.dumps(packet, ensure_ascii=False))
        result = self.response(packet)
        result["defects"] = [self.claim()]
        self.assertEqual(fluency.validate_response(packet, result), result)
        changed = self.grouped()
        changed["native_text"] = "谁？快点。出发吧。"
        with self.assertRaises(ValueError):
            self.build(changed)
        packet["translation_groups"][0]["source_ids"] = ["b", "a"]
        with self.assertRaises(ValueError):
            fluency.validate_packet(packet)

    def test_faithful_alternatives_do_not_need_invented_defects(self):
        for wording in ("快点。", "赶快。", "快些。"):
            delivery = deepcopy(self.delivery)
            delivery["translations"]["a"] = wording
            packet = self.build(delivery)
            result = self.response(packet)
            self.assertEqual(fluency.validate_response(packet, result)["defects"], [])
        self.assertIn("equally faithful Chinese alternatives", fluency.PROMPT)
        self.assertIn("Do not invent defects", fluency.PROMPT)

    def test_strict_exact_quotes_per_id_no_fuzzy_or_cross_id_matching(self):
        result = self.response()
        result["defects"] = [self.claim()]
        self.assertEqual(fluency.validate_response(self.packet, json.dumps(result, ensure_ascii=False)), result)
        for location, value in (("source_evidence", [{"id": "a", "quote": "早い"}]),
                                ("candidate_evidence", [{"id": "a", "quote": "出发吧"}]),
                                ("candidate_evidence", [{"id": "before", "quote": "谁"}]),
                                ("candidate_evidence", [{"id": "a", "quote": " "}])):
            bad = deepcopy(result)
            bad["defects"][0][location] = value
            with self.subTest(location=location, value=value), self.assertRaises(ValueError):
                fluency.validate_response(self.packet, bad)
        bad = deepcopy(result)
        bad["defects"][0]["ids"] = ["a", "b"]
        with self.assertRaises(ValueError):
            fluency.validate_response(self.packet, bad)

    def test_no_score_winner_fields_or_duplicate_json_claims(self):
        for field in ("semantic", "naturalness", "winner", "quality_score"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                fluency.validate_response(self.packet, dict(self.response(), **{field: 4}))
        result = self.response()
        result["defects"] = [self.claim(), self.claim()]
        with self.assertRaises(ValueError):
            fluency.validate_response(self.packet, result)
        content = json.dumps(self.response()).replace('"defects": []', '"defects": [], "defects": []')
        with self.assertRaises(ValueError):
            fluency.validate_response(self.packet, content)

    def test_preference_stays_separate_and_cannot_duplicate_defect(self):
        result = self.response()
        preference = {k: v for k, v in self.claim().items() if k not in {"type", "observable_effect_zh"}}
        result["preferences"] = [preference]
        self.assertEqual(fluency.validate_response(self.packet, result)["defects"], [])
        result["defects"] = [self.claim()]
        with self.assertRaises(ValueError):
            fluency.validate_response(self.packet, result)

    def test_partial_supported_findings_do_not_erase_unknown(self):
        result = self.response()
        result["status"] = "unknown"
        result["defects"] = [self.claim()]
        result["uncertainties"] = [{"ids": ["b"], "reason_zh": "源范围不足，保留未知。"}]
        checked = fluency.validate_response(self.packet, result)
        self.assertEqual(checked["status"], "unknown")
        self.assertEqual(len(checked["defects"]), 1)
        result["status"] = "assessed"
        with self.assertRaises(ValueError):
            fluency.validate_response(self.packet, result)

    def test_paired_coverage_keeps_three_seed_denominator_and_unknown(self):
        records = [self.record("C0", fluency.SEEDS[0], defects=True), self.record("F7", fluency.SEEDS[0]),
                   {"candidate_alias": "F7", "window_id": self.metadata["id"], "seed": fluency.SEEDS[1],
                    "status": "unresolved", "reason_zh": "合成未决"}]
        summary = fluency.aggregate_paired([self.metadata], records, baseline_alias="C0", candidate_alias="F7")
        self.assertEqual(summary["expected_pairs"], 3)
        self.assertEqual(summary["expected_candidate_records"], 6)
        self.assertEqual(summary["missing_record_count"], 3)
        table = next(r["counts"] for r in summary["tables"] if r["scope"] == ["stratum", "representative"])
        self.assertEqual(table["known_pairs"], 1)
        self.assertEqual(table["unknown_pairs"], 2)
        self.assertEqual(table["baseline_only_present"], 1)
        self.assertEqual(table["candidate_unknown"], 2)
        self.assertFalse(summary["seed_replicates_are_independent_samples"])
        self.assertNotIn("winner", summary)

    def test_risk_stratum_never_pooled_as_representative_quality(self):
        risk = deepcopy(self.metadata)
        risk.update(id="risk-window", window_id="risk-window", selection_type="risk")
        records = [self.record("C0", s, defects=True, metadata=risk) for s in fluency.SEEDS]
        records += [self.record("F7", s, metadata=risk) for s in fluency.SEEDS]
        summary = fluency.aggregate_paired([self.metadata, risk], records, baseline_alias="C0", candidate_alias="F7")
        tables = {tuple(r["scope"]): r["counts"] for r in summary["tables"]}
        self.assertEqual(tables[("stratum", "representative")]["unknown_pairs"], 3)
        self.assertEqual(tables[("stratum", "risk")]["known_pairs"], 3)
        self.assertNotIn(("overall",), tables)

    def test_aggregate_rejects_unregistered_seed_duplicate_provisional_and_drift(self):
        record = self.record("C0", fluency.SEEDS[0])
        cases = [[record, record], [dict(record, seed=0)], [dict(record, seed=True)],
                 [dict(record, status="primary_provisional")], [dict(record, candidate_alias="other")]]
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                fluency.aggregate_paired([self.metadata], rows, baseline_alias="C0", candidate_alias="F7")
        bad = deepcopy(record)
        bad["packet"]["binding"]["window_metadata_sha256"] = "2" * 64
        with self.assertRaises(ValueError):
            fluency.aggregate_paired([self.metadata], [bad], baseline_alias="C0", candidate_alias="F7")
        candidate = self.record("F7", fluency.SEEDS[0])
        candidate["packet"]["binding"]["source_view_sha256"] = "3" * 64
        with self.assertRaises(ValueError):
            fluency.aggregate_paired([self.metadata], [record, candidate], baseline_alias="C0", candidate_alias="F7")

    def calibration(self):
        windows = []
        for index in range(16):
            windows.append(dict(self.metadata, id=f"w{index}", window_id=f"w{index}", work_id=f"W{index % 10}",
                                selection_type="representative" if index % 2 else "risk"))
        return {"windows": windows}, {"window_ids": [r["id"] for r in windows], "count": 16}

    def test_calibration_reuses_fixed_ids_and_binds_only_source_metadata(self):
        manifest, selection = self.calibration()
        binding = fluency.bind_calibration(manifest, selection, source_manifest_sha256="1" * 64,
                                          selection_sha256="2" * 64)
        self.assertEqual(binding["window_ids"], selection["window_ids"])
        self.assertEqual(binding["independent_source_windows"], 16)
        self.assertEqual(binding["expected_judgments"], 48)
        self.assertEqual(binding["generation_seed"], 20261008)
        self.assertFalse(binding["quality_based_selection"])
        self.assertNotIn("units", json.dumps(binding))
        self.assertEqual(binding, fluency.bind_calibration(manifest, selection, source_manifest_sha256="1" * 64,
                                                         selection_sha256="2" * 64))

    def test_calibration_rejects_confirmation_duplicate_wrong_count_and_missing_work(self):
        manifest, selection = self.calibration()
        for bad in (dict(selection, count=15), dict(selection, window_ids=selection["window_ids"][:-1]),
                    dict(selection, window_ids=["w0"] * 16)):
            with self.assertRaises(ValueError):
                fluency.bind_calibration(manifest, bad, source_manifest_sha256="1" * 64, selection_sha256="2" * 64)
        for update in ({"split": "confirmation"}, {"work_id": "W0"}):
            bad = deepcopy(manifest)
            for row in bad["windows"]:
                row.update(update)
            with self.assertRaises(ValueError):
                fluency.bind_calibration(bad, selection, source_manifest_sha256="1" * 64, selection_sha256="2" * 64)

    def test_bundle_is_offline_immutable_custom_schema_and_same_isolation_command(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "中文 路径"
            binding = fluency.export_bundle(self.packet, root)
            self.assertFalse(binding["automatic_dispatch"])
            self.assertEqual(binding["requested_model"], "gpt-6.1-sol")
            self.assertEqual(binding["requested_effort"], "high")
            self.assertEqual(binding["global_cli_limit"], 6)
            schema = json.loads((root / "schema.json").read_text(encoding="utf-8"))
            self.assertFalse(schema["additionalProperties"])
            self.assertNotIn("semantic", schema["properties"])
            command = fluency.fresh_cli_command("codex.cmd", Path(temp), root, root / "raw-response.json")
            self.assertIn("--ephemeral", command)
            self.assertIn("--ignore-user-config", command)
            self.assertIn(str(root / "schema.json"), command)
            with self.assertRaises(FileExistsError):
                fluency.export_bundle(self.packet, root)


if __name__ == "__main__":
    unittest.main()
