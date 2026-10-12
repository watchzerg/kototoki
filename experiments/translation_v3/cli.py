"""`python -m experiments.translation_v3 <command>`; see README.md (Simplified Chinese)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .common import DEFAULT_ROOT, atomic_write_json, read_json, sha256_bytes, utc_now
from .generate import SessionFactory, managed_session_factory, run_generation, run_id_for

EXIT_LOCKED = 3


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def scope_scenes(root: Path, recipe, scope: str):
    from . import data
    from .common import check_locked_candidate
    if scope == "screening":
        scenes, _, hashes = data.load_screening()
    elif scope == "confirmation":
        check_locked_candidate(root, recipe.name, recipe.recipe_hash)
        scenes, _, hashes = data.load_confirmation()
    else:
        raise ValueError("scope must be screening or confirmation")
    return scenes, hashes


def do_generate(root: Path, recipe_name: str, seed: int, scope: str, *, port: int = 8080,
                break_stale_lock: bool = False, retry_failed: bool = False,
                session_factory: SessionFactory | None = None) -> dict[str, Any]:
    from .recipes import load_recipe
    recipe = load_recipe(recipe_name, root)
    scenes, hashes = scope_scenes(root, recipe, scope)
    run_id = run_id_for(recipe, seed, scope)
    factory = session_factory or managed_session_factory(root, run_id, port=port, break_stale_lock=break_stale_lock)
    run = run_generation(root / "runs" / run_id, recipe, seed, scenes, scope=scope, sources=hashes,
                         session_factory=factory, retry_failed=retry_failed)
    return {"run_id": run_id, "completion": run["completion"], "resumed": run["resumed"]}


def cmd_generate(args: argparse.Namespace) -> int:
    from .server import LockError
    try:
        result = do_generate(args.root, args.recipe, args.seed, args.scope, port=args.port,
                             break_stale_lock=args.break_stale_lock, retry_failed=args.retry_failed)
    except LockError as exc:
        print(f"GPU lock: {exc}", file=sys.stderr)
        return EXIT_LOCKED
    _print(result)
    return 0 if result["completion"]["state"] == "complete" else 1


def run_finished(run_dir: Path) -> bool:
    """Every scene has a terminal file; legacy infra-failure scene files count as unfinished (retried)."""
    from .generate import scene_state
    if not (run_dir / "run.json").is_file():
        return False
    return all(scene_state(run_dir, s) in ("complete", "failed") for s in read_json(run_dir / "run.json")["scene_ids"])


def cmd_run_queue(args: argparse.Namespace) -> int:
    from .server import LockError
    from .status import read_queue
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
            print("Run stopped early (infrastructure failure); queue halted. Rerunning run-queue retries the "
                  "unfinished scenes; inspect run.json sessions[].infra_failure first.", file=sys.stderr)
            return 1
        code |= result["completion"]["state"] != "complete"
    return code


def cmd_status(args: argparse.Namespace) -> int:
    from .status import derive_status
    _print(derive_status(args.root))
    return 0


def cmd_freeze(args: argparse.Namespace) -> int:
    from .data import freeze_reference
    summary = freeze_reference(args.root, force=args.force)
    _print({k: summary[k] for k in ("counts", "output")} | {"already_frozen": summary.get("already_frozen", False)})
    return 0


def cmd_queue(args: argparse.Namespace) -> int:
    from .recipes import load_recipe
    from .status import add_job, derive_status
    if args.queue_cmd == "add":
        load_recipe(args.recipe, args.root)
        for seed in args.seed:
            _print(add_job(args.root, args.recipe, seed, args.scope))
    else:
        _print(derive_status(args.root)["queue"])
    return 0


def _reference(root: Path):
    from .data import load_reference_v3
    return load_reference_v3(root)


def _run_dir(root: Path, run: str) -> Path:
    path = root / "runs" / run
    if not (path / "run.json").is_file():
        raise FileNotFoundError(f"No run.json for run {run} under {root / 'runs'}")
    return path


def ingest_contexts(root: Path, reference) -> list:
    from .judge import prepare_run
    contexts = []
    for plan_path in sorted((root / "runs").glob("*/judge/*/packets.json")):
        plan = read_json(plan_path)
        splits = sorted({p["split"] for p in plan["packets"]})
        split = "screening" if splits == ["screen-a", "screen-b"] else splits[0] if len(splits) == 1 else None
        if split is None:
            continue
        contexts.append(prepare_run(plan_path.parents[2], reference, split, plan["replicate"], root=root))
    return contexts


def cmd_judge(args: argparse.Namespace) -> int:
    from . import judge as J
    reference = _reference(args.root)
    if args.backend == "ingest":
        _print(J.ingest_packets(args.root, ingest_contexts(args.root, reference)))
        return 0
    if not args.run:
        raise SystemExit("--run is required for cli/export backends")
    run_dir = _run_dir(args.root, args.run)
    scope = read_json(run_dir / "run.json")["scope"]
    split = args.split or ("confirmation" if scope == "confirmation" else "screening")
    ctx = J.prepare_run(run_dir, reference, split, args.replicate, root=args.root)
    if args.backend == "export":
        queue, inbox = J.queue_dirs(args.root, ctx.confirmation)
        exported = J.export_packets(args.root, ctx, args.max_packets)
        _print({"exported": len(exported) if ctx.confirmation else exported,
                "queue_dir": str(queue), "inbox_dir": str(inbox)})
        return 0
    summary = J.judge_run(args.root, ctx, J.CliBackend(args.claude), max_packets=args.max_packets, parallel=args.parallel)
    _print(summary)
    return summary["exit_code"]


def _reference_pseudo_run(root: Path, reference) -> Path:
    from .data import load_screening
    scenes, _, hashes = load_screening()
    run_id = "reference-v3-self__s0__screening"
    run_dir = root / "runs" / run_id
    if (run_dir / "run.json").is_file():
        return run_dir
    zh = {u["id"]: u["zh"] for w in reference.values() if w.meta.split in ("screen-a", "screen-b") for u in w.units}
    for scene in scenes:
        translations = {cue.id: zh[cue.id] for cue in scene.cues if cue.id in zh}
        atomic_write_json(run_dir / "scenes" / f"{scene.scene_id}.json",
                          {"scene_id": scene.scene_id, "status": "complete", "cue_ids": scene.ids,
                           "translations": translations, "run_id": run_id})
    atomic_write_json(run_dir / "run.json", {
        "schema": "hy30-flow-v3-run-v1", "run_id": run_id, "pseudo": {"kind": "reference-self-check"},
        "recipe": {"name": "reference-v3-self"}, "recipe_hash": None, "seed": 0, "scope": "screening",
        "sources": hashes, "scene_ids": [s.scene_id for s in scenes], "created_at_utc": utc_now(), "sessions": [],
        "resumed": False, "completion": {"state": "complete", "missing_scene_ids": [], "failed_scene_ids": []}})
    return run_dir


def cmd_calibrate(args: argparse.Namespace) -> int:
    from . import stats, synth
    from .judge import load_judgements
    reference = _reference(args.root)
    out = args.root / "calibration"
    args.split = args.split or ("screening" if args.kind == "repeat" else "screen-a")
    if args.kind == "reference":
        run_dir = _reference_pseudo_run(args.root, reference)
        meta = {k: w for k, w in reference.items() if w.meta.split == args.split}
        report = stats.reference_self_check(run_dir, meta)
        if report["windows_judged"]:
            atomic_write_json(out / "reference-self-check.json", report)
        _print({k: report[k] for k in ("windows_judged", "accuracy", "fluency")}
               | {"major_or_critical_cues": len(report["major_or_critical_cues"]),
                  "next": f"judge --run {run_dir.name} --split {args.split}" if not report["windows_judged"] else None})
        return 0
    if args.kind == "synthetic":
        if not args.run:
            raise SystemExit("calibrate synthetic needs --run <base C0 run id>")
        base = _run_dir(args.root, args.run)
        base_read = read_json(base / "run.json")
        synth_id = f"synth-{base_read['recipe']['name']}-s{base_read['seed']}__s0__{base_read['scope']}"
        manifest_path = out / "synthetic" / f"{synth_id}.manifest.json"
        if not manifest_path.is_file():
            run_dir, manifest = synth.make_synthetic(args.root, base, reference, split=args.split)
            _print({"created": run_dir.name, "perturbations": manifest["count"], "by_kind": manifest["by_kind"],
                    "next": f"judge --run {run_dir.name} --split {args.split}"})
            return 0
        manifest = read_json(manifest_path)
        report = synth.detection_report(manifest, load_judgements(args.root / "runs" / synth_id)[0],
                                        load_judgements(base)[0] or None)
        atomic_write_json(out / "synthetic-detection.json", report)
        _print({k: v for k, v in report.items() if k != "rows"})
        return 0
    if not args.run:
        raise SystemExit("calibrate repeat needs --run <C0 run id or recipe prefix, e.g. c0>")
    meta = stats.split_meta(reference, args.split)
    run_dirs = ([args.root / "runs" / args.run] if (args.root / "runs" / args.run / "run.json").is_file()
                else stats.find_runs(args.root, args.run, "screening"))
    if not run_dirs:
        raise SystemExit(f"No runs match {args.run}")
    report = stats.repeat_noise(run_dirs, meta, args.replicate, reps=args.reps)
    if report.get("suggested_mde") is not None:
        atomic_write_json(out / f"repeat-noise-{args.run}.json", report)
    else:
        report["next"] = f"judge --run {args.run} --replicate {args.replicate}"
    _print(report)
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    from .stats import compare
    report = compare(args.root, _reference(args.root), args.candidate, args.control, args.split,
                     reps=args.reps, allow_without_policy=False)
    path = args.root / "summaries" / f"compare-{'+'.join(args.candidate)}-vs-{args.control}-{args.split}.json"
    atomic_write_json(path, report)
    _print({name: {"decision": r.get("decision"), "reason": r.get("reason"),
                   "primary_delta": r.get("primary", {}).get("delta"),
                   "ci95_overall": (r.get("primary", {}).get("bootstrap", {}).get("overall") or {}).get("ci95")}
            for name, r in report["candidates"].items()} | {"summary_file": str(path)})
    return 0


def cmd_translate_srt(args: argparse.Namespace) -> int:
    from experiments.translation_flow import srt
    from .data import Cue, Scene
    from .recipes import load_recipe
    document = srt.read_srt(args.srt)
    tag = f"srt-{document.source_sha256[:12]}"
    scene = Scene(tag, tuple(Cue(c.id, c.text, c.start_ms / 1000, c.end_ms / 1000) for c in document.cues),
                  category=args.category)
    recipe = load_recipe(args.recipe, args.root)
    recipe.for_category(args.category)  # fail before loading the model if routing needs a category
    run_id = run_id_for(recipe, args.seed, tag)
    run_dir = args.root / "deliveries" / run_id
    factory = managed_session_factory(args.root, run_id, port=args.port, break_stale_lock=args.break_stale_lock)
    run = run_generation(run_dir, recipe, args.seed, [scene], scope=tag,
                         sources={"srt": document.source_sha256}
                         | ({"category": args.category} if args.category else {}), session_factory=factory)
    row = read_json(run_dir / "scenes" / f"{tag}.json")
    report = srt.validate_translations(document, row.get("translations", {}) if row["status"] == "complete" else {})
    if report["status"] != "complete":
        _print({"run_id": run_id, "coverage": {k: report[k] for k in ("status", "expected_count", "valid_count")},
                "failure": row.get("failure")})
        return 1
    srt.write_srt(document, row["translations"], args.out)
    _print({"run_id": run_id, "out": str(args.out), "cues": report["expected_count"],
            "wall_clock_seconds": run["wall_clock_seconds"], "out_sha256": sha256_bytes(Path(args.out).read_bytes())})
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m experiments.translation_v3", description="Hy30 v3 flow exploration")
    p.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("status").set_defaults(func=cmd_status)
    s = sub.add_parser("freeze-reference")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_freeze)
    def gpu_options(s: argparse.ArgumentParser) -> None:
        s.add_argument("--port", type=int, default=8080)
        s.add_argument("--break-stale-lock", action="store_true")
    s = sub.add_parser("generate")
    s.add_argument("--recipe", required=True)
    s.add_argument("--seed", type=int, required=True)
    s.add_argument("--scope", choices=["screening", "confirmation"], default="screening")
    s.add_argument("--retry-failed", action="store_true")
    gpu_options(s)
    s.set_defaults(func=cmd_generate)
    s = sub.add_parser("queue")
    qs = s.add_subparsers(dest="queue_cmd", required=True)
    qa = qs.add_parser("add")
    qa.add_argument("--recipe", required=True)
    qa.add_argument("--seed", type=int, nargs="+", required=True)
    qa.add_argument("--scope", choices=["screening", "confirmation"], default="screening")
    qs.add_parser("list")
    s.set_defaults(func=cmd_queue)
    s = sub.add_parser("run-queue")
    gpu_options(s)
    s.set_defaults(func=cmd_run_queue)
    s = sub.add_parser("judge")
    s.add_argument("--run")
    s.add_argument("--backend", choices=["cli", "export", "ingest"], default="cli")
    s.add_argument("--split", choices=["screen-a", "screen-b", "screening", "confirmation"])
    s.add_argument("--replicate", type=int, default=0)
    s.add_argument("--max-packets", type=int)
    s.add_argument("--parallel", type=int, default=2)
    s.add_argument("--claude", help="claude executable (default: found on PATH)")
    s.set_defaults(func=cmd_judge)
    s = sub.add_parser("calibrate")
    s.add_argument("kind", choices=["reference", "synthetic", "repeat"])
    s.add_argument("--run")
    s.add_argument("--split", choices=["screen-a", "screen-b", "screening"],
                   help="default: screen-a (reference/synthetic), screening (repeat)")
    s.add_argument("--replicate", type=int, default=1)
    s.add_argument("--reps", type=int, default=10000)
    s.set_defaults(func=cmd_calibrate)
    s = sub.add_parser("compare")
    s.add_argument("--candidate", action="append", required=True, help="run prefix (recipe id); repeat for Holm")
    s.add_argument("--control", default="c0")
    s.add_argument("--split", required=True, choices=["screen-a", "screen-b", "screening", "confirmation"])
    s.add_argument("--reps", type=int, default=10000)
    s.set_defaults(func=cmd_compare)
    s = sub.add_parser("translate-srt")
    s.add_argument("--srt", type=Path, required=True)
    s.add_argument("--recipe", required=True)
    s.add_argument("--seed", type=int, required=True)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--category", choices=["anime_series", "animation_movie"],
                   help="content category; required by recipes with category_overrides")
    gpu_options(s)
    s.set_defaults(func=cmd_translate_srt)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    args.root = args.root.resolve()
    return int(args.func(args) or 0)
