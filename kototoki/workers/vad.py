"""VAD worker：`python -m kototoki.workers.vad --jobs <path>`，逐文件写 `vad.json`。

jobs：`config` 需要 `models.vad`（segmentation-3.0 checkpoint 路径）与 `model_cache`
（`model-verification.json` 路径）；每个文件的 `inputs` 需要 `wav`（`audio-16k.wav`）。
`vad.json`（坐标为 WAV 本地）：身份 = PCM SHA256＋VAD 配方 hash＋checkpoint SHA256；
payload 为 `schema_version`、`offset_s`、`input`、`chunks`（整数样本窗口与子段）、
`raw_intervals`／`speech_intervals`／`accounting`、`metadata`、`stages`。
本模块导入时不加载 torch；推理模块在 `start` 里才导入。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import sys
import time
from typing import Any

from kototoki import artifacts, recipes
from kototoki.schema import validate_windows
from kototoki.workers import gpu
from kototoki.workers.protocol import FileJob, Jobs

RECIPE_HASH = recipes.recipe_hash(recipes.VAD)
CHECKPOINT_SHA256 = "da85c29829d4002daedd676e012936488234d9255e65e86dfab9bec6b1729298"


def model_files(models: Mapping[str, str]) -> dict[str, tuple[Path, str]]:
    return {"pyannote-segmentation-3.0/pytorch_model.bin": (Path(models["vad"]), CHECKPOINT_SHA256)}


def identity(pcm_sha256: str, model_sha256: Mapping[str, str]) -> dict[str, Any]:
    return artifacts.derived_identity(upstream={artifacts.AUDIO_16K: pcm_sha256},
                                      recipe_hash=RECIPE_HASH, models=model_sha256)


def compute(vad: Any, model_sha256: Mapping[str, str], load_s: float) -> gpu.Compute:
    def run(job: FileJob) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
        audio, pcm_sha256 = gpu.read_wav(job.inputs["wav"])
        started = time.perf_counter()
        chunks, accounting = vad.segment(audio)
        inference_s = time.perf_counter() - started
        validate_windows(chunks, len(audio))
        payload = {
            "schema_version": 1, "offset_s": recipes.MEDIA["offset_s"],
            "input": {"pcm_sha256": pcm_sha256, "samples": len(audio), "sample_rate": gpu.SAMPLE_RATE,
                      "duration_s": len(audio) / gpu.SAMPLE_RATE},
            "chunks": chunks, **accounting, "metadata": vad.metadata,
            "stages": {"load_s": load_s, "inference_s": inference_s},
        }
        return job.work_dir / artifacts.VAD, identity(pcm_sha256, model_sha256), payload, {"windows": len(chunks)}
    return run


def start(jobs: Jobs) -> Any:
    gpu.require_recipe(jobs, RECIPE_HASH)
    models = jobs.config["models"]
    model_sha256 = gpu.verify_models(model_files(models), Path(jobs.config["model_cache"]))
    from kototoki.vad import PyannoteVad

    started = time.perf_counter()
    vad = PyannoteVad(Path(models["vad"]))
    return gpu.file_processor(compute(vad, model_sha256, time.perf_counter() - started))


if __name__ == "__main__":
    sys.exit(gpu.main(start))
