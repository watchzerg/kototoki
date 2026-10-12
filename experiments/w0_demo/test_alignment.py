"""Offline MMS contracts; no model load, GPU inference or asset acquisition."""
from __future__ import annotations

import unittest
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from unittest.mock import patch

from experiments.w0_demo.alignment import (
    MmsAligner, character_targets, clamp_window, map_records, mms_numeric_policy, normalize_window,
    sample_window,
)

try:
    import numpy as np
except ImportError:
    np = None


def token(position: int, start: int, end: int, *, known: bool = True) -> dict:
    return {"original_position": position, "start_frame": start, "end_frame": end,
            "token_probability": 0.8, "evidence_kind": "vocabulary_token" if known else "wildcard",
            "lexical_interval_accepted": known}


class TargetTests(unittest.TestCase):
    def test_repeats_keep_positions_and_unknown_characters_use_wildcard(self) -> None:
        targets = character_targets(" \t日日? A|\n", {"日": 1, "a": 2}, 3)
        self.assertEqual([row["original_position"] for row in targets], [2, 3, 4, 6])
        self.assertEqual([row["token_id"] for row in targets], [1, 1, 3, 2])
        self.assertEqual([row["lexical_interval_accepted"] for row in targets], [True, True, False, True])

    def test_known_internal_space_is_not_replaced_by_delimiter_for_japanese(self) -> None:
        targets = character_targets("a a", {"a": 1, " ": 2}, 3)
        self.assertEqual([row["token_id"] for row in targets], [1, 2, 1])
        self.assertEqual(character_targets(" \t\n", {" ": 2}, 3), [])

    def test_lowercase_expansion_has_no_fabricated_character_mapping(self) -> None:
        with self.assertRaisesRegex(ValueError, "token_character_count_mismatch"):
            character_targets("İ", {"i": 1}, 2)


class NumericPolicyTests(unittest.TestCase):
    def fake_torch(self, *, global_deterministic: bool) -> SimpleNamespace:
        cudnn = SimpleNamespace(enabled=False, benchmark=True, deterministic=True, allow_tf32=False)

        @contextmanager
        def flags(**requested):
            before = {name: getattr(cudnn, name) for name in requested}
            try:
                for name, value in requested.items():
                    setattr(cudnn, name, value)
                yield
            finally:
                for name, value in before.items():
                    setattr(cudnn, name, value)

        cudnn.flags = flags
        return SimpleNamespace(
            backends=SimpleNamespace(cuda=SimpleNamespace(matmul=SimpleNamespace(allow_tf32=True)), cudnn=cudnn),
            are_deterministic_algorithms_enabled=lambda: global_deterministic,
            get_float32_matmul_precision=lambda: "highest")

    def assert_restored(self, torch) -> None:
        self.assertTrue(torch.backends.cuda.matmul.allow_tf32)
        self.assertFalse(torch.backends.cudnn.enabled)
        self.assertTrue(torch.backends.cudnn.benchmark)
        self.assertTrue(torch.backends.cudnn.deterministic)
        self.assertFalse(torch.backends.cudnn.allow_tf32)

    def test_scoped_defaults_and_caller_deterministic_requirement_are_preserved(self) -> None:
        for deterministic in (False, True):
            torch = self.fake_torch(global_deterministic=deterministic)
            with mms_numeric_policy(torch) as actual:
                self.assertEqual(actual, {
                    "matmul_allow_tf32": False, "cudnn_allow_tf32": True, "cudnn_enabled": True,
                    "cudnn_benchmark": False, "cudnn_deterministic": False,
                    "deterministic_algorithms": deterministic, "float32_matmul_precision": "highest"})
            self.assert_restored(torch)
            self.assertEqual(torch.are_deterministic_algorithms_enabled(), deterministic)

    def test_forward_failure_restores_every_changed_flag(self) -> None:
        torch = self.fake_torch(global_deterministic=True)
        with self.assertRaisesRegex(RuntimeError, "synthetic forward failure"):
            with mms_numeric_policy(torch) as actual:
                self.assertTrue(actual["cudnn_allow_tf32"])
                raise RuntimeError("synthetic forward failure")
        self.assert_restored(torch)
        self.assertTrue(torch.are_deterministic_algorithms_enabled())


