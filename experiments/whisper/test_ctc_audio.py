"""GPU-free checks against the official checkpoint feature extractor."""
import unittest
from pathlib import Path

np = torch = Wav2Vec2FeatureExtractor = None
try:
    import numpy as np
    import torch
    from transformers import Wav2Vec2FeatureExtractor
except ImportError:
    np = torch = Wav2Vec2FeatureExtractor = None

from ctc_audio import SegmentNormalizer, digest, normalize_segments


@unittest.skipUnless(np is not None and torch is not None and Wav2Vec2FeatureExtractor is not None,
                     "Run normalization tests in the pinned WhisperX environment")
class NormalizationTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[2] / ".local/models/wav2vec2-large-xlsr-53-japanese"
        if not (path / "preprocessor_config.json").is_file():
            raise unittest.SkipTest("Provisioned local checkpoint feature-extractor config is unavailable")
        self.extractor = Wav2Vec2FeatureExtractor.from_pretrained(path, local_files_only=True)

    def test_short_slice_matches_official_processor_and_zero_padding(self):
        audio = np.linspace(-0.2, 0.7, 800, dtype=np.float32)
        segments = [{"text": "A", "start": 0.01, "end": 0.02}]
        normalizer = SegmentNormalizer(audio, segments, {"a": 1}, self.extractor)
        valid = audio[160:320]
        expected = self.extractor(valid, sampling_rate=16000, return_tensors="np")["input_values"][0]
        actual = normalizer.plans[0][1]
        np.testing.assert_array_equal(actual[:160], expected)
        np.testing.assert_array_equal(actual[160:], np.zeros(240, np.float32))
        self.assertEqual(normalizer.plans[0][0]["source_sample_start"], 160)
        self.assertEqual(normalizer.plans[0][0]["normalization_attention_length"], 160)

    def test_regular_slice_hook_identity_and_no_asr_mutation(self):
        audio = np.sin(np.arange(1600, dtype=np.float32) / 19) * .03 + .01
        original = audio.copy()
        normalizer = SegmentNormalizer(audio, [{"text": "A", "start": 0, "end": .1}], {"a": 1}, self.extractor)
        model = torch.nn.Identity()
        raw = torch.from_numpy(audio).unsqueeze(0)
        baseline = model(raw)
        with normalize_segments(model, normalizer):
            actual = model(raw)
        expected = self.extractor(audio, sampling_rate=16000, return_tensors="np")["input_values"]
        np.testing.assert_array_equal(actual.numpy(), expected)
        np.testing.assert_array_equal(audio, original)
        self.assertIs(model(raw), baseline)
        self.assertEqual(normalizer.records[0]["normalized_float32_sha256"], digest(actual.numpy()[0]))

    def test_silence_is_finite_and_mismatch_fails_restores_hook(self):
        audio = np.zeros(1600, np.float32)
        normalizer = SegmentNormalizer(audio, [{"text": "A", "start": 0, "end": .1}], {"a": 1}, self.extractor)
        self.assertTrue(np.isfinite(normalizer.plans[0][1]).all())
        model = torch.nn.Identity()
        with self.assertRaises(ValueError):
            with normalize_segments(model, normalizer):
                model(torch.ones(1, 1600))
        self.assertFalse(model._forward_pre_hooks)


if __name__ == "__main__":
    unittest.main()
