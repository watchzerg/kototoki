"""v8 票据 07：备选路线预检——每个多 cue 小组由程序合成一个源条目，模型整句翻译，再离线与逐行对照比较。

读票据 02 两份小样（``02b`` 为主、``02`` 为对话对照）的 20 个包，按 ``dp10-cut`` 重新切包核对 ID 并取 cue 时间；
每包把每个多 cue 小组换成一个上下文条目（ID ``<首条 ID>~<行数>``，日文各行以全角空格连接），单条目标与只读邻文不变；
用 ``dp10-cut`` 原样的 joint v1 提示渲染（不注入 groups、不加新措辞），grammar 按合并后的目标 ID 生成。

离线比较（每个多 cue 小组）：对照逐行中文拼接 vs 合并译文的 ``SequenceMatcher`` 相似度、字数、去标点后是否相同；
语序（对照各行片段在合并译文中的最长公共子串位置是否保持行序）；切回可行性（只在合并译文的中文标点处切 n−1 刀，
DP 最小化各行"字数占比 − 时长占比"的最大绝对值，≤ ``checks.SHARE_DEVIATION_MAX`` 记为可切）。

``--dry-run`` 只渲染提示；``--reuse <probe.json>`` 复用已生成的合并译文、只重算比较。真实生成与 ``sample.py`` 同一条链路（``managed_session_factory``、``run_step``、配方采样），
不是 ``run_generation`` 的 run，不能裁判。输出 ``<out>/probe.json`` 与 ``<out>/probe.md``（含原文，放 ``.local`` 不入库）。

    PYTHONPATH=. python -X utf8 -m experiments.reorder_groups.merge_probe [--dry-run] [--out .local/group-reorder-v8/02c]
"""

from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import json
from pathlib import Path
import statistics
import time
from typing import Any

from experiments.scene_batching_v6 import sim7
from experiments.translation_v3 import recipes as R
from experiments.translation_v3.batching import Batch, build_batches
from experiments.translation_v3.common import REPO, atomic_write_json, sha256_bytes
from experiments.translation_v3.data import Scene
from experiments.translation_v3.generate import StepFailed, managed_session_factory, run_step

from .checks import SHARE_DEVIATION_MAX, zh_len

V8_ROOT = REPO / ".local/group-reorder-v8"
CONTROL = "dp10-cut"
# 噪声参照：同一小样里 grp1 臂（同样逐行输出、只换了 joint 句与 groups 行）对对照的拼接相似度。
REFERENCE = "grp1"
JOINER = "　"
SPLIT_MARKS = "，、。？！…；：,?!;:"
MIN_MATCH = 3


def merged_key(group: list[str]) -> str:
    return f"{group[0]}~{len(group)}"


def units(target_ids: list[str], groups: list[list[str]]) -> list[tuple[str, list[str]]]:
    """目标按源顺序折叠：多 cue 小组 → (合并 ID, 各行 ID)，单条 → (ID, [ID])。"""
    first = {g[0]: g for g in groups if len(g) > 1}
    inside = {i for g in first.values() for i in g}
    out = []
    for i in target_ids:
        if i in first:
            out.append((merged_key(first[i]), list(first[i])))
        elif i not in inside:
            out.append((i, [i]))
    if [c for _, cues in out for c in cues] != list(target_ids):
        raise ValueError("Groups must be contiguous runs of target IDs")
    return out


def merged_window(scene: Scene, batch: Batch, groups: list[list[str]]) -> tuple[dict[str, Any], list[tuple[str, list[str]]]]:
    text = {cue.id: cue.text for cue in scene.cues}
    folded = units(list(batch.target_ids), groups)
    context = ([{"id": k, "text": text[k]} for k in batch.before_ids]
               + [{"id": key, "text": JOINER.join(text[c] for c in cues)} for key, cues in folded]
               + [{"id": k, "text": text[k]} for k in batch.after_ids])
    window = {"id": batch.batch_id, "source_language": "ja", "target_language": "zh-Hans",
              "context": context, "translate_ids": [key for key, _ in folded]}
    return window, folded


def render(scene: Scene, batch: Batch, groups: list[list[str]], recipe: R.Recipe) -> tuple[str, str, list[str], list]:
    window, folded = merged_window(scene, batch, groups)
    prompt = R.render_translation(recipe, window, [], None, scene.work_id)
    ids = window["translate_ids"]
    return prompt, R.translation_grammar(recipe, ids), ids, folded