class MappingTests(unittest.TestCase):
    def test_repeats_oov_spaces_and_offset_preserve_every_character(self) -> None:
        segments = [{"text": " 日日? ", "start": 1.12345, "end": 2.12345},
                    {"text": "日", "start": 3, "end": 4}]
        records = [{"segment_index": 0, "frame_count": 10, "failure": None,
                    "tokens": [token(1, 0, 2), token(2, 3, 6), token(3, 7, 8, known=False)]}]
        result = map_records(segments, records, 100.0004)
        self.assertEqual(result["text"], " 日日? 日")
        self.assertEqual([unit["char_start"] for unit in result["units"]], list(range(6)))
        self.assertEqual([unit["status"] for unit in result["units"]],
                         ["text_only", "ok", "ok", "text_only", "text_only", "text_only"])
        first = result["units"][1]
        self.assertEqual(first["start"], round(1.12345, 3) + 100.0004)
        self.assertEqual(first["end"], round(1.32345, 3) + 100.0004)
        self.assertEqual(result["derived_segments"][0]["chars"][1]["start"], round(1.12345, 3))
        self.assertTrue(all(unit["granularity"] == "character" and unit["time_source"] == "api"
                            and unit["time_semantics"] == "ctc_nonblank_token_span"
                            for unit in result["units"]))

    def test_invalid_frame_and_failed_path_never_generate_times(self) -> None:
        segments = [{"text": "日日日", "start": 0, "end": 1},
                    {"text": "日", "start": 1, "end": 2}]
        records = [{"segment_index": 0, "frame_count": 10,
                    "tokens": [token(0, -1, 1), token(1, 2, 2), token(2, 9, 11)]},
                   {"segment_index": 1, "frame_count": 10, "failure": "CUDA failure",
                    "tokens": [token(0, 0, 1)]}]
        result = map_records(segments, records)
        self.assertEqual(len(result["units"]), 4)
        self.assertTrue(all(unit["status"] == "text_only" and unit["start"] is None for unit in result["units"]))

    def test_window_duration_not_padded_audio_duration_maps_frames(self) -> None:
        # A <400-sample window still maps the one padded emission frame over
        # its original duration, not the 25 ms padded input length.
        segments = [{"text": "日", "start": 0.1, "end": 0.11}]
        records = [{"segment_index": 0, "frame_count": 1, "tokens": [token(0, 0, 1)],
                    "normalization": {"valid_samples": 160, "padded_samples": 400}}]
        unit = map_records(segments, records)["units"][0]
        self.assertEqual((unit["start"], unit["end"]), (0.1, 0.11))

    def test_rounding_can_equal_endpoints_as_in_historical_mapping(self) -> None:
        segments = [{"text": "日", "start": 0, "end": 0.0001}]
        records = [{"segment_index": 0, "frame_count": 1, "tokens": [token(0, 0, 1)]}]
        unit = map_records(segments, records)["units"][0]
        self.assertEqual((unit["start"], unit["end"], unit["status"]), (0.0, 0.0, "ok"))

    def test_empty_results_and_zero_frames(self) -> None:
        self.assertEqual(map_records([], []), {"text": "", "units": [], "records": [], "derived_segments": []})
        result = map_records([{"text": "日", "start": 0, "end": 0}],
                             [{"segment_index": 0, "frame_count": 0, "tokens": [token(0, 0, 1)]}])
        self.assertEqual(result["units"][0]["status"], "text_only")

    def test_clamp_source_bounds_and_invalid_windows(self) -> None:
        self.assertEqual(clamp_window(-2, 4, 2), (0, 2))
        self.assertEqual(clamp_window(4, 5, 2), (2, 2))
        self.assertEqual(clamp_window(-4, -2, 2), (0, 0))
        for values in [(1, 0, 2), (0, float("nan"), 2), (0, 1, -2)]:
            with self.assertRaises(ValueError):
                clamp_window(*values)


class FakeAligner(MmsAligner):
    def __init__(self) -> None:
        self.model = object()
        self.processor = None
        self.blank_id = 0
        self.dictionary = {"日": 1}
        self.metadata = {"fake": True}

    def _align_segment(self, audio, start, end, text, record):
        targets = character_targets(text, self.dictionary, 2)
        if not targets:
            record["skip_reason"] = "no_eligible_characters"
            return
        if text == "失敗":
            raise RuntimeError("synthetic CUDA failure")
        first = record.get("window_start_sample", int(start * 16000))
        last = record.get("window_end_sample", int(end * 16000))
        if not len(audio[first:last]):
            raise ValueError("Empty alignment waveform")
        record["frame_count"] = 10
        record["tokens"] = [{**row, **token(row["original_position"], index * 2, index * 2 + 1,
                                           known=row["lexical_interval_accepted"])}
                            for index, row in enumerate(targets)]


