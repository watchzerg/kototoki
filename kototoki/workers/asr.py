"""ASR worker：`python -m kototoki.workers.asr --jobs <path>`，逐文件写 `asr.json`。

按 `config.engine` 选择适配器（`w0` → `kototoki.asr_whisper`，`x0` → `kototoki.asr_qwen`），
两个适配器写出同一种 `asr.json`。jobs：`config` 需要 `engine`、`models`（w0 用 `w0`、
`w0_mel_assets`，x0 用 `x0`）与 `model_cache`；`inputs` 需要 `wav` 与 `vad`（`vad.json`）。

`asr.json`（坐标为 WAV 本地）：身份 = PCM SHA256＋`vad.json` SHA256＋引擎配方 hash＋模型文件 SHA256；
payload 为 `schema_version`、`engine`、`offset_s`、`input`、`chunks`（照抄 `vad.json`）、
`original_segments`（与窗口一一对应）、`asr_traces`、`failed_windows`（协议 `fail_window` 写法）、
保留文本 `text`、`metadata`、`stages`。本模块导入时不加载 torch／CT2，适配器在 `start` 里才导入。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import sys
import time
from typing import Any

from kototoki import artifacts, recipes
from kototoki.workers import gpu
from kototoki.workers.protocol import FileJob, Jobs, fail_window, retained_text, validate_failed_windows

RECIPES = {"w0": recipes.W0, "x0": recipes.X0}
# faster-whisper large-v3（CT2）目录内参与推理的文件，SHA256 取自 W0 基线运行记录。
W0_FILES = {
    "config.json": "a9306624f5ec14270a014b647e5c316b6e03a662c369758d1b90697a7b0655b9",
    "model.bin": "69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1",
    "preprocessor_config.json": "7ccc62c6f2765af1f3b46c00c9b5894426835a05021c8b9c01eecb6dfb542711",
    "tokenizer.json": "6d8cbd7cd0d8d5815e478dac67b85a26bbe77c1f5e0c6d76d1ce2abc0e5f21ca",
    "vocabulary.json": "c69260f2ab26d659b7c398f9a2b2b48ed0df16c3b47d7326782fd9cba71690c1",
}
# Qwen3-ASR-1.7B-hf 目录内参与推理的文件（权重与全部 .json／.jinja；README 与下载残留不参与），
# SHA256 取自 X0 基线运行记录（`model_files_sha256.asr`）。
X0_FILES = {
    "model.safetensors": "2db53c7d81bd9b8cbc6a074e89be2c968a0d373fb4ee68bb1b1e14f7042dfee1",
    "chat_template.jinja": "f50e6b694fbf4a683206e37869990d68333fe95d285730f084c838a34b0d98c2",
    "config.json": "117ac8e63e2af7cae3665e5a632d6eb03f5f384915519ceb6403c15ec6533f63",
    "generation_config.json": "9939fc9388b79bd70757f938b87381e817173d6a6158f5af6506c0b73e775c3c",
    "processor_config.json": "bc0b230081b44e629dd5b9045b78495615c1831b4b9f4cffe97bd37e82a6156a",
    "tokenizer.json": "fe1fad59be22a41ee293363fcf95fdedbc7c93f3b49270b1d2e18bd1399a7a05",
    "tokenizer_config.json": "945e980986de2ca7768f3326bfdbb4fbea3406f972b8ae0be233089f2b253c11",
}


def recipe_hash(engine: str) -> str:
    return recipes.recipe_hash(RECIPES[engine])


def model_files(engine: str, models: Mapping[str, str]) -> dict[str, tuple[Path, str]]:
    if engine == "x0":
        return {f"qwen3-asr-1.7b-hf/{name}": (Path(models["x0"]) / name, sha256)
                for name, sha256 in X0_FILES.items()}
    files = {f"faster-whisper-large-v3/{name}": (Path(models["w0"]) / name, sha256)
             for name, sha256 in W0_FILES.items()}
    files["w0-assets/mel_filters.npz"] = (Path(models["w0_mel_assets"]) / "mel_filters.npz",
                                          recipes.W0["features"]["mel_sha256"])
    return files


def identity(engine: str, pcm_sha256: str, vad_sha256: str, model_sha256: Mapping[str, str]) -> dict[str, Any]:
    return artifacts.derived_identity(upstream={artifacts.AUDIO_16K: pcm_sha256, artifacts.VAD: vad_sha256},
                                      recipe_hash=recipe_hash(engine), models=model_sha256)


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
        validate_failed_windows(document)
        document.update(text=retained_text(document), metadata=asr.metadata,
                        stages={"load_s": load_s, "inference_s": inference_s})
        fields = {"windows": len(segments), "failed_windows": len(failures)}
        return (job.work_dir / artifacts.ASR, identity(engine, pcm_sha256, vad_sha256, model_sha256),
                document, fields)
    return run


def start(jobs: Jobs) -> Any:
    engine, models = jobs.config["engine"], jobs.config["models"]
    if engine not in RECIPES:
        raise ValueError(f"ASR engine {engine!r} is not available")
    gpu.require_recipe(jobs, recipe_hash(engine))
    model_sha256 = gpu.verify_models(model_files(engine, models), Path(jobs.config["model_cache"]))
    started = time.perf_counter()
    if engine == "x0":
        from kototoki.asr_qwen import QwenAsr

        asr: Any = QwenAsr(Path(models["x0"]))
    else:
        from kototoki.asr_whisper import WhisperAsr

        asr = WhisperAsr(Path(models["w0"]), Path(models["w0_mel_assets"]))
    return gpu.file_processor(compute(asr, engine, model_sha256, time.perf_counter() - started))


if __name__ == "__main__":
    sys.exit(gpu.main(start))
