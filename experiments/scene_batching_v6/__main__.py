"""CLI: python -m experiments.scene_batching_v6 <command> (see q2.py for the layout)."""

from __future__ import annotations

import argparse
import json
import sys

from . import q1, q2, status
from .common import V6_ROOT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scene_batching_v6")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="offline: runs, subsets, judge progress, GPU lock")
    sub.add_parser("q1", help="offline Q1 analysis -> q1/q1.json")
    g = sub.add_parser("generate", help="GPU: one variant run on a v4 dev seed block")
    g.add_argument("--recipe", required=True)
    g.add_argument("--seed", type=int, required=True)
    g.add_argument("--break-stale-lock", action="store_true")
    for name in ("copy-control", "subset", "judge"):
        p = sub.add_parser(name)
        p.add_argument("--seed", type=int, required=True)
        p.add_argument("--control-seed", type=int)
        if name != "copy-control":
            p.add_argument("--variant", required=True)
        if name == "judge":
            p.add_argument("--parallel", type=int, default=3)
    c = sub.add_parser("compare", help="offline paired comparison on the affected subset")
    c.add_argument("--variant", required=True)
    c.add_argument("--seeds", type=int, nargs="+", required=True)
    c.add_argument("--control-seeds", type=int, nargs="+")
    c.add_argument("--label", default="")
    args = parser.parse_args(argv)
    if args.command == "status":
        out = status.status(V6_ROOT)
    elif args.command == "q1":
        out = {"written": str(q1.main())}
    elif args.command == "generate":
        out = q2.generate(args.recipe, args.seed, break_stale_lock=args.break_stale_lock)
    elif args.command == "copy-control":
        out = {"copied": str(q2.copy_control(args.control_seed or args.seed))}
    elif args.command == "subset":
        out = q2.build_subset(args.variant, args.seed, control_seed=args.control_seed)
        out = {k: v for k, v in out.items() if k not in ("affected_cues", "windows")} | {
            "affected": len(out["affected_cues"]), "windows": len(out["windows"])}
    elif args.command == "judge":
        out = q2.judge(args.variant, args.seed, parallel=args.parallel, control_seed=args.control_seed)
        print(json.dumps({"exit_code": out["exit_code"]}))
        return out["exit_code"]
    else:
        out = q2.compare(args.variant, args.seeds, control_seeds=args.control_seeds, label=args.label)
        out = {k: out.get(k) for k in ("state", "affected_cues", "by_category_counts", "full_set_guard")} | {
            "accuracy": (out.get("affected") or {}).get("accuracy", {}).get("delta")}
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