def plan(samples: list[tuple[str, dict[str, Any]]], scenes: list[Scene]) -> list[dict[str, Any]]:
    recipe = R.load_recipe(CONTROL)
    by_id = {s.scene_id: s for s in scenes}
    rows = []
    for label, report in samples:
        for pack in report["packs"]:
            scene = by_id[pack["scene_id"]]
            batch = next(b for b in build_batches(scene, recipe) if b.index == pack["batch_index"])
            if (list(batch.target_ids), list(batch.before_ids), list(batch.after_ids)) != (
                    pack["target_ids"], pack["before_ids"], pack["after_ids"]):
                raise RuntimeError(f"{pack['scene_id']} b{pack['batch_index']}: batch differs from sample.json")
            prompt, grammar, ids, folded = render(scene, batch, pack["groups"], recipe)
            control = pack["arms"][CONTROL]
            cues = {c.id: c for c in scene.cues}
            rows.append({"sample": label, "scene_id": scene.scene_id, "category": scene.category,
                         "batch_index": batch.index, "target_ids": pack["target_ids"],
                         "before_ids": pack["before_ids"], "after_ids": pack["after_ids"],
                         "units": [[key, cues_] for key, cues_ in folded], "ja": pack["ja"],
                         "durations": {i: (cues[i].end - cues[i].start
                                           if cues[i].start is not None and cues[i].end is not None else None)
                                       for i in pack["target_ids"]},
                         "control": {k: control.get(k) for k in ("translations", "input_tokens", "output_tokens",
                                                                 "seconds")},
                         "reference": (pack["arms"].get(REFERENCE) or {}).get("translations"),
                         "merged": {"recipe_hash": recipe.recipe_hash, "prompt_sha256": sha256_bytes(prompt.encode()),
                                    "prompt_chars": len(prompt), "_prompt": prompt, "_grammar": grammar, "_ids": ids,
                                    "_sampling": recipe.sampling}})
    return rows


def generate(rows: list[dict[str, Any]], seed: int, out: Path, *, port: int) -> None:
    factory = managed_session_factory(V8_ROOT, f"merge-probe__s{seed}__dev02c", port=port)
    cache_state: dict[str, Any] = {"checked": False}
    with factory(out, 0) as handle:
        for number, row in enumerate(rows, 1):
            info = row["merged"]
            record: dict[str, Any] = {"stage": "translation"}
            started = time.perf_counter()
            try:
                info["translations"] = run_step(handle.client, info["_prompt"], info["_grammar"], seed,
                                                lambda text, ids=info["_ids"]: R.parse_translation(text, ids),
                                                cache_state, record, info["_sampling"])
            except StepFailed as exc:
                info["translations"] = None
                info["error"] = {"kind": exc.kind, "error": str(exc)[:500]}
                if exc.kind in ("oom", "cache", "server"):
                    raise
            attempt = record["attempts"][-1]
            info.update(input_tokens=attempt.get("input_tokens"), output_tokens=attempt.get("output_tokens"),
                        seconds=time.perf_counter() - started, attempts=len(record["attempts"]))
            print(f"{number}/{len(rows)} {row['sample']} {row['scene_id']} b{row['batch_index']}: "
                  f"{'ok' if info['translations'] else info['error']['kind']} {info['seconds']:.1f}s")


# --- offline comparison ---------------------------------------------------------------

def bare(text: str) -> str:
    """去掉空白与标点／符号（与 ``zh_len`` 同口径）。"""
    return "".join(ch for ch in text if zh_len(ch))


def order(pieces: list[str], merged: str) -> dict[str, Any]:
    """各行片段（去标点）在合并译文（去标点）里的最长公共子串起点；任一片段匹配长度 < min(3, 片段长) 记 unmatched。"""
    target = bare(merged)
    starts: list[int | None] = []
    for piece in (bare(p) for p in pieces):
        need = min(MIN_MATCH, len(piece))
        m = SequenceMatcher(None, piece, target, autojunk=False).find_longest_match(0, len(piece), 0, len(target))
        starts.append(m.b if need and m.size >= need else None)
    if any(s is None for s in starts):
        verdict = "unmatched"
    else:
        verdict = "same_order" if all(a < b for a, b in zip(starts, starts[1:])) else "reordered"
    return {"verdict": verdict, "starts": starts}


def max_deviation(chars: list[int], durations: list[float]) -> float | None:
    if sum(chars) <= 0 or sum(durations) <= 0:
        return None
    return max(abs(c / sum(chars) - d / sum(durations)) for c, d in zip(chars, durations))


