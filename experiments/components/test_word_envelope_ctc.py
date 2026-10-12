"""Offline checks for bounds-only repair and unchanged cached ASR identity."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import wave

from experiments.components import word_envelope_ctc as repair
from experiments.components.separate import read_pcm, sha256
from experiments.components import test_align_raw_w0 as cached_asr_tests


class WordEnvelopeTests(unittest.TestCase):
    def test_native_word_outside_short_parent_changes_only_parent_bounds(self):
        segments = [{"start": 96.14, "end": 96.16, "text": "日本。", "id": 5,
                     "words": [{"start": 95.46, "end": 96.16, "word": "日本。", "probability": .9}]}]
        before = deepcopy(segments)
        fixed, mapping = repair.envelope(segments, 180)
        expected = deepcopy(segments)
        expected[0]["start"] = 95.46
        self.assertEqual(fixed, expected)
        self.assertEqual(segments, before)
        self.assertEqual(mapping[0]["source_sample_start"], int(95.46 * 16000))
        self.assertEqual(mapping[0]["source_sample_end_exclusive"], int(96.16 * 16000))
        self.assertTrue(mapping[0]["changed"])
        fixed[0]["words"][0]["word"] = "mutated"
        self.assertEqual(segments, before)

    def test_enclosing_parent_stays_exactly_unchanged(self):
        segments = [{"start": 1, "end": 3, "text": "a", "words": [{"start": 1.5, "end": 2, "word": "a"}]}]
        fixed, mapping = repair.envelope(segments, 4)
        self.assertEqual(fixed, segments)
        self.assertFalse(mapping[0]["changed"])

    def test_parent_clamp_and_empty_transcript_are_explicit(self):
        fixed, mapping = repair.envelope([{"start": -1, "end": 5, "text": "a", "words": []}], 4)
        self.assertEqual((fixed[0]["start"], fixed[0]["end"]), (0, 4))
        self.assertTrue(mapping[0]["parent_clamped"])
        self.assertEqual(repair.envelope([], 4), ([], []))

    def test_invalid_words_and_parent_bounds_fail_closed(self):
        cases = [
            [{"start": 1, "end": 2, "text": "a", "words": [{"start": -.1, "end": 1}]}],
            [{"start": 1, "end": 2, "text": "a", "words": [{"start": 1, "end": 5}]}],
            [{"start": 1, "end": 2, "text": "a", "words": [{"start": float("nan"), "end": 2}]}],
            [{"start": float("inf"), "end": 2, "text": "a", "words": []}],
            [{"start": 2, "end": 1, "text": "a", "words": []}],
            [{"start": 1, "end": 2, "text": "a", "words": [{"start": True, "end": 2}]}],
            [{"start": 1, "end": 2, "text": "a", "words": [{"start": 1, "end": 1.6}, {"start": 1.5, "end": 2}]}],
            [{"start": 1, "end": 2, "text": "a", "words": []},
             {"start": 2.1, "end": 3, "text": "b", "words": [{"start": 1.9, "end": 2.9}]}],
            [{"start": 2, "end": 2, "text": "a", "words": []}], [None],
        ]
        for segments in cases:
            with self.subTest(segments=segments), self.assertRaises(ValueError):
                repair.envelope(segments, 4)

    def test_bridge_binds_complete_text_audio_offset_and_original_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio, source = root / "audio.wav", root / "asr.json"
            with wave.open(str(audio), "wb") as writer:
                writer.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                writer.writeframes(b"\x01\x00" * 64000)
            _, identity = read_pcm(audio)
            saved, _ = cached_asr_tests.AlignRawW0Tests().fixture()
            saved["input"] = identity
            saved["original_segments"][0]["words"] = [{"start": .5, "end": 2, "word": "日本語"}]
            saved["native"]["segments"] = deepcopy(saved["original_segments"])
            source.write_text(json.dumps(saved), encoding="utf-8")
            original_hash = sha256(source)
            bridge = repair.build_bridge(source, audio, 120)
            repair.verify_bridge(bridge, saved, 120)
            self.assertEqual(sha256(source), original_hash)
            self.assertEqual(bridge["original_asr"]["original_segments"], saved["original_segments"])
            self.assertEqual(bridge["original_segments"][0]["start"], .5)
            self.assertEqual(bridge["text"], saved["text"])
            for field, value in (("offset_s", 121), ("text", "日本")):
                bad = deepcopy(bridge)
                bad[field] = value
                with self.assertRaises(ValueError):
                    repair.verify_bridge(bad, saved, 120)
            bad = deepcopy(bridge)
            bad["input"]["pcm_sha256"] = "changed"
            with self.assertRaises(ValueError):
                repair.verify_bridge(bad, saved, 120)


if __name__ == "__main__":
    unittest.main()
