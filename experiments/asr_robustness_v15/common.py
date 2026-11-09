"""v15 公共部分：产物根目录、两部影片的对照（沿用 v14 `common.FILMS`）、读写工具与 w0 转写的两种落盘形状。

转写内容只在内存里处理；写进 `.local/asr-robustness-v15/` 的逐窗文字文件只供 Opus 判读，报告与文档只含计数。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from experiments.asr_robustness_v14 import common as v14

LOCAL = v14.LOCAL
ROOT = LOCAL / "asr-robustness-v15"
FILMS = v14.FILMS
PCM_SHA256 = v14.PCM_SHA256
SAMPLE_RATE = v14.SAMPLE_RATE

read_json = v14.read_json
write_json = v14.write_json
write_text = v14.write_text
utc_now = v14.utc_now
timed = v14.timed
gpu_lock = v14.gpu_lock
other_gpu_jobs = v14.other_gpu_jobs
VramSampler = v14.VramSampler


def segments_and_traces(document: dict[str, Any]) -> tuple[list[dict[str, Any]], list[Any]]:
    """产品 `asr.json` 与 W0 demo `result.json`／`asr.json` 都有 `original_segments`（含 `text`、`avg_logprob`）与
    `asr_traces`（含 `tokens`、`prompt`，失败窗口为 null）；窗口数以段为准，trace 缺失时补 None。"""
    segments = list(document["original_segments"])
    traces = list(document.get("asr_traces") or [])
    traces += [None] * (len(segments) - len(traces))
    return segments, traces[:len(segments)]


def ticket_dir(ticket: str) -> Path:
    path = ROOT / ticket
    path.mkdir(parents=True, exist_ok=True)
    return path
