"""Offline checks for full-film reference coverage and immutable PCM reuse."""

import json
from pathlib import Path
import struct
import tempfile
import unittest
import wave

from experiments.fullfilm_comparison import corpus


def cue(identity: str, start: float, end: float, text: str = "台詞") -> dict:
    return {"id": identity, "cue_id": int(identity), "start": start, "end": end,
            "original_text": text, "text": "parser stripped text", "removed_prefix_labels": ["（声）"],
            "flags": [], "spoken_status": "unreviewed", "acoustic_review": False}


class CorpusTests(unittest.TestCase):
    def test_bins_cover_every_sample_and_tail(self):
        samples = 605 * corpus.RATE + 1
        bins = corpus.scoring_bins(samples, "film")
        self.assertEqual(len(bins), 3)
        self.assertEqual(bins[0]["source_start_sample"], 0)
        self.assertEqual(bins[-1]["source_end_sample"], samples)
        self.assertEqual(sum(b["source_end_sample"] - b["source_start_sample"] for b in bins), samples)
        for left, right in zip(bins, bins[1:]):
            self.assertEqual(left["source_end_sample"], right["source_start_sample"])
        self.assertEqual(bins[-1]["duration_seconds"], 5 + 1 / corpus.RATE)
        for invalid in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                corpus.scoring_bins(invalid, "film")

    def test_midpoint_assignment_once_preserves_all_text_and_times(self):
        spans = [cue("1", 0, 1, "（声）台詞！"), cue("2", 299, 301),
                 cue("3", 300, 301), cue("4", 602, 605, "最後")]
        reference, bins = corpus.full_reference(spans, 605 * corpus.RATE, "film", "hash")
        assigned = [identity for bucket in bins for identity in bucket["cue_ids"]]
        self.assertEqual(len(set(assigned)), 4)
        self.assertEqual(len(assigned), 4)
        self.assertEqual(reference["spans"][0]["text"], "（声）台詞！")
        self.assertEqual(reference["spans"][0]["removed_prefix_labels"], [])
        self.assertEqual(reference["spans"][0]["parser_removed_prefix_labels"], ["（声）"])
        self.assertEqual(reference["spans"][1]["bin_id"], "film-bin-02")
        self.assertTrue(reference["spans"][1]["boundary_crossing"])
        self.assertFalse(reference["spans"][2]["boundary_crossing"])
        self.assertEqual(reference["spans"][-1]["end"], 605)
        self.assertEqual(reference["reference_characters"], sum(b["reference_characters"] for b in bins))
        self.assertFalse(reference["acoustic_ground_truth"])

    def test_cue_exactly_at_bin_end_is_not_crossing(self):
        reference, bins = corpus.full_reference([cue("1", 298, 300)], 600 * corpus.RATE, "film", "hash")
        self.assertFalse(reference["spans"][0]["boundary_crossing"])
        self.assertEqual(bins[0]["reference_cue_count"], 1)
        self.assertEqual(bins[1]["reference_cue_count"], 0)

    def test_reject_outside_duplicate_empty_or_invalid_cues(self):
        for spans in ([cue("1", -1, 1)], [cue("1", 1, 601)], [cue("1", 1, 1)],
                      [cue("1", 1, float("nan"))], [cue("1", 1, 2, " ")],
                      [cue("1", 1, 2), cue("1", 3, 4)]):
            with self.subTest(spans=spans), self.assertRaises(ValueError):
                corpus.full_reference(spans, 600 * corpus.RATE, "film", "hash")

    def test_reused_pcm_descriptor_detects_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio, descriptor = root / "full.wav", root / "full.json"
            with wave.open(str(audio), "wb") as output:
                output.setparams((1, 2, corpus.RATE, 4, "NONE", "not compressed"))
                output.writeframes(struct.pack("<4h", 0, 100, -100, 0))
            info = corpus.describe_audio(audio, 0)
            corpus.write_immutable(descriptor, info)
            self.assertEqual(corpus.verify_existing_audio(audio, descriptor, 0), info)
            with audio.open("r+b") as stream:
                stream.seek(-2, 2)
                stream.write(b"\x01\x00")
            with self.assertRaises(ValueError):
                corpus.verify_existing_audio(audio, descriptor, 0)
            self.assertEqual(json.loads(descriptor.read_text()), info)

    def test_immutable_reference_rejects_changed_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "reference.json"
            reference, _ = corpus.full_reference([cue("1", 0, 1)], 600 * corpus.RATE, "film", "hash")
            corpus.write_immutable(path, reference)
            corpus.write_immutable(path, reference)
            changed = dict(reference, source_end_seconds=500)
            with self.assertRaises(ValueError):
                corpus.write_immutable(path, changed)


if __name__ == "__main__":
    unittest.main()
