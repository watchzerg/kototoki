"""B0：窗内 VAD 子段的落字统计、空子段与参考覆盖，以及对照删除项按位置分类。

- 落字：`align.json` 每个字符一个 unit；取 `status == "ok"` 且起止有限的 unit 的时间中点，落在子段 `[s, e]`
  （`vad.json` 的 `chunks[].segments`，WAV 本地秒，产品 `offset_s` 为 0）内即计入该子段。中点落在窗内子段之间的
  间隙记 `gap_chars`。没有时间的字符（`text_only`、回退）只计数，不参与落字；窗口有文字却没有任何带时间字符时记为
  `untimed`，其子段不判空。
- 空子段：时长 ≥ `MIN_EMPTY_S`（0.5 s）且落字 0；另记 ≥1 s 的数量（B1 只补 ≥1 s）。
- 参考覆盖：与空子段时间重叠的参考 cue，按重叠时长比例分摊其规范化字符数（主口径 `proportional`），同时给
  "整条 cue 计入"的上界（`whole_cue`，按 cue 去重）。
- 删除项定位：用 `kototoki_eval.alignment.align` 复算官方口径的对齐（与 `evaluate` 相同的规范化文本），每个被删参考字符
  按其所在参考 cue 内的位置线性内插出时间点，分类：`outside_window`（不在任何 VAD 窗口内）、`window_gap`
  （窗内但不在任何子段内）、`empty_segment`、`nonempty_segment`、`untimed_window`。删除总数须等于官方 D。
- 进 B1 的条件（§4.2）：两部空子段覆盖的参考字符数（proportional）之和 ≥ 两部官方 D 之和的 15%。
"""

from __future__ import annotations

import bisect
import math
from typing import Any

from experiments.asr_robustness_v14 import common
from kototoki import artifacts
from kototoki_eval.alignment import align as edit_align
from kototoki_eval.schema import normalize

MIN_EMPTY_S = 0.5
FILL_MIN_S = 1.0
B1_SHARE = 0.15


def timed_chars(align: dict[str, Any]) -> list[float | None]:
    """每个字符的时间中点（无可用时间为 None）；长度等于 `text`。"""
    text = align["text"]
    times: list[float | None] = [None] * len(text)
    for unit in align["units"]:
        if unit.get("status", "ok") != "ok":
            continue
        start, end = unit.get("start"), unit.get("end")
        if not (isinstance(start, (int, float)) and isinstance(end, (int, float))
                and math.isfinite(start) and math.isfinite(end)):
            continue
        mid = (start + end) / 2
        for position in range(unit["char_start"], unit["char_end"]):
            times[position] = mid
    return times


def window_char_ranges(asr: dict[str, Any]) -> list[tuple[int, int]]:
    ranges, cursor = [], 0
    for segment in asr["original_segments"]:
        ranges.append((cursor, cursor + len(segment["text"])))
        cursor += len(segment["text"])
    return ranges


def segment_table(vad: dict[str, Any], asr: dict[str, Any], align: dict[str, Any]) -> list[dict[str, Any]]:
    """逐窗逐子段：`{window, segment, start, end, duration_s, chars, empty}` 加每窗 `gap_chars`／`untimed`。"""
    if align["text"] != "".join(s["text"] for s in asr["original_segments"]):
        raise ValueError("align.json text differs from asr.json retained text")
    times = timed_chars(align)
    rows = []
    for index, (chunk, (lo, hi)) in enumerate(zip(vad["chunks"], window_char_ranges(asr))):
        segments = [tuple(seg) for seg in chunk["segments"]]
        counts = [0] * len(segments)
        gap = untimed = 0
        for position in range(lo, hi):
            if not normalize(align["text"][position]).text:
                continue  # 标点与空白不算字
            t = times[position]
            if t is None:
                untimed += 1
                continue
            for k, (s, e) in enumerate(segments):
                if s <= t <= e:
                    counts[k] += 1
                    break
            else:
                gap += 1
        lexical = sum(counts) + gap + untimed
        window_untimed = lexical > 0 and sum(counts) + gap == 0
        for k, (s, e) in enumerate(segments):
            rows.append({"window": index, "segment": k, "start": s, "end": e, "duration_s": round(e - s, 4),
                         "chars": counts[k], "window_gap_chars": gap, "window_untimed_chars": untimed,
                         "window_lexical_chars": lexical, "window_untimed": window_untimed,
                         "empty": (not window_untimed) and counts[k] == 0 and e - s >= MIN_EMPTY_S})
    return rows


