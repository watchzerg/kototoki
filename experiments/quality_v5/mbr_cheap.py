"""更省的 MBR（票据 07）：从 v4 的 8 样本 run 离线派生 N＝4、6 的逐条 MBR，模拟样本一致早停，并统一核算成本。

v4 的 `mbr8` 每批串行生成 8 个样本（样本 k 用 seed `sample_seed(seed, k)`，样本 0 就是对照），每个请求都记了
批次、样本序号与耗时。所以：
- N＝n 的逐条 MBR 只是"取前 n 个样本再逐条选"，用 v4 `derive.py` 派生，带真实配方 `mbr{n}c` 的 hash；
- 早停是"按顺序生成，到第 k（≥ k_min）个样本时，若本批的共识度 ≥ θ 就停"；共识度是逐条 MBR 胜者与其他样本
  的平均 chrF，在本批各 cue 上取最小值（`min`，最严）或平均值（`mean`）；只依赖已生成样本的内容，可在 8 个样本上精确模拟；停下后在已生成的样本里逐条 MBR。
成本口径：本批实际用到的样本的请求耗时之和（与 `derive.py` 相同），对照为样本 0 的耗时之和。墙钟比只在同一
口径内可比，v4 记录的整 run 墙钟受与裁判并发影响。

命令（仓库根目录，`.venv`）：
  python -X utf8 -m experiments.quality_v5.mbr_cheap derive --root ROOT --n 4 6
  python -X utf8 -m experiments.quality_v5.mbr_cheap early-stop --root ROOT --kmin 3 --theta 0.7 --agg mean --name es3m70 [--scope confirm]
  python -X utf8 -m experiments.quality_v5.mbr_cheap cost --root ROOT [--grid] --out cost.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from experiments.translation_v3.common import atomic_write_json, read_json, utc_now
from experiments.translation_v3.mbr import chrf, select

BASE = "mbr8"
SELECTOR = "mbr-chrf-cue"


def base_runs(root: Path, scope: str = "dev", base: str = BASE) -> list[Path]:
    return sorted(p for p in (root / "runs").glob(f"{base}__s*__{scope}") if (p / "run.json").is_file())


def batch_samples(row: dict[str, Any], batch: dict[str, Any], total: int) -> list[tuple[int, dict[str, str]]]:
    """(样本序号, 译文) 按序号排列；失败样本跳过（`candidates[i]` 对应第 i 个成功样本）。"""
    failed = {f["sample"] for f in batch.get("failed_samples", [])}
    succeeded = [k for k in range(total) if k not in failed]
    return list(zip(succeeded, batch["candidates"]))


def request_seconds(row: dict[str, Any]) -> dict[tuple[int, int], float]:
    seconds: dict[tuple[int, int], float] = {}
    for request in row["requests"]:
        key = (request.get("batch_index", 0), request.get("sample", 0))
        seconds[key] = seconds.get(key, 0.0) + sum(a.get("elapsed_seconds") or 0 for a in request.get("attempts", []))
    return seconds


def consensus(samples: list[dict[str, str]], ids: list[str], agg: str = "min") -> float:
    """本批共识度：逐条 MBR 胜者与其他样本的平均 chrF，在各 cue 上取最小值（min）或平均值（mean）。"""
    values = []
    for key in ids:
        texts = [sample[key] for sample in samples]
        values.append(max(sum(chrf(t, u) for j, u in enumerate(texts) if j != i) / (len(texts) - 1)
                          for i, t in enumerate(texts)))
    return min(values) if agg == "min" else sum(values) / len(values)


def stop_point(samples: list[tuple[int, dict[str, str]]], ids: list[str], kmin: int, theta: float,
               agg: str = "min") -> int:
    """按顺序生成时用到的样本数（含失败样本的序号位置）：第一个满足共识的 k，否则全部。"""
    for count in range(kmin, len(samples) + 1):
        if consensus([s for _, s in samples[:count]], ids, agg) >= theta:
            return samples[count - 1][0] + 1
    return samples[-1][0] + 1 if samples else 0


def simulate(root: Path, base_run: Path, kmin: int, theta: float, agg: str = "min") -> dict[str, Any]:
    """一个 mbr8 run 的早停模拟：逐批停点、选择结果与成本（不写文件）。"""
    run = read_json(base_run / "run.json")
    total = run["recipe"]["recipe"]["candidates"]
    scenes, used, seconds, control = {}, [], 0.0, 0.0
    for scene_id in run["scene_ids"]:
        row = read_json(base_run / "scenes" / f"{scene_id}.json")
        if row["status"] != "complete":
            scenes[scene_id] = None
            continue
        cost = request_seconds(row)
        translations: dict[str, str] = {}
        for batch in row["batches"]:
            ids = batch["target_ids"]
            samples = batch_samples(row, batch, total)
            stop = stop_point(samples, ids, kmin, theta, agg)
            chosen = [s for k, s in samples if k < stop]
            picked, _ = select(SELECTOR, chosen, ids) if len(chosen) > 1 else (dict(chosen[0]), None)
            translations.update(picked)
            used.append(stop)
            seconds += sum(v for (b, k), v in cost.items() if b == batch["index"] and k < stop)
            control += cost.get((batch["index"], 0), 0.0)
        scenes[scene_id] = translations
    return {"scenes": scenes, "batches": len(used), "mean_samples": sum(used) / len(used),
            "seconds": seconds, "control_seconds": control}


def write_early_stop(root: Path, name: str, kmin: int, theta: float, agg: str,
                     scope: str = "dev") -> list[dict[str, Any]]:
    """早停伪 run：`<name>__s<seed>__<scope>`，配方记为 mbr8c（同样本上的逐条 MBR）加 `pseudo.kind = early-stop-simulation`。"""
    from experiments.translation_v3.recipes import load_recipe
    from experiments.translation_v4.derive import derived_recipe

    mbr8c = derived_recipe(load_recipe(BASE, root), "mbr8c", 8, SELECTOR)
    reports = []
    for base_run in base_runs(root, scope):
        run = read_json(base_run / "run.json")
        run_id = f"{name}__s{run['seed']}__{run['scope']}"
        out = root / "runs" / run_id
        result = simulate(root, base_run, kmin, theta, agg)
        for scene_id, translations in result["scenes"].items():
            row = read_json(base_run / "scenes" / f"{scene_id}.json")
            payload = ({"scene_id": scene_id, "status": "complete", "cue_ids": row["cue_ids"],
                        "translations": translations, "run_id": run_id} if translations is not None else
                       {"scene_id": scene_id, "status": "failed", "cue_ids": row["cue_ids"], "translations": {},
                        "failure": row.get("failure"), "run_id": run_id})
            atomic_write_json(out / "scenes" / f"{scene_id}.json", payload)
        recipe = {**mbr8c.to_json(), "name": name}
        atomic_write_json(out / "run.json", {
            "schema": run["schema"], "run_id": run_id, "recipe": recipe, "recipe_hash": mbr8c.recipe_hash,
            "pseudo": {"kind": "early-stop-simulation", "base_run_id": run["run_id"], "kmin": kmin, "theta": theta, "agg": agg,
                       "selector": SELECTOR, "mean_samples": result["mean_samples"]},
            "seed": run["seed"], "scope": run["scope"], "sources": run["sources"], "scene_ids": run["scene_ids"],
            "created_at_utc": utc_now(), "sessions": [], "resumed": False, "performance_comparable": False,
            "wall_clock_seconds": result["seconds"], "completion": run["completion"]})
        reports.append({"run_id": run_id, "mean_samples": round(result["mean_samples"], 2),
                        "cost_ratio": round(result["seconds"] / result["control_seconds"], 2)})
    return reports


def cost_table(root: Path, grid: bool) -> dict[str, Any]:
    """每个 seed：N＝1..8 的累计成本比；可选早停网格（k_min × θ）的平均样本数与成本比。"""
    table: dict[str, Any] = {"by_n": {}, "early_stop": {}}
    for base_run in base_runs(root):
        run = read_json(base_run / "run.json")
        totals = [0.0] * 9
        for scene_id in run["scene_ids"]:
            row = read_json(base_run / "scenes" / f"{scene_id}.json")
            for (_, sample), value in request_seconds(row).items():
                for n in range(sample + 1, 9):
                    totals[n] += value
        table["by_n"][run["run_id"]] = {n: round(totals[n] / totals[1], 3) for n in range(1, 9)}
        if grid:
            for kmin in (2, 3, 4):
                for theta in (0.6, 0.7, 0.8, 0.9):
                    result = simulate(root, base_run, kmin, theta)
                    table["early_stop"].setdefault(f"k{kmin}-t{theta}", {})[run["run_id"]] = {
                        "mean_samples": round(result["mean_samples"], 2),
                        "cost_ratio": round(result["seconds"] / result["control_seconds"], 3)}
    return table


def main() -> int:
    parser = argparse.ArgumentParser(description="更省的 MBR（票据 07）")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("derive")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--n", type=int, nargs="+", required=True)
    p = sub.add_parser("early-stop")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--kmin", type=int, required=True)
    p.add_argument("--theta", type=float, required=True)
    p.add_argument("--agg", choices=("min", "mean"), default="min")
    p.add_argument("--name", required=True)
    p.add_argument("--scope", choices=("dev", "confirm"), default="dev")
    p = sub.add_parser("cost")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--grid", action="store_true")
    p.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "derive":
        from experiments.translation_v4.derive import derive

        for base_run in base_runs(args.root):
            for n in args.n:
                out = derive(args.root, base_run, f"mbr{n}c", n, SELECTOR)
                print(out.name, round(read_json(out / "run.json")["wall_clock_seconds"]))
    elif args.command == "early-stop":
        for report in write_early_stop(args.root, args.name, args.kmin, args.theta, args.agg, args.scope):
            print(json.dumps(report))
    else:
        table = cost_table(args.root, args.grid)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(table, indent=1), encoding="utf-8")
        print(json.dumps(table, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