def split_points(text: str, n: int, durations: list[float]) -> dict[str, Any]:
    """只在中文标点之后切 n−1 刀，DP 最小化 max |字数占比 − 时长占比|。"""
    marks = [i + 1 for i, ch in enumerate(text) if ch in SPLIT_MARKS and i + 1 < len(text)]
    marks = [p for p in marks if bare(text[p:])]  # 切点之后须还有正文
    total_d, total_c = sum(durations), zh_len(text)
    result: dict[str, Any] = {"marks": len(marks), "needed": n - 1, "deviation": None, "cuts": None}
    if n < 2 or len(marks) < n - 1 or total_d <= 0 or total_c <= 0:
        result["splittable"] = False
        return result
    points = [0] + marks + [len(text)]
    target = [d / total_d for d in durations]
    inf = float("inf")
    # best[k][j]：前 k 段、第 k 段止于 points[j] 时的最小最大偏差
    best = [[inf] * len(points) for _ in range(n + 1)]
    back = [[-1] * len(points) for _ in range(n + 1)]
    best[0][0] = 0.0
    for k in range(1, n + 1):
        for j in range(1, len(points)):
            if k == n and j != len(points) - 1:
                continue
            for i in range(j):
                if best[k - 1][i] == inf:
                    continue
                seg = zh_len(text[points[i]:points[j]])
                if seg == 0:
                    continue
                worst = max(best[k - 1][i], abs(seg / total_c - target[k - 1]))
                if worst < best[k][j]:
                    best[k][j], back[k][j] = worst, i
    end = len(points) - 1
    if best[n][end] == inf:
        result["splittable"] = False
        return result
    cuts, j = [], end
    for k in range(n, 1, -1):
        j = back[k][j]
        cuts.append(points[j])
    result.update(deviation=best[n][end], cuts=sorted(cuts), splittable=best[n][end] <= SHARE_DEVIATION_MAX)
    return result


def compare_group(control: list[str], merged: str, durations: list[float | None]) -> dict[str, Any]:
    concat = "".join(control)
    row: dict[str, Any] = {
        "lines": len(control), "ratio": SequenceMatcher(None, concat, merged, autojunk=False).ratio(),
        "control_chars": zh_len(concat), "merged_chars": zh_len(merged),
        "identical_after_strip": bare(concat) == bare(merged), "order": order(control, merged)}
    if any(d is None or d <= 0 for d in durations):
        row["split"] = None
        row["control_deviation"] = None
    else:
        row["split"] = split_points(merged, len(control), durations)
        row["control_deviation"] = max_deviation([zh_len(c) for c in control], durations)
    return row


