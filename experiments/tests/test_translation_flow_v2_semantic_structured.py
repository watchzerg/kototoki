"""Offline source-boundary and immutable substring protocol checks."""

from copy import deepcopy
from itertools import product
import json
import unittest

from experiments.translation_demo import adapters
from experiments.translation_flow import v2_semantic, v2_semantic_structured as structured


class StructuredSemanticTests(unittest.TestCase):
    def setUp(self):
        self.window = {"id": "synthetic", "source_language": "ja", "target_language": "zh-Hans",
                       "context": [{"id": "before", "text": "誰？"}, {"id": "a", "text": "雨が"},
                                   {"id": "b", "text": "降るかも。"}, {"id": "c", "text": "行こう。"}],
                       "translate_ids": ["a", "b", "c"]}
        self.decisions = {"boundaries": [
            {"join": True, "evidence_ids": ["before", "a", "b"], "uncertain": False},
            {"join": False, "evidence_ids": ["b", "c"], "uncertain": True}]}
        self.plan = structured.parse_plan(self.encode(self.decisions), self.window)
        self.native = {"u1": "雨🌧️可能会下。", "u2": "走吧。"}
        self.partition = {"segments": [
            {"unit_id": "u1", "source_id": "a", "text": "雨🌧️"},
            {"unit_id": "u1", "source_id": "b", "text": "可能会下。"}]}

    @staticmethod
    def encode(obj):
        return json.dumps(obj, ensure_ascii=False)

    def planning(self, obj):
        return structured.parse_planning(self.encode(obj), self.window)

    def mapping(self, obj=None, native=None):
        return structured.parse_mapping(self.encode(self.partition if obj is None else obj),
                                        self.window, self.plan, self.native if native is None else native)

    def test_model_boundary_decisions_create_real_joint_units_and_preserve_evidence(self):
        result = self.planning(self.decisions)
        units = result["semantic_plan"]["units"]
        self.assertEqual([u["source_ids"] for u in units], [["a", "b"], ["c"]])
        self.assertEqual([u["id"] for u in units], ["u1", "u2"])
        self.assertTrue(all(u["uncertain"] for u in units))
        self.assertIn("before", units[0]["evidence_ids"])
        evidence = result["planning_provenance"]["ordered_boundaries"]
        self.assertEqual([x["boundary_index"] for x in evidence], [0, 1])
        self.assertEqual([(x["left_source_id"], x["right_source_id"]) for x in evidence], [("a", "b"), ("b", "c")])
        self.assertEqual([x["join"] for x in evidence], [True, False])
        self.assertTrue(result["planning_provenance"]["model_planning_required"])
        self.assertEqual(structured.native_prompt(self.window, self.plan), v2_semantic.native_prompt(self.window, self.plan))

    def test_every_boolean_partition_preserves_order_and_exact_coverage(self):
        for choices in product((False, True), repeat=2):
            decisions = {"boundaries": [dict(row, join=join) for row, join in zip(self.decisions["boundaries"], choices)]}
            units = self.planning(decisions)["semantic_plan"]["units"]
            self.assertEqual([sid for u in units for sid in u["source_ids"]], ["a", "b", "c"])
            self.assertEqual(len(units), 1 + sum(not choice for choice in choices))
        self.window["translate_ids"].reverse()
        self.assertEqual(structured.parse_plan(self.encode(self.decisions), self.window), self.plan)

    def test_single_target_planning_and_mapping_are_recorded_zero_call_shortcuts(self):
        self.window["translate_ids"] = ["a"]
        self.assertFalse(structured.planning_required(self.window))
        result = structured.parse_planning(None, self.window)
        plan = result["semantic_plan"]
        self.assertEqual(plan["units"], [{"id": "u1", "source_ids": ["a"], "evidence_ids": ["a"], "uncertain": False}])
        self.assertTrue(result["planning_provenance"]["deterministic_single_target"])
        self.assertFalse(result["planning_provenance"]["model_planning_required"])
        self.assertFalse(structured.mapping_required(self.window, plan))
        mapped = structured.parse_mapping(None, self.window, plan, {"u1": "雨🌧️"})
        self.assertEqual(mapped["translations"], {"a": "雨🌧️"})
        self.assertFalse(mapped["mapping_provenance"]["model_mapping_required"])
        with self.assertRaisesRegex(ValueError, "skip planning"):
            structured.planning_prompt(self.window)
        with self.assertRaisesRegex(ValueError, "grammar is unnecessary"):
            structured.planning_grammar(self.window)
        with self.assertRaisesRegex(ValueError, "no model planning response"):
            structured.parse_planning('{"boundaries":[]}', self.window)

    def test_join_across_readonly_gap_is_rejected_and_grammar_forces_break(self):
        self.window["translate_ids"] = ["a", "c"]
        decisions = {"boundaries": [dict(self.decisions["boundaries"][0])]}
        with self.assertRaisesRegex(ValueError, "read-only"):
            self.planning(decisions)
        decisions["boundaries"][0]["join"] = False
        self.assertEqual([u["source_ids"] for u in self.planning(decisions)["semantic_plan"]["units"]], [["a"], ["c"]])
        rule = next(line for line in structured.planning_grammar(self.window).splitlines() if line.startswith("boundary0 ::="))
        self.assertIn('ws ":" ws "false"', rule)

    def test_invalid_decision_count_fields_types_evidence_and_duplicate_json_rejected(self):
        for rows in ([], self.decisions["boundaries"][:1], self.decisions["boundaries"] * 2):
            with self.subTest(rows=rows), self.assertRaisesRegex(ValueError, "fixed ordered"):
                self.planning({"boundaries": rows})
        for field, value in (("join", 1), ("uncertain", "true"), ("evidence_ids", []),
                             ("evidence_ids", ["hidden"]), ("evidence_ids", ["a", "a"]),
                             ("evidence_ids", "a")):
            obj = deepcopy(self.decisions)
            obj["boundaries"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.planning(obj)
        obj = deepcopy(self.decisions)
        obj["boundaries"][0]["source_ids"] = ["a", "b"]
        with self.assertRaisesRegex(ValueError, "fields"):
            self.planning(obj)
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            structured.parse_plan('{"boundaries":[],"boundaries":[]}', self.window)
        with self.assertRaisesRegex(ValueError, "explicit semantic boundary"):
            structured.parse_planning(None, self.window)

    def test_substring_partition_preserves_supplementary_unicode_and_singleton(self):
        result = self.mapping()
        self.assertEqual(result["translations"], {"a": "雨🌧️", "b": "可能会下。", "c": "走吧。"})
        self.assertEqual(result["source_span_to_target_span"], [
            {"unit_id": "u1", "source_ids": ["a"], "target_spans": [[0, 3]]},
            {"unit_id": "u1", "source_ids": ["b"], "target_spans": [[3, 8]]},
            {"unit_id": "u2", "source_ids": ["c"], "target_spans": [[0, 3]]}])
        self.assertEqual(result["mapping_provenance"]["deterministic_singleton_unit_ids"], ["u2"])
        self.assertTrue(result["mapping_provenance"]["exact_concatenation_verified"])
        self.assertFalse(result["mapping_provenance"]["semantic_correspondence_verified"])

    def test_repeated_native_phrases_need_no_unique_anchor_or_copy_disambiguation(self):
        native = {"u1": "是。是。", "u2": "走吧。"}
        obj = deepcopy(self.partition)
        for row in obj["segments"]:
            row["text"] = "是。"
        result = self.mapping(obj, native)
        self.assertEqual(result["translations"]["a"], result["translations"]["b"])
        self.assertEqual(result["source_span_to_target_span"][0]["target_spans"], [[0, 2]])
        self.assertEqual(result["source_span_to_target_span"][1]["target_spans"], [[2, 4]])

    def test_punctuation_whitespace_and_combining_characters_are_never_normalized(self):
        native = {"u1": " e\u0301 🌧️\n后面。 ", "u2": " 走吧。\n"}
        obj = deepcopy(self.partition)
        obj["segments"][0]["text"] = " e\u0301 🌧️\n"
        obj["segments"][1]["text"] = "后面。 "
        result = self.mapping(obj, native)
        self.assertEqual(result["translations"]["a"] + result["translations"]["b"], native["u1"])
        self.assertEqual(result["translations"]["c"], native["u2"])
        obj["segments"][0]["text"] = " é 🌧️\n"
        with self.assertRaisesRegex(ValueError, "exactly equal"):
            self.mapping(obj, native)

    def test_missing_duplicate_reordered_unknown_and_singleton_segments_rejected(self):
        rows = self.partition["segments"]
        for segments in (rows[:1], rows + [rows[0]], list(reversed(rows)), [rows[0], rows[0]],
                         rows + [{"unit_id": "u2", "source_id": "c", "text": "走吧。"}],
                         [dict(rows[0], unit_id="u2"), rows[1]],
                         [dict(rows[0], source_id="before"), rows[1]]):
            with self.subTest(segments=segments), self.assertRaisesRegex(ValueError, "coverage or order"):
                self.mapping({"segments": segments})

    def test_altered_omitted_reordered_and_whole_unit_repeated_text_rejected(self):
        for left, right in (("雨🌧️", "可能会下！"), ("雨🌧️", "可能会"),
                            ("可能会下。", "雨🌧️"), (self.native["u1"], self.native["u1"]),
                            ("雨🌧️", " ")):
            obj = deepcopy(self.partition)
            obj["segments"][0]["text"], obj["segments"][1]["text"] = left, right
            with self.subTest(left=left, right=right), self.assertRaises(ValueError):
                self.mapping(obj)
        for field in ("start", "end", "reference", "translation"):
            obj = deepcopy(self.partition)
            obj["segments"][0][field] = "not allowed"
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "fields"):
                self.mapping(obj)

    def test_all_singletons_mapping_has_no_completion_and_explicit_provenance(self):
        decisions = deepcopy(self.decisions)
        for row in decisions["boundaries"]:
            row["join"] = False
        plan = structured.parse_plan(self.encode(decisions), self.window)
        self.assertFalse(structured.mapping_required(self.window, plan))
        native = {"u1": "雨🌧️", "u2": "可能会下。", "u3": "走吧。"}
        result = structured.parse_mapping(None, self.window, plan, native)
        self.assertEqual(result["mapping_provenance"]["deterministic_singleton_unit_ids"], ["u1", "u2", "u3"])
        with self.assertRaises(ValueError):
            structured.mapping_prompt(self.window, plan, native)
        with self.assertRaises(ValueError):
            structured.mapping_grammar(self.window, plan)
        with self.assertRaises(ValueError):
            structured.parse_mapping('{"segments":[]}', self.window, plan, native)

    def test_grammars_use_adapter_json_rules_and_freeze_linear_identity_order(self):
        planner = structured.planning_grammar(self.window)
        mapper = structured.mapping_grammar(self.window, self.plan)
        for grammar in (planner, mapper):
            self.assertIn("root ::=", grammar)
            self.assertIn("| unresolved", grammar)
            self.assertIn('string ::= "\\\"" char+ "\\\""', grammar)
            self.assertIn(next(line for line in adapters.id_grammar(["a"]).splitlines() if line.startswith("char ::=")), grammar)
        rule = next(line for line in planner.splitlines() if line.startswith("planning ::="))
        self.assertLess(rule.index("boundary0"), rule.index("boundary1"))
        self.assertNotIn("boundary2", planner)
        self.assertEqual(sum(line.startswith("boundary") and "::=" in line for line in planner.splitlines()), 2)
        rule = next(line for line in mapper.splitlines() if line.startswith("mapping ::="))
        self.assertLess(rule.index("segment0"), rule.index("segment1"))
        self.assertNotIn("segment2", mapper)
        self.assertNotIn(structured._terminal_json("u2"), mapper)
        self.assertTrue(structured.planning_required(self.window))
        self.assertIn("ordered_boundaries", structured.planning_prompt(self.window))
        self.assertNotIn("走吧。", structured.mapping_prompt(self.window, self.plan, self.native))

    def test_visible_ids_with_quotes_unicode_and_backslashes_are_grammar_literals(self):
        sid = 'q"\\日'
        self.window["context"][0]["id"] = sid
        grammar = structured.planning_grammar(self.window)
        self.assertIn(json.dumps(json.dumps(sid, ensure_ascii=False), ensure_ascii=False), grammar)

    def test_unresolved_and_private_source_fields_cannot_become_fake_delivery(self):
        content = '{"unresolved":true,"reason":"无法可靠对应"}'
        with self.assertRaisesRegex(ValueError, "Boundary planner unresolved"):
            structured.parse_planning(content, self.window)
        with self.assertRaisesRegex(ValueError, "Substring mapper unresolved"):
            structured.parse_mapping(content, self.window, self.plan, self.native)
        with self.assertRaises(ValueError):
            structured.parse_mapping(None, self.window, self.plan, self.native)
        with self.assertRaises(ValueError):
            structured.parse_mapping('{"segments":[],"segments":[]}', self.window, self.plan, self.native)
        contaminated = dict(self.window, reference={"a": "forbidden"})
        with self.assertRaisesRegex(ValueError, "frozen model-input"):
            structured.planning_grammar(contaminated)
        for native in ({"u1": self.native["u1"]}, dict(self.native, extra="余分"), dict(self.native, u1=" ")):
            with self.subTest(native=native), self.assertRaises(ValueError):
                self.mapping(native=native)


if __name__ == "__main__":
    unittest.main()
