"""ASR worker：`python -m kototoki.workers.asr --jobs <path>`，逐文件写 `asr.json`。

按 `config.engine` 选择适配器（`w0` → `kototoki.asr_whisper`，`x0` → `kototoki.asr_qwen`），
两个适配器写出同一种 `asr.json`。jobs：`config` 需要 `engine`、`models`（w0 用 `w0`、
`w0_mel_assets`，x0 用 `x0`）与 `model_cache`；`inputs` 需要 `wav` 与 `vad`（`vad.json`）。

`asr.json`（坐标为 WAV 本地）：身份 = PCM SHA256＋`vad.json` SHA256＋引擎配方 hash＋模型文件 SHA256（取自 `kototoki.plan`）；
payload 为 `schema_version`、`engine`、`offset_s`、`input`、`chunks`（照抄 `vad.json`）、
`original_segments`（与窗口一一对应）、`asr_traces`、`failed_windows`（协议 `fail_window` 写法）、
保留文本 `text`、`metadata`、`stages`。本模块导入时不加载 torch／CT2，适配器在 `start` 里才导入。
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
from pathlib import Path
import sys
import time
from typing import Any

from kototoki import artifacts, plan
from kototoki.workers import gpu
from kototoki.workers.protocol import FileJob, Jobs, fail_window, retained_text, validate_failed_windows

STAGE = "asr"

logger = logging.getLogger(__name__)


def compute(asr: Any, engine: str, model_sha256: Mapping[str, str], load_s: float) -> gpu.Compute:
    def run(job: FileJob) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
        audio, pcm_sha256 = gpu.read_wav(job.inputs["wav"])
        vad, vad_sha256 = gpu.read_input_artifact(job.inputs["vad"], pcm_sha256)
        started = time.perf_counter()
        segments, traces, failures = asr.transcribe(audio, vad["chunks"])
        inference_s = time.perf_counter() - started
        document: dict[str, Any] = {
            "schema_version": 1, "engine": engine, "offset_s": vad["offset_s"], "input": vad["input"],
            "chunks": vad["chunks"], "original_segments": segments, "asr_traces": traces, "failed_windows": [],
        }
        for index, reason in failures:
            fail_window(document, index, reason)
            logger.warning("[%s] %s: window %d failed: %s", STAGE, job.id, index, reason)  # 不记窗口文字
        validate_failed_windows(document)
        document.update(text=retained_text(document), metadata=asr.metadata,
                        stages={"load_s": load_s, "inference_s": inference_s})
        fields = {"windows": len(segments), "failed_windows": len(failures)}
        logger.info("[%s] %s: %d window(s), %d failed, inference %.1fs",
                    STAGE, job.id, len(segments), len(failures), inference_s)
        return (job.work_dir / artifacts.ASR, plan.asr_identity(engine, pcm_sha256, vad_sha256, model_sha256),
                document, fields)
    return run


def start(jobs: Jobs) -> Any:
    engine, models = jobs.config["engine"], jobs.config["models"]
    gpu.require_recipe(jobs, plan.recipe_hash(STAGE, engine=engine))  # 引擎不可用即启动失败
    model_sha256 = gpu.verify_models(plan.model_files(STAGE, models, engine=engine), Path(jobs.config["model_cache"]))
    logger.info("[%s] engine %s: verified %d model file(s)", STAGE, engine, len(model_sha256))
    started = time.perf_counter()
    if engine == "x0":
        from kototoki.asr_qwen import QwenAsr

        asr: Any = QwenAsr(Path(models["x0"]))
    else:
        from kototoki.asr_whisper import WhisperAsr

        asr = WhisperAsr(Path(models["w0"]), Path(models["w0_mel_assets"]))
    load_s = time.perf_counter() - started
    logger.info("[%s] model loaded in %.1fs", STAGE, load_s)
    return gpu.file_processor(compute(asr, engine, model_sha256, load_s))


if __name__ == "__main__":
    sys.exit(gpu.main(start))
