"""三个 STT worker 壳（`kototoki.workers.{vad,asr,align}`）与共用的 `workers.gpu`：伪推理对象，离线。

覆盖产物身份与坐标（壳写出的身份与阶段计划模块 `kototoki.plan` 给出的期望身份逐字段相等，壳自身不再持有
身份实现）、输入身份重验、`failed_windows` 记账、退出码 0／1／2、CUDA 守卫、三阶段串起来的 `align.json`
能被 `cues.build_cues` 消费、worker 进程的 stderr 日志与 stdout 协议行分离，以及壳模块导入时不加载 torch。
cross 引擎（伪 Whisper／Qwen）：四个产物、裁判切换与 margin 边界、相同窗口不打分、两路失败窗口与打分出错的处理、
x0 空白清理、合并结果被 align 消费、启动时先 Whisper 后 Qwen；`asr.json` 与三个审计产物的字节钉成改动前的 sha256。
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
import warnings
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
REPEATED = "まって、" + "うっ…" * 22 + "だめ。"   # 相邻重复 22 份：守卫折叠
COLLAPSED = "まって、うっ…だめ。"
RECURRING = "".join(f"たすけ{index}" for index in range(10))  # 只有非相邻复现：守卫置空


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

    def align(self, audio, segments):
        records = []
        for index, segment in enumerate(segments):
            count = len(segment["text"])
            records.append({"segment_index": index, "window_start": segment["start"], "window_end": segment["end"],
                            "frame_count": 50, "failure": None,
                            "tokens": [{"original_position": p, "lexical_interval_accepted": True,
                                        "evidence_kind": "vocabulary_token", "start_frame": 5 * p,
                                        "end_frame": 5 * p + 4, "token_probability": 0.9} for p in range(count)]})
        return map_records(segments, records)


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

    def run_asr(self, asr=None, engine="w0") -> int:
        return self.run_stage(asr_worker.compute(asr or FakeAsr(), engine, MODELS, 2.0),
                              {"wav": self.wav, "vad": self.work_dir / artifacts.VAD})

    def run_cross(self, whisper, qwen) -> int:
        compute = asr_worker.compute_cross(whisper, qwen, CROSS_SHA, W0_SHA, X0_SHA, LOADS)
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
        self.assertEqual(self.progress()[-1]["guarded_windows"], 0)

    def test_guard_collapses_a_repeated_window_and_records_the_trace(self):
        self.run_vad()
        with self.assertLogs("kototoki.workers", "INFO") as logs:
            self.assertEqual(self.run_asr(FakeEngine("w0", ("こんにちは。", REPEATED, "はい"))), EXIT_OK)
        document = artifacts.read_json(self.work_dir / artifacts.ASR)
        validate_transcript(document)
        self.assertEqual([s["text"] for s in document["original_segments"]], ["こんにちは。", COLLAPSED, "はい"])
        self.assertEqual(document["text"], "こんにちは。" + COLLAPSED + "はい")
        self.assertEqual(document["failed_windows"], [])
        self.assertEqual(document["asr_traces"], [
            {"window": 0},
            {"window": 1, "guard": {"rule": "repeat-strict", "action": "collapse", "period": 2, "copies": 22,
                                    "removed_raw_chars": 63}},
            {"window": 2}])
        self.assertEqual(self.progress()[-1], {"windows": 3, "failed_windows": 0, "guarded_windows": 1,
                                               "event": "done", "id": "0123456789ab"})
        output = "\n".join(logs.output)
        self.assertIn("WARNING:kototoki.workers.asr:[asr] 0123456789ab: window 1 guard repeat-strict collapsed: "
                      "period 2, copies 22, removed 63 chars", output)
        self.assertIn("3 window(s), 0 failed, 1 guarded, inference ", output)
        for text in ("うっ", "まって", "だめ"):
            self.assertNotIn(text, output)

    def test_guard_blanks_a_window_it_cannot_collapse(self):
        self.run_vad()
        asr = FakeEngine("w0", (REPEATED, RECURRING, "はい"), [(0, "RuntimeError: boom")])
        with self.assertLogs("kototoki.workers", "INFO") as logs:
            self.assertEqual(self.run_asr(asr), EXIT_OK)
        document = artifacts.read_json(self.work_dir / artifacts.ASR)
        validate_transcript(document)
        self.assertEqual(document["text"], "はい")
        self.assertEqual(document["failed_windows"], [  # 已失败的窗口不过守卫，保留原因与原文
            {"chunk_index": 0, "reason": "RuntimeError: boom", "text": REPEATED},
            {"chunk_index": 1, "reason": "guard:repeat-strict", "text": RECURRING}])
        self.assertEqual(document["asr_traces"][0], {"window": 0})
        self.assertEqual(document["asr_traces"][1]["guard"], {"rule": "repeat-strict", "action": "blank",
                                                              "period": None, "copies": None, "removed_raw_chars": 0})
        self.assertEqual((self.progress()[-1]["failed_windows"], self.progress()[-1]["guarded_windows"]), (2, 1))
        output = "\n".join(logs.output)
        self.assertIn("[asr] 0123456789ab: window 1 failed: guard:repeat-strict", output)
        self.assertNotIn("たすけ", output)

    def test_guard_blanks_impossible_speech_rate_and_hallucination_phrase(self):  # ADR-0030
        self.run_vad()
        fast = "今日は良い天気なので外へ出かけて買い物をします"  # 规范化 23 字，窗口 1 s
        asr = FakeEngine("w0", (fast, "ご視聴ありがとうございました。", "はい"))
        with self.assertLogs("kototoki.workers", "INFO") as logs:
            self.assertEqual(self.run_asr(asr), EXIT_OK)
        document = artifacts.read_json(self.work_dir / artifacts.ASR)
        validate_transcript(document)
        self.assertEqual(document["text"], "はい")
        self.assertEqual(document["failed_windows"], [
            {"chunk_index": 0, "reason": "guard:speech-rate", "text": fast},
            {"chunk_index": 1, "reason": "guard:hallucination-phrase", "text": "ご視聴ありがとうございました。"}])
        self.assertEqual(document["asr_traces"][0]["guard"], {"rule": "speech-rate", "action": "blank", "chars": 23,
                                                              "duration_s": 1.0})
        self.assertEqual(document["asr_traces"][1]["guard"], {"rule": "hallucination-phrase", "action": "blank",
                                                              "phrase_index": 0})
        self.assertEqual((self.progress()[-1]["failed_windows"], self.progress()[-1]["guarded_windows"]), (2, 2))
        output = "\n".join(logs.output)
        self.assertIn("[asr] 0123456789ab: window 0 failed: guard:speech-rate", output)
        self.assertIn("[asr] 0123456789ab: window 1 failed: guard:hallucination-phrase", output)
        for text in ("天気", "視聴"):
            self.assertNotIn(text, output)

    def test_x0_engine_is_not_guarded(self):
        self.run_vad()
        self.assertEqual(self.run_asr(FakeEngine("x0", (REPEATED, RECURRING, "はい")), engine="x0"), EXIT_OK)
        document = artifacts.read_json(self.work_dir / artifacts.ASR)
        self.assertEqual(document["text"], REPEATED + RECURRING + "はい")
        self.assertEqual(document["asr_traces"], [{"window": 0}, {"window": 1}, {"window": 2}])
        self.assertEqual(document["failed_windows"], [])
        self.assertEqual(self.progress()[-1]["guarded_windows"], 0)

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
        self.assertEqual(self.progress()[-1], {"windows": 3, "failed_windows": 0, "guarded_windows": 0,
                                               "identical": 1, "intervals": 1,
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

    def test_guard_runs_on_the_w0_path_only_and_the_judge_sees_guarded_text(self):
        # 窗口 0：w0 复读被折叠，x0 给出另一种写法并被裁判选中；窗口 1：w0 置空，不以 x0 替代；
        # 窗口 2：x0 自己复读，x0 那一路不过守卫（裁判照常比较）。
        other = COLLAPSED.replace("だめ", "ダメ")
        whisper = FakeWhisper((REPEATED, RECURRING, "はい"), scores={other: -9.5, "はい": 0.0})
        qwen = self.qwen(texts=(other, "たすけて", "はい" + "うっ" * 22), failures=())
        with self.assertLogs("kototoki.workers", "INFO") as logs:
            self.assertEqual(self.run_cross(whisper, qwen), EXIT_OK)
        w0 = self.read(artifacts.ASR_W0)
        self.assertEqual([s["text"] for s in w0["original_segments"]], [COLLAPSED, "", "はい"])
        self.assertEqual(w0["asr_traces"][0]["guard"]["action"], "collapse")
        self.assertEqual(w0["failed_windows"], [{"chunk_index": 1, "reason": "guard:repeat-strict",
                                                 "text": RECURRING}])
        x0 = self.read(artifacts.ASR_X0)
        self.assertEqual(x0["original_segments"][2]["text"], "はい" + "うっ" * 22)
        self.assertEqual(x0["asr_traces"], [{"window": 0}, {"window": 1}, {"window": 2}])
        self.assertEqual(whisper.calls[0], (0, [COLLAPSED, other], 16))  # hyp_w 是守卫后的 w0 文字
        audit = self.read(artifacts.ASR_JUDGE)
        self.assertEqual([w["decision"] for w in audit["windows"]], ["judged", "w0_failed", "judged"])
        self.assertEqual(audit["windows"][0]["w0_text"], COLLAPSED)
        document = self.read(artifacts.ASR)
        validate_transcript(document)
        self.assertEqual([s["text"] for s in document["original_segments"]], [other, "", "はい"])
        self.assertEqual(document["failed_windows"], w0["failed_windows"])
        self.assertEqual(document["asr_traces"], w0["asr_traces"])
        self.assertEqual((self.progress()[-1]["failed_windows"], self.progress()[-1]["guarded_windows"]), (1, 2))
        output = "\n".join(logs.output)
        self.assertIn("window 0 guard repeat-strict collapsed: period 2, copies 22, removed 63 chars", output)
        self.assertIn("w0 window 1 failed: guard:repeat-strict", output)
        self.assertIn("score_error 0, guarded 2, w0 ", output)
        for text in ("うっ", "たすけ", "だめ", "ダメ"):
            self.assertNotIn(text, output)

    def test_score_error_keeps_w0_and_logs_no_text(self):
        whisper = FakeWhisper(("こんにちは。", SECRET, "はい"),
                              error="align returned a different number of results than texts")
        qwen = self.qwen(texts=("こんにちは", "ひみつのまど", "はい"), failures=())
        with self.assertLogs("kototoki.workers", "INFO") as logs:
            self.assertEqual(self.run_cross(whisper, qwen), EXIT_OK)
        output = "\n".join(logs.output)
        self.assertIn("[asr] 0123456789ab: window 1 score error, keeping w0: RuntimeError: align returned", output)
        self.assertIn("[asr] 0123456789ab: cross windows 3, identical 2, intervals 0, switched 0, x0_failed 0, "
                      "score_error 1, guarded 0, w0 ", output)
        for text in (SECRET, "ひみつのまど", "こんにちは", "はい"):
            self.assertNotIn(text, output)
        document = self.read(artifacts.ASR)
        self.assertEqual(document["original_segments"][1]["text"], SECRET)
        self.assertEqual(document["failed_windows"], [])
        self.assertEqual(document["metadata"]["judge"]["score_error"], 1)
        self.assertEqual(self.read(artifacts.ASR_JUDGE)["windows"][1]["decision"], "score_error")

    def test_failure_after_the_w0_pass_writes_no_artifact(self):
        class Broken(FakeEngine):
            def transcribe(self, audio, chunks):
                raise TypeError("qwen broke")
        self.assertEqual(self.run_cross(FakeWhisper(W0_TEXTS), Broken("x0", ())), EXIT_PARTIAL)
        for name in (artifacts.ASR, artifacts.ASR_W0, artifacts.ASR_X0, artifacts.ASR_JUDGE):
            self.assertFalse((self.work_dir / name).exists(), name)

    def test_score_count_mismatch_is_a_score_error(self):
        class Short(FakeWhisper):
            def score(self, audio, chunk, texts, max_batch=16):
                return super().score(audio, chunk, texts, max_batch)[:1]
        self.assertEqual(self.run_cross(Short(W0_TEXTS), self.qwen()), EXIT_OK)
        document = self.read(artifacts.ASR)
        self.assertEqual(document["text"], "こんにちは。元気？はい")
        self.assertEqual(document["metadata"]["judge"]["score_error"], 1)


CROSS_OTHER = COLLAPSED.replace("だめ", "ダメ")
# 四个 cross 场景（同上面各测试的夹具）与两个单引擎场景。
BYTE_SCENARIOS = {
    "switch": lambda: (FakeWhisper(W0_TEXTS, scores={"げんき？": -9.5}),
                       FakeEngine("x0", ("こんにちは", "げん き？", "ええ"), X0_TOKEN_LIMIT)),
    "w0_failed": lambda: (FakeWhisper(W0_TEXTS, failures=[(1, "RuntimeError: boom")], scores={"げんき？": 0.0}),
                          FakeEngine("x0", ("こんにちは", "げんき？", "はい"), ())),
    "guard": lambda: (FakeWhisper((REPEATED, RECURRING, "はい"), scores={CROSS_OTHER: -9.5, "はい": 0.0}),
                      FakeEngine("x0", (CROSS_OTHER, "たすけて", "はい" + "うっ" * 22), ())),
    "score_error": lambda: (FakeWhisper(("こんにちは。", SECRET, "はい"), error="align returned a different number"),
                            FakeEngine("x0", ("こんにちは", "ひみつのまど", "はい"), ())),
}
# 2026-11-11 架构整理票据 06 改动前（提交 c04f21d）的代码在这些夹具上写出的产物字节 sha256，
# `time.perf_counter` 固定为 0.0（`stages`、`score_s` 是墙钟）。重构不得改变任何一个。
PINNED_ASR_BYTES = {
    "switch": {"asr.json": "5619cd4dc6a017c604e1e4b946c5acba1944671dc25029f82448b3d944d632ed",
               "asr-w0.json": "0f4193b888352782e882657adc10907d6e31f5b3bdb14f9198968bef998e6e5e",
               "asr-x0.json": "9d6440c199073ee87a5be7e9860d1159004e7bccb20c93a225aed4cfa2a0f691",
               "asr-judge.json": "7d61df0753d04be0ac094eec52dd013cd8d9f8468e6363f6cfcb2872d64d11c0"},
    "w0_failed": {"asr.json": "5b2b8f713c07864f03648bdbe702c8854ec73cd1bcc5bb3a0a7e5ab3efa84d77",
                  "asr-w0.json": "a5011aa3d33f1dccaa207954ee26af3956385fd04b1c9017082ceb82e9b0c802",
                  "asr-x0.json": "ea2aa241a794e3bd57ad2e469b596d64cf14bea24d4277462b9db94afa4f579a",
                  "asr-judge.json": "f28c3cd744285b3537ff2da04c28541ed8014885cf72dcd17a7807ae87fc1a8f"},
    "guard": {"asr.json": "9e047f427ebceeabc0683826798388ad0594f8570003468bcf83ae6ffd46cf78",
              "asr-w0.json": "48526ef4022cec162f7afd0e38914b9807d8f94a66a7cf22e9dad0d620491c56",
              "asr-x0.json": "d9f45b6263b3115eeb54087de5bfec6b9ebfe93d273e0dc7ccc069fa5b9bc7ce",
              "asr-judge.json": "fd540668ec831c2f4ef595cc866aebadb33a61162a63a28dc0d5d7c5cfc5af07"},
    "score_error": {"asr.json": "e198a645ddee38d781a75565df7376c37cb6895e0590a39ead35fd6a5113d94c",
                    "asr-w0.json": "475617ca100896c490056e1874a1171d1bef57c6d6209ed851eae7c85cae28ec",
                    "asr-x0.json": "6bff8762369cd17250f8305ea0b310a3769f58c849eb347900d54cb91e21bcad",
                    "asr-judge.json": "2fb6ef36d0b3c8ba2ad9bea02cecad8294daae1c776eb2fce8347f7997f9a1b1"},
    "w0": "ac6a9e4acbd230545fef788a78d3e50cabd94272aa538f6e0d16ad05228a2d2f",
    "x0": "9d8561a7ac2eaac4877319ebcbce42f362b16e97317717b8e1429821aba22ee4",
}


class AsrArtifactBytesTest(WorkerTestCase):
    """`asr.json` 与三个 cross 审计产物的字节在重构前后不变（计划 architecture-cleanup §3 第 9 条）。"""

    def digest(self, name):
        return hashlib.sha256((self.work_dir / name).read_bytes()).hexdigest()

    def test_cross_artifacts_are_byte_identical_to_the_pinned_output(self):
        names = (artifacts.ASR, artifacts.ASR_W0, artifacts.ASR_X0, artifacts.ASR_JUDGE)
        with mock.patch("time.perf_counter", return_value=0.0):
            for scenario, make in BYTE_SCENARIOS.items():
                with self.subTest(scenario=scenario):
                    for name in names:
                        (self.work_dir / name).unlink(missing_ok=True)
                    self.run_vad()
                    self.assertEqual(self.run_cross(*make()), EXIT_OK)
                    self.assertEqual({name: self.digest(name) for name in names}, PINNED_ASR_BYTES[scenario])

    def test_single_engine_asr_is_byte_identical_to_the_pinned_output(self):
        engines = {"w0": FakeEngine("w0", ("こんにちは。", REPEATED, RECURRING), [(0, "RuntimeError: boom")]),
                   "x0": FakeEngine("x0", (REPEATED, "げん き？", "ええ"), X0_TOKEN_LIMIT)}
        with mock.patch("time.perf_counter", return_value=0.0):
            for engine, asr in engines.items():
                with self.subTest(engine=engine):
                    (self.work_dir / artifacts.ASR).unlink(missing_ok=True)
                    self.run_vad()
                    self.assertEqual(self.run_asr(asr, engine=engine), EXIT_OK)
                    self.assertEqual(self.digest(artifacts.ASR), PINNED_ASR_BYTES[engine])


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
        models = {"w0": "w", "x0": "x"}
        jobs = Jobs("asr", plan.recipe_hash("asr", engine="cross"),
                    {"engine": "cross", "models": models, "model_cache": "cache"}, ())
        verified = {name: "e" * 64 for name in plan.model_files("asr", models, engine="cross")}
        with mock.patch.dict(sys.modules, {"kototoki.asr_whisper": whisper_module, "kototoki.asr_qwen": qwen_module}), \
                mock.patch.object(gpu, "verify_models", return_value=verified), \
                mock.patch.object(asr_worker, "compute_cross", wraps=asr_worker.compute_cross) as compute, \
                self.assertLogs("kototoki.workers.asr", "INFO"):
            asr_worker.start(jobs)
        self.assertEqual(order, [("w0", (Path("w"),)), ("x0", (Path("x"),))])
        _, _, model_sha256, w0_sha256, x0_sha256, loads = compute.call_args.args
        self.assertEqual(model_sha256, verified)
        self.assertEqual(set(w0_sha256), set(plan.model_files("asr", models, engine="w0")))
        self.assertEqual(set(x0_sha256), set(plan.model_files("asr", models, engine="x0")))
        self.assertEqual(set(loads), {"load_s", "load_w0_s", "load_x0_s"})

    def test_single_engine_loads_only_its_own_part(self):
        for engine, models, expected in (("w0", {"w0": "w"}, [("w0", (Path("w"),))]),
                                         ("x0", {"x0": "x"}, [("x0", (Path("x"),))])):
            with self.subTest(engine=engine):
                order = []

                def adapter(name):
                    def init(self, *paths):
                        order.append((name, paths))
                        self.metadata = {}
                    return type(name, (), {"__init__": init})
                whisper_module, qwen_module = (types.ModuleType("kototoki.asr_whisper"),
                                               types.ModuleType("kototoki.asr_qwen"))
                whisper_module.WhisperAsr, qwen_module.QwenAsr = adapter("w0"), adapter("x0")
                jobs = Jobs("asr", plan.recipe_hash("asr", engine=engine),
                            {"engine": engine, "models": models, "model_cache": "cache"}, ())
                verified = {name: "e" * 64 for name in plan.model_files("asr", models, engine=engine)}
                with mock.patch.dict(sys.modules, {"kototoki.asr_whisper": whisper_module,
                                                   "kototoki.asr_qwen": qwen_module}), \
                        mock.patch.object(gpu, "verify_models", return_value=verified), \
                        mock.patch.object(asr_worker, "compute", wraps=asr_worker.compute) as compute, \
                        self.assertLogs("kototoki.workers.asr", "INFO") as logs:
                    asr_worker.start(jobs)
                self.assertEqual(order, expected)
                self.assertEqual(compute.call_args.args[1:3], (engine, verified))
                self.assertTrue(any(line.startswith("INFO:kototoki.workers.asr:[asr] model loaded in ")
                                    for line in logs.output), logs.output)


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
            def align(self, audio, segments):
                result = super().align(audio, segments)
                return {**result, "text": result["text"][:-1]}
        self.run_vad()
        self.run_asr()
        status = self.run_stage(align_worker.compute(Lossy(), MODELS, 0),
                                {"wav": self.wav, "asr": self.work_dir / artifacts.ASR})
        self.assertEqual(status, EXIT_PARTIAL)
        self.assertFalse((self.work_dir / artifacts.ALIGN).exists())


# 2026-11-11 架构整理票据 08 改动前（票据 06 提交之上、offset 仍由对齐加）的代码在 offset 0 的整链夹具上写出的字节
# sha256：`align.json`、`ja-cues.json`（payload 以固定身份 {"fixed": 1} 写出）与 `ja.srt`；`time.perf_counter` 固定为 0.0。
PINNED_CUE_CHAIN_BYTES = {
    "w0": {"align.json": "18e62d0285ac2bc89c05c90351f875e5a4be0912ba7ad94f02120cd61f348df3",
           "ja-cues.json": "f3736e25d8c364e29f9679b3874acae9938b941f66b151e42722927ba025131e",
           "ja.srt": "ea77acfaa498939d0c3d4fe1a42a22da36e21293aaeb738df053df626c17ca94"},
    "cross": {"align.json": "161490389d52b876cb1bba3acc245427a9f08b5f533b9e39dba429c0996f840a",
              "ja-cues.json": "fc6469779d1131b0b5c8b3b814b177de6bff13bfbe66aba551ab80024e3e27b4",
              "ja.srt": "b75439e16c5e0172164e2561d7c0758f7921e8cfe4d7908757813bc7dad04615"},
}


class CueChainBytesTest(WorkerTestCase):
    """offset 为 0 时 `align.json`、`ja-cues.json`、`ja.srt` 的字节在 offset 挪到 cue 前后不变（计划 §3 第 9 条）。"""

    def test_align_and_cue_outputs_are_byte_identical_to_the_pinned_output(self):
        scenarios = {
            "w0": lambda: self.run_asr(FakeAsr(failures=[(1, "RuntimeError: boom")])),
            "cross": lambda: self.run_cross(*BYTE_SCENARIOS["switch"]()),
        }
        with mock.patch("time.perf_counter", return_value=0.0):
            for name, run_asr in scenarios.items():
                with self.subTest(scenario=name):
                    for artifact in (artifacts.ASR, artifacts.ALIGN):
                        (self.work_dir / artifact).unlink(missing_ok=True)
                    self.run_vad()
                    self.assertEqual(run_asr(), EXIT_OK)
                    self.assertEqual(self.run_align(), EXIT_OK)
                    payload, srt_text = cues.build_cues(artifacts.read_json(self.work_dir / artifacts.ALIGN),
                                                        config.DEFAULTS["cues"])
                    path = self.root / "ja-cues.json"
                    artifacts.write_artifact(path, {"fixed": 1}, payload)
                    digests = {"align.json": hashlib.sha256((self.work_dir / artifacts.ALIGN).read_bytes()).hexdigest(),
                               "ja-cues.json": hashlib.sha256(path.read_bytes()).hexdigest(),
                               "ja.srt": hashlib.sha256(srt_text.encode("utf-8")).hexdigest()}
                    self.assertEqual(digests, PINNED_CUE_CHAIN_BYTES[name])


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
                                                                   "0 guarded, inference ")
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
        self.assertEqual(LOG_LINE.match(stderr[0]).groups(), ("ERROR", "[vad] startup failed: ValueError"))
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
        models = {"vad": "v/pytorch_model.bin", "w0": "w", "x0": "x", "align": "a"}
        self.assertEqual(len(plan.model_files("vad", models)), 1)
        w0 = plan.model_files("asr", models, engine="w0")
        self.assertIn("faster-whisper-large-v3/model.bin", w0)
        self.assertEqual(len(w0), len(plan.W0_FILES))
        self.assertIn("qwen3-asr-1.7b-hf/model.safetensors", plan.model_files("asr", models, engine="x0"))
        self.assertIn("mms-1b-all/adapter.jpn.safetensors", plan.model_files("align", models))

    def test_file_processor_checks_cuda_once_then_writes_every_output_in_order(self):
        written, checks = [], []
        outputs = [(self.root / name, {"n": index}, {"offset_s": 0}) for index, name in enumerate(("a.json", "b.json"))]
        with mock.patch.object(artifacts, "write_artifact", side_effect=lambda path, *_: written.append(path.name)):
            fields = gpu.file_processor(lambda job: (outputs, {"windows": 2}),
                                        check=lambda: checks.append(list(written)))(None)
        self.assertEqual((fields, written, checks), ({"windows": 2}, ["a.json", "b.json"], [[]]))

    def test_file_processor_writes_nothing_when_cuda_is_broken(self):
        def broken():
            raise FatalWorkerError("CUDA context is unusable")
        outputs = [(self.root / "a.json", {}, {}), (self.root / "b.json", {}, {})]
        with self.assertRaises(FatalWorkerError):
            gpu.file_processor(lambda job: (outputs, {}), check=broken)(None)
        self.assertEqual(list(self.root.iterdir()), [])

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


class ReproducibilityWarning(UserWarning):
    """与 pyannote.audio.utils.reproducibility 的同名类同构（UserWarning 子类）；测试不导入 pyannote。"""


# 文字取自 2026-11-09 真实 vad 运行的 stderr（pyannote `fix_reproducibility`）。
TF32_MESSAGE = ("TensorFloat-32 (TF32) has been disabled as it might lead to reproducibility issues and lower accuracy.\n"
                "It can be re-enabled by calling\n")


class KnownWarningFilterTest(unittest.TestCase):
    def test_only_the_tf32_notice_is_dropped(self):
        with warnings.catch_warnings():
            warnings.simplefilter("always")
            gpu.quiet_known_warnings()
            logging.captureWarnings(True)
            try:
                with self.assertLogs("py.warnings", "WARNING") as logs:
                    warnings.warn(ReproducibilityWarning(TF32_MESSAGE))
                    warnings.warn("TensorFloat-32 (TF32) has been disabled", DeprecationWarning)  # 类别不符，保留
                    warnings.warn("some other notice", UserWarning)
            finally:
                logging.captureWarnings(False)
        messages = [record.getMessage() for record in logs.records]
        self.assertEqual(len(messages), 2, messages)
        self.assertIn("DeprecationWarning", messages[0])
        self.assertIn("UserWarning: some other notice", messages[1])
