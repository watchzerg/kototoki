"""Synthetic source-only tests for the F5 mechanical delivery contract."""

import copy
import json
import unittest

from experiments.translation_demo import adapters
from . import v2_semantic as semantic


class SemanticProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.window = {"id": "synthetic", "source_language": "ja", "target_language": "zh-Hans",
                       "context": [{"id": "before", "text": "誰？"},
                                   {"id": "a", "text": "雨が"},
                                   {"id": "b", "text": "降るかも。"},
                                   {"id": "c", "text": "行こう。"},
                                   {"id": "after", "text": "はい。"}],
                       "translate_ids": ["a", "b", "c"]}
        self.plan = {"units": [{"id": "u1", "source_ids": ["a", "b"],
                                "evidence_ids": ["before", "a", "b"], "uncertain": True},
                               {"id": "u2", "source_ids": ["c"],
                                "evidence_ids": ["c"], "uncertain": False}]}
        self.native = {"u1": "雨🌧️可能会下。", "u2": "走吧。"}
        self.mapping = {"segments": [{"unit_id": "u1", "source_id": "a", "start": 0, "end": 3},
                                     {"unit_id": "u1", "source_id": "b", "start": 3, "end": 8},
                                     {"unit_id": "u2", "source_id": "c", "start": 0, "end": 3}]}

    def encode(self, obj: object) -> str:
        return json.dumps(obj, ensure_ascii=False)

    def parse_plan(self, plan: dict) -> dict:
        return semantic.parse_plan(self.encode(plan), self.window)

    def parse_mapping(self, mapping: dict) -> dict:
        return semantic.parse_mapping(self.encode(mapping), self.window, self.plan, self.native)

    def test_plan_keeps_source_evidence_and_uncertainty(self) -> None:
        self.assertEqual(self.parse_plan(self.plan), self.plan)
        self.window["translate_ids"] = ["c", "b", "a"]
        self.assertEqual(self.parse_plan(self.plan), self.plan)

    def test_source_only_prompt_boundary_and_native_wrapper(self) -> None:
        for prompt in (semantic.planning_prompt(self.window),
                       semantic.joint_prompt(self.window, self.plan),
                       semantic.mapping_prompt(self.window, self.plan, self.native)):
            self.assertTrue(prompt.startswith("<｜hy_begin▁of▁sentence｜>"))
            self.assertIn("reasoning_effort:no_think", prompt)
            self.assertIn("誰？", prompt)
        self.assertEqual(semantic.native_prompt(self.window, self.plan),
                         semantic.joint_prompt(self.window, self.plan))
        contaminated = dict(self.window, reference={"a": "private"})
        with self.assertRaisesRegex(ValueError, "frozen model-input"):
            semantic.planning_prompt(contaminated)

    def test_plan_rejects_missing_duplicate_reordered_or_unknown_sources(self) -> None:
        for sources in (["a"], ["a", "a"], ["b", "a"], ["a", "c"], ["a", "hidden"], ["before", "a"]):
            with self.subTest(sources=sources):
                plan = copy.deepcopy(self.plan)
                plan["units"][0]["source_ids"] = sources
                with self.assertRaises(ValueError):
                    self.parse_plan(plan)
        plan = {"units": list(reversed(self.plan["units"]))}
        with self.assertRaisesRegex(ValueError, "source order"):
            self.parse_plan(plan)

    def test_plan_cannot_merge_across_readonly_source(self) -> None:
        self.window["translate_ids"] = ["a", "c"]
        plan = {"units": [{"id": "u1", "source_ids": ["a", "c"], "evidence_ids": ["a"], "uncertain": True}]}
        with self.assertRaisesRegex(ValueError, "contiguous"):
            self.parse_plan(plan)

    def test_plan_rejects_invalid_evidence_uncertainty_and_fields(self) -> None:
        for field, value in (("evidence_ids", []), ("evidence_ids", ["hidden"]),
                             ("evidence_ids", ["a", "a"]), ("evidence_ids", "a"),
                             ("uncertain", "true"), ("uncertain", 1), ("id", "")):
            with self.subTest(field=field, value=value):
                plan = copy.deepcopy(self.plan)
                plan["units"][0][field] = value
                with self.assertRaises(ValueError):
                    self.parse_plan(plan)
        plan = copy.deepcopy(self.plan)
        plan["units"][1]["id"] = "u1"
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.parse_plan(plan)
        for obj in (dict(self.plan, reference="not allowed"),
                    {"units": [dict(self.plan["units"][0], translated_text="not allowed")]},
                    {"units": []}):
            with self.assertRaises(ValueError):
                self.parse_plan(obj)

    def test_joint_translation_uses_existing_strict_parser(self) -> None:
        self.assertEqual(adapters.translations(self.encode({"translations": self.native}), ["u1", "u2"]), self.native)
        for native in ({"u1": "雨。"}, dict(self.native, extra="余分"), dict(self.native, u1=" ")):
            with self.assertRaises(ValueError):
                semantic.mapping_prompt(self.window, self.plan, native)

    def test_two_unit_mapping_preserves_unicode_and_every_character(self) -> None:
        result = self.parse_mapping(self.mapping)
        self.assertEqual(result["translations"], {"a": "雨🌧️", "b": "可能会下。", "c": "走吧。"})
        self.assertEqual(result["source_span_to_target_span"], [
            {"unit_id": "u1", "source_ids": ["a"], "target_spans": [[0, 3]]},
            {"unit_id": "u1", "source_ids": ["b"], "target_spans": [[3, 8]]},
            {"unit_id": "u2", "source_ids": ["c"], "target_spans": [[0, 3]]}])
        for unit in self.plan["units"]:
            self.assertEqual("".join(result["translations"][sid] for sid in unit["source_ids"]),
                             self.native[unit["id"]])

    def test_mapping_rejects_gap_overlap_empty_out_of_range_and_boolean_offsets(self) -> None:
        for index, field, value in ((0, "start", 1), (1, "start", 4), (1, "start", 2),
                                    (1, "end", 7), (1, "end", 9), (0, "end", 0),
                                    (0, "start", False), (0, "end", 3.0), (0, "start", -1)):
            with self.subTest(index=index, field=field, value=value):
                mapping = copy.deepcopy(self.mapping)
                mapping["segments"][index][field] = value
                with self.assertRaises(ValueError):
                    self.parse_mapping(mapping)

    def test_mapping_rejects_missing_duplicate_reordered_and_cross_unit_cues(self) -> None:
        items = self.mapping["segments"]
        for segments in (items[:-1], items + [items[0]], list(reversed(items)),
                         [items[0], items[0], items[2]], [items[2], items[0], items[1]]):
            with self.subTest(segments=segments):
                with self.assertRaisesRegex(ValueError, "coverage or order"):
                    self.parse_mapping({"segments": segments})
        for field, value in (("unit_id", "u2"), ("source_id", "before"), ("unit_id", "hidden")):
            mapping = copy.deepcopy(self.mapping)
            mapping["segments"][0][field] = value
            with self.assertRaises(ValueError):
                self.parse_mapping(mapping)

    def test_mapping_rejects_text_edits_and_whole_unit_copy(self) -> None:
        for field in ("text", "reference", "translation"):
            mapping = copy.deepcopy(self.mapping)
            mapping["segments"][0][field] = "改写"
            with self.assertRaisesRegex(ValueError, "fields"):
                self.parse_mapping(mapping)
        mapping = copy.deepcopy(self.mapping)
        mapping["segments"][0]["end"] = 8
        mapping["segments"][1]["start"] = 0
        with self.assertRaises(ValueError):
            self.parse_mapping(mapping)
        with self.assertRaisesRegex(ValueError, "envelope"):
            self.parse_mapping(dict(self.mapping, text="改写"))

    def test_unresolved_never_produces_fake_translation(self) -> None:
        content = self.encode({"unresolved": True, "reason": "不能可靠拆分"})
        with self.assertRaisesRegex(ValueError, "Planner unresolved"):
            semantic.parse_plan(content, self.window)
        with self.assertRaisesRegex(ValueError, "Mapper unresolved"):
            semantic.parse_mapping(content, self.window, self.plan, self.native)
        for obj in ({"unresolved": False, "reason": "no"}, {"unresolved": True},
                    {"unresolved": True, "reason": " "},
                    {"unresolved": True, "reason": "no", "segments": []}):
            with self.assertRaises(ValueError):
                self.parse_mapping(obj)

    def test_duplicate_json_keys_rejected_in_all_stages(self) -> None:
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            semantic.parse_plan('{"units":[],"units":[]}', self.window)
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            semantic.parse_mapping('{"segments":[],"segments":[]}', self.window, self.plan, self.native)


if __name__ == "__main__":
    unittest.main()