def compare(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        got, ctl = row["merged"].get("translations"), row["control"]["translations"]
        ref = row.get("reference")
        row["groups"] = [] if not got or not ctl else [
            {"key": key, **compare_group([ctl[c] for c in cues], got[key], [row["durations"][c] for c in cues]),
             "reference_ratio": (SequenceMatcher(None, "".join(ctl[c] for c in cues), "".join(ref[c] for c in cues),
                                                 autojunk=False).ratio() if ref else None)}
            for key, cues in row["units"] if len(cues) > 1]


def p50(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for label in sorted({r["sample"] for r in rows}):
        part = [r for r in rows if r["sample"] == label]
        groups = [g for r in part for g in r.get("groups", [])]
        splits = [g["split"] for g in groups if g["split"] is not None]
        verdicts = [g["order"]["verdict"] for g in groups]
        tok = {arm: {k: sum(r[arm].get(k) or 0 for r in part) for k in ("input_tokens", "output_tokens", "seconds")}
               for arm in ("control", "merged")}
        out[label] = {
            "packs": len(part), "failed_packs": sum(1 for r in part if not r["merged"].get("translations")),
            "groups": len(groups), "lines": sum(g["lines"] for g in groups),
            "ratio_p50": p50([g["ratio"] for g in groups]),
            "reference_ratio_p50": p50([g["reference_ratio"] for g in groups if g["reference_ratio"] is not None]),
            "identical_after_strip": sum(g["identical_after_strip"] for g in groups),
            "chars": {"control": sum(g["control_chars"] for g in groups), "merged": sum(g["merged_chars"] for g in groups)},
            "order": {v: verdicts.count(v) for v in ("same_order", "reordered", "unmatched")},
            "split": {"with_timing": len(splits), "splittable": sum(s["splittable"] for s in splits),
                      "fallback": sum(not s["splittable"] for s in splits),
                      "too_few_marks": sum(s["marks"] < s["needed"] for s in splits),
                      "deviation_p50": p50([s["deviation"] for s in splits if s["deviation"] is not None]),
                      "control_deviation_p50": p50([g["control_deviation"] for g in groups
                                                    if g["control_deviation"] is not None]),
                      "control_flagged": sum(g["control_deviation"] is not None
                                             and g["control_deviation"] >= SHARE_DEVIATION_MAX for g in groups)},
            "tokens": tok}
    return out


def markdown(rows: list[dict[str, Any]]) -> str:
    lines = ["# v8 票据 07 合并预检（含日文原文，不入库）", ""]
    for row in rows:
        ctl = row["control"]["translations"] or {}
        got = row["merged"].get("translations") or {}
        cmp_ = {g["key"]: g for g in row.get("groups", [])}
        lines += [f"## 小样 {row['sample']}：{row['scene_id']} 包 {row['batch_index']}（{row['category']}）", ""]
        for key, cues in row["units"]:
            if len(cues) == 1:
                lines.append(f"- 单条 {cues[0].rsplit('-', 1)[-1]}：{row['ja'][cues[0]]} ｜ 对照 {ctl.get(cues[0], '')}"
                             f" ｜ 合并 {got.get(key, '')}")
                continue
            g = cmp_.get(key, {})
            split = g.get("split") or {}
            lines += ["", f"### 组 {key.rsplit('-', 1)[-1]}（相似度 {g.get('ratio', 0):.2f}，语序 "
                      f"{g.get('order', {}).get('verdict')}，标点 {split.get('marks')}/{split.get('needed')}，"
                      f"切回偏差 {split.get('deviation')}）", "", "| 行 | 日文 | 对照 | 时长 |", "| --- | --- | --- | --- |"]
            for c in cues:
                d = row["durations"][c]
                lines.append(f"| {c.rsplit('-', 1)[-1]} | {row['ja'][c]} | {ctl.get(c, '')} | "
                             f"{'' if d is None else f'{d:.2f}'} |")
            merged = got.get(key, "")
            if split.get("cuts"):
                bounds = [0] + split["cuts"] + [len(merged)]
                merged = " ‖ ".join(merged[a:b] for a, b in zip(bounds, bounds[1:]))
            lines += ["", f"合并：{merged}", ""]
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--local-root", type=Path, default=REPO / ".local")
    parser.add_argument("--sample", action="append", nargs=2, metavar=("LABEL", "SAMPLE_JSON"),
                        help="默认 B=02b/sample.json（主）、A=02/sample.json（对话对照）")
    parser.add_argument("--seed", type=int, default=20261011)
    parser.add_argument("--out", type=Path, default=V8_ROOT / "02c")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--dry-run", action="store_true", help="只渲染提示，不启动服务器")
    parser.add_argument("--reuse", type=Path, help="已有 probe.json：复用其合并译文与 token，只重算离线比较（不占 GPU）")
    args = parser.parse_args(argv)
    specs = args.sample or [("B", V8_ROOT / "02b/sample.json"), ("A", V8_ROOT / "02/sample.json")]
    samples = [(label, json.loads(Path(path).read_text(encoding="utf-8"))) for label, path in specs]
    rows = plan(samples, sim7.dev_scenes(args.local_root / "translation-evaluation/hy30-flow-v4"))
    if args.reuse:
        old = {(p["scene_id"], p["batch_index"]): p["merged"]
               for p in json.loads(args.reuse.read_text(encoding="utf-8"))["packs"]}
        for row in rows:
            prev = old[(row["scene_id"], row["batch_index"])]
            if prev["prompt_sha256"] != row["merged"]["prompt_sha256"]:
                raise RuntimeError(f"{row['scene_id']} b{row['batch_index']}: prompt differs from {args.reuse}")
            row["merged"].update({k: v for k, v in prev.items() if k not in row["merged"]})
    elif not args.dry_run:
        generate(rows, args.seed, args.out, port=args.port)
    compare(rows)
    public = [{**row, "merged": {k: v for k, v in row["merged"].items() if not k.startswith("_")}} for row in rows]
    report = {"seed": args.seed, "dry_run": args.dry_run, "reused": str(args.reuse) if args.reuse else None,
              "recipe": CONTROL, "joiner": JOINER,
              "summary": summarise(rows), "packs": public}
    args.out.mkdir(parents=True, exist_ok=True)
    atomic_write_json(args.out / "probe.json", report)
    (args.out / "probe.md").write_text(markdown(rows), encoding="utf-8")
    print(json.dumps({"out": str(args.out), **report["summary"]}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
