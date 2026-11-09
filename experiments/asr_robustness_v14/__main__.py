"""命令行入口：`.venv/Scripts/python.exe -X utf8 -m experiments.asr_robustness_v14 <子命令>`。

子命令按票据分组（README 有表）；输出只打印计数与指标。
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="experiments.asr_robustness_v14")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify-hf-ii", help="票据 01：HF II 对照产物身份与官方 CER")
    sub.add_parser("reproduce-hf-iii", help="票据 01：HF III 产品 STT 重算（GPU 1 run）")
    p = sub.add_parser("signals", help="票据 01 A0：守卫信号、逐窗 CER、阈值表")
    p.add_argument("--film", choices=("hf-ii", "hf-iii"), action="append")
    p = sub.add_parser("gaps", help="票据 01 B0：空子段统计与删除项定位")
    p.add_argument("--film", choices=("hf-ii", "hf-iii"), action="append")
    p = sub.add_parser("blank", help="票据 02 A1：被标记窗口置空的离线模拟（官方口径）")
    p.add_argument("--rule", required=True)
    p = sub.add_parser("redecode", help="票据 02 A2：问题窗口单次补解（GPU）")
    p.add_argument("--rule", required=True)
    p = sub.add_parser("fill", help="票据 03 B1：空子段补窗重解码（GPU）")
    p.add_argument("--rule", required=True)
    p = sub.add_parser("correct", help="票据 04 C1／C2：Strata 后校正（GPU：一次 Strata session）")
    p.add_argument("--arms", default="c1,c2")
    p.add_argument("--prompt", default="ja-correct-v1")
    p.add_argument("--film", choices=("hf-ii", "hf-iii"), action="append")
    p = sub.add_parser("correct-eval", help="票据 04：校正结果的单元口径评估与改动分类（离线）")
    p.add_argument("--run", required=True)
    p = sub.add_parser("correct-sample", help="票据 04：抽 30 条改动供 Opus 抽看（离线，只写计数与条目）")
    p.add_argument("--run", required=True)
    args = parser.parse_args(argv)
    films = tuple(getattr(args, "film", None) or ("hf-ii", "hf-iii"))

    if args.command == "verify-hf-ii":
        from experiments.asr_robustness_v14 import inputs
        print(dumps(inputs.verify_hf_ii()))
    elif args.command == "reproduce-hf-iii":
        from experiments.asr_robustness_v14 import inputs
        print(dumps(inputs.reproduce_hf_iii()))
    elif args.command == "signals":
        from experiments.asr_robustness_v14 import signals
        print(dumps(signals.run(films)))
    elif args.command == "gaps":
        from experiments.asr_robustness_v14 import gaps
        print(dumps(gaps.run(films)))
    elif args.command == "blank":
        from experiments.asr_robustness_v14 import guard
        print(dumps(guard.blank(args.rule)))
    elif args.command == "redecode":
        from experiments.asr_robustness_v14 import guard
        print(dumps(guard.redecode(args.rule)))
    elif args.command == "fill":
        from experiments.asr_robustness_v14 import fill
        print(dumps(fill.run(args.rule)))
    elif args.command == "correct":
        from experiments.asr_robustness_v14 import correct
        print(dumps(correct.run(tuple(args.arms.split(",")), args.prompt, films)))
    elif args.command == "correct-eval":
        from experiments.asr_robustness_v14 import correct
        print(dumps(correct.evaluate_run(args.run)))
    elif args.command == "correct-sample":
        from experiments.asr_robustness_v14 import correct
        print(dumps(correct.sample_changes(args.run)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
