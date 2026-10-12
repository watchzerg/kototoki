"""Offline W0 boundary tests: no weights, downloads, or GPU execution."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from experiments.w0_demo import asr, vad


class Array:
    """Only the crop and trace behavior is faked; neural math is not asserted."""

    def __init__(self, size: int) -> None:
        self.size = size

    def __len__(self) -> int:
        return self.size

    def __getitem__(self, key):
        if isinstance(key, slice):
            return Array(key.stop - key.start)
        return self

    def tobytes(self) -> bytes:
        return str(self.size).encode("ascii")


class BoundaryTests(unittest.TestCase):
    def test_import_has_no_optional_dependencies(self):
        root = Path(__file__).resolve().parents[2]
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "import experiments.w0_demo.asr, experiments.w0_demo.vad; "
            "assert not any(x in sys.modules for x in "
            "('numpy', 'torch', 'faster_whisper', 'pyannote', 'whisperx'))"
        )
        run = subprocess.run([sys.executable, "-I", "-c", code, str(root)],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_missing_assets_fail_before_optional_imports(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with self.assertRaises(FileNotFoundError):
                asr.WhisperAsr(directory / "missing", directory / "mel.npz")
            with self.assertRaises(FileNotFoundError):
                vad.PyannoteVad(directory / "missing.bin")

    def test_unpinned_assets_fail_before_optional_imports(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            asset = directory / "untrusted.bin"
            asset.write_bytes(b"synthetic wrong asset")
            with self.assertRaisesRegex(ValueError, "checkpoint differs"):
                vad.PyannoteVad(asset)
            with self.assertRaisesRegex(ValueError, "Mel asset differs"):
                asr.WhisperAsr(directory, asset)

    def test_raw_windows_not_rounded_and_replay_is_owned(self):
        chunks = [{"start": .123456, "end": 1.789123,
                   "segments": [[.123456, .9], [1.1, 1.789123]]}]
        frozen = vad.FrozenVad(chunks)
        chunks[0]["start"] = 0
        with patch.object(vad, "validate_audio"):
            first = frozen.segment(Array(32000))
            first[0]["segments"].clear()
            second = frozen.segment(Array(32000))
        self.assertEqual(second[0]["start"], .123456)
        self.assertEqual(len(second[0]["segments"]), 2)
        self.assertFalse(frozen.metadata["fresh_inference"])

    def test_window_bounds_and_crop_limits(self):
        bad = [
            [{"start": -1, "end": 1}],
            [{"start": 1, "end": 1}],
            [{"start": 0, "end": float("nan")}],
            [{"start": 0, "end": float("inf")}],
            [{"start": 0, "end": 2}],
            [{"start": 0, "end": .000001}],
            [{"start": 0, "end": 1}, {"start": .5, "end": 1}],
            [{"start": 0, "end": 1, "segments": [(.1, 1.1)]}],
        ]
        for windows in bad:
            with self.subTest(windows=windows), self.assertRaises(ValueError):
                vad.validate_chunks(windows, 16000)
        with self.assertRaises(ValueError):
            vad.validate_chunks([{"start": 0, "end": 30.001}], 500000)
        self.assertEqual(vad.validate_chunks([], 0), [])
        self.assertEqual(vad.validate_chunks([{"start": 0, "end": 30}], 480000)[0]["end"], 30)

    def test_transcribe_preserves_raw_crop_rounded_result_and_reuses_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            asset = directory / "mel.npz"
            asset.write_bytes(b"fake; loader mocked")
            with patch.object(asr.WhisperAsr, "_load") as load:
                engine = asr.WhisperAsr(directory, asset)
                engine._model, engine._filters = object(), object()
                generation = {"text": "日本語", "avg_logprob": -.25,
                              "tokens": [1, 2], "prompt": [3], "kwargs": {"beam_size": 5}}
                windows = [{"start": .123456, "end": 1.789123}]
                with patch.object(asr, "validate_audio"), \
                     patch.object(asr, "features", side_effect=lambda audio, _: audio) as features, \
                     patch.object(asr, "generate", return_value=generation):
                    segments, traces = engine.transcribe(Array(32000), windows)
                    again = engine.transcribe(Array(32000), windows)
                load.assert_called_once()
                self.assertEqual(segments, again[0])
                self.assertEqual(segments[0]["start"], .123)
                self.assertEqual(segments[0]["end"], 1.789)
                self.assertEqual(traces[0]["start_sample"], int(.123456 * 16000))
                self.assertEqual(traces[0]["end_sample"], int(1.789123 * 16000))
                count = int(1.789123 * 16000) - int(.123456 * 16000)
                self.assertEqual(len(features.call_args.args[0]), count)
                self.assertEqual(traces[0]["feature_sha256"], hashlib.sha256(str(count).encode()).hexdigest())

    def test_closed_and_empty_asr_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            asset = directory / "mel.npz"
            asset.write_bytes(b"fake")
            with patch.object(asr.WhisperAsr, "_load"):
                engine = asr.WhisperAsr(directory, asset)
            with patch.object(asr, "validate_audio"):
                self.assertEqual(engine.transcribe(Array(0), []), ([], []))
            model = SimpleNamespace(model=SimpleNamespace(unload_model=lambda: None))
            engine._model = model
            engine.close()
            engine.close()
            self.assertIsNone(engine._model)
            with self.assertRaisesRegex(RuntimeError, "closed"):
                engine.transcribe(Array(1), [])

    def test_exact_sample_windows_reach_asr_and_mms_without_rounding(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            asset = directory / "mel.npz"
            asset.write_bytes(b"fake")
            with patch.object(asr.WhisperAsr, "_load"):
                engine = asr.WhisperAsr(directory, asset)
                engine._model, engine._filters = object(), object()
            generation = {"text": "あ", "avg_logprob": -.25,
                          "tokens": [1], "prompt": [3], "kwargs": {}}
            windows = [{"start": 1001 / 16000, "end": 2002 / 16000,
                        "start_sample": 1001, "end_sample": 2002}]
            with patch.object(asr, "validate_audio"), \
                 patch.object(asr, "features", side_effect=lambda audio, _: audio) as features, \
                 patch.object(asr, "generate", return_value=generation):
                segments, traces = engine.transcribe(Array(32000), windows)
            self.assertEqual(len(features.call_args.args[0]), 1001)
            self.assertEqual((traces[0]["start_sample"], traces[0]["end_sample"]), (1001, 2002))
            self.assertEqual((segments[0]["start_sample"], segments[0]["end_sample"]), (1001, 2002))
            self.assertEqual((segments[0]["start"], segments[0]["end"]),
                             (1001 / 16000, 2002 / 16000))
            with patch.object(asr, "validate_audio"), patch.object(asr, "features") as features:
                with self.assertRaises(ValueError):
                    engine.transcribe(Array(32000), [{**windows[0], "end_sample": 2001}])
                features.assert_not_called()

    def test_generation_uses_fixed_prompt_and_effective_whitelist(self):
        calls = []

        class Tokenizer:
            eot = 100

            def __init__(self, hf, multilingual, **kwargs):
                calls.append(("tokenizer", kwargs))
                self.tokenizer = SimpleNamespace(decode_batch=lambda tokens: [str(tokens[0])])

            def encode(self, text):
                return [len(text)]

        class Model:
            hf_tokenizer = object()
            max_length = 448
            model = SimpleNamespace(is_multilingual=True)

            def get_prompt(self, tokenizer, previous, **kwargs):
                calls.append(("prompt", previous, kwargs))
                return [50258, 50266, 50360, 50364]

            def encode(self, mel):
                return "encoded"

        model = Model()

        def generate(encoded, prompts, **kwargs):
            calls.append(("generate", encoded, prompts, kwargs))
            return [SimpleNamespace(sequences_ids=[[1, 101, 2]], scores=[-.5])]

        model.model.generate = generate
        options = {"beam_size": 5, "patience": 1, "length_penalty": 1,
                   "suppress_blank": True, "suppress_tokens": [-1], "no_repeat_ngram_size": 0,
                   "repetition_penalty": 1, "initial_prompt": None, "without_timestamps": True,
                   "prefix": None, "hotwords": None, "temperature": .8}
        with patch.dict(sys.modules, {"numpy": SimpleNamespace(newaxis=None),
                                     "faster_whisper.tokenizer": SimpleNamespace(Tokenizer=Tokenizer)}):
            first = asr.generate(model, Array(1), options)
            second = asr.generate(model, Array(1), options)
        self.assertEqual(first, second)
        self.assertEqual(first["text"], "[1, 2]")
        self.assertEqual(first["tokens"], [1, 101, 2])
        self.assertEqual(first["avg_logprob"], -.375)
        self.assertEqual(first["kwargs"]["suppress_tokens"], [-1])
        self.assertNotIn("temperature", first["kwargs"])
        self.assertNotIn("return_no_speech_prob", first["kwargs"])
        self.assertEqual(calls[1][1], [])
        self.assertEqual(calls[4][1], [])


@unittest.skipUnless(importlib.util.find_spec("numpy") and importlib.util.find_spec("pyannote"),
                     "Optional numerical/Pyannote dependencies unavailable")
class NumericalTests(unittest.TestCase):
    def test_audio_dtype_shape_and_finite_samples(self):
        import numpy as np

        for audio in (np.zeros((1, 10), np.float32), np.zeros(10, np.float64),
                      np.array([np.nan], np.float32), [0.0]):
            with self.subTest(audio_type=type(audio).__name__), self.assertRaises(ValueError):
                vad.validate_audio(audio)
        vad.validate_audio(np.zeros(0, np.float32))
        self.assertEqual(vad.FrozenVad([]).segment(np.zeros(0, np.float32)), [])

    def test_cut_merge_matches_historical_replica_46_cases(self):
        import json
        import numpy as np
        from pyannote.core import SlidingWindow, SlidingWindowFeature
        from experiments.framework_equivalence.vad import merge_scores as reference

        root = Path(__file__).resolve().parents[2]
        saved = root / ".local/framework-equivalence/v1/wx.json"
        cases = []
        if saved.is_file():
            for row in json.loads(saved.read_text(encoding="utf-8"))["results"]:
                cases.append(SlidingWindowFeature(
                    np.load(saved.parent / (row["clip"]["id"] + "-vad.npy")),
                    SlidingWindow(**row["scores_window"])))
        window = SlidingWindow(start=0, duration=.02, step=.01)
        cases.extend(SlidingWindowFeature(data, window) for data in (
            np.zeros((100, 1)), np.full((7500, 1), .8),
            np.array([[.5], [.501], [.363], [.362], [.5], [.501], [.4], [.3]]),
            np.array([[0], [.8], [0], [.8], [0]], dtype=float)))
        rng = np.random.default_rng(20261004)
        for _ in range(40):
            cases.append(SlidingWindowFeature(rng.random((rng.integers(1, 8500), rng.integers(1, 4))),
                                              SlidingWindow(start=-.003, duration=.02, step=.01)))
        for index, scores in enumerate(cases):
            with self.subTest(case=index):
                self.assertEqual(vad.merge_scores(scores), reference(scores))
        self.assertEqual(vad.merge_scores(SlidingWindowFeature(np.zeros((0, 1)), window)), [])

    def test_exact_features_equal_historical_adapter(self):
        import numpy as np
        import torch
        from experiments.framework_equivalence.adapter import features as reference

        root = Path(__file__).resolve().parents[2]
        asset = root / ".local/framework-equivalence/v1/mel_filters.npz"
        if not asset.is_file():
            self.skipTest("Frozen measured Mel asset unavailable")
        with np.load(asset) as archive:
            bank = torch.from_numpy(archive["mel_128"].copy())
        for length in (16000, 480000):
            audio = np.sin(np.arange(length, dtype=np.float32) / 50) * np.float32(.1)
            self.assertEqual(asr.features(audio, bank).tobytes(), reference(audio, bank).tobytes())


if __name__ == "__main__":
    unittest.main()
