"""Synthetic exact-output/judge-noise diagnostics; no real subtitle content."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from experiments.translation_eval.runner import dump_jsonl, read_json
from experiments.translation_identical_output_diagnostics import analyze_identical_outputs, main, report


def finding(severity: str, uid: str = "u1") -> dict:
    return {"ids": [uid], "type": "mistranslation", "severity": severity,
            "source_evidence": "PRIVATE_SOURCE_MARKER", "candidate_evidence": "PRIVATE_OUTPUT_MARKER",
            "reason_zh": "合成错误描述。"}


def fixtures() -> tuple[list[dict], dict[str, list[dict]], list[dict], list[dict]]:
    expected, primary, final = [], [], []
    results = {alias: [] for alias in "ABCD"}
    for window in ("same", "two-groups", "different"):
        maps = {
            "same": ["PRIVATE_OUTPUT_MARKER"] * 4,
            "two-groups": ["first", "first", "second", "second"],
            "different": ["a", "b", "c", "d"],
        }[window]
        for i, alias in enumerate("ABCD"):
            scope = {"candidate_alias": alias, "window_id": window, "work": "synthetic-work",
                     "category": "anime_series", "scored_ids": ["u1", "u2"], "structural_status": "valid"}
            expected.append(scope)
            results[alias].append({"id": window, "translations": {"u1": maps[i], "u2": "tail"}})
            primary.append({"candidate_alias": alias, "window_id": window, "semantic": 4,
                            "naturalness": 2, "status": "scored", "errors": []})
            final.append({**scope, "semantic": 4, "naturalness": 2, "status": "scored",
                          "errors": [], "reviewed": False})
    return expected, results, primary, final


class IdenticalOutputDiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.expected, self.results, self.primary, self.final = fixtures()

    def analyze(self, *, review: list[dict] | None = None) -> dict:
        return analyze_identical_outputs(self.expected, self.results, primary=self.primary, review=review,
                                         final=self.final, set_name="expanded")

    def scope(self, **kwargs) -> dict:
        return self.analyze(**kwargs)["sets"]["expanded"]

    def test_groups_windows_and_pairs_have_distinct_full_denominators(self) -> None:
        scope = self.scope()
        self.assertEqual(scope["expected_windows"], 3)
        self.assertEqual(scope["expected_candidate_windows"], 12)
        self.assertEqual(scope["expected_window_pairs"], 18)
        self.assertEqual(scope["identical_output_windows"], 2)
        self.assertEqual(scope["identical_output_groups"], 3)
        self.assertEqual(scope["identical_output_pairs"], 8)
        self.assertEqual(scope["identical_participant_candidate_windows"], 8)
        self.assertEqual(scope["observed_unequal_pairs"], 10)
        self.assertEqual(scope["identity_known_pairs"], 18)
        self.assertEqual(scope["identity_unknown_pairs"], 0)
        self.assertEqual(scope["stage_comparisons"]["primary"]["signed_difference_distribution"], {"0": 8})
        self.assertEqual(scope["within_alias_primary_review"]["expected_pairs"], 8)

    def test_map_key_order_ignored_but_text_ids_and_unicode_are_exact(self) -> None:
        for alias, rows in self.results.items():
            rows[0]["translations"] = {"u1": "é", "u2": "same"}
            if alias == "B":
                rows[0]["translations"] = {"u2": "same", "u1": "é"}
            elif alias == "C":
                rows[0]["translations"]["u1"] = "é "
            elif alias == "D":
                rows[0]["translations"]["u1"] = "e\u0301"
        groups = [group for group in self.scope()["groups"] if group["window_id"] == "same"]
        self.assertEqual([group["aliases"] for group in groups], [["A", "B"]])
        self.results["B"][0]["translations"] = {"u1": "same", "u2": "é"}
        self.assertFalse(any(group["window_id"] == "same" for group in self.scope()["groups"]))

    def test_primary_final_and_review_differences_are_separate(self) -> None:
        scores = {"A": 4, "B": 3, "C": 2, "D": None}
        for record in self.primary:
            if record["window_id"] == "same":
                record["semantic"] = scores[record["candidate_alias"]]
        for record in self.final:
            if record["window_id"] == "same":
                record["semantic"] = 4
        scope = self.scope()
        first = scope["stage_comparisons"]["primary"]
        self.assertEqual(first["known_semantic_pairs"], 5)  # 3 on same, 2 on two-groups
        self.assertEqual(first["missing_semantic_pairs"], 3)
        self.assertEqual(first["missing_score_sides"], 3)
        self.assertEqual(first["missing_record_sides"], 0)
        unique = first["identical_participant_candidate_windows"]
        self.assertEqual(unique["expected_windows"], 8)
        self.assertEqual(unique["semantic_null_records"], 1)
        self.assertEqual(unique["semantic_scored_windows"], 7)
        self.assertEqual(first["full_expected_candidate_windows"]["expected_windows"], 12)
        self.assertEqual(first["signed_difference_distribution"], {"-2": 1, "-1": 2, "0": 2})
        self.assertEqual(first["mean_absolute_difference"], .8)
        self.assertEqual(scope["stage_comparisons"]["final"]["nonzero_difference_pairs"], 0)
        self.assertEqual(scope["stage_comparisons"]["review"]["known_semantic_pairs"], 0)
        self.assertEqual(scope["stage_comparisons"]["review"]["missing_record_sides"], 16)

    def test_missing_results_make_identity_unknown_not_equal_or_unequal(self) -> None:
        self.results["D"] = self.results["D"][1:]
        scope = self.scope()
        self.assertEqual(scope["expected_window_pairs"], 18)
        self.assertEqual(scope["identity_known_pairs"], 15)
        self.assertEqual(scope["identity_unknown_pairs"], 3)
        self.assertEqual(scope["identical_output_pairs"], 5)
        self.assertEqual(scope["candidate_output_coverage"]["D"]["expected_windows"], 3)
        self.assertEqual(scope["candidate_output_coverage"]["D"]["excluded_windows"], {"missing_result": 1})

    def test_unusable_and_program_delivery_zeros_do_not_fake_judge_agreement(self) -> None:
        for row in self.expected:
            if row["window_id"] == "same" and row["candidate_alias"] == "D":
                row["structural_status"] = "delivery_zero"
        self.results["C"][0]["translations"] = {"u1": " ", "u2": ""}
        scope = self.scope()
        same = [group for group in scope["groups"] if group["window_id"] == "same"]
        self.assertEqual(same[0]["aliases"], ["A", "B"])
        self.assertEqual(scope["candidate_output_coverage"]["D"]["excluded_windows"], {"delivery_zero": 1})
        self.assertEqual(scope["candidate_output_coverage"]["C"]["excluded_windows"], {"wholly_absent_or_unreadable_map": 1})

    def test_partial_maps_are_exact_including_missing_ids(self) -> None:
        for alias in "AB":
            self.results[alias][0]["translations"] = {"u1": "same fragment"}
        for alias in "CD":
            self.results[alias][0]["translations"] = {"u2": "same fragment"}
        groups = [group for group in self.scope()["groups"] if group["window_id"] == "same"]
        self.assertEqual([group["aliases"] for group in groups], [["A", "B"], ["C", "D"]])

    def test_severe_classification_and_claim_scope_disagreement(self) -> None:
        for record in self.primary:
            if record["window_id"] == "same":
                record["errors"] = {"A": [finding("major", "u1")], "B": [finding("major", "u2")],
                                    "C": [finding("critical")], "D": []}[record["candidate_alias"]]
        primary = self.scope()["stage_comparisons"]["primary"]
        self.assertEqual(primary["severe_classification_disagreement_pairs"], 5)
        self.assertEqual(primary["serious_presence_disagreement_pairs"], 3)
        self.assertEqual(primary["major_presence_disagreement_pairs"], 4)
        self.assertEqual(primary["critical_presence_disagreement_pairs"], 3)
        self.assertEqual(primary["severe_claim_scope_disagreement_pairs"], 6)
        self.assertEqual(self.scope()["stage_comparisons"]["final"]["severe_classification_disagreement_pairs"], 0)

    def test_final_origin_distinguishes_review_and_adjudication_without_score_fallback(self) -> None:
        for record in self.final:
            if record["window_id"] != "same":
                continue
            alias = record["candidate_alias"]
            if alias == "B":
                record["reviewed"] = True
            elif alias == "C":
                record.update(reviewed=True, adjudication={"resolved": True})
            elif alias == "D":
                record.update(semantic=None, naturalness=None, status="unresolved", adjudication={"resolved": False},
                              provisional_primary={"semantic": 4})
        review = [dict(record) for record in self.primary if record["candidate_alias"] in {"A", "B"}]
        scope = self.scope(review=review)
        self.assertEqual(scope["stage_comparisons"]["final"]["missing_semantic_pairs"], 3)
        same_pairs = [pair for pair in scope["pairs"] if pair["window_id"] == "same"]
        origins = {tuple(pair["final_origins"]) for pair in same_pairs}
        self.assertIn(("primary_only", "review_agreement"), origins)
        self.assertIn(("adjudicated", "unresolved_adjudication"), origins)
        self.assertEqual(scope["final_origin_candidate_window_counts"]["adjudicated"], 1)
        self.assertEqual(scope["final_origin_candidate_window_counts"]["unresolved_adjudication"], 1)
        self.assertEqual(scope["stage_comparisons"]["review"]["known_semantic_pairs"], 2)
        self.assertEqual(scope["within_alias_primary_review"]["known_semantic_pairs"], 4)
        self.assertEqual(scope["stage_comparisons"]["primary"]["nonzero_difference_pairs"], 0)

    def test_scope_partition_no_combined_quality_distribution_and_order_determinism(self) -> None:
        for row in self.expected:
            row["set"] = "regression" if row["window_id"] == "same" else "expanded"
        summary = self.analyze()
        self.assertEqual(set(summary["sets"]), {"regression", "expanded"})
        self.assertEqual(summary["sets"]["regression"]["identical_output_pairs"], 6)
        self.assertEqual(summary["sets"]["expanded"]["identical_output_pairs"], 2)
        self.assertNotIn("stage_comparisons", summary)
        self.expected.reverse()
        self.primary.reverse()
        self.final.reverse()
        self.results = {alias: list(reversed(rows)) for alias, rows in reversed(list(self.results.items()))}
        self.assertEqual(self.analyze(), summary)

    def test_invalid_scopes_duplicates_and_scores_are_setup_errors(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate candidate/window"):
            analyze_identical_outputs(self.expected + self.expected[:1], self.results)
        self.results["A"].append(deepcopy(self.results["A"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate candidate result"):
            self.analyze()
        self.results["A"].pop()
        self.primary.append({"candidate_alias": "A", "window_id": "wrong", "semantic": 4, "errors": []})
        with self.assertRaisesRegex(ValueError, "unexpected candidate/window"):
            self.analyze()
        self.primary.pop()
        self.primary[0]["semantic"] = True
        with self.assertRaisesRegex(ValueError, "invalid semantic"):
            self.analyze()
        self.primary[0]["semantic"] = 4
        self.expected[0]["scored_ids"] = ["u1"]
        with self.assertRaisesRegex(ValueError, "expected candidate scopes differ"):
            self.analyze()

    def test_report_and_summary_do_not_leak_translation_or_error_evidence(self) -> None:
        self.primary[0]["errors"] = [finding("major")]
        summary = self.analyze()
        text = report(summary)
        serialized = json.dumps(summary, ensure_ascii=False)
        for marker in ("PRIVATE_OUTPUT_MARKER", "PRIVATE_SOURCE_MARKER", "合成错误描述"):
            self.assertNotIn(marker, text)
            self.assertNotIn(marker, serialized)
        self.assertIn("同一 Sol 模型家族", text)
        self.assertIn("不能证明译文／参考正确", text)
        self.assertIn("不能统称为独立盲评", text)
        self.assertEqual(len(summary["sets"]["expanded"]["groups"][0]["translation_map_sha256"]), 64)

    def test_cli_provenance_configuration_and_source_snapshot(self) -> None:
        scratch = Path(__file__).resolve().parents[2] / ".local" / "translation-evaluation-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            root = Path(directory)
            for name, rows in (("expected", self.expected), ("primary", self.primary), ("final", self.final)):
                dump_jsonl(root / f"{name}.jsonl", rows)
            args = ["--expected", str(root / "expected.jsonl"), "--primary", str(root / "primary.jsonl"),
                    "--final", str(root / "final.jsonl"), "--set-name", "expanded", "--output", str(root / "output")]
            for alias, rows in self.results.items():
                dump_jsonl(root / f"{alias}.jsonl", rows)
                args.extend(["--candidate", alias + "=" + str(root / f"{alias}.jsonl")])
            self.assertEqual(main(args), 0)
            self.assertEqual({path.name for path in (root / "output").iterdir()}, {
                "summary.json", "diagnostics-config.json", "report.md",
                "aggregation-executed-identical-output-diagnostics.py"})
            summary = read_json(root / "output" / "summary.json")
            config = read_json(root / "output" / "diagnostics-config.json")
            self.assertEqual(summary["input_provenance"]["candidate:A"]["sha256"], hashlib.sha256((root / "A.jsonl").read_bytes()).hexdigest())
            self.assertEqual(config["configuration"], summary["configuration"])
            self.assertEqual(hashlib.sha256((root / "output" / "aggregation-executed-identical-output-diagnostics.py").read_bytes()).hexdigest(),
                             summary["diagnostics_source_sha256"])
            text = (root / "output" / "report.md").read_text(encoding="utf-8")
            self.assertEqual(text, report(summary))
            self.assertNotIn("PRIVATE_OUTPUT_MARKER", text)
            sentinel = root / "output" / "sentinel.txt"
            sentinel.write_bytes(b"preserve existing history\r\n")
            before = {path.name: path.read_bytes() for path in (root / "output").iterdir()}
            with self.assertRaises(FileExistsError):
                main(args)
            self.assertEqual({path.name: path.read_bytes() for path in (root / "output").iterdir()}, before)


if __name__ == "__main__":
    unittest.main()
