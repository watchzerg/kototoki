import math
import random
import tempfile
import unittest
from pathlib import Path

from kototoki_eval.alignment import align
from kototoki_eval.schema import from_segments, map_time, normalize
from kototoki_eval.scoring import evaluate, micro_summary, quantile
from kototoki_eval.__main__ import validate_output_path


def reference(spans, kind="srt_display"):
    return {"schema_version": 1, "reference_kind": kind, "spans": spans}


def span(text, start=0, end=1, id="r"):
    return {"id": id, "text": text, "start": start, "end": end}


def candidate(text, offset=0):
    return {"schema_version": 1, "text": text,
            "units": [{"char_start": i, "char_end": i + 1, "start": offset + i,
                       "end": offset + i + 1, "granularity": "character", "time_source": "native"}
                      for i in range(len(text))],
            "cues": [{"text": text, "start": offset, "end": offset + len(text)}]}


class EvaluatorTests(unittest.TestCase):
    def test_cue_split_merge_invariance(self):
        ref = reference([span("今日", 0, 2, "a"), span("元気", 2, 4, "b")])
        hyp = candidate("今日元気")
        merged = evaluate(ref, hyp)
        hyp["cues"] = [{"text": "今日", "start": 0, "end": 2}, {"text": "元気", "start": 2, "end": 4}]
        split = evaluate(ref, hyp)
        self.assertEqual(merged["text"], split["text"])
        self.assertEqual(merged["timing"], split["timing"])
        self.assertEqual(split["timing"]["measurable_count"], 2)

    def test_nfkc_punctuation_mapping(self):
        value = normalize(" ｶﾞ、Ａ\nか\u3099。")
        self.assertEqual(value.text, "ガAが")
        self.assertEqual(value.raw_spans, ((1, 3), (4, 5), (6, 8)))
        self.assertEqual(align("今日は元気", normalize("今日、は\n元気。").text).distance, 0)

    def test_missing_repeated_and_silence_denominator(self):
        ref = reference([span("abc", 0, 3)])
        deleted = evaluate(ref, candidate("bc"))
        repeated = evaluate(ref, candidate("abcabc"))
        silence = evaluate(reference([]), candidate("xy"))
        self.assertEqual(deleted["text"]["D"], 1)
        self.assertEqual(deleted["timing"]["denominator"], 1)
        self.assertEqual(deleted["timing"]["success"]["0.5"]["lower"], 0)
        self.assertEqual(repeated["text"]["I"], 3)
        self.assertIsNone(silence["text"]["CER"])
        self.assertEqual(micro_summary([deleted, silence])["CER"], 1)
        self.assertEqual(micro_summary([deleted, silence])["I"], 2)

    def test_one_second_offset(self):
        result = evaluate(reference([span("abc", 0, 3)]), candidate("abc", 1))
        self.assertEqual(result["text"]["CER"], 0)
        self.assertEqual(result["spans"][0]["start_error"], 1)
        self.assertEqual(result["timing"]["error"]["p95"], 1)
        self.assertEqual(result["timing"]["success"]["0.5"]["lower"], 0)
        self.assertEqual(result["timing"]["success"]["2.0"]["lower"], 1)

    def test_coarse_vs_whole_segment(self):
        hyp = from_segments([{"text": "abc", "start": 0, "end": 3}])
        full = evaluate(reference([span("abc", 0, 3)]), hyp)
        partial = evaluate(reference([span("a", 0, 1, "a"), span("bc", 1, 3, "b")]), hyp)
        self.assertEqual(full["timing"]["measurable_count"], 1)
        self.assertEqual(partial["timing"]["status_counts"], {"coarse_time": 2})
        self.assertTrue(math.isinf(partial["timing"]["joint_completeness_timing"]["p95"]))

    def test_text_only_invalid_failed_interpolated(self):
        ref = reference([span("a")])
        for key, value, status in [("start", None, "text_only"), ("end", 0, "invalid_time"),
                                   ("status", "failed", "alignment_failure"),
                                   ("time_source", "interpolated", "fallback_or_interpolated")]:
            hyp = candidate("a")
            hyp["units"][0][key] = value
            result = evaluate(ref, hyp)
            self.assertEqual(result["timing"]["status_counts"], {status: 1})
            self.assertEqual(result["timing"]["success"]["2.0"]["lower"], 0)

    def test_repeated_phrase_ambiguity_never_uses_time(self):
        ref = reference([span("abc", 0, 3)])
        hyp = candidate("abcabc")
        before = evaluate(ref, hyp)
        for unit in hyp["units"]:
            unit["start"] += 100
            unit["end"] += 100
        after = evaluate(ref, hyp)
        self.assertEqual(before["mapping"], after["mapping"])
        self.assertEqual(before["spans"][0]["status"], "matching_ambiguity")
        self.assertEqual(before["timing"]["success"]["0.5"],
                         {"success_count": 0, "unresolved_count": 1, "lower": 0.0, "upper": 1.0})

    def test_context_disambiguates_repeat(self):
        match = align("xabcYabcZ", "xabcYabcZ")
        self.assertFalse(match.ambiguous)

    def test_definitely_incomplete_ambiguity_is_not_optimistic_success(self):
        result = evaluate(reference([span("abba", 0, 4)]), candidate("aba"))
        self.assertEqual(result["spans"][0]["status"], "incomplete_content")
        self.assertFalse(result["spans"][0]["unresolved_may_be_complete"])
        self.assertEqual(result["timing"]["success"]["5.0"]["upper"], 0)
        middle = evaluate(reference([span("a", 0, 1, "a"), span("bb", 1, 3, "b"),
                                    span("a", 3, 4, "c")]), candidate("aba"))
        self.assertFalse(middle["spans"][1]["unresolved_may_be_complete"])

    def test_internal_ambiguity_invariant_complete_time_is_measurable(self):
        result = evaluate(reference([span("aba", 0, 4)]), candidate("abba"))
        row = result["spans"][0]
        self.assertEqual(result["text"]["I"], 1)
        self.assertAlmostEqual(result["text"]["CER"], 1 / 3)
        self.assertEqual(row["status"], "measurable")
        self.assertTrue(row["character_mapping_ambiguous"])
        self.assertTrue(row["timing_boundary_mapping_invariant"])
        self.assertEqual((row["predicted_start"], row["predicted_end"]), (0, 4))
        self.assertEqual(result["timing"]["success"]["0.5"]["lower"], 1)

    def test_invariant_time_requires_all_paths_valid_not_one(self):
        hyp = candidate("abba")
        hyp["units"][1]["status"] = "failed"
        result = evaluate(reference([span("aba", 0, 4)]), hyp)
        self.assertEqual(result["spans"][0]["status"], "matching_ambiguity")
        self.assertEqual(result["timing"]["success"]["0.5"]["lower"], 0)
        self.assertEqual(result["timing"]["success"]["0.5"]["upper"], 1)
        hyp = candidate("abba")
        hyp["units"][1].update(start=20, end=21)
        result = evaluate(reference([span("aba", 0, 4)]), hyp)
        self.assertEqual(result["spans"][0]["status"], "matching_ambiguity")
        self.assertEqual(result["timing"]["success"]["0.5"]["lower"], 0)

    def test_boundary_identity_ambiguity_never_promotes_equal_numeric_times(self):
        hyp = candidate("aa")
        for unit in hyp["units"]:
            unit.update(start=0, end=1)
        result = evaluate(reference([span("a")]), hyp)
        self.assertEqual(result["spans"][0]["status"], "matching_ambiguity")
        self.assertEqual(result["timing"]["success"]["0.5"]["lower"], 0)

    def test_cross_reference_normalization_cluster_rejected_not_dropped(self):
        ref = reference([span("か", 0, 1, "a"), span("\u3099", 1, 2, "b")])
        with self.assertRaisesRegex(ValueError, "crosses fixed reference span boundary"):
            evaluate(ref, candidate("が"))
        control = evaluate(reference([span("か\u3099")]), candidate("が"))
        self.assertEqual(control["text"]["CER"], 0)
        self.assertEqual(control["timing"]["denominator"], 1)
        self.assertEqual(control["timing"]["measurable_count"], 1)

    def test_ambiguity_impossible_timing_is_not_unresolved_success(self):
        ref = reference([span("a")])
        hyp = candidate("aa", 100)
        result = evaluate(ref, hyp)
        self.assertEqual(result["timing"]["success"]["5.0"]["upper"], 0)
        hyp["units"] = []
        result = evaluate(ref, hyp)
        self.assertEqual(result["timing"]["success"]["5.0"]["upper"], 0)

    def test_source_range_after_crop(self):
        hyp = candidate("a", 100)
        hyp.update(source_start_seconds=100, duration_seconds=1)
        ref = reference([span("a", 100, 101)])
        self.assertEqual(evaluate(ref, hyp)["spans"][0]["status"], "measurable")
        hyp["units"][0]["start"] = 99
        self.assertEqual(evaluate(ref, hyp)["spans"][0]["status"], "invalid_time")

    def test_ambiguous_failed_internal_units_not_in_upper_bound(self):
        hyp = candidate("abcdabcd")
        for index in (1, 2, 5, 6):
            hyp["units"][index]["status"] = "failed"
        result = evaluate(reference([span("abcd", 0, 4)]), hyp)
        self.assertEqual(result["timing"]["success"]["5.0"]["upper"], 0)

    def test_ambiguous_no_identity_or_internal_reverse_not_in_upper(self):
        result = evaluate(reference([span("a")]), candidate("bc"))
        self.assertEqual(result["timing"]["success"]["5.0"]["upper"], 0)
        hyp = candidate("abcdabcd")
        for index in (1, 5):
            hyp["units"][index].update(start=100, end=101)
        result = evaluate(reference([span("abcd", 0, 4)]), hyp)
        self.assertEqual(result["timing"]["success"]["5.0"]["upper"], 0)

    def test_partial_content_never_complete_success(self):
        result = evaluate(reference([span("abcd", 0, 4)]), candidate("acd"))
        self.assertEqual(result["spans"][0]["status"], "incomplete_content")
        self.assertTrue(result["spans"][0]["boundary_complete"])
        self.assertEqual(result["timing"]["success"]["5.0"]["upper"], 0)

    def test_uncertainty_strict_threshold(self):
        item = span("a")
        item["start_interval"] = [0, 0.6]
        item["end_interval"] = [0.4, 1]
        result = evaluate(reference([item], "human_acoustic"), candidate("a"))
        self.assertEqual(result["timing"]["success"]["0.5"]["unresolved_count"], 1)
        self.assertEqual(result["timing"]["success"]["2.0"]["success_count"], 1)
        result = evaluate(reference([span("a")]), candidate("a", 0.5))
        self.assertEqual(result["timing"]["success"]["0.5"]["success_count"], 0)

    def test_word_adapter_retains_unmapped_text(self):
        hyp = from_segments([{"text": "abcde", "start": 0, "end": 5,
                              "words": [{"word": "abc", "start": 0, "end": 3},
                                        {"word": "WRONG", "start": 3, "end": 5}]}])
        self.assertEqual(hyp["text"], "abcde")
        self.assertEqual(hyp["adapter_issues"], ["word_text_not_found"])
        self.assertTrue(evaluate(reference([span("abcde", 0, 5)]), hyp)["display"]["writer_text_preserved"])

    def test_crop_resampling_padding_vad_mapping(self):
        pieces = [{"processed_start_sample": 8000, "processed_end_sample": 24000,
                   "processed_rate": 16000, "source_start_sample": 480000, "source_rate": 48000},
                  {"processed_start_sample": 24000, "processed_end_sample": 40000,
                   "processed_rate": 16000, "source_start_sample": 960000, "source_rate": 48000}]
        self.assertEqual(map_time(0.5, pieces, boundary="start"), 10)
        self.assertEqual(map_time(1.5, pieces, boundary="end"), 11)
        self.assertEqual(map_time(1.5, pieces, boundary="start"), 20)
        self.assertAlmostEqual(map_time(2.12345, pieces, boundary="end"), 20.62345)
        with self.assertRaises(ValueError):
            map_time(0, pieces, boundary="start")

    def test_quantile_nearest_rank(self):
        self.assertEqual(quantile([1, 2, 3], .5), 2)
        self.assertEqual(quantile([1, 2, 3], .99), 3)

    def test_mapping_rejects_overlap_disorder_nonfinite(self):
        first = {"processed_start_sample": 0, "processed_end_sample": 16000,
                 "processed_rate": 16000, "source_start_sample": 0, "source_rate": 16000}
        overlap = {**first, "processed_start_sample": 8000, "processed_end_sample": 24000,
                   "source_start_sample": 1600000}
        for pieces in ([first, overlap], [overlap, first], [{**first, "source_rate": math.inf}],
                       [{**first, "processed_end_sample": 0}]):
            with self.assertRaises(ValueError):
                map_time(.75, pieces, boundary="start")

    def test_cli_output_protects_source_and_previous_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / ".local" / "new.json"
            self.assertEqual(validate_output_path(output, (), root), output.resolve())
            with self.assertRaises(ValueError):
                validate_output_path(root / "source.json", (), root)
            with self.assertRaises(ValueError):
                validate_output_path(output, (output,), root)
            output.parent.mkdir()
            output.write_text("old evidence", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                validate_output_path(output, (), root)

    def test_edit_counts_match_independent_full_matrix(self):
        rng = random.Random(12)
        for _ in range(100):
            a = "".join(rng.choices("abc", k=rng.randrange(12)))
            b = "".join(rng.choices("abc", k=rng.randrange(12)))
            row = list(range(len(b) + 1))
            for i, ac in enumerate(a, 1):
                new = [i]
                for j, bc in enumerate(b, 1):
                    new.append(min(row[j] + 1, new[-1] + 1, row[j - 1] + (ac != bc)))
                row = new
            result = align(a, b)
            self.assertEqual(result.distance, row[-1])
            self.assertEqual(result.substitutions + result.deletions + result.insertions, row[-1])

    def test_missing_all_span_denominator(self):
        result = evaluate(reference([span("abc", 0, 3)]), candidate(""))
        self.assertEqual(result["text"]["D"], 3)
        self.assertEqual(result["timing"]["status_counts"], {"missing_content": 1})

    def test_synthetic_digital_silence_truthful_kind_and_empty_only(self):
        ref = {"schema_version": 1, "reference_kind": "synthetic_digital_silence", "spans": [],
               "expected_spoken_characters": 0, "silence_kind": "digital_zero_no_room_noise",
               "provenance": "generated zero-valued PCM16 fixture", "duration_seconds": 10}
        result = evaluate(ref, candidate("abc"))
        self.assertEqual(result["reference_kind"], "synthetic_digital_silence")
        self.assertIsNone(result["text"]["CER"])
        self.assertEqual(result["text"]["I"], 3)
        self.assertEqual(result["text"]["silence_hallucination_characters"], 3)
        self.assertEqual(result["timing"]["denominator"], 0)
        self.assertIn("not room-noise robustness", result["limitations"][0])
        bad = {**ref, "spans": [span("a")]}
        with self.assertRaises(ValueError):
            evaluate(bad, candidate("a"))
        with self.assertRaises(ValueError):
            evaluate({**ref, "provenance": ""}, candidate(""))


if __name__ == "__main__":
    unittest.main()
