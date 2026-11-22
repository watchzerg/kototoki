"""`kototoki.asr_whisper`：W0 特征规则、逐窗失败记账与裁判打分。

用伪模块代替 torch／ctranslate2／faster_whisper，不加载真实库与 GPU。
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


class FeaturesTest(unittest.TestCase):
    """faster-whisper 逐块路径：去掉最后一帧，再在 Mel 上补零或截断到 3000 帧（ADR-0035「W0 特征」）。"""

    def setUp(self):
        self.module, _ = import_with_fakes()

    def test_short_window_is_trimmed_by_one_frame_then_zero_padded(self):
        extractor = mock.Mock(return_value=np.ones((128, 101), dtype=np.float32))
        mel = self.module.features(np.zeros(16000, dtype=np.float32), extractor)
        self.assertEqual(mel.shape, (128, 3000))
        self.assertEqual(float(mel[:, :100].min()), 1.0)
        self.assertEqual(float(np.abs(mel[:, 100:]).max()), 0.0)



class TranscribeTest(unittest.TestCase):
    def setUp(self):
        self.module, _ = import_with_fakes()
        self.asr = object.__new__(self.module.WhisperAsr)
        self.asr._model, self.asr.options = mock.Mock(), {}
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
        self.asr._model = self.model
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

    def test_empty_text_scores_zero_and_is_not_sent_to_align(self):
        scores = self.asr.score(self.audio, self.chunk, ["", "あい", ""])
        self.assertEqual(scores[0], 0.0)
        self.assertEqual(scores[2], 0.0)
        self.assertAlmostEqual(scores[1], self.expected("あい"))
        self.assertEqual(sum(len(call[1]) for call in self.aligned), 1)


if __name__ == "__main__":
    unittest.main()
