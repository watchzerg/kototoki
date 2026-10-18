"""v8 重排率（§4.4）与显示校验器（§4.5）：只读 run 目录里的译文与场景时间，纯 CPU。

小组：按给定配方切包（``build_batches``），包内用 v8 共用的 R2+ 规则（``batching.sentence_groups``）划组；
配方本身不带 ``groups`` 时按 ``--gap``（默认 1.0 s）划组，所以 dp10-cut 对照与 grp1 候选的小组完全相同。

- 重排率：多 cue 小组内各条中文字数占比向量（字数／组内总字数）的 L1 差 ≥ 阈值记为"重排"；报 0.1／0.2／0.3
  三档（主阈值 0.2），另报译文逐字不同的多 cue 组比例（上界），以及单条小组 cue 的逐字不同条数（按所在包有无
  多 cue 组分开：无组包的 prompt 与对照逐字相同，有组包的 prompt 换了 joint 句并多一行 groups）。
- 显示校验：每条 cue 的读速（中文字数／时长，字/秒）p50／p90／p99 与超过阈值的比例；多 cue 组内每条
  "字数占比 − 时长占比"的绝对值最大者 ≥ 0.3 的组比例。

字数：去掉空白与 Unicode 标点／符号（P*、S* 类）后的字符数。

运行（worktree 里没有 ``.local/``，用 ``--local-root`` 指向有数据的 checkout）：
    PYTHONPATH=. python -X utf8 -m experiments.reorder_groups.checks --local-root D:/AI_Projects/kototoki/.local \\
        --set dev --recipe grp1 --control <对照 run 目录> --candidate <候选 run 目录> [--json <输出.json>]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import unicodedata
from typing import Any

from experiments.scene_batching_v6 import sim7
from experiments.translation_v3.batching import build_batches, sentence_groups
from experiments.translation_v3.data import Scene
from experiments.translation_v3.generate import load_run_translations
from experiments.translation_v3.recipes import Recipe, load_recipe

REORDER_THRESHOLDS = (0.1, 0.2, 0.3)
REORDER_MAIN = 0.2
# 读速阈值（字/秒）：Netflix 简体中文字幕规范的成人节目上限 9 字/秒（儿童 7）；本仓库没有自己的读速规范。
READING_SPEED_MAX = 9.0
SHARE_DEVIATION_MAX = 0.3


def zh_len(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace() and unicodedata.category(ch)[0] not in "PS")


def shares(values: list[float]) -> list[float] | None:
    total = sum(values)
    return [v / total for v in values] if total > 0 else None


def l1(a: list[float], b: list[float]) -> float:
    return sum(abs(x - y) for x, y in zip(a, b))


def pack_groups(scene: Scene, recipe: Recipe, gap: float) -> list[list[tuple[str, ...]]]:
    """每个包的全部小组（含单条组），目标 cue ID 元组。"""
    gap = recipe.groups["gap"] if recipe.groups else gap
    ids = scene.ids
    return [[tuple(ids[a:b]) for a, b in sentence_groups(scene, batch.start, batch.stop, gap)]
            for batch in build_batches(scene, recipe)]


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[round(q * 100) - 1]


def reorder(packs: list[list[tuple[str, ...]]], control: dict[str, str], candidate: dict[str, str]) -> dict[str, Any]:
    """候选相对对照的重排率；任一侧缺译文（失败场景）的组跳过并计数。"""
    diffs: list[float] = []
    verbatim = skipped = 0
    single = {"in_grouped_packs": [0, 0], "in_ungrouped_packs": [0, 0]}  # [cue 数, 逐字不同]
    for groups in packs:
        key = "in_grouped_packs" if any(len(g) > 1 for g in groups) else "in_ungrouped_packs"
        for group in groups:
            if any(c not in control or c not in candidate for c in group):
                skipped += 1
                continue
            if len(group) == 1:
                single[key][0] += 1
                single[key][1] += control[group[0]] != candidate[group[0]]
                continue
            a = shares([zh_len(control[c]) for c in group])
            b = shares([zh_len(candidate[c]) for c in group])
            verbatim += any(control[c] != candidate[c] for c in group)
            if a is None or b is None:
                skipped += 1
                continue
            diffs.append(l1(a, b))
    n = len(diffs)
    return {"multi_groups": n, "skipped_groups": skipped,
            "reordered_share": {f"{t:g}": (sum(d >= t for d in diffs) / n if n else None) for t in REORDER_THRESHOLDS},
            "main_threshold": REORDER_MAIN,
            "verbatim_different_share": verbatim / n if n else None,
            "l1_p50": quantile(diffs, 0.5), "l1_p90": quantile(diffs, 0.9),
            "single_cues": {k: {"cues": v[0], "verbatim_different": v[1]} for k, v in single.items()}}


def display(scene_packs: list[tuple[Scene, list[list[tuple[str, ...]]]]], translations: dict[str, str]) -> dict[str, Any]:
    """读速分布与多 cue 组的占比偏差；缺时间戳或时长 ≤0 的 cue 不计读速，含这类 cue 的组不计偏差。"""
    speeds: list[float] = []
    flagged = groups_n = 0
    deviations: list[float] = []
    for scene, packs in scene_packs:
        cues = {c.id: c for c in scene.cues}
        duration = {k: c.end - c.start for k, c in cues.items()
                    if c.start is not None and c.end is not None and c.end > c.start}
        for key, text in ((k, translations[k]) for k in cues if k in translations and k in duration):
            speeds.append(zh_len(text) / duration[key])
        for group in (g for groups in packs for g in groups if len(g) > 1):
            if any(c not in translations or c not in duration for c in group):
                continue
            chars = shares([zh_len(translations[c]) for c in group])
            if chars is None:
                continue
            times = shares([duration[c] for c in group])
            worst = max(abs(x - y) for x, y in zip(chars, times))
            deviations.append(worst)
            groups_n += 1
            flagged += worst >= SHARE_DEVIATION_MAX
    n = len(speeds)
    return {"cues": n, "reading_speed": {"p50": quantile(speeds, 0.5), "p90": quantile(speeds, 0.9),
                                         "p99": quantile(speeds, 0.99)},
            "reading_speed_max": READING_SPEED_MAX,
            "over_speed_share": sum(s > READING_SPEED_MAX for s in speeds) / n if n else None,
            "multi_groups": groups_n, "share_deviation_max": SHARE_DEVIATION_MAX,
            "deviation_flagged_share": flagged / groups_n if groups_n else None,
            "deviation_p90": quantile(deviations, 0.9)}


def load_set(name: str, local: Path) -> list[Scene]:
    if name == "dev":
        return sim7.dev_scenes(local / "translation-evaluation/hy30-flow-v4")
    if name == "product":
        return sim7.product_scenes(local / "quality-exploration-v5/01/out-w0")
    raise ValueError(f"unknown set {name!r}")


def analyse(scenes: list[Scene], recipe: Recipe, gap: float, runs: dict[str, Path]) -> dict[str, Any]:
    """runs: {"control": 目录, "candidate": 目录}（至少一个）。只看两侧都出现的场景。"""
    raw = {arm: load_run_translations(path) for arm, path in runs.items()}
    loaded = {arm: translations for arm, (translations, _) in raw.items()}
    covered = [set(translations) | failed for translations, failed in raw.values()]
    scenes = [s for s in scenes if all(any(c.id in cov for c in s.cues) for cov in covered)]
    report: dict[str, Any] = {"recipe": recipe.name, "recipe_hash": recipe.recipe_hash, "gap": gap,
                              "runs": {arm: str(path) for arm, path in runs.items()}, "by_category": {}}
    categories = sorted({s.category or "unknown" for s in scenes})
    for category in ["all", *categories]:
        chosen = [s for s in scenes if category == "all" or (s.category or "unknown") == category]
        scene_packs = [(s, pack_groups(s, recipe, gap)) for s in chosen]
        block: dict[str, Any] = {"scenes": len(chosen), "display": {arm: display(scene_packs, t) for arm, t in loaded.items()}}
        if {"control", "candidate"} <= set(loaded):
            block["reorder"] = reorder([p for _, packs in scene_packs for p in packs], loaded["control"], loaded["candidate"])
        report["by_category"][category] = block
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--local-root", type=Path, default=sim7.REPO / ".local")
    parser.add_argument("--set", choices=("dev", "product"), required=True)
    parser.add_argument("--recipe", default="grp1", help="切包配方（builtin 或 --recipe-root 下的 recipes/<name>.json）")
    parser.add_argument("--recipe-root", type=Path)
    parser.add_argument("--gap", type=float, default=1.0, help="配方不带 groups 时的划组停顿门槛（秒）")
    parser.add_argument("--control", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--json", type=Path, help="可选：完整结果写入此 JSON（放 .local 下）")
    args = parser.parse_args(argv)
    runs = {arm: path for arm, path in (("control", args.control), ("candidate", args.candidate)) if path}
    if not runs:
        parser.error("need --control and/or --candidate")
    report = analyse(load_set(args.set, args.local_root), load_recipe(args.recipe, args.recipe_root), args.gap, runs)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
