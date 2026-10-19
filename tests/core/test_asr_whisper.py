"""`kototoki.asr_whisper`：导入顺序（torch 先于 ctranslate2／faster_whisper）与逐窗失败记账。

用伪模块代替 torch／ctranslate2／faster_whisper：导入时记录次序，不加载真实库与 GPU。
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import sys
import math
import types
import unittest
from unittest import mock

import numpy as np

FAKE = ("torch", "ctranslate2", "faster_whisper", "faster_whisper.tokenizer")
TARGET = "kototoki.asr_whisper"


class _RecordingFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """把 FAKE 中的模块换成伪模块，记录其被导入的先后次序。"""

    def __init__(self) -> None:
        self.order: list[str] = []

    def find_spec(self, name, path, target=None):
        if name in FAKE:
            return importlib.util.spec_from_loader(name, self, is_package=name == "faster_whisper")
        return None

    def create_module(self, spec):
        module = types.ModuleType(spec.name)

        def attribute(name: str):
            if name.startswith("__"):
                raise AttributeError(name)
            return mock.MagicMock(name=f"{spec.name}.{name}")
        module.__getattr__ = attribute
        return module

    def exec_module(self, module) -> None:
        self.order.append(module.__name__)


def import_with_fakes() -> tuple[types.ModuleType, list[str]]:
    """在伪模块下全新导入 `kototoki.asr_whisper`，之后恢复 `sys.modules` 与 `sys.meta_path`。"""
    saved = {name: sys.modules.pop(name) for name in (*FAKE, TARGET) if name in sys.modules}
    finder = _RecordingFinder()
    sys.meta_path.insert(0, finder)
    try:
        module = importlib.import_module(TARGET)
    finally:
        sys.meta_path.remove(finder)
        for name in (*FAKE, TARGET):
            sys.modules.pop(name, None)
        sys.modules.update(saved)
    return module, finder.order


class ImportOrderTest(unittest.TestCase):
    def test_torch_is_imported_before_ctranslate2_and_faster_whisper(self):
        _, order = import_with_fakes()
        self.assertEqual(order, ["torch", "ctranslate2", "faster_whisper", "faster_whisper.tokenizer"])


class TranscribeTest(unittest.TestCase):
    def setUp(self):
        self.module, _ = import_with_fakes()
        self.asr = object.__new__(self.module.WhisperAsr)
        self.asr._model, self.asr._filters, self.asr.options = object(), object(), {}
        self.audio = np.zeros(48000, dtype=np.float32)
        self.chunks = [
            {"start": 0.0, "end": 1.0, "start_sample": 0, "end_sample": 16000, "segments": [[0.0, 1.0]]},
            {"start": 1.0, "end": 2.0, "start_sample": 16000, "end_sample": 32000, "segments": [[1.0, 2.0]]},
            {"start": 2.0, "end": 3.0, "start_sample": 32000, "end_sample": 48000, "segments": [[2.0, 3.0]]},
        ]

    def run_transcribe(self, generate):
        features = mock.Mock(return_value=np.zeros((128, 3000), dtype=np.float32))
        with mock.patch.object(self.module, "features", features), \
                mock.patch.object(self.module, "generate", side_effect=generate):
            return self.asr.transcribe(self.audio, self.chunks), features

    def test_windows_are_cropped_by_integer_samples_and_copied_into_segments(self):
        results = iter([{"text": t, "avg_logprob": -0.1, "tokens": [1], "prompt": [2], "kwargs": {}}
                        for t in ("あ", "い", "う")])
        (segments, traces, failures), features = self.run_transcribe(lambda *args: next(results))
        self.assertEqual([s["text"] for s in segments], ["あ", "い", "う"])
        self.assertEqual(failures, [])
        self.assertEqual([(s["start_sample"], s["end_sample"]) for s in segments],
                         [(0, 16000), (16000, 32000), (32000, 48000)])
        self.assertEqual([len(call.args[0]) for call in features.call_args_list], [16000] * 3)
        self.assertEqual([t["start_sample"] for t in traces], [0, 16000, 32000])

    def test_runtime_error_in_one_window_is_recorded_and_the_rest_continue(self):
        def generate(model, mel, options):
            generate.calls += 1
            if generate.calls == 2:
                raise RuntimeError("CUDA failed with error out of memory")
            return {"text": "文", "avg_logprob": -0.2, "tokens": [], "prompt": [], "kwargs": {}}
        generate.calls = 0
        (segments, traces, failures), _ = self.run_transcribe(generate)
        self.assertEqual([s["text"] for s in segments], ["文", "", "文"])
        self.assertIsNone(traces[1])
        self.assertIsNone(segments[1]["avg_logprob"])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0][0], 1)
        self.assertIn("RuntimeError", failures[0][1])

    def test_invalid_windows_are_rejected_before_decoding(self):
        self.chunks[1]["end_sample"] = 15000
        with self.assertRaises(ValueError):
            self.run_transcribe(lambda *args: {})


NO_TIMESTAMPS = 50363
SOT_SEQUENCE = [50258, 50266, 50360]


class _FakeTokenizer:
    """可预测的分词器：每个字符一个 token（`ord(c) % 50 + 1`）。"""

    sot_sequence = tuple(SOT_SEQUENCE)
    no_timestamps = NO_TIMESTAMPS
    eot = 50257

    def __init__(self, *args, **kwargs) -> None:
        self.tokenizer = mock.Mock()
        self.tokenizer.decode_batch.return_value = ["文"]

    def encode(self, text: str) -> list[int]:
        return [ord(char) % 50 + 1 for char in text]


def _prob(token: int) -> float:
    return 1.0 / (token + 1)


class ScoreTest(unittest.TestCase):
    def setUp(self):
        self.module, _ = import_with_fakes()
        self.asr = object.__new__(self.module.WhisperAsr)
        self.model = mock.Mock()
        self.model.hf_tokenizer = object()
        self.model.model.is_multilingual = True
        # 与 faster-whisper `get_prompt(previous=[], without_timestamps=True)` 同形
        self.model.get_prompt.side_effect = lambda tokenizer, previous, **kwargs: (
            list(tokenizer.sot_sequence) + ([tokenizer.no_timestamps] if kwargs["without_timestamps"] else []))
        self.model.encode.return_value = "encoder-output"
        self.model.model.align.side_effect = self.align
        self.asr._model, self.asr._filters = self.model, object()
        self.asr.options = {}
        self.audio = np.zeros(48000, dtype=np.float32)
        self.chunk = {"start": 1.0, "end": 2.0, "start_sample": 16000, "end_sample": 32000}
        self.aligned: list[tuple] = []
        self.torch = mock.MagicMock()
        self.features = mock.Mock(return_value=np.zeros((128, 3000), dtype=np.float32))
        patches = (mock.patch.object(self.module, "features", self.features),
                   mock.patch.object(self.module, "Tokenizer", _FakeTokenizer),
                   mock.patch.object(self.module, "torch", self.torch),
                   mock.patch.object(self.module, "ctranslate2", mock.MagicMock()))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def align(self, view, start_sequence, text_tokens, num_frames):
        self.aligned.append((start_sequence, text_tokens, num_frames))
        return [types.SimpleNamespace(text_token_probs=[_prob(token) for token in tokens])
                for tokens in text_tokens]

    @staticmethod
    def expected(text: str) -> float:
        return sum(math.log(_prob(token)) for token in _FakeTokenizer().encode(text))

    def test_scores_are_the_sum_of_log_probs_in_input_order(self):
        texts = ["あい", "う", "えおか"]
        scores = self.asr.score(self.audio, self.chunk, texts)
        self.assertEqual(len(scores), 3)
        for text, score in zip(texts, scores):
            self.assertAlmostEqual(score, self.expected(text))

    def test_window_audio_is_sliced_like_transcribe_and_frames_follow_the_window(self):
        self.asr.score(self.audio, self.chunk, ["あ"])
        window = self.features.call_args.args[0]
        self.assertEqual(len(window), 16000)
        self.assertEqual(self.features.call_args.args[1], self.asr._filters)
        self.assertEqual(self.aligned[0][2], [100])  # ceil(16000 / 160)

    def test_encoder_runs_once_and_texts_are_aligned_in_batches_of_at_most_16(self):
        texts = [f"{chr(0x3042 + index)}" for index in range(40)]
        scores = self.asr.score(self.audio, self.chunk, texts)
        self.assertEqual(self.model.encode.call_count, 1)
        self.assertEqual([len(call[1]) for call in self.aligned], [16, 16, 8])
        self.assertEqual([tokens for call in self.aligned for tokens in call[1]],
                         [_FakeTokenizer().encode(text) for text in texts])
        self.assertEqual(self.torch.as_tensor.call_count, 1)
        expanded = self.torch.as_tensor.return_value.expand
        self.assertEqual([call.args[0] for call in expanded.call_args_list], [16, 16, 8])
        for text, score in zip(texts, scores):
            self.assertAlmostEqual(score, self.expected(text))

    def test_max_batch_argument_is_honored(self):
        self.asr.score(self.audio, self.chunk, ["あ", "い", "う"], max_batch=2)
        self.assertEqual([len(call[1]) for call in self.aligned], [2, 1])

    def test_empty_text_scores_zero_and_is_not_sent_to_align(self):
        scores = self.asr.score(self.audio, self.chunk, ["", "あい", ""])
        self.assertEqual(scores[0], 0.0)
        self.assertEqual(scores[2], 0.0)
        self.assertAlmostEqual(scores[1], self.expected("あい"))
        self.assertEqual(sum(len(call[1]) for call in self.aligned), 1)

    def test_all_empty_skips_features_encoder_and_align(self):
        self.assertEqual(self.asr.score(self.audio, self.chunk, ["", ""]), [0.0, 0.0])
        self.assertEqual(self.asr.score(self.audio, self.chunk, []), [])
        self.features.assert_not_called()
        self.model.encode.assert_not_called()
        self.assertEqual(self.aligned, [])

    def test_zero_probability_is_clamped(self):
        self.model.model.align.side_effect = lambda *args: [types.SimpleNamespace(text_token_probs=[0.0])]
        [score] = self.asr.score(self.audio, self.chunk, ["あ"])
        self.assertAlmostEqual(score, math.log(1e-45))

    def test_prob_count_mismatch_raises(self):
        self.model.model.align.side_effect = lambda *args: [types.SimpleNamespace(text_token_probs=[0.5])]
        with self.assertRaises(RuntimeError):
            self.asr.score(self.audio, self.chunk, ["あい"])

    def test_result_count_mismatch_raises(self):
        self.model.model.align.side_effect = lambda *args: []
        with self.assertRaises(RuntimeError):
            self.asr.score(self.audio, self.chunk, ["あ"])

    def test_start_sequence_is_the_generate_prompt_without_the_notimestamps_token(self):
        options = {"initial_prompt": None, "without_timestamps": True, "prefix": None, "hotwords": None,
                   "beam_size": 1, "patience": 1.0, "length_penalty": 1.0, "suppress_blank": True,
                   "suppress_tokens": [], "no_repeat_ngram_size": 0, "repetition_penalty": 1.0}
        self.model.model.generate.return_value = [types.SimpleNamespace(sequences_ids=[[7]], scores=[-0.5])]
        prompt = self.module.generate(self.model, self.features.return_value, options)["prompt"]
        self.asr.score(self.audio, self.chunk, ["あ"])
        start_sequence = self.aligned[0][0]
        self.assertEqual(start_sequence, SOT_SEQUENCE)
        self.assertEqual(prompt, start_sequence + [NO_TIMESTAMPS])


if __name__ == "__main__":
    unittest.main()
