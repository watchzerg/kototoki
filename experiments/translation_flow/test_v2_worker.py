"""Offline contracts for independent v2 protocols, auxiliary costs and recovery."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from experiments.translation_demo import adapters
from . import v2_recipes as recipes
from .test_worker import FakeClient, budget, window
from .v2_worker import (CANDIDATE, SCHEMA, execute_plan, load_plan, object_hash,
                        run_window, sha256, source_token_counts)


def settings(recipe="c0", **changes):
    return {"label": recipe, "recipe": recipe, "sampling": "official", "cache_prompt": True,
            "n_predict": 4096, "seed": 20261008, "max_attempts": 2, **changes}


def result(content, **changes):
    return {"content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
            "tokens_predicted": 10, "tokens_evaluated": 7, "timings": {"cache_n": 0}, **changes}


def translated(key="a", text="明天不去。", **changes):
    return result({"translations": {key + "-1": text}}, **changes)


def pair_window():
    return {"id": "pair", "source_language": "ja", "target_language": "zh-Hans",
            "context": [{"id": "x1", "text": "もし雨なら"}, {"id": "x2", "text": "出かけません。"}],
            "translate_ids": ["x1", "x2"]}


class V2WorkerTests(unittest.TestCase):
    def run_one(self, outputs=None, *, item=None, source=None, limits=None, tokens=7):
        client = FakeClient(outputs or [translated()], tokens=tokens)
        cache = {"verified": False, "first_response_checked": False}
        limits = limits or budget(max_estimated_tokens=200000)
        row = run_window(client, source or window(), item or settings(), 8192, limits, cache)
        return row, client, limits, cache

    def test_c0_exact_native_prompt_and_independent_official_cache(self):
        self.assertEqual(recipes.render_window("c0", window()), adapters.render("hy-mt2-30b", window()))
        row, client, _, cache = self.run_one()
        self.assertEqual(row["status"], "delivered")
        request = client.requests[0]
        self.assertTrue(request["cache_prompt"])
        self.assertEqual(request["n_predict"], 4096)
        self.assertEqual(request["temperature"], .7)
        self.assertEqual(request["seed"], 20261008)
        self.assertEqual(request["min_p"], 0)
        self.assertEqual(request["samplers"], ["temperature"])
        self.assertTrue(cache["verified"])
        off = recipes.completion_request(settings("joint-json", cache_prompt=False), [1], ["a-1"])
        self.assertFalse(off["cache_prompt"])

    def test_f3_only_changes_joint_understanding_instruction(self):
        baseline = recipes.render_window("c0", window())
        joint = recipes.render_window("joint-json", window())
        start = "【只读日文上下文】"
        self.assertEqual(baseline[baseline.index(start):], joint[joint.index(start):])
        self.assertIn("先共同理解", joint)
        row, client, _, _ = self.run_one(item=settings("joint-json"))
        self.assertEqual(row["status"], "delivered")
        self.assertIn("grammar", client.requests[0])

    def test_f4_genuine_id_text_protocol_and_strict_failures(self):
        row, client, _, _ = self.run_one([result("[[a-1]]\n明天\n不去。")], item=settings("id-text"))
        self.assertEqual(row["translations"], {"a-1": "明天\n不去。"})
        self.assertNotIn("grammar", client.requests[0])
        for content in ("解释\n[[a-1]]\n明天", "[[wrong]]\n明天", "[[a-1]]\n明天\n[[a-1]]\n明天",
                        "[[a-1]]\n", "```\n[[a-1]]\n明天\n```", "[[a-1]]\n明天\n\n不去"):
            with self.subTest(content=content):
                with self.assertRaises(ValueError):
                    recipes.parse_id_text(content, ["a-1"])

    def test_f5_actual_three_calls_exact_remapping_and_all_costs(self):
        plan = {"units": [{"id": "u1", "source_ids": ["x1", "x2"], "evidence_ids": ["x1", "x2"], "uncertain": False}]}
        mapping = {"segments": [{"unit_id": "u1", "source_id": "x1", "start": 0, "end": 5},
                                {"unit_id": "u1", "source_id": "x2", "start": 5, "end": 9}]}
        row, client, limits, _ = self.run_one([result(plan), result({"translations": {"u1": "如果下雨，就不出门"}}), result(mapping)],
                                             item=settings("semantic"), source=pair_window())
        self.assertEqual(row["status"], "delivered", row)
        self.assertEqual(row["translations"], {"x1": "如果下雨，", "x2": "就不出门"})
        self.assertEqual(limits.translation_calls, 3)
        self.assertEqual(limits.estimated_tokens, 3 * (7 + 4096))
        self.assertEqual([attempt["stage"] for attempt in row["attempts"]],
                         ["source-planning", "joint-unit-translation", "semantic-remapping"])
        self.assertIn("source_span_to_target_span", row)
        self.assertEqual(len(client.requests), 3)

    def test_id_text_flex_is_explicit_new_contract_with_no_json_grammar(self):
        row, client, _, _ = self.run_one([result("[[a-1]]明天\n不去。")], item=settings("id-text-flex"))
        self.assertEqual(row["translations"], {"a-1": "明天\n不去。"})
        self.assertEqual(row["native_protocol"], "id-text-exact-markers-flex-v1")
        self.assertNotIn("grammar", client.requests[0])
        self.assertIn("两种布局均有效", recipes.render_window("id-text-flex", window()))
        with self.assertRaises(ValueError):
            recipes.parse_id_text("[[a-1]]明天", ["a-1"])

    def test_semantic_anchors_singletons_skip_mapper_and_record_zero_auxiliary_cost(self):
        plan = {"units": [{"id": "u1", "source_ids": ["a-1"], "evidence_ids": ["a-1"], "uncertain": False}]}
        row, client, limits, _ = self.run_one([result(plan), result({"translations": {"u1": "明天不去。"}})],
                                             item=settings("semantic-anchors"))
        self.assertEqual(row["status"], "delivered", row)
        self.assertEqual(row["translations"], {"a-1": "明天不去。"})
        self.assertEqual(limits.translation_calls, 2)
        self.assertEqual(len(client.requests), 2)
        self.assertFalse(row["mapping_cost"]["model_mapping_required"])
        for key in ("completion_calls", "elapsed_seconds", "generation_seconds", "input_tokens", "output_tokens"):
            self.assertEqual(row["mapping_cost"][key], 0)
        self.assertEqual(row["mapping_provenance"]["deterministic_singleton_unit_ids"], ["u1"])

    def test_semantic_anchors_exact_native_substrings_and_failed_mapping_costs(self):
        plan = {"units": [{"id": "u1", "source_ids": ["x1", "x2"], "evidence_ids": ["x1", "x2"], "uncertain": False}]}
        anchors = {"segments": [{"unit_id": "u1", "source_id": "x1", "start_anchor": "如果下雨"},
                                {"unit_id": "u1", "source_id": "x2", "start_anchor": "就不出门"}]}
        for response, status in ((anchors, "delivered"), ({"unresolved": True, "reason": "无法确定归属"}, "mapping_unjudgeable")):
            row, client, limits, _ = self.run_one(
                [result(plan), result({"translations": {"u1": "如果下雨，就不出门"}}), result(response)],
                item=settings("semantic-anchors", max_attempts=1), source=pair_window())
            self.assertEqual(row["status"], status, row)
            self.assertEqual(limits.translation_calls, 3)
            self.assertEqual(row["mapping_cost"]["completion_calls"], 1)
            self.assertEqual(row["mapping_cost"]["output_tokens"], 10)
            self.assertNotIn("grammar", client.requests[2])
            if status == "delivered":
                self.assertEqual(row["translations"], {"x1": "如果下雨，", "x2": "就不出门"})
                self.assertTrue(row["mapping_provenance"]["native_text_unchanged"])
            else:
                self.assertEqual(row["translations"], {})

    def test_new_recipes_load_and_semantic_review_remains_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for recipe in ("id-text-flex", "semantic-anchors", "semantic-structured", "semantic-partition"):
                _, args = self.make_plan(root, item=settings(recipe))
                self.assertEqual(load_plan(args.session_plan)[1][0][0]["recipe"], recipe)
            for recipe in ("semantic-anchors", "semantic-structured", "semantic-partition"):
                _, args = self.make_plan(root, item=settings(recipe, review=True))
                with self.assertRaisesRegex(ValueError, "Semantic review"):
                    load_plan(args.session_plan)

    def test_structured_mixed_units_use_ordered_grammars_and_immutable_native_mapping(self):
        source = pair_window()
        source["context"].append({"id": "x3", "text": "また明日。"})
        source["translate_ids"].append("x3")
        decisions = {"boundaries": [
            {"join": True, "evidence_ids": ["x1", "x2"], "uncertain": False},
            {"join": False, "evidence_ids": ["x2", "x3"], "uncertain": True}]}
        native = {"translations": {"u1": "如果下雨，就不出门", "u2": "明天见。"}}
        mapping = {"segments": [{"unit_id": "u1", "source_id": "x1", "text": "如果下雨，"},
                                {"unit_id": "u1", "source_id": "x2", "text": "就不出门"}]}
        row, client, limits, cache = self.run_one([result(decisions), result(native), result(mapping)],
                                                item=settings("semantic-structured"), source=source)
        self.assertEqual(row["status"], "delivered", row)
        self.assertEqual(row["translations"], {"x1": "如果下雨，", "x2": "就不出门", "x3": "明天见。"})
        self.assertEqual(row["native_unit_translations"], native["translations"])
        self.assertEqual([unit["source_ids"] for unit in row["semantic_plan"]["units"]], [["x1", "x2"], ["x3"]])
        self.assertTrue(row["semantic_plan"]["units"][0]["uncertain"])
        self.assertEqual(row["planning_provenance"]["protocol"], "semantic-ordered-boundary-decisions-v1")
        self.assertEqual(row["mapping_provenance"]["protocol"], "semantic-immutable-substring-partition-v1")
        self.assertFalse(row["mapping_provenance"]["semantic_correspondence_verified"])
        self.assertIn("boundary0 ::=", client.requests[0]["grammar"])
        self.assertNotIn("boundary0 ::=", client.requests[1]["grammar"])
        self.assertIn("segment0 ::=", client.requests[2]["grammar"])
        self.assertEqual(row["planning_cost"]["completion_calls"], 1)
        self.assertEqual(row["mapping_cost"]["completion_calls"], 1)
        self.assertEqual(limits.translation_calls, 3)
        self.assertEqual(limits.estimated_tokens, 3 * (7 + 4096))
        self.assertTrue(cache["verified"])

    def test_structured_single_target_generates_once_and_verifies_first_native_cache(self):
        for cache_n in (0, 2):
            row, client, limits, cache = self.run_one(
                [result({"translations": {"u1": "明天不去。"}}, timings={"cache_n": cache_n})],
                item=settings("semantic-structured"))
            self.assertEqual(limits.translation_calls, 1)
            self.assertEqual(len(client.requests), 1)
            self.assertFalse(row["planning_cost"]["model_planning_required"])
            self.assertEqual(row["planning_cost"]["completion_calls"], 0)
            self.assertEqual(row["planning_cost"]["elapsed_seconds"], 0)
            self.assertTrue(row["planning_provenance"]["deterministic_single_target"])
            self.assertEqual(row["status"], "delivered" if cache_n == 0 else "translation_failed")
            self.assertEqual(cache["verified"], cache_n == 0)
            if cache_n == 0:
                for key in ("completion_calls", "elapsed_seconds", "generation_seconds", "input_tokens", "output_tokens"):
                    self.assertEqual(row["mapping_cost"][key], 0)
                self.assertEqual(row["translations"], {"a-1": "明天不去。"})
            else:
                self.assertEqual(row["error_kind"], "cache")
                self.assertEqual(row["translations"], {})

    def test_structured_all_breaks_still_plan_but_skip_mapping(self):
        decisions = {"boundaries": [{"join": False, "evidence_ids": ["x1", "x2"], "uncertain": False}]}
        row, client, limits, _ = self.run_one([result(decisions), result({"translations": {"u1": "如果下雨", "u2": "就不出门"}})],
                                             item=settings("semantic-structured"), source=pair_window())
        self.assertEqual(row["status"], "delivered", row)
        self.assertEqual(len(client.requests), 2)
        self.assertEqual(limits.translation_calls, 2)
        self.assertTrue(row["planning_cost"]["model_planning_required"])
        self.assertFalse(row["mapping_cost"]["model_mapping_required"])
        self.assertEqual(row["mapping_cost"]["completion_calls"], 0)

    def test_structured_planning_failure_and_budget_stop_retain_real_costs(self):
        decisions = {"boundaries": [{"join": True, "evidence_ids": ["x1", "x2"], "uncertain": False}]}
        unresolved = result({"unresolved": True, "reason": "无法可靠规划"})
        row, client, limits, _ = self.run_one([unresolved, unresolved], item=settings("semantic-structured"), source=pair_window())
        self.assertEqual(row["status"], "translation_failed")
        self.assertEqual(row["failure_stage"], "source-planning")
        self.assertEqual(row["planning_cost"]["completion_calls"], 2)
        self.assertEqual(row["planning_cost"]["output_tokens"], 20)
        self.assertEqual(client.requests[0], client.requests[1])
        self.assertEqual(limits.translation_calls, 2)
        self.assertNotIn("native_unit_translations", row)
        row, client, limits, _ = self.run_one([result(decisions)], item=settings("semantic-structured"),
                                             source=pair_window(), limits=budget(max_translation_calls=1))
        self.assertEqual(row["error_kind"], "budget")
        self.assertEqual(row["planning_cost"]["completion_calls"], 1)
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(limits.translation_calls, 1)

    def test_structured_mapping_retry_never_rewrites_native_or_hides_failed_costs(self):
        decisions = {"boundaries": [{"join": True, "evidence_ids": ["x1", "x2"], "uncertain": False}]}
        native = {"translations": {"u1": "如果下雨，就不出门"}}
        good = {"segments": [{"unit_id": "u1", "source_id": "x1", "text": "如果下雨，"},
                             {"unit_id": "u1", "source_id": "x2", "text": "就不出门"}]}
        bad = deepcopy(good)
        bad["segments"][1]["text"] = "就出门"
        for mapper_outputs, status in (([bad, good], "delivered"), ([bad, bad], "mapping_unjudgeable")):
            row, client, limits, _ = self.run_one([result(decisions), result(native), *[result(obj) for obj in mapper_outputs]],
                                                 item=settings("semantic-structured"), source=pair_window())
            self.assertEqual(row["status"], status, row)
            self.assertEqual(row["native_unit_translations"], native["translations"])
            self.assertEqual(row["mapping_cost"]["completion_calls"], 2)
            self.assertEqual(row["mapping_cost"]["output_tokens"], 20)
            self.assertEqual(limits.translation_calls, 4)
            self.assertEqual(client.requests[2], client.requests[3])
            if status != "delivered":
                self.assertEqual(row["translations"], {})
                self.assertNotIn("source_span_to_target_span", row)

    def test_partition_dispatch_uses_finite_planning_and_exact_native_state_grammar(self):
        from . import v2_semantic_partition_grammar as partition
        source = pair_window()
        source["context"].append({"id": "x3", "text": "また明日。"})
        source["translate_ids"].append("x3")
        decisions = {"boundaries": [
            {"join": True, "evidence_ids": ["x1", "x2"], "uncertain": False},
            {"join": False, "evidence_ids": ["x2", "x3"], "uncertain": True}]}
        native = {"translations": {"u1": ' 甲"\\🌧️\t乙 ', "u2": "明天见。"}}
        parts = [native["translations"]["u1"][:6], native["translations"]["u1"][6:]]
        mapping = {"segments": [{"unit_id": "u1", "source_id": sid, "text": text}
                                for sid, text in zip(["x1", "x2"], parts)]}
        row, client, limits, _ = self.run_one([result(decisions), result(native), result(mapping)],
                                             item=settings("semantic-partition"), source=source)
        self.assertEqual(row["status"], "delivered", row)
        self.assertEqual([unit["source_ids"] for unit in row["semantic_plan"]["units"]],
                         [["x1", "x2"], ["x3"]])
        self.assertEqual(row["translations"], {"x1": parts[0], "x2": parts[1], "x3": "明天见。"})
        self.assertEqual(row["native_unit_translations"], native["translations"])
        self.assertEqual(client.requests[0]["grammar"], partition.planning_grammar(source))
        self.assertIn(r"ws ::= [ \t\n\r]?", client.requests[0]["grammar"])
        built = partition.build_mapping_grammar(source, row["semantic_plan"], native["translations"])
        self.assertEqual(client.requests[2]["grammar"], built["grammar"])
        self.assertIn("u0-c0-p0-b0 ::=", client.requests[2]["grammar"])
        self.assertEqual(row["mapping_grammar_build"]["diagnostics"], built["diagnostics"])
        self.assertEqual(row["planning_provenance"]["protocol"], partition.PLANNING_PROTOCOL)
        self.assertEqual(row["mapping_provenance"]["protocol"], partition.PROTOCOL)
        self.assertFalse(row["mapping_provenance"]["semantic_correspondence_verified"])
        self.assertEqual(limits.translation_calls, 3)
        self.assertEqual(row["mapping_cost"]["completion_calls"], 1)
        self.assertGreaterEqual(row["mapping_cost"]["elapsed_seconds"],
                                row["mapping_grammar_build"]["elapsed_seconds"])
        self.assertEqual(row["mapping_cost"]["grammar_build_seconds"],
                         row["mapping_grammar_build"]["elapsed_seconds"])
        self.assertEqual(row["attempts"][0]["prompt"], partition.planning_prompt(source))
        self.assertEqual(row["attempts"][2]["prompt"],
                         partition.mapping_prompt(source, row["semantic_plan"], native["translations"]))
        self.assertEqual(row["attempts"][2]["response"]["content"], result(mapping)["content"])

    def test_partition_single_target_and_all_singletons_use_zero_call_shortcuts(self):
        from . import v2_semantic_partition_grammar as partition
        decisions = {"boundaries": [{"join": False, "evidence_ids": ["x1", "x2"], "uncertain": False}]}
        fixtures = [(window(), [result({"translations": {"u1": "明天不去。"}})], 1),
                    (pair_window(), [result(decisions), result({"translations": {"u1": "如果下雨", "u2": "就不出门"}})], 2)]
        for source, responses, expected_calls in fixtures:
            with self.subTest(expected_calls=expected_calls):
                row, client, limits, _ = self.run_one(responses, item=settings("semantic-partition"), source=source)
                self.assertEqual(row["status"], "delivered", row)
                self.assertEqual(limits.translation_calls, expected_calls)
                self.assertEqual(len(client.requests), expected_calls)
                self.assertEqual(row["mapping_provenance"]["protocol"], partition.PROTOCOL)
                self.assertFalse(row["mapping_cost"]["model_mapping_required"])
                self.assertNotIn("mapping_grammar_build", row)
                for key in ("completion_calls", "elapsed_seconds", "generation_seconds", "input_tokens", "output_tokens"):
                    self.assertEqual(row["mapping_cost"][key], 0)
                if expected_calls == 1:
                    self.assertFalse(row["planning_cost"]["model_planning_required"])
                    for key in ("completion_calls", "elapsed_seconds", "generation_seconds", "input_tokens", "output_tokens"):
                        self.assertEqual(row["planning_cost"][key], 0)
                else:
                    self.assertTrue(row["planning_cost"]["model_planning_required"])
                    self.assertEqual(row["planning_cost"]["completion_calls"], 1)

    def test_partition_failed_mapper_costs_and_raw_data_survive_identical_retry(self):
        decisions = {"boundaries": [{"join": True, "evidence_ids": ["x1", "x2"], "uncertain": False}]}
        native = {"translations": {"u1": "如果下雨，就不出门"}}
        good = {"segments": [{"unit_id": "u1", "source_id": "x1", "text": "如果下雨，"},
                             {"unit_id": "u1", "source_id": "x2", "text": "就不出门"}]}
        bad = deepcopy(good)
        bad["segments"][1]["text"] = "就出门"
        for outputs, status in (([bad, good], "delivered"), ([bad, bad], "mapping_unjudgeable")):
            with self.subTest(status=status):
                row, client, limits, _ = self.run_one([result(decisions), result(native), *map(result, outputs)],
                                                     item=settings("semantic-partition"), source=pair_window())
                self.assertEqual(row["status"], status, row)
                self.assertEqual(row["native_unit_translations"], native["translations"])
                self.assertEqual(limits.translation_calls, 4)
                self.assertEqual(row["mapping_cost"]["completion_calls"], 2)
                self.assertEqual(row["mapping_cost"]["output_tokens"], 20)
                self.assertEqual(row["mapping_cost"]["input_tokens"], 14)
                self.assertEqual(client.requests[2], client.requests[3])
                self.assertEqual(row["attempts"][2]["response"]["content"], result(bad)["content"])
                self.assertEqual(row["attempts"][2]["status"], "failed")
                self.assertEqual(row["attempts"][2]["prompt"], row["attempts"][3]["prompt"])
                if status != "delivered":
                    self.assertEqual(row["translations"], {})
                    self.assertNotIn("source_span_to_target_span", row)

    def test_partition_build_limit_failure_retains_native_and_counts_build_without_dispatch(self):
        decisions = {"boundaries": [{"join": True, "evidence_ids": ["x1", "x2"], "uncertain": False}]}
        native = {"translations": {"u1": "如果下雨，就不出门"}}
        for limits in ({"max_states": 1, "max_grammar_bytes": 16777216},
                       {"max_states": 100000, "max_grammar_bytes": 1}):
            with self.subTest(limits=limits):
                row, client, reserved, _ = self.run_one([result(decisions), result(native)],
                    item=settings("semantic-partition", partition_grammar_limits=limits), source=pair_window())
                self.assertEqual(row["status"], "mapping_unjudgeable", row)
                self.assertEqual(row["error_kind"], "grammar_complexity")
                self.assertEqual(row["failure_stage"], "semantic-remapping")
                self.assertEqual(row["native_unit_translations"], native["translations"])
                self.assertEqual(row["translations"], {})
                self.assertNotIn("source_span_to_target_span", row)
                self.assertEqual(len(client.requests), 2)
                self.assertEqual(reserved.translation_calls, 2)
                self.assertEqual(row["mapping_cost"]["completion_calls"], 0)
                self.assertEqual(row["mapping_cost"]["input_tokens"], 0)
                self.assertEqual(row["mapping_cost"]["output_tokens"], 0)
                self.assertEqual(row["mapping_cost"]["generation_seconds"], 0)
                build = row["mapping_grammar_build"]
                self.assertEqual(build["status"], "failed")
                self.assertEqual(build["limits"], limits)
                self.assertFalse(build["native_text_truncated"])
                self.assertIn("exceeded_limit", build["diagnostics"])
                self.assertGreater(build["elapsed_seconds"], 0)
                self.assertEqual(row["mapping_cost"]["elapsed_seconds"], build["elapsed_seconds"])
                auxiliary_attempts = [a for a in row["attempts"] if a["stage"] != "joint-unit-translation"]
                self.assertAlmostEqual(row["auxiliary_seconds"],
                                       sum(a["elapsed_seconds"] for a in auxiliary_attempts) + build["elapsed_seconds"])

    def test_partition_planning_failure_records_cost_and_never_builds_mapper(self):
        failed = result({"unresolved": True, "reason": "无法可靠规划"})
        row, client, limits, _ = self.run_one([failed, failed], item=settings("semantic-partition"), source=pair_window())
        self.assertEqual(row["status"], "translation_failed", row)
        self.assertEqual(row["planning_cost"]["completion_calls"], 2)
        self.assertEqual(row["planning_cost"]["output_tokens"], 20)
        self.assertEqual(limits.translation_calls, 2)
        self.assertEqual(client.requests[0], client.requests[1])
        self.assertNotIn("native_unit_translations", row)
        self.assertNotIn("mapping_grammar_build", row)
        self.assertEqual(row["attempts"][0]["response"]["content"], failed["content"])

    def test_partition_grammar_limits_require_registered_recipe_and_positive_exact_keys(self):
        good = {"max_states": 100, "max_grammar_bytes": 10000}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, args = self.make_plan(root, item=settings("semantic-partition", partition_grammar_limits=good))
            self.assertEqual(load_plan(args.session_plan)[1][0][0]["partition_grammar_limits"], good)
            for recipe, bad in (("semantic-structured", good), ("semantic-partition", {"max_states": 1}),
                                ("semantic-partition", {**good, "extra": 1}),
                                ("semantic-partition", {**good, "max_states": True}),
                                ("semantic-partition", {**good, "max_grammar_bytes": 0})):
                _, args = self.make_plan(root, item=settings(recipe, partition_grammar_limits=bad))
                with self.assertRaisesRegex(ValueError, "partition_grammar_limits"):
                    load_plan(args.session_plan)

    def test_semantic_mapping_failure_retains_native_no_srt_fallback(self):
        plan = {"units": [{"id": "u1", "source_ids": ["x1", "x2"], "evidence_ids": ["x1"], "uncertain": True}]}
        row, _, limits, _ = self.run_one([result(plan), result({"translations": {"u1": "如果下雨，就不出门"}}),
                                         result({"unresolved": True, "reason": "无法确定归属"})],
                                        item=settings("semantic", max_attempts=1), source=pair_window())
        self.assertEqual(row["status"], "mapping_unjudgeable")
        self.assertEqual(row["translations"], {})
        self.assertIn("native_unit_translations", row)
        self.assertEqual(limits.translation_calls, 3)

    def test_source_review_records_before_after_and_auxiliary_call(self):
        row, _, limits, _ = self.run_one([translated(text="明天去。"), translated()], item=settings("joint-json", review=True))
        self.assertEqual(row["before_review"], {"a-1": "明天去。"})
        self.assertEqual(row["translations"], {"a-1": "明天不去。"})
        self.assertEqual(limits.translation_calls, 2)
        self.assertEqual(row["attempts"][1]["stage"], "source-review")

    def test_source_cards_require_evidence_and_c0_rejects_augmentation(self):
        item = settings("joint-json", terms=[{"source": "明日", "translation": "明天", "evidence_ids": ["a-1"], "origin": "source-preparation"}],
                        background=[{"text": "讨论明天的安排", "evidence_ids": ["a-1"], "origin": "source-preparation"}], style="natural-dialogue")
        recipes.validate_options(item, {"a-1"})
        self.assertIn("讨论明天", recipes.render_window("joint-json", window(), item))
        self.assertEqual(recipes.source_options(item, window("b")), "使用自然简洁的中文对白，保留口语语气，不删去事实、不改变关系或原文歧义。")
        item["terms"][0]["origin"] = "reference"
        with self.assertRaises(ValueError):
            recipes.validate_options(item, {"a-1"})
        with self.assertRaisesRegex(ValueError, "C0"):
            recipes.validate_options(settings(style="natural-dialogue"), {"a-1"})

    def test_base_json_option_free_single_changes_without_joint_prompt(self):
        self.assertEqual(recipes.render_window("base-json", window()), recipes.render_window("c0", window()))
        prompt = recipes.render_window("base-json", window(), settings("base-json", style="natural-dialogue"))
        self.assertIn("每个值独立对应一个 ID", prompt)
        self.assertNotIn("先共同理解", prompt)
        self.assertLess(prompt.index("使用自然简洁"), prompt.index("<｜hy_Assistant｜>"))
        row, _, limits, _ = self.run_one([translated(), translated()], item=settings("base-json", review=True))
        self.assertEqual(row["status"], "delivered")
        self.assertEqual(limits.translation_calls, 2)

    def test_empty_cache_evidence_missing_nonzero_and_wrong_type_stop(self):
        for value in (None, 5, False, "0"):
            row, client, _, cache = self.run_one([translated(timings={} if value is None else {"cache_n": value})])
            self.assertEqual(row["error_kind"], "cache")
            self.assertEqual(row["translations"], {})
            self.assertEqual(len(client.requests), 1)
            self.assertFalse(cache["verified"])
        # Retained-state size is deliberately not mistaken for cache reuse.
        row, _, _, cache = self.run_one([translated(tokens_cached=200, timings={"cache_n": 0})])
        self.assertEqual(row["status"], "delivered")
        self.assertTrue(cache["verified"])

    def test_auxiliary_budget_stops_before_next_dispatch(self):
        plan = {"units": [{"id": "u1", "source_ids": ["a-1"], "evidence_ids": ["a-1"], "uncertain": False}]}
        row, client, limits, _ = self.run_one([result(plan)], item=settings("semantic"), limits=budget(max_translation_calls=1))
        self.assertEqual(row["error_kind"], "budget")
        self.assertEqual(row["translations"], {})
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(limits.translation_calls, 1)

    def test_context_limit_never_truncates_or_dispatches(self):
        row, client, _, _ = self.run_one(tokens=4033)
        self.assertEqual(row["status"], "setup_failed")
        self.assertEqual(client.requests, [])
        self.assertIn("context_budget", row["reason"])

    def test_failed_parse_retries_identical_request_and_counts_costs(self):
        row, client, limits, _ = self.run_one([result({"translations": {"wrong": "错"}}), translated()])
        self.assertEqual(row["status"], "delivered")
        self.assertEqual(client.requests[0], client.requests[1])
        self.assertEqual(limits.translation_calls, 2)

    def test_explicit_oom_stops_but_translated_oom_phrase_is_data(self):
        row, client, _, _ = self.run_one([ValueError("CUDA_ERROR_OUT_OF_MEMORY")])
        self.assertEqual(row["error_kind"], "oom")
        self.assertEqual(len(client.requests), 1)
        row, _, _, _ = self.run_one([translated(text="out of memory")])
        self.assertEqual(row["status"], "delivered")
        row, _, _, _ = self.run_one([result("", error={"message": "CUDA_ERROR_OUT_OF_MEMORY"})])
        self.assertEqual(row["error_kind"], "oom")

    def make_plan(self, root, *, windows=None, item=None, **changes):
        windows = windows or [window()]
        inputs = root / "source.jsonl"
        inputs.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in windows), encoding="utf-8")
        item = {**(item or settings()), "inputs": "source.jsonl", "input_sha256": sha256(inputs)}
        plan = {"schema": SCHEMA, "stage": "qualification", "lane": "P-flow",
                "budgets": budget(max_estimated_tokens=200000).limits,
                "experiment_identity": {"source_manifest_sha256": "a" * 64, "split": "screen-a", "seed": item["seed"],
                                        "recipe_id": item["label"], "source_order_sha256": object_hash([row["id"] for row in windows])},
                "cache_reset": {"method": "fresh-managed-server", "verification": "first-completion-cache-n-zero"},
                "workloads": [item], **changes}
        path = root / "plan.json"
        path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        args = argparse.Namespace(candidate=CANDIDATE, session_plan=path, output_dir=root / "out",
                                  server_url="http://127.0.0.1:8080", context_size=8192,
                                  engine_manifest=root / "engine.json", asset_manifest=[], stop_on_oom=True)
        return plan, args

    def identity(self, args):
        return {"asset": {"id": CANDIDATE, "sha256": "a" * 64},
                "engine": {"model_path": "fake.gguf", "server_pid": 1234, "command": ["server", "-np", "1"],
                           "build": 11429, "context_size": 8192, "model_sha256": "a" * 64},
                "engine_manifest_sha256": "a" * 64, "template_sha256": "b" * 64}

    def test_v2_no_legacy_caps_and_source_firewall_order_seed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, args = self.make_plan(root, windows=[window(f"a{i}") for i in range(96)])
            self.assertEqual(len(load_plan(args.session_plan)[1][0][2]), 96)
            bad = {**window(), "reference": "禁止读取"}
            _, args = self.make_plan(root, windows=[bad])
            with self.assertRaisesRegex(ValueError, "model-input"):
                load_plan(args.session_plan)
            plan, args = self.make_plan(root)
            plan["experiment_identity"]["source_order_sha256"] = "b" * 64
            args.session_plan.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "order"):
                load_plan(args.session_plan)

    def test_v2_rejects_multiple_workloads_and_old_schema(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan, args = self.make_plan(root)
            plan["workloads"].append(deepcopy(plan["workloads"][0]))
            args.session_plan.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "own server"):
                load_plan(args.session_plan)
            plan["schema"] = "hy30-flow-session-v1"
            args.session_plan.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "v2"):
                load_plan(args.session_plan)

    def test_worker_journal_checkpoint_failures_and_tails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, args = self.make_plan(root, windows=[window("a"), window("b")])
            client = FakeClient([ValueError("CUDA_ERROR_OUT_OF_MEMORY")])
            self.assertEqual(execute_plan(args, lambda *a, **k: client, self.identity), 1)
            target = args.output_dir / "c0"
            ledger = [json.loads(line) for line in (target / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(ledger), 1)
            self.assertEqual(ledger[0]["error_kind"], "oom")
            schedule = json.loads((target / "schedule.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(schedule["window_id"], "b")
            checkpoint = json.loads((args.output_dir / "checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["budget"]["translation_calls"], 1)
            self.assertEqual(checkpoint["completed"], [])
            self.assertTrue((target / "dispatch-journal.jsonl").read_text(encoding="utf-8").strip())
            with self.assertRaises(FileExistsError):
                execute_plan(args, lambda *a, **k: client, self.identity)

    def test_resume_reuses_only_hash_verified_successes_no_new_timings(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan, args = self.make_plan(root, windows=[window("a"), window("b")])
            client = FakeClient([translated(), ValueError("CUDA_ERROR_OUT_OF_MEMORY")])
            self.assertEqual(execute_plan(args, lambda *a, **k: client, self.identity), 1)
            checkpoint = args.output_dir / "checkpoint.json"
            plan["resume"] = {"checkpoint": str(checkpoint), "sha256": sha256(checkpoint)}
            args.session_plan.write_text(json.dumps(plan), encoding="utf-8")
            args.output_dir = root / "resume"
            fresh = FakeClient([translated("b")])
            self.assertEqual(execute_plan(args, lambda *a, **k: fresh, self.identity), 0)
            self.assertEqual(len(fresh.requests), 1)
            reused = json.loads((args.output_dir / "c0/window-a.json").read_text(encoding="utf-8"))
            self.assertTrue(reused["reused_not_new_measurement"])
            self.assertIsNone(reused["elapsed_seconds"])
            completion = json.loads((args.output_dir / "worker-completion.json").read_text(encoding="utf-8"))
            self.assertFalse(completion["performance_valid_for_fresh_flow"])
            self.assertEqual(completion["budget"]["translation_calls"], 3)
            self.assertEqual(completion["inherited_budget"]["translation_calls"], 2)

    def test_resume_recipe_or_completed_artifact_mutation_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan, args = self.make_plan(root)
            self.assertEqual(execute_plan(args, lambda *a, **k: FakeClient([translated()]), self.identity), 0)
            checkpoint = args.output_dir / "checkpoint.json"
            plan["resume"] = {"checkpoint": str(checkpoint), "sha256": sha256(checkpoint)}
            plan["workloads"][0]["recipe"] = "joint-json"
            args.session_plan.write_text(json.dumps(plan), encoding="utf-8")
            args.output_dir = root / "resume"
            with self.assertRaisesRegex(ValueError, "identity differs"):
                execute_plan(args, lambda *a, **k: FakeClient([translated()]), self.identity)

    def test_token_count_source_once_per_unique_cue_with_identity_costs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            client = FakeClient(tokens=3)
            counts = source_token_counts(client, [window(), window(), window("b")], self.identity(None), budget(), root / "counts.json")
            report = json.loads((root / "counts.json").read_text(encoding="utf-8"))
            self.assertEqual(report["cue_token_counts"], {"a-1": 3, "b-1": 3})
            self.assertEqual(counts["attempts"], 2)
            self.assertTrue(report["complete"])
            self.assertIn("template_sha256", report)
            self.assertEqual(client.requests, [])

    def test_native_source_target_ranges_are_contiguous_in_frozen_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = pair_window()
            source["translate_ids"] = ["x2", "x1"]
            _, args = self.make_plan(root, windows=[source])
            with self.assertRaisesRegex(ValueError, "contiguous"):
                load_plan(args.session_plan)

    def test_optional_frozen_source_token_count_path_integrates_after_cache_check(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan, args = self.make_plan(root)
            plan["token_count_source"] = {"inputs": "source.jsonl", "input_sha256": sha256(root / "source.jsonl")}
            args.session_plan.write_text(json.dumps(plan), encoding="utf-8")
            client = FakeClient([translated()])
            self.assertEqual(execute_plan(args, lambda *a, **k: client, self.identity), 0)
            counts = json.loads((args.output_dir / "source-token-counts.json").read_text(encoding="utf-8"))
            self.assertEqual(counts["cue_token_counts"], {"a-1": 7})
            complete = json.loads((args.output_dir / "worker-completion.json").read_text(encoding="utf-8"))
            self.assertEqual(complete["source_token_count_cost"]["attempts"], 1)
            self.assertEqual(complete["budget"]["translation_calls"], 1)

    def test_source_token_failure_is_durable_and_not_claimed_complete(self):
        class FailingTokenizer(FakeClient):
            def tokenize(self, prompt):
                raise ValueError("synthetic tokenizer failure")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(ValueError, "tokenizer failure"):
                source_token_counts(FailingTokenizer(), [window()], self.identity(None), budget(), root / "counts.json")
            report = json.loads((root / "counts.json").read_text(encoding="utf-8"))
            self.assertFalse(report["complete"])
            self.assertEqual(report["attempts"][0]["status"], "failed")
            self.assertIn("elapsed_seconds", report["attempts"][0])


if __name__ == "__main__":
    unittest.main()
