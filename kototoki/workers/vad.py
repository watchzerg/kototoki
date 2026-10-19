"""VAD worker：`python -m kototoki.workers.vad --jobs <path>`，逐文件写 `vad.json`。

jobs：`config` 需要 `models.vad`（segmentation-3.0 checkpoint 路径）与 `model_cache`
（`model-verification.json` 路径）；每个文件的 `inputs` 需要 `wav`（`audio-16k.wav`）。
`vad.json`（坐标为 WAV 本地）：身份 = PCM SHA256＋VAD 配方 hash＋checkpoint SHA256（取自 `kototoki.plan`）；
payload 为 `schema_version`、`offset_s`、`input`、`chunks`（整数样本窗口与子段）、
`raw_intervals`／`speech_intervals`／`accounting`、`metadata`、`stages`。
本模块导入时不加载 torch；推理模块在 `start` 里才导入。
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
from pathlib import Path
import sys
import time
from typing import Any

from kototoki import artifacts, plan, recipes
from kototoki.schema import validate_windows
from kototoki.workers import gpu
from kototoki.workers.protocol import FileJob, Jobs

STAGE = "vad"

logger = logging.getLogger(f"kototoki.workers.{STAGE}")  # 以 `python -m` 运行时 __name__ 是 __main__，不在 INFO 级的 kototoki 之下


def compute(vad: Any, model_sha256: Mapping[str, str], load_s: float) -> gpu.Compute:
    def run(job: FileJob) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
        audio, pcm_sha256 = gpu.read_wav(job.inputs["wav"])
        started = time.perf_counter()
        chunks, accounting = vad.segment(audio)
        inference_s = time.perf_counter() - started
        validate_windows(chunks, len(audio))
        logger.info("[%s] %s: %d window(s), inference %.1fs", STAGE, job.id, len(chunks), inference_s)
        payload = {
            "schema_version": 1, "offset_s": recipes.MEDIA["offset_s"],
            "input": {"pcm_sha256": pcm_sha256, "samples": len(audio), "sample_rate": gpu.SAMPLE_RATE,
                      "duration_s": len(audio) / gpu.SAMPLE_RATE},
            "chunks": chunks, **accounting, "metadata": vad.metadata,
            "stages": {"load_s": load_s, "inference_s": inference_s},
        }
        return job.work_dir / artifacts.VAD, plan.vad_identity(pcm_sha256, model_sha256), payload, {"windows": len(chunks)}
    return run


def start(jobs: Jobs) -> Any:
    gpu.require_recipe(jobs, plan.recipe_hash(STAGE))
    models = jobs.config["models"]
    model_sha256 = gpu.verify_models(plan.model_files(STAGE, models), Path(jobs.config["model_cache"]))
    logger.info("[%s] verified %d model file(s)", STAGE, len(model_sha256))
    from kototoki.vad import PyannoteVad

    started = time.perf_counter()
    vad = PyannoteVad(Path(models["vad"]))
    load_s = time.perf_counter() - started
    logger.info("[%s] model loaded in %.1fs", STAGE, load_s)
    return gpu.file_processor(compute(vad, model_sha256, load_s))


if __name__ == "__main__":
    sys.exit(gpu.main(start))
