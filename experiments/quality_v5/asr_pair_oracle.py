"""w0／x0 两路 ASR 交叉合并的理论上限测算（离线、零 GPU、不加载任何模型）。

口径沿用 `asr_source.py`：`kototoki_eval.schema.normalize` 规范化，参考 cue 与产品 cue 按时间重叠（交集 > 0）连成
连通分量作为"单元"；区别是这里三条轨道（参考、w0、x0）一起连，因此单元比两轨更粗。

四种对象，均按单元累计字符级编辑距离（S／D／I 分开）：
  w0、x0      各自单路。
  select      oracle 选择：每单元取 w0／x0 中编辑距离更小者（平局取 w0）。
  splice      oracle 拼接：w0 与 x0 字符级对齐，找出分歧区间；对参考做"晶格编辑距离"（每个分歧区间二选一），
              全局最优地逐区间取更接近参考者。splice ≤ select ≤ min(w0, x0)。
这些都需要参考答案，是上界而非可实现的合并；单元内局部对齐的 S／D／I 与整片全局对齐的官方数字略有出入，
编辑总量以单元对齐为准，官方数字另列作对照。

命令（仓库根目录）：python -X utf8 -m experiments.quality_v5.asr_pair_oracle [--out-dir DIR] [--samples N]
"""

import argparse
import json
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from kototoki_eval.schema import normalize

from .asr_source import load_reference, read_srt

LOCAL = Path(".local")
V5 = LOCAL / "quality-exploration-v5"
REFERENCES = LOCAL / "fullfilm-comparison/fullfilm-v1/corpus/references"
FILMS = {
    "hf-ii": {"name": "FateStay Night Heaven’s Feel II", "reference": REFERENCES / "hf-ii-full.json"},
    "hf-iii": {"name": "FateStay Night Heaven's Feel III", "reference": REFERENCES / "hf-iii-full.json"},
}
TRACKS = ("ref", "w0", "x0")
BIN_SECONDS = 300


def clean(cues: list[dict], ids: list[int]) -> str:
    """按下标顺序拼接并规范化（逐 cue 规范化后相连，避免跨 cue 的 NFKC 簇问题）。"""
    return "".join(normalize(cues[i]["text"]).text for i in ids)


# ---------- 单元：多轨道时间重叠连通分量 ----------

