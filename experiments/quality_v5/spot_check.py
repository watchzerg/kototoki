"""人工观感抽查表（票据 05）：每部整片取开头、中段对白最密处、结尾各约 2 分钟，列产品中文、产品日文与参考日文。

命令（仓库根目录）：
  python -X utf8 -m experiments.quality_v5.spot_check --film NAME PRODUCT_JA PRODUCT_ZH REFERENCE_JSON [...] --out sheet.md
"""

import argparse
import json
from pathlib import Path

from experiments.quality_v5.readability import read_srt

WINDOW_S = 120.0


def densest_window(starts: list[float], low: float, high: float, width: float = WINDOW_S) -> float:
    """[low, high − width] 内起点使窗口里 cue 数最多的位置（按 cue 起点枚举）。"""
    best, best_count = low, -1
    for t in starts:
        if t < low or t > high - width:
            continue
        count = sum(1 for s in starts if t <= s < t + width)
        if count > best_count:
            best, best_count = t, count
    return best


def segments(product: list[dict], reference: list[dict]) -> list[tuple[str, float, float]]:
    first, last = reference[0]["start"], reference[-1]["end"]
    third = (last - first) / 3
    middle = densest_window([c["start"] for c in product], first + third, first + 2 * third)
    return [("开头", first, first + WINDOW_S), ("中段（对白最密）", middle, middle + WINDOW_S),
            ("结尾", last - WINDOW_S, last)]


def clock(t: float) -> str:
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:04.1f}"


def overlapping(cues: list[dict], start: float, end: float) -> list[dict]:
    return [c for c in cues if c["end"] > start and c["start"] < end]


def cell(text: str) -> str:
    return text.replace("|", "｜").replace("\n", " ")


def film_section(name: str, ja: list[dict], zh: list[dict], reference: list[dict]) -> list[str]:
    lines = [f"## {name}", ""]
    for label, start, end in segments(zh, reference):
        lines += [f"### {label} {clock(start)}–{clock(end)}", "",
                  "| # | 时间 | 中文（产品） | 日文（产品 ASR） | 日文参考（同时段） | 看得懂／别扭／错 | 备注 |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for index, (j, z) in enumerate(zip(ja, zh), 1):
            if z["end"] <= start or z["start"] >= end:
                continue
            ref = " ／ ".join(r["text"] for r in overlapping(reference, z["start"], z["end"]))
            lines.append(f"| {index} | {clock(z['start'])}（{z['end'] - z['start']:.1f} s） | {cell(' '.join(z['lines']))} | "
                         f"{cell(' '.join(j['lines']))} | {cell(ref) or '（无）'} |  |  |")
        lines.append("")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="人工观感抽查表")
    parser.add_argument("--film", nargs=4, action="append", required=True, metavar=("NAME", "JA", "ZH", "REFERENCE"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    lines = ["# v5 人工观感抽查表", "",
             "每部取开头、中段对白最密处、结尾各约 2 分钟。请对照视频观看，在\"看得懂／别扭／错\"列填一项，"
             "备注写原因（例如人名不对、意思反了、闪得太快、太长读不完）。可只填一部分；填完告诉下一个会话即可。",
             "时长列是该条显示秒数；参考日文是官方日文字幕在同一时段的条目（可能多条或没有）。", ""]
    for name, ja, zh, reference in args.film:
        spans = json.loads(Path(reference).read_text(encoding="utf-8"))["spans"]
        lines += film_section(name, read_srt(Path(ja)), read_srt(Path(zh)),
                              [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in spans])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
