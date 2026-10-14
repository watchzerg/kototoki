"""STT 产物的数据契约：`validate_transcript`（复制自 `kototoki_eval/schema.py`）、源窗口与 units 校验。

基础层：只依赖标准库，编排器与各 worker 都可直接导入。窗口与 units 的坐标约定见
`kototoki.artifacts` 模块文档：窗口是 WAV 本地整数样本与秒，`units[].start/end` 含 `offset_s`。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any

SAMPLE_RATE = 16000
MAX_WINDOW_SAMPLES = 30 * SAMPLE_RATE
# 有时间的 unit 允许超出源末尾的量（秒），与 W0 pipeline 的历史判据相同（毫秒取整）。
UNIT_END_SLACK_S = 0.001


def finite_time(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_transcript(document: dict[str, Any]) -> None:
    if document.get("schema_version") != 1 or not isinstance(document.get("text"), str):
        raise ValueError("Transcript requires schema_version=1 and complete text")
    for key in ("source_start_seconds", "source_end_seconds", "duration_seconds"):
        if key in document and (not finite_time(document[key]) or document[key] < 0):
            raise ValueError("Source coordinate bounds must be finite nonnegative seconds")
    if document.get("source_end_seconds", math.inf) < document.get("source_start_seconds", 0):
        raise ValueError("Source end precedes source start")
    for unit in document.get("units", []):
        a, b = unit.get("char_start"), unit.get("char_end")
        if (not isinstance(a, int) or not isinstance(b, int)
                or not 0 <= a < b <= len(document["text"])):
            raise ValueError("Unit character ranges must address complete original text")
        if unit.get("granularity") not in {"word", "character", "segment"}:
            raise ValueError("Unit granularity must be word, character, or segment")
        if unit.get("time_source", "native") not in {"native", "api", "fallback", "interpolated"}:
            raise ValueError("Unknown time provenance")
        if unit.get("status", "ok") not in {"ok", "failed", "text_only"}:
            raise ValueError("Unknown unit status")


def validate_windows(chunks: Sequence[Mapping[str, Any]], samples: int) -> None:
    """VAD 窗口：成对整数 `start_sample/end_sample` 有序不重叠、落在源内、每窗 1..480000 样本，
    秒坐标与样本一致（`sample / 16000`，截断回样本不少于原值），子段落在窗内且有序。"""
    previous = 0
    for index, chunk in enumerate(chunks):
        start, end = chunk.get("start_sample"), chunk.get("end_sample")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (start, end)) \
                or not previous <= start < end <= samples or end - start > MAX_WINDOW_SAMPLES:
            raise ValueError(f"Window {index} needs ordered integer sample bounds of at most 30 s inside the source")
        for key, sample in (("start", start), ("end", end)):
            seconds = chunk.get(key)
            if not finite_time(seconds) or not math.isclose(seconds, sample / SAMPLE_RATE, rel_tol=0, abs_tol=1e-9):
                raise ValueError(f"Window {index} {key} seconds must match its sample bound")
        span_end = chunk["start"]
        for span in chunk.get("segments", []):
            if (not isinstance(span, (list, tuple)) or len(span) != 2 or not all(map(finite_time, span))
                    or not span_end <= span[0] < span[1] <= chunk["end"]):
                raise ValueError(f"Window {index} has invalid constituent segments")
            span_end = span[1]
        previous = end


def validate_units(document: Mapping[str, Any]) -> None:
    """对齐结果的不变量（取自 W0 pipeline）：每个字符恰好一个 unit；有时间的 unit 落在源范围内。"""
    text, offset, duration = document["text"], document["offset_s"], document["duration_seconds"]
    covered = [0] * len(text)
    for unit in document["units"]:
        for index in range(unit["char_start"], unit["char_end"]):
            covered[index] += 1
        if unit["status"] == "ok" and not (
                finite_time(unit.get("start")) and finite_time(unit.get("end"))
                and offset <= unit["start"] <= unit["end"] <= offset + duration + UNIT_END_SLACK_S):
            raise ValueError("Timed units must remain inside the source input")
    if any(count != 1 for count in covered):
        raise ValueError("Alignment units must account for every original character exactly once")
