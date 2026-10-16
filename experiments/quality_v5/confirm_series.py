"""只含剧集的确认集上运行 v4 `confirm`（票据 14）。

v4 `stats4.aggregate_sums` 只在两类（剧集、电影）都有值时才给 `overall`，否则为 None，判定门槛随之报错。v5 确认集
只有剧集（电影已被 v4 confirm 用尽），这里在运行时把 `overall` 改为"有值类别的均值"——单类别时就等于剧集值——
其余统计、判定规则（评测根里冻结的 `decision-policy-v4.json`）与 Holm 校正全部沿用 v4 原样。不修改 v4 代码。

命令（仓库根目录，`.venv`；离线；只运行一次）：
  python -X utf8 -m experiments.quality_v5.confirm_series --root ROOT [--reps 10000]
"""

from __future__ import annotations

import argparse
import statistics
import sys


def patch() -> None:
    from experiments.translation_v4 import stats4

    def aggregate_sums(work_sums, category_of):
        result = {}
        for category in stats4.CATEGORIES:
            means = [s / n for w, (s, n) in sorted(work_sums.items()) if category_of[w] == category and n]
            result[category] = statistics.fmean(means) if means else None
        present = [result[c] for c in stats4.CATEGORIES if result[c] is not None]
        result["overall"] = statistics.fmean(present) if present else None
        return result

    stats4.aggregate_sums = aggregate_sums


def main() -> int:
    parser = argparse.ArgumentParser(description="只含剧集的确认集上运行 v4 confirm（票据 14）")
    parser.add_argument("--root", required=True)
    parser.add_argument("--reps", default="10000")
    args = parser.parse_args()
    patch()
    from experiments.translation_v4.cli import main as v4_main

    return v4_main(["--root", args.root, "confirm", "--reps", args.reps])

if __name__ == "__main__":
    sys.exit(main())
