"""对齐 worker：`python -m kototoki.workers.align --jobs <path>`，逐文件写 `align.json`。

jobs：`config` 需要 `models.align`（`mms-1b-all` 目录）与 `model_cache`；`inputs` 需要 `wav` 与 `asr`（`asr.json`）。
`align.json` 是现有 W0 `result.json` 的结构（`validate_transcript` 与 `validate_units` 通过）：身份 =
PCM SHA256＋`asr.json` SHA256＋MMS 配方 hash＋模型文件 SHA256（取自 `kototoki.plan`）；窗口、段与对齐记录是 WAV 本地秒，
只有 `units[].start/end` 含 `offset_s`（产品恒为 0）。`failed_windows` 从 `asr.json` 照抄，
失败窗口的保留文本为空，不参与对齐。本模块导入时不加载 torch，推理模块在 `start` 里才导入。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import sys
import time
from typing import Any

from kototoki import artifacts, plan
from kototoki.schema import validate_transcript, validate_units
from kototoki.workers import gpu
from kototoki.workers.protocol import FileJob, Jobs, validate_failed_windows

STAGE = "align"


def compute(aligner: Any, model_sha256: Mapping[str, str], load_s: float) -> gpu.Compute:
    def run(job: FileJob) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
        audio, pcm_sha256 = gpu.read_wav(job.inputs["wav"])
        asr, asr_sha256 = gpu.read_input_artifact(job.inputs["asr"], pcm_sha256)
        validate_failed_windows(asr)
        offset, duration = asr["offset_s"], len(audio) / gpu.SAMPLE_RATE
        started = time.perf_counter()
        aligned = aligner.align(audio, asr["original_segments"], offset)
        inference_s = time.perf_counter() - started
        if aligned["text"] != asr["text"]:
            raise ValueError("Alignment must preserve the complete ASR text")
        document = {
            "schema_version": 1, "engine": asr["engine"], "status": "ok", "text": aligned["text"],
            "units": aligned["units"], "cues": [], "original_segments": asr["original_segments"],
            "chunks": asr["chunks"], "failed_windows": asr["failed_windows"],
            "alignment_records": aligned["records"], "derived_segments": aligned["derived_segments"],
            "offset_s": offset, "source_start_seconds": offset, "duration_seconds": duration,
            "source_end_seconds": offset + duration, "input": asr["input"],
            "metadata": aligner.metadata, "stages": {"load_s": load_s, "inference_s": inference_s},
        }
        validate_transcript(document)
        validate_units(document)
        fields = {"windows": len(aligned["records"]),
                  "failed_alignment_windows": sum(1 for record in aligned["records"] if record["failure"]),
                  "text_only_units": sum(1 for unit in aligned["units"] if unit["status"] == "text_only")}
        return job.work_dir / artifacts.ALIGN, plan.align_identity(pcm_sha256, asr_sha256, model_sha256), document, fields
    return run


def start(jobs: Jobs) -> Any:
    gpu.require_recipe(jobs, plan.recipe_hash(STAGE))
    models = jobs.config["models"]
    model_sha256 = gpu.verify_models(plan.model_files(STAGE, models), Path(jobs.config["model_cache"]))
    from kototoki.align import MmsAligner

    started = time.perf_counter()
    aligner = MmsAligner(Path(models["align"]))
    return gpu.file_processor(compute(aligner, model_sha256, time.perf_counter() - started))


if __name__ == "__main__":
    sys.exit(gpu.main(start))
