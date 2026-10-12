"""Offline synthetic checks for equal-work, missing-score and paired statistics."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from experiments.translation_eval.runner import dump, dump_jsonl, read_json
from experiments.translation_four_stats import (
    BOOTSTRAP_ITERATIONS, CONFIDENCE_LEVELS, SEED, build_statistics,
    clustered_intervals, main, quantile, report,
)


def error(severity: str = "major", reason: str = "语义改变。") -> dict:
    return {"ids": ["u1"], "type": "mistranslation", "severity": severity,
            "source_evidence": "source", "candidate_evidence": "candidate", "reason_zh": reason}


def fixture() -> tuple[list[dict], list[dict], dict]:
    # Work a has three windows, b only one: a pooled mean must differ from
    # the required equal-work mean. Movie m stays in its separate category.
    windows = [("a1", "a", "anime_series"), ("a2", "a", "anime_series"),
               ("a3", "a", "anime_series"), ("b1", "b", "anime_series"), ("m1", "m", "movie")]
    scores = {"A": [4, 4, 4, 0, 2], "B": [3, 3, None, 4, 3],
              "C": [4, 4, 4, 0, 2], "D": [0, 4, 4, 0, 2]}
    expected, final, sources = [], [], []
    for i, (wid, work, category) in enumerate(windows):
        sources.append({"id": wid, "work": work, "category": category,
                        "episode": "01" if work == "a" else None,
                        "position_stratum": 0 if i < 2 else 1,
                        "length_stratum": "short", "risk_tags": ["negation", "pronoun"] if i == 0 else []})
        for alias in scores:
            scope = {"window_id": wid, "candidate_alias": alias, "work": work,
                     "category": category, "scored_ids": ["u1"], "structural_status": "valid"}
            expected.append(scope)
            value = scores[alias][i]
            status = "review_failed" if value is None else "delivery_zero" if alias == "D" and i == 0 else "scored"
            final.append(dict(scope, semantic=value, naturalness=None if status != "scored" else 2,
                              status=status, errors=[], reviewed=False, initial_disagreement=False))
    return expected, final, {"windows": sources}


class FourStatisticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.expected, self.final, self.manifest = fixture()

    def build(self, **kwargs) -> dict:
        return build_statistics(self.expected, self.final, self.manifest, "A", bootstrap_iterations=300, **kwargs)

    def candidate(self, alias: str) -> dict:
        return self.build()["sets"]["expanded"]["quality"]["candidates"][alias]

    def test_equal_work_complete_denominator_bounds_and_delivery_zero(self) -> None:
        a = self.candidate("A")["categories"]["anime_series"]
        self.assertEqual(a["semantic_lower"], 2)  # pooled window mean would be 3
        self.assertEqual(a["semantic_upper"], 2)
        b = self.candidate("B")["categories"]["anime_series"]
        self.assertEqual(b["semantic_scored_windows"], 3)
        self.assertEqual(b["expected_windows"], 4)
        self.assertEqual(b["semantic_lower"], 3)
        self.assertAlmostEqual(b["semantic_upper"], 11 / 3)
        d = self.candidate("D")
        self.assertEqual(d["works"]["a"]["semantic_scored_windows"], 3)
        self.assertEqual(d["works"]["a"]["naturalness_scored_windows"], 2)
        self.assertEqual(d["status_counts"]["delivery_zero"], 1)

    def test_pairing_uses_ids_not_row_order_and_keeps_coverage(self) -> None:
        original = self.build()
        self.final.reverse()
        self.expected.reverse()
        self.manifest["windows"].reverse()
        self.assertEqual(self.build(), original)
        pair = original["sets"]["expanded"]["categories"]["anime_series"]["paired_vs_baseline"]["B"]
        self.assertEqual(pair["paired_windows"], 3)
        self.assertEqual(pair["paired_coverage"], .75)
        self.assertEqual((pair["win"], pair["tie"], pair["loss"]), (1, 0, 2))
        self.assertEqual(pair["semantic_difference"], 1.5)  # (-1 + 4) / 2, not 2/3
        self.assertEqual(pair["equal_work_rates"]["win"], .5)
        self.assertEqual(pair["complete_denominator_difference_bounds"]["lower"], 1)
        self.assertAlmostEqual(pair["complete_denominator_difference_bounds"]["upper"], 5 / 3)
        self.assertEqual(pair["leave_one_work_out"]["a"]["semantic_difference"], 4)
        self.assertEqual(pair["leave_one_work_out"]["b"]["semantic_difference"], -1)

    def test_missing_final_is_scheduling_unknown_never_delivery_zero(self) -> None:
        self.final = [row for row in self.final if not (row["candidate_alias"] == "B" and row["window_id"] == "b1")]
        data = self.build()["sets"]["expanded"]
        b = data["quality"]["candidates"]["B"]
        self.assertEqual(data["scheduled_missing_final_records"], 1)
        self.assertEqual(b["expected_windows"], 5)
        self.assertEqual(b["status_counts"]["not_run"], 1)
        self.assertNotIn("delivery_zero", b["status_counts"])
        pair = data["categories"]["anime_series"]["paired_vs_baseline"]["B"]
        self.assertEqual(pair["omitted_works"], ["b"])
        self.assertEqual(pair["paired_works"], 1)
        self.assertEqual(pair["semantic_difference"], -1)
        self.assertIsNone(pair["leave_one_work_out"]["a"]["semantic_difference"])

    def test_bootstrap_clusters_works_and_adjusted_intervals_are_nested(self) -> None:
        intervals = clustered_intervals([-1, 4], BOOTSTRAP_ITERATIONS, SEED)
        # Two equally weighted clusters can yield only -1, 1.5, or 4.
        for label in CONFIDENCE_LEVELS:
            self.assertEqual(intervals[label]["lower"], -1)
            self.assertEqual(intervals[label]["upper"], 4)
        self.assertEqual(intervals, clustered_intervals([-1, 4], BOOTSTRAP_ITERATIONS, SEED))
        many = clustered_intervals([0, 1, 2, 3, 4, 5, 6, 7], BOOTSTRAP_ITERATIONS, SEED)
        self.assertLessEqual(many["99.1667"]["lower"], many["98.33"]["lower"])
        self.assertLessEqual(many["98.33"]["lower"], many["95"]["lower"])
        self.assertGreaterEqual(many["99.1667"]["upper"], many["98.33"]["upper"])
        self.assertGreaterEqual(many["98.33"]["upper"], many["95"]["upper"])
        self.assertEqual(quantile([0, 10], .25), 2.5)

    def test_constant_paired_differences_ignore_unequal_window_counts(self) -> None:
        for row in self.final:
            if row["candidate_alias"] in {"A", "B"}:
                row["semantic"] = 2 if row["candidate_alias"] == "A" else 3
                row["status"] = "scored"
                row["naturalness"] = 2
        pair = self.build()["sets"]["expanded"]["categories"]["anime_series"]["paired_vs_baseline"]["B"]
        for interval in pair["intervals"].values():
            self.assertEqual((interval["lower"], interval["upper"]), (1, 1))

    def test_regression_and_new_windows_are_never_pooled(self) -> None:
        for row in self.manifest["windows"]:
            row["set"] = "regression" if row["id"] == "m1" else "expanded"
        summary = self.build()
        self.assertEqual(set(summary["sets"]), {"regression", "expanded"})
        self.assertEqual(summary["sets"]["regression"]["windows_per_candidate"], 1)
        self.assertNotIn("movie", summary["sets"]["expanded"]["categories"])
        self.assertNotIn("overall_quality", summary)

    def test_shared_series_is_explicit_and_preserves_equal_work_inside_groups(self) -> None:
        # Add a third work with B-A=0. The original equal-work effect is 1;
        # merging a,b gives (1.5 + 0)/2 = .75, regardless of their window counts.
        for alias in ("A", "B", "C", "D"):
            scope = dict(self.expected[0], candidate_alias=alias, window_id="c1", work="c")
            self.expected.append(scope)
            self.final.append(dict(scope, semantic=2, naturalness=2, status="scored", errors=[]))
        self.manifest["windows"].append({"id": "c1", "work": "c", "category": "anime_series"})
        pair = self.build(shared_series={"a": "franchise", "b": "franchise"})["sets"]["expanded"]["categories"]["anime_series"]["paired_vs_baseline"]["B"]
        sensitivity = pair["shared_series_sensitivity"]
        self.assertEqual(pair["semantic_difference"], 1)
        self.assertEqual(sensitivity["semantic_difference"], .75)
        self.assertEqual(sensitivity["group_members"]["series:franchise"], ["a", "b"])
        self.assertEqual(sensitivity["cluster_count"], 2)
        with self.assertRaisesRegex(ValueError, "unknown works"):
            self.build(shared_series={"imagined": "franchise"})

    def test_review_changes_allegations_and_common_final_error_coverage(self) -> None:
        first = []
        review = []
        for row in self.final:
            record = {name: row[name] for name in ("candidate_alias", "window_id", "semantic", "naturalness", "status", "errors")}
            first.append(deepcopy(record))
        # Duplicate prose explanations of exactly the same accepted claim count once.
        target = next(row for row in self.final if row["candidate_alias"] == "B" and row["window_id"] == "a1")
        target.update(semantic=4, errors=[error(), error(reason="相同根因。")], reviewed=True, initial_disagreement=True)
        primary = next(row for row in first if row["candidate_alias"] == "B" and row["window_id"] == "a1")
        primary["errors"] = [error("critical")]
        review.append({**primary, "semantic": 4, "errors": [error()]})
        data = self.build(primary=first, review=review)["sets"]["expanded"]
        variation = data["categories"]["anime_series"]["reviewer_variation"]["B"]
        self.assertEqual(variation["primary_final_score_changed_windows"], 1)
        self.assertEqual(variation["primary_review_disagreement_windows"], 1)
        self.assertEqual(variation["primary_alleged_errors"]["counts"]["critical"], 1)
        self.assertEqual(variation["final_accepted_errors"]["counts"]["critical"], 0)
        self.assertEqual(variation["final_accepted_errors"]["counts"]["major"], 1)
        self.assertEqual(variation["final_accepted_errors"]["unresolved_windows"], 1)
        common = data["four_candidate_common_coverage"]
        self.assertEqual(common["windows"], 4)
        self.assertNotIn("a3", common["window_ids"])
        self.assertEqual(common["errors"]["B"]["known_windows"], 4)

    def test_source_only_strata_have_unknown_buckets_and_overlapping_tags(self) -> None:
        strata = self.build()["sets"]["expanded"]["source_diagnostics"]
        self.assertEqual(strata["risk_tags"]["negation"]["windows_per_candidate"], 1)
        self.assertEqual(strata["risk_tags"]["pronoun"]["windows_per_candidate"], 1)
        self.assertEqual(strata["risk_tags"]["untagged"]["windows_per_candidate"], 4)
        self.assertEqual(strata["episode"]["a/01"]["windows_per_candidate"], 3)
        self.assertTrue(strata["position_stratum"]["0"]["diagnostic_only"])

    def test_expanded_manifest_aliases_source_length_and_unannotated_risks(self) -> None:
        source = self.manifest["windows"][0]
        source.pop("episode")
        source.pop("position_stratum")
        source.pop("length_stratum")
        source.pop("risk_tags")
        source.update(episode_id="s01e02", position_decile=3, source_length_chars=90)
        data = self.build()
        strata = data["sets"]["expanded"]["source_diagnostics"]
        self.assertEqual(strata["episode"]["a/s01e02"]["windows_per_candidate"], 1)
        self.assertEqual(strata["position_stratum"]["3"]["windows_per_candidate"], 1)
        self.assertEqual(strata["length_stratum"]["81-160"]["windows_per_candidate"], 1)
        self.assertEqual(strata["risk_tags"]["unknown"]["windows_per_candidate"], 1)
        self.assertEqual(data["source_diagnostic_config"]["length_bins"]["81-160"], [81, 160])
        source["diagnostic_tags"] = ["negation"]
        strata = self.build()["sets"]["expanded"]["source_diagnostics"]
        self.assertNotIn("unknown", strata["risk_tags"])
        self.assertEqual(strata["risk_tags"]["negation"]["windows_per_candidate"], 1)

    def test_rejects_duplicates_scope_mismatches_invalid_scores_and_unexpected_judges(self) -> None:
        bad = deepcopy(self.final)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_statistics(self.expected, bad + bad[:1], self.manifest, "A")
        bad[0]["scored_ids"] = ["different"]
        with self.assertRaisesRegex(ValueError, "scope mismatch"):
            build_statistics(self.expected, bad, self.manifest, "A")
        self.final[0]["semantic"] = 4.0
        with self.assertRaisesRegex(ValueError, "invalid final semantic"):
            self.build()
        self.final[0]["semantic"] = 4
        with self.assertRaisesRegex(ValueError, "unexpected candidate/window"):
            self.build(primary=[{"candidate_alias": "Z", "window_id": "a1"}])
        with self.assertRaisesRegex(ValueError, "positive"):
            build_statistics(self.expected, self.final, self.manifest, "A", bootstrap_iterations=0)

    def test_rejects_source_identity_changes_and_candidate_scope_changes(self) -> None:
        manifest = deepcopy(self.manifest)
        manifest["windows"][0]["work"] = "changed"
        with self.assertRaisesRegex(ValueError, "work mismatch"):
            build_statistics(self.expected, self.final, manifest, "A")
        manifest["windows"].pop()
        with self.assertRaisesRegex(ValueError, "scope mismatch"):
            build_statistics(self.expected, self.final, manifest, "A")
        self.expected.pop()
        self.final.pop()
        with self.assertRaisesRegex(ValueError, "candidate final scopes differ"):
            self.build()

    def test_all_missing_pair_has_no_fabricated_mean_or_interval(self) -> None:
        for row in self.final:
            if row["candidate_alias"] == "B":
                row.update(semantic=None, naturalness=None, status="judge_failed")
        data = self.build()["sets"]["expanded"]
        pair = data["categories"]["anime_series"]["paired_vs_baseline"]["B"]
        self.assertEqual(pair["paired_windows"], 0)
        self.assertIsNone(pair["semantic_difference"])
        self.assertIsNone(pair["intervals"]["95"]["lower"])
        self.assertEqual(data["quality"]["candidates"]["B"]["categories"]["anime_series"]["semantic_upper"], 4)

    def test_cli_preserves_input_hashes_and_produces_chinese_report(self) -> None:
        scratch = Path(__file__).resolve().parents[1] / ".local" / "translation-evaluation-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            root = Path(directory)
            dump_jsonl(root / "expected.jsonl", self.expected)
            dump_jsonl(root / "final.jsonl", self.final)
            dump(root / "sources.json", self.manifest)
            self.assertEqual(main(["--expected", str(root / "expected.jsonl"), "--final", str(root / "final.jsonl"),
                "--source-manifest", str(root / "sources.json"), "--baseline-alias", "A", "--output", str(root / "output")]), 0)
            summary = read_json(root / "output" / "summary.json")
            self.assertEqual(summary["bootstrap"]["iterations"], BOOTSTRAP_ITERATIONS)
            self.assertEqual(summary["bootstrap"]["seed"], SEED)
            self.assertEqual(len(summary["input_provenance"]["final"]["sha256"]), 64)
            text = (root / "output" / "report.md").read_text(encoding="utf-8")
            self.assertIn("语义缺分界", text)
            self.assertIn("98.33%", text)
            self.assertIn("99.1667%", text)
            self.assertIn("同模型", text)
            self.assertEqual(text, report(summary))


if __name__ == "__main__":
    unittest.main()