class SampleWindowTests(unittest.TestCase):
    def segment(self, start: int = 0, end: int = 1001) -> dict:
        return {"text": "日", "start": start / 16000, "end": end / 16000,
                "start_sample": start, "end_sample": end}

    def test_exact_odd_length_and_nonzero_offset_accept_float_roundtrip_loss(self) -> None:
        self.assertEqual(int((1001 / 16000) * 16000), 1000)
        self.assertEqual(sample_window(self.segment(), 1001), (0, 1001))
        self.assertEqual(sample_window(self.segment(480000, 481001), 481001), (480000, 481001))
        near = self.segment()
        near["end"] += 1e-12
        self.assertEqual(sample_window(near, 1001), (0, 1001))
        self.assertIsNone(sample_window({"start": -10, "end": 100}, 1001))

    def test_invalid_or_incomplete_sample_bounds_are_rejected(self) -> None:
        for updates in ({"start_sample": True}, {"end_sample": False}, {"end_sample": 1001.0},
                        {"start_sample": -1}, {"end_sample": 1002}, {"end_sample": 0},
                        {"end_sample": 10 ** 1000}, {"start_sample": None}):
            with self.subTest(updates=updates):
                with self.assertRaisesRegex(ValueError, "integer"):
                    sample_window({**self.segment(), **updates}, 1001)
        for missing in ("start_sample", "end_sample"):
            segment = self.segment()
            del segment[missing]
            with self.assertRaisesRegex(ValueError, "integer"):
                sample_window(segment, 1001)

    def test_seconds_must_be_finite_and_match_samples(self) -> None:
        for updates in ({"start": 0.1}, {"end": 1000 / 16000}, {"end": float("inf")},
                        {"start": float("nan")}, {"end": True}, {"end": 10 ** 1000},
                        {"end": "0.0625625"}):
            with self.subTest(updates=updates):
                with self.assertRaisesRegex(ValueError, "seconds must match"):
                    sample_window({**self.segment(), **updates}, 1001)


@unittest.skipIf(np is None, "NumPy is optional in the lightweight root environment")
class NormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            from transformers import Wav2Vec2FeatureExtractor
        except ImportError:
            self.skipTest("Transformers feature extractor requires the isolated backend environment")
        self.extractor = Wav2Vec2FeatureExtractor(
            feature_size=1, sampling_rate=16000, padding_value=0, do_normalize=True,
            return_attention_mask=True)

    def test_valid_samples_define_statistics_and_right_padding_stays_zero(self) -> None:
        for samples in (160, 400, 801):
            waveform = np.linspace(0.2, 0.9, samples, dtype=np.float32)
            before = waveform.copy()
            normalized, record = normalize_window(waveform, self.extractor)
            expected = (waveform - waveform.mean()) / np.sqrt(waveform.var() + 1e-7)
            np.testing.assert_allclose(normalized[:samples], expected, rtol=1e-6, atol=1e-6)
            np.testing.assert_array_equal(normalized[samples:], 0)
            np.testing.assert_array_equal(waveform, before)
            self.assertEqual(record["valid_samples"], samples)
            self.assertEqual(record["padded_samples"], max(samples, 400))
            self.assertFalse(record["model_attention_mask"])

    def test_empty_window_is_an_explicit_failure(self) -> None:
        with self.assertRaisesRegex(ValueError, "Empty alignment waveform"):
            normalize_window(np.zeros(0, dtype=np.float32), self.extractor)


