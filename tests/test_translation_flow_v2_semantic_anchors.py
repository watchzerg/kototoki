"""Synthetic exact-anchor partition tests; no inference or private subtitle data."""

from copy import deepcopy
import json
import unittest

from experiments.translation_flow import v2_semantic_anchors as anchors


class ExactAnchorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.window = {"id": "synthetic", "source_language": "ja", "target_language": "zh-Hans",
                       "context": [{"id": "before", "text": "誰？"}, {"id": "a", "text": "雨が"},
                                   {"id": "b", "text": "降るかも。"}, {"id": "c", "text": "行こう。"}],
                       "translate_ids": ["a", "b", "c"]}
        self.plan = {"units": [{"id": "u1", "source_ids": ["a", "b"],
                                "evidence_ids": ["a", "b"], "uncertain": True},
                               {"id": "u2", "source_ids": ["c"],
                                "evidence_ids": ["c"], "uncertain": False}]}
        self.native = {"u1": "雨🌧️可能会下。", "u2": "走吧。"}
        self.response = {"segments": [{"unit_id": "u1", "source_id": "a", "start_anchor": "雨🌧️"},
                                      {"unit_id": "u1", "source_id": "b", "start_anchor": "可能会下。"}]}

    def parse(self, obj=None, native=None):
        return anchors.parse_mapping(json.dumps(self.response if obj is None else obj, ensure_ascii=False),
                                     self.window, self.plan, self.native if native is None else native)

    def test_multicue_native_joint_text_preserved_with_unicode_offsets(self):
        result = self.parse()
        self.assertEqual(result["translations"], {"a": "雨🌧️", "b": "可能会下。", "c": "走吧。"})
        self.assertEqual(result["source_span_to_target_span"], [
            {"unit_id": "u1", "source_ids": ["a"], "target_spans": [[0, 3]]},
            {"unit_id": "u1", "source_ids": ["b"], "target_spans": [[3, 8]]},
            {"unit_id": "u2", "source_ids": ["c"], "target_spans": [[0, 3]]}])
        for unit in self.plan["units"]:
            self.assertEqual("".join(result["translations"][sid] for sid in unit["source_ids"]),
                             self.native[unit["id"]])
        proof = result["mapping_provenance"]
        self.assertEqual(proof["anchored_multi_cue_unit_ids"], ["u1"])
        self.assertEqual(proof["deterministic_singleton_unit_ids"], ["u2"])
        self.assertTrue(proof["model_mapping_required"])
        self.assertFalse(proof["semantic_correspondence_verified"])

    def test_all_singletons_bypass_generation_and_derive_unit_local_offsets(self):
        self.plan = {"units": [{"id": "u" + sid, "source_ids": [sid], "evidence_ids": [sid],
                                "uncertain": False} for sid in ("a", "b", "c")]}
        self.native = {"ua": "雨🌧️", "ub": "可能会下。", "uc": "走吧。"}
        self.assertFalse(anchors.mapping_required(self.window, self.plan))
        result = anchors.parse_mapping(None, self.window, self.plan, self.native)
        self.assertEqual(result["translations"], {"a": "雨🌧️", "b": "可能会下。", "c": "走吧。"})
        self.assertFalse(result["mapping_provenance"]["model_mapping_required"])
        self.assertEqual(result["mapping_provenance"]["resolved_anchors"], [])
        for row in result["source_span_to_target_span"]:
            self.assertEqual(row["target_spans"][0][0], 0)
        with self.assertRaisesRegex(ValueError, "skip model mapping"):
            anchors.mapping_prompt(self.window, self.plan, self.native)
        with self.assertRaisesRegex(ValueError, "no model mapping response"):
            anchors.parse_mapping('{"segments":[]}', self.window, self.plan, self.native)

    def test_prompt_only_requests_multicue_unit_mapping(self):
        self.assertTrue(anchors.mapping_required(self.window, self.plan))
        prompt = anchors.mapping_prompt(self.window, self.plan, self.native)
        self.assertIn("start_anchor", prompt)
        self.assertIn("reasoning_effort:no_think", prompt)
        self.assertIn("雨🌧️可能会下。", prompt)
        self.assertNotIn("走吧。", prompt)
        self.assertNotIn('"u2"', prompt)

    def test_rejects_ambiguous_overlapping_and_fuzzy_anchors(self):
        cases = [("是。是。", "是。"), ("aaaa", "aa"), ("雨可能会下。", "雨可能会下！"),
                 ("e\u0301可能会下。", "é"), (self.native["u1"], " ")]
        for text, anchor in cases:
            with self.subTest(text=text, anchor=anchor):
                response = deepcopy(self.response)
                response["segments"][0]["start_anchor"] = anchor
                with self.assertRaises(ValueError):
                    self.parse(response, {"u1": text, "u2": self.native["u2"]})

    def test_long_exact_anchors_disambiguate_repeated_short_text(self):
        native = {"u1": "是。是。继续。", "u2": "走吧。"}
        response = deepcopy(self.response)
        response["segments"][0]["start_anchor"] = "是。是。"
        response["segments"][1]["start_anchor"] = "是。继续。"
        result = self.parse(response, native)
        self.assertEqual(result["translations"]["a"], "是。")
        self.assertEqual(result["translations"]["b"], "是。继续。")

    def test_rejects_nonzero_first_boundary_reorder_or_whole_paragraph_copy(self):
        for first, second in (("可能", "雨🌧️"), ("可能", "会下"),
                              (self.native["u1"], self.native["u1"])):
            with self.subTest(first=first, second=second):
                response = deepcopy(self.response)
                response["segments"][0]["start_anchor"] = first
                response["segments"][1]["start_anchor"] = second
                with self.assertRaisesRegex(ValueError, "begin at zero|advance strictly"):
                    self.parse(response)

    def test_rejects_missing_duplicate_reordered_unknown_or_singleton_anchors(self):
        items = self.response["segments"]
        cases = [items[:-1], items + [items[0]], list(reversed(items)), [items[0], items[0]],
                 items + [{"unit_id": "u2", "source_id": "c", "start_anchor": "走吧。"}],
                 [dict(items[0], source_id="before"), items[1]],
                 [dict(items[0], unit_id="hidden"), items[1]]]
        for segments in cases:
            with self.subTest(segments=segments), self.assertRaisesRegex(ValueError, "coverage or order"):
                self.parse({"segments": segments})

    def test_preserves_all_whitespace_and_punctuation_without_trimming(self):
        native = {"u1": " 雨 🌧️ 可能会下。\n", "u2": " 走吧。\n"}
        response = deepcopy(self.response)
        response["segments"][0]["start_anchor"] = " 雨 🌧️ "
        response["segments"][1]["start_anchor"] = "可能会下。"
        result = self.parse(response, native)
        self.assertEqual(result["translations"]["a"], " 雨 🌧️ ")
        self.assertEqual(result["translations"]["b"], "可能会下。\n")
        self.assertEqual(result["translations"]["c"], " 走吧。\n")

    def test_existing_partition_validator_rejects_blank_cue_segment(self):
        native = {"u1": " X", "u2": "走吧。"}
        response = deepcopy(self.response)
        response["segments"][0]["start_anchor"] = " X"
        response["segments"][1]["start_anchor"] = "X"
        with self.assertRaisesRegex(ValueError, "blank cue"):
            self.parse(response, native)

    def test_mapping_missing_response_cannot_guess_a_multicue_boundary(self):
        with self.assertRaisesRegex(ValueError, "explicit exact-anchor"):
            anchors.parse_mapping(None, self.window, self.plan, self.native)

    def test_strict_envelope_fields_duplicate_json_and_unresolved(self):
        for content in ('{"segments":[],"segments":[]}',
                        '{"unresolved":true,"reason":"无法可靠对应"}',
                        '{"unresolved":false,"reason":"错误"}', '{"unresolved":true}',
                        '{"segments":[],"text":"新译文"}'):
            with self.subTest(content=content), self.assertRaises(ValueError):
                anchors.parse_mapping(content, self.window, self.plan, self.native)
        for field in ("start", "end", "text", "translation", "reference"):
            response = deepcopy(self.response)
            response["segments"][0][field] = "not allowed"
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "segment fields"):
                self.parse(response)

    def test_existing_source_and_native_identity_contracts_remain_required(self):
        contaminated = dict(self.window, reference={"a": "forbidden"})
        with self.assertRaisesRegex(ValueError, "frozen model-input"):
            anchors.mapping_required(contaminated, self.plan)
        malformed = deepcopy(self.plan)
        malformed["units"][0]["source_ids"] = ["b", "a"]
        with self.assertRaises(ValueError):
            anchors.mapping_required(self.window, malformed)
        for native in ({"u1": self.native["u1"]}, dict(self.native, extra="余分"), dict(self.native, u1=" ")):
            with self.subTest(native=native), self.assertRaises(ValueError):
                self.parse(native=native)


if __name__ == "__main__":
    unittest.main()
