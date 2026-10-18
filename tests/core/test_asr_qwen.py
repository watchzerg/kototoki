"""`kototoki.asr_qwen` 与 ASR worker 的 x0 分支：逐窗转写、触顶窗口置空并记 `failed_windows`、窗口级失败。

用伪模块代替 torch／transformers 导入，伪 processor 与伪模型代替 Qwen3-ASR：不加载真实库与 GPU。
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.abc
import importlib.util
import sys
import types
import unittest
from unittest import mock

import numpy as np

from kototoki import artifacts, config, cues, plan, recipes
from kototoki.workers import align as align_worker
from kototoki.workers import asr as asr_worker
from kototoki.workers.protocol import EXIT_OK
from tests.core.test_stt_workers import MODELS, FakeAligner, WorkerTestCase

FAKE = ("torch", "transformers")
TARGET = "kototoki.asr_qwen"
LIMIT = recipes.X0["generate"]["max_new_tokens"]
PROMPT_TOKENS = 3


class _FakeFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, name, path, target=None):
        return importlib.util.spec_from_loader(name, self) if name in FAKE else None

    def create_module(self, spec):
        module = types.ModuleType(spec.name)
        module.__getattr__ = lambda name: mock.MagicMock(name=f"{spec.name}.{name}")
        return module

    def exec_module(self, module) -> None:
        pass


def import_with_fakes() -> types.ModuleType:
    saved = {name: sys.modules.pop(name) for name in (*FAKE, TARGET) if name in sys.modules}
    finder = _FakeFinder()
    sys.meta_path.insert(0, finder)
    try:
        module = importlib.import_module(TARGET)
    finally:
        sys.meta_path.remove(finder)
        for name in (*FAKE, TARGET):
            sys.modules.pop(name, None)
        sys.modules.update(saved)
    return module


class FakeDevice(str):
    @property
    def type(self) -> str:
        return self.split(":")[0]


class FakeTensor:
    """只支持本模块用到的二维整数张量操作。"""

    def __init__(self, rows: list[list[int]], device: str = "cuda:0") -> None:
        self.rows, self.device, self._device = rows, FakeDevice(device), device

    @property
    def ndim(self) -> int:
        return 2

    @property
    def shape(self) -> tuple[int, int]:
        return (len(self.rows), len(self.rows[0]))

    def is_floating_point(self) -> bool:
        return False

    def __getitem__(self, key):
        if isinstance(key, tuple):
            return FakeTensor([row[key[1]] for row in self.rows[key[0]]], self._device)
        return FakeTensor([self.rows[key]], self._device)

    def detach(self):
        return self

    def cpu(self):
        return self

    def tolist(self):
        return self.rows[0] if len(self.rows) == 1 else self.rows


FAKE_TORCH = types.SimpleNamespace(
    Tensor=FakeTensor, bfloat16="bfloat16", inference_mode=contextlib.nullcontext,
    cuda=types.SimpleNamespace(synchronize=lambda: None, reset_peak_memory_stats=lambda: None,
                               max_memory_allocated=lambda: 1, max_memory_reserved=lambda: 2))


class FakeBatch(dict):
    def to(self, device, dtype):
        return self


class FakeProcessor:
    def __init__(self) -> None:
        self.texts: dict[int, str] = {}

    def apply_transcription_request(self, audio, language, processor_kwargs):
        assert language == "ja" and processor_kwargs == {"audio_kwargs": {"sampling_rate": 16000}}
        return FakeBatch(input_ids=FakeTensor([[7] * PROMPT_TOKENS]))

    def decode(self, generated, return_format="raw"):
        text = self.texts[len(generated.rows[0])]
        return [{"language": "Japanese", "transcription": text}] if return_format == "parsed" else [text]


class FakeModel:
    dtype = "torch.bfloat16"

    def __init__(self, processor: FakeProcessor, plan: list) -> None:
        self.processor, self.plan, self.calls = processor, list(plan), []

    def parameters(self):
        return [types.SimpleNamespace(device="cuda:0")]

    def generate(self, input_ids, max_new_tokens, do_sample):
        self.calls.append((max_new_tokens, do_sample))
        step = self.plan.pop(0)
        if isinstance(step, Exception):
            raise step
        text, count = step
        self.processor.texts[count] = text
        return FakeTensor([input_ids.rows[0] + list(range(count))])


def window(start: int, end: int) -> dict:
    return {"start": start / 16000, "end": end / 16000, "start_sample": start, "end_sample": end,
            "segments": [[start / 16000, end / 16000]]}


def fake_qwen(module: types.ModuleType, plan: list):
    asr = object.__new__(module.QwenAsr)
    asr._processor = FakeProcessor()
    asr._model = FakeModel(asr._processor, plan)
    asr.metadata = {"device": "fake"}
    return asr


class TranscribeTest(unittest.TestCase):
    def setUp(self):
        self.module = import_with_fakes()
        patcher = mock.patch.object(self.module, "torch", FAKE_TORCH)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.audio = np.zeros(48000, dtype=np.float32)
        self.chunks = [window(0, 16000), window(16000, 32000), window(32000, 48000)]

    def test_windows_are_transcribed_independently_with_recipe_options(self):
        asr = fake_qwen(self.module, [("あ", 2), ("い", 3), ("う", 4)])
        segments, traces, failures = asr.transcribe(self.audio, self.chunks)
        self.assertEqual([s["text"] for s in segments], ["あ", "い", "う"])
        self.assertEqual(failures, [])
        self.assertEqual([(s["start_sample"], s["end_sample"]) for s in segments],
                         [(0, 16000), (16000, 32000), (32000, 48000)])
        self.assertEqual(set(segments[0]), {"text", "start", "end", "start_sample", "end_sample", "avg_logprob"})
        self.assertEqual(traces[1]["tokens"], [0, 1, 2])  # 只取 prompt 之后的生成部分
        self.assertFalse(traces[1]["token_limit_reached"])
        self.assertEqual(asr._model.calls, [(LIMIT, False)] * 3)
        self.assertEqual(asr.metadata["peak_reserved_bytes"], 2)

    def test_token_limit_window_keeps_truncated_text_for_the_shell_to_empty(self):
        asr = fake_qwen(self.module, [("あ", 2), ("ああああ", LIMIT), ("う", 4)])
        segments, traces, failures = asr.transcribe(self.audio, self.chunks)
        self.assertEqual(segments[1]["text"], "ああああ")
        self.assertTrue(traces[1]["token_limit_reached"])
        self.assertEqual(traces[1]["generated_tokens"], LIMIT)
        self.assertEqual(failures, [(1, f"token_limit_reached: generated {LIMIT} tokens")])
        self.assertEqual(segments[2]["text"], "う")

    def test_runtime_error_in_one_window_is_recorded_and_the_rest_continue(self):
        asr = fake_qwen(self.module, [("あ", 2), RuntimeError("CUDA out of memory"), ("う", 4)])
        segments, traces, failures = asr.transcribe(self.audio, self.chunks)
        self.assertEqual([s["text"] for s in segments], ["あ", "", "う"])
        self.assertIsNone(traces[1])
        self.assertEqual(failures[0][0], 1)
        self.assertIn("RuntimeError", failures[0][1])

    def test_model_off_cuda_is_rejected(self):
        asr = fake_qwen(self.module, [("あ", 2)])
        asr._model.parameters = lambda: [types.SimpleNamespace(device="cpu")]
        with self.assertRaises(RuntimeError):
            asr.transcribe(self.audio, self.chunks)

    def test_invalid_windows_are_rejected_before_decoding(self):
        self.chunks[1]["end_sample"] = 15000
        asr = fake_qwen(self.module, [])
        with self.assertRaises(ValueError):
            asr.transcribe(self.audio, self.chunks)


class X0WorkerTest(WorkerTestCase):
    """x0 适配器经 ASR worker 壳：触顶窗口置空、截断文字进 `failed_windows`，不进对齐与 cue。"""

    def setUp(self):
        super().setUp()
        self.module = import_with_fakes()
        patcher = mock.patch.object(self.module, "torch", FAKE_TORCH)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_token_limit_window_is_emptied_recorded_and_skipped_downstream(self):
        self.run_vad()
        asr = fake_qwen(self.module, [("こんにちは。", 5), ("ああああ", LIMIT), ("はい", 3)])
        status = self.run_stage(asr_worker.compute(asr, "x0", MODELS, 2.0),
                                {"wav": self.wav, "vad": self.work_dir / artifacts.VAD})
        self.assertEqual(status, EXIT_OK)
        path = self.work_dir / artifacts.ASR
        vad_sha256 = artifacts.sha256_file(self.work_dir / artifacts.VAD)
        self.assertTrue(artifacts.is_current(path, plan.asr_identity("x0", self.pcm_sha256, vad_sha256, MODELS)))
        document = artifacts.read_json(path)
        self.assertEqual(document["engine"], "x0")
        self.assertEqual(document["original_segments"][1]["text"], "")
        self.assertEqual(document["failed_windows"], [{"chunk_index": 1, "text": "ああああ",
                                                       "reason": f"token_limit_reached: generated {LIMIT} tokens"}])
        self.assertEqual(document["text"], "こんにちは。はい")
        self.assertTrue(document["asr_traces"][1]["token_limit_reached"])
        self.assertEqual(self.progress()[-1]["failed_windows"], 1)

        self.assertEqual(self.run_stage(align_worker.compute(FakeAligner(), MODELS, 3.0),
                                        {"wav": self.wav, "asr": path}), EXIT_OK)
        align = artifacts.read_json(self.work_dir / artifacts.ALIGN)
        self.assertEqual(align["text"], "こんにちは。はい")
        self.assertEqual(align["failed_windows"][0]["chunk_index"], 1)
        _, srt_text = cues.build_cues(align, config.DEFAULTS["cues"])
        self.assertNotIn("あ", srt_text)


class X0ShellTest(unittest.TestCase):
    def test_recipe_hash_and_model_files_follow_engine(self):
        self.assertEqual(plan.recipe_hash("asr", engine="x0"), recipes.recipe_hash(recipes.X0))
        files = plan.model_files("asr", {"x0": "q"}, engine="x0")
        self.assertEqual(len(files), 7)
        self.assertEqual(files["qwen3-asr-1.7b-hf/model.safetensors"][1],
                         "2db53c7d81bd9b8cbc6a074e89be2c968a0d373fb4ee68bb1b1e14f7042dfee1")
        self.assertTrue(all(path.parent.name == "q" for path, _ in files.values()))


if __name__ == "__main__":
    unittest.main()