def overlap_components(tracks: dict[str, list[dict]]) -> list[dict[str, list[int]]]:
    """各轨道 cue 之间交集 > 0 的连成连通分量（同轨道 cue 不直接相连）。返回按起点排序的 {轨道: [下标]}。"""
    nodes = [(cue["start"], cue["end"], name, i) for name, cues in tracks.items() for i, cue in enumerate(cues)]
    nodes.sort()
    parent = {(name, i): (name, i) for _, _, name, i in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    active: list[tuple[float, str, int, float]] = []  # (end, track, index, start)
    for start, end, name, i in nodes:
        active = [a for a in active if a[0] > start]
        for a_end, a_name, a_i, a_start in active:
            if a_name != name and min(end, a_end) - max(start, a_start) > 0:
                parent[find((name, i))] = find((a_name, a_i))
        active.append((end, name, i, start))
    groups: dict = {}
    for _, _, name, i in nodes:
        groups.setdefault(find((name, i)), {t: [] for t in tracks})[name].append(i)
    units = []
    for group in groups.values():
        for ids in group.values():
            ids.sort()
        units.append(group)

    def first_start(group):
        return min(tracks[name][i]["start"] for name, ids in group.items() for i in ids)

    return sorted(units, key=first_start)


@dataclass
class Unit:
    unit_id: str
    start: float
    end: float
    ids: dict[str, list[int]]
    texts: dict[str, str]  # 规范化后的 ref／w0／x0


def build_units(film: str, tracks: dict[str, list[dict]]) -> list[Unit]:
    units = []
    for n, group in enumerate(overlap_components(tracks), 1):
        times = [tracks[t][i][k] for t, ids in group.items() for i in ids for k in ("start", "end")]
        units.append(Unit(f"{film}-u{n:04d}", min(times), max(times), group,
                          {t: clean(tracks[t], group[t]) for t in TRACKS}))
    return units


# ---------- 字符级编辑距离与对齐 ----------

def align_ops(a: str, b: str) -> list[tuple[str, int, int]]:
    """Levenshtein 回溯，返回 (op, i, j)：M 匹配、S 替换、D（a 有 b 无）、I（b 有 a 无）。i／j 为 a／b 中字符下标
    （D 的 j、I 的 i 为该处的对应位置，仅供参考）。平局优先对角，其次 D，最后 I。"""
    n, m = len(a), len(b)
    table = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        table[i][0] = i
    for j in range(m + 1):
        table[0][j] = j
    for i in range(1, n + 1):
        row, prev = table[i], table[i - 1]
        for j in range(1, m + 1):
            row[j] = min(prev[j - 1] + (a[i - 1] != b[j - 1]), prev[j] + 1, row[j - 1] + 1)
    ops = []
    i, j = n, m
    while i or j:
        if i and j and table[i][j] == table[i - 1][j - 1] + (a[i - 1] != b[j - 1]):
            ops.append(("M" if a[i - 1] == b[j - 1] else "S", i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i and table[i][j] == table[i - 1][j] + 1:
            ops.append(("D", i - 1, j))
            i -= 1
        else:
            ops.append(("I", i, j - 1))
            j -= 1
    ops.reverse()
    return ops


def sdi(reference: str, hypothesis: str) -> dict[str, int]:
    counts = Counter(op for op, _, _ in align_ops(reference, hypothesis))
    return {"S": counts["S"], "D": counts["D"], "I": counts["I"]}


def edits(counts: dict[str, int]) -> int:
    return counts["S"] + counts["D"] + counts["I"]


def correct_reference_chars(reference: str, hypothesis: str) -> list[bool]:
    """每个参考字符是否被该假设精确匹配。"""
    flags = [False] * len(reference)
    for op, i, _ in align_ops(reference, hypothesis):
        if op == "M":
            flags[i] = True
    return flags


# ---------- 分歧区间与 oracle 拼接 ----------

def disagreement_intervals(w0: str, x0: str) -> list[dict]:
    """w0 与 x0 字符级对齐，非匹配操作的极大连续段为一个分歧区间（相隔至少一个匹配字符才分开）。"""
    intervals: list[dict] = []
    current = None
    for op, i, j in align_ops(w0, x0):
        if op == "M":
            current = None
            continue
        if current is None:
            current = {"w_start": i, "w_end": i, "x_start": j, "x_end": j}
            intervals.append(current)
        if op in ("S", "D"):
            current["w_end"] = i + 1
        if op in ("S", "I"):
            current["x_end"] = j + 1
    for it in intervals:
        it["w"], it["x"] = w0[it["w_start"]:it["w_end"]], x0[it["x_start"]:it["x_end"]]
    return intervals


def _advance(frontier: list[int], text: str, reference: str) -> list[int]:
    """晶格 DP：frontier[j] 为已消耗的假设与 reference[:j] 的最小编辑代价；吃入 text。"""
    for ch in text:
        new = [frontier[0] + 1]
        for j in range(1, len(frontier)):
            new.append(min(frontier[j] + 1, frontier[j - 1] + (reference[j - 1] != ch), new[j - 1] + 1))
        frontier = new
    return frontier


def lattice_pick(reference: str, w0: str, x0: str, intervals: list[dict]) -> list[str]:
    """逐区间在 w0／x0 间选择使整体编辑距离最小的一方（"w"／"x"，平局取 w0）。顺序提交前缀，保证全局最优。"""
    if not intervals:
        return []
    parts: list[tuple[str, str]] = []  # (w 串, x 串)，公共段两者相同
    cursor = 0
    for it in intervals:
        parts.append((w0[cursor:it["w_start"]],) * 2)
        parts.append((it["w"], it["x"]))
        cursor = it["w_end"]
    parts.append((w0[cursor:],) * 2)
    n = len(reference)
    reversed_reference = reference[::-1]
    # 后缀代价：B[k][j] = 从第 k 部分起的假设后缀与 reference[j:] 的最小代价
    suffix = [None] * (len(parts) + 1)
    frontier = list(range(n + 1))
    suffix[len(parts)] = frontier[::-1]
    for k in range(len(parts) - 1, -1, -1):
        w_part, x_part = parts[k]
        if w_part == x_part:
            frontier = _advance(frontier, w_part[::-1], reversed_reference)
        else:
            a = _advance(frontier, w_part[::-1], reversed_reference)
            b = _advance(frontier, x_part[::-1], reversed_reference)
            frontier = [min(p, q) for p, q in zip(a, b)]
        suffix[k] = frontier[::-1]
    picks = []
    front = list(range(n + 1))
    for k, (w_part, x_part) in enumerate(parts):
        if w_part == x_part:
            front = _advance(front, w_part, reference)
            continue
        after_w = _advance(front, w_part, reference)
        after_x = _advance(front, x_part, reference)
        total_w = min(f + s for f, s in zip(after_w, suffix[k + 1]))
        total_x = min(f + s for f, s in zip(after_x, suffix[k + 1]))
        if total_x < total_w:
            picks.append("x")
            front = after_x
        else:
            picks.append("w")
            front = after_w
    return picks


def compose(w0: str, intervals: list[dict], picks: list[str]) -> str:
    out = []
    cursor = 0
    for it, pick in zip(intervals, picks):
        out.append(w0[cursor:it["w_start"]])
        out.append(it[pick])
        cursor = it["w_end"]
    out.append(w0[cursor:])
    return "".join(out)


# ---------- 汇总 ----------

def add(total: dict[str, int], counts: dict[str, int]) -> None:
    for key in "SDI":
        total[key] += counts[key]


def new_total() -> dict[str, int]:
    return {"S": 0, "D": 0, "I": 0}


def cer_row(total: dict[str, int], ref_chars: int) -> dict:
    return {**total, "edits": edits(total), "CER": edits(total) / ref_chars if ref_chars else None}


def interval_kind(it: dict) -> str:
    if it["w"] and it["x"]:
        return "替换"
    return "w0 多出" if it["w"] else "x0 多出"


def interval_length_class(it: dict) -> str:
    length = max(len(it["w"]), len(it["x"]))
    return "1" if length == 1 else "2" if length == 2 else "3–5" if length <= 5 else "6–15" if length <= 15 else ">15"


def analyze_film(film: str, units: list[Unit]) -> dict:
    ref_chars = sum(len(u.texts["ref"]) for u in units)
    singles = {"w0": new_total(), "x0": new_total()}
    select, splice = new_total(), new_total()
    gains = {"both_present": [0, 0, 0], "w0_only": [0, 0, 0], "x0_only": [0, 0, 0], "neither": [0, 0, 0]}
    # 各类单元：[数量, w0 编辑, oracle 选择编辑, oracle 拼接编辑] 的累计
    status_rows: dict[str, dict[str, int]] = {}
    corr_units = Counter()
    corr_chars = Counter()
    both_wrong_same = 0
    disagreement_units = 0
    disagreement_chars = 0
    w0_chars = x0_chars = 0
    intervals_all: list[dict] = []
    interval_stats = {"kind": Counter(), "length": Counter(), "position": Counter(), "unit_status": Counter(),
                      "chars_kind": Counter(), "chars_length": Counter(), "chars_position": Counter(),
                      "chars_unit_status": Counter()}
    bin_chars: Counter = Counter()
    pick_counts = Counter()
    for unit in units:
        ref, w0, x0 = unit.texts["ref"], unit.texts["w0"], unit.texts["x0"]
        w0_chars += len(w0)
        x0_chars += len(x0)
        c_w, c_x = sdi(ref, w0), sdi(ref, x0)
        add(singles["w0"], c_w)
        add(singles["x0"], c_x)
        chosen = c_x if edits(c_x) < edits(c_w) else c_w
        add(select, chosen)
        intervals = disagreement_intervals(w0, x0)
        picks = lattice_pick(ref, w0, x0, intervals)
        spliced = sdi(ref, compose(w0, intervals, picks))
        add(splice, spliced)
        status = ("both_present" if w0 and x0 else "w0_only" if w0 else "x0_only" if x0 else "neither")
        if status in gains:
            row = gains[status]
            row[0] += edits(c_w)
            row[1] += edits(chosen)
            row[2] += edits(spliced)
        status_row = status_rows.setdefault(status, {"units": 0, "ref_chars": 0, "w0_edits": 0, "x0_edits": 0,
                                                     "select_edits": 0, "splice_edits": 0})
        status_row["units"] += 1
        status_row["ref_chars"] += len(ref)
        status_row["w0_edits"] += edits(c_w)
        status_row["x0_edits"] += edits(c_x)
        status_row["select_edits"] += edits(chosen)
        status_row["splice_edits"] += edits(spliced)
        # 单元级相关性（只统计有参考的单元；"对"＝编辑距离 0）
        if ref:
            w_ok, x_ok = edits(c_w) == 0, edits(c_x) == 0
            corr_units[("w0 对" if w_ok else "w0 错", "x0 对" if x_ok else "x0 错")] += 1
            if not w_ok and not x_ok and w0 == x0:
                both_wrong_same += 1
            w_flags = correct_reference_chars(ref, w0)
            x_flags = correct_reference_chars(ref, x0)
            for a, b in zip(w_flags, x_flags):
                corr_chars[("w0 对" if a else "w0 错", "x0 对" if b else "x0 错")] += 1
        # 分歧统计
        if w0 != x0:
            disagreement_units += 1
        for k, (it, pick) in enumerate(zip(intervals, picks)):
            size = max(len(it["w"]), len(it["x"]))
            disagreement_chars += size
            rel = ("头" if it["w_start"] == 0 else "尾" if it["w_end"] == len(w0) else "中")
            kind, length = interval_kind(it), interval_length_class(it)
            for key, value in (("kind", kind), ("length", length), ("position", rel), ("unit_status", status)):
                interval_stats[key][value] += 1
                interval_stats["chars_" + key][value] += size
            bin_chars[int(unit.start // BIN_SECONDS)] += size
            pick_counts[pick] += 1
            intervals_all.append({"film": film, "unit_id": unit.unit_id, "interval": k, "start": unit.start,
                                  "w": it["w"], "x": it["x"], "kind": kind, "position": rel, "status": status,
                                  "oracle_pick": "w0" if pick == "w" else "x0",
                                  "ref_unit": ref, "w0_unit": w0, "x0_unit": x0})
        if not intervals and w0 != x0:  # 保险：对齐无分歧而文本不同不应发生
            raise AssertionError(unit.unit_id)
    ranked = sorted(bin_chars.values(), reverse=True)
    top_bins = max(1, round(0.1 * len(bin_chars)))
    return {
        "film": film, "units": len(units), "ref_chars": ref_chars, "w0_chars": w0_chars, "x0_chars": x0_chars,
        "ref_cues": sum(len(u.ids["ref"]) for u in units), "w0_cues": sum(len(u.ids["w0"]) for u in units),
        "x0_cues": sum(len(u.ids["x0"]) for u in units),
        "max_unit_cues": max(sum(len(i) for i in u.ids.values()) for u in units),
        "cer": {"w0": cer_row(singles["w0"], ref_chars), "x0": cer_row(singles["x0"], ref_chars),
                "select": cer_row(select, ref_chars), "splice": cer_row(splice, ref_chars)},
        "by_status": status_rows,
        "disagreement": {"units": disagreement_units, "unit_share": disagreement_units / len(units),
                         "units_with_text": sum(1 for u in units if u.texts["w0"] or u.texts["x0"]),
                         "intervals": len(intervals_all), "chars": disagreement_chars,
                         "char_share_of_w0": disagreement_chars / w0_chars if w0_chars else None,
                         "char_share_of_ref": disagreement_chars / ref_chars,
                         "oracle_pick": dict(pick_counts),
                         "top10pct_bins_char_share": sum(ranked[:top_bins]) / disagreement_chars if disagreement_chars else None,
                         **{key: dict(value) for key, value in interval_stats.items()}},
        "correlation_units": {f"{a}／{b}": n for (a, b), n in sorted(corr_units.items())},
        "correlation_chars": {f"{a}／{b}": n for (a, b), n in sorted(corr_chars.items())},
        "both_wrong_identical_units": both_wrong_same,
        "_intervals": intervals_all,
    }


def merge_films(per_film: list[dict]) -> dict:
    """两部合计：字符数、编辑量直接相加。"""
    ref_chars = sum(f["ref_chars"] for f in per_film)
    out = {"ref_chars": ref_chars, "cer": {}}
    for name in ("w0", "x0", "select", "splice"):
        total = {k: sum(f["cer"][name][k] for f in per_film) for k in "SDI"}
        out["cer"][name] = cer_row(total, ref_chars)
    return out


def sample_intervals(intervals: list[dict], n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    chosen = sorted(rng.sample(range(len(intervals)), min(n, len(intervals))))
    return [dict(intervals[i], sample_id=k + 1) for k, i in enumerate(chosen)]


def run(out_dir: Path, samples: int, seed: int, root: Path = Path(".")) -> dict:
    per_film, all_intervals = [], []
    for film, spec in FILMS.items():
        reference = load_reference(root / spec["reference"])
        tracks = {"ref": reference}
        for engine in ("w0", "x0"):
            tracks[engine] = read_srt(root / V5 / f"01/out-{engine}/{spec['name']}.ja.srt")
        units = build_units(film, tracks)
        result = analyze_film(film, units)
        result["cue_counts"] = {t: len(c) for t, c in tracks.items()}
        all_intervals.extend(result.pop("_intervals"))
        per_film.append(result)
    report = {"films": per_film, "total": merge_films(per_film), "seed": seed}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    picked = sample_intervals(all_intervals, samples, seed)
    (out_dir / "samples.json").write_text(json.dumps(picked, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "intervals.jsonl").write_text(
        "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in all_intervals), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="w0／x0 交叉合并 oracle 上限测算（纯 CPU）")
    parser.add_argument("--out-dir", type=Path, default=V5 / "asr-pair-oracle")
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20261019)
    args = parser.parse_args()
    report = run(args.out_dir, args.samples, args.seed)
    for film in report["films"]:
        print(film["film"], {k: (round(v["CER"], 4), v["S"], v["D"], v["I"]) for k, v in film["cer"].items()})
    print("total", {k: round(v["CER"], 4) for k, v in report["total"]["cer"].items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
