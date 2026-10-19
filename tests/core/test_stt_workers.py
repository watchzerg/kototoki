"""三个 STT worker 壳（`kototoki.workers.{vad,asr,align}`）与共用的 `workers.gpu`：伪推理对象，离线。

覆盖产物身份与坐标（壳写出的身份与阶段计划模块 `kototoki.plan` 给出的期望身份逐字段相等，壳自身不再持有
身份实现）、输入身份重验、`failed_windows` 记账、退出码 0／1／2、CUDA 守卫、三阶段串起来的 `align.json`
能被 `cues.build_cues` 消费、worker 进程的 stderr 日志与 stdout 协议行分离，以及壳模块导入时不加载 torch。
cross 引擎（伪 Whisper／Qwen）：四个产物、裁判切换与 margin 边界、相同窗口不打分、两路失败窗口与打分出错的处理、
x0 空白清理、合并结果被 align 消费、启动时先 Whisper 后 Qwen。
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock
import wave

import numpy as np

from kototoki import artifacts, config, cues, plan, recipes
from kototoki.align import map_records
from kototoki.schema import validate_transcript
from kototoki.workers import align as align_worker
from kototoki.workers import asr as asr_worker
from kototoki.workers import gpu
from kototoki.workers import vad as vad_worker
from kototoki.workers.protocol import (EXIT_FATAL, EXIT_OK, EXIT_PARTIAL, FatalWorkerError, FileJob, Jobs,
                                       run_jobs, run_worker, write_jobs)

MODELS = {"vad": "a" * 64}
SAMPLES = 3 * 16000
REPO = Path(__file__).resolve().parents[2]
LOG_LINE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}Z \[ *\d+\.\ds\] (\w+) +(.*)$")
SECRET = "ひみつの窓"


def write_wav(path: Path, samples: np.ndarray, *, channels: int = 1) -> str:
    pcm = samples.astype("<i2").tobytes()
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(channels)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(pcm)
    return hashlib.sha256(pcm).hexdigest()


def window(start: int, end: int) -> dict:
    return {"start": start / 16000, "end": end / 16000, "start_sample": start, "end_sample": end,
            "segments": [[start / 16000, end / 16000]]}


CHUNKS = [window(0, 16000), window(16000, 32000), window(32000, 48000)]


class FakeVad:
    metadata = {"device": "fake"}

    def segment(self, audio):
        return [dict(chunk) for chunk in CHUNKS], {"accounting": {"chunk_count": len(CHUNKS)}}


class FakeAsr:
    metadata = {"device": "fake"}

    def __init__(self, failures=()):
        self.failures = list(failures)

    def transcribe(self, audio, chunks):
        segments = [{"text": "" if i in dict(self.failures) else text, "start": c["start"], "end": c["end"],
                     "start_sample": c["start_sample"], "end_sample": c["end_sample"], "avg_logprob": -0.1}
                    for i, (c, text) in enumerate(zip(chunks, ("こんにちは。", "元気？", "はい")))]
        return segments, [None] * len(segments), self.failures


class LeakyAsr(FakeAsr):
    """失败窗口仍带着截断文字（真实适配器的生成触顶就是这样），用来确认文字不进日志。"""

    def transcribe(self, audio, chunks):
        segments, traces, failures = super().transcribe(audio, chunks)
        for index, _ in failures:
            segments[index]["text"] = SECRET
        return segments, traces, failures


class FakeEngine:
    """给定每窗文字的伪适配器（cross 用两份：一份当 w0，一份当 x0）；失败窗口的文字照样返回。"""

    def __init__(self, name, texts, failures=()):
        self.metadata = {"device": "fake", "engine": name}
        self.texts, self.failures = list(texts), list(failures)

    def transcribe(self, audio, chunks):
        segments = [{"text": text, "start": c["start"], "end": c["end"], "start_sample": c["start_sample"],
                     "end_sample": c["end_sample"], "avg_logprob": -0.1} for c, text in zip(chunks, self.texts)]
        return segments, [{"window": i} for i in range(len(segments))], self.failures


class FakeWhisper(FakeEngine):
    """`score`：`scores` 里有的文本取其分数，空文本 0.0，其余 −10；`error` 非空时抛 RuntimeError。"""

    def __init__(self, texts, failures=(), scores=None, error=None):
        super().__init__("w0", texts, failures)
        self.scores, self.error, self.calls = dict(scores or {}), error, []

    def score(self, audio, chunk, texts, max_batch=16):
        self.calls.append((chunk["start_sample"], list(texts), max_batch))
        if self.error:
            raise RuntimeError(self.error)
        return [0.0 if not text else self.scores.get(text, -10.0) for text in texts]


W0_SHA = {"faster-whisper-large-v3/model.bin": "c" * 64}
X0_SHA = {"qwen3-asr-1.7b-hf/model.safetensors": "d" * 64}
CROSS_SHA = {**W0_SHA, **X0_SHA}
LOADS = {"load_s": 5.0, "load_w0_s": 2.0, "load_x0_s": 3.0}


def leaky_asr_start(jobs):
    """`WorkerLogTest` 子进程里的伪 `start`：不加载模型，直接用伪 ASR 跑 `asr` 壳的 `compute`。"""
    return gpu.file_processor(asr_worker.compute(LeakyAsr([(1, "RuntimeError: boom")]), "w0", MODELS, 2.0),
                              check=no_check)


class FakeAligner:
    """每个字符占 0.1 s，窗口内从窗口起点排开。"""
    metadata = {"device": "fake"}

    def align(self, audio, segments, offset=0):
        records = []
        for index, segment in enumerate(segments):
            count = len(segment["text"])
            records.append({"segment_index": index, "window_start": segment["start"], "window_end": segment["end"],
                            "frame_count": 50, "failure": None,
                            "tokens": [{"original_position": p, "lexical_interval_accepted": True,
                                        "evidence_kind": "vocabulary_token", "start_frame": 5 * p,
                                        "end_frame": 5 * p + 4, "token_probability": 0.9} for p in range(count)]})
        return map_records(segments, records, offset)


def no_check() -> None:
    pass


class WorkerTestCase(unittest.TestCase):
    def setUp(self):
        # 进程内跑壳时日志无处可去：挂 NullHandler，免得 logging 的 lastResort 把告警与 traceback 打到测试输出。
        quiet, workers = logging.NullHandler(), logging.getLogger("kototoki.workers")
        workers.addHandler(quiet)
        self.addCleanup(workers.removeHandler, quiet)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.work_dir = self.root / "out" / ".work" / "0123456789ab"
        self.work_dir.mkdir(parents=True)
        self.wav = self.work_dir / artifacts.AUDIO_16K
        self.pcm_sha256 = write_wav(self.wav, (np.arange(SAMPLES) % 200 - 100).astype(np.int16))
        self.stream = io.BytesIO()

    def run_stage(self, compute, inputs, *, check=no_check) -> int:
        job = FileJob("0123456789ab", self.work_dir, {name: Path(path) for name, path in inputs.items()})
        jobs = Jobs("stage", "0" * 64, {}, (job,))
        return run_jobs(jobs, gpu.file_processor(compute, check=check), stream=self.stream)

    def progress(self) -> list[dict]:
        return [json.loads(line) for line in self.stream.getvalue().decode("utf-8").splitlines()]

    def run_vad(self) -> int:
        return self.run_stage(vad_worker.compute(FakeVad(), MODELS, 1.5), {"wav": self.wav})

    def run_asr(self, asr=None) -> int:
        return self.run_stage(asr_worker.compute(asr or FakeAsr(), "w0", MODELS, 2.0),
                              {"wav": self.wav, "vad": self.work_dir / artifacts.VAD})

    def run_cross(self, whisper, qwen) -> int:
        compute = asr_worker.compute_cross(whisper, qwen, CROSS_SHA, W0_SHA, X0_SHA, LOADS, check=no_check)
        return self.run_stage(compute, {"wav": self.wav, "vad": self.work_dir / artifacts.VAD})

    def run_align(self) -> int:
        return self.run_stage(align_worker.compute(FakeAligner(), MODELS, 3.0),
                              {"wav": self.wav, "asr": self.work_dir / artifacts.ASR})


class VadWorkerTest(WorkerTestCase):
    def test_writes_local_coordinate_windows_with_identity(self):
        self.assertEqual(self.run_vad(), EXIT_OK)
        path = self.work_dir / artifacts.VAD
        expected = plan.vad_identity(self.pcm_sha256, MODELS)
        self.assertEqual(artifacts.read_json(path)["identity"], expected)
        self.assertTrue(artifacts.is_current(path, expected))
        self.assertEqual(expected["recipe_hash"], recipes.recipe_hash(recipes.VAD))
        document = artifacts.read_json(path)
        self.assertEqual(document["offset_s"], 0)
        self.assertEqual(document["chunks"], CHUNKS)
        self.assertEqual(document["input"]["samples"], SAMPLES)
        self.assertEqual(document["stages"]["load_s"], 1.5)
        self.assertEqual(self.progress(), [{"windows": 3, "event": "done", "id": "0123456789ab"}])

    def test_invalid_windows_fail_the_file_without_writing(self):
        class BadVad(FakeVad):
            def segment(self, audio):
                return [window(0, 600000)], {}
        self.assertEqual(self.run_stage(vad_worker.compute(BadVad(), MODELS, 0), {"wav": self.wav}), EXIT_PARTIAL)
        self.assertFalse((self.work_dir / artifacts.VAD).exists())
        self.assertTrue((self.work_dir / artifacts.FAILURE).exists())


class AsrWorkerTest(WorkerTestCase):
    def test_writes_segments_and_identity_chained_to_vad(self):
        self.run_vad()
        self.assertEqual(self.run_asr(), EXIT_OK)
        vad_sha256 = artifacts.sha256_file(self.work_dir / artifacts.VAD)
        path = self.work_dir / artifacts.ASR
        expected = plan.asr_identity("w0", self.pcm_sha256, vad_sha256, MODELS)
        self.assertEqual(artifacts.read_json(path)["identity"], expected)
        self.assertTrue(artifacts.is_current(path, expected))
        document = artifacts.read_json(path)
        self.assertEqual(document["engine"], "w0")
        self.assertEqual(document["offset_s"], 0)
        self.assertEqual(document["chunks"], CHUNKS)
        self.assertEqual(document["failed_windows"], [])
        self.assertEqual(document["text"], "こんにちは。元気？はい")

    def test_failed_window_is_emptied_and_recorded(self):
        self.run_vad()
        self.assertEqual(self.run_asr(FakeAsr(failures=[(1, "RuntimeError: boom")])), EXIT_OK)
        document = artifacts.read_json(self.work_dir / artifacts.ASR)
        self.assertEqual(document["original_segments"][1]["text"], "")
        self.assertEqual(document["failed_windows"], [{"chunk_index": 1, "reason": "RuntimeError: boom", "text": ""}])
        self.assertEqual(document["text"], "こんにちは。はい")
        self.assertEqual(self.progress()[-1]["failed_windows"], 1)

    def test_vad_from_other_audio_fails_the_file(self):
        self.run_vad()
        write_wav(self.wav, np.zeros(SAMPLES, dtype=np.int16))
        self.assertEqual(self.run_asr(), EXIT_PARTIAL)
        self.assertFalse((self.work_dir / artifacts.ASR).exists())
        self.assertEqual(artifacts.read_json(self.work_dir / artifacts.FAILURE)["stage"], "stage")

    def test_recipe_hash_follows_engine(self):
        self.assertEqual(plan.recipe_hash("asr", engine="w0"), recipes.recipe_hash(recipes.W0))
        self.assertEqual(plan.recipe_hash("asr", engine="x0"), recipes.recipe_hash(recipes.X0))
        self.assertEqual(plan.recipe_hash("asr", engine="cross"), recipes.recipe_hash(recipes.CROSS))


W0_TEXTS = ("こんにちは。", "元気？", "はい")
X0_TOKEN_LIMIT = [(2, "token_limit_reached: generated 448 tokens")]


class CrossAsrWorkerTest(WorkerTestCase):
    """cross：窗口 0 两路规范化相同，窗口 1 有分歧（x0 文字中间带空格），窗口 2 x0 触顶。"""

    def setUp(self):
        super().setUp()
        self.run_vad()
        self.vad_sha256 = artifacts.sha256_file(self.work_dir / artifacts.VAD)

    def qwen(self, texts=("こんにちは", "げん き？", "ええ"), failures=X0_TOKEN_LIMIT):
        return FakeEngine("x0", texts, failures)

    def read(self, name):
        return artifacts.read_json(self.work_dir / name)

    def test_writes_four_artifacts_and_switches_preferred_x0_interval(self):
        whisper = FakeWhisper(W0_TEXTS, scores={"げんき？": -9.5})
        self.assertEqual(self.run_cross(whisper, self.qwen()), EXIT_OK)
        identity = plan.asr_identity("cross", self.pcm_sha256, self.vad_sha256, CROSS_SHA)
        self.assertTrue(artifacts.is_current(self.work_dir / artifacts.ASR, identity))
        document = self.read(artifacts.ASR)
        validate_transcript(document)
        self.assertEqual(document["engine"], "cross")
        self.assertEqual(document["offset_s"], 0)
        self.assertEqual(document["chunks"], CHUNKS)
        self.assertEqual([s["text"] for s in document["original_segments"]], ["こんにちは。", "げんき？", "はい"])
        self.assertEqual(document["original_segments"][1]["avg_logprob"], -0.1)  # w0 的段结构
        self.assertEqual(document["text"], "こんにちは。げんき？はい")
        self.assertEqual(document["asr_traces"], [{"window": 0}, {"window": 1}, {"window": 2}])
        self.assertEqual(document["failed_windows"], [])
        self.assertEqual(document["metadata"]["w0"]["engine"], "w0")
        self.assertEqual(document["metadata"]["x0"]["engine"], "x0")
        meta = document["metadata"]["judge"]
        self.assertEqual((meta["id"], meta["margin"], meta["max_batch"]),
                         (recipes.CROSS["id"], -1.0, 16))
        self.assertEqual({k: meta[k] for k in ("windows", "identical", "scored", "intervals", "switched",
                                               "w0_failed", "x0_failed", "score_error")},
                         {"windows": 3, "identical": 1, "scored": 1, "intervals": 1, "switched": 1,
                          "w0_failed": 0, "x0_failed": 1, "score_error": 0})
        self.assertEqual(set(document["stages"]), {"load_s", "load_w0_s", "load_x0_s", "inference_w0_s",
                                                   "inference_x0_s", "score_s"})
        self.assertEqual(document["stages"]["load_s"], 5.0)
        # 相同窗口与 x0 失败窗口不打分；分歧窗口 hyp_w 与 hyp_x 同批，x0 空白已清理
        self.assertEqual(whisper.calls, [(16000, ["元気？", "げんき？"], 16)])

        w0 = self.read(artifacts.ASR_W0)
        self.assertEqual(w0["identity"], plan.asr_identity("w0", self.pcm_sha256, self.vad_sha256, W0_SHA))
        self.assertEqual((w0["engine"], w0["text"], w0["offset_s"]), ("w0", "こんにちは。元気？はい", 0))
        x0 = self.read(artifacts.ASR_X0)
        self.assertEqual(x0["identity"], plan.asr_identity("x0", self.pcm_sha256, self.vad_sha256, X0_SHA))
        self.assertEqual((x0["engine"], x0["text"]), ("x0", "こんにちはげん き？"))
        self.assertEqual(x0["failed_windows"], [{"chunk_index": 2, "reason": X0_TOKEN_LIMIT[0][1], "text": "ええ"}])

        audit = self.read(artifacts.ASR_JUDGE)
        self.assertEqual(audit["identity"], identity)
        self.assertEqual(audit["offset_s"], 0)
        self.assertEqual([w["decision"] for w in audit["windows"]], ["identical", "judged", "x0_failed"])
        self.assertTrue(audit["windows"][0]["identical"])
        judged = audit["windows"][1]
        self.assertEqual((judged["index"], judged["w0_text"], judged["x0_text"], judged["text_form"], judged["guard"]),
                         (1, "元気？", "げん き？", "raw", None))
        self.assertEqual(judged["intervals"], [{"w": "元気", "x": "げんき", "kind": "substitution", "score_w": -10.0,
                                                "score_x": -9.5, "d": 0.5, "switched": True}])
        self.assertEqual(audit["summary"]["switched"], 1)
        self.assertEqual(self.progress()[-1], {"windows": 3, "failed_windows": 0, "identical": 1, "intervals": 1,
                                               "switched": 1, "x0_failed": 1, "score_error": 0,
                                               "event": "done", "id": "0123456789ab"})

    def test_margin_boundary_keeps_w0(self):
        whisper = FakeWhisper(W0_TEXTS, scores={"げんき？": -11.0})  # d = −1，不大于 margin
        self.assertEqual(self.run_cross(whisper, self.qwen()), EXIT_OK)
        self.assertEqual(self.read(artifacts.ASR)["text"], "こんにちは。元気？はい")
        self.assertFalse(self.read(artifacts.ASR_JUDGE)["windows"][1]["intervals"][0]["switched"])

    def test_w0_failed_window_stays_failed_without_x0_substitution(self):
        whisper = FakeWhisper(W0_TEXTS, failures=[(1, "RuntimeError: boom")], scores={"げんき？": 0.0})
        self.assertEqual(self.run_cross(whisper, self.qwen(("こんにちは", "げんき？", "はい"), ())), EXIT_OK)
        document = self.read(artifacts.ASR)
        validate_transcript(document)
        self.assertEqual(document["original_segments"][1]["text"], "")
        self.assertEqual(document["failed_windows"], [{"chunk_index": 1, "reason": "RuntimeError: boom",
                                                       "text": "元気？"}])
        self.assertEqual(document["text"], "こんにちは。はい")  # 窗口 2 两路相同
        self.assertEqual(whisper.calls, [])
        audit = self.read(artifacts.ASR_JUDGE)
        self.assertEqual([w["decision"] for w in audit["windows"]], ["identical", "w0_failed", "identical"])
        self.assertEqual(audit["summary"]["w0_failed"], 1)

    def test_score_error_keeps_w0_and_logs_no_text(self):
        whisper = FakeWhisper(("こんにちは。", SECRET, "はい"),
                              error="align returned a different number of results than texts")
        qwen = self.qwen(texts=("こんにちは", "ひみつのまど", "はい"), failures=())
        with self.assertLogs("kototoki.workers", "INFO") as logs:
            self.assertEqual(self.run_cross(whisper, qwen), EXIT_OK)
        output = "\n".join(logs.output)
        self.assertIn("[asr] 0123456789ab: window 1 score error, keeping w0: RuntimeError: align returned", output)
        self.assertIn("[asr] 0123456789ab: cross windows 3, identical 2, intervals 0, switched 0, x0_failed 0, "
                      "score_error 1, w0 ", output)
        for text in (SECRET, "ひみつのまど", "こんにちは", "はい"):
            self.assertNotIn(text, output)
        document = self.read(artifacts.ASR)
        self.assertEqual(document["original_segments"][1]["text"], SECRET)
        self.assertEqual(document["failed_windows"], [])
        self.assertEqual(document["metadata"]["judge"]["score_error"], 1)
        self.assertEqual(self.read(artifacts.ASR_JUDGE)["windows"][1]["decision"], "score_error")

    def test_score_count_mismatch_is_a_score_error(self):
        class Short(FakeWhisper):
            def score(self, audio, chunk, texts, max_batch=16):
                return super().score(audio, chunk, texts, max_batch)[:1]
        self.assertEqual(self.run_cross(Short(W0_TEXTS), self.qwen()), EXIT_OK)
        document = self.read(artifacts.ASR)
        self.assertEqual(document["text"], "こんにちは。元気？はい")
        self.assertEqual(document["metadata"]["judge"]["score_error"], 1)

    def test_clean_x0_drops_whitespace_next_to_non_ascii(self):
        self.assertEqual(asr_worker.clean_x0(" げん き 、OK  Google\nです "), "げんき、OK Googleです")
        self.assertEqual(asr_worker.clean_x0("a \t b"), "a b")
        self.assertEqual(asr_worker.clean_x0(""), "")


class CrossStartupTest(unittest.TestCase):
    def test_loads_whisper_then_qwen_and_splits_model_identities(self):
        order = []

        def adapter(name):
            def init(self, *paths):
                order.append((name, paths))
                self.metadata = {}
            return type(name, (), {"__init__": init})
        whisper_module, qwen_module = types.ModuleType("kototoki.asr_whisper"), types.ModuleType("kototoki.asr_qwen")
        whisper_module.WhisperAsr, qwen_module.QwenAsr = adapter("w0"), adapter("x0")
        models = {"w0": "w", "w0_mel_assets": "m", "x0": "x"}
        jobs = Jobs("asr", plan.recipe_hash("asr", engine="cross"),
                    {"engine": "cross", "models": models, "model_cache": "cache"}, ())
        verified = {name: "e" * 64 for name in plan.model_files("asr", models, engine="cross")}
        with mock.patch.dict(sys.modules, {"kototoki.asr_whisper": whisper_module, "kototoki.asr_qwen": qwen_module}), \
                mock.patch.object(gpu, "verify_models", return_value=verified), \
                mock.patch.object(asr_worker, "compute_cross", wraps=asr_worker.compute_cross) as compute, \
                self.assertLogs("kototoki.workers.asr", "INFO"):
            asr_worker.start(jobs)
        self.assertEqual(order, [("w0", (Path("w"), Path("m"))), ("x0", (Path("x"),))])
        _, _, model_sha256, w0_sha256, x0_sha256, loads = compute.call_args.args
        self.assertEqual(model_sha256, verified)
        self.assertEqual(set(w0_sha256), set(plan.model_files("asr", models, engine="w0")))
        self.assertEqual(set(x0_sha256), set(plan.model_files("asr", models, engine="x0")))
        self.assertEqual(set(loads), {"load_s", "load_w0_s", "load_x0_s"})


class AlignWorkerTest(WorkerTestCase):
    def test_chain_writes_a_valid_result_consumable_by_cues(self):
        self.run_vad()
        self.run_asr(FakeAsr(failures=[(1, "RuntimeError: boom")]))
        self.assertEqual(self.run_align(), EXIT_OK)
        asr_sha256 = artifacts.sha256_file(self.work_dir / artifacts.ASR)
        path = self.work_dir / artifacts.ALIGN
        expected = plan.align_identity(self.pcm_sha256, asr_sha256, MODELS)
        self.assertEqual(artifacts.read_json(path)["identity"], expected)
        self.assertTrue(artifacts.is_current(path, expected))
        document = artifacts.read_json(path)
        self.assertEqual(document["text"], "こんにちは。はい")
        self.assertEqual(len(document["units"]), len(document["text"]))
        self.assertEqual(document["units"][0]["start"], 0.0)
        self.assertEqual(document["units"][6]["start"], 2.0)  # 第三窗首字，WAV 本地秒
        self.assertEqual(document["failed_windows"][0]["chunk_index"], 1)
        self.assertEqual(document["source_end_seconds"], 3.0)
        payload, srt_text = cues.build_cues(document, config.DEFAULTS["cues"])
        self.assertTrue(srt_text.startswith("1\n00:00:00,000 --> "))

    def test_cross_asr_result_is_consumed_by_align(self):
        self.run_vad()
        self.run_cross(FakeWhisper(W0_TEXTS, scores={"げんき？": -9.5}),
                       FakeEngine("x0", ("こんにちは", "げん き？", "ええ"), X0_TOKEN_LIMIT))
        self.assertEqual(self.run_align(), EXIT_OK)
        asr_sha256 = artifacts.sha256_file(self.work_dir / artifacts.ASR)
        document = artifacts.read_json(self.work_dir / artifacts.ALIGN)
        self.assertEqual(document["identity"], plan.align_identity(self.pcm_sha256, asr_sha256, MODELS))
        self.assertEqual((document["engine"], document["text"]), ("cross", "こんにちは。げんき？はい"))
        self.assertEqual(len(document["units"]), len(document["text"]))
        payload, srt_text = cues.build_cues(document, config.DEFAULTS["cues"])
        self.assertTrue(srt_text.startswith("1\n00:00:00,000 --> "))

    def test_alignment_that_changes_text_fails_the_file(self):
        class Lossy(FakeAligner):
            def align(self, audio, segments, offset=0):
                result = super().align(audio, segments, offset)
                return {**result, "text": result["text"][:-1]}
        self.run_vad()
        self.run_asr()
        status = self.run_stage(align_worker.compute(Lossy(), MODELS, 0),
                                {"wav": self.wav, "asr": self.work_dir / artifacts.ASR})
        self.assertEqual(status, EXIT_PARTIAL)
        self.assertFalse((self.work_dir / artifacts.ALIGN).exists())


class CudaGuardTest(WorkerTestCase):
    @staticmethod
    def broken() -> None:
        raise FatalWorkerError("CUDA context is unusable")

    def test_error_with_broken_cuda_exits_2(self):
        class Crashing(FakeVad):
            def segment(self, audio):
                raise RuntimeError("CUDA error: an illegal memory access was encountered")
        status = self.run_stage(vad_worker.compute(Crashing(), MODELS, 0), {"wav": self.wav}, check=self.broken)
        self.assertEqual(status, EXIT_FATAL)
        self.assertEqual(self.progress()[-1]["event"], "fatal")

    def test_success_with_broken_cuda_exits_2_without_writing(self):
        status = self.run_stage(vad_worker.compute(FakeVad(), MODELS, 0), {"wav": self.wav}, check=self.broken)
        self.assertEqual(status, EXIT_FATAL)
        self.assertFalse((self.work_dir / artifacts.VAD).exists())

    def test_error_with_healthy_cuda_is_a_file_failure(self):
        class Crashing(FakeVad):
            def segment(self, audio):
                raise RuntimeError("bad input")
        status = self.run_stage(vad_worker.compute(Crashing(), MODELS, 0), {"wav": self.wav})
        self.assertEqual(status, EXIT_PARTIAL)


class StartupTest(unittest.TestCase):
    def run_start(self, start, stage, recipe_hash, config_value) -> tuple[int, dict]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.json"
            write_jobs(path, Jobs(stage, recipe_hash, config_value, ()))
            stream = io.BytesIO()
            with self.assertLogs("kototoki.workers.protocol", "ERROR"):
                status = run_worker(path, start, stream=stream)
        return status, json.loads(stream.getvalue().decode("utf-8"))

    def test_recipe_mismatch_fails_before_touching_models(self):
        status, event = self.run_start(vad_worker.start, "vad", "f" * 64, {"models": {}, "model_cache": "x"})
        self.assertEqual(status, EXIT_FATAL)
        self.assertEqual(event["event"], "startup_failed")
        self.assertIn("recipe_hash", event["message"])

    def test_unavailable_engine_fails_startup(self):
        status, event = self.run_start(asr_worker.start, "asr", recipes.recipe_hash(recipes.X0),
                                       {"engine": "x9", "models": {}, "model_cache": "x"})
        self.assertEqual(status, EXIT_FATAL)
        self.assertIn("x9", event["message"])

    def test_main_reads_jobs_argument(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.json"
            write_jobs(path, Jobs("vad", "0" * 64, {}, ()))
            root, ours = logging.getLogger(), logging.getLogger("kototoki")
            handlers, level = list(root.handlers), ours.level
            try:
                self.assertEqual(gpu.main(lambda jobs: (lambda job: None), ["--jobs", str(path)]), EXIT_OK)
            finally:  # main 为整个进程配置日志；测试进程里还原
                root.handlers[:] = handlers
                ours.setLevel(level)
                logging.captureWarnings(False)


class WorkerLogTest(WorkerTestCase):
    """真实子进程：日志只进 stderr 且符合运行日志格式，stdout 只有协议 JSON 行。"""

    def spawn(self, args: list[str]) -> tuple[int, list[dict], list[str]]:
        result = subprocess.run([sys.executable, *args], capture_output=True, cwd=REPO,
                                env={**os.environ, "PYTHONUTF8": "1"})
        stdout = [json.loads(line) for line in result.stdout.decode("utf-8").splitlines()]
        return result.returncode, stdout, result.stderr.decode("utf-8").splitlines()

    def test_shell_logs_go_to_stderr_without_window_text(self):
        self.run_vad()
        good = FileJob("0123456789ab", self.work_dir, {"wav": self.wav, "vad": self.work_dir / artifacts.VAD})
        broken_dir = self.root / "out" / ".work" / "ba9876543210"
        broken_dir.mkdir()
        broken = FileJob("ba9876543210", broken_dir, {"wav": broken_dir / "missing.wav", "vad": good.inputs["vad"]})
        jobs_path = self.root / "jobs.json"
        write_jobs(jobs_path, Jobs("asr", "0" * 64, {}, (good, broken)))
        code = ("import sys; from kototoki.workers import gpu; from tests.core.test_stt_workers import leaky_asr_start; "
                "sys.exit(gpu.main(leaky_asr_start, sys.argv[1:]))")
        status, stdout, stderr = self.spawn(["-c", code, "--jobs", str(jobs_path)])
        self.assertEqual(status, EXIT_PARTIAL)
        self.assertEqual([(event["event"], event["id"]) for event in stdout],
                         [("done", "0123456789ab"), ("failed", "ba9876543210")])
        entries = [(m[1], m[2]) for m in map(LOG_LINE.match, stderr) if m]
        self.assertIn(("WARNING", "[asr] 0123456789ab: window 1 failed: RuntimeError: boom"), entries)
        self.assertTrue(any(level == "INFO" and message.startswith("[asr] 0123456789ab: 3 window(s), 1 failed, "
                                                                   "inference ")
                            for level, message in entries), entries)
        self.assertIn(("ERROR", "[asr] FAILED ba9876543210: FileNotFoundError"), entries)
        self.assertIn("Traceback (most recent call last):", stderr)
        self.assertNotIn(SECRET, "\n".join(stderr))
        self.assertEqual(artifacts.read_json(self.work_dir / artifacts.ASR)["failed_windows"][0]["text"], SECRET)

    def test_startup_failure_logs_traceback_and_reports_on_stdout(self):
        jobs_path = self.root / "jobs.json"
        write_jobs(jobs_path, Jobs("vad", "f" * 64, {"models": {}, "model_cache": "x"}, ()))
        status, stdout, stderr = self.spawn(["-m", "kototoki.workers.vad", "--jobs", str(jobs_path)])
        self.assertEqual(status, EXIT_FATAL)
        self.assertEqual([event["event"] for event in stdout], ["startup_failed"])
        self.assertRegex(stderr[0], LOG_LINE)
        self.assertEqual(LOG_LINE.match(stderr[0]).groups(), ("ERROR", "startup failed: ValueError"))
        self.assertIn("Traceback (most recent call last):", stderr)


class GpuHelpersTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_read_wav_scales_pcm16_and_hashes_the_data_chunk(self):
        path = self.root / "a.wav"
        digest = write_wav(path, np.array([0, 16384, -32768], dtype=np.int16))
        audio, pcm_sha256 = gpu.read_wav(path)
        self.assertEqual(audio.dtype, np.float32)
        self.assertEqual(audio.tolist(), [0.0, 0.5, -1.0])
        self.assertEqual(pcm_sha256, digest)

    def test_read_wav_rejects_stereo(self):
        path = self.root / "stereo.wav"
        write_wav(path, np.zeros(4, dtype=np.int16), channels=2)
        with self.assertRaises(ValueError):
            gpu.read_wav(path)

    def test_verify_models_checks_and_caches_each_file(self):
        model = self.root / "model.bin"
        model.write_bytes(b"weights")
        digest = hashlib.sha256(b"weights").hexdigest()
        cache = self.root / "cache" / "model-verification.json"
        self.assertEqual(gpu.verify_models({"m": (model, digest)}, cache), {"m": digest})
        self.assertTrue(cache.is_file())
        with self.assertRaises(ValueError):
            gpu.verify_models({"m": (model, "0" * 64)}, cache)

    def test_model_file_lists_cover_pinned_assets(self):
        models = {"vad": "v/pytorch_model.bin", "w0": "w", "w0_mel_assets": "m", "x0": "x", "align": "a"}
        self.assertEqual(len(plan.model_files("vad", models)), 1)
        w0 = plan.model_files("asr", models, engine="w0")
        self.assertIn("faster-whisper-large-v3/model.bin", w0)
        self.assertEqual(w0["w0-assets/mel_filters.npz"][1], recipes.W0["features"]["mel_sha256"])
        self.assertIn("qwen3-asr-1.7b-hf/model.safetensors", plan.model_files("asr", models, engine="x0"))
        self.assertIn("mms-1b-all/adapter.jpn.safetensors", plan.model_files("align", models))

    def test_shells_hold_no_identity_of_their_own(self):
        for shell in (vad_worker, asr_worker, align_worker):
            for name in ("identity", "model_files", "recipe_hash", "RECIPE_HASH"):
                self.assertFalse(hasattr(shell, name), f"{shell.__name__}.{name}")


class ImportBoundaryTest(unittest.TestCase):
    def test_worker_shells_import_without_inference_libraries(self):
        code = ("import sys, kototoki.workers.vad, kototoki.workers.asr, kototoki.workers.align, kototoki.vad, "
                "kototoki.align, kototoki.schema\n"
                "print([m for m in ('torch', 'ctranslate2', 'faster_whisper', 'transformers', 'pyannote', "
                "'torchaudio', 'torchcodec') if m in sys.modules])")
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                                cwd=Path(__file__).resolve().parents[2])
        self.assertEqual(result.stdout.strip(), "[]")


if __name__ == "__main__":
    unittest.main()


class WorkerLoggerNameTest(unittest.TestCase):
    """三个 worker 壳以 `python -m kototoki.workers.<stage>` 运行时 `__name__` 是 `__main__`，
    若按 `__name__` 取 logger 就不在 `gpu.main` 设为 INFO 的 `kototoki` 之下，每文件 INFO 行会被丢弃
    （2026-10-19 cross 验收发现）；logger 名必须固定为 `kototoki.workers.<stage>`。"""

    def test_worker_loggers_are_under_kototoki(self):
        for module in (vad_worker, asr_worker, align_worker):
            self.assertEqual(module.logger.name, f"kototoki.workers.{module.STAGE}")

    def test_main_run_module_emits_info_under_kototoki(self):
        code = ("import logging, runpy, sys; sys.argv = ['x']; "
                "mod = runpy.run_module('kototoki.workers.asr', run_name='not_main'); "
                "print(mod['logger'].name)")
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, cwd=REPO,
                                env={**os.environ, "PYTHONUTF8": "1"}, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "kototoki.workers.asr")