def reference_coverage(empty: list[dict[str, Any]], reference: list[dict[str, Any]]) -> dict[str, Any]:
    starts = [cue["start"] for cue in reference]
    proportional = 0.0
    whole: dict[int, int] = {}
    per_segment = []
    for seg in empty:
        s, e = seg["start"], seg["end"]
        share = 0.0
        i = max(0, bisect.bisect_left(starts, s) - 5)
        while i < len(reference) and reference[i]["start"] < e:
            cue = reference[i]
            overlap = min(e, cue["end"]) - max(s, cue["start"])
            if overlap > 0 and cue["end"] > cue["start"]:
                chars = len(normalize(cue["text"]).text)
                share += chars * overlap / (cue["end"] - cue["start"])
                whole[i] = chars
            i += 1
        proportional += share
        per_segment.append(round(share, 2))
    return {"proportional": round(proportional, 1), "whole_cue": sum(whole.values()), "cues": len(whole),
            "segments_with_reference": sum(1 for v in per_segment if v > 0), "per_segment": per_segment}


def reference_char_times(reference_doc: dict[str, Any]) -> tuple[str, list[float]]:
    """官方口径的规范化参考文本及其每个字符的内插时间（按所在 cue 内的位置线性分布）。"""
    spans = reference_doc["spans"]
    raw = "".join(span["text"] for span in spans)
    norm = normalize(raw)
    boundaries, cursor = [], 0
    for span in spans:
        cursor += len(span["text"])
        boundaries.append(cursor)
    owner = [bisect.bisect_right(boundaries, raw_start) for raw_start, _ in norm.raw_spans]
    per_cue: dict[int, list[int]] = {}
    for position, cue in enumerate(owner):
        per_cue.setdefault(cue, []).append(position)
    times = [0.0] * len(norm.text)
    for cue, positions in per_cue.items():
        start, end = spans[cue]["start"], spans[cue]["end"]
        for k, position in enumerate(positions):
            times[position] = start + (k + 0.5) / len(positions) * (end - start)
    return norm.text, times


def classify_deletions(reference_doc: dict[str, Any], align_doc: dict[str, Any], vad: dict[str, Any],
                       rows: list[dict[str, Any]]) -> dict[str, Any]:
    ref_text, ref_times = reference_char_times(reference_doc)
    hyp_text = normalize(align_doc["text"]).text
    alignment = edit_align(ref_text, hyp_text)
    windows = [(c["start"], c["end"], i) for i, c in enumerate(vad["chunks"])]
    by_window: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        by_window.setdefault(row["window"], []).append(row)
    classes = {"outside_window": 0, "window_gap": 0, "empty_segment": 0, "nonempty_segment": 0, "untimed_window": 0}
    for i, mapped in enumerate(alignment.mapping):
        if mapped is not None:
            continue
        t = ref_times[i]
        window = next((w for s, e, w in windows if s <= t <= e), None)
        if window is None:
            classes["outside_window"] += 1
            continue
        segs = by_window.get(window, [])
        if segs and segs[0]["window_untimed"]:
            classes["untimed_window"] += 1
            continue
        hit = next((seg for seg in segs if seg["start"] <= t <= seg["end"]), None)
        if hit is None:
            classes["window_gap"] += 1
        elif hit["empty"]:
            classes["empty_segment"] += 1
        else:
            classes["nonempty_segment"] += 1
    total = sum(classes.values())
    return {"deletions": total, "official_D": alignment.deletions, "matches_official": total == alignment.deletions,
            "classes": classes, "shares": {k: round(v / total, 4) if total else None for k, v in classes.items()}}


