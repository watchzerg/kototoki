"""命令行入口：`.venv/Scripts/python.exe -X utf8 -m experiments.asr_robustness_v15 <子命令>`（README 有表）。输出只打印计数与指标。"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="experiments.asr_robustness_v15")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("scan", help="票据 01 A3：盘点 w0 产物、四信号、规则候选统计、写出被标记窗口供 Opus 判读")
    p.add_argument("--group", action="append", help="只扫描这些分组（默认全部）")
    p = sub.add_parser("safety-net", help="票据 01：合并 Opus 判读，算每条规则的误报与安全网判据")
    p.add_argument("--judgements")
    p = sub.add_parser("actions", help="票据 02 A4：置空／折叠／补解＋折叠三种动作（GPU：补解＋一次 align 批）")
    p.add_argument("--rule", required=True)
    p.add_argument("--film", choices=("hf-ii", "hf-iii"), action="append")
    p = sub.add_parser("names-build", help="票据 04：HF III 的 Q3 建表（Strata session 内）＋C3b（同一 session）")
    p.add_argument("--film", choices=("hf-ii", "hf-iii"), action="append")
    p.add_argument("--skip-build", action="store_true")
    p = sub.add_parser("names-rules", help="票据 04 C3a：纯规则表内替换（离线）")
    p.add_argument("--film", choices=("hf-ii", "hf-iii"), action="append")
    p = sub.add_parser("names-eval", help="票据 04：C3a／C3b 的单元口径评估、人名命中率、有害率（离线）")
    p.add_argument("--film", choices=("hf-ii", "hf-iii"), action="append")
    p = sub.add_parser("names-sample", help="票据 04：抽 30 条改动供 Opus 抽看（离线）")
    sub.add_parser("impact-translate", help="票据 05：两臂 × 两部 × 3 seed 的产品翻译（GPU：一个 Strata session）")
    sub.add_parser("impact-plan", help="票据 05：写配对裁判计划（离线；只写一次）")
    sub.add_parser("impact-judge", help="票据 05：配对裁判 v5-asr-pairwise-v1（Opus 经 claude CLI；可续跑）")
    sub.add_parser("impact-report", help="票据 05：裁判估计、不一致率、交付失败、成本（离线）")
    args = parser.parse_args(argv)
    films = tuple(getattr(args, "film", None) or ("hf-ii", "hf-iii"))

    if args.command == "scan":
        from experiments.asr_robustness_v15 import scan
        print(dumps(scan.run(tuple(args.group) if args.group else None)))
    elif args.command == "safety-net":
        from experiments.asr_robustness_v15 import scan
        print(dumps(scan.judge_rules(args.judgements)))
    elif args.command == "actions":
        from experiments.asr_robustness_v15 import actions
        print(dumps(actions.run(args.rule, films)))
    elif args.command == "names-build":
        from experiments.asr_robustness_v15 import names_replace
        print(dumps(names_replace.run_strata(films, skip_build=args.skip_build)))
    elif args.command == "names-rules":
        from experiments.asr_robustness_v15 import names_replace
        print(dumps(names_replace.run_rules(films)))
    elif args.command == "names-eval":
        from experiments.asr_robustness_v15 import names_replace
        print(dumps(names_replace.evaluate(films)))
    elif args.command == "names-sample":
        from experiments.asr_robustness_v15 import names_replace
        print(dumps(names_replace.sample_changes()))
    elif args.command.startswith("impact-"):
        from experiments.asr_robustness_v15 import translate_impact
        if args.command == "impact-judge":
            return translate_impact.judge()
        action = {"impact-translate": translate_impact.run_translate, "impact-plan": translate_impact.judge_plan,
                  "impact-report": translate_impact.report}[args.command]
        print(dumps(action()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