@unittest.skipIf(np is None, "NumPy is optional in the lightweight root environment")
class PublicContractTests(unittest.TestCase):
    def test_explicit_sample_windows_map_canonical_seconds_and_keep_original_input(self) -> None:
        segment = SampleWindowTests().segment(480000, 481001)
        segment["end"] += 1e-12
        original = dict(segment)
        result = FakeAligner().align(np.zeros(481001, dtype=np.float32), [segment], 12.0004)
        record = result["records"][0]
        self.assertEqual((record["window_start_sample"], record["window_end_sample"]), (480000, 481001))
        self.assertEqual((record["window_start"], record["window_end"]), (30, 481001 / 16000))
        unit = result["units"][0]
        self.assertEqual((unit["start"], unit["end"]), (42.0004, round(30 + (1001 / 16000) / 10, 3) + 12.0004))
        self.assertEqual(segment, original)

    def test_real_preprocessing_uses_exact_samples_and_failure_retains_all_text(self) -> None:
        # Exercise the shared _align_segment through normalization and model
        # invocation using a fake CUDA boundary; no Torch/GPU model executes.
        received = []

        def extract(waveform, **options):
            received.append(waveform.copy())
            length = options["max_length"]
            normalized = (waveform - waveform.mean()) / np.sqrt(waveform.var() + 1e-7)
            return {"input_values": np.pad(normalized, (0, length - len(waveform)))[None],
                    "attention_mask": np.pad(np.ones(len(waveform)), (0, length - len(waveform)))[None]}

        class Tensor:
            device = "cuda:0"
            dtype = "torch.float32"

            def unsqueeze(self, axis):
                return self

            def to(self, device):
                return self

        class Model:
            def eval(self):
                return self

            def __call__(self, tensor):
                raise RuntimeError("synthetic forward failure")

        class ForwardFailureAligner(MmsAligner):
            def __init__(self):
                self.model = Model()
                self.processor = SimpleNamespace(feature_extractor=extract)
                self.dictionary = {"日": 1}
                self.blank_id = 0
                self.device = "cuda:0"

        torch = NumericPolicyTests().fake_torch(global_deterministic=False)
        torch.from_numpy = lambda values: Tensor()
        torch.inference_mode = nullcontext
        functional = SimpleNamespace(forced_align=None, merge_tokens=None)
        audio = np.linspace(-0.5, 0.5, 481001, dtype=np.float32)
        segments = [SampleWindowTests().segment(), SampleWindowTests().segment(480000, 481001),
                    {"text": "日", "start": 0, "end": 1001 / 16000}]
        with patch.dict("sys.modules", {"torch": torch, "torchaudio.functional": functional}):
            result = ForwardFailureAligner().align(audio, segments)
        self.assertEqual(result["text"], "日日日")
        self.assertTrue(all(unit["status"] == "text_only" for unit in result["units"]))
        for index, (first, last) in enumerate(((0, 1001), (480000, 481001), (0, 1000))):
            np.testing.assert_array_equal(received[index], audio[first:last])
            record = result["records"][index]
            normalization = record["normalization"]
            self.assertEqual(normalization["valid_samples"], last - first)
            self.assertEqual(normalization["normalization_attention_length"], last - first)
            self.assertEqual((normalization["source_sample_start"], normalization["source_sample_end"]),
                             (first, last))
            self.assertEqual(record["failure"], "RuntimeError: synthetic forward failure")
            self.assertEqual(record["tokens"], [])
        self.assertNotIn("window_start_sample", result["records"][2])
        self.assertEqual(result["records"][2]["window_end"], 1001 / 16000)

    def test_invalid_explicit_bounds_fail_before_model_invocation(self) -> None:
        for updates in ({"start_sample": True}, {"end_sample": 1002}, {"end": 0.1}):
            with self.subTest(updates=updates):
                with self.assertRaises(ValueError):
                    FakeAligner().align(np.zeros(1001, dtype=np.float32),
                                        [{**SampleWindowTests().segment(), **updates}])

    def test_failures_are_recorded_without_dropping_text_or_later_segments(self) -> None:
        aligner = FakeAligner()
        segments = [{"text": "失敗", "start": 0, "end": 0.5},
                    {"text": "日日? ", "start": 0.5, "end": 2}]
        result = aligner.align(np.zeros(16000, dtype=np.float32), segments, 12)
        self.assertEqual(result["text"], "失敗日日? ")
        self.assertEqual(result["records"][0]["failure"], "RuntimeError: synthetic CUDA failure")
        self.assertEqual(result["records"][1]["window_end"], 1)
        self.assertEqual([unit["status"] for unit in result["units"]],
                         ["text_only", "text_only", "ok", "ok", "text_only", "text_only"])
        self.assertEqual(segments[1]["end"], 2)
        aligner.close()
        aligner.close()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            aligner.align(np.zeros(16000, dtype=np.float32), [])

    def test_empty_audio_no_text_and_out_of_bounds_keep_separate_records(self) -> None:
        segments = [{"text": "", "start": 0, "end": 0}, {"text": "日", "start": 1, "end": 2}]
        result = FakeAligner().align(np.zeros(0, dtype=np.float32), segments)
        self.assertEqual(result["text"], "日")
        self.assertEqual(result["records"][0]["skip_reason"], "no_eligible_characters")
        self.assertIn("Empty alignment waveform", result["records"][1]["failure"])
        self.assertEqual(result["units"][0]["status"], "text_only")

    def test_input_representation_and_finite_values_are_required(self) -> None:
        aligner = FakeAligner()
        for audio in [np.zeros(10, dtype=np.float64), np.zeros((1, 10), dtype=np.float32),
                      np.array([float("nan")], dtype=np.float32), [0.0]]:
            with self.assertRaises(ValueError):
                aligner.align(audio, [])
        for offset in [-1, float("inf")]:
            with self.assertRaises(ValueError):
                aligner.align(np.zeros(10, dtype=np.float32), [], offset)


if __name__ == "__main__":
    unittest.main()
