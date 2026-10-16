"""CLI: python -m experiments.scene_batching_v6 [--round v7] <command> (layout: q2.py; v7: v7.py)."""

from __future__ import annotations

import argparse
import json
import sys

from . import q1, q2, sim7, status, v7
from .common import V6_ROOT, V7_ROOT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scene_batching_v6")
    parser.add_argument("--round", choices=("v6", "v7"), default="v6",
                        help="v7: root .local/gap-aware-batching-v7, full-set subsets and comparisons")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("simulate", help="v7 offline: batch-size distributions on dev and product timing -> sim/sim.json")
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
            p.add_argument("--candidate-only", action="store_true", help="skip the control copy (v7: judged once)")
    c = sub.add_parser("compare", help="offline paired comparison on the affected subset")
    c.add_argument("--variant", required=True)
    c.add_argument("--seeds", type=int, nargs="+", required=True)
    c.add_argument("--control-seeds", type=int, nargs="+")
    c.add_argument("--label", default="")
    c.add_argument("--against", default=q2.CONTROL_COPY, help="v7: another variant instead of the control copy")
    jc = sub.add_parser("judge-control", help="v7: judge the control copy of a seed on the full set")
    jc.add_argument("--seed", type=int, required=True)
    jc.add_argument("--parallel", type=int, default=3)
    pl = sub.add_parser("pooled", help="v7: mean paired difference over independent seed sets")
    pl.add_argument("--variant", required=True)
    pl.add_argument("--seed-sets", required=True, help="e.g. 20261011,20261012,20261013/20261021,20261022,20261023")
    pl.add_argument("--against", default=q2.CONTROL_COPY)
    args = parser.parse_args(argv)
    root = V7_ROOT if args.round == "v7" else V6_ROOT
    if args.command == "simulate":
        report = sim7.simulate(V7_ROOT)
        out = {name: {s: {k: row[s][k] for k in ("requests_vs_b10", "mean_size", "share_lt6", "cross_ge_5s",
                                                 "cross_ge_10s", "affected_cue_share")}
                      for s in ("dev", "product")} for name, row in report["recipes"].items()}
    elif args.round == "v7" and args.command in ("q1",):
        parser.error("q1 is a v6 command")
    elif args.command == "status":
        out = status.status(root)
    elif args.command == "q1":
        out = {"written": str(q1.main())}
    elif args.command == "generate":
        out = q2.generate(args.recipe, args.seed, root=root, break_stale_lock=args.break_stale_lock)
    elif args.command == "copy-control":
        out = {"copied": str(q2.copy_control(args.control_seed or args.seed, root=root))}
    elif args.command == "subset":
        out = q2.build_subset(args.variant, args.seed, root=root, control_seed=args.control_seed,
                              full=args.round == "v7")
        out = {k: v for k, v in out.items() if k not in ("affected_cues", "windows")} | {
            "affected": len(out["affected_cues"]), "windows": len(out["windows"])}
    elif args.command == "judge":
        out = q2.judge(args.variant, args.seed, root=root, parallel=args.parallel, control_seed=args.control_seed,
                       candidate_only=args.candidate_only)
        print(json.dumps({"exit_code": out["exit_code"]}))
        return out["exit_code"]
    elif args.command == "judge-control":
        out = v7.judge_control(args.seed, parallel=args.parallel)
        print(json.dumps({"exit_code": out["exit_code"]}))
        return out["exit_code"]
    elif args.command == "pooled":
        sets = [[int(x) for x in part.split(",")] for part in args.seed_sets.split("/")]
        out = v7.pooled(args.variant, sets, against=args.against)
        out = {"cues": out.get("cues"), "accuracy": (out.get("full") or {}).get("accuracy", {}).get("delta"),
               "ci90": {k: v["ci90"] for k, v in ((out.get("full") or {}).get("accuracy", {}).get("bootstrap") or {}).items() if v}}
    elif args.round == "v7":
        out = v7.compare(args.variant, args.seeds, against=args.against, against_seeds=args.control_seeds,
                         label=args.label)
        out = {k: out.get(k) for k in ("state", "cues", "affected_share", "decision")}
    else:
        out = q2.compare(args.variant, args.seeds, control_seeds=args.control_seeds, label=args.label)
        out = {k: out.get(k) for k in ("state", "affected_cues", "by_category_counts", "full_set_guard")} | {
            "accuracy": (out.get("affected") or {}).get("accuracy", {}).get("delta")}
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
