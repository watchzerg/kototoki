"""`python -m experiments.translation_v4 <command>`; see README.md (Simplified Chinese)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .common import DEFAULT_ROOT, SETS


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def cmd_review(args: argparse.Namespace) -> int:
    from . import reference
    summary = reference.review_set(args.root, args.set, reference.review_backend(args.claude), parallel=args.parallel,
                                   max_scenes=args.max_scenes, log=(lambda _: None) if args.set == "confirm" else print)
    _print(summary)
    return summary["exit_code"]


def cmd_freeze(args: argparse.Namespace) -> int:
    from . import reference
    summary = reference.freeze(args.root, args.set)
    _print({k: summary[k] for k in ("set", "counts", "output")} | {"already_frozen": summary.get("already_frozen", False)})
    return 0


EXIT_LOCKED = 3


def cmd_generate(args: argparse.Namespace) -> int:
    from experiments.translation_v3.server import LockError
    from .gen import do_generate
    try:
        result = do_generate(args.root, args.recipe, args.seed, args.set, port=args.port,
                             break_stale_lock=args.break_stale_lock, retry_failed=args.retry_failed)
    except LockError as exc:
        print(f"GPU lock: {exc}", file=sys.stderr)
        return EXIT_LOCKED
    _print(result)
    return 0 if result["completion"]["state"] == "complete" else 1


def cmd_queue(args: argparse.Namespace) -> int:
    from experiments.translation_v3.recipes import load_recipe
    from experiments.translation_v3.status import add_job, read_queue
    from .gen import seeds_for
    if args.queue_cmd == "add":
        load_recipe(args.recipe, args.root)
        for seed in args.seed or seeds_for(args.set, args.replicate):
            _print(add_job(args.root, args.recipe, seed, args.set))
    else:
        _print(read_queue(args.root))
    return 0


def cmd_run_queue(args: argparse.Namespace) -> int:
    from experiments.translation_v3.cli import run_finished
    from experiments.translation_v3.server import LockError
    from experiments.translation_v3.status import read_queue
    from .gen import do_generate
    code = 0
    for job in read_queue(args.root):
        run_dir = args.root / "runs" / f"{job['recipe']}__s{job['seed']}__{job['scope']}"
        if run_finished(run_dir):
            continue
        try:
            result = do_generate(args.root, job["recipe"], job["seed"], job["scope"], port=args.port,
                                 break_stale_lock=args.break_stale_lock)
        except LockError as exc:
            print(f"GPU lock: {exc}", file=sys.stderr)
            return EXIT_LOCKED
        _print(result)
        if result["completion"]["missing_scene_ids"]:
            print("Run stopped early (infrastructure failure); queue halted. Rerun run-queue to retry.", file=sys.stderr)
            return 1
        code |= result["completion"]["state"] != "complete"
    return code


def _run_dir(root: Path, run: str) -> Path:
    path = root / "runs" / run
    if not (path / "run.json").is_file():
        raise FileNotFoundError(f"No run.json for {run} under {root / 'runs'}")
    return path


def cmd_judge(args: argparse.Namespace) -> int:
    from .evaluate import judge
    run_dir = _run_dir(args.root, args.run)
    quiet = run_dir.name.endswith("__confirm")
    summary = judge(args.root, run_dir, args.half, replicate=args.replicate, parallel=args.parallel,
                    max_packets=args.max_packets, log=(lambda _: None) if quiet else print)
    _print(summary)
    return summary["exit_code"]


def cmd_compare(args: argparse.Namespace) -> int:
    from experiments.translation_v3.common import atomic_write_json
    from .evaluate import reference_for
    from .stats4 import compare
    from .common import DEV_REPLICATE_SEEDS, DEV_SEEDS
    seeds = DEV_REPLICATE_SEEDS if args.candidate_replicate else (DEV_SEEDS if args.set == "dev" else None)
    control_seeds = (DEV_REPLICATE_SEEDS if args.control_replicate else DEV_SEEDS) if args.set == "dev" else None
    report = compare(args.root, reference_for(args.root, args.set), args.candidate, args.control, args.set,
                     halves=tuple(args.half), seeds=seeds, control_seeds=control_seeds, reps=args.reps,
                     calibration=args.calibration)
    tag = "".join(args.half) + ("-rep" if args.candidate_replicate else "") + ("-crep" if args.control_replicate else "") + ("-calib" if args.calibration else "")
    path = args.root / "summaries" / f"compare-{args.candidate}-vs-{args.control}-{args.set}-{tag}.json"
    atomic_write_json(path, report)
    acc = report.get("accuracy", {})
    _print({"decision": report.get("decision"), "reason": report.get("reason"), "cues": report.get("cues"),
            "delta": acc.get("delta"), "control": acc.get("control"),
            "se": (acc.get("bootstrap", {}).get("overall") or {}).get("se"),
            "ci95": (acc.get("bootstrap", {}).get("overall") or {}).get("ci95"),
            "p_ge_0": (acc.get("bootstrap", {}).get("overall") or {}).get("p_ge_0"),
            "gates": report.get("gates"), "summary_file": str(path)})
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    from . import calibrate as C
    from .evaluate import judge, reference_for
    from .stats4 import find_runs, recipe_cues
    from .common import CONTROL, DEV_REPLICATE_SEEDS, DEV_SEEDS
    windows = reference_for(args.root, "dev")
    if args.kind == "reference":
        run_dir = C.reference_run(args.root)
        if args.judge:
            _print(judge(args.root, run_dir, ["A"], parallel=args.parallel))
        report = C.level(run_dir, windows)
        if not report["missing_windows"]:
            C.save(args.root, "reference-self-check", report)
        _print({k: v for k, v in report.items() if k != "major_or_critical_cues"}
               | {"major_or_critical_cues": len(report["major_or_critical_cues"])})
        return 0
    controls = find_runs(args.root, CONTROL, "dev", DEV_SEEDS)
    if args.kind == "synthetic":
        base = controls[0]
        synth_dir = args.root / "runs" / f"synth-{CONTROL}-s{DEV_SEEDS[0]}__s0__dev"
        if not (synth_dir / "run.json").is_file():
            synth_dir, manifest = C.synthetic_run(args.root, base, windows)
            print(f"created {synth_dir.name}: {manifest['count']} perturbations {manifest['by_kind']}")
        manifest = C.read_json(args.root / "calibration" / "synthetic" / f"{synth_dir.name}.manifest.json")
        perturbed = {p["window_id"] for p in manifest["perturbations"]}
        if args.judge:
            only = {k: w for k, w in windows.items() if k in perturbed}
            _print(judge(args.root, synth_dir, ["A"], parallel=args.parallel, reference=only))
            _print(judge(args.root, base, ["A"], parallel=args.parallel))
        report = C.synthetic_report(args.root, synth_dir, base)
        C.save(args.root, "synthetic-detection", report)
        _print({k: v for k, v in report.items() if k != "rows"})
        return 0
    if args.kind == "repeat":
        base = controls[0]
        if args.judge:
            _print(judge(args.root, base, ["A"], replicate=1, parallel=args.parallel))
        report = C.repeat_noise(base, {k: w for k, w in windows.items() if w.meta.split == "dev-A"})
        C.save(args.root, "repeat-noise", report)
        _print(report)
        return 0
    if args.kind == "power":
        _print(_power(args.root, windows))
        return 0
    # aa / bridge: per-cue variance components of a null pair and of a real pair (c0 vs control)
    ctrl = recipe_cues(controls, windows)
    if args.kind == "aa":
        other = recipe_cues(find_runs(args.root, CONTROL, "dev", DEV_REPLICATE_SEEDS), windows)
    else:
        other = recipe_cues(find_runs(args.root, "c0", "dev", DEV_SEEDS), windows)
    if ctrl["missing"] or other["missing"]:
        _print({"insufficient": {k: len(v) for k, v in {**ctrl["missing"], **other["missing"]}.items()}})
        return 1
    report = C.pair_components(other, ctrl, windows)
    C.save(args.root, f"pair-{args.kind}", report)
    _print(report)
    return 0


def _power(root: Path, windows: dict) -> dict:
    """MDE table from the saved A/A and bridge pairs (no candidate scores): see power.py."""
    from collections import Counter
    from . import calibrate as C
    from .power import analytic_var, design_table
    from .reference import load_scenes
    aa, bridge = (C.read_json(root / "calibration" / f"pair-{k}.json") for k in ("aa", "bridge"))
    noise = aa["per_cue_var"]
    tau = max(0.0, bridge["per_cue_var"] - noise)
    layouts, category_of = {}, {}
    for set_name in ("dev", "confirm"):
        for scene in load_scenes(root, set_name):
            category_of[scene["work_id"]] = scene["category"]
    def counts(set_name, half=None):
        return dict(Counter(s["work_id"] for s in load_scenes(root, set_name) if half in (None, s.get("half"))
                            for _ in s["cues"]))
    dev_cues = counts("dev")
    deff = {"window_vs_analytic": bridge["se"] ** 2 / analytic_var(bridge["per_cue_var"], dev_cues, category_of),
            "scene_vs_window": (bridge["se_scene_unit"] / bridge["se"]) ** 2,
            "aa_scene_vs_window": (aa["se_scene_unit"] / aa["se"]) ** 2}
    used = max(1.0, deff["window_vs_analytic"]) * max(1.0, deff["scene_vs_window"], deff["aa_scene_vs_window"])
    layouts = {"dev-A (1 seed)": (counts("dev", "A"), category_of, 1), "dev-full (1 seed)": (dev_cues, category_of, 1),
               "dev-full (2 seeds)": (dev_cues, category_of, 2), "confirm (3 seeds)": (counts("confirm"), category_of, 3)}
    table = design_table(tau, noise, used, layouts, {"alpha0.05": 0.05, "alpha0.10": 0.10})
    report = {"noise_per_cue": noise, "tau_per_cue": tau, "deff": deff, "deff_used": used, "table": table,
              "aa_delta": aa["delta"], "bridge_delta": bridge["delta"], "control_level": aa["control_level"]}
    C.save(root, "power", report)
    return report


def cmd_confirm(args: argparse.Namespace) -> int:
    """Confirm-set test of every locked candidate vs the control, one-sided, Holm across the locked family.
    Prints aggregates and decisions only (no reference or judge text)."""
    from experiments.translation_v3.common import atomic_write_json, read_json, utc_now
    from .evaluate import reference_for
    from .stats4 import compare, holm, load_policy
    locked = read_json(args.root / "locked-candidates.json")
    policy = load_policy(args.root)
    alpha = policy.get("alpha_confirm", policy["alpha"])
    windows = reference_for(args.root, "confirm")
    reports, pvalues = {}, {}
    for name in locked["holm_family"]:
        report = compare(args.root, windows, name, "b10-joint", "confirm", halves=("A", "B"), reps=args.reps)
        reports[name] = report
        if report["decision"] == "insufficient":
            _print({name: {k: report.get(k) for k in ("decision", "reason", "missing", "missing_scenes")}})
            return 1
        pvalues[name] = report["accuracy"]["bootstrap"]["overall"]["p_ge_0"]
    adjusted = holm(pvalues, alpha)
    summary = {}
    for name, report in reports.items():
        acc = report["accuracy"]
        summary[name] = {"cues": report["cues"], "delta": acc["delta"], "se": acc["bootstrap"]["overall"]["se"],
                         "ci90": acc["bootstrap"]["overall"]["ci90"], "per_work": {w: round(v["delta"], 4) for w, v in acc["per_work"].items()},
                         "leave_one_work_out": acc["leave_one_work_out"], "critical_delta": report["critical"]["delta"],
                         "major_plus_delta": report["major_plus"]["delta"], "risk_major_plus": report["risk_major_plus"]["delta"],
                         "delivery_failed_scenes": {k: len(v) for k, v in report["delivery_failed_scenes"].items()},
                         "wall_clock_seconds": report["wall_clock_seconds"], "error_categories": report["error_categories"],
                         "gates": report["gates"], "decision_before_holm": report["decision"], "holm": adjusted[name],
                         "confirmed": report["decision"] == "confirmed_before_holm" and adjusted[name]["reject"]}
    out = {"family": locked["holm_family"], "alpha": alpha, "computed_at_utc": utc_now(), "results": summary}
    atomic_write_json(args.root / "summaries" / "confirm-holm.json", out)
    _print(out)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from .status import derive_status
    _print(derive_status(args.root))
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m experiments.translation_v4", description="Hy30 v4 flow exploration")
    p.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("review", help="Opus review of fansub Chinese into references (Claude quota)")
    s.add_argument("--set", choices=SETS, required=True)
    s.add_argument("--parallel", type=int, default=3)
    s.add_argument("--max-scenes", type=int)
    s.add_argument("--claude")
    s.set_defaults(func=cmd_review)
    s = sub.add_parser("freeze-reference")
    s.add_argument("--set", choices=SETS, required=True)
    s.set_defaults(func=cmd_freeze)

    def gpu_options(s: argparse.ArgumentParser) -> None:
        s.add_argument("--port", type=int, default=8080)
        s.add_argument("--break-stale-lock", action="store_true")
    s = sub.add_parser("generate")
    s.add_argument("--recipe", required=True)
    s.add_argument("--seed", type=int, required=True)
    s.add_argument("--set", choices=SETS, default="dev")
    s.add_argument("--retry-failed", action="store_true")
    gpu_options(s)
    s.set_defaults(func=cmd_generate)
    s = sub.add_parser("queue")
    qs = s.add_subparsers(dest="queue_cmd", required=True)
    qa = qs.add_parser("add")
    qa.add_argument("--recipe", required=True)
    qa.add_argument("--set", choices=SETS, default="dev")
    qa.add_argument("--seed", type=int, nargs="+", help="default: the set's three seeds")
    qa.add_argument("--replicate", action="store_true", help="dev: use the replicate seeds")
    qs.add_parser("list")
    s.set_defaults(func=cmd_queue)
    s = sub.add_parser("run-queue")
    gpu_options(s)
    s.set_defaults(func=cmd_run_queue)
    s = sub.add_parser("judge", help="blind MQM judging of one run (Claude quota; exit 75 = blocked)")
    s.add_argument("--run", required=True)
    s.add_argument("--half", nargs="+", choices=["A", "B"], default=["A", "B"])
    s.add_argument("--replicate", type=int, default=0)
    s.add_argument("--parallel", type=int, default=3)
    s.add_argument("--max-packets", type=int)
    s.set_defaults(func=cmd_judge)
    s = sub.add_parser("confirm", help="confirm-set test of the locked family with Holm (run once)")
    s.add_argument("--reps", type=int, default=10000)
    s.set_defaults(func=cmd_confirm)
    s = sub.add_parser("compare")
    s.add_argument("--candidate", required=True)
    s.add_argument("--control", default="b10-joint")
    s.add_argument("--set", choices=SETS, default="dev")
    s.add_argument("--half", nargs="+", choices=["A", "B"], default=["A", "B"])
    s.add_argument("--candidate-replicate", action="store_true", help="dev: candidate runs use the replicate seeds")
    s.add_argument("--control-replicate", action="store_true",
                   help="dev: control runs use the replicate seeds (removes the shared-control draw)")
    s.add_argument("--calibration", action="store_true", help="control-vs-control or bridge comparison, no decision")
    s.add_argument("--reps", type=int, default=10000)
    s.set_defaults(func=cmd_compare)
    s = sub.add_parser("calibrate", help="measurement calibration on dev (before the policy is frozen)")
    s.add_argument("kind", choices=["reference", "synthetic", "repeat", "aa", "bridge", "power"])
    s.add_argument("--judge", action="store_true", help="judge the needed packets first (Claude quota)")
    s.add_argument("--parallel", type=int, default=3)
    s.set_defaults(func=cmd_calibrate)
    sub.add_parser("status").set_defaults(func=cmd_status)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    args.root = args.root.resolve()
    return int(args.func(args) or 0)
