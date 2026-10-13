"""Synthetic terminology scope, alias and non-semantic diagnostic checks."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from experiments.translation_eval.runner import dump, dump_jsonl, read_json
from experiments.translation_terminology_diagnostics import analyze, main, prepare_manifest, report


class TerminologyTests(unittest.TestCase):
    def setUp(self):
        self.inputs = [{"id": wid, "context": [{"id": "u", "text": "魔術の話"}, {"id": "context", "text": "先輩"}], "translate_ids": ["u"]} for wid in ("w1", "w2", "w3")]
        self.sources = {"windows": [{"id": wid, "work": "work", "category": "anime_series"} for wid in ("w1", "w2", "w3")]}
        self.catalog = {"candidate_outputs_used": False, "translator_use_allowed": False, "terms": [
            {"term_id": "magic", "source_forms": ["魔術"], "target_alias_groups": {"style_a": ["魔术", "魔術"], "style_b": ["魔法"]}},
            {"term_id": "senior", "source_forms": ["先輩"], "target_alias_groups": {"accepted": ["前辈", "学长"]}}]}

    def manifest(self):
        return prepare_manifest(self.inputs, self.sources, self.catalog, "expanded")

    def results(self, texts):
        return {alias: [{"id": "w" + str(i + 1), "translations": {"u": text}} for i, text in enumerate(texts)] for alias in "ABCD"}

    def test_source_selection_ignores_context_only_ids_and_requires_two_windows(self):
        manifest = self.manifest()
        self.assertEqual(manifest["source_selection"]["eligible_terms"], 1)
        self.assertEqual(manifest["source_selection"]["excluded_terms_below_two_windows"], ["senior"])
        self.assertEqual(len(manifest["eligible_occurrences"]), 3)
        self.assertEqual(manifest["expected_scored_ids"], 3)

    def test_formal_five_field_contract_and_metadata_scored_ids_are_verified(self):
        formal = [{**row, "source_language": "ja", "target_language": "zh-Hans"} for row in self.inputs]
        self.assertEqual(prepare_manifest(formal, self.sources, self.catalog, "expanded")["expected_windows"], 3)
        formal[0]["source_language"] = "zh"
        with self.assertRaisesRegex(ValueError, "language identity"):
            prepare_manifest(formal, self.sources, self.catalog, "expanded")
        formal[0]["source_language"] = "ja"
        self.sources["windows"][0]["scored_ids"] = ["context"]
        with self.assertRaisesRegex(ValueError, "scored ID scope"):
            prepare_manifest(formal, self.sources, self.catalog, "expanded")

    def test_legal_same_family_aliases_are_allowed_and_cross_family_is_not_semantic_error(self):
        summary = analyze(self.manifest(), self.results(["魔术", "魔術", "魔术"]))
        self.assertEqual(summary["candidate_results"]["A"]["potential_inconsistency_groups"], 0)
        self.assertEqual(summary["candidate_results"]["A"]["groups"][0]["observed_alias_variants"], 2)
        changed = analyze(self.manifest(), self.results(["魔术", "魔法", "魔术"]))
        group = changed["candidate_results"]["A"]["groups"][0]
        self.assertTrue(group["potential_inconsistency"])
        self.assertIsNone(group["semantic_error"])
        self.assertFalse(changed["semantic_scoring_performed"])

    def test_unknown_proper_names_ambiguous_and_missing_are_not_errors(self):
        summary = analyze(self.manifest(), self.results(["PRIVATE_UNKNOWN_NAME_7549", "魔术与魔法", ""]))
        counts = summary["candidate_results"]["A"]["status_counts"]
        self.assertEqual(counts, {"ambiguous_multiple_families": 1, "missing_translation": 1, "unclassified": 1})
        self.assertEqual(summary["candidate_results"]["A"]["potential_inconsistency_groups"], 0)
        serialized = json.dumps(summary, ensure_ascii=False)
        self.assertNotIn("PRIVATE_UNKNOWN_NAME_7549", serialized)
        self.assertIn("未命中不证明漏译", report(summary))

    def test_work_source_alias_and_context_rules_are_kept_separate(self):
        self.inputs[2]["context"][0]["text"] = "魔術と別の場面"
        self.catalog["terms"][0]["excluded_context_any"] = ["別の場面"]
        self.sources["windows"][1]["work"] = "other-work"
        summary = analyze(self.manifest(), self.results(["魔术", "魔法", "魔法"]))
        self.assertEqual(summary["candidate_results"]["A"]["expected_eligible_occurrences"], 2)
        self.assertEqual(summary["candidate_results"]["A"]["potential_inconsistency_groups"], 0)
        self.assertEqual(len(summary["candidate_results"]["A"]["groups"]), 2)

    def test_rejects_reference_leakage_duplicate_scopes_and_candidate_informed_catalog(self):
        bad = deepcopy(self.inputs)
        bad[0]["reference"] = "forbidden"
        with self.assertRaisesRegex(ValueError, "source-only"):
            prepare_manifest(bad, self.sources, self.catalog, "expanded")
        self.catalog["candidate_outputs_used"] = True
        with self.assertRaisesRegex(ValueError, "candidate-blind"):
            self.manifest()
        self.catalog["candidate_outputs_used"] = False
        outputs = self.results(["魔术", "魔术", "魔术"])
        outputs["A"].append(outputs["A"][0])
        with self.assertRaisesRegex(ValueError, "duplicate or unexpected"):
            analyze(self.manifest(), outputs)

    def test_cli_new_directory_snapshot_and_history_refusal(self):
        scratch = Path(__file__).resolve().parents[2] / ".local" / "translation-evaluation-tests"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            root = Path(directory)
            dump_jsonl(root / "inputs.jsonl", self.inputs)
            dump(root / "source.json", self.sources)
            dump(root / "catalog.json", self.catalog)
            args = ["prepare", "--inputs", str(root / "inputs.jsonl"), "--source-manifest", str(root / "source.json"),
                    "--catalog", str(root / "catalog.json"), "--set-name", "expanded", "--output", str(root / "prepared")]
            self.assertEqual(main(args), 0)
            manifest = read_json(root / "prepared" / "source-term-manifest.json")
            self.assertEqual(len(manifest["input_provenance"]["catalog"]["sha256"]), 64)
            before = {path.name: path.read_bytes() for path in (root / "prepared").iterdir()}
            with self.assertRaises(FileExistsError):
                main(args)
            self.assertEqual({path.name: path.read_bytes() for path in (root / "prepared").iterdir()}, before)
            args = ["analyze", "--manifest", str(root / "prepared" / "source-term-manifest.json"), "--output", str(root / "diagnostics")]
            for alias, rows in self.results(["魔术", "魔法", "魔術"]).items():
                dump_jsonl(root / (alias + ".jsonl"), rows)
                args += ["--candidate", alias + "=" + str(root / (alias + ".jsonl"))]
            self.assertEqual(main(args), 0)
            self.assertTrue((root / "diagnostics" / "report.md").is_file())


if __name__ == "__main__":
    unittest.main()
