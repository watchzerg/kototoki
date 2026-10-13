"""Offline exact term eligibility, complete dispositions and corruption checks."""

from copy import deepcopy
import json
import unittest

from experiments.translation_flow import v2_source_proposals as proposals


def scene():
    return {"id": "scene-a", "source_language": "ja", "target_language": "zh-Hans",
            "context": [{"id": "a1", "text": "隊長　隊長です。"},
                        {"id": "a2", "text": "もし雨なら中止です。"},
                        {"id": "a3", "text": "隊長を呼んでください。"},
                        {"id": "a4", "text": "センシが来ます。"}],
            "translate_ids": ["a1", "a2", "a3", "a4"]}


def proposal(source="隊長", translation="队长", uncertain=False):
    return {"source": source, "translation": translation, "uncertain": uncertain}


def content(rows):
    return json.dumps({"terms": rows}, ensure_ascii=False)


class SourceTermProposalTests(unittest.TestCase):
    def test_native_prompt_declares_suggestion_eligibility_and_separate_protocol(self):
        prompt = proposals.render_prompt(scene())
        self.assertTrue(prompt.startswith("<｜hy_begin▁of▁sentence｜>"))
        self.assertTrue(prompt.endswith("<｜hy_Assistant｜><think></think>"))
        self.assertIn("reasoning_effort:no_think", prompt)
        self.assertIn("程序生成证据ID", prompt)
        self.assertIn("uncertain", prompt)
        self.assertIn("至少两个不同源cue", prompt)
        with self.assertRaises(ValueError):
            proposals.render_prompt(dict(scene(), reference={"a1": "forbidden"}))

    def test_all_proposals_retained_with_exact_occurrences_and_distinct_cue_reasons(self):
        raw = content([proposal(), proposal("センシ", "先西"), proposal("不存在", "不存在")])
        parsed = proposals.parse_proposals(raw, scene())
        self.assertEqual(parsed["protocol"], "eligibility-filtered-proposals-v1")
        self.assertEqual(parsed["returned_count"], 3)
        self.assertEqual(parsed["accepted_count"], 1)
        self.assertEqual(parsed["declined_count"], 2)
        self.assertEqual(parsed["raw_response"], raw)
        self.assertEqual([row["disposition"] for row in parsed["proposals"]], ["accepted", "declined", "declined"])
        self.assertEqual([row["reason"] for row in parsed["proposals"]],
                         ["exact-repeat-in-distinct-cues", "single-cue-only", "source-not-present"])
        term = parsed["proposals"][0]
        self.assertEqual(term["distinct_source_cue_count"], 2)
        self.assertEqual(term["literal_occurrence_count"], 3)
        self.assertEqual(term["occurrences"], [{"id": "a1", "quote": "隊長", "start": 0, "end": 2},
                                               {"id": "a1", "quote": "隊長", "start": 3, "end": 5},
                                               {"id": "a3", "quote": "隊長", "start": 0, "end": 2}])
        self.assertEqual(parsed["records"][0]["evidence"], [{"id": "a1", "quote": "隊長"}, {"id": "a3", "quote": "隊長"}])
        self.assertFalse(parsed["semantic_quality_checked"])
        proposals.validate_result(parsed)

    def test_overlapping_literal_occurrences_do_not_count_as_multiple_cues(self):
        source = scene()
        source["context"][0]["text"] = "aaaa"
        parsed = proposals.parse_proposals(content([proposal("aa", "aa")]), source)
        self.assertEqual(parsed["proposals"][0]["literal_occurrence_count"], 3)
        self.assertEqual(parsed["proposals"][0]["distinct_source_cue_count"], 1)
        self.assertTrue(parsed["zero_eligible_glossary"])
        self.assertEqual(parsed["records"], [])

    def test_empty_and_entirely_ineligible_glossaries_are_complete_zero_effect_results(self):
        for rows in ([], [proposal("センシ", "先西"), proposal("不存在", "不存在")]):
            parsed = proposals.parse_proposals(content(rows), scene())
            self.assertTrue(parsed["complete"])
            self.assertTrue(parsed["zero_eligible_glossary"])
            self.assertEqual(parsed["accepted_count"], 0)
            projected = proposals.project_terms(parsed, scene())
            self.assertEqual(projected["injected_count"], 0)
            self.assertTrue(projected["zero_effective_injection"])
            self.assertEqual(projected["declined_proposal_count"], len(rows))

    def test_malformed_duplicate_and_contradictory_responses_fail_atomically(self):
        bad = [proposal(), proposal("センシ", "先西")]
        bad[1]["evidence"] = []
        for raw in (content(bad), content([proposal(), proposal(translation="指挥官")]),
                    content([proposal(), proposal()]), '{"terms":[],"terms":[]}',
                    content([dict(proposal(), uncertain="false")]),
                    content([dict(proposal(), translation="")]), content([dict(proposal(), source=1)]),
                    '{"terms":[],"reference":"forbidden"}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                proposals.parse_proposals(raw, scene())
        with self.assertRaises(ValueError):
            proposals.parse_proposals(content([proposal(), proposal("センシ", "先西")]), scene(), 1)
        for limit in (0, True, 1.5):
            with self.assertRaises(ValueError):
                proposals.parse_proposals(content([]), scene(), limit)

    def test_unicode_literals_are_never_normalized_or_replaced_by_short_aliases(self):
        source = scene()
        source["context"][0]["text"] = "🌧️e\u0301隊長"
        source["context"][2]["text"] = "🌧️e\u0301隊長"
        parsed = proposals.parse_proposals(content([proposal("🌧️e\u0301", "雨"), proposal("🌧️é", "雨"),
                                                   proposal("隊長の全名", "队长")]), source)
        self.assertEqual([row["distinct_source_cue_count"] for row in parsed["proposals"]], [2, 0, 0])
        self.assertEqual(parsed["proposals"][0]["occurrences"][0]["end"], 4)
        self.assertEqual(len(parsed["records"]), 1)

    def test_scoped_uncertain_suggestions_and_zero_batch_injections_are_explicit(self):
        parsed = proposals.parse_proposals(content([proposal(uncertain=True), proposal("センシ", "先西")]), scene())
        source = scene()
        first = {**source, "context": source["context"][:1], "translate_ids": ["a1"]}
        projected = proposals.project_terms(parsed, first)
        self.assertTrue(projected["terms"][0]["uncertain"])
        self.assertEqual(projected["terms"][0]["evidence_ids"], ["a1"])
        self.assertEqual(projected["terms"][0]["evidence"], [{"id": "a1", "quote": "隊長"}])
        self.assertEqual(projected["accepted_proposal_count"], 1)
        self.assertEqual(projected["declined_proposal_count"], 1)
        self.assertIn("shared preparation counted once", projected["cost_attribution"])
        second = {**source, "context": source["context"][1:2], "translate_ids": ["a2"]}
        empty = proposals.project_terms(parsed, second)
        self.assertTrue(empty["zero_effective_injection"])
        self.assertEqual(empty["accepted_proposal_count"], 1)
        for mutate in (lambda obj: obj["context"][0].update(text="改変された台詞"),
                       lambda obj: obj["context"][0].update(id="foreign-1")):
            bad = deepcopy(first)
            mutate(bad)
            with self.assertRaises(ValueError):
                proposals.project_terms(parsed, bad)

    def test_corrupted_source_raw_response_dispositions_and_derived_evidence_are_rejected(self):
        parsed = proposals.parse_proposals(content([proposal(), proposal("センシ", "先西")]), scene())
        mutations = (lambda obj: obj["source_context"][0].update(text="改変"),
                     lambda obj: obj.update(raw_response=content([proposal(translation="伪造")])),
                     lambda obj: obj["proposals"][1].update(disposition="accepted"),
                     lambda obj: obj["proposals"][0]["occurrences"][0].update(start=1),
                     lambda obj: obj["records"][0].update(translation="伪造"),
                     lambda obj: obj.update(scene_id="other-scene"),
                     lambda obj: obj.update(accepted_count=True),
                     lambda obj: obj.update(source_scene_sha256="0" * 64),
                     lambda obj: obj.update(response_sha256="0" * 64))
        for index, mutate in enumerate(mutations):
            corrupt = deepcopy(parsed)
            mutate(corrupt)
            with self.subTest(index=index), self.assertRaises(ValueError):
                proposals.validate_result(corrupt)

    def test_scoring_only_scene_or_reordered_source_context_cannot_expand_identity(self):
        partial = scene()
        partial["translate_ids"] = ["a1"]
        with self.assertRaises(ValueError):
            proposals.parse_proposals(content([proposal()]), partial)
        parsed = proposals.parse_proposals(content([proposal()]), scene())
        reordered = scene()
        reordered["context"].reverse()
        with self.assertRaisesRegex(ValueError, "source context order"):
            proposals.project_terms(parsed, reordered)
        noncontiguous = scene()
        noncontiguous["translate_ids"] = ["a1", "a3"]
        with self.assertRaisesRegex(ValueError, "contiguous ordered"):
            proposals.project_terms(parsed, noncontiguous)


if __name__ == "__main__":
    unittest.main()
