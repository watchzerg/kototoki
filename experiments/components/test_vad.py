"""Offline tests for VAD crop coordinates and exact source PCM preservation."""
from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from experiments.components.separate import read_pcm
from experiments.components.vad import MAX_SAMPLES, padded_chunks, write_crop


class VadCropTests(unittest.TestCase):
    def test_empty_speech_produces_no_artificial_chunk(self) -> None:
        self.assertEqual(padded_chunks([], 32000), [])

    def test_context_is_clipped_to_input_and_avoids_duplicate_samples(self) -> None:
        chunks = padded_chunks([{"start": 0.1, "end": 1}, {"start": 1.1, "end": 1.9}], 32000)
        self.assertEqual(chunks[0]["start_sample"], 0)
        self.assertEqual(chunks[-1]["end_sample_exclusive"], 32000)
        self.assertEqual(chunks[0]["end_sample_exclusive"], chunks[1]["start_sample"])
        self.assertEqual(chunks[1]["start_sample"], 16800)

    def test_native_thirty_second_cut_survives_context(self) -> None:
        chunks = padded_chunks([{"start": 0, "end": 30}, {"start": 30, "end": 60}], 960000)
        self.assertEqual([(c["start_sample"], c["end_sample_exclusive"]) for c in chunks],
                         [(0, 480000), (480000, 960000)])

    def test_long_native_core_is_explicitly_split_without_missing_samples(self) -> None:
        chunks = padded_chunks([{"start": 1, "end": 65}], 70 * 16000)
        self.assertEqual(len(chunks), 3)
        for chunk in chunks:
            self.assertLessEqual(chunk["end_sample_exclusive"] - chunk["start_sample"], MAX_SAMPLES)
        for before, after in zip(chunks, chunks[1:]):
            self.assertEqual(before["end_sample_exclusive"], after["start_sample"])

    def test_context_only_trim_keeps_core_and_nonoverlap(self) -> None:
        chunks = padded_chunks([{"start": 2, "end": 31.9}, {"start": 40, "end": 42}], 50 * 16000)
        for chunk in chunks:
            self.assertLessEqual(chunk["end_sample_exclusive"] - chunk["start_sample"], MAX_SAMPLES)
            self.assertLessEqual(chunk["start_sample"], chunk["speech_start_sample"])
            self.assertGreaterEqual(chunk["end_sample_exclusive"], chunk["speech_end_sample_exclusive"])
        self.assertLess(chunks[0]["end_sample_exclusive"], chunks[1]["start_sample"])

    def test_invalid_native_times_are_rejected(self) -> None:
        for native in ([{"start": 1, "end": 1}], [{"start": float("nan"), "end": 2}],
                       [{"start": 0, "end": 2}, {"start": 1, "end": 3}]):
            with self.assertRaises(ValueError):
                padded_chunks(native, 160000)

    def test_crop_preserves_exact_pcm_and_cannot_overwrite(self) -> None:
        pcm = b"\x00\x00\x01\x00\xff\x7f\x00\x80"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "日本語.wav"
            identity = write_crop(path, pcm, 1, 3)
            actual, read_identity = read_pcm(path)
            self.assertEqual(actual, pcm[2:6])
            self.assertEqual(identity["samples"], 2)
            self.assertEqual(identity["pcm_sha256"], hashlib.sha256(pcm[2:6]).hexdigest())
            self.assertEqual(identity["file_sha256"], read_identity["file_sha256"])
            with self.assertRaises(FileExistsError):
                write_crop(path, pcm, 1, 3)


if __name__ == "__main__":
    unittest.main()
