"""Offline tests for confirmation selection, exposure guards and immutable crops."""
from pathlib import Path
import struct
import tempfile
import unittest
import wave
from unittest.mock import patch

from experiments.components import prepare_confirmation as prepare


class ConfirmationPreparationTests(unittest.TestCase):
    def test_fractions_exact_samples_and_exposure_guard(self):
        duration = 7325.333333
        windows = prepare.fixed_windows(duration, 117205333)
        self.assertEqual([w["source_start_seconds"] for w in windows],
                         [732.5333125, 2014.4666875, 3296.4, 4212.0666875, 5310.8666875, 6592.8])
        self.assertTrue(all(w["source_end_sample"] - w["source_start_sample"] == 4800000 for w in windows))
        exposed = [{"source_start_sample": round(duration * f * 16000),
                    "source_end_sample": round(duration * f * 16000) + 4800000}
                   for f in prepare.round2.FRACTIONS]
        exposed += [{"source_start_sample": round(a * 16000), "source_end_sample": round(b * 16000)}
                    for a, b in prepare.SPOTCHECKS]
        self.assertAlmostEqual(prepare.validate_intervals(windows, exposed), 66.266625, places=6)
        for window in windows:
            self.assertEqual(window["source_end_seconds"], window["source_end_sample"] / 16000)
            self.assertAlmostEqual(window["source_start_seconds"] + 123 / 16000,
                                   (window["source_start_sample"] + 123) / 16000, places=10)

    def test_overlap_and_guard_rejected_without_outputs(self):
        window = {"source_start_sample": 1600000, "source_end_sample": 6400000}
        for exposed in ({"source_start_sample": 6399999, "source_end_sample": 6500000},
                        {"source_start_sample": 6400000 + 959999, "source_end_sample": 8000000}):
            with self.assertRaises(ValueError):
                prepare.validate_intervals([window], [exposed])
        self.assertEqual(prepare.validate_intervals([window],
                         [{"source_start_sample": 7360000, "source_end_sample": 8000000}]), 60)
        with self.assertRaises(ValueError):
            prepare.fixed_windows(1000, 16000000)

    def test_invalid_identity_fails_before_output_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / ".local/components/new"
            corpus = {"films": [{"id": "hf-iii"}]}
            flat = {"clips": [{"film": "hf-iii"}] * 6, "corpus_manifest_sha256": "incorrect"}
            with patch.object(prepare, "ROOT", root), patch.object(prepare, "read", side_effect=[flat, corpus]), \
                 patch.object(prepare.original, "sha256", return_value="actual"):
                with self.assertRaisesRegex(ValueError, "corpus identity"):
                    prepare.prepare(output, round2_root=root / "old", media_manifest=root / "spots.json")
            self.assertFalse(output.exists())

    def test_reused_crop_preserves_source_and_pcm_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, crop = root / "source.wav", root / "crop.wav"
            pcm = struct.pack("<32000h", *(i % 32767 for i in range(32000)))
            with wave.open(str(source), "wb") as stream:
                stream.setparams((1, 2, 16000, 32000, "NONE", "not compressed"))
                stream.writeframes(pcm)
            before = prepare.original.sha256(source)
            prepare.round2.crop_pcm(source, crop, 123, 30123)
            with wave.open(str(crop), "rb") as stream:
                self.assertEqual(stream.readframes(stream.getnframes()), pcm[246:60246])
            info = prepare.original.describe_audio(crop, 123 / 16000)
            self.assertEqual(info["source_end_seconds"], 30123 / 16000)
            self.assertEqual(prepare.original.sha256(source), before)
            with self.assertRaises(ValueError):
                prepare.round2.crop_pcm(source, crop, 123, 30123)


if __name__ == "__main__":
    unittest.main()
