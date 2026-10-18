"""v8 票据 02：小样生成与人工观察。

在 dev 全集上按 ``dp10-cut`` 切包（``grp1`` 的切包与之相同），挑多 cue 小组覆盖 cue 最多的包（剧集、电影各
``--per-category`` 个），对每个包分别用 ``dp10-cut``（对照）与 ``grp1``（候选）各生成一次，写
``<out>/sample.json``（含提示 sha256、译文、token 与耗时）与 ``<out>/sample.md``（日文、对照、候选并排，供人工阅读；
含原文，放 ``.local`` 下不入库），并用 ``checks.reorder`` 算这几个包的重排率。

``--dry-run`` 只渲染提示、不启动服务器、不占 GPU。真实生成走 ``translation_v3.generate.managed_session_factory``
（``.local/gpu.lock``、新启动的 llama-server、首个 completion 须 ``cache_n == 0``），与正式 run 同一条链路，但它不是
``run_generation`` 的 run：没有 ``run.json``／``scenes/``，不能用于裁判或配对，只用于观察。

    PYTHONPATH=. python -X utf8 -m experiments.reorder_groups.sample [--dry-run] [--seed 20261011] [--per-category 5]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from typing import Any

from experiments.scene_batching_v6 import sim7
from experiments.translation_v3 import recipes as R
from experiments.translation_v3.batching import Batch, build_batches, sentence_groups
from experiments.translation_v3.common import REPO, atomic_write_json, sha256_bytes
from experiments.translation_v3.data import Scene
from experiments.translation_v3.generate import StepFailed, managed_session_factory, run_step

from .checks import reorder, zh_len

V8_ROOT = REPO / ".local/group-reorder-v8"
CONTROL, CANDIDATE, ALT = "dp10-cut", "grp1", "grp1-alt"
CATEGORIES = ("anime_series", "animation_movie")
# 挑包准则 "split"：组内非末行以接续成分结尾（句子被拆开的信号），按这类行数排序。
CONTINUATION = ("、", "，", "は", "が", "を", "に", "で", "と", "へ", "の", "も", "から", "まで", "て", "ば", "し",
                "けど", "のに", "ので", "や", "か", "って", "たら", "なら", "じゃ", "ない")
# 票据 02 允许的那一次措辞调整：两步式（先合句译、再切回各行），作为第三臂与 joint-understanding-v2 同场对照。
ALT_INSTRUCTION = ("先共同理解全部可见台词及跨条目的条件、否定、指代和语气，再表达各源 ID 的信息。"
                   "groups 里同组的 ID 是同一句话被拆成的几行。翻译这样的组时，先把这几行合起来理解成一句完整的话，译成通顺自然的中文，"
                   "再按说话顺序把这句中文切成同样数量的几段依次填入各 ID：每段的内容可以与原文那一行不同，只要整句意思完整、"
                   "各段长度与各行原文大致相称、每个值不为空。未列入 groups 的 ID 各自单独成组。"
                   "不同组之间仍各自只承载对应源 ID，不搬运邻条事实、不提前补完后文。保留原文歧义和信息揭示顺序。")


def continuation_lines(scene: Scene, group: tuple[int, int]) -> int:
    return sum(1 for i in range(group[0], group[1] - 1)
               if scene.cues[i].text.rstrip(" 　").endswith(CONTINUATION))


def rank_batches(scenes: list[Scene], recipe: R.Recipe, gap: float, per_category: int, criterion: str,
                 exclude: set[tuple[str, int]] = frozenset()) -> list[tuple[Scene, Batch]]:
    """按对照配方切包，每类取得分最高的包。criterion "covered"：多 cue 小组覆盖的 cue 数（并列按小组数、场景顺序）；
    "split"：组内以接续成分结尾的非末行数（并列按覆盖数、场景顺序）。"""
    scored: dict[str, list[tuple[tuple[int, int, int], Scene, Batch]]] = {c: [] for c in CATEGORIES}
    for order, scene in enumerate(scenes):
        if scene.category not in scored:
            continue
        for batch in build_batches(scene, recipe):
            if (scene.scene_id, batch.index) in exclude:
                continue
            groups = [g for g in sentence_groups(scene, batch.start, batch.stop, gap) if g[1] - g[0] > 1]
            covered = sum(b - a for a, b in groups)
            split = sum(continuation_lines(scene, g) for g in groups)
            key = (-covered, -len(groups), order) if criterion == "covered" else (-split, -covered, order)
            if covered and (criterion == "covered" or split):
                scored[scene.category].append((key, scene, batch))
    picked = []
    for category in CATEGORIES:
        rows = sorted(scored[category], key=lambda row: row[0])[:per_category]
        picked.extend((scene, batch) for _, scene, batch in rows)
    return picked


def render(scene: Scene, batch: Batch, recipe: R.Recipe, instruction: str | None = None) -> tuple[str, str, list[str]]:
    window = batch.to_window(scene)
    ids = list(batch.target_ids)
    saved = R.JOINT2_INSTRUCTION
    try:
        if instruction is not None:
            R.JOINT2_INSTRUCTION = instruction
        prompt = R.render_translation(recipe, window, [], None, scene.work_id, batch.pauses, batch.groups)
    finally:
        R.JOINT2_INSTRUCTION = saved
    return prompt, R.translation_grammar(recipe, ids), ids


def plan(scenes: list[Scene], per_category: int, criterion: str = "covered", alt: bool = False,
         exclude: set[tuple[str, int]] = frozenset()) -> list[dict[str, Any]]:
    control, candidate = R.load_recipe(CONTROL), R.load_recipe(CANDIDATE)
    rows = []
    for scene, batch in rank_batches(scenes, control, candidate.groups["gap"], per_category, criterion, exclude):
        cand_batch = next(b for b in build_batches(scene, candidate) if b.index == batch.index)
        if cand_batch.target_ids != batch.target_ids or cand_batch.before_ids != batch.before_ids:
            raise RuntimeError("grp1 and dp10-cut batches differ")
        text = {cue.id: cue.text for cue in scene.cues}
        arms = {}
        specs = [(CONTROL, control, batch, None), (CANDIDATE, candidate, cand_batch, None)]
        if alt:
            specs.append((ALT, candidate, cand_batch, ALT_INSTRUCTION))
        for arm, recipe, b, instruction in specs:
            prompt, grammar, ids = render(scene, b, recipe, instruction)
            arms[arm] = {"recipe_hash": recipe.recipe_hash, "prompt_sha256": sha256_bytes(prompt.encode()),
                         "prompt_chars": len(prompt), "_prompt": prompt, "_grammar": grammar, "_ids": ids,
                         "_sampling": recipe.sampling}
            if instruction is not None:
                arms[arm]["instruction_sha256"] = sha256_bytes(instruction.encode())
        rows.append({"scene_id": scene.scene_id, "category": scene.category, "work_id": scene.work_id,
                     "batch_index": batch.index, "target_ids": list(batch.target_ids),
                     "before_ids": list(batch.before_ids), "after_ids": list(batch.after_ids),
                     "groups": [list(g) for g in cand_batch.groups],
                     "ja": {k: text[k] for k in batch.before_ids + batch.target_ids + batch.after_ids},
                     "arms": arms})
    return rows


def generate(rows: list[dict[str, Any]], seed: int, out: Path, *, port: int, break_stale_lock: bool) -> None:
    run_id = f"{CANDIDATE}-sample__s{seed}__dev02"
    factory = managed_session_factory(V8_ROOT, run_id, port=port, break_stale_lock=break_stale_lock)
    cache_state: dict[str, Any] = {"checked": False}
    with factory(out, 0) as handle:
        for number, row in enumerate(rows, 1):
            for arm, info in row["arms"].items():
                record: dict[str, Any] = {"stage": "translation"}
                started = time.perf_counter()
                try:
                    result = run_step(handle.client, info["_prompt"], info["_grammar"], seed,
                                      lambda text, ids=info["_ids"]: R.parse_translation(text, ids),
                                      cache_state, record, info["_sampling"])
                    info["translations"] = result
                except StepFailed as exc:
                    info["translations"] = None
                    info["error"] = {"kind": exc.kind, "error": str(exc)[:500]}
                    if exc.kind in ("oom", "cache", "server"):
                        raise
                attempt = record["attempts"][-1]
                info["input_tokens"] = attempt.get("input_tokens")
                info["output_tokens"] = attempt.get("output_tokens")
                info["seconds"] = time.perf_counter() - started
                info["attempts"] = len(record["attempts"])
                print(f"{number}/{len(rows)} {row['scene_id']} b{row['batch_index']} {arm}: "
                      f"{'ok' if info['translations'] else info['error']['kind']} {info['seconds']:.1f}s")


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    arms = [a for a in (CONTROL, CANDIDATE, ALT) if rows and a in rows[0]["arms"]]
    texts: dict[str, dict[str, str]] = {a: {} for a in arms}
    packs = []
    for row in rows:
        got = {a: row["arms"][a].get("translations") for a in arms}
        if not all(got.values()):
            continue
        for a in arms:
            texts[a].update(got[a])
        grouped = {i for g in row["groups"] for i in g}
        packs.append([tuple(g) for g in row["groups"]] + [(i,) for i in row["target_ids"] if i not in grouped])
    stats = {a: reorder(packs, texts[CONTROL], texts[a]) for a in arms[1:]} if packs else None
    if packs and ALT in arms:
        stats[f"{ALT} vs {CANDIDATE}"] = reorder(packs, texts[CANDIDATE], texts[ALT])
    tokens = {arm: {"input": sum(r["arms"][arm].get("input_tokens") or 0 for r in rows),
                    "output": sum(r["arms"][arm].get("output_tokens") or 0 for r in rows),
                    "seconds": sum(r["arms"][arm].get("seconds") or 0 for r in rows)} for arm in arms}
    return {"packs": len(rows), "generated_pairs": len(packs), "reorder": stats, "tokens": tokens}


def markdown(rows: list[dict[str, Any]]) -> str:
    arms = [a for a in (CONTROL, CANDIDATE, ALT) if rows and a in rows[0]["arms"]]
    lines = ["# v8 票据 02 小样（含日文原文，不入库）", ""]
    for row in rows:
        lines += [f"## {row['scene_id']} 包 {row['batch_index']}（{row['category']}）", "",
                  "小组：" + "；".join(" + ".join(i.rsplit('-', 1)[-1] for i in g) for g in row["groups"]), "",
                  "| ID | 日文 | " + " | ".join(arms) + " | 字数 " + "/".join(arms) + " |",
                  "| --- | --- | " + " | ".join("---" for _ in arms) + " | --- |"]
        grouped = {i: n for n, g in enumerate(row["groups"], 1) for i in g}
        texts = {a: row["arms"][a].get("translations") or {} for a in arms}
        for i in row["before_ids"] + row["target_ids"] + row["after_ids"]:
            tag = f"[组{grouped[i]}] " if i in grouped else ("[邻] " if i not in row["target_ids"] else "")
            cells = " | ".join(texts[a].get(i, "") for a in arms)
            counts = "/".join(str(zh_len(texts[a][i])) if i in texts[a] else "" for a in arms)
            lines.append(f"| {tag}{i.rsplit('-', 1)[-1]} | {row['ja'][i]} | {cells} | {counts} |")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--local-root", type=Path, default=REPO / ".local")
    parser.add_argument("--seed", type=int, default=20261011)
    parser.add_argument("--per-category", type=int, default=5)
    parser.add_argument("--out", type=Path, default=V8_ROOT / "02")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--break-stale-lock", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="只渲染提示，不启动服务器")
    parser.add_argument("--criterion", choices=("covered", "split"), default="covered")
    parser.add_argument("--alt", action="store_true", help="加第三臂 grp1-alt（ALT_INSTRUCTION 措辞）")
    parser.add_argument("--exclude", type=Path, help="已有 sample.json：排除其中的包")
    args = parser.parse_args(argv)
    scenes = sim7.dev_scenes(args.local_root / "translation-evaluation/hy30-flow-v4")
    exclude = set()
    if args.exclude:
        exclude = {(p["scene_id"], p["batch_index"]) for p in json.loads(args.exclude.read_text(encoding="utf-8"))["packs"]}
    rows = plan(scenes, args.per_category, args.criterion, args.alt, exclude)
    if not args.dry_run:
        generate(rows, args.seed, args.out, port=args.port, break_stale_lock=args.break_stale_lock)
    public = [{**row, "arms": {arm: {k: v for k, v in info.items() if not k.startswith("_")}
                                for arm, info in row["arms"].items()}} for row in rows]
    report = {"seed": args.seed, "dry_run": args.dry_run, "criterion": args.criterion,
              "alt_instruction": ALT_INSTRUCTION if args.alt else None, "summary": summarise(rows), "packs": public}
    args.out.mkdir(parents=True, exist_ok=True)
    atomic_write_json(args.out / "sample.json", report)
    (args.out / "sample.md").write_text(markdown(rows), encoding="utf-8")
    print(json.dumps({"out": str(args.out), **report["summary"]}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
