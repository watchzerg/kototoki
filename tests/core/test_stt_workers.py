"""三个 STT worker 壳（`kototoki.workers.{vad,asr,align}`）与共用的 `workers.gpu`：伪推理对象，离线。

覆盖产物身份与坐标（壳写出的身份与 `kototoki.plan` 给出的期望身份相等）、输入身份重验、`failed_windows` 记账、
复读守卫接线且日志不含窗口文字、CUDA 守卫退出码 2、三阶段串起来的 `align.json` 能被 `cues.build_cues` 消费、
cross 引擎的产物与裁判切换，以及壳模块导入时不加载 torch。
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
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
                                       run_jobs)

MODELS = {"vad": "a" * 64}
SAMPLES = 3 * 16000
REPEATED = "まって、" + "うっ…" * 22 + "だめ。"   # 相邻重复 22 份：守卫折叠
COLLAPSED = "まって、うっ…だめ。"


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

    def test_vad_from_other_audio_fails_the_file(self):
        self.run_vad()
        write_wav(self.wav, np.zeros(SAMPLES, dtype=np.int16))
        self.assertEqual(self.run_asr(), EXIT_PARTIAL)
        self.assertFalse((self.work_dir / artifacts.ASR).exists())
        self.assertEqual(artifacts.read_json(self.work_dir / artifacts.FAILURE)["stage"], "stage")



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



class GpuHelpersTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_verify_models_checks_and_caches_each_file(self):
        model = self.root / "model.bin"
        model.write_bytes(b"weights")
        digest = hashlib.sha256(b"weights").hexdigest()
        cache = self.root / "cache" / "model-verification.json"
        self.assertEqual(gpu.verify_models({"m": (model, digest)}, cache), {"m": digest})
        self.assertTrue(cache.is_file())
        with self.assertRaises(ValueError):
            gpu.verify_models({"m": (model, "0" * 64)}, cache)

    def test_read_wav_normalizes_pcm16_to_float32_with_sha256(self):
        wav = self.root / "audio.wav"
        expected_sha256 = write_wav(wav, np.array([-32768, 0, 32767], dtype="<i2"))
        waveform, pcm_sha256 = gpu.read_wav(wav)
        self.assertEqual(waveform.dtype, np.float32)
        np.testing.assert_array_equal(waveform, np.array([-1.0, 0.0, 32767 / 32768.0], dtype=np.float32))
        self.assertEqual(pcm_sha256, expected_sha256)


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
