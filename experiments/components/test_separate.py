"""GPU-free boundary tests for private derived audio and unchanged coordinates."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import wave

from experiments.components.separate import (
    read_pcm, resampled_length, source_origin_sample, trim_count, validate_output,
)


class SeparateContractTests(unittest.TestCase):
    def test_round_trip_ceil_never_loses_an_original_sample(self) -> None:
        for samples in list(range(1, 1000)) + [16000, 16001, 16000 * 300]:
            high = resampled_length(samples, 16000, 44100)
            back = resampled_length(high, 44100, 16000)
            self.assertIn(trim_count(back, samples), (0, 1))

    def test_unexpected_length_is_not_hidden_by_padding(self) -> None:
        for actual in (0, 9, 12, 500):
            with self.assertRaises(ValueError):
                trim_count(actual, 10)

    def test_sample_origin_keeps_source_coordinates(self) -> None:
        self.assertEqual(source_origin_sample(121.0000625), 1936001)
        for offset in (-1, float("nan"), float("inf"), 0.00001):
            with self.assertRaises(ValueError):
                source_origin_sample(offset)

    def test_output_cannot_escape_private_root_or_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            local = parent / ".local"
            local.mkdir()
            self.assertEqual(validate_output(local / "new", local), (local / "new").resolve())
            for destination in (parent / "public", local / ".." / "public", local):
                with self.assertRaises(ValueError):
                    validate_output(destination, local)
            existing = local / "existing"
            existing.mkdir()
            with self.assertRaises(FileExistsError):
                validate_output(existing, local)

    def test_pcm_validation_hashes_exact_file_and_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "speech 日本語.wav"
            pcm = b"\x00\x00\x01\x00\xff\x7f"
            with wave.open(str(path), "wb") as output:
                output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                output.writeframes(pcm)
            actual, identity = read_pcm(path)
            self.assertEqual(actual, pcm)
            self.assertEqual(identity["samples"], 3)
            self.assertEqual(identity["duration_s"], 3 / 16000)
            self.assertEqual(len(identity["file_sha256"]), 64)
            with wave.open(str(path), "wb") as output:
                output.setparams((2, 2, 16000, 0, "NONE", "not compressed"))
                output.writeframes(pcm + b"\x00\x00")
            with self.assertRaises(ValueError):
                read_pcm(path)

    def test_empty_and_truncated_pcm_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "empty.wav"
            with wave.open(str(path), "wb") as output:
                output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            with self.assertRaises(ValueError):
                read_pcm(path)
            with wave.open(str(path), "wb") as output:
                output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                output.writeframes(b"\x01\x00" * 20)
            with path.open("r+b") as stream:
                stream.truncate(path.stat().st_size - 10)
            with self.assertRaises(ValueError):
                read_pcm(path)


if __name__ == "__main__":
    unittest.main()
