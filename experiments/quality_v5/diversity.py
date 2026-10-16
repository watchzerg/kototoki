"""样本多样性（票据 09）：多样本 run 里每条 cue 的样本两两 chrF 均值，再在 cue 上平均；越高越相似（多样性越低）。

另报"8 个样本全相同"的 cue 占比。用于说明低温采样下 MBR 可选空间的大小。

命令（仓库根目录，`.venv`；离线）：
  python -X utf8 -m experiments.quality_v5.diversity --root ROOT --runs mbr8__s20261011__dev t03mbr8__s20261011__dev
"""

from __future__ import annotations

import argparse
from itertools import combinations
import json
from pathlib import Path
from typing import Any

from experiments.translation_v3.common import read_json
from experiments.translation_v3.mbr import chrf

from .mbr_cheap import batch_samples


def cue_similarity(texts: list[str]) -> float:
    pairs = list(combinations(texts, 2))
    return sum(chrf(a, b) for a, b in pairs) / len(pairs)


def run_diversity(run_dir: Path) -> dict[str, Any]:
    run = read_json(run_dir / "run.json")
    total = run["recipe"]["recipe"]["candidates"]
    values, identical = [], 0
    for scene_id in run["scene_ids"]:
        row = read_json(run_dir / "scenes" / f"{scene_id}.json")
        if row["status"] != "complete":
            continue
        for batch in row["batches"]:
            samples = [s for _, s in batch_samples(row, batch, total)]
            if len(samples) < 2:
                continue
            for key in batch["target_ids"]:
                texts = [s[key] for s in samples]
                values.append(cue_similarity(texts))
                identical += len(set(texts)) == 1
    return {"run_id": run_dir.name, "cues": len(values), "mean_pairwise_chrf": round(sum(values) / len(values), 4),
            "all_identical": round(identical / len(values), 4)}


def main() -> int:
    parser = argparse.ArgumentParser(description="样本多样性（票据 09）")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--runs", nargs="+", required=True)
    args = parser.parse_args()
    for run_id in args.runs:
        print(json.dumps(run_diversity(args.root / "runs" / run_id)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
