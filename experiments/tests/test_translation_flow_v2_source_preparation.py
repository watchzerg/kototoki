"""Offline evidence, visibility, failure and cost contracts for source preparation."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from experiments.translation_demo import adapters
from experiments.translation_flow.cli import digest
from experiments.translation_flow.test_worker import FakeClient
from experiments.translation_flow.test_v2_worker import result
from experiments.translation_flow.v2_source_preparation import (
    ARTIFACT_SCHEMA, ARTIFACT_SCHEMA_V3, BACKGROUND_PROTOCOL, CANDIDATE, SCHEMA,
    SESSION_SCHEMA, TERMS_PROTOCOL, execute_plan, load_options, load_plan,
    options_for_window, parse_response, render_prompt,
)


def source_scene(key="scene-a"):
    return {"id": key, "source_language": "ja", "target_language": "zh-Hans",
            "context": [{"id": key + "-1", "text": "隊長はここにいます。"},
                        {"id": key + "-2", "text": "もし雨なら中止です。"},
                        {"id": key + "-3", "text": "隊長を呼んでください。"}],
            "translate_ids": [key + "-1", key + "-2", key + "-3"]}


def term_response(key="scene-a", uncertain=False):
    return {"terms": [{"source": "隊長", "translation": "队长", "uncertain": uncertain,
                        "evidence": [{"id": key + "-1", "quote": "隊長"}, {"id": key + "-3", "quote": "隊長"}]}]}


def background_response(key="scene-a", uncertain=False):
    return {"background": [{"text": "队长在这里。", "uncertain": uncertain,
                             "evidence": [{"id": key + "-1", "quote": "隊長はここにいます。"}]}]}


class SourcePreparationProtocolTests(unittest.TestCase):
    def parse(self, obj, mode="terms", scene=None):
        return parse_response(json.dumps(obj, ensure_ascii=False), mode, scene or source_scene())

    def test_native_source_only_prompt_and_separate_hypotheses(self):
        terms = render_prompt("terms", source_scene())
        background = render_prompt("background", source_scene())
        self.assertTrue(terms.startswith("<｜hy_begin▁of▁sentence｜>"))
        self.assertTrue(terms.endswith("<｜hy_Assistant｜><think></think>"))
        self.assertIn("reasoning_effort:no_think", terms)
        self.assertIn("至少在两个不同源 cue", terms)
        self.assertNotIn('"background":[', terms)
        self.assertIn("不得在引文之外合成新事实", background)
        self.assertIn("uncertain=true", background)
        bad = {**source_scene(), "reference": "forbidden"}
        with self.assertRaises(ValueError):
            render_prompt("terms", bad)

    def test_terms_exact_repetition_quotes_provenance_and_empty_set(self):
        prepared = self.parse(term_response())
        self.assertEqual(prepared["records"][0]["evidence_ids"], ["scene-a-1", "scene-a-3"])
        self.assertEqual(prepared["records"][0]["origin"], "source-preparation")
        self.assertFalse(prepared["semantic_quality_checked"])
        self.assertEqual(self.parse({"terms": []})["records"], [])

    def test_terms_reject_invisible_modified_unordered_duplicate_or_single_evidence(self):
        mutations = (lambda obj: obj["terms"][0]["evidence"][0].update(id="other-scene-1"),
                     lambda obj: obj["terms"][0]["evidence"][0].update(quote="隊長は来た"),
                     lambda obj: obj["terms"][0]["evidence"][0].update(quote="ここに"),
                     lambda obj: obj["terms"][0]["evidence"].reverse(),
                     lambda obj: obj["terms"][0]["evidence"].pop(),
                     lambda obj: obj["terms"][0]["evidence"][1].update(id="scene-a-1"))
        for number, mutate in enumerate(mutations):
            with self.subTest(mutation=number):
                obj = term_response()
                mutate(obj)
                with self.assertRaises(ValueError):
                    self.parse(obj)

    def test_records_reject_unknown_fields_duplicate_terms_unbounded_and_nonboolean_uncertainty(self):
        bad = term_response()
        bad["terms"][0]["reference_translation"] = "forbidden"
        with self.assertRaises(ValueError):
            self.parse(bad)
        bad = term_response()
        bad["terms"].append(deepcopy(bad["terms"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.parse(bad)
        bad = term_response()
        bad["terms"][0]["uncertain"] = "false"
        with self.assertRaises(ValueError):
            self.parse(bad)
        with self.assertRaises(ValueError):
            parse_response(json.dumps(term_response()), "terms", source_scene(), 0)
        with self.assertRaises(ValueError):
            parse_response('{"terms":[],"terms":[]}', "terms", source_scene())

    def test_uncertainty_preserved_and_not_injected_as_certainty(self):
        terms = self.parse(term_response(uncertain=True))
        facts = self.parse(background_response(uncertain=True), "background")
        self.assertTrue(terms["records"][0]["uncertain"])
        self.assertTrue(facts["records"][0]["uncertain"])
        self.assertEqual(options_for_window(terms, source_scene()), {"terms": []})
        self.assertEqual(options_for_window(facts, source_scene()), {"background": []})

    def test_far_repeat_term_projects_to_visible_occurrence_without_future_fact(self):
        prepared = self.parse(term_response())
        source = source_scene()
        batch = {**source, "context": source["context"][:1], "translate_ids": source["translate_ids"][:1]}
        options = options_for_window(prepared, batch)
        self.assertEqual(options["terms"][0]["evidence_ids"], ["scene-a-1"])
        absent = {**source, "context": source["context"][1:2], "translate_ids": source["translate_ids"][1:2]}
        self.assertEqual(options_for_window(prepared, absent), {"terms": []})
        background = background_response()
        background["background"][0]["evidence"].append({"id": "scene-a-3", "quote": "隊長を呼んでください。"})
        facts = self.parse(background, "background")
        self.assertEqual(options_for_window(facts, batch), {"background": []})
        self.assertEqual(len(options_for_window(facts, source)["background"]), 1)
        wrong = deepcopy(batch)
        wrong["context"][0]["text"] = "改変された台詞"
        with self.assertRaisesRegex(ValueError, "exact subset"):
            options_for_window(prepared, wrong)


class SourcePreparationWorkerTests(unittest.TestCase):
    def fixture(self, root, *, mode="terms", scenes=None):
        scenes = scenes or [source_scene()]
        source = root / "source"
        source.mkdir()
        manifest, scene_path = source / "source-manifest.json", source / "scenes.jsonl"
        manifest.write_text('{"windows":[]}', encoding="utf-8")
        original = [{**scene, "scene_id": scene["id"],
                     "context": [{**cue, "start": number, "end": number + 1}
                                 for number, cue in enumerate(scene["context"])]} for scene in scenes]
        scene_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in original), encoding="utf-8")
        freeze = source / "freeze-manifest.json"
        freeze.write_text(json.dumps({"version": "hy30-flow-v2-source-v1", "state": "source_frozen_reference_unreviewed",
                          "role": "screening", "artifacts": [{"path": path.name, "sha256": digest(path)}
                                                               for path in (manifest, scene_path)]}), encoding="utf-8")
        plan = {"schema": SCHEMA, "mode": mode, "stage": "qualification",
                "source": {"manifest": str(manifest), "manifest_sha256": digest(manifest), "scenes": str(scene_path),
                           "scenes_sha256": digest(scene_path), "freeze_sha256": digest(freeze)},
                "scene_ids": [scene["id"] for scene in scenes],
                "settings": {"sampling": "official", "cache_prompt": True, "n_predict": 4096,
                             "seed": 20261008, "max_attempts": 2, "max_items": 16},
                "budgets": {"max_translation_calls": 20, "max_judge_calls": 0,
                            "max_estimated_tokens": 200000, "max_wall_seconds": 120}}
        plan_path = root / "plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        args = argparse.Namespace(candidate=CANDIDATE, session_plan=plan_path, output_dir=root / "output",
                                  server_url="http://127.0.0.1:8080", context_size=8192,
                                  engine_manifest=root / "engine.json", asset_manifest=[], stop_on_oom=True)
        return plan, args

    def identity(self, args):
        return {"asset": {"id": CANDIDATE}, "engine": {"model_path": "fake.gguf", "server_pid": 1234,
                "command": ["server", "-np", "1"], "build": 11429},
                "engine_manifest_sha256": "a" * 64, "template_sha256": "b" * 64}

    def run_fake(self, args, outputs, tokens=7):
        client = FakeClient(outputs, tokens=tokens)
        code = execute_plan(args, lambda *a, **k: client, self.identity)
        return code, client

    def test_complete_artifact_shares_scene_cost_once_and_preserves_native_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            _, args = self.fixture(Path(temp))
            code, client = self.run_fake(args, [result(term_response())])
            self.assertEqual(code, 0)
            self.assertEqual(len(client.requests), 1)
            self.assertEqual(client.requests[0]["temperature"], .7)
            self.assertTrue(client.requests[0]["cache_prompt"])
            artifact = args.output_dir / "preparation-options.json"
            options = load_options(artifact, digest(artifact))
            self.assertEqual(options["schema"], ARTIFACT_SCHEMA)
            self.assertFalse(options["semantic_quality_checked"])
            self.assertTrue(options["cache_reset"]["verified"])
            self.assertIn("template_sha256", options["identity"])
            complete = json.loads((args.output_dir / "worker-completion.json").read_text(encoding="utf-8"))
            self.assertEqual(complete["budget"]["translation_calls"], 1)
            self.assertEqual(complete["budget"]["estimated_tokens"], 7 + 4096)
            self.assertTrue((args.output_dir / "prompt-scene-a.json").exists())
            self.assertTrue((args.output_dir / "dispatch-journal.jsonl").exists())
            artifact.write_bytes(artifact.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "artifact changed"):
                load_options(artifact, complete["artifact"]["sha256"])

    def test_background_is_separate_scene_call_and_preserves_quotes(self):
        with tempfile.TemporaryDirectory() as temp:
            _, args = self.fixture(Path(temp), mode="background")
            code, client = self.run_fake(args, [result(background_response())])
            self.assertEqual(code, 0)
            options = load_options(args.output_dir / "preparation-options.json", digest(args.output_dir / "preparation-options.json"))
            self.assertEqual(options["mode"], "background")
            self.assertEqual(options["preparations"][0]["records"][0]["evidence"][0]["quote"], "隊長はここにいます。")
            self.assertEqual(len(client.requests), 1)

    def test_rehashed_artifact_cannot_bypass_quotes_cache_or_once_only_ledger(self):
        for change in ("quote", "cache", "ledger"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temp:
                _, args = self.fixture(Path(temp))
                self.assertEqual(self.run_fake(args, [result(term_response())])[0], 0)
                path = args.output_dir / "preparation-options.json"
                artifact = json.loads(path.read_text(encoding="utf-8"))
                if change == "quote":
                    artifact["preparations"][0]["records"][0]["evidence"][0]["quote"] = "伪造引文"
                elif change == "cache":
                    artifact["cache_reset"]["first_response_cache_n"] = 1
                else:
                    ledger = args.output_dir / "ledger.jsonl"
                    ledger.write_bytes(ledger.read_bytes() + b"\n")
                path.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_options(path, digest(path))

    def test_parse_retry_identical_request_keeps_both_costs(self):
        with tempfile.TemporaryDirectory() as temp:
            _, args = self.fixture(Path(temp))
            code, client = self.run_fake(args, [result({"terms": [{"reference": "forbidden"}]}), result(term_response())])
            self.assertEqual(code, 0)
            self.assertEqual(client.requests[0], client.requests[1])
            complete = json.loads((args.output_dir / "worker-completion.json").read_text(encoding="utf-8"))
            self.assertEqual(complete["budget"]["translation_calls"], 2)
            self.assertEqual(complete["budget"]["estimated_tokens"], 2 * (7 + 4096))

    def test_oom_cache_and_context_failure_keep_partial_artifact_and_tail(self):
        cases = (([ValueError("CUDA_ERROR_OUT_OF_MEMORY")], 7, "oom"),
                 ([result(term_response(), timings={"cache_n": 2})], 7, "cache"),
                 ([result(term_response())], 4033, "budget"))
        for outputs, tokens, reason in cases:
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as temp:
                _, args = self.fixture(Path(temp), scenes=[source_scene(), source_scene("scene-b")])
                code, client = self.run_fake(args, outputs, tokens=tokens)
                self.assertEqual(code, 1)
                self.assertFalse((args.output_dir / "preparation-options.json").exists())
                partial = args.output_dir / "preparation-options.partial.json"
                with self.assertRaisesRegex(ValueError, "Only complete"):
                    load_options(partial, digest(partial))
                tail = json.loads((args.output_dir / "schedule.jsonl").read_text(encoding="utf-8"))
                self.assertEqual(tail["scene_id"], "scene-b")
                self.assertEqual(tail["reason"], reason)
                self.assertEqual(len(client.requests), 0 if reason == "budget" else 1)

    def test_source_hash_firewall_and_scoring_only_scene_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan, args = self.fixture(root)
            self.assertEqual(load_plan(args.session_plan)[1], [source_scene()])
            source = Path(plan["source"]["scenes"])
            source.write_bytes(source.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "identity changed"):
                load_plan(args.session_plan)
        with tempfile.TemporaryDirectory() as temp:
            incomplete = source_scene()
            incomplete["translate_ids"] = incomplete["translate_ids"][:1]
            _, args = self.fixture(Path(temp), scenes=[incomplete])
            with self.assertRaisesRegex(ValueError, "complete frozen source scene"):
                load_plan(args.session_plan)


class SourcePreparationVersion3Tests(unittest.TestCase):
    def fixture(self, root, *, mode="terms", scenes=None, relative=False):
        plan, args = SourcePreparationWorkerTests().fixture(root, mode=mode, scenes=scenes)
        plan["schema"] = SESSION_SCHEMA
        plan["protocol"] = TERMS_PROTOCOL if mode == "terms" else BACKGROUND_PROTOCOL
        plan["settings"]["n_predict"] = 2048
        if relative:
            for key in ("manifest", "scenes"):
                plan["source"][key] = Path(plan["source"][key]).relative_to(root).as_posix()
        args.session_plan.write_text(json.dumps(plan), encoding="utf-8")
        return plan, args

    def run_fake(self, args, outputs, tokens=7):
        return SourcePreparationWorkerTests().run_fake(args, outputs, tokens)

    def options(self, args):
        path = args.output_dir / "preparation-options.json"
        return load_options(path, digest(path))

    def proposals(self, *, mixed=False):
        rows = [{"source": "不存在", "translation": "不存在", "uncertain": False},
                {"source": "雨", "translation": "雨", "uncertain": True}]
        if mixed:
            rows.insert(0, {"source": "隊長", "translation": "队长", "uncertain": True})
        return {"terms": rows}

    def test_zero_and_single_cue_proposals_complete_without_eligibility_retries(self):
        for response in (self.proposals(), {"terms": []}):
            with self.subTest(response=response), tempfile.TemporaryDirectory() as temp:
                _, args = self.fixture(Path(temp), relative=True)
                code, client = self.run_fake(args, [result(response)])
                self.assertEqual(code, 0)
                self.assertEqual(len(client.requests), 1)
                self.assertEqual(client.requests[0]["n_predict"], 2048)
                artifact = self.options(args)
                self.assertEqual(artifact["schema"], ARTIFACT_SCHEMA_V3)
                prep = artifact["preparations"][0]
                self.assertEqual(prep["accepted_count"], 0)
                self.assertEqual(prep["declined_count"], len(response["terms"]))
                self.assertTrue(prep["zero_eligible_glossary"])
                self.assertEqual(prep["raw_response"], artifact["raw_responses"][0]["content"])
                complete = json.loads((args.output_dir / "worker-completion.json").read_text(encoding="utf-8"))
                self.assertEqual(complete["budget"]["translation_calls"], 1)
                self.assertEqual(complete["budget"]["estimated_tokens"], 2055)
                prompt = json.loads((args.output_dir / "prompt-scene-a.json").read_text(encoding="utf-8"))
                self.assertIn("你不要复制证据ID或引文", prompt["prompt"])
                self.assertEqual(prompt["protocol"], TERMS_PROTOCOL)

    def test_mixed_dispositions_and_uncertainty_survive_complete_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            _, args = self.fixture(Path(temp))
            code, client = self.run_fake(args, [result(self.proposals(mixed=True))])
            self.assertEqual(code, 0)
            prep = self.options(args)["preparations"][0]
            self.assertEqual((prep["returned_count"], prep["accepted_count"], prep["declined_count"]), (3, 1, 2))
            self.assertEqual([row["disposition"] for row in prep["proposals"]], ["accepted", "declined", "declined"])
            self.assertEqual([row["reason"] for row in prep["proposals"]],
                             ["exact-repeat-in-distinct-cues", "source-not-present", "single-cue-only"])
            self.assertEqual(prep["records"][0]["evidence_ids"], ["scene-a-1", "scene-a-3"])
            self.assertTrue(prep["records"][0]["uncertain"])
            self.assertFalse(prep["zero_eligible_glossary"])
            self.assertEqual(len(client.requests), 1)

    def test_malformed_or_contradictory_proposals_fail_atomically_with_bounded_retry_cost(self):
        for response in ('{"terms":', {"terms": [
                {"source": "隊長", "translation": "队长", "uncertain": False},
                {"source": "隊長", "translation": "队员", "uncertain": False}]}):
            with self.subTest(response=response), tempfile.TemporaryDirectory() as temp:
                _, args = self.fixture(Path(temp))
                code, client = self.run_fake(args, [result(response), result(response)])
                self.assertEqual(code, 1)
                self.assertEqual(len(client.requests), 2)
                self.assertEqual(client.requests[0], client.requests[1])
                partial = args.output_dir / "preparation-options.partial.json"
                artifact = json.loads(partial.read_text(encoding="utf-8"))
                self.assertEqual(artifact["preparations"], [])
                self.assertEqual(artifact["raw_responses"], [])
                with self.assertRaisesRegex(ValueError, "Only complete"):
                    load_options(partial, digest(partial))
                row = json.loads((args.output_dir / "ledger.jsonl").read_text(encoding="utf-8"))
                self.assertEqual(len(row["attempts"]), 2)
                self.assertTrue(all(attempt["response"]["content"] == result(response)["content"] for attempt in row["attempts"]))
                self.assertEqual(row["budget_after"]["estimated_tokens"], 2 * 2055)

    def test_versioned_background_keeps_raw_quotes_and_uncertain_records(self):
        with tempfile.TemporaryDirectory() as temp:
            _, args = self.fixture(Path(temp), mode="background")
            code, client = self.run_fake(args, [result(background_response(uncertain=True))])
            self.assertEqual(code, 0)
            artifact = self.options(args)
            self.assertEqual(artifact["protocol"], BACKGROUND_PROTOCOL)
            self.assertTrue(artifact["preparations"][0]["records"][0]["uncertain"])
            self.assertEqual(artifact["preparations"][0]["records"][0]["evidence"][0]["quote"], "隊長はここにいます。")
            self.assertEqual(artifact["raw_responses"][0]["content"], result(background_response(uncertain=True))["content"])
            self.assertEqual(len(client.requests), 1)

    def test_versioned_plan_requires_explicit_mode_protocol_and_existing_settings_bounds(self):
        for change in ("missing", "wrong-mode", "unknown", "legacy-extra", "attempts"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temp:
                plan, args = self.fixture(Path(temp))
                if change == "missing":
                    del plan["protocol"]
                elif change == "wrong-mode":
                    plan["protocol"] = BACKGROUND_PROTOCOL
                elif change == "unknown":
                    plan["protocol"] = "unregistered"
                elif change == "legacy-extra":
                    plan["schema"] = SCHEMA
                else:
                    plan["settings"]["max_attempts"] = 3
                args.session_plan.write_text(json.dumps(plan), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_plan(args.session_plan)
                self.assertFalse(args.output_dir.exists())

    def test_rehashed_accepted_subset_or_typed_helper_drift_cannot_bypass_full_derivation(self):
        with tempfile.TemporaryDirectory() as temp:
            _, args = self.fixture(Path(temp))
            self.assertEqual(self.run_fake(args, [result(self.proposals(mixed=True))])[0], 0)
            path = args.output_dir / "preparation-options.json"
            original = json.loads(path.read_text(encoding="utf-8"))
            ledger = args.output_dir / "ledger.jsonl"
            original_ledger = ledger.read_text(encoding="utf-8")
            for change in ("subset", "count-bool", "zero-int", "context", "raw-response", "cache-bool", "ledger-response"):
                with self.subTest(change=change):
                    artifact = deepcopy(original)
                    row = json.loads(original_ledger)
                    prep = artifact["preparations"][0]
                    if change == "subset":
                        prep["proposals"] = prep["proposals"][:1]
                        prep["returned_count"], prep["declined_count"] = 1, 0
                    elif change == "count-bool":
                        prep["accepted_count"] = True
                    elif change == "zero-int":
                        prep["zero_eligible_glossary"] = 0
                    elif change == "context":
                        prep["source_context"][0]["text"] = "変更"
                    elif change == "raw-response":
                        artifact["raw_responses"][0]["content"] = '{"terms":[]}'
                    elif change == "cache-bool":
                        artifact["cache_reset"]["first_response_cache_n"] = False
                    elif change == "ledger-response":
                        row["attempts"][0]["response"]["content"] = '{"terms":[]}'
                    row["preparation"] = deepcopy(prep)
                    ledger.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
                    artifact["cost_artifacts"]["ledger.jsonl"] = digest(ledger)
                    path.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        load_options(path, digest(path))
            ledger.write_bytes(original_ledger.encode("utf-8"))
            path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
            self.assertTrue(self.options(args)["complete"])

    def test_new_protocol_keeps_capacity_oom_cache_stopped_tails(self):
        cases = (([ValueError("CUDA_ERROR_OUT_OF_MEMORY")], 7, "oom"),
                 ([result(self.proposals(), timings={"cache_n": 3})], 7, "cache"),
                 ([result(self.proposals())], 6081, "budget"))
        for outputs, tokens, reason in cases:
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as temp:
                _, args = self.fixture(Path(temp), scenes=[source_scene(), source_scene("scene-b")])
                code, client = self.run_fake(args, outputs, tokens)
                self.assertEqual(code, 1)
                tail = json.loads((args.output_dir / "schedule.jsonl").read_text(encoding="utf-8"))
                self.assertEqual(tail["scene_id"], "scene-b")
                self.assertEqual(tail["reason"], reason)
                self.assertEqual(len(client.requests), 0 if reason == "budget" else 1)


if __name__ == "__main__":
    unittest.main()
