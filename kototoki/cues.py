"""日文 cue：把 `align.json` 的字符级时间回填后切成字幕条目。

`build_cues(align, rules)` 是纯函数：输入已解析的 `align.json` 内容与 `[cues]`
规则表，返回 `ja-cues.json` 的 payload 与 `ja.srt` 文本，不读写文件。

坐标：`units[].start/end` 已含 `offset_s`；窗口（`original_segments`）与 VAD 子段
（`chunks[].segments`）是 WAV 本地秒，用到时加一次 `offset_s`。这是时间轴上唯一
加 offset 的地方（规格 §4）。

顺序：先回填无时间字符（窗内插值、窗边外推、整窗按 VAD 子段 `fallback`），再按
句末标点与间隔断句、超限时在软断点后切、仍超限则硬切，最后加 `lead_out_s` 与
`min_duration_s`。间隔断句只在间隔不落在同一个 VAD 子段内时成立：CTC 只给每个
字符一个短发射点，拖长音会在词内留下超过 `max_gap_s` 的"假间隙"（票据 12）。cue 时间只取词汇字符；标点、空白与 ♪ 等符号附着到相邻 cue。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
import bisect
import math
import unicodedata
from typing import Any, cast

from kototoki.srt import format_srt, milliseconds

RULE_KEYS = frozenset({"max_chars", "max_duration_s", "min_duration_s", "max_gap_s",
                       "sentence_endings", "soft_breaks", "lead_out_s"})

# 整窗回退时每字符时长上限（秒）：VAD 子段很长而文字很少时不把几个字摊满整段。
FALLBACK_MAX_CHAR_S = 0.25

Interval = tuple[float, float]


def is_lexical(char: str) -> bool:
    """标点、空白与符号（含 ♪）不是词汇字符，不决定 cue 时间与切点。"""
    return not (char.isspace() or unicodedata.category(char)[0] in "PSZC")


def _windows(align: Mapping[str, Any]) -> list[tuple[int, int, Interval, list[Interval]]]:
    """每个 ASR 窗口的字符范围、窗口边界与 VAD 子段（均已加 offset）。"""
    offset = align["offset_s"]
    segments, chunks = align["original_segments"], align["chunks"]
    if len(segments) != len(chunks):
        raise ValueError("align.json original_segments and chunks must correspond one to one")
    windows, base = [], 0
    for segment, chunk in zip(segments, chunks):
        end = base + len(segment["text"])
        bounds = (segment["start"] + offset, segment["end"] + offset)
        spans = [(a + offset, b + offset) for a, b in chunk.get("segments") or []] or [bounds]
        windows.append((base, end, bounds, spans))
        base = end
    if base != len(align["text"]):
        raise ValueError("align.json window texts must concatenate to the full text")
    return windows


def _interpolate(times: list[Interval | None], sources: list[str], lo: int, hi: int,
                 bounds: Interval) -> None:
    """窗内有时间字符之间线性插值；窗首／窗尾按窗内平均每字符时长外推，不越过窗口边界。"""
    timed = [i for i in range(lo, hi) if times[i] is not None]
    first, last = timed[0], timed[-1]
    per_char = (times[last][1] - times[first][0]) / (last - first + 1)
    for left, right in zip(timed, timed[1:]):
        if right - left > 1:
            begin, finish = times[left][1], times[right][0]
            step = max(finish - begin, 0.0) / (right - left - 1)
            for k, i in enumerate(range(left + 1, right)):
                times[i] = (begin + k * step, begin + (k + 1) * step)
                sources[i] = "interpolated"
    for k, i in enumerate(range(first - 1, lo - 1, -1)):
        start = times[first][0]
        times[i] = (max(start - (k + 1) * per_char, bounds[0]), max(start - k * per_char, bounds[0]))
        sources[i] = "interpolated"
    for k, i in enumerate(range(last + 1, hi)):
        end = times[last][1]
        times[i] = (min(end + k * per_char, bounds[1]), min(end + (k + 1) * per_char, bounds[1]))
        sources[i] = "interpolated"


def _fallback(times: list[Interval | None], sources: list[str], lo: int, hi: int,
              spans: list[Interval]) -> None:
    """整窗无时间：按子段时长比例（最大余数法）分配字符，子段内从起点按上限时长排列。"""
    total = sum(b - a for a, b in spans)
    count = hi - lo
    shares = [count * (b - a) / total if total > 0 else count / len(spans) for a, b in spans]
    allotted = [math.floor(share) for share in shares]
    by_remainder = sorted(range(len(spans)), key=lambda j: (allotted[j] - shares[j], j))
    for j in by_remainder[:count - sum(allotted)]:
        allotted[j] += 1
    i = lo
    for (a, b), n in zip(spans, allotted):
        if n:
            per_char = min((b - a) / n, FALLBACK_MAX_CHAR_S)
            for k in range(n):
                times[i] = (a + k * per_char, a + (k + 1) * per_char)
                sources[i] = "fallback"
                i += 1


def _backfill(align: Mapping[str, Any]) -> tuple[list[Interval], list[str], list[int]]:
    text, units = align["text"], align["units"]
    if len(units) != len(text) or any(
            unit["char_start"] != i or unit["char_end"] != i + 1 for i, unit in enumerate(units)):
        raise ValueError("align.json units must be one contiguous character unit per text character")
    times: list[Interval | None] = [
        (unit["start"], unit["end"]) if unit["status"] == "ok" else None for unit in units]
    sources = [unit.get("time_source", "native") if unit["status"] == "ok" else "" for unit in units]
    fallback_windows = []
    for index, (lo, hi, bounds, spans) in enumerate(_windows(align)):
        if lo == hi:
            continue
        if any(times[i] is not None for i in range(lo, hi)):
            _interpolate(times, sources, lo, hi, bounds)
        else:
            _fallback(times, sources, lo, hi, spans)
            fallback_windows.append(index)
    return cast(list[Interval], times), sources, fallback_windows


def _speech_spans(align: Mapping[str, Any]) -> list[Interval]:
    """全部窗口的 VAD 子段（已加 offset），按起点排序；没有子段的窗口以窗口边界代替。"""
    return sorted(span for _, _, _, spans in _windows(align) for span in spans)


def _within_one_span(spans: list[Interval], start: float, end: float) -> bool:
    """[start, end] 是否整个落在某一个子段内（允许端点相等）。"""
    i = bisect.bisect_right(spans, (start, math.inf)) - 1
    while i >= 0 and spans[i][1] >= end:
        if spans[i][0] <= start:
            return True
        i -= 1
    return False


def _check_rules(rules: Mapping[str, Any]) -> None:
    if set(rules) != RULE_KEYS:
        raise ValueError(f"cue rules must have exactly the keys {sorted(RULE_KEYS)}")
    if not (isinstance(rules["max_chars"], int) and rules["max_chars"] >= 1):
        raise ValueError("max_chars must be a positive integer")
    if not rules["max_duration_s"] > 0 or rules["min_duration_s"] < 0 or rules["max_gap_s"] < 0 \
            or rules["lead_out_s"] < 0:
        raise ValueError("cue durations must be nonnegative and max_duration_s positive")


def build_cues(align: Mapping[str, Any], rules: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    """返回 (`ja-cues.json` payload, `ja.srt` 文本)；没有可渲染文字时得到零条目。"""
    _check_rules(rules)
    text = align["text"]
    times, sources, fallback_windows = _backfill(align)
    speech = _speech_spans(align)
    lexical = [i for i, char in enumerate(text) if is_lexical(char)]
    n = len(lexical)

    # 相邻词汇字符之间的非词汇串在第一个空白或开括号处分开：前半附着前一条，后半附着后一条。
    split = [0] * (n + 1)
    split[n] = len(text)
    sentence_break, soft_break = [False] * (n + 1), [False] * (n + 1)
    for j in range(1, n):
        lo, hi = lexical[j - 1] + 1, lexical[j]
        split[j] = next((i for i in range(lo, hi)
                         if text[i].isspace() or unicodedata.category(text[i]) in ("Ps", "Pi")), hi)
        run = text[lo:hi]
        previous_end, next_start = times[lexical[j - 1]][1], times[lexical[j]][0]
        gap_break = (next_start - previous_end > rules["max_gap_s"]
                     and not _within_one_span(speech, previous_end, next_start))
        sentence_break[j] = gap_break or any(c in rules["sentence_endings"] for c in run)
        soft_break[j] = any(c in rules["soft_breaks"] for c in run)
    visible = [0]
    for char in text:
        visible.append(visible[-1] + (not char.isspace()))

    def chars(a: int, b: int) -> int:
        return visible[split[b]] - visible[split[a]]

    def duration(a: int, b: int) -> float:
        return times[lexical[b - 1]][1] - times[lexical[a]][0]

    def fits(a: int, b: int) -> bool:
        return chars(a, b) <= rules["max_chars"] and duration(a, b) <= rules["max_duration_s"]

    def cut(a: int, b: int) -> list[tuple[int, int]]:
        if fits(a, b) or b - a == 1:  # 单个词汇字符本身超限（拖长音、附着大量标点）时不再切，否则硬切会递归出空区间
            return [(a, b)]
        soft = [j for j in range(a + 1, b) if soft_break[j] and fits(a, j)]
        if soft:
            return [(a, soft[-1])] + cut(soft[-1], b)
        pieces = max(math.ceil(chars(a, b) / rules["max_chars"]),
                     math.ceil(duration(a, b) / rules["max_duration_s"]))
        target = math.ceil(chars(a, b) / pieces)
        j = a + 1
        while j + 1 < b and chars(a, j + 1) <= target and duration(a, j + 1) <= rules["max_duration_s"]:
            j += 1
        return [(a, j)] + cut(j, b)

    starts = [0] + [j for j in range(1, n) if sentence_break[j]]
    spans = [piece for a, b in zip(starts, starts[1:] + [n]) for piece in cut(a, b)] if n else []

    bounds = [(times[lexical[a]][0], times[lexical[b - 1]][1]) for a, b in spans]
    entries, cues = [], []
    for k, ((a, b), (start, end)) in enumerate(zip(spans, bounds)):
        limit = bounds[k + 1][0] if k + 1 < len(bounds) else math.inf
        end = max(end, min(end + rules["lead_out_s"], limit))
        end = max(end, min(start + rules["min_duration_s"], limit))
        start_ms, end_ms = milliseconds(start), milliseconds(end)
        end_ms = max(end_ms, start_ms + 1)
        char_start, char_end = split[a], split[b]
        body = " ".join(text[char_start:char_end].split())
        counts = Counter(sources[char_start:char_end])
        entries.append((start_ms / 1000, end_ms / 1000, body))
        cues.append({"index": k + 1, "start_ms": start_ms, "end_ms": end_ms, "text": body,
                     "char_start": char_start, "char_end": char_end,
                     "unit_start": char_start, "unit_end": char_end,
                     "time_sources": dict(sorted(counts.items())),
                     "backfilled_units": counts["interpolated"] + counts["fallback"]})

    totals = Counter(sources)
    payload = {
        "cues": cues,
        "time_sources": dict(sorted(totals.items())),
        "backfilled_units": _runs(sources),
        "fallback_windows": fallback_windows,
        "unrendered_chars": len(text) if not cues else 0,
    }
    return payload, format_srt(entries)


def _runs(sources: Sequence[str]) -> list[dict[str, Any]]:
    """回填来源按连续区间记账：`[unit_start, unit_end)` 与 `time_source`。"""
    runs: list[dict[str, Any]] = []
    for i, source in enumerate(sources):
        if source not in ("interpolated", "fallback"):
            continue
        if runs and runs[-1]["unit_end"] == i and runs[-1]["time_source"] == source:
            runs[-1]["unit_end"] = i + 1
        else:
            runs.append({"unit_start": i, "unit_end": i + 1, "time_source": source})
    return runs
