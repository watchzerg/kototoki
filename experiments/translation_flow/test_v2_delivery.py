"""Synthetic v2 arbitrary-batch export/projection; no models or references."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from experiments.translation_eval.runner import dump, dump_jsonl, load_jsonl, read_json, sha
from .v2_delivery import aggregate, deliver, project_windows


class DeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch = Path(__file__).resolve().parents[2] / ".local/translation-v2-delivery-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(self.temp.name)
        ids = [f"source-{number}" for number in range(5)]
        context = [{"id": uid, "text": f"日文{number}。", "start": number + 1., "end": number + 1.9}
                   for number, uid in enumerate(ids)]
        self.scene = {"id": "scene1", "scene_id": "scene1", "source_language": "ja", "target_language": "zh-Hans",
                      "context": context, "translate_ids": ids}
        units = [{"id": uid, "ja_srt_index": number + 101, "index_text": f"00{number + 101}",
                  "time_line": f"00:00:{number + 1:02d},000  -->\t00:00:{number + 1:02d},900",
                  "start_ms": (number + 1) * 1000, "end_ms": (number + 1) * 1000 + 900,
                  "score": uid in ids[1:4]} for number, uid in enumerate(ids)]
        self.windows = [{"id": "score1", "window_id": "score1", "scene_id": "scene1", "work": "synthetic",
                         "source_sha256": "a" * 64, "scored_ids": ids[1:4], "units": units},
                        {"id": "score2", "window_id": "score2", "scene_id": "scene1", "work": "synthetic",
                         "source_sha256": "a" * 64, "scored_ids": ids[3:],
                         "units": [{**unit, "score": unit["id"] in ids[3:]} for unit in units]}]
        self.manifest = self.root / "source-manifest.json"
        dump(self.manifest, {"windows": self.windows})
        self.scene_path = self.root / "scenes.jsonl"
        dump_jsonl(self.scene_path, [self.scene])
        self.packed = {"schema": "hy30-flow-packed-v2", "scene_ids": ["scene1"], "scenes": [self.scene],
                       "source_manifest": {"path": str(self.manifest), "sha256": sha(self.manifest)},
                       "source_scenes": {"path": str(self.scene_path), "sha256": sha(self.scene_path)},
                       "recipe_id": "c0", "seed": 20261008, "windows": self.windows,
                       "batches": [{"id": "b1", "scene_id": "scene1", "target_ids": ids[:3], "readonly_ids": ids[3:4]},
                                   {"id": "b2", "scene_id": "scene1", "target_ids": ids[3:], "readonly_ids": ids[2:3]}]}
        self.mapping = self.root / "packed-mapping.json"
        dump(self.mapping, self.packed)
        self.run = self.root / "run"
        self.run.mkdir()
        inputs = []
        for batch in self.packed["batches"]:
            included = set(batch["target_ids"] + batch["readonly_ids"])
            inputs.append({"id": batch["id"], "source_language": "ja", "target_language": "zh-Hans",
                           "context": [{"id": cue["id"], "text": cue["text"]} for cue in context if cue["id"] in included],
                           "translate_ids": batch["target_ids"]})
        dump_jsonl(self.run / "inputs.jsonl", inputs)
        dump(self.run / "run.json", {"lane": "P-flow", "candidate": "apex", "expected_window_ids": ["b1", "b2"],
             "source_manifest_sha256": sha(self.manifest), "packed_mapping_sha256": sha(self.mapping),
             "input_sha256": sha(self.run / "inputs.jsonl")})
        self.results, self.ledger = [], []
        for batch in self.packed["batches"]:
            values = {uid: f"中文{uid}。" for uid in batch["target_ids"]}
            self.results.append({"id": batch["id"], "translations": values, "elapsed_seconds": 3, "status": "delivered"})
            self.ledger.append({"window_id": batch["id"], "translations": values, "status": "delivered",
                                "elapsed_seconds": 3, "generation_seconds": 2, "auxiliary_seconds": 1,
                                "attempts": [{}, {}]})
        self.write_run()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_run(self) -> None:
        dump_jsonl(self.run / "results.jsonl", self.results)
        dump_jsonl(self.run / "ledger.jsonl", self.ledger)

    def execute(self) -> dict:
        return deliver(self.manifest, self.mapping, self.run, self.root / "delivery", candidate_id="apex")

    def test_complete_export_retains_exact_indices_times_and_hash_provenance(self) -> None:
        report = self.execute()
        text = (self.root / "delivery/scenes/scene1/chn.srt").read_text(encoding="utf-8")
        for unit in self.windows[0]["units"]:
            self.assertIn(f"{unit['index_text']}\n{unit['time_line']}\n", text)
        self.assertNotIn("日文", text)
        self.assertEqual(report["source_manifest"]["sha256"], sha(self.manifest))
        self.assertEqual(report["packed_mapping"]["sha256"], sha(self.mapping))
        self.assertEqual(report["scenes"][0]["expected_cues"], 5)
        sidecar = read_json(self.root / "delivery/scenes/scene1/sidecar.json")
        self.assertEqual([cue["id"] for cue in sidecar["source"]["cues"]], self.scene["translate_ids"])

    def test_cross_batch_windows_and_overlap_do_not_duplicate_costs(self) -> None:
        report = self.execute()
        self.assertEqual(report["costs"]["elapsed_seconds"]["measured_sum"], 6)
        self.assertEqual(report["costs"]["attempts"]["measured_sum"], 4)
        results = load_jsonl(self.root / "delivery/results.jsonl")
        ledger = load_jsonl(self.root / "delivery/ledger.jsonl")
        self.assertEqual(set(results[0]["translations"]), set(self.windows[0]["scored_ids"]))
        self.assertEqual(ledger[0]["source_batch_ids"], ["b1", "b2"])
        self.assertTrue(all(row["elapsed_seconds"] is None for row in results + ledger))

    def test_partial_missing_cue_has_no_success_srt(self) -> None:
        self.results[0]["translations"].pop("source-1")
        self.ledger[0]["translations"] = self.results[0]["translations"]
        self.write_run()
        report = self.execute()
        self.assertEqual(report["scenes"][0]["status"], "incomplete")
        self.assertEqual(report["scenes"][0]["status_counts"]["missing"], 1)
        self.assertFalse((self.root / "delivery/scenes/scene1/chn.srt").exists())

    def test_failed_missing_and_unexecuted_remain_distinct(self) -> None:
        self.results, self.ledger = [], []
        self.write_run()
        dump_jsonl(self.run / "schedule.jsonl", [{"window_id": "b2", "status": "not_run", "reason": "Stopped"}])
        report = self.execute()
        self.assertEqual(report["scenes"][0]["status_counts"], {"missing": 3, "not_run": 2})
        ledger = load_jsonl(self.root / "delivery/ledger.jsonl")
        self.assertEqual(ledger[0]["status"], "mapping_unjudgeable")
        self.assertEqual(load_jsonl(self.root / "delivery/schedule.jsonl")[0]["window_id"], "score2")

    def test_translation_failure_preserves_failed_denominator(self) -> None:
        self.results[0].update(status="translation_failed", translations={})
        self.ledger[0].update(status="translation_failed", translations={}, reason="Engine failure")
        self.write_run()
        report = self.execute()
        self.assertEqual(report["scenes"][0]["status_counts"]["translation_failed"], 3)
        self.assertEqual(load_jsonl(self.root / "delivery/ledger.jsonl")[0]["status"], "translation_failed")

    def test_omitted_batch_does_not_become_explicit_nonexecution(self) -> None:
        aggregated = aggregate(self.packed, [], [], [])
        projected = project_windows(self.packed, aggregated)
        self.assertEqual(projected["results"], [])
        self.assertEqual(projected["schedule"], [])
        self.assertEqual(projected["mechanical"][0]["status_counts"], {"missing": 3})
        self.assertFalse(aggregated["costs"]["elapsed_seconds"]["complete"])
        self.assertEqual(aggregated["costs"]["elapsed_seconds"]["unknown_records"], 2)

    def test_duplicate_source_coverage_rejected(self) -> None:
        packed = deepcopy(self.packed)
        packed["batches"][1]["target_ids"].insert(0, "source-2")
        packed["batches"][1]["readonly_ids"] = []
        with self.assertRaisesRegex(ValueError, "duplicate"):
            aggregate(packed, self.results, self.ledger, [])

    def test_conflicting_result_and_ledger_rejected(self) -> None:
        self.ledger[0]["translations"] = {"source-0": "冲突"}
        with self.assertRaisesRegex(ValueError, "disagree"):
            aggregate(self.packed, self.results, self.ledger, [])

    def semantic_delivery(self) -> None:
        native = "甲乙丙"
        self.ledger[0].update(
            semantic_plan={"units": [{"id": "u1", "source_ids": self.scene["translate_ids"][:3],
                                      "evidence_ids": ["source-0"], "uncertain": False}]},
            native_unit_translations={"u1": native},
            source_span_to_target_span=[{"unit_id": "u1", "source_ids": [f"source-{i}"],
                                         "target_spans": [[i, i + 1]]} for i in range(3)],
            translations={f"source-{i}": native[i] for i in range(3)},
        )
        self.results[0]["translations"] = self.ledger[0]["translations"]

    def test_semantic_exact_partition_is_deliverable_and_native_kept_separate(self) -> None:
        self.semantic_delivery()
        self.write_run()
        self.execute()
        diagnostics = load_jsonl(self.root / "delivery/native-diagnostics.jsonl")
        self.assertEqual(diagnostics[0]["native_unit_translations"], {"u1": "甲乙丙"})
        self.assertNotIn("native_unit_translations", load_jsonl(self.root / "delivery/results.jsonl")[0])

    def test_semantic_copied_paragraph_rejected(self) -> None:
        self.semantic_delivery()
        self.ledger[0]["translations"] = {f"source-{i}": "甲乙丙" for i in range(3)}
        self.results[0]["translations"] = self.ledger[0]["translations"]
        with self.assertRaisesRegex(ValueError, "partition"):
            aggregate(self.packed, self.results, self.ledger, [])

    def test_semantic_missing_native_provenance_rejected(self) -> None:
        self.semantic_delivery()
        del self.ledger[0]["native_unit_translations"]
        with self.assertRaisesRegex(ValueError, "provenance"):
            aggregate(self.packed, self.results, self.ledger, [])

    def test_unresolved_native_is_not_assigned_to_source_cues(self) -> None:
        self.semantic_delivery()
        self.ledger[0].update(status="mapping_unjudgeable", translations={}, reason="Cannot split reliably")
        self.results[0].update(status="mapping_unjudgeable", translations={})
        self.write_run()
        self.execute()
        projected = load_jsonl(self.root / "delivery/results.jsonl")[0]
        self.assertEqual(projected["translations"], {"source-3": "中文source-3。"})
        self.assertFalse((self.root / "delivery/scenes/scene1/chn.srt").exists())

    def test_source_mutation_rejected_before_output(self) -> None:
        self.manifest.write_text('{"windows": []}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "identity"):
            self.execute()
        self.assertFalse((self.root / "delivery").exists())

    def shared_transport(self) -> Path:
        run = read_json(self.run / "run.json")
        settings = {"label": self.run.name, "recipe": "c0", "input_sha256": run["input_sha256"]}
        plan = {"schema": "hy30-flow-session-v2", "lane": "P-flow", "workloads": [settings],
                "experiment_identity": {"source_manifest_sha256": run["source_manifest_sha256"]}}
        dump(self.root / "session-plan.json", plan)
        run.update(schema=plan["schema"], settings=settings, session_plan_sha256=sha(self.root / "session-plan.json"),
                   compatibility_sha256="b" * 64, code_sha256={"worker.py": "c" * 64})
        dump(self.run / "run.json", run)
        dump(self.root / "session.json", {"schema": plan["schema"], "plan_sha256": run["session_plan_sha256"],
             "compatibility_sha256": run["compatibility_sha256"], "code_sha256": run["code_sha256"],
             "identity": {"asset": {"id": "apex", "sha256": "d" * 64},
                          "engine": {"asset": {"sha256": "d" * 64}, "model_sha256": "d" * 64}}})
        transport = self.root / "transport"
        prompt = "Synthetic source-only prompt"
        request = {"prompt": [1, 2, 3], "n_predict": 4096}
        response = {"content": "synthetic candidate output", "tokens_predicted": 5}
        for number, endpoint, body, raw in (
            (1, "/tokenize", {"content": prompt}, {"tokens": [1, 2, 3]}),
            (2, "/completion", request, response),
        ):
            pointer = transport / f"{number:05d}"
            dump(pointer / "request.json", {"endpoint": endpoint, "body": body})
            dump(pointer / "response.raw", raw)
            dump(pointer / "transport.json", {"status": 200})
        self.ledger[0]["attempts"] = [{"prompt_sha256": hashlib.sha256(json.dumps(prompt, ensure_ascii=False).encode()).hexdigest(),
                                      "request": request, "response": response,
                                      "tokenize_exchange": str(transport / "00001"),
                                      "original_response": str(transport / "00002")}]
        self.write_run()
        return transport

    def test_verified_session_shared_transport_is_hashed_and_deliverable(self) -> None:
        transport = self.shared_transport()
        report = self.execute()
        artifacts = {item["path"] for item in report["artifacts"]}
        self.assertIn(str(transport / "00002/response.raw"), artifacts)
        self.assertIn(str(self.root / "session.json"), artifacts)
        self.assertEqual(report["scenes"][0]["status"], "complete")

    def test_other_session_transport_is_rejected(self) -> None:
        self.shared_transport()
        self.ledger[0]["attempts"][0]["original_response"] = str(self.root / "other-session/transport/00002")
        self.write_run()
        with self.assertRaisesRegex(ValueError, "escapes"):
            self.execute()

    def test_shared_transport_changed_session_identity_is_rejected(self) -> None:
        self.shared_transport()
        session = read_json(self.root / "session.json")
        session["compatibility_sha256"] = "e" * 64
        dump(self.root / "session.json", session)
        with self.assertRaisesRegex(ValueError, "identity"):
            self.execute()

    def test_shared_transport_changed_response_is_rejected(self) -> None:
        transport = self.shared_transport()
        dump(transport / "00002/response.raw", {"content": "different output"})
        with self.assertRaisesRegex(ValueError, "response disagrees"):
            self.execute()

    def test_new_mapping_and_protocol_diagnostics_survive_sidecars(self) -> None:
        self.semantic_delivery()
        diagnostics = {
            'mapping_provenance': {'protocol': 'exact-anchors-v1', 'resolved_anchors': [],
                                   'deterministic_singleton_unit_ids': ['u1'], 'native_text_unchanged': True},
            'mapping_protocol': 'exact-anchors-v1',
            'mapping_cost': {'model_mapping_required': False, 'completion_calls': 0,
                             'elapsed_seconds': 0, 'generation_seconds': 0, 'input_tokens': 0, 'output_tokens': 0},
            'native_protocol': 'id-text-exact-markers-flex-v1',
            'mapping_grammar_build': {'protocol': 'semantic-immutable-partition-state-grammar-v1',
                                      'status': 'accepted', 'diagnostics': {'state_count': 12, 'grammar_bytes': 900},
                                      'elapsed_seconds': .1, 'native_text_truncated': False},
        }
        self.ledger[0].update(deepcopy(diagnostics))
        self.write_run()
        report = self.execute()
        native = load_jsonl(self.root / 'delivery/native-diagnostics.jsonl')[0]
        sidecar = read_json(self.root / 'delivery/scenes/scene1/sidecar.json')
        for key, value in diagnostics.items():
            self.assertEqual(native[key], value)
            self.assertEqual(sidecar['batch_diagnostics'][0][key], value)
        self.assertEqual(report['costs']['elapsed_seconds']['measured_sum'], 6)
        self.assertNotIn('mapping_cost', load_jsonl(self.root / 'delivery/ledger.jsonl')[0])

    def test_shared_source_preparation_preserves_links_without_duplicate_costs(self) -> None:
        identity = {'artifact': {'path': str(self.root / 'source-preparation.json'), 'sha256': 'e' * 64},
                    'batch_options': {'path': 'batch-options.json', 'sha256': 'f' * 64}}
        for row in self.ledger:
            row['source_preparation'] = {
                'identity': deepcopy(identity), 'visible_options_sha256': 'd' * 64,
                'cost_attribution': 'shared separate preparation; no per-batch duplicate cost',
                'cost': {'elapsed_seconds': 100, 'completion_calls': 20},
                'protocol': 'quoted-background-with-uncertainty-v1',
                'projection': 'background-supported-scene-context-v1',
                'source_visibility': {'actual_context_ids': ['1', '2'], 'new_readonly_ids': ['2'],
                                      'uncertain_injected_items': 1},
            }
        run = read_json(self.run / 'run.json')
        run['source_preparation'] = deepcopy(identity)
        dump(self.run / 'run.json', run)
        self.write_run()
        report = self.execute()
        self.assertEqual(report['source_preparation']['identity'], identity)
        self.assertEqual(report['source_preparation']['relative_pointer_root'], str(self.mapping.parent))
        sidecar = read_json(self.root / 'delivery/scenes/scene1/sidecar.json')
        native = load_jsonl(self.root / 'delivery/native-diagnostics.jsonl')
        self.assertEqual(sidecar['source_preparation'], report['source_preparation'])
        self.assertEqual(len(sidecar['batch_diagnostics']), 2)
        self.assertTrue(all(row['source_preparation']['identity'] == identity for row in native))
        self.assertTrue(all('cost' not in row['source_preparation'] for row in native))
        self.assertTrue(all(row['source_preparation']['source_visibility']['uncertain_injected_items'] == 1 for row in native))
        self.assertEqual(report['costs']['elapsed_seconds']['measured_sum'], 6)
        self.assertNotIn('source_preparation', report['costs'])
        self.assertTrue(all('source_preparation' not in row for row in load_jsonl(self.root / 'delivery/ledger.jsonl')))

    def test_structured_planning_diagnostics_do_not_duplicate_inference_costs(self) -> None:
        self.semantic_delivery()
        planning = {
            'planning_provenance': {'protocol': 'semantic-ordered-boundary-decisions-v1',
                                    'ordered_boundaries': [], 'model_planning_required': True,
                                    'deterministic_single_target': False,
                                    'source_ids_derived_from_frozen_window': True,
                                    'semantic_boundary_correctness_verified': False},
            'planning_cost': {'model_planning_required': True, 'completion_calls': 1,
                              'elapsed_seconds': 1, 'generation_seconds': .5,
                              'input_tokens': 100, 'output_tokens': 40},
            'mapping_provenance': {'protocol': 'semantic-immutable-substring-partition-v1',
                                   'native_text_unchanged': True},
            'mapping_cost': {'model_mapping_required': True, 'completion_calls': 1,
                             'elapsed_seconds': .5, 'generation_seconds': .4},
        }
        self.ledger[0].update(deepcopy(planning))
        self.write_run()
        report = self.execute()
        native = load_jsonl(self.root / 'delivery/native-diagnostics.jsonl')[0]
        sidecar = read_json(self.root / 'delivery/scenes/scene1/sidecar.json')
        for key, value in planning.items():
            self.assertEqual(native[key], value)
            self.assertEqual(sidecar['batch_diagnostics'][0][key], value)
        self.assertEqual(report['costs']['elapsed_seconds']['measured_sum'], 6)
        self.assertEqual(report['costs']['auxiliary_seconds']['measured_sum'], 2)
        self.assertNotIn('planning_cost', report['costs'])
        self.assertTrue(all('planning_cost' not in row for row in load_jsonl(self.root / 'delivery/ledger.jsonl')))

    def test_legacy_rows_add_no_new_sidecar_protocol_fields(self) -> None:
        report = self.execute()
        sidecar = read_json(self.root / 'delivery/scenes/scene1/sidecar.json')
        self.assertNotIn('batch_diagnostics', sidecar)
        self.assertNotIn('source_preparation', sidecar)
        self.assertNotIn('source_preparation', report)


if __name__ == "__main__":
    unittest.main()
