"""Source-only scope merging and single-variant preparations using synthetic SRT."""

from pathlib import Path
import tempfile
import unittest

from experiments.translation_eval.runner import dump, dump_jsonl, read_json
from .cli import load_prepared
from .screening import VARIANTS, build
from .srt import read_srt


class ScreeningTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch = Path(__file__).resolve().parents[2] / ".local/translation-screening-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.srt"
        text = "\n\n".join(f"{100 + index * 3}\n00:00:{index:02},000 --> 00:00:{index:02},900\n台詞{index}。"
                            for index in range(50)) + "\n"
        self.source.write_text(text, encoding="utf-8")
        self.cues = read_srt(self.source).cues
        self.inputs, self.mapping = self.root / "inputs.jsonl", self.root / "mapping.json"
        self.budgets = {"max_translation_calls": 40, "max_judge_calls": 0,
                        "max_estimated_tokens": 100000, "max_wall_seconds": 120}
        self.select([12, 17, 36])

    def tearDown(self) -> None:
        self.temp.cleanup()

    def select(self, starts: list[int]) -> None:
        inputs, mapping = [], []
        for number, start in enumerate(starts):
            wid = f"w{number}"
            selected = self.cues[start:start + 3]
            ids = [f"{wid}-{index}" for index in range(len(selected))]
            inputs.append({"id": wid, "source_language": "ja", "target_language": "zh-Hans",
                           "context": [{"id": uid, "text": cue.text}
                                                    for uid, cue in zip(ids, selected)], "translate_ids": ids})
            mapping.append({"window_id": wid, "source_srt": "source.srt",
                            "cue_map": {uid: cue.id for uid, cue in zip(ids, selected)}})
        dump_jsonl(self.inputs, inputs)
        dump(self.mapping, {"windows": mapping})

    def test_overlap_merges_by_source_ordinal_without_duplicate_targets(self) -> None:
        manifest = build(self.inputs, self.mapping, self.root / "screen", "fixed5context1", self.budgets)
        self.assertEqual(manifest["excerpt_count"], 2)
        first, second = manifest["excerpts"]
        self.assertEqual((first["first_ordinal"], first["last_ordinal"]), (8, 25))
        self.assertEqual(first["window_ids"], ["w0", "w1"])
        self.assertEqual((second["first_ordinal"], second["last_ordinal"]), (32, 44))
        self.assertEqual(first["start_cue"], self.cues[7].index)
        self.assertEqual(first["end_cue"], self.cues[24].index)
        targets = set()
        for item in manifest["excerpts"]:
            _, _, windows, workload = load_prepared(Path(item["prepared"]))
            ids = {uid for window in windows for uid in window["translate_ids"]}
            self.assertFalse(ids & targets)
            targets.update(ids)
            self.assertEqual(workload["label"], "b0-prompt")
            self.assertEqual(workload["recipe"], "b0-prompt")
            self.assertEqual(workload["sampling"], "official-temperature0")
            self.assertEqual(workload["n_predict"], 1024)
        self.assertEqual(len(targets), 31)
        self.assertEqual(manifest["total_batches"], 7)

    def test_each_invocation_produces_only_one_named_variant(self) -> None:
        self.select([12])
        for variant, expected in VARIANTS.items():
            with self.subTest(variant=variant):
                manifest = build(self.inputs, self.mapping, self.root / variant, variant, self.budgets)
                self.assertEqual(manifest["variant"], variant)
                self.assertEqual(manifest["excerpt_count"], 1)
                prepared = read_json(Path(manifest["excerpts"][0]["prepared"]) / "prepared.json")
                for key, value in expected.items():
                    self.assertEqual(prepared["batching"][key], value)
                self.assertEqual(prepared["candidate"], "hy-mt2-30b-a3b-apex-i-compact")

    def test_padding_clips_to_source_bounds(self) -> None:
        self.select([0, 48])
        manifest = build(self.inputs, self.mapping, self.root / "clipped", "fixed5context1", self.budgets)
        self.assertEqual([(entry["first_ordinal"], entry["last_ordinal"]) for entry in manifest["excerpts"]],
                         [(1, 8), (44, 50)])

    def test_reference_fields_and_wrong_source_mapping_are_rejected(self) -> None:
        mapping = read_json(self.mapping)
        mapping["references"] = "never-read.jsonl"
        dump(self.mapping, mapping)
        with self.assertRaisesRegex(ValueError, "only a windows list"):
            build(self.inputs, self.mapping, self.root / "bad", "fixed5context1", self.budgets)
        self.select([12])
        mapping = read_json(self.mapping)
        mapping["windows"][0]["cue_map"]["w0-0"] = "13"
        dump(self.mapping, mapping)
        with self.assertRaisesRegex(ValueError, "source text/ID/order"):
            build(self.inputs, self.mapping, self.root / "bad", "fixed5context1", self.budgets)
        self.assertFalse((self.root / "bad").exists())

    def test_original_source_and_existing_preparations_are_preserved(self) -> None:
        original = self.source.read_bytes()
        target = self.root / "screen"
        build(self.inputs, self.mapping, target, "fixed5context1", self.budgets)
        self.assertEqual(self.source.read_bytes(), original)
        with self.assertRaisesRegex(ValueError, "new directory"):
            build(self.inputs, self.mapping, target, "fixed5context1", self.budgets)

    def test_stage_batch_cap_refuses_before_preparing(self) -> None:
        self.select([0, 12, 24, 36, 47])
        # All padded ranges overlap, creating one 50-cue workload / 10 batches.
        with self.assertRaisesRegex(ValueError, "P0 per-workload cap"):
            build(self.inputs, self.mapping, self.root / "over-cap", "fixed5context1", self.budgets, "P0")
        self.assertFalse((self.root / "over-cap").exists())


if __name__ == "__main__":
    unittest.main()
