"""三个 STT worker 壳（`kototoki.workers.{vad,asr,align}`）与共用的 `workers.gpu`：伪推理对象，离线。

覆盖产物身份与坐标（壳写出的身份与阶段计划模块 `kototoki.plan` 给出的期望身份逐字段相等，壳自身不再持有
身份实现）、输入身份重验、`failed_windows` 记账、退出码 0／1／2、CUDA 守卫、三阶段串起来的 `align.json`
能被 `cues.build_cues` 消费，以及壳模块导入时不加载 torch。
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import wave

import numpy as np

from kototoki import artifacts, config, cues, plan, recipes
from kototoki.align import map_records
from kototoki.workers import align as align_worker
from kototoki.workers import asr as asr_worker
from kototoki.workers import gpu
from kototoki.workers import vad as vad_worker
from kototoki.workers.protocol import (EXIT_FATAL, EXIT_OK, EXIT_PARTIAL, FatalWorkerError, FileJob, Jobs,
                                       run_jobs, run_worker, write_jobs)

MODELS = {"vad": "a" * 64}
SAMPLES = 3 * 16000


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
        self.assertEqual(plan.recipe_hash("asr", "w0"), recipes.recipe_hash(recipes.W0))
        self.assertEqual(plan.recipe_hash("asr", "x0"), recipes.recipe_hash(recipes.X0))


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
            self.assertEqual(gpu.main(lambda jobs: (lambda job: None), ["--jobs", str(path)]), EXIT_OK)


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
        self.assertEqual(len(plan.model_files("vad", "w0", models)), 1)
        w0 = plan.model_files("asr", "w0", models)
        self.assertIn("faster-whisper-large-v3/model.bin", w0)
        self.assertEqual(w0["w0-assets/mel_filters.npz"][1], recipes.W0["features"]["mel_sha256"])
        self.assertIn("qwen3-asr-1.7b-hf/model.safetensors", plan.model_files("asr", "x0", models))
        self.assertIn("mms-1b-all/adapter.jpn.safetensors", plan.model_files("align", "w0", models))

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
                                cwd=Path(__file__).resolve().parent.parent)
        self.assertEqual(result.stdout.strip(), "[]")


if __name__ == "__main__":
    unittest.main()
