"""CLI: python -m experiments.scene_batching_v6 [--round v7|v9|v10] <command> (layout: q2.py; v7: v7.py; v9: v9.py;
v10: v9 commands on the v10 root plus v10.py)."""

from __future__ import annotations

import argparse
import json
import sys

from . import q1, q2, sim7, status, v7, v9, v10, v11
from .common import V6_ROOT, V7_ROOT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scene_batching_v6")
    parser.add_argument("--round", choices=("v6", "v7", "v9", "v10", "v11"), default="v6",
                        help="v7: root .local/gap-aware-batching-v7, full-set subsets and comparisons; "
                             "v9: root .local/general-model-translation-v9 (general-model arms); "
                             "v10: root .local/q0-exploration-v10 (v9 commands + v10 ones); "
                             "v11: root .local/q0-product-route-v11 (v9/v10 commands + v11 ones)")
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
    sm = sub.add_parser("smoke", help="v9 GPU: the 5 smoke packs on one Qwen arm")
    sm.add_argument("--recipe", required=True)
    sm.add_argument("--break-stale-lock", action="store_true")
    cb = sub.add_parser("check-batches", help="v9 offline: target-ID sequences of the three arms must be identical")
    cb.add_argument("--seed", type=int)
    jr = sub.add_parser("judge-run", help="v9: full-set judgement of one run")
    jr.add_argument("--recipe", required=True)
    jr.add_argument("--seed", type=int, required=True)
    jr.add_argument("--parallel", type=int, default=3)
    c9 = sub.add_parser("compare9", help="v9 offline: paired comparison with per-category metrics and the gates")
    c9.add_argument("--variant", required=True)
    c9.add_argument("--against", default=v9.CONTROL)
    c9.add_argument("--seeds", type=int, nargs="+", required=True)
    c9.add_argument("--label", default="")
    a9 = sub.add_parser("analyze9", help="v9 offline: names / leak / reading list / judge spend")
    a9.add_argument("what", choices=("names", "leak", "reading", "spend"))
    a9.add_argument("--seeds", type=int, nargs="+", default=[])
    c10 = sub.add_parser("compare10", help="v10 offline: compare9 + compact gate view")
    c10.add_argument("--variant", required=True)
    c10.add_argument("--against", default=v10.Q0)
    c10.add_argument("--seeds", type=int, nargs="+", required=True)
    c10.add_argument("--label", default="")
    cc = sub.add_parser("copy-q0", help="v10 offline: copy v9 Q0 translations of a main seed for re-judging")
    cc.add_argument("--seed", type=int, required=True)
    a10 = sub.add_parser("a2", help="v10 offline: A2 similarity (CPU bge-m3) or the blind sheet")
    a10.add_argument("what", choices=("similarity", "blind"))
    cr = sub.add_parser("copy-run", help="v11 offline: copy a v10 run's translations (no judgements) into the v11 root")
    cr.add_argument("--recipe", required=True)
    cr.add_argument("--seed", type=int, required=True)
    ci = sub.add_parser("copy-identical", help="v11 offline: before judging a candidate, copy the control's "
                                               "judgement of every packet whose cues are all identical")
    ci.add_argument("--variant", required=True)
    ci.add_argument("--against", default=v11.Q0)
    ci.add_argument("--seed", type=int, required=True)
    c11 = sub.add_parser("compare11", help="v11 offline: compare9 with identical cues at Δ = 0, name errors, "
                                           "dev inconsistency; compact gate view")
    c11.add_argument("--variant", required=True)
    c11.add_argument("--against", default=v11.Q0)
    c11.add_argument("--seeds", type=int, nargs="+", required=True)
    c11.add_argument("--label", default="")
    pr = sub.add_parser("product", help="v11 stage C (asr10 on C/, seeds 20261054-56): plan skips identical units")
    pr.add_argument("what", choices=("plan", "judge", "estimate", "estimate08", "inconsistency", "replace", "failures"))
    pr.add_argument("--x", help="control arm")
    pr.add_argument("--y", help="candidate arm")
    pr.add_argument("--arms", nargs="*", default=[])
    pr.add_argument("--name")
    args = parser.parse_args(argv)
    root = {"v7": V7_ROOT, "v9": v9.V9_ROOT, "v10": v10.V10_ROOT, "v11": v11.V11_ROOT}.get(args.round, V6_ROOT)
    v9_only = ("smoke", "check-batches", "judge-run", "compare9", "analyze9", "compare10", "copy-q0", "a2",
               "copy-run", "copy-identical", "compare11", "product")
    if args.command in ("compare10", "copy-q0", "a2") and args.round not in ("v10", "v11"):
        parser.error(f"{args.command} is a --round v10 command")
    if args.command in ("copy-run", "copy-identical", "compare11", "product") and args.round != "v11":
        parser.error(f"{args.command} is a --round v11 command")
    v9_like = args.round in ("v9", "v10", "v11")
    if v9_like != (args.command in v9_only) and args.command not in ("status", "generate"):
        parser.error(f"{args.command} is not a --round {args.round} command")
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
    elif args.command == "generate" and v9_like:
        out = v9.generate(args.recipe, args.seed, root=root, break_stale_lock=args.break_stale_lock)
    elif args.command == "smoke":
        out = v9.smoke(args.recipe, root=root, break_stale_lock=args.break_stale_lock)
    elif args.command == "check-batches":
        out = v9.check_batches(args.seed, root=root)
    elif args.command == "judge-run":
        out = v9.judge_run(args.recipe, args.seed, root=root, parallel=args.parallel)
        print(json.dumps({"exit_code": out["exit_code"]}))
        return out["exit_code"]
    elif args.command == "compare9":
        out = v9.compare(args.variant, args.seeds, against=args.against, root=root, label=args.label)
        out = {k: out.get(k) for k in ("state", "cues", "cue_counts", "decision")}
    elif args.command == "compare10":
        out = v10.summary(v9.compare(args.variant, args.seeds, against=args.against, root=root, label=args.label))
    elif args.command == "copy-q0":
        out = {"copied": str(v10.copy_control(args.seed, root=root) if args.round == "v10"
                             else v11.copy_run(v11.Q0, args.seed, root=root))}
    elif args.command == "copy-run":
        out = {"copied": str(v11.copy_run(args.recipe, args.seed, root=root))}
    elif args.command == "copy-identical":
        out = v11.copy_identical_packets(args.variant, args.against, args.seed, root=root)
    elif args.command == "compare11":
        out = v11.summary11(v11.compare11(args.variant, args.seeds, against=args.against, root=root, label=args.label))
    elif args.command == "product":
        out = v11.product(args.what, x=args.x, y=args.y, arms=args.arms, name=args.name)
        if args.what == "judge":
            print(json.dumps({"exit_code": out}))
            return out
        if args.what == "estimate":
            out = {k: v for k, v in out.items() if k != "buckets"} | {
                "buckets": {b: {k: r[k] for k in ("n", "n_identical", "delta", "ci90", "name_errors",
                                                  "name_error_delta_ci90")} for b, r in out["buckets"].items()}}
    elif args.command == "a2":
        from . import a2
        out = a2.blind_sheet() if args.what == "blind" else {k: v for k, v in a2.similarity().items() if k != "sets"}
    elif args.command == "analyze9":
        if args.what == "names":
            out = {a: {k: r[k] for k in ("errors", "inconsistency_by_category")}
                   for a, r in v9.name_errors(args.seeds, root=root)["arms"].items()}
        elif args.what == "leak":
            out = {k: v for k, v in v9.leak_check(args.seeds, root=root).items() if k != "hits"}
        elif args.what == "reading":
            out = {"written": [str(v9.reading_list(s, root=root)) for s in args.seeds]}
        else:
            out = v9.judge_spend(root)
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
               "ci90": {k: v["ci90"] for k, v in ((out.get("full") or {}).get("accuracy", {}).get("bootstrap") or {}).items() if isinstance(v, dict)}}
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
