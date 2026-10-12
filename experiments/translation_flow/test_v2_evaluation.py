"""Synthetic, offline contract tests; no corpus references or model calls."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from experiments.translation_eval import runner
from . import v2_delivery, v2_evaluation, v2_prepare, v2_reproject


class SceneEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.manifest_path = self.source / "source-manifest.json"
        self.scene_path = self.source / "scenes.jsonl"
        self.input_path = self.source / "windows.jsonl"
        self.reference_root = self.root / "evaluation-only"
        self.reference_path = self.reference_root / "reference" / "windows.jsonl"
        self.freeze_path = self.reference_root / "freeze-manifest.json"
        self.windows, self.scenes, self.inputs, self.refs = [], [], [], []
        for number, sid in enumerate(("scene-a", "scene-b"), 1):
            text = "".join(f"{index}\n00:00:0{index},000 --> 00:00:0{index},500\n台詞{number}-{index}\n\n"
                           for index in range(1, 4))
            source_path = self.source / f"episode-{number}.srt"
            source_path.write_text(text, encoding="utf-8")
            map_path = self.source / f"episode-{number}-events.json"
            runner.dump(map_path, {"源SHA256": "a" * 64, "语言轨": {"ja": [
                {"SRT序号": i, "开始毫秒": i * 1000, "结束毫秒": i * 1000 + 500,
                 "文本": f"台詞{number}-{i}", "源事件": [{"source_line": i, "text_sha256": "a" * 64}]}
                for i in range(1, 4)]}})
            context = [{"id": f"{sid}-J{i}", "text": f"台詞{number}-{i}", "start": float(i), "end": i + .5}
                       for i in range(1, 4)]
            scene = {"id": sid, "context": context, "translate_ids": [cue["id"] for cue in context]}
            self.scenes.append(scene)
            for scored_index in ((1, 2) if number == 1 else (2,)):
                wid = f"{sid}-Q{scored_index}"
                scored = [f"{sid}-J{scored_index}"]
                units = [{"id": cue["id"], "score": cue["id"] in scored, "ja_srt_index": i,
                          "zh_srt_index": i, "start": cue["start"], "end": cue["end"],
                          "start_ms": i * 1000, "end_ms": i * 1000 + 500, "index_text": str(i),
                          "time_line": f"00:00:0{i},000 --> 00:00:0{i},500",
                          "source_events": {"ja": [{"source_line": i, "text_sha256": "a" * 64}]}}
                         for i, cue in enumerate(context, 1)]
                window = {"id": wid, "window_id": wid, "scene_id": sid, "work": "Synthetic shared work",
                          "work_id": "W01", "category": "anime_series", "episode_id": f"episode-{number}",
                          "split": "screen-a", "scored_ids": scored, "units": units,
                          "source_srt": str(source_path), "source_srt_sha256": runner.sha(source_path),
                          "source_mapping": str(map_path), "source_mapping_sha256": runner.sha(map_path),
                          "source_sha256": "a" * 64, "visible_start_index": 1, "visible_end_index": 3}
                self.windows.append(window)
                self.inputs.append({"id": wid, "source_language": "ja", "target_language": "zh-Hans",
                                    "context": [{"id": cue["id"], "text": cue["text"]} for cue in context],
                                    "translate_ids": scored})
                reference_units = [{"id": cue["id"], "ja": cue["text"], "score": cue["id"] in scored,
                                    **({"zh": f"合成参考{i}"} if cue["id"] in scored else {})}
                                   for i, cue in enumerate(context, 1)]
                self.refs.append({"id": wid, "work": window["work"], "category": window["category"],
                                  "scored_ids": scored, "units": reference_units})
        runner.dump(self.manifest_path, {"version": "synthetic-source-v2", "external_corpus": str(self.source),
                                        "windows": self.windows})
        runner.dump_jsonl(self.scene_path, self.scenes)
        runner.dump_jsonl(self.input_path, self.inputs)
        runner.dump_jsonl(self.reference_path, self.refs)
        self.freeze()

    def freeze(self, state="frozen_double_fresh_reference_review"):
        runner.dump(self.freeze_path, {"state": state, "inference_allowed": state == "frozen_double_fresh_reference_review",
                                      "corpus_version": v2_evaluation.REFERENCE_VERSION, "files": [
                                          {"path": "reference/windows.jsonl", "sha256": runner.sha(self.reference_path)}]})

    def delivery(self, name="c01", states=None, scene_ids=None):
        prepared, original, output = (self.root / f"{name}-{suffix}" for suffix in ("prepared", "run", "delivery"))
        artifacts = [{"path": path.name, "sha256": runner.sha(path)}
                     for path in (self.manifest_path, self.scene_path)]
        source_origin = self.source / "original-source-freeze.json"
        runner.dump(source_origin, {"version": v2_prepare.SOURCE_FREEZE_VERSION,
                                   "state": "source_frozen_reference_unreviewed", "role": "screening",
                                   "artifacts": artifacts})
        # The qualified source binds the exact evaluator-owned reference freeze;
        # preparation checks its metadata bytes without loading reference text.
        approval = self.freeze_path
        runner.dump(self.source / "freeze-manifest.json", {"version": v2_prepare.SOURCE_FREEZE_VERSION,
            "state": "source_frozen_reference_qualified", "role": "screening", "artifacts": artifacts,
            "original_source_freeze": {"path": str(source_origin.resolve()), "sha256": runner.sha(source_origin)},
            "reference_qualification": {"path": str(approval.resolve()), "sha256": runner.sha(approval),
                                        "version": "hy30-flow-v2-reference-v1",
                                        "state": "frozen_double_fresh_reference_review", "inference_allowed": True}})
        v2_prepare.prepare(manifest=self.manifest_path, scenes=self.scene_path, output=prepared,
                           split="screen-a", recipe_id="synthetic-c0", target_size=1,
                           selected_scene_ids=scene_ids)
        packed_path = prepared / "packed-mapping.json"
        packed = runner.read_json(packed_path)
        original.mkdir()
        shutil_source = prepared / "inputs.jsonl"
        (original / "inputs.jsonl").write_bytes(shutil_source.read_bytes())
        runner.dump(original / "run.json", {"lane": "P-flow", "source_manifest_sha256": runner.sha(self.manifest_path),
                                            "packed_mapping_sha256": runner.sha(packed_path), "input_sha256": runner.sha(original / "inputs.jsonl"),
                                            "expected_window_ids": [batch["id"] for batch in packed["batches"]], "candidate": "synthetic"})
        results, ledger, schedule = [], [], []
        for batch in packed["batches"]:
            bid, uid = batch["id"], batch["target_ids"][0]
            status = (states or {}).get(uid, "delivered")
            if status == "missing":
                continue
            values = {uid: f"合成译文{uid}"} if status == "delivered" else {}
            if status in {"not_run", "setup_failed"}:
                schedule.append({"window_id": bid, "status": status, "reason": "合成未执行"})
                continue
            results.append({"id": bid, "translations": values, "status": status})
            ledger.append({"window_id": bid, "translations": values, "status": status,
                           "reason": None if status == "delivered" else "合成映射或交付失败"})
        for name, rows in (("results", results), ("ledger", ledger), ("schedule", schedule)):
            runner.dump_jsonl(original / f"{name}.jsonl", rows)
        v2_delivery.deliver(self.manifest_path, packed_path, original, output)
        return output

    def prepare(self, deliveries, **kwargs):
        output = self.root / "evaluation"
        result = v2_evaluation.prepare(self.manifest_path, self.input_path, self.reference_path, deliveries,
                                      output, reference_freeze_path=self.freeze_path, **kwargs)
        return output, result

    def test_multiple_scenes_and_episodes_keep_same_work_and_fixed_scope(self):
        delivery = self.delivery()
        original = (delivery / "results.jsonl").read_bytes()
        output, result = self.prepare({"c01": delivery, "c02": self.delivery("c02")})
        expected = runner.load_jsonl(output / "expected.jsonl")
        self.assertEqual(result["windows"], 3)
        self.assertEqual(result["expected_records"], 6)
        self.assertEqual({row["work"] for row in expected}, {"Synthetic shared work"})
        self.assertEqual({row["scene_id"] for row in expected}, {"scene-a", "scene-b"})
        self.assertEqual(original, (output / "originals/c01/results.jsonl").read_bytes())
        run = runner.read_json(output / "run.json")
        self.assertEqual(run["lane"], "P-flow")
        self.assertEqual(run["p_flow_contract"]["schema"], v2_evaluation.SCENE_CONTRACT)
        self.assertEqual(run["p_flow_contract"]["reference_freeze"]["corpus_version"], v2_evaluation.REFERENCE_VERSION)
        self.assertEqual(run["p_flow_contract"]["source_qualification_freeze"]["sha256"],
                         runner.sha(self.source / "freeze-manifest.json"))
        for row in expected:
            packet = runner.read_json(output / row["packet"])
            self.assertEqual(packet["lane"], "P-flow")
            self.assertEqual(len(packet["context"]), 3)
            self.assertEqual(set(packet["reference"]), set(row["scored_ids"]))
            self.assertEqual(row["delivery_contract"], runner.P_FLOW_CONTRACT)
            self.assertEqual(run["packet_sha256"][row["packet"]], runner.sha(output / row["packet"]))
        runner.finalize(output)
        self.assertEqual(runner.read_json(output / "summary.json")["lane"], "P-flow")

    def test_mapping_unresolved_missing_and_nonexecution_remain_distinct(self):
        delivery = self.delivery(states={"scene-a-J1": "mapping_unjudgeable", "scene-a-J2": "missing", "scene-b-J2": "not_run"})
        output, result = self.prepare({"c01": delivery})
        self.assertEqual(result["primary_jobs"], 0)
        statuses = {row["window_id"]: row["structural_status"] for row in runner.load_jsonl(output / "expected.jsonl")}
        self.assertEqual(statuses, {"scene-a-Q1": "mapping_unjudgeable", "scene-a-Q2": "delivery_zero", "scene-b-Q2": "not_run"})
        runner.finalize(output)
        final = {row["window_id"]: row for row in runner.load_jsonl(output / "final.jsonl")}
        self.assertIsNone(final["scene-a-Q1"]["semantic"])
        self.assertIsNone(final["scene-b-Q2"]["semantic"])
        self.assertEqual(final["scene-a-Q2"]["semantic"], 0)

    def test_explicit_translation_failure_keeps_delivery_zero(self):
        delivery = self.delivery(states={"scene-a-J1": "translation_failed"})
        output, _ = self.prepare({"c01": delivery})
        first = runner.load_jsonl(output / "expected.jsonl")[0]
        self.assertEqual(first["structural_status"], "delivery_zero")
        self.assertIn("translation_failed", first["structural_issues"])

    def test_partial_delivery_is_judged_as_missing_without_source_fallback(self):
        ids = ["scene-a-J1", "scene-a-J2"]
        self.windows[0]["scored_ids"] = ids
        self.inputs[0]["translate_ids"] = ids
        self.refs[0]["scored_ids"] = ids
        self.windows[0]["units"][1]["score"] = True
        self.refs[0]["units"][1].update(score=True, zh="合成参考2")
        runner.dump(self.manifest_path, {"version": "synthetic-source-v2", "external_corpus": str(self.source), "windows": self.windows})
        runner.dump_jsonl(self.input_path, self.inputs)
        runner.dump_jsonl(self.reference_path, self.refs)
        self.freeze()
        output, _ = self.prepare({"c01": self.delivery(states={"scene-a-J2": "missing"})})
        first = runner.load_jsonl(output / "expected.jsonl")[0]
        self.assertEqual(first["structural_status"], "partial_delivery")
        packet = runner.read_json(output / first["packet"])
        self.assertIsNone(packet["translations"]["scene-a-J2"])
        self.assertIn(first["window_id"], [row["window_id"] for row in runner.load_jsonl(output / "jobs.jsonl")])

    def test_engineering_subset_requires_explicit_selection(self):
        delivery = self.delivery(scene_ids=["scene-a"])
        with self.assertRaises(ValueError):
            self.prepare({"c01": delivery})
        output, result = self.prepare({"c01": delivery}, window_ids=["scene-a-Q1", "scene-a-Q2"])
        self.assertEqual(result["windows"], 2)
        self.assertEqual(len(runner.load_jsonl(output / "expected.jsonl")), 2)

    def test_reject_reference_without_successful_freeze_before_output(self):
        delivery = self.delivery()
        self.freeze("primary_only")
        with self.assertRaisesRegex(ValueError, "double-fresh"):
            self.prepare({"c01": delivery})
        self.assertFalse((self.root / "evaluation").exists())

    def test_reject_changed_reference_source_or_mapping_hash(self):
        delivery = self.delivery()
        original = self.reference_path.read_bytes()
        self.reference_path.write_text(self.reference_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "hash changed"):
            self.prepare({"c01": delivery})
        self.reference_path.write_bytes(original)
        self.freeze()
        map_path = self.source / "episode-1-events.json"
        map_path.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "hash changed"):
            self.prepare({"c01": delivery})

    def test_reject_time_id_reference_scope_and_japanese_mutations(self):
        delivery = self.delivery()
        for change in ("time", "id", "source", "score", "events"):
            with self.subTest(change=change):
                windows, inputs, refs = deepcopy(self.windows), deepcopy(self.inputs), deepcopy(self.refs)
                if change == "time":
                    windows[0]["units"][0]["start_ms"] += 1
                elif change == "id":
                    windows[0]["units"][0]["ja_srt_index"] = 3
                elif change == "source":
                    inputs[0]["context"][0]["text"] = "改変"
                    refs[0]["units"][0]["ja"] = "改変"
                elif change == "score":
                    refs[0]["scored_ids"] = ["scene-a-J3"]
                else:
                    windows[0]["units"][0]["source_events"]["ja"][0]["source_line"] = 9999
                runner.dump(self.manifest_path, {"version": "synthetic-source-v2", "external_corpus": str(self.source), "windows": windows})
                runner.dump_jsonl(self.input_path, inputs)
                runner.dump_jsonl(self.reference_path, refs)
                self.freeze()
                with self.assertRaises(ValueError):
                    self.prepare({"c01": delivery})

    def test_reject_candidate_context_mapping_or_translation_repair(self):
        delivery = self.delivery()
        for name in ("inputs", "mapping", "results"):
            with self.subTest(name=name):
                path = delivery / f"{name}.jsonl"
                original = path.read_bytes()
                rows = runner.load_jsonl(path)
                if name == "inputs":
                    rows[0]["context"] = rows[0]["context"][:1]
                elif name == "mapping":
                    rows[0]["cues"][0]["source_cue_id"] = "wrong-source"
                else:
                    rows[0]["translations"]["scene-a-J1"] = "参考修补不可进入候选"
                runner.dump_jsonl(path, rows)
                with self.assertRaises(ValueError):
                    self.prepare({"c01": delivery})
                path.write_bytes(original)

    def test_frozen_adapter_contract_is_checked_by_existing_finalizer(self):
        output, _ = self.prepare({"c01": self.delivery()})
        path = output / "p-flow-scene-contract.json"
        path.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "frozen evaluation artifact changed"):
            runner.finalize(output)

    def derived_delivery(self):
        original = self.delivery()
        qualified = self.root / "qualified"
        manifest, scenes = qualified / "source-manifest.json", qualified / "scenes.jsonl"
        accepted, inputs, refs = deepcopy(self.windows), deepcopy(self.inputs), deepcopy(self.refs)
        for window, request, ref, target in zip(accepted, inputs, refs, ("scene-a-J3", "scene-a-J2", "scene-b-J1")):
            wid = f"{window['id']}-reserve"
            window.update(id=wid, window_id=wid, scored_ids=[target])
            request.update(id=wid, translate_ids=[target])
            ref.update(id=wid, scored_ids=[target])
            for unit in window["units"]:
                unit["score"] = unit["id"] == target
            for unit in ref["units"]:
                unit["score"] = unit["id"] == target
                unit.pop("zh", None)
                if unit["score"]:
                    unit["zh"] = "合成 reserve 参考"
        source = runner.read_json(self.manifest_path)
        runner.dump(manifest, {**source, "windows": accepted})
        scenes.write_bytes(self.scene_path.read_bytes())
        original_freeze = self.source / "freeze-manifest.json"
        # Preserve the original approved reference version; the reserve selection
        # has its own successful freeze rather than rewriting earlier evidence.
        self.reference_root = self.root / "evaluation-only-qualified"
        self.reference_path = self.reference_root / "reference" / "windows.jsonl"
        self.freeze_path = self.reference_root / "freeze-manifest.json"
        runner.dump_jsonl(self.reference_path, refs)
        self.freeze()
        approval = self.freeze_path
        runner.dump(qualified / "freeze-manifest.json", {"version": v2_prepare.SOURCE_FREEZE_VERSION,
            "state": "source_frozen_reference_qualified", "role": "screening",
            "reference_qualification": {"path": str(approval.resolve()), "sha256": runner.sha(approval),
                                        "version": "hy30-flow-v2-reference-v1",
                                        "state": "frozen_double_fresh_reference_review", "inference_allowed": True},
            "original_source_freeze": {"path": str(original_freeze.resolve()), "sha256": runner.sha(original_freeze)},
            "artifacts": [{"path": path.name, "sha256": runner.sha(path)} for path in (manifest, scenes)]})
        derived = self.root / "derived-delivery"
        report = v2_reproject.reproject_scoring(original, manifest, scenes, derived)
        scorer_input = qualified / "windows.jsonl"
        runner.dump_jsonl(scorer_input, inputs)
        return original, derived, manifest, scorer_input, report

    def test_cached_reprojection_validates_and_keeps_original_generation_cost_identity(self):
        original, derived, manifest, inputs, report = self.derived_delivery()
        original_run = Path(runner.read_json(original / "delivery.json")["run"]) / "run.json"
        original_bytes = original_run.read_bytes()
        output = self.root / "derived-evaluation"
        result = v2_evaluation.prepare(manifest, inputs, self.reference_path, {"c01": derived}, output,
                                      reference_freeze_path=self.freeze_path)
        self.assertEqual(result["windows"], 3)
        run = runner.read_json(output / "run.json")
        for meta in (run["candidates"]["c01"], run["p_flow_contract"]["candidate_artifacts"]["c01"]):
            self.assertEqual(meta["derivation"], report["derivation"])
            self.assertEqual(meta["new_inference_calls"], 0)
            self.assertEqual(meta["new_generated_samples"], 0)
            self.assertEqual(meta["original_generation_cost_identity"], report["derivation"]["original_run"])
            self.assertEqual(meta["seed"], report["seed"])
            self.assertEqual(meta["cost_attribution"], "original_run_once")
        self.assertEqual(run["lane"], "P-flow")
        self.assertIn("scoring-reprojection-validator.py", run["frozen_artifact_sha256"])
        self.assertEqual(original_run.read_bytes(), original_bytes)
        row = runner.load_jsonl(output / "expected.jsonl")[0]
        packet = runner.read_json(output / row["packet"])
        self.assertEqual(packet["scored_ids"], ["scene-a-J3"])
        self.assertEqual(packet["translations"], {"scene-a-J3": "合成译文scene-a-J3"})
        self.assertNotIn("derivation", packet)  # Judge remains blind to recipe/run identities.

    def test_reprojection_tampered_derived_packing_or_original_raw_is_rejected(self):
        original, derived, manifest, inputs, report = self.derived_delivery()
        packed_path = derived / "packed-mapping.json"
        packed_original, delivery_original = packed_path.read_bytes(), (derived / "delivery.json").read_bytes()
        packed = runner.read_json(packed_path)
        packed["batches"].reverse()
        runner.dump(packed_path, packed)
        report["packed_mapping"]["sha256"] = runner.sha(packed_path)
        runner.dump(derived / "delivery.json", report)
        with self.assertRaisesRegex(ValueError, "more than"):
            v2_evaluation.prepare(manifest, inputs, self.reference_path, {"c01": derived}, self.root / "rejected-packing",
                                  reference_freeze_path=self.freeze_path)
        packed_path.write_bytes(packed_original)
        (derived / "delivery.json").write_bytes(delivery_original)
        raw = Path(runner.read_json(original / "delivery.json")["run"]) / "results.jsonl"
        raw.write_bytes(raw.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "hash changed"):
            v2_evaluation.prepare(manifest, inputs, self.reference_path, {"c01": derived}, self.root / "rejected-raw",
                                  reference_freeze_path=self.freeze_path)

    def test_explicit_subset_preserves_full_delivery_bytes_and_validates_unselected_mapping(self):
        delivery = self.delivery()
        original = (delivery / "results.jsonl").read_bytes()
        output, result = self.prepare({"c01": delivery}, window_ids=["scene-a-Q1"])
        self.assertEqual(result["windows"], 1)
        self.assertEqual(result["expected_records"], 1)
        self.assertEqual((output / "originals/c01/results.jsonl").read_bytes(), original)
        meta = runner.read_json(output / "run.json")["candidates"]["c01"]
        self.assertEqual(meta["evaluation_window_ids"], ["scene-a-Q1"])
        self.assertEqual(len(meta["delivery_window_ids"]), 3)
        mapping_path = delivery / "mapping.jsonl"
        mapping = runner.load_jsonl(mapping_path)
        mapping[-1]["cues"][0]["source_cue_id"] = "tampered-unselected-cue"
        runner.dump_jsonl(mapping_path, mapping)
        with self.assertRaisesRegex(ValueError, "cue identities"):
            v2_evaluation.prepare(self.manifest_path, self.input_path, self.reference_path, {"c01": delivery},
                                  self.root / "rejected-unselected", reference_freeze_path=self.freeze_path,
                                  window_ids=["scene-a-Q1"])

    def test_explicit_subset_of_full_cached_reprojection_keeps_original_cost_scope(self):
        _, derived, manifest, inputs, report = self.derived_delivery()
        wid = "scene-a-Q1-reserve"
        output = self.root / "derived-subset-evaluation"
        result = v2_evaluation.prepare(manifest, inputs, self.reference_path, {"c01": derived}, output,
                                      reference_freeze_path=self.freeze_path, window_ids=[wid])
        self.assertEqual(result["expected_records"], 1)
        self.assertEqual(len(runner.load_jsonl(output / "jobs.jsonl")), 1)
        meta = runner.read_json(output / "run.json")["candidates"]["c01"]
        self.assertEqual(meta["original_generation_cost_identity"], report["derivation"]["original_run"])
        self.assertEqual(meta["new_generated_samples"], 0)
        self.assertEqual(meta["evaluation_window_ids"], [wid])
        self.assertEqual(len(meta["delivery_window_ids"]), 3)
        self.assertEqual((output / "originals/c01/results.jsonl").read_bytes(), (derived / "results.jsonl").read_bytes())

    def test_alternate_successful_reference_freeze_with_same_source_is_rejected(self):
        delivery = self.delivery()
        alternate = self.root / "alternate-evaluation-only"
        references = alternate / "reference" / "windows.jsonl"
        freeze = alternate / "freeze-manifest.json"
        values = deepcopy(self.refs)
        for row in values:
            for unit in row["units"]:
                if unit["score"]:
                    unit["zh"] = "另一版本的合成参考"
        runner.dump_jsonl(references, values)
        runner.dump(freeze, {"corpus_version": v2_evaluation.REFERENCE_VERSION,
                            "state": "frozen_double_fresh_reference_review", "inference_allowed": True,
                            "files": [{"path": "reference/windows.jsonl", "sha256": runner.sha(references)}]})
        v2_evaluation.reference_freeze(freeze, references)  # Independently valid, but never source-approved.
        with self.assertRaisesRegex(ValueError, "accepted source qualification"):
            v2_evaluation.prepare(self.manifest_path, self.input_path, references, {"c01": delivery},
                                  self.root / "rejected-alternate", reference_freeze_path=freeze)
        self.assertFalse((self.root / "rejected-alternate").exists())

    def test_successful_reference_replacement_at_approved_path_cannot_change_hash(self):
        delivery = self.delivery()
        values = deepcopy(self.refs)
        values[0]["units"][0]["zh"] = "同路径不同版本的合成参考"
        runner.dump_jsonl(self.reference_path, values)
        self.freeze()
        v2_evaluation.reference_freeze(self.freeze_path, self.reference_path)
        with self.assertRaisesRegex(ValueError, "accepted source qualification"):
            self.prepare({"c01": delivery})

    def test_reference_corpus_version_and_accepted_version_are_exact(self):
        delivery = self.delivery()
        path = self.source / "freeze-manifest.json"
        source_freeze = runner.read_json(path)
        source_freeze["reference_qualification"]["version"] = "alternate-reference-v2"
        runner.dump(path, source_freeze)
        with self.assertRaisesRegex(ValueError, "accepted source qualification"):
            self.prepare({"c01": delivery})


if __name__ == "__main__":
    unittest.main()
