"""内嵌日文字幕的清洗：ffmpeg 转出的 SRT 文本 → 可直接当 `ja.srt` 的文本（ADR-0024，配方 `recipes.EMBEDDED`）。

纯函数，不读写文件、不调用 ffmpeg（抽取在 `media.extract_subtitle`，落盘与跳过判定在编排）。输入是 ffmpeg
`-c:s srt -f srt` 的输出：ASS 的样式会变成 `<font>`／`<i>` 标签，对齐留成 `{\\an8}`，`\\h` 原样留下，绘图指令
漏成文字，空事件留成只有标签的条目，文字里还可能有空行——所以这里自己宽松地分条，不用 `srt.parse_srt`
的严格解析。不改写时间，不判断内容是不是日文，不过滤听障字幕的音效说明。
"""

from __future__ import annotations

import re

from kototoki.srt import format_srt_ms, time_parts_ms

_TIME = re.compile(r"(\d+):(\d{2}):(\d{2})[,.](\d{3})[ \t]+-->[ \t]+(\d+):(\d{2}):(\d{2})[,.](\d{3})")
_TAG = re.compile(r"</?(?:i|b|u|s|font)\b[^>]*>", re.IGNORECASE)
_OVERRIDE = re.compile(r"\{\\[^}]*\}")
_HARD_BREAK = re.compile(r"\\[hNn]")
# ASS 绘图指令（`{\p1}m 0 0 l 100 0 …`）去掉标签后的样子：以 m 开头，只有指令字母、数字与空白。
_DRAWING = re.compile(r"m(?:\s+-?\d+(?:\.\d+)?){2}(?:\s+(?:[mnlbspc]|-?\d+(?:\.\d+)?))*")


def _text(lines: list[str]) -> str:
    """一条字幕的文字：去标签，多行并成一行，空白折叠为单个空格。"""
    joined = " ".join(_HARD_BREAK.sub(" ", _OVERRIDE.sub("", _TAG.sub("", line))) for line in lines)
    return " ".join(joined.split())


def clean(text: str) -> tuple[str, dict[str, int]]:
    """返回 `(srt_text, stats)`；没有可用条目时 `srt_text == ""`。

    分条：时间行且上一行是纯数字编号即一条的开头，文字取到下一条的编号行之前。丢弃清洗后为空、是绘图指令、
    时长非正的条目，以及与已保留条目起止和文字都相同的重复条目；按（起、止）稳定排序后从 1 重新编号。
    `stats` 只有计数：`source_cues`、`cues`、`dropped_empty`、`dropped_drawing`、`dropped_invalid_time`、
    `dropped_duplicate`。
    """
    lines = text.removeprefix("﻿").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    heads = [i for i in range(1, len(lines)) if _TIME.fullmatch(lines[i].strip()) and lines[i - 1].strip().isdigit()]
    stats = {"source_cues": len(heads), "cues": 0, "dropped_empty": 0, "dropped_drawing": 0,
             "dropped_invalid_time": 0, "dropped_duplicate": 0}
    kept: list[tuple[int, int, str]] = []
    seen: set[tuple[int, int, str]] = set()
    for head, following in zip(heads, [*heads[1:], len(lines) + 1]):
        match = _TIME.fullmatch(lines[head].strip())
        assert match is not None
        start, end = time_parts_ms(match.groups()[:4]), time_parts_ms(match.groups()[4:])
        cue = (start, end, _text(lines[head + 1:following - 1]))
        if not cue[2]:
            stats["dropped_empty"] += 1
        elif _DRAWING.fullmatch(cue[2]):
            stats["dropped_drawing"] += 1
        elif cue[1] <= cue[0]:
            stats["dropped_invalid_time"] += 1
        elif cue in seen:
            stats["dropped_duplicate"] += 1
        else:
            seen.add(cue)
            kept.append(cue)
    kept.sort(key=lambda cue: cue[:2])
    stats["cues"] = len(kept)
    return format_srt_ms(kept), stats
