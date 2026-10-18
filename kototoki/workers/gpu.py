"""三个 GPU worker 壳共用：命令行入口（含 stderr 日志配置）、读模型输入 WAV、模型文件核对、CUDA 粘性错误守卫与产物写出。

只被 `kototoki.workers.{vad,asr,align}` 导入；本模块导入时不加载 torch，`check_cuda` 用到时才导入。
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import hashlib
import json
import logging
from pathlib import Path
import sys
import time
from typing import Any
import wave

from kototoki import artifacts
from kototoki.logs import RunFormatter
from kototoki.workers.protocol import FatalWorkerError, FileJob, Jobs, run_worker

SAMPLE_RATE = 16000

# compute(job) -> (产物路径, 身份, payload, 进度行附加字段)
Compute = Callable[[FileJob], tuple[Path, Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]]


def main(start: Callable[[Jobs], Callable[[FileJob], Mapping[str, Any] | None]],
         argv: list[str] | None = None) -> int:
    """`python -m kototoki.workers.<stage> --jobs <path>`；返回协议退出码。

    日志只写 stderr（编排器把它存成 `run-<戳>-<stage>.stderr.log`），stdout 只留协议 JSON 行。
    handler 挂在 root 上：`kototoki` logger 放到 INFO，第三方库按 root 默认级别只有 WARNING 及以上。
    """
    started = time.time()
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=Path, required=True)
    jobs_path = parser.parse_args(argv).jobs
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(RunFormatter(started))
    logging.getLogger().addHandler(handler)
    logging.getLogger("kototoki").setLevel(logging.INFO)
    logging.captureWarnings(True)
    return run_worker(jobs_path, start)


def require_recipe(jobs: Jobs, recipe_hash: str) -> None:
    """jobs 的配方 hash 必须等于本 worker 写进身份的那个，否则编排器会把产物判为过期而反复重算。"""
    if jobs.recipe_hash != recipe_hash:
        raise ValueError(f"Jobs recipe_hash {jobs.recipe_hash} differs from worker recipe {recipe_hash}")


def read_input_artifact(path: Path, pcm_sha256: str) -> tuple[dict[str, Any], str]:
    """读上游 JSON 产物并重验输入身份：它必须由同一份 `audio-16k.wav` 算出；返回 (内容, 文件 SHA256)。"""
    data = Path(path).read_bytes()
    document = json.loads(data.decode("utf-8"))
    if document["identity"]["upstream"].get(artifacts.AUDIO_16K) != pcm_sha256:
        raise ValueError(f"{Path(path).name} was computed from different audio")
    return document, artifacts.sha256_bytes(data)


def read_wav(path: Path) -> tuple[Any, str]:
    """mono 16 kHz PCM16 WAV → (float32 波形 = PCM16 / 32768, PCM 数据 SHA256)。"""
    import numpy as np

    with wave.open(str(path), "rb") as source:
        if (source.getnchannels(), source.getframerate(), source.getsampwidth(), source.getcomptype()) \
                != (1, SAMPLE_RATE, 2, "NONE"):
            raise ValueError("Model input must be mono 16000 Hz PCM16 WAV")
        frames = source.getnframes()
        pcm = source.readframes(frames)
    if len(pcm) != frames * 2:
        raise ValueError("Model input WAV is truncated")
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0, hashlib.sha256(pcm).hexdigest()


def verify_models(files: Mapping[str, tuple[Path, str]], cache_path: Path) -> dict[str, str]:
    """加载前逐个核对模型文件 SHA256（size+mtime 缓存，见 `artifacts.verify_model`）；返回 {名称: SHA256}。"""
    return {name: artifacts.verify_model(path, expected, cache_path)["sha256"]
            for name, (path, expected) in files.items()}


def check_cuda() -> None:
    """CUDA 粘性错误（非法访存、设备断言等）之后任何 CUDA 调用都会失败：同步一次即可判定。"""
    import torch

    try:
        torch.cuda.synchronize()
    except Exception as error:  # noqa: BLE001 - 任何同步失败都说明上下文不可用
        raise FatalWorkerError(f"CUDA context is unusable: {type(error).__name__}: {error}") from error


def file_processor(compute: Compute, *, check: Callable[[], None] = check_cuda
                   ) -> Callable[[FileJob], Mapping[str, Any]]:
    """把 `compute` 包成协议的逐文件处理函数：算完先确认 CUDA 仍可用再写产物。

    模块内部按窗口吞掉的错误也可能来自粘性错误，所以写产物前无论成败都检查一次；
    `compute` 抛异常时同样检查，上下文已坏即升级为 `FatalWorkerError`（退出码 2），
    否则原样抛出，由协议记为单文件失败。
    """
    def process(job: FileJob) -> Mapping[str, Any]:
        try:
            path, identity, payload, fields = compute(job)
        except FatalWorkerError:
            raise
        except Exception:
            check()
            raise
        check()
        artifacts.write_artifact(path, identity, payload)
        return fields
    return process
