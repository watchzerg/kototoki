"""Synthetic inference-time feature mechanics, never real translation quality."""

from copy import deepcopy
from types import MappingProxyType
import unittest

from experiments.translation_flow import v2_review_trigger_features as features


def source(texts, readonly=None):
    rows = [{"id": uid, "text": text} for uid, text in texts]
    return {"id": "synthetic-batch", "source_language": "ja", "target_language": "zh-Hans",
            "context": (readonly or []) + rows, "translate_ids": [uid for uid, _ in texts]}


def initial(values):
    return {"stage": "translation", "status": "accepted", "translations": values, "acceptance_sha256": "1" * 64}


class ReviewTriggerFeatureTests(unittest.TestCase):
    def extract(self, src, view=None):
        return features.extract_features(src, view, generation_seed=20261008)

    def test_faithful_condition_is_a_proxy_not_quality_error(self):
        result = self.extract(source([("a", "もし雨なら行かない。")]), initial({"a": "如果下雨就不去。"}))
        self.assertEqual(result["rules"], dict(zip(features.RULE_IDS, (True, False, True))))
        self.assertIsNone(result["quality_label"])

    def test_readonly_markers_do_not_trigger_target_rule(self):
        result = self.extract(source([("a", "出発。")], [{"id": "r", "text": "もし雨なら。"}]), initial({"a": "出发。"}))
        self.assertFalse(any(result["rules"].values()))

    def test_uncertainty_overlapping_markers_and_exact_offsets(self):
        result = self.extract(source([("a", "行かもしれない、ない。")]), initial({"a": "也许去，不去。"}))
        hits = result["source_literal_marker_hits"]
        self.assertEqual([h["start"] for h in hits if h["marker"] == "ない"], [5, 8])
        self.assertIn({"id": "a", "marker": "かもしれない", "start": 1, "end": 7}, hits)

    def test_legal_japanese_name_copy_can_trigger_without_error_claim(self):
        result = self.extract(source([("a", " アスナ ")]), initial({"a": "アスナ"}))
        self.assertEqual(result["source_copy_with_kana_ids"], ["a"])
        self.assertTrue(result["rules"][features.RULE_IDS[1]])
        self.assertIsNone(result["quality_label"])

    def test_exact_copy_requires_kana_and_retains_punctuation(self):
        han = self.extract(source([("a", "東京")]), initial({"a": "東京"}))
        punct = self.extract(source([("a", "はい。")]), initial({"a": "はい"}))
        self.assertEqual(han["source_copy_with_kana_ids"], [])
        self.assertEqual(punct["source_copy_with_kana_ids"], [])

    def test_adjacent_distinct_source_identical_output_proxy(self):
        result = self.extract(source([("a", "そうだ。"), ("b", "その通り。")]), initial({"a": "是的。", "b": " 是的。 "}))
        self.assertEqual(result["adjacent_duplicate_output_pairs"], [{"left_id": "a", "right_id": "b"}])
        self.assertIsNone(result["quality_label"])

    def test_faithful_source_repetition_and_whitespace_do_not_count_distinct(self):
        result = self.extract(source([("a", " そうだ。"), ("b", "そうだ。 ")]), initial({"a": "是的。", "b": "是的。"}))
        self.assertEqual(result["adjacent_duplicate_output_pairs"], [])

    def test_punctuation_not_normalized_and_nonadjacent_not_compared(self):
        src = source([("a", "一。"), ("b", "二。"), ("c", "三。")])
        result = self.extract(src, initial({"a": "好。", "b": "好！", "c": "好。"}))
        self.assertEqual(result["adjacent_duplicate_output_pairs"], [])

    def test_only_current_targets_never_readonly_output(self):
        src = source([("a", "一。")], [{"id": "r", "text": "二。"}])
        view = initial({"a": "好。", "r": "好。"})
        with self.assertRaises(ValueError):
            self.extract(src, view)

    def test_missing_and_failed_initial_preserve_unknown_with_source_observable(self):
        src = source([("a", "行かない。")])
        cases = [None] + [{"stage": "translation", "status": s, "translations": None, "acceptance_sha256": None}
                          for s in ("failed", "not_executed")]
        for view in cases:
            with self.subTest(view=view):
                result = self.extract(src, view)
                self.assertFalse(result["eligible"])
                self.assertTrue(result["source_literal_marker_presence"])
                self.assertEqual(result["decision_status"], "unknown")
                self.assertEqual(set(result["rules"].values()), {None})
                self.assertIsNone(result["adjacent_duplicate_output_pairs"])

    def test_reject_review_and_forbidden_additional_channels(self):
        src, view = source([("a", "出発。")]), initial({"a": "出发。"})
        for modified in ({**view, "stage": "source-review"}, {**view, "after": {}}, {**view, "judge_score": 2}):
            with self.subTest(modified=modified), self.assertRaises(ValueError):
                self.extract(src, modified)
        with self.assertRaises(ValueError):
            self.extract({**src, "reference": "never"}, view)

    def test_reject_incomplete_empty_and_malformed_accepted_initial(self):
        src = source([("a", "出発。"), ("b", "急げ。")])
        for values in ({"a": "出发。"}, {"a": "", "b": "快点。"}, {"a": None, "b": "快点。"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.extract(src, initial(values))
        with self.assertRaises(ValueError):
            self.extract(src, {**initial({"a": "出发。", "b": "快点。"}), "acceptance_sha256": None})

    def test_reject_wrong_source_order_duplicate_and_seed(self):
        src, view = source([("a", "一。"), ("b", "二。")]), initial({"a": "一。", "b": "二。"})
        for targets in (["b", "a"], ["a", "a"], ["missing"]):
            with self.subTest(targets=targets), self.assertRaises(ValueError):
                self.extract({**src, "translate_ids": targets}, view)
        for seed in (True, 1, "20261008"):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                features.extract_features(src, view, generation_seed=seed)

    def test_snapshot_determinism_input_immutability_and_no_text_export(self):
        src, view = source([("a", "行かない。")]), initial({"a": "不去。"})
        saved = deepcopy((src, view))
        first, second = self.extract(src, view), self.extract(src, view)
        self.assertEqual(first, second)
        self.assertEqual((src, view), saved)
        self.assertNotIn("translations", first)
        self.assertNotIn("context", first)
        features.validate_snapshot(first, src, view)

    def test_tamper_and_changed_inputs_rejected(self):
        src, view = source([("a", "出発。")]), initial({"a": "出发。"})
        result = self.extract(src, view)
        damaged = deepcopy(result)
        damaged["rules"][features.RULE_IDS[0]] = True
        with self.assertRaises(ValueError):
            features.validate_snapshot(damaged, src, view)
        with self.assertRaises(ValueError):
            features.validate_snapshot(result, src, initial({"a": "开始。"}))

    def test_all_three_seed_snapshot_bindings_and_fresh_contract(self):
        src, view = source([("a", "出発。")]), initial({"a": "出发。"})
        snapshots = [features.extract_features(src, view, generation_seed=s) for s in features.SEEDS]
        self.assertEqual(len({s["snapshot_sha256"] for s in snapshots}), 3)
        self.assertEqual(len({s["source_request_canonical_sha256"] for s in snapshots}), 1)
        changed = features.contract()
        changed["source_markers"].append("synthetic-only")
        self.assertEqual(features.contract()["source_markers"], list(features.MARKERS))

    def test_readonly_mapping_interface_has_same_canonical_binding(self):
        src, view = source([("a", "出発。")]), initial({"a": "出发。"})
        frozen_src = MappingProxyType({**src, "context": [MappingProxyType(c) for c in src["context"]]})
        frozen_view = MappingProxyType({**view, "translations": MappingProxyType(view["translations"])})
        self.assertEqual(self.extract(src, view), self.extract(frozen_src, frozen_view))


if __name__ == "__main__":
    unittest.main()
