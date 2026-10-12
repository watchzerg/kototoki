"""Offline source-span and VAD adapter contract tests, without model assets."""
from __future__ import annotations

import hashlib
import random
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from experiments.w0_demo import vad_candidates as candidates


class Waveform:
    def __init__(self, samples: int):
        self.samples = samples

    def __len__(self):
        return self.samples

    def tobytes(self):
        return b"synthetic-pcm"


class ChunkTests(unittest.TestCase):
    def test_internal_silence_and_source_positions_are_retained(self):
        chunks, metadata = candidates.chunk_intervals([[1, 3], [12, 14], [40, 42]], 50 * 16000)
        self.assertEqual([(row["start"], row["end"]) for row in chunks], [(1, 14), (40, 42)])
        self.assertEqual(chunks[0]["segments"], [[1, 3], [12, 14]])
        accounting = metadata["accounting"]
        self.assertEqual(accounting["speech_samples"], 6 * 16000)
        self.assertEqual(accounting["chunk_samples"], 15 * 16000)
        self.assertEqual(accounting["internal_silence_samples"], 9 * 16000)
        self.assertEqual(accounting["skipped_source_samples"], 35 * 16000)

    def test_silence_longer_than_source_span_limit_is_not_concatenated(self):
        chunks, _ = candidates.chunk_intervals([[0, 1], [30, 31]], 32 * 16000)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[1]["start_sample"], 30 * 16000)

    def test_exact_30_second_span_merges(self):
        chunks, metadata = candidates.chunk_intervals([[1, 2], [30, 31]], 32 * 16000)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["end_sample"] - chunks[0]["start_sample"], 480000)
        self.assertEqual(metadata["accounting"]["hard_split_count"], 0)

    def test_long_continuous_speech_has_explicit_bounded_splits(self):
        chunks, metadata = candidates.chunk_intervals([[1, 71]], 80 * 16000)
        self.assertEqual([(row["start"], row["end"]) for row in chunks], [(1, 31), (31, 61), (61, 71)])
        self.assertEqual(metadata["accounting"]["hard_split_count"], 2)
        self.assertEqual(metadata["accounting"]["speech_samples"], 70 * 16000)
        self.assertEqual(metadata["accounting"]["internal_silence_samples"], 0)

    def test_native_overlaps_and_order_are_normalized_without_duplicate_samples(self):
        chunks, metadata = candidates.chunk_intervals([[3, 5], [1, 4], [5, 6]], 10 * 16000)
        self.assertEqual(chunks[0]["segments"], [[1, 6]])
        self.assertEqual(metadata["accounting"]["raw_interval_count"], 3)
        self.assertEqual(metadata["accounting"]["speech_interval_count"], 1)
        self.assertEqual(metadata["raw_intervals"][0]["start"], 3)

    def test_padded_tail_and_negative_origin_are_clipped_and_counted(self):
        chunks, metadata = candidates.chunk_intervals([[-.1, .2], [.8, 1.1], [1.2, 1.3]], 16000)
        self.assertEqual((chunks[0]["start"], chunks[0]["end"]), (0, 1))
        self.assertEqual(metadata["accounting"]["clipped_interval_count"], 3)
        self.assertEqual(metadata["accounting"]["dropped_interval_count"], 1)
        self.assertEqual(metadata["raw_intervals"][0]["start"], -.1)

    def test_native_units_map_to_same_source_samples(self):
        by_samples = candidates.chunk_intervals([[1600, 7200]], 16000, unit="samples")
        by_ms = candidates.chunk_intervals([[100, 450]], 16000, unit="milliseconds")
        by_s = candidates.chunk_intervals([[.1, .45]], 16000)
        self.assertEqual(by_samples[0], by_ms[0])
        self.assertEqual(by_samples[0], by_s[0])

    def test_subsample_conversion_conservatively_retains_source(self):
        chunks, metadata = candidates.chunk_intervals([[.00001, .00007]], 10)
        self.assertEqual(chunks[0]["start_sample"], 0)
        self.assertEqual(chunks[0]["end_sample"], 2)
        self.assertEqual(metadata["accounting"]["speech_samples"], 2)

    def test_integer_coordinates_survive_legacy_float_crop(self):
        chunks, _ = candidates.chunk_intervals([[1001, 481001]], 600000, unit="samples")
        self.assertEqual(int(chunks[0]["start"] * 16000), 1001)
        self.assertEqual(int(chunks[0]["end"] * 16000), 481001)

    def test_one_sample_tail_keeps_source_duration(self):
        chunks, _ = candidates.chunk_intervals([[1000, 1001]], 1001, unit="samples")
        self.assertEqual(chunks[0]["end"], 1001 / 16000)
        self.assertEqual(chunks[0]["end_sample"], 1001)

    def test_empty_and_silent_inputs_are_accounted(self):
        for samples in (0, 16000):
            chunks, metadata = candidates.chunk_intervals([], samples)
            self.assertEqual(chunks, [])
            self.assertEqual(metadata["accounting"]["skipped_source_samples"], samples)
        chunks, metadata = candidates.chunk_intervals([[0, 1]], 0)
        self.assertEqual(chunks, [])
        self.assertEqual(metadata["accounting"]["dropped_interval_count"], 1)

    def test_invalid_intervals_fail_instead_of_disappearing(self):
        invalid = [[[1, 1]], [[2, 1]], [[0, float("nan")]], [[0, float("inf")]],
                   [[True, 1]], [["0", 1]], [[0]], [{"start": 0, "end": 1}]]
        for intervals in invalid:
            with self.subTest(intervals=intervals), self.assertRaises(ValueError):
                candidates.chunk_intervals(intervals, 16000)
        with self.assertRaises(ValueError):
            candidates.chunk_intervals([[0, .5]], 16000, unit="samples")
        with self.assertRaises(ValueError):
            candidates.chunk_intervals([], 16000, unit="minutes")
        for samples in (-1, 1.5, True):
            with self.subTest(samples=samples), self.assertRaises(ValueError):
                candidates.chunk_intervals([], samples)

    def test_randomized_union_preserves_all_detected_samples_and_accounting(self):
        rng = random.Random(20261005)
        for _ in range(200):
            samples = rng.randint(1, 4000)
            intervals = []
            speech = set()
            for _ in range(rng.randint(0, 12)):
                start = rng.randint(0, samples - 1)
                end = rng.randint(start + 1, samples)
                intervals.append([start, end])
                speech.update(range(start, end))
            chunks, metadata = candidates.chunk_intervals(intervals, samples, unit="samples")
            processed = set()
            reconstructed = set()
            for chunk in chunks:
                span = set(range(chunk["start_sample"], chunk["end_sample"]))
                self.assertFalse(processed & span)
                self.assertLessEqual(len(span), 480000)
                processed.update(span)
            for interval in metadata["speech_intervals"]:
                reconstructed.update(range(interval["start_sample"], interval["end_sample"]))
            self.assertEqual(speech, reconstructed)
            self.assertTrue(speech <= processed)
            self.assertEqual(metadata["accounting"]["speech_samples"], len(speech))
            self.assertEqual(metadata["accounting"]["chunk_samples"], len(processed))


