"""可读性与 cue 统计（票据 03）：中文每秒字数（CPS）、行长、显示时长、双语每条行数、中日长度比。

字数口径：去掉空白后的可见字符数（标点计入，与常见字幕规范的计法一致）；另报不计标点的"词汇字数"。
阈值只作统计参照，不是产品规则：CPS 9（Netflix 简中成人）／12／15，行长 16（Netflix 简中）／20，
时长 < 0.833 s（5/6 秒）与 > 7 s。

命令（仓库根目录）：
  python -X utf8 -m experiments.quality_v5.readability srt --film NAME JA.srt ZH.srt JA-ZH.srt [...] --out FILE
  python -X utf8 -m experiments.quality_v5.readability v4ref [--set dev] --out FILE   # 字幕组参考中文作人工基准
"""

import argparse
import json
import re
import unicodedata
from pathlib import Path

CPS_LIMITS = (9, 12, 15)
LINE_LIMITS = (16, 20)
MIN_DURATION, MAX_DURATION = 5 / 6, 7.0
TIME = r"(\d+):(\d+):(\d+)[,.](\d+)"
BLOCK = re.compile(r"\d+\s*\n" + TIME + r"\s*-->\s*" + TIME + r"[^\n]*\n(.*?)(?:\n\s*\n|\Z)", re.S)


def seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 10 ** len(ms)


def read_srt(path: Path) -> list[dict]:
    """[{start, end, lines}]，lines 保留原有分行。"""
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    cues = []
    for match in BLOCK.finditer(text + "\n\n"):
        groups = match.groups()
        lines = [line.strip() for line in groups[8].strip().split("\n") if line.strip()]
        cues.append({"start": seconds(*groups[0:4]), "end": seconds(*groups[4:8]), "lines": lines})
    return cues


def visible_len(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace())


def lexical_len(text: str) -> int:
    return sum(1 for ch in text if unicodedata.category(ch)[0] in "LN")


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def distribution(values: list[float]) -> dict:
    return {"n": len(values), "mean": sum(values) / len(values) if values else None,
            "p50": percentile(values, 0.5), "p90": percentile(values, 0.9),
            "p95": percentile(values, 0.95), "max": max(values) if values else None}


def share_over(values: list[float], limit: float) -> dict:
    count = sum(1 for v in values if v > limit)
    return {"count": count, "share": count / len(values) if values else None}


def histogram(values: list[float], edges: list[float]) -> list[int]:
    """edges 升序；返回 len(edges)+1 个桶：(<e0), [e0,e1), ..., [e_last, ∞)。"""
    counts = [0] * (len(edges) + 1)
    for value in values:
        counts[sum(1 for e in edges if value >= e)] += 1
    return counts


def zh_metrics(zh_cues: list[dict]) -> dict:
    durations = [c["end"] - c["start"] for c in zh_cues]
    chars = [visible_len("".join(c["lines"])) for c in zh_cues]
    lexical = [lexical_len("".join(c["lines"])) for c in zh_cues]
    cps = [n / d for n, d in zip(chars, durations) if d > 0]
    lines = [visible_len(line) for c in zh_cues for line in c["lines"]]
    return {
        "cues": len(zh_cues),
        "empty_cues": sum(1 for n in chars if n == 0),
        "cps": distribution(cps), "cps_over": {str(l): share_over(cps, l) for l in CPS_LIMITS},
        "cps_histogram": {"edges": [3, 6, 9, 12, 15, 20, 25], "counts": histogram(cps, [3, 6, 9, 12, 15, 20, 25])},
        "lexical_cps": distribution([n / d for n, d in zip(lexical, durations) if d > 0]),
        "chars": distribution(chars),
        "line_length": distribution(lines), "line_over": {str(l): share_over(lines, l) for l in LINE_LIMITS},
        "lines_per_cue": distribution([len(c["lines"]) for c in zh_cues]),
        "duration": distribution(durations),
        "duration_under_min": share_over([-d for d in durations], -MIN_DURATION),
        "duration_over_max": share_over(durations, MAX_DURATION),
    }


def pair_metrics(ja_cues: list[dict], zh_cues: list[dict]) -> dict:
    ratios = []
    for ja, zh in zip(ja_cues, zh_cues):
        ja_len = lexical_len("".join(ja["lines"]))
        if ja_len:
            ratios.append(lexical_len("".join(zh["lines"])) / ja_len)
    return {"zh_ja_lexical_ratio": distribution(ratios)}


def film_report(ja: Path, zh: Path, bilingual: Path | None) -> dict:
    ja_cues, zh_cues = read_srt(ja), read_srt(zh)
    if len(ja_cues) != len(zh_cues):
        raise ValueError(f"cue count differs: {ja} {len(ja_cues)} vs {zh} {len(zh_cues)}")
    report = {**zh_metrics(zh_cues), **pair_metrics(ja_cues, zh_cues)}
    if bilingual:
        bi = read_srt(bilingual)
        report["bilingual_lines_per_cue"] = distribution([len(c["lines"]) for c in bi])
        report["bilingual_cues_over_2_lines"] = sum(1 for c in bi if len(c["lines"]) > 2)
    return report


def v4_reference_cues(root: Path, set_name: str) -> dict[str, list[tuple[dict, dict]]]:
    """字幕组复核中文按作品分组，配原日文 cue 的时间；类别作为键前缀。"""
    with open(root / "sets" / set_name / "scenes.jsonl", encoding="utf-8") as handle:
        scenes = [json.loads(line) for line in handle if line.strip()]
    with open(root / "evaluation-only" / set_name / "reference" / "cues.jsonl", encoding="utf-8") as handle:
        reference = {row["id"]: row["zh"] for row in map(json.loads, handle)}
    groups: dict[str, list[tuple[dict, dict]]] = {}
    for scene in scenes:
        for cue in scene["cues"]:
            timing = {"start": cue["start"], "end": cue["end"]}
            groups.setdefault(scene["category"], []).append(
                ({**timing, "lines": [cue["text"]]}, {**timing, "lines": [reference.get(cue["id"], "")]}))
    return groups


def main() -> int:
    parser = argparse.ArgumentParser(description="字幕可读性统计（离线）")
    sub = parser.add_subparsers(dest="command", required=True)
    srt = sub.add_parser("srt")
    srt.add_argument("--film", nargs=4, action="append", required=True, metavar=("NAME", "JA", "ZH", "BILINGUAL"))
    srt.add_argument("--out", type=Path, required=True)
    ref = sub.add_parser("v4ref")
    ref.add_argument("--root", type=Path, default=Path(".local/translation-evaluation/hy30-flow-v4"))
    ref.add_argument("--set", dest="set_name", default="dev")
    ref.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "srt":
        report = {name: film_report(Path(ja), Path(zh), Path(bi)) for name, ja, zh, bi in args.film}
    else:
        report = {}
        for category, pairs in v4_reference_cues(args.root, args.set_name).items():
            ja_cues, zh_cues = [p[0] for p in pairs], [p[1] for p in pairs]
            report[f"reference-{category}"] = {**zh_metrics(zh_cues), **pair_metrics(ja_cues, zh_cues)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for name, r in report.items():
        print(name, f"cues {r['cues']} cps p50 {r['cps']['p50']:.1f} p95 {r['cps']['p95']:.1f} "
                    f">9 {r['cps_over']['9']['share']:.1%} >15 {r['cps_over']['15']['share']:.1%} "
                    f"line p95 {r['line_length']['p95']:.0f} >16 {r['line_over']['16']['share']:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
