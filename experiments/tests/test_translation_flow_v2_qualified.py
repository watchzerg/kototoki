from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from experiments.translation_corpus.flow_v2_qualified import publish, validate_accepted
from experiments.translation_corpus.prepare import digest, write_json, write_jsonl


def fixture() -> tuple[list[dict], list[dict]]:
    rows = []
    for split in ("screen-a", "screen-b"):
        for role, count in (("representative", 36), ("risk", 12)):
            for i in range(count):
                index = len(rows)
                sid = f"scene{index // 3}"
                wid = f"q{index}"
                unit = {"id": f"j{index}", "ja_srt_index": index + 1, "zh_srt_index": index + 1, "start": index, "end": index + 0.9, "score": True, "source_events": {"ja": [], "zh": []}}
                rows.append({"id": wid, "scene_id": sid, "work_id": "M01", "work": "Synthetic", "category": "animation_movie", "episode_id": "M01", "source_sha256": "hash", "selection_type": role, "selection_group": sid, "split": split, "scored_ids": [unit["id"]], "visible_start_index": 3 * (index // 3) + 1, "visible_end_index": 3 * (index // 3) + 3, "source_event_keys": [], "position_stratum": 0, "historically_visible_context_events": 0, "units": [unit]})
    reserve = copy.deepcopy(rows[0])
    reserve.update({"id": "reserve", "split": "screening", "scored_ids": ["new"]})
    reserve["units"][0]["id"] = "new"
    return rows, [reserve]


def confirmation_fixture() -> tuple[list[dict], list[dict]]:
    rows, reserve = fixture()
    rows = rows[:48]
    for row in rows + reserve:
        row.update(split="confirmation", selection_type="representative")
    return rows, reserve


class QualifiedSourceTests(unittest.TestCase):
    def test_confirmation_requires_48_representative_windows_and_same_scene_reserves(self):
        rows, reserve = confirmation_fixture()
        step = {"removed": rows[0]["id"], "added": reserve[0]["id"], "split": "confirmation", "selection_group": rows[0]["selection_group"], "selection_type": "representative"}
        accepted = [copy.deepcopy(reserve[0])] + copy.deepcopy(rows[1:])
        mapping = validate_accepted(rows, reserve, accepted, [step], role="confirmation")
        self.assertEqual(mapping[rows[0]["id"]], "reserve")
        with self.assertRaisesRegex(ValueError, "48 windows"):
            validate_accepted(rows[:-1], reserve, copy.deepcopy(rows[:-1]), [], role="confirmation")
        risk = copy.deepcopy(rows)
        risk[0]["selection_type"] = "risk"
        with self.assertRaisesRegex(ValueError, "role/split quotas"):
            validate_accepted(risk, reserve, copy.deepcopy(risk), [], role="confirmation")
        with self.assertRaisesRegex(ValueError, "96 windows"):
            validate_accepted(rows, reserve, copy.deepcopy(rows), [])
        with self.assertRaisesRegex(ValueError, "role must"):
            validate_accepted([], [], [], [], role="unknown")

    def test_confirmation_publication_uses_separate_safe_pointers_and_no_calibration(self):
        temp_root = Path(__file__).resolve().parents[2] / ".local/tests/qualified-source"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as temporary:
            root = Path(temporary)
            original = root / "original"
            rows, reserve = confirmation_fixture()
            scene_rows = []
            for sid in sorted({r["scene_id"] for r in rows}):
                ids = [r["scored_ids"][0] for r in rows if r["scene_id"] == sid]
                scene_rows.append({"id": sid, "scene_id": sid, "context": [{"id": x, "text": "Synthetic source only"} for x in ids], "translate_ids": ids})
            write_json(original / "source-manifest.json", {"version": "hy30-flow-v2-source-v1", "external_corpus": str(root / "external"), "windows": rows})
            write_jsonl(original / "audit/reserve-manifest.jsonl", reserve)
            write_jsonl(original / "model-input/scenes.jsonl", scene_rows)
            original_scene_bytes = (original / "model-input/scenes.jsonl").read_bytes()
            artifacts = [{"path": p.relative_to(original).as_posix(), "sha256": digest(p)} for p in sorted(original.rglob("*")) if p.is_file()]
            write_json(original / "freeze-manifest.json", {"version": "hy30-flow-v2-source-v1", "state": "source_frozen_reference_unreviewed", "role": "confirmation", "policy_sha256": "synthetic", "artifacts": artifacts})
            accepted_file, reference_marker, replacements_file = root / "accepted.json", root / "reference-freeze.json", root / "replacements.jsonl"
            write_json(accepted_file, {"corpus_version": "hy30-flow-v2-reference-v1", "windows": rows})
            write_json(reference_marker, {"state": "synthetic-reference-qualification-fixture"})
            write_jsonl(replacements_file, [])
            qualification = {"reference_qualification": {"path": str(reference_marker), "sha256": digest(reference_marker), "version": "hy30-flow-v2-reference-v1", "state": "frozen_double_fresh_reference_review", "inference_allowed": True}, "confirmation_manifest": {"path": str(accepted_file), "sha256": digest(accepted_file)}, "confirmation_replacements": {"path": str(replacements_file), "sha256": digest(replacements_file)}, "confirmation_windows": 48}
            qualification_file = root / "qualification.json"
            write_json(qualification_file, qualification)
            with self.assertRaisesRegex(ValueError, "screening freeze"):
                publish(original, qualification_file, root / "wrong-role")
            result = publish(original, qualification_file, root / "qualified", role="confirmation")
            self.assertEqual((result["role"], result["windows"]), ("confirmation", 48))
            self.assertEqual((root / "qualified/model-input/scenes.jsonl").read_bytes(), original_scene_bytes)
            self.assertFalse((root / "qualified/calibration-selection.json").exists())
            self.assertTrue((root / "qualified/audit/confirmation-replacements.jsonl").exists())
            self.assertEqual((original / "model-input/scenes.jsonl").read_bytes(), original_scene_bytes)

    def test_exact_accepted_metadata_without_replacements(self):
        rows, reserve = fixture()
        mapping = validate_accepted(rows, reserve, copy.deepcopy(rows), [])
        self.assertTrue(all(k == v for k, v in mapping.items()))

    def test_reserve_replacement_maps_initial_id_preserving_split(self):
        rows, reserve = fixture()
        step = {"removed": rows[0]["id"], "added": reserve[0]["id"], "split": rows[0]["split"], "selection_group": rows[0]["selection_group"], "selection_type": rows[0]["selection_type"]}
        accepted = [{**reserve[0], "split": rows[0]["split"]}] + copy.deepcopy(rows[1:])
        mapping = validate_accepted(rows, reserve, accepted, [step])
        self.assertEqual(mapping[rows[0]["id"]], reserve[0]["id"])

    def test_unfrozen_reselection_and_provenance_mutation_rejected(self):
        rows, reserve = fixture()
        mutated = copy.deepcopy(rows)
        mutated[0]["units"][0]["start"] += 0.01
        with self.assertRaisesRegex(ValueError, "provenance"):
            validate_accepted(rows, reserve, mutated, [])
        step = {"removed": rows[0]["id"], "added": "unknown", "split": rows[0]["split"], "selection_group": rows[0]["selection_group"], "selection_type": rows[0]["selection_type"]}
        with self.assertRaisesRegex(ValueError, "frozen reserve"):
            validate_accepted(rows, reserve, rows, [step])

    def test_cross_scene_or_split_replacement_rejected(self):
        rows, reserve = fixture()
        step = {"removed": rows[0]["id"], "added": "reserve", "split": "screen-b", "selection_group": rows[0]["selection_group"], "selection_type": rows[0]["selection_type"]}
        with self.assertRaisesRegex(ValueError, "split"):
            validate_accepted(rows, reserve, rows, [step])
        step["split"] = "screen-a"
        reserve[0]["scene_id"] = "another-scene"
        with self.assertRaisesRegex(ValueError, "same-scene"):
            validate_accepted(rows, reserve, rows, [step])

    def test_reserve_order_cannot_skip_eligible_candidate(self):
        rows, reserve = fixture()
        reserve[0]["reserve_rank"] = 0
        later = copy.deepcopy(reserve[0])
        later.update({"id": "later", "reserve_rank": 1, "scored_ids": ["later-cue"]})
        later["units"][0]["id"] = "later-cue"
        step = {"removed": rows[0]["id"], "added": "later", "split": rows[0]["split"], "selection_group": rows[0]["selection_group"], "selection_type": rows[0]["selection_type"]}
        with self.assertRaisesRegex(ValueError, "reserve order"):
            validate_accepted(rows, reserve + [later], rows, [step])

    def test_publication_allows_event_language_metadata_but_rejects_reference_text(self):
        temp_root = Path(__file__).resolve().parents[2] / ".local/tests/qualified-source"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as temporary:
            root = Path(temporary)
            original = root / "original"
            rows, reserve = fixture()
            for i, row in enumerate(rows):
                row["work_id"] = f"M{i % 10:02d}"
            scene_rows = []
            for sid in sorted({r["scene_id"] for r in rows}):
                ids = [r["scored_ids"][0] for r in rows if r["scene_id"] == sid]
                scene_rows.append({"id": sid, "scene_id": sid, "context": [{"id": x, "text": "Synthetic Japanese source"} for x in ids], "translate_ids": ids})
            write_json(original / "source-manifest.json", {"version": "hy30-flow-v2-source-v1", "external_corpus": str(root / "external"), "windows": rows})
            write_jsonl(original / "audit/reserve-manifest.jsonl", reserve)
            write_jsonl(original / "model-input/scenes.jsonl", scene_rows)
            write_json(original / "calibration-selection.json", {"window_ids": [r["id"] for r in rows[:16]]})
            artifacts = [{"path": p.relative_to(original).as_posix(), "sha256": digest(p)} for p in sorted(original.rglob("*")) if p.is_file()]
            write_json(original / "freeze-manifest.json", {"version": "hy30-flow-v2-source-v1", "state": "source_frozen_reference_unreviewed", "role": "screening", "policy_sha256": "synthetic", "artifacts": artifacts})
            accepted_file, reference_marker, replacements_file = root / "accepted.json", root / "reference-freeze.json", root / "replacements.jsonl"
            write_json(accepted_file, {"corpus_version": "hy30-flow-v2-reference-v1", "windows": rows})
            write_json(reference_marker, {"state": "synthetic-reference-qualification-fixture"})
            write_jsonl(replacements_file, [])
            qualification = {"reference_qualification": {"path": str(reference_marker), "sha256": digest(reference_marker), "version": "hy30-flow-v2-reference-v1", "state": "frozen_double_fresh_reference_review", "inference_allowed": True}, "screening_manifest": {"path": str(accepted_file), "sha256": digest(accepted_file)}, "screening_replacements": {"path": str(replacements_file), "sha256": digest(replacements_file)}, "screening_windows": 96}
            qualification_file = root / "qualification.json"
            write_json(qualification_file, qualification)
            result = publish(original, qualification_file, root / "qualified")
            self.assertEqual(result["windows"], 96)
            self.assertEqual((root / "qualified/model-input/scenes.jsonl").read_bytes(), (original / "model-input/scenes.jsonl").read_bytes())
            rows[0]["units"][0]["original_zh"] = "Forbidden synthetic reference text"
            write_json(accepted_file, {"corpus_version": "hy30-flow-v2-reference-v1", "windows": rows})
            qualification["screening_manifest"]["sha256"] = digest(accepted_file)
            write_json(qualification_file, qualification)
            with self.assertRaisesRegex(ValueError, "semantic fields"):
                publish(original, qualification_file, root / "forbidden-output")


if __name__ == "__main__":
    unittest.main()
