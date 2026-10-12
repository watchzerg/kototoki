"""Offline arithmetic, pairing, hierarchy, isolation and timing checks."""

from copy import deepcopy
import unittest

from .v2_statistics import (
    SEEDS, build_statistics, student_t_critical, summarize_blind_calibration,
    summarize_paired_timing,
)


def fixture():
    windows = []
    for wid, work, scene, category, stratum in (
        ("a1", "a", "scene-a", "anime_series", "representative"),
        ("a2", "a", "scene-a", "anime_series", "representative"),
        ("a3", "a", "scene-b", "anime_series", "representative"),
        ("b1", "b", "scene-c", "anime_series", "representative"),
        ("r1", "a", "scene-risk", "anime_series", "risk"),
        ("m1", "m", "scene-movie", "animation_movie", "representative"),
    ):
        windows.append({"id": wid, "work_id": work, "category": category, "scene_id": scene,
                        "selection_type": stratum, "split": "screen-a", "scored_ids": ["u1", "u2"]})
    expected, final = [], []
    for source in windows:
        for alias in ("C0", "C1", "C2"):
            for seed in SEEDS:
                row = {"candidate_alias": alias, "window_id": source["id"], "seed": seed}
                expected.append(row)
                score = 2 if alias != "C1" else 3
                final.append(dict(row, semantic=score, naturalness=2, status="scored", errors=[]))
    return expected, final, {"windows": windows}