class AdapterTests(unittest.TestCase):
    def test_import_does_not_load_optional_libraries(self):
        root = Path(__file__).resolve().parents[2]
        code = ("import sys; sys.path.insert(0,sys.argv[1]); "
                "import experiments.w0_demo.vad_candidates; "
                "assert not any(name in sys.modules for name in "
                "('numpy','torch','silero_vad','funasr','fireredvad','pyannote','whisperx'))")
        run = subprocess.run([sys.executable, "-I", "-c", code, str(root)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_missing_assets_fail_before_optional_imports(self):
        with tempfile.TemporaryDirectory() as temporary:
            for name in candidates.PACKAGE_PINS:
                with self.subTest(name=name), self.assertRaises(FileNotFoundError):
                    candidates.create_vad(name, Path(temporary) / "missing")

    def test_required_directory_files_cannot_be_silently_omitted(self):
        with tempfile.TemporaryDirectory() as temporary:
            for adapter in (candidates.FsmnVad, candidates.FireRedVad):
                with self.subTest(adapter=adapter), self.assertRaises(FileNotFoundError):
                    adapter(Path(temporary))

    def test_unknown_candidate_and_automatic_device_are_rejected(self):
        with self.assertRaises(ValueError):
            candidates.create_vad("old-pyannote", Path("missing"))
        with self.assertRaises(ValueError):
            candidates.create_vad("silero", Path("missing"), device="auto")

    def test_wrong_package_version_requires_isolated_pin(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "silero_vad.jit"
            checkpoint.write_bytes(b"synthetic")
            with patch.object(candidates.importlib.metadata, "version", return_value="0.0.0"), \
                 self.assertRaisesRegex(RuntimeError, "silero-vad==6.2.3"):
                candidates.SileroVad(checkpoint)

    def test_fake_detection_metadata_resource_release_and_reuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "silero_vad.jit"
            checkpoint.write_bytes(b"synthetic")
            with patch.object(candidates.importlib.metadata, "version", return_value="6.2.3"), \
                 patch.object(candidates.SileroVad, "_load") as load:
                adapter = candidates.SileroVad(checkpoint)
            self.assertEqual(adapter.metadata["model_files_sha256"]["silero_vad.jit"],
                             hashlib.sha256(b"synthetic").hexdigest())
            with patch.object(candidates, "validate_audio"), \
                 patch.object(adapter, "_intervals", return_value=([[100, 500]], "samples")) as detect:
                first = adapter.segment(Waveform(1000))
                again = adapter.segment(Waveform(1000))
                self.assertEqual(first, again)
                self.assertEqual(adapter.segment(Waveform(0)), [])
            load.assert_called_once()
            self.assertEqual(detect.call_count, 2)
            self.assertEqual(adapter.metadata["input_pcm_sha256"], hashlib.sha256(b"synthetic-pcm").hexdigest())
            adapter._engine = adapter._model = object()
            adapter.close()
            adapter.close()
            self.assertIsNone(adapter._engine)
            self.assertIsNone(adapter._model)
            with self.assertRaisesRegex(RuntimeError, "closed"):
                adapter.segment(Waveform(1))

    def test_actual_device_must_match_request(self):
        adapter = object.__new__(candidates.SileroVad)
        adapter.device, adapter.metadata = "cpu", {}
        parameter = SimpleNamespace(device="cuda:0", dtype="torch.float32")
        with self.assertRaisesRegex(RuntimeError, "fallback"):
            adapter._record_device(SimpleNamespace(parameters=lambda: iter([parameter])))
        parameter.device = "cpu"
        adapter._record_device(SimpleNamespace(parameters=lambda: iter([parameter])))
        self.assertEqual(adapter.metadata["device"], "cpu")


if __name__ == "__main__":
    unittest.main()
