"""划组规则离线统计：dp10-cut 的包内，R1／R2 规则下小组的大小、截断、标点与停顿敏感性。

数据：v4 dev 集（研究集时间轴）与产品 ``ja.srt``（HF II／III，产品时间轴），加载沿用 ``scene_batching_v6.sim7``。
切包：``translation_v3`` 的 ``dp10-cut``（``build_batches``）。不改任何现有文件，不写 ``.local`` 以外的产物。

运行（worktree 里没有 ``.local/``，用 ``--local-root`` 指向有数据的 checkout）：
    PYTHONPATH=. python -X utf8 -m experiments.reorder_groups.stats --local-root D:/AI_Projects/kototoki/.local
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import unicodedata
from typing import Any, Iterable

from experiments.scene_batching_v6 import sim7
from experiments.translation_v3.batching import build_batches, silence
from experiments.translation_v3.data import Scene
from experiments.translation_v3.recipes import load_recipe

THRESHOLDS = (0.5, 0.8, 1.0, 1.5, 2.0)  # 任务要求前四个；2.0 用来读产品时间轴
FULL_END = "。？！"
EXT_END = "。？！?!."
CLOSERS = "」』）)】〕\"'”’"
QUESTION = "？?"
# 接续词（句首）。代理指标用，不求完整。
CONJUNCTIONS = ("そして", "それで", "それから", "それに", "だから", "ですから", "でも", "しかし", "だけど", "けど",
                "けれど", "だが", "ところが", "つまり", "ただ", "また", "さらに", "すると", "じゃあ", "では", "なので",
                "だって", "なぜなら", "あと", "それなら", "ならば", "あるいは", "もしくは", "で、")
# 句首助词／接续助词：说明上一行没说完，下一行是续接片段。
PARTICLES = ("が", "を", "に", "で", "と", "て", "の", "は", "も", "から", "ので", "のに", "って", "し", "けど")
ANSWERS = ("はい", "いいえ", "いえ", "うん", "ううん", "ええ", "いや", "ああ", "そう", "ほう", "へえ", "うむ", "なるほど")
LEADING = " \u3000「『（(【"


def tail(text: str, closers: bool) -> str:
    """去掉行尾空白（及可选的右括号／引号）后的最后一个字符，空串返回 ""。"""
    text = text.rstrip(" \u3000")
    while closers and text and text[-1] in CLOSERS:
        text = text[:-1].rstrip(" \u3000")
    return text[-1] if text else ""


def head(text: str) -> str:
    return text.lstrip(LEADING)


def ends_sentence(text: str, extended: bool) -> bool:
    """R2 的"句末标点"判定：extended=False 严格取 。？！（全角，不剥右括号）；True 加半角 ?!. 并剥右括号。"""
    char = tail(text, extended)
    return bool(char) and char in (EXT_END if extended else FULL_END)


def is_punct(char: str) -> bool:
    return bool(char) and unicodedata.category(char)[0] in "PS"


@dataclass(frozen=True)
class Rule:
    name: str
    sentence: str | None = None  # None: R1；"full": R2（严格 。？！）；"ext": R2+（含半角、剥右括号）

    def joins(self, scene: Scene, i: int, threshold: float) -> bool:
        """cue i 与 cue i+1 是否同组（缺时间戳按"无停顿"处理，与 gap_groups 一致）。"""
        gap = silence(scene, i)
        if gap is not None and gap >= threshold:
            return False
        return self.sentence is None or not ends_sentence(scene.cues[i].text, self.sentence == "ext")


R1, R2, R2X = Rule("R1"), Rule("R2", "full"), Rule("R2+", "ext")
RULES = (R1, R2, R2X)


def groups_in(scene: Scene, low: int, high: int, rule: Rule, threshold: float) -> list[tuple[int, int]]:
    """[low, high) 内的小组 [a, b)。"""
    out, a = [], low
    for i in range(low, high - 1):
        if not rule.joins(scene, i, threshold):
            out.append((a, i + 1))
            a = i + 1
    return out + [(a, high)]


def pack_ranges(scene: Scene, recipe: Any) -> list[tuple[int, int]]:
    return [(b.start, b.stop) for b in build_batches(scene, recipe)]


def in_pack_groups(scene: Scene, ranges: list[tuple[int, int]], rule: Rule, threshold: float) -> list[tuple[int, int]]:
    return [g for low, high in ranges for g in groups_in(scene, low, high, rule, threshold)]


def size_bucket(size: int) -> str:
    return "4+" if size >= 4 else str(size)


def size_distribution(sizes: Iterable[int]) -> dict[str, Any]:
    sizes = list(sizes)
    groups, cues = Counter(), Counter()
    for s in sizes:
        groups[size_bucket(s)] += 1
        cues[size_bucket(s)] += s
    total_g, total_c = len(sizes), sum(sizes)
    return {"groups": total_g, "cues": total_c, "max": max(sizes, default=0),
            "group_share": {k: groups[k] / total_g for k in ("1", "2", "3", "4+")},
            "cue_share": {k: cues[k] / total_c for k in ("1", "2", "3", "4+")}}


def truncation(scene_groups: list[tuple[list[tuple[int, int]], list[int]]]) -> dict[str, Any]:
    """整片划组后被切点截断的小组。scene_groups = [(整片小组, 包起点（不含 0）)]。"""
    multi = truncated = cues_total = cues_trunc = cuts = cuts_inside = oversize = small = small_trunc = 0
    for groups, starts in scene_groups:
        cut_set = set(starts)
        for a, b in groups:
            cues_total += b - a
            inside = [c for c in cut_set if a < c < b]
            cuts_inside += len(inside)
            if b - a > 1:
                multi += 1
                small += b - a <= 10
            if inside:
                truncated += 1
                cues_trunc += b - a
                oversize += b - a > 10
                small_trunc += b - a <= 10
        cuts += len(cut_set)
    return {"groups_multi": multi, "groups_truncated": truncated, "share_of_multi": truncated / multi,
            "cues": cues_total, "cues_in_truncated": cues_trunc, "cue_share": cues_trunc / cues_total,
            "cuts": cuts, "cuts_inside_group": cuts_inside, "cut_share_inside": cuts_inside / cuts,
            "truncated_oversize_gt10": oversize,
            "groups_le10_multi": small, "groups_le10_truncated": small_trunc,
            "share_of_le10_multi": small_trunc / small if small else 0.0}


def punctuation(scenes: list[Scene]) -> dict[str, Any]:
    texts = [c.text for s in scenes for c in s.cues]
    n = len(texts)
    chars = Counter()
    for t in texts:
        c = tail(t, False)
        chars[c if c and c in "。？！?!…、，," else ("other_punct" if is_punct(c) else "none")] += 1
    return {"cues": n,
            "end_full_sentence": sum(ends_sentence(t, False) for t in texts) / n,
            "end_ext_sentence": sum(ends_sentence(t, True) for t in texts) / n,
            "end_any_punct": sum(is_punct(tail(t, False)) for t in texts) / n,
            "end_ext_any_punct": sum(is_punct(tail(t, True)) for t in texts) / n,
            "by_char": {k: v / n for k, v in chars.most_common()}}


def pair_stats(scenes: list[Scene], ranges: dict[str, list[tuple[int, int]]], threshold: float) -> dict[str, Any]:
    """包内相邻 cue 对（停顿 < threshold）：R2 拆开的比例，以及说话人切换的代理指标。"""
    joined = split_strict = split_ext = 0
    q_prev = q_noconj = q_noconj_nopart = q_answer = 0
    r2_joined = r2_answer = 0
    for scene in scenes:
        for low, high in ranges[scene.scene_id]:
            for i in range(low, high - 1):
                if not R1.joins(scene, i, threshold):
                    continue
                joined += 1
                prev, nxt = scene.cues[i].text, head(scene.cues[i + 1].text)
                split_strict += ends_sentence(prev, False)
                split_ext += ends_sentence(prev, True)
                is_answer = nxt.startswith(ANSWERS)
                if (mark := tail(prev, True)) and mark in QUESTION:
                    q_prev += 1
                    noconj = not nxt.startswith(CONJUNCTIONS)
                    q_noconj += noconj
                    q_noconj_nopart += noconj and not nxt.startswith(PARTICLES)
                    q_answer += is_answer
                if R2X.joins(scene, i, threshold):
                    r2_joined += 1
                    r2_answer += is_answer
    return {"threshold": threshold, "joined_pairs": joined,
            "r2_split_share": split_strict / joined, "r2plus_split_share": split_ext / joined,
            "prev_question_share": q_prev / joined,
            "proxy_switch_share": q_noconj / joined,
            "proxy_switch_share_strict": q_noconj_nopart / joined,
            "question_then_answer_word_share": q_answer / joined,
            "r2plus_joined_pairs": r2_joined, "r2plus_next_answer_word_share": r2_answer / r2_joined}


def load_sets(local: Path) -> dict[str, list[Scene]]:
    dev = sim7.dev_scenes(local / "translation-evaluation/hy30-flow-v4")
    return {"dev_series": [s for s in dev if s.category == "anime_series"],
            "dev_movie": [s for s in dev if s.category == "animation_movie"],
            "dev": dev,
            "product": sim7.product_scenes(local / "quality-exploration-v5/01/out-w0")}


def analyse(local: Path) -> dict[str, Any]:
    recipe = load_recipe("dp10-cut", local / "gap-aware-batching-v7")
    sets = load_sets(local)
    report: dict[str, Any] = {"recipe": "dp10-cut", "recipe_hash": recipe.recipe_hash, "sets": {}}
    for name, scenes in sets.items():
        ranges = {s.scene_id: pack_ranges(s, recipe) for s in scenes}
        packs = [r for s in scenes for r in ranges[s.scene_id]]
        out: dict[str, Any] = {"scenes": len(scenes), "cues": sum(len(s.cues) for s in scenes), "packs": len(packs),
                               "pack_size_mean": sum(b - a for a, b in packs) / len(packs),
                               "punctuation": punctuation(scenes), "size": {}, "truncation": {}, "sweep": {}, "pairs": {}}
        gaps = [g for s in scenes for i in range(len(s.cues) - 1) if (g := silence(s, i)) is not None]
        out["gaps_lt0_share"] = sum(g < 0 for g in gaps) / len(gaps)
        cuts_gap = [g for s in scenes for _, high in ranges[s.scene_id][:-1] if (g := silence(s, high - 1)) is not None]
        out["pack_cuts"] = {"n": len(cuts_gap), **{f"share_lt_{t:g}s": sum(g < t for g in cuts_gap) / len(cuts_gap)
                                                   for t in THRESHOLDS}}
        for rule in RULES:
            out["size"][rule.name] = size_distribution(
                b - a for s in scenes for a, b in in_pack_groups(s, ranges[s.scene_id], rule, 1.0))
            whole = [(groups_in(s, 0, len(s.cues), rule, 1.0), [a for a, _ in ranges[s.scene_id][1:]]) for s in scenes]
            out["truncation"][rule.name] = {"whole_film_sizes": size_distribution(b - a for g, _ in whole for a, b in g),
                                            **truncation(whole)}
            for t in THRESHOLDS:
                dist = size_distribution(b - a for s in scenes for a, b in in_pack_groups(s, ranges[s.scene_id], rule, t))
                out["sweep"].setdefault(rule.name, {})[f"{t:g}"] = {
                    "multi_cue_cue_share": 1 - dist["cue_share"]["1"], "four_plus_cue_share": dist["cue_share"]["4+"],
                    "groups": dist["groups"], "max": dist["max"]}
        for t in THRESHOLDS:
            out["pairs"][f"{t:g}"] = pair_stats(scenes, ranges, t)
        report["sets"][name] = out
    return report


# ---- Markdown 输出 ----

def pct(x: float, digits: int = 1) -> str:
    return f"{100 * x:.{digits}f}%"


def table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(" --- " for _ in header) + "|"]
    return "\n".join(lines + ["| " + " | ".join(r) + " |" for r in rows])


def render(report: dict[str, Any]) -> str:
    sets = report["sets"]
    parts = [f"配方 `{report['recipe']}`，recipe_hash `{report['recipe_hash'][:12]}`", ""]
    parts += ["## 0 概览", table(["数据集", "场景", "cue", "包数", "平均包大小", "重叠间隔（停顿<0）占比", "切点处停顿 <0.5／<1.0 s"],
              [[n, str(s["scenes"]), str(s["cues"]), str(s["packs"]), f"{s['pack_size_mean']:.2f}", pct(s["gaps_lt0_share"]),
                f"{pct(s['pack_cuts']['share_lt_0.5s'])}／{pct(s['pack_cuts']['share_lt_1s'])}"] for n, s in sets.items()]), ""]
    parts += ["## 1 包内小组大小（停顿门槛 1.0 s）",
              table(["数据集", "规则", "小组数", "最大", "1 条 组%", "2 条 组%", "3 条 组%", "4+ 条 组%",
                     "1 条 cue%", "2 条 cue%", "3 条 cue%", "4+ 条 cue%"],
                    [[n, r, str(d["groups"]), str(d["max"]), *[pct(d["group_share"][k]) for k in ("1", "2", "3", "4+")],
                      *[pct(d["cue_share"][k]) for k in ("1", "2", "3", "4+")]]
                     for n, s in sets.items() for r, d in s["size"].items()]), ""]
    parts += ["## 2 整片划组后被切点截断的小组（门槛 1.0 s）",
              table(["数据集", "规则", "多 cue 组数", "被截断组数", "占多 cue 组", "受影响 cue", "占全部 cue", "切点落在组内", "被截断组中 >10 条",
                     "≤10 条的多 cue 组被截断"],
                    [[n, r, str(d["groups_multi"]), str(d["groups_truncated"]), pct(d["share_of_multi"]),
                      str(d["cues_in_truncated"]), pct(d["cue_share"]), f"{d['cuts_inside_group']}/{d['cuts']}（{pct(d['cut_share_inside'])}）",
                      str(d["truncated_oversize_gt10"]), pct(d["share_of_le10_multi"])]
                     for n, s in sets.items() for r, d in s["truncation"].items()]), "",
              "整片划组的组大小：",
              table(["数据集", "规则", "组数", "最大组", "4+ 条组覆盖的 cue%"],
                    [[n, r, str(d["whole_film_sizes"]["groups"]), str(d["whole_film_sizes"]["max"]),
                      pct(d["whole_film_sizes"]["cue_share"]["4+"])] for n, s in sets.items() for r, d in s["truncation"].items()]), ""]
    p = {n: s["punctuation"] for n, s in sets.items()}
    keys = ["。", "？", "！", "?", "!", "…", "、", "，", ",", "other_punct", "none"]
    parts += ["## 3 ja cue 行尾标点",
              table(["数据集", "cue", "行尾 。？！（全角）", "行尾 。？！?!.（含半角，剥右括号）", "行尾任何标点（P/S 类）", "剥右括号后任何标点"],
                    [[n, str(d["cues"]), pct(d["end_full_sentence"]), pct(d["end_ext_sentence"]), pct(d["end_any_punct"]),
                      pct(d["end_ext_any_punct"])] for n, d in p.items()]), "",
              "分字符（行尾最后一个非空白字符；不剥括号）：",
              table(["数据集", *keys], [[n, *[pct(d["by_char"].get(k, 0.0)) for k in keys]] for n, d in p.items()]), ""]
    parts += ["R1 连接对（包内，停顿 <门槛）被 R2 拆开的比例：",
              table(["数据集", "门槛", "R1 连接对", "R2 拆开（严格）", "R2+ 拆开（扩展）"],
                    [[n, t, str(d["joined_pairs"]), pct(d["r2_split_share"]), pct(d["r2plus_split_share"])]
                     for n, s in sets.items() for t, d in s["pairs"].items()]), ""]
    parts += ["## 4 停顿门槛敏感性（包内；多 cue 小组覆盖的 cue 比例／4+ 条小组覆盖的 cue 比例）"]
    for rule in (r.name for r in RULES):
        parts += [f"{rule}：", table(["数据集", *[f"{t:g} s" for t in THRESHOLDS]],
                  [[n, *[f"{pct(s['sweep'][rule][f'{t:g}']['multi_cue_cue_share'])}／{pct(s['sweep'][rule][f'{t:g}']['four_plus_cue_share'])}"
                         for t in THRESHOLDS]] for n, s in sets.items()]), ""]
    parts += ["## 5 说话人切换代理（包内相邻对，停顿 <1.0 s）",
              table(["数据集", "R1 连接对", "前行以 ？/? 结尾", "且下行无接续词（代理）", "再排除助词开头（严格代理）", "前行问句且下行答语词开头",
                     "R2+ 连接对", "其中下行答语词开头"],
                    [[n, str(d["joined_pairs"]), pct(d["prev_question_share"], 2), pct(d["proxy_switch_share"], 2),
                      pct(d["proxy_switch_share_strict"], 2), pct(d["question_then_answer_word_share"], 2),
                      str(d["r2plus_joined_pairs"]), pct(d["r2plus_next_answer_word_share"], 2)]
                     for n, s in sets.items() for d in [s["pairs"]["1"]]]), ""]
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--local-root", type=Path, default=sim7.REPO / ".local")
    parser.add_argument("--json", type=Path, help="可选：完整结果写入此 JSON（放 .local 下）")
    args = parser.parse_args(argv)
    report = analyse(args.local_root)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(render(report))


if __name__ == "__main__":
    main()
