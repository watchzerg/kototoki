"""Synthetic source selection, retained-byte binding and auxiliary evidence tests."""

from copy import deepcopy
import hashlib
import json
import unittest

from . import v2_unit_diagnostics as diag
from .v2_prepare import pack_scene
from .v2_semantic import parse_mapping


def artifact(name, value, *, lines=False):
    if type(value) is bytes:
        content = value
    elif lines:
        content = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in value).encode("utf-8")
    else:
        content = json.dumps(value, ensure_ascii=False).encode("utf-8")
    return {"identity": {"path": f"retained/{name}", "sha256": hashlib.sha256(content).hexdigest()}, "content": content}


class UnitDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.ids = [f"s{i}" for i in range(1, 10)]
        self.scene = {"id": "scene", "scene_id": "scene", "source_language": "ja", "target_language": "zh-Hans",
            "context": [{"id": uid, "text": f"仮の台詞{i}。", "start": i, "end": i + .5}
                        for i, uid in enumerate(self.ids, 1)], "translate_ids": self.ids}
        self.authority = {key: artifact(key, key.encode())["identity"] for key in ("manifest", "scenes", "freeze")}
        units = [{"id": uid, "ja_srt_index": i, "start_ms": i * 1000, "end_ms": i * 1000 + 500,
                  "source_events": {"ja": [{"Dialogue序号": i}], "zh": []}}
                 for i, uid in enumerate(self.ids, 1)]
        self.windows = [{"id": f"w{i}", "scene_id": "scene", "scored_ids": ["s2"] if i % 2 == 0 else ["s3", "s4"],
            "split": "screen-a", "selection_type": "representative" if i < 36 else "risk",
            "work": "synthetic-work", "category": "anime_series", "series_cluster": "synthetic-series",
            "units": [{**u, "score": u["id"] in (["s2"] if i % 2 == 0 else ["s3", "s4"])} for u in units]}
            for i in range(48)]
        self.packed = self.pack(20261008, 3)
        raw = artifact("source-packed.json", self.packed)
        self.frame = diag.freeze_frame(raw["content"], raw["identity"], [w["id"] for w in self.windows],
                                       source_authority=self.authority)
        self.frame_sha = diag.canonical_sha256(self.frame)
        self.batch = self.frame["batches"][0]["batch_id"]

    def pack(self, seed, size):
        _, batches = pack_scene(self.scene, target_size=size, context_before=1, context_after=1)
        return {"schema": "hy30-flow-packed-v2", "split": "screen-a", "scene_ids": ["scene"],
            "source_manifest": self.authority["manifest"], "source_scenes": self.authority["scenes"],
            "seed": seed, "recipe_id": f"synthetic-{seed}", "packing": {"target_size": size},
            "scenes": [deepcopy(self.scene)], "windows": deepcopy(self.windows), "batches": batches}

    def bundle(self, *, seed=20261008, control=False):
        packed = self.pack(seed, 2 if control else 3)
        source = diag._source(packed)
        inputs = [b["producer_input"] for b in source["batches"]]
        input_artifact, packed_artifact = artifact("inputs.jsonl", inputs, lines=True), artifact("packed.json", packed)
        run = {"schema": "hy30-flow-session-v2", "phase": "translation", "lane": "P-flow",
            "recipe": "c0" if control else "semantic-partition", "settings": {"seed": seed},
            "packed_mapping_sha256": packed_artifact["identity"]["sha256"],
            "source_manifest_sha256": self.authority["manifest"]["sha256"],
            "input_sha256": input_artifact["identity"]["sha256"],
            "expected_window_ids": [b["batch_id"] for b in source["batches"]]}
        ledger, results = [], []
        for b in source["batches"]:
            targets = b["source_ids"]
            if control:
                translations = {uid: f"原始控制{uid}。" for uid in targets}
                row = {"window_id": b["batch_id"], "status": "delivered", "scored_ids": targets,
                       "translations": translations}
            else:
                plan = {"units": [{"id": "u1", "source_ids": targets, "evidence_ids": targets, "uncertain": True}]}
                native = {"u1": "甲。\t乙😀丙"}
                segments = [{"unit_id": "u1", "source_id": uid, "start": a, "end": z}
                            for uid, a, z in zip(targets, [0, 3, 5], [3, 5, 6], strict=True)]
                mapping = parse_mapping(json.dumps({"segments": segments}), b["producer_input"], plan, native)
                translations = mapping["translations"]
                row = {"window_id": b["batch_id"], "status": "delivered", "scored_ids": targets,
                       "semantic_plan": plan, "native_unit_translations": native, **mapping}
            ledger.append(row)
            results.append({"id": b["batch_id"], "status": "delivered", "translations": translations})
        return {"packed": packed_artifact, "run": artifact("run.json", run), "inputs": input_artifact,
            "ledger": artifact("ledger.jsonl", ledger, lines=True), "results": artifact("results.jsonl", results, lines=True),
            "schedule": artifact("schedule.jsonl", [], lines=True)}

    def rows(self, bundle, name):
        return [json.loads(line) for line in bundle[name]["content"].decode().splitlines()]

    def replace_rows(self, bundle, name, rows):
        bundle[name] = artifact(name + ".jsonl", rows, lines=True)

    def build(self, retained=None, **kwargs):
        return diag.build_packets(self.frame, expected_frame_sha256=self.frame_sha, batch_id=self.batch,
                                 seed=20261008, retained=retained, **kwargs)

    def response(self, packet, *, errors=None, assessment=None):
        value = {"packet_sha256": diag.canonical_sha256(packet),
            "assessment": assessment or ("assessable" if packet["phase"] == "native_fidelity" else "supported"),
            "reason": "", "errors": errors or []}
        if packet["phase"] == "native_fidelity":
            value["native_semantic"] = 4
        return value

    def error(self):
        return {"root_id": "r1", "group_id": "u1", "source_ids": ["s2"], "severity": "major",
            "source_evidence": [{"source_id": "s2", "quote": "台詞2"}],
            "target_evidence": [{"start": 3, "end": 5, "quote": "乙😀"}], "explanation": "合成测试证据。"}

    def test_source_intersection_dedups_batches_and_freezes_all_seed_slots_before_outputs(self):
        self.assertEqual(len(self.frame["batches"]), 2)
        self.assertEqual(len(self.frame["expected_slots"]), 6)
        self.assertEqual([r["seed"] for r in self.frame["expected_slots"]], [20261008] * 2 + [20261009] * 2 + [20261010] * 2)
        self.assertNotIn("scene-b0003", [b["batch_id"] for b in self.frame["batches"]])
        self.assertEqual(len(self.frame["batches"][0]["intersecting_window_ids"]), 48)
        self.assertFalse(self.frame["primary_endpoint_changed"])
        self.assertFalse(self.frame["new_independent_samples"])

    def test_selection_wrong_counts_duplicates_output_leaks_and_source_times_rejected(self):
        for change in ("subset", "duplicate", "reference", "output", "times", "confirmation"):
            packed, ids = deepcopy(self.packed), [w["id"] for w in self.windows]
            if change == "subset":
                ids.pop()
            elif change == "duplicate":
                ids[-1] = ids[0]
            elif change == "reference":
                packed["scenes"][0]["context"][0]["zh"] = "不可进入源 frame 的参考。"
            elif change == "output":
                packed["native_unit_translations"] = {"u1": "候选译文"}
            elif change == "times":
                packed["scenes"][0]["context"][0]["start"] = 999
            else:
                packed["split"] = "confirmation"
            raw = artifact("changed.json", packed)
            with self.subTest(change=change), self.assertRaises(ValueError):
                diag.freeze_frame(raw["content"], raw["identity"], ids, source_authority=self.authority)

    def test_exact_retained_bytes_seed_source_and_producer_inputs_bound(self):
        bundle = self.bundle()
        for change in ("bytes", "seed", "input", "source", "frame"):
            altered = deepcopy(bundle)
            if change == "bytes":
                altered["ledger"]["content"] += b" "
            elif change == "seed":
                run = json.loads(altered["run"]["content"])
                run["settings"]["seed"] = 20261009
                altered["run"] = artifact("run.json", run)
            elif change == "input":
                inputs = self.rows(altered, "inputs")
                inputs[0]["context"][0]["text"] = "変更された台詞。"
                altered["inputs"] = artifact("inputs.jsonl", inputs, lines=True)
                run = json.loads(altered["run"]["content"])
                run["input_sha256"] = altered["inputs"]["identity"]["sha256"]
                altered["run"] = artifact("run.json", run)
            elif change == "source":
                packed = json.loads(altered["packed"]["content"])
                packed["source_manifest"]["sha256"] = "0" * 64
                altered["packed"] = artifact("packed.json", packed)
            else:
                changed = deepcopy(self.frame)
                changed["selected_window_ids"].reverse()
                with self.assertRaisesRegex(ValueError, "registered pre-quality"):
                    diag.build_packets(changed, expected_frame_sha256=self.frame_sha, batch_id=self.batch, seed=20261008)
                continue
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.build(altered)

    def test_intact_native_uncertainty_separate_mapping_and_cross_window_unknown(self):
        result = self.build(self.bundle())
        native, attribution = result["native_packet"], result["attribution_packet"]
        self.assertEqual(native["output_groups"][0]["text"], "甲。\t乙😀丙")
        self.assertTrue(native["output_groups"][0]["uncertain"])
        self.assertNotIn("mapped_cues", native)
        self.assertEqual("".join(cue["text"] for cue in attribution["mapped_cues"]), native["output_groups"][0]["text"])
        self.assertEqual(attribution["mapped_cues"][1]["target_span"], [3, 5])
        self.assertEqual(attribution["mapped_cues"][1]["start_ms"], 2000)
        self.assertIsNone(result["boundary_diagnostics"][0]["window_native_semantic"])
        self.assertEqual(result["boundary_diagnostics"][0]["window_attribution"], "boundary_unknown")
        self.assertTrue(result["protocol_validated"])
        self.assertFalse(result["actual_native_authenticated"])
        self.assertFalse(result["primary_score_changed"])
        self.assertFalse(result["new_independent_samples"])
        self.assertNotIn('"references"', json.dumps(result))

    def test_all_missing_planning_native_mapping_and_not_run_states_remain_slots(self):
        missing = self.build()
        self.assertEqual(missing["status"], "missing")
        self.assertEqual(missing["expected_source_ids"], ["s1", "s2", "s3"])
        for failure in ("planning", "native", "mapping", "not-run", "empty-native", "delivered-without-native"):
            bundle = self.bundle()
            rows = self.rows(bundle, "ledger")
            row = rows[0]
            results = self.rows(bundle, "results")[1:]
            if failure == "not-run":
                rows = rows[1:]
                self.replace_rows(bundle, "schedule", [{"window_id": self.batch, "status": "not_run", "reason": "合成停止"}])
            else:
                row.update(status="mapping_unjudgeable" if failure == "mapping" else "translation_failed",
                           reason="合成失败", translations={})
                row.pop("source_span_to_target_span")
                if failure == "planning":
                    row.pop("semantic_plan")
                    row.pop("native_unit_translations")
                elif failure == "native":
                    row.pop("native_unit_translations")
                elif failure == "empty-native":
                    row["native_unit_translations"] = {"u1": ""}
                elif failure == "delivered-without-native":
                    row["status"] = "delivered"
                    row.pop("native_unit_translations")
            self.replace_rows(bundle, "ledger", rows)
            self.replace_rows(bundle, "results", results)
            with self.subTest(failure=failure):
                value = self.build(bundle)
                self.assertEqual(value["expected_source_ids"], ["s1", "s2", "s3"])
                self.assertIsNone(value["attribution_packet"])
                self.assertEqual(value["native_packet"] is not None, failure == "mapping")
                self.assertEqual(value["planned_unit_count"], None if failure in ("planning", "not-run") else 1)

    def test_mapping_protocol_failure_keeps_native_without_copying_paragraph_each_cue(self):
        for wrong in ("span", "text", "copy-whole-paragraph"):
            bundle = self.bundle()
            rows, predictions = self.rows(bundle, "ledger"), self.rows(bundle, "results")
            if wrong == "span":
                rows[0]["source_span_to_target_span"][1]["target_spans"] = [[4, 5]]
            else:
                values = {uid: "甲。\t乙😀丙" if wrong == "copy-whole-paragraph" else "被改写" for uid in self.ids[:3]}
                rows[0]["translations"] = values
                predictions[0]["translations"] = values
            self.replace_rows(bundle, "ledger", rows)
            self.replace_rows(bundle, "results", predictions)
            with self.subTest(wrong=wrong):
                value = self.build(bundle)
                self.assertIsNotNone(value["native_packet"])
                self.assertIsNone(value["attribution_packet"])
                self.assertEqual(value["attribution_state"], "invalid_partition_or_final_delivery")

    def test_c0_whole_batch_control_joins_exact_source_ids_across_original_batches(self):
        result = self.build(self.bundle(), c0_retained=self.bundle(control=True))
        control = result["c0_packet"]
        self.assertEqual(control["target_source_ids"], result["native_packet"]["target_source_ids"])
        self.assertEqual([g["source_ids"] for g in control["output_groups"]], [["s1"], ["s2"], ["s3"]])
        self.assertEqual([g["text"] for g in control["output_groups"]], ["原始控制s1。", "原始控制s2。", "原始控制s3。"])
        self.assertTrue(all(g["uncertain"] is None for g in control["output_groups"]))
        self.assertIn("not_joint_generation", result["c0_state"])
        schema = diag.response_schema(control)
        self.assertEqual(set(schema["properties"]), {"packet_sha256", "assessment", "reason", "errors", "native_semantic"})

    def test_incomplete_c0_control_is_not_retranslated_or_partial_batch_grade(self):
        bundle = self.bundle(control=True)
        self.replace_rows(bundle, "results", self.rows(bundle, "results")[1:])
        self.replace_rows(bundle, "ledger", self.rows(bundle, "ledger")[1:])
        result = self.build(self.bundle(), c0_retained=bundle)
        self.assertIsNone(result["c0_packet"])
        self.assertEqual(result["c0_state"], "incomplete_whole_batch_control")

    def test_response_exact_source_quote_codepoint_evidence_and_unknown_preserved(self):
        packet = self.build(self.bundle())["native_packet"]
        value = self.response(packet, errors=[self.error()])
        value["native_semantic"] = 2
        validated = diag.parse_response(json.dumps(value, ensure_ascii=False), packet)
        self.assertTrue(validated["response_protocol_validated"])
        self.assertFalse(validated["semantic_accuracy_verified"])
        unresolved = self.response(packet, assessment="unresolved")
        unresolved.update(native_semantic=None, reason="源范围无法可靠归属。")
        self.assertIsNone(diag.parse_response(json.dumps(unresolved), packet)["native_semantic"])

    def test_duplicate_ids_quotes_roots_and_unicode_offset_errors_rejected_locally(self):
        packet = self.build(self.bundle())["native_packet"]
        original = self.response(packet, errors=[self.error()])
        original["native_semantic"] = 2
        for case in ("root", "source-id", "quote", "source-scope", "UTF16", "span", "score-bool", "packet", "unit-score"):
            value = deepcopy(original)
            error = value["errors"][0]
            if case == "root":
                value["errors"].append(deepcopy(error))
            elif case == "source-id":
                error["source_evidence"].append(deepcopy(error["source_evidence"][0]))
            elif case == "quote":
                error["source_evidence"][0]["quote"] = "未提供的日文。"
            elif case == "source-scope":
                error["source_ids"] = ["s9"]
            elif case == "UTF16":
                error["target_evidence"][0]["end"] = 6
            elif case == "span":
                error["target_evidence"].append(deepcopy(error["target_evidence"][0]))
            elif case == "score-bool":
                value["native_semantic"] = True
            elif case == "packet":
                value["packet_sha256"] = "0" * 64
            else:
                value["unit_scores"] = [{"u1": 4}]
            with self.subTest(case=case), self.assertRaises(ValueError):
                diag.parse_response(json.dumps(value), packet)

    def test_attribution_verdict_requires_evidence_but_never_claims_semantic_pass(self):
        packet = self.build(self.bundle())["attribution_packet"]
        value = self.response(packet, assessment="misattributed", errors=[self.error()])
        result = diag.parse_response(json.dumps(value), packet)
        self.assertNotIn("native_semantic", result)
        self.assertFalse(result["semantic_accuracy_verified"])
        value["errors"] = []
        with self.assertRaisesRegex(ValueError, "evidence"):
            diag.parse_response(json.dumps(value), packet)

    def test_schema_omits_unsupported_uniqueitems_and_sourceevent_zh_is_metadata_only(self):
        packet = self.build(self.bundle())["native_packet"]
        self.assertNotIn("uniqueItems", json.dumps(diag.response_schema(packet)))
        self.assertNotIn("source_events", json.dumps(packet))
        self.assertNotIn("reference", json.dumps(packet))
        bad = '{"packet_sha256":"a","packet_sha256":"b"}'
        with self.assertRaises(ValueError):
            diag.parse_response(bad, packet)

    def test_all_seeds_bind_their_own_packed_bytes_to_same_fixed_source_geometry(self):
        for seed in diag.SEEDS:
            value = diag.build_packets(self.frame, expected_frame_sha256=self.frame_sha, batch_id=self.batch,
                                      seed=seed, retained=self.bundle(seed=seed))
            self.assertEqual(value["native_packet"]["seed"], seed)
        bundle = self.bundle(seed=20261009)
        packed = json.loads(bundle["packed"]["content"])
        packed["seed"] = 20261008
        bundle["packed"] = artifact("packed.json", packed)
        run = json.loads(bundle["run"]["content"])
        run["packed_mapping_sha256"] = bundle["packed"]["identity"]["sha256"]
        bundle["run"] = artifact("run.json", run)
        with self.assertRaisesRegex(ValueError, "run/seed/source"):
            diag.build_packets(self.frame, expected_frame_sha256=self.frame_sha, batch_id=self.batch,
                               seed=20261009, retained=bundle)

    def test_repeated_quotes_backslashes_whitespace_and_nonbmp_remain_exact_data(self):
        bundle = self.bundle()
        rows, predictions = self.rows(bundle, "ledger"), self.rows(bundle, "results")
        text = '甲"\\😀 甲"\\😀！'
        rows[0]["native_unit_translations"] = {"u1": text}
        segments = [{"unit_id": "u1", "source_id": uid, "start": a, "end": z}
                    for uid, a, z in zip(self.ids[:3], [0, 4, 8], [4, 8, len(text)], strict=True)]
        mapping = parse_mapping(json.dumps({"segments": segments}),
            self.frame["batches"][0]["producer_input"], rows[0]["semantic_plan"], {"u1": text})
        rows[0].update(mapping)
        predictions[0]["translations"] = mapping["translations"]
        self.replace_rows(bundle, "ledger", rows)
        self.replace_rows(bundle, "results", predictions)
        value = self.build(bundle)
        self.assertEqual(value["native_packet"]["output_groups"][0]["text"], text)
        self.assertEqual("".join(cue["text"] for cue in value["attribution_packet"]["mapped_cues"]), text)
        error = self.error()
        error["source_ids"] = ["s1"]
        error["source_evidence"] = [{"source_id": "s1", "quote": "台詞1"}]
        error["target_evidence"] = [{"start": 0, "end": 4, "quote": text[:4]}]
        response = self.response(value["native_packet"], errors=[error])
        response["native_semantic"] = 2
        self.assertTrue(diag.parse_response(json.dumps(response, ensure_ascii=False), value["native_packet"])["response_protocol_validated"])

    def test_omission_can_have_no_target_quote_but_misattribution_cannot(self):
        result = self.build(self.bundle())
        error = self.error()
        error["target_evidence"] = []
        native = self.response(result["native_packet"], errors=[error])
        native["native_semantic"] = 2
        diag.parse_response(json.dumps(native), result["native_packet"])
        attribution = self.response(result["attribution_packet"], errors=[error], assessment="misattributed")
        with self.assertRaisesRegex(ValueError, "native text/span"):
            diag.parse_response(json.dumps(attribution), result["attribution_packet"])

    def test_multiple_intact_units_keep_unit_local_offsets_and_never_create_unit_grades(self):
        bundle = self.bundle()
        rows, predictions = self.rows(bundle, "ledger"), self.rows(bundle, "results")
        plan = {"units": [
            {"id": "u1", "source_ids": ["s1", "s2"], "evidence_ids": ["s1", "s2"], "uncertain": True},
            {"id": "u2", "source_ids": ["s3"], "evidence_ids": ["s3"], "uncertain": False}]}
        native = {"u1": "甲乙", "u2": "丙"}
        segments = [{"unit_id": uid, "source_id": sid, "start": a, "end": z}
                    for uid, sid, a, z in [("u1", "s1", 0, 1), ("u1", "s2", 1, 2), ("u2", "s3", 0, 1)]]
        mapping = parse_mapping(json.dumps({"segments": segments}), self.frame["batches"][0]["producer_input"], plan, native)
        rows[0].update(semantic_plan=plan, native_unit_translations=native, **mapping)
        predictions[0]["translations"] = mapping["translations"]
        self.replace_rows(bundle, "ledger", rows)
        self.replace_rows(bundle, "results", predictions)
        result = self.build(bundle)
        self.assertEqual(result["planned_unit_count"], 2)
        self.assertEqual([g["text"] for g in result["native_packet"]["output_groups"]], ["甲乙", "丙"])
        self.assertEqual(result["attribution_packet"]["mapped_cues"][-1]["target_span"], [0, 1])
        error = self.error()
        error.update(group_id="u2", source_ids=["s3"], source_evidence=[{"source_id": "s3", "quote": "台詞3"}],
                     target_evidence=[{"start": 0, "end": 1, "quote": "丙"}])
        response = self.response(result["native_packet"], errors=[error])
        response["native_semantic"] = 2
        diag.parse_response(json.dumps(response), result["native_packet"])
        self.assertNotIn("unit_scores", diag.response_schema(result["native_packet"])["properties"])
        response["errors"][0]["source_ids"] = ["s2"]
        with self.assertRaisesRegex(ValueError, "another candidate-defined source scope"):
            diag.parse_response(json.dumps(response), result["native_packet"])


if __name__ == "__main__":
    unittest.main()