def analyze(film: str) -> dict[str, Any]:
    work = common.FILMS[film]["work"]
    vad = common.read_json(work / artifacts.VAD)
    asr = common.read_json(work / artifacts.ASR)
    align_doc = common.read_json(work / artifacts.ALIGN)
    reference = common.reference_cues(film)
    rows = segment_table(vad, asr, align_doc)
    empty = [r for r in rows if r["empty"]]
    empty_1s = [r for r in empty if r["duration_s"] >= FILL_MIN_S]
    coverage = reference_coverage(empty, reference)
    coverage_1s = reference_coverage(empty_1s, reference)
    windows_untimed = len({r["window"] for r in rows if r["window_untimed"]})
    report = {
        "film": film, "windows": len(vad["chunks"]), "segments": len(rows),
        "segment_duration_s": {"total": round(sum(r["duration_s"] for r in rows), 1)},
        "lexical_chars": sum(r["chars"] for r in rows) + sum({r["window"]: r["window_gap_chars"] + r["window_untimed_chars"]
                                                           for r in rows}.values()),
        "gap_chars": sum({r["window"]: r["window_gap_chars"] for r in rows}.values()),
        "untimed_chars": sum({r["window"]: r["window_untimed_chars"] for r in rows}.values()),
        "untimed_windows": windows_untimed,
        "empty_segments": {"count": len(empty), "duration_s": round(sum(r["duration_s"] for r in empty), 1),
                           "windows": len({r["window"] for r in empty}), "reference": {k: v for k, v in coverage.items()
                                                                                     if k != "per_segment"}},
        "empty_segments_ge_1s": {"count": len(empty_1s), "duration_s": round(sum(r["duration_s"] for r in empty_1s), 1),
                                 "reference": {k: v for k, v in coverage_1s.items() if k != "per_segment"}},
        "segments_short_lt_0.5s_zero_chars": sum(1 for r in rows if r["chars"] == 0 and r["duration_s"] < MIN_EMPTY_S
                                                 and not r["window_untimed"]),
        "deletions": classify_deletions(common.load_reference_doc(film), align_doc, vad, rows),
    }
    common.write_json(common.ROOT / "01" / f"gaps-{film}.json", report)
    common.write_json(common.ROOT / "01" / f"segments-{film}.json", rows)
    return report


def empty_segments(film: str, min_s: float = FILL_MIN_S) -> list[dict[str, Any]]:
    """B1 用：空子段表（按窗口、子段序号），只取时长 ≥ `min_s`。"""
    path = common.ROOT / "01" / f"segments-{film}.json"
    rows = common.read_json(path) if path.is_file() else analyze(film) and common.read_json(path)
    return [r for r in rows if r["empty"] and r["duration_s"] >= min_s]


def run(films: tuple[str, ...]) -> dict[str, Any]:
    reports = {film: analyze(film) for film in films}
    covered = sum(r["empty_segments"]["reference"]["proportional"] for r in reports.values())
    deletions = sum(r["deletions"]["official_D"] for r in reports.values())
    summary = {
        "films": {film: {"empty_segments": r["empty_segments"]["count"],
                         "empty_ge_1s": r["empty_segments_ge_1s"]["count"],
                         "reference_proportional": r["empty_segments"]["reference"]["proportional"],
                         "reference_whole_cue": r["empty_segments"]["reference"]["whole_cue"],
                         "deletions": r["deletions"]["classes"], "D": r["deletions"]["official_D"],
                         "matches_official": r["deletions"]["matches_official"]}
                  for film, r in reports.items()},
        "covered_reference_chars": round(covered, 1), "total_deletions": deletions,
        "share_of_deletions": round(covered / deletions, 4) if deletions else None,
        "b1_condition": {"threshold": B1_SHARE, "met": deletions > 0 and covered >= B1_SHARE * deletions,
                         "complete": len(films) == 2},
    }
    common.write_json(common.ROOT / "01" / "gaps.json", summary)
    return summary


__all__ = ["B1_SHARE", "FILL_MIN_S", "MIN_EMPTY_S", "analyze", "classify_deletions", "empty_segments",
           "reference_char_times", "reference_coverage", "run", "segment_table", "timed_chars"]
