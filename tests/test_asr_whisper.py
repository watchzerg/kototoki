"""`kototoki.asr_whisper`：导入顺序（torch 先于 ctranslate2／faster_whisper）与逐窗失败记账。

用伪模块代替 torch／ctranslate2／faster_whisper：导入时记录次序，不加载真实库与 GPU。
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import sys
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


if __name__ == "__main__":
    unittest.main()