class StatisticsTests(unittest.TestCase):
    def setUp(self):
        self.expected, self.final, self.manifest = fixture()

    def build(self, **kwargs):
        return build_statistics(self.expected, self.final, self.manifest, "C0", bootstrap_iterations=200, **kwargs)

    def category(self, summary=None):
        return (summary or self.build())["splits"]["screen-a"]["strata"]["representative"]["categories"]["anime_series"]

    def pair(self, left="C0", right="C1", summary=None):
        return next(row for row in self.category(summary)["pairs"] if row["left_alias"] == left and row["right_alias"] == right)

    def test_unequal_windows_scenes_works_seeds_are_not_pooled(self):
        for row in self.final:
            if row["candidate_alias"] == "C0":
                row["semantic"] = {"a1": 4, "a2": 4, "a3": 0, "b1": 0, "r1": 4, "m1": 2}[row["window_id"]]
        candidate = self.category()["candidates"]["C0"]
        # Equal windows: work a=8/3, work b=0 -> category=4/3.
        self.assertAlmostEqual(candidate["semantic_lower"]["mean"], 4/3)
        self.assertEqual(candidate["expected_windows"], 4)
        self.assertEqual(candidate["expected_seed_records"], 12)
        self.assertAlmostEqual(candidate["semantic_lower"]["works"]["a"]["mean"], 8/3)
        self.assertEqual(candidate["semantic_lower"]["equal_scene_sensitivity_mean"], 1)

    def test_correlated_seeds_do_not_inflate_bootstrap_clusters(self):
        pair = self.pair()
        self.assertEqual(pair["complete_seed_pairs"], 12)
        self.assertEqual(pair["complete_paired_windows"], 4)
        self.assertEqual(pair["work_cluster_interval"]["cluster_count"], 2)
        self.assertEqual(pair["semantic_difference"], 1)
        self.assertEqual(pair["work_cluster_interval"]["lower"], 1)
        self.assertEqual(pair["work_cluster_interval"]["upper"], 1)
        for row in self.final:
            if row["candidate_alias"] == "C1":
                row["semantic"] = {SEEDS[0]: 4, SEEDS[1]: 2, SEEDS[2]: 3}[row["seed"]]
        pair = self.pair()
        self.assertEqual(pair["semantic_difference"], 1)
        self.assertEqual(pair["per_seed"][str(SEEDS[0])]["mean"], 2)
        self.assertEqual(pair["per_seed"][str(SEEDS[1])]["mean"], 0)

    def test_missing_final_null_bounds_and_delivery_zero(self):
        self.final = [row for row in self.final if not (row["candidate_alias"] == "C1" and row["window_id"] == "b1" and row["seed"] == SEEDS[0])]
        category = self.category()
        candidate = category["candidates"]["C1"]
        self.assertEqual(candidate["status_counts"]["not_run"], 1)
        self.assertEqual(candidate["semantic_scored_seed_records"], 11)
        self.assertEqual(candidate["semantic_lower"]["mean"], 2.5)
        self.assertAlmostEqual(candidate["semantic_upper"]["mean"], 19/6)
        pair = self.pair()
        self.assertEqual(pair["complete_paired_windows"], 3)
        self.assertEqual(pair["hierarchy"]["omitted_works"], ["b"])
        self.assertEqual(pair["missing_0_4_difference_bounds"]["lower"], .5)
        self.assertAlmostEqual(pair["missing_0_4_difference_bounds"]["upper"], 7/6)
        self.assertEqual(pair["interval_scope"], "complete_all_seeds_paired_window_subset_only")
        for row in self.final:
            if row["candidate_alias"] == "C1" and row["window_id"] == "a1":
                row.update(status="delivery_zero", semantic=0, naturalness=None)
        self.assertEqual(self.category()["candidates"]["C1"]["naturalness_scored_seed_records"], 8)

    def test_unresolved_semantic_cannot_use_provisional_score(self):
        row = self.final[0]
        row.update(status="unresolved", semantic=None, naturalness=None, provisional_primary={"semantic": 4})
        result = self.category()["candidates"]["C0"]
        self.assertEqual(result["windows"]["a1"]["semantic_scored_seeds"], 2)
        self.assertEqual(result["severe_errors"]["known_seed_records"], 11)
        row["semantic"] = 4
        with self.assertRaisesRegex(ValueError, "null final semantic"):
            self.build()

    def test_series_resampling_preserves_work_point_weight_and_pairing(self):
        # Works a,b share a series; c is its own cluster. Equal-work point=(2+2+0)/3.
        new = dict(self.manifest["windows"][0], id="c1", work_id="c", scene_id="scene-new")
        self.manifest["windows"].append(new)
        for alias in ("C0", "C1", "C2"):
            for seed in SEEDS:
                scope = {"candidate_alias": alias, "window_id": "c1", "seed": seed}
                self.expected.append(scope)
                self.final.append(dict(scope, status="scored", semantic=2, naturalness=2, errors=[]))
        for row in self.final:
            if row["candidate_alias"] == "C1" and row["window_id"] != "c1":
                row["semantic"] = 4
        summary = self.build(shared_series={"a": "same", "b": "same"}, family_size=6)
        pair = self.pair(summary=summary)
        self.assertAlmostEqual(pair["semantic_difference"], 4/3)
        self.assertEqual(pair["series_cluster_interval"]["members"]["series:same"], ["a", "b"])
        self.assertEqual(pair["series_cluster_interval"]["cluster_count"], 2)
        self.assertEqual(pair["work_cluster_interval"]["cluster_count"], 3)
        self.assertEqual(pair["leave_one_work_out"]["a"], 1)
        self.assertEqual(pair["leave_one_work_out"]["c"], 2)
        self.assertGreater(pair["simultaneous_interval"]["confidence"], .95)
        self.assertIsNotNone(self.pair("C1", "C2", summary))
        self.expected.reverse()
        self.final.reverse()
        self.manifest["windows"].reverse()
        self.assertEqual(self.build(shared_series={"a": "same", "b": "same"}, family_size=6), summary)

    def test_risk_categories_and_splits_remain_separate(self):
        summary = self.build()
        self.assertTrue(summary["splits"]["screen-a"]["strata"]["risk"]["diagnostic_only"])
        self.assertEqual(summary["splits"]["screen-a"]["strata"]["risk"]["categories"]["anime_series"]["candidates"]["C1"]["expected_windows"], 1)
        self.manifest["windows"][1]["split"] = "screen-b"
        self.assertNotIn("screening-combined", self.build()["splits"])
        combined = self.build(combine_screening=True)
        self.assertEqual(combined["splits"]["screening-combined"]["windows_per_candidate"], 6)
        self.manifest["windows"][1]["split"] = "confirmation"
        with self.assertRaisesRegex(ValueError, "scene leakage"):
            self.build()

    def test_episode_and_whole_visible_interval_leakage(self):
        left, right = self.manifest["windows"][0], self.manifest["windows"][2]
        left.update(episode_id="01")
        right.update(split="confirmation", episode_id="01")
        with self.assertRaisesRegex(ValueError, "episode leakage"):
            self.build()
        left.pop("episode_id")
        right.pop("episode_id")
        left.update(source_sha256="sha", visible_start_index=1, visible_end_index=160)
        right.update(source_sha256="sha", visible_start_index=150, visible_end_index=300)
        with self.assertRaisesRegex(ValueError, "interval leakage"):
            self.build()
        right["visible_start_index"] = 161
        self.build()
        left["source_event_keys"] = ["event"]
        right["source_event_keys"] = ["event"]
        with self.assertRaisesRegex(ValueError, "event leakage"):
            self.build()

    def test_root_dedup_keeps_distinct_evidence_and_reports_unknown(self):
        claim = {"ids": ["u1"], "type": "mistranslation", "severity": "major",
                 "source_evidence": "first fact", "candidate_evidence": "first change"}
        for row in self.final:
            if row["candidate_alias"] == "C1" and row["window_id"] == "a1":
                row["errors"] = [claim, dict(claim), dict(claim, source_evidence="second fact", candidate_evidence="second change")]
        result = self.category()["candidates"]["C1"]["severe_errors"]
        self.assertEqual(result["accepted_root_counts_union_across_seeds"]["major"], 2)
        for row in self.final:
            if row["candidate_alias"] == "C1" and row["window_id"] == "a1":
                row["errors"] = [dict(claim, root_id="root", ids=["u1"]), dict(claim, root_id="root", ids=["u2"], severity="critical")]
            if row["candidate_alias"] == "C1" and row["window_id"] == "b1":
                row.update(status="unresolved", semantic=None, naturalness=None, errors=[claim])
        result = self.category()["candidates"]["C1"]["severe_errors"]
        self.assertEqual(result["accepted_root_counts_union_across_seeds"]["critical"], 1)
        self.assertEqual(result["accepted_root_counts_union_across_seeds"]["major"], 0)
        bounds = result["serious_affected_rate_bounds"]
        self.assertAlmostEqual(bounds["lower"], 1/6)
        self.assertAlmostEqual(bounds["upper"], 2/3)

    def test_global_supported_roots_cross_windows_seeds_and_strata_are_work_qualified(self):
        claim = {"ids": ["u1"], "type": "mistranslation", "severity": "major", "root_id": "shared-1",
                 "source_evidence": "fact", "candidate_evidence": "change", "root_scope": "work",
                 "root_supported": True, "root_registry_sha256": "a" * 64}
        for row in self.final:
            if row["candidate_alias"] == "C1" and row["window_id"] in {"a1", "a2", "r1", "b1"}:
                row["errors"] = [dict(claim, severity="critical" if row["window_id"] == "a2" else "major")]
        summary = self.build()
        global_roots = summary["splits"]["screen-a"]["global_error_root_union"]["C1"]
        # a1/a2/r1 share a curated root; the same root label in work b is separate.
        self.assertEqual(global_roots["counts"], {"minor": 0, "major": 1, "critical": 1})
        self.assertEqual(global_roots["supported_shared_root_count"], 2)
        self.assertFalse(global_roots["candidate_specific_new_root_gate_assessed"])
        # Existing per-window root diagnostics are preserved.
        severe = self.category(summary)["candidates"]["C1"]["severe_errors"]
        self.assertEqual(severe["accepted_root_counts_union_across_seeds"], {"minor": 0, "major": 2, "critical": 1})
        for row in self.final:
            for error in row["errors"]:
                error.pop("root_registry_sha256")
        roots = self.build()["splits"]["screen-a"]["global_error_root_union"]["C1"]
        self.assertEqual(roots["counts"], {"minor": 0, "major": 3, "critical": 1})
        self.assertEqual(roots["unresolved_window_local_root_count"], 4)

    def test_global_exact_evidence_requires_work_and_source_identity(self):
        claim = {"ids": ["u1"], "type": "mistranslation", "severity": "major",
                 "source_evidence": "fact", "candidate_evidence": "change"}
        for source in self.manifest["windows"]:
            if source["id"] in {"a1", "a2", "b1"}:
                source["source_sha256"] = "b" * 64
        for row in self.final:
            if row["candidate_alias"] == "C1" and row["window_id"] in {"a1", "a2", "b1"}:
                row["errors"] = [dict(claim)]
        roots = self.build()["splits"]["screen-a"]["global_error_root_union"]["C1"]
        self.assertEqual(roots["counts"]["major"], 2)
        self.assertEqual(roots["exact_evidence_claim_count"], 2)
        self.manifest["windows"][1].pop("source_sha256")
        roots = self.build()["splits"]["screen-a"]["global_error_root_union"]["C1"]
        self.assertEqual(roots["counts"]["major"], 3)

    def test_blind_calibration_measures_resolution_without_thresholds(self):
        first = [row for row in self.final if row["candidate_alias"] == "C0"]
        repeat = deepcopy(first)
        repeat[0]["semantic"] = 1
        report = summarize_blind_calibration(first, repeat, self.manifest)
        self.assertFalse(report["thresholds_selected"])
        self.assertEqual(report["expected_windows"], 6)
        self.assertEqual(report["semantic_comparable_pairs"], 18)
        self.assertEqual(report["semantic_exact_agreement_pairs"], 17)
        repeat[0]["semantic"] = None
        report = summarize_blind_calibration(first, repeat, self.manifest)
        self.assertEqual(report["semantic_missing_pairs"], 1)
        with self.assertRaisesRegex(ValueError, "identical"):
            summarize_blind_calibration(first, repeat[1:], self.manifest)

    def test_calibration_separates_ceiling_presence_flips_evidence_and_strata(self):
        first = deepcopy([row for row in self.final if row["candidate_alias"] == "C0"])
        repeat = deepcopy(first)
        major = {"ids": ["u1"], "severity": "major", "type": "mistranslation",
                 "source_evidence": "fact one", "candidate_evidence": "change one"}
        for row in first:
            if row["window_id"] in {"a1", "a2"}:
                row["errors"] = [major]
        for row in repeat:
            if row["window_id"] == "a1":
                row.update(semantic=1, naturalness=1,
                           errors=[dict(major, source_evidence="fact two", candidate_evidence="change two")])
            if row["window_id"] == "b1":
                row["errors"] = [dict(major, severity="critical")]
        summary = summarize_blind_calibration(first, repeat, self.manifest)
        anime = summary["strata"]["representative"]["categories"]["anime_series"]
        self.assertFalse(summary["pooled_score_mean_reported"])
        self.assertAlmostEqual(anime["scores"]["semantic"]["mean_absolute_difference"]["mean"], 1/6)
        self.assertAlmostEqual(anime["scores"]["semantic"]["exact_score_flip_rate"]["mean"], 1/6)
        self.assertEqual(anime["naturalness_ceiling"]["first"]["naturalness_2_frequency"]["mean"], 1)
        self.assertAlmostEqual(anime["naturalness_ceiling"]["repeat"]["naturalness_2_frequency"]["mean"], 5/6)
        presence = anime["severe_affected_window_presence"]
        self.assertEqual(presence["major_or_critical"]["no_to_yes_rate"]["mean"], .5)
        self.assertAlmostEqual(presence["major_or_critical"]["yes_to_no_rate"]["mean"], 1/6)
        self.assertEqual(presence["critical"]["no_to_yes_rate"]["mean"], .5)
        self.assertEqual(presence["major"]["no_to_yes_rate"]["mean"], 0)
        # a1 evidence changes without presence change; a2 and b1 also change claims.
        self.assertEqual(anime["severe_evidence_claim_disagreement"]["changed_pairs"], 9)
        self.assertEqual(summary["strata"]["risk"]["categories"]["anime_series"]["expected_windows"], 1)
        self.assertEqual(summary["strata"]["representative"]["categories"]["movie"]["expected_windows"], 1)
        repeat_row = next(row for row in repeat if row["window_id"] == "b1")
        repeat_row.update(semantic=None, naturalness=None, status="judge_failed", errors=[])
        summary = summarize_blind_calibration(first, repeat, self.manifest)
        anime = summary["strata"]["representative"]["categories"]["anime_series"]
        self.assertEqual(anime["severe_affected_window_presence"]["critical"]["unknown_pairs"], 1)
        self.assertEqual(anime["severe_affected_window_presence"]["critical"]["comparable_pairs"], 11)
        self.assertEqual(anime["scores"]["naturalness"]["missing_pairs"], 1)

    def test_scope_duplicate_and_seed_checks(self):
        self.final.append(dict(self.final[0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.build()
        self.final.pop()
        self.expected.pop()
        with self.assertRaisesRegex(ValueError, "scope mismatch"):
            self.build()

    def test_baseline_pairs_have_one_direction_regardless_of_alias_sort_order(self):
        summary = build_statistics(self.expected, self.final, self.manifest, "C2", bootstrap_iterations=30)
        pairs = self.category(summary)["pairs"]
        self.assertEqual(len(pairs), 3)
        self.assertEqual({(row["left_alias"], row["right_alias"]) for row in pairs},
                         {("C2", "C0"), ("C2", "C1"), ("C0", "C1")})

    def test_source_builder_series_cluster_and_distinct_movie_id_title(self):
        # Exact source metadata names; no subtitle text or reference assets.
        titles = {
            "M01": "Sword Art Online The Movie Progressive - Aria of a Starless Night (2021)",
            "M02": "Sword Art Online the Movie Progressive - Scherzo of Deep Night (2022)",
            "M03": "Synthetic unrelated movie",
        }
        sources, expected, final = [], [], []
        for work_id, title in titles.items():
            sources.append({"id": work_id + "-window", "work_id": work_id, "work": title,
                "category": "animation_movie", "episode_id": work_id, "scene_id": work_id + "-scene",
                "split": "screen-a", "selection_type": "representative",
                "series_cluster": "SAO" if work_id in {"M01", "M02"} else work_id})
            for alias in ("C0", "C1"):
                for seed in SEEDS:
                    scope = {"candidate_alias": alias, "window_id": work_id + "-window", "seed": seed,
                             "work_id": work_id, "work": title, "category": "animation_movie"}
                    expected.append(scope)
                    score = 3 if alias == "C1" and work_id in {"M01", "M02"} else 1
                    final.append(dict(scope, semantic=score, naturalness=2, status="scored", errors=[]))
        summary = build_statistics(expected, final, sources, "C0", bootstrap_iterations=100)
        pair = summary["splits"]["screen-a"]["strata"]["representative"]["categories"]["movie"]["pairs"][0]
        self.assertAlmostEqual(pair["semantic_difference"], 4/3)
        self.assertEqual(pair["series_cluster_interval"]["cluster_count"], 2)
        self.assertEqual(pair["series_cluster_interval"]["members"]["series:SAO"], [titles["M01"], titles["M02"]])
        self.assertEqual(pair["work_cluster_interval"]["cluster_count"], 3)
        self.assertEqual(summary["estimand_scope"], "frozen_window_frame_and_allocation_only")
        self.assertFalse(summary["population_sampling_weights_applied"])
        sources[0]["series_id"] = "SAO"
        build_statistics(expected, final, sources, "C0", bootstrap_iterations=20)
        sources[0]["series_id"] = "different"
        with self.assertRaisesRegex(ValueError, "contradictory"):
            build_statistics(expected, final, sources, "C0", bootstrap_iterations=20)
        sources[0].pop("series_id")
        final[0]["work_id"] = "M99"
        with self.assertRaisesRegex(ValueError, "work_id mismatch"):
            build_statistics(expected, final, sources, "C0", bootstrap_iterations=20)


def timing_pairs(phase="exploratory", savings=(1, 2, 3, 4)):
    return [{"pair_id": f"{phase}-{index}", "phase": phase, "order": "AB" if index % 2 == 0 else "BA",
             "baseline_seconds": 10, "candidate_seconds": 10 - value} for index, value in enumerate(savings)]


class TimingTests(unittest.TestCase):
    def test_stdlib_t_quantiles_match_known_values(self):
        self.assertAlmostEqual(student_t_critical(.95, 1), 12.706204736, places=7)
        self.assertAlmostEqual(student_t_critical(.95, 10), 2.228138852, places=7)

    def test_precision_only_plans_independent_fixed_repetitions(self):
        result = summarize_paired_timing(timing_pairs(), target_half_width_seconds=.5)
        self.assertEqual(result["exploratory"]["mean_savings_seconds"], 2.5)
        self.assertTrue(result["exploratory"]["order_balanced"])
        planned = result["suggested_fixed_repetitions_from_exploratory_variance"]
        self.assertGreater(planned, 4)
        independent = timing_pairs("confirmation", (2,) * planned)
        result = summarize_paired_timing(timing_pairs() + independent, planned_confirmation_repetitions=planned)
        self.assertTrue(result["confirmation_complete"])
        self.assertEqual(result["exploratory"]["pair_count"], 4)
        self.assertEqual(result["confirmation"]["mean_savings_seconds"], 2)
        self.assertEqual(result["confirmation"]["half_width_seconds"], 0)

    def test_fixed_plan_reuse_and_measurement_constraints(self):
        with self.assertRaisesRegex(ValueError, "pre-frozen"):
            summarize_paired_timing(timing_pairs("confirmation"))
        with self.assertRaisesRegex(ValueError, "exceeds"):
            summarize_paired_timing(timing_pairs("confirmation"), planned_confirmation_repetitions=2)
        result = summarize_paired_timing(timing_pairs("confirmation"), planned_confirmation_repetitions=6)
        self.assertFalse(result["confirmation_complete"])
        pairs = timing_pairs()
        copied = dict(pairs[0], phase="confirmation")
        with self.assertRaisesRegex(ValueError, "unique across"):
            summarize_paired_timing(pairs + [copied])
        pairs[0]["reused"] = True
        with self.assertRaisesRegex(ValueError, "reused artifacts"):
            summarize_paired_timing(pairs)
        pairs[0].pop("reused")
        pairs[0]["candidate_seconds"] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite"):
            summarize_paired_timing(pairs)

    def test_failures_stay_visible_and_do_not_fake_speed_advantage(self):
        pairs = timing_pairs("confirmation")
        pairs[0].update(candidate_completed=False, candidate_seconds=.01)
        result = summarize_paired_timing(pairs, planned_confirmation_repetitions=4)
        self.assertEqual(result["confirmation"]["failed_pair_count"], 1)
        self.assertEqual(result["confirmation"]["completed_pair_count"], 3)
        self.assertEqual(result["confirmation"]["mean_savings_seconds"], 3)
        self.assertTrue(result["confirmation_schedule_complete"])
        self.assertFalse(result["confirmation_complete"])
        pairs[0].update(candidate_seconds=None)
        summarize_paired_timing(pairs, planned_confirmation_repetitions=4)
        pairs[0].update(baseline_cache_initial_state="empty", candidate_cache_initial_state="warm")
        with self.assertRaisesRegex(ValueError, "cache_initial_state mismatch"):
            summarize_paired_timing(pairs, planned_confirmation_repetitions=4)


if __name__ == "__main__":
    unittest.main()
