"""v11: component verification on the Q0 product route (docs/research/2026-10-22-q0-product-route-v11.md).

Layout under ``.local/q0-product-route-v11``: dev runs as v9/v10 (``runs/<recipe>__s<seed>__dev``, ``smoke/``,
``checks/``, ``summaries/``, ``recipes/``); the product stage under ``C/`` with the ``asr10`` layout (``C/root`` for
``translate-srt`` deliveries and arm recipes, ``C/zh/<arm>/<film>.s<seed>.zh.srt``, ``C/judge/<y>-vs-<x>/``) on the
new seeds 20261054-56. v10 artefacts are read only: ``copy_run`` copies translations (no judgements) for same-period
re-judging.

Diff before judging (§2.3): on the product source ``asr10.plan(skip_identical=True)`` leaves byte-identical units
out of the plan and ``asr10.estimate`` counts them as Δ = 0. On dev the mqm judge works in fixed packets of four
5-cue windows shared by every run; ``copy_identical_packets`` copies the control's judgement of a packet whose 20
cues are all identical in the candidate (cost 0, ``surface: copied-identical``), the other packets are judged as
usual, and ``compare11`` sets the candidate's row of every identical cue to the control's row (Δ = 0) before the
paired statistics. ``identical_cues`` records the per-seed lists under ``checks/``.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from experiments.translation_v3 import judge as J
from experiments.translation_v3.common import REPO, atomic_write_json, read_json, sha256_bytes
from experiments.translation_v3.generate import load_run_translations
from experiments.translation_v4 import evaluate as E
from experiments.translation_v4.common import DEFAULT_ROOT as V4_ROOT

from . import asr10, q2, v9, v10

V11_ROOT = REPO / ".local/q0-product-route-v11"
C_ROOT = V11_ROOT / "C"
PRODUCT_SEEDS = (20261054, 20261055, 20261056)
MAIN_SEEDS = v9.MAIN_SEEDS
Q0 = v10.Q0
PRODUCT_QUOTAS = {"exact": "all", "light": "all", "heavy": "all"}


def copy_run(recipe: str, seed: int, *, root: Path = V11_ROOT, source: Path = v10.V10_ROOT) -> Path:
    """Copy a v10 run's translations (not its judgements) into the v11 root for same-period re-judging."""
    return v10.copy_control(seed, root=root, source=source, recipe=recipe)


# --- dev: identical cues and packets ---------------------------------------------------------

def identical_cues(variant: str, against: str, seed: int, *, root: Path = V11_ROOT) -> dict[str, Any]:
    ta, _ = load_run_translations(q2.run_dir(root, variant, seed))
    tb, _ = load_run_translations(q2.run_dir(root, against, seed))
    keys = sorted(ta.keys() & tb.keys())
    ids = [k for k in keys if ta[k] == tb[k]]
    out = {"variant": variant, "against": against, "seed": seed, "cues": len(keys), "identical": len(ids), "ids": ids}
    atomic_write_json(root / "checks" / f"identical-{variant}-vs-{against}-s{seed}.json", out)
    return out


def packet_id(run_id: str, window_ids: list[str], replicate: int = 0) -> str:
    """The id ``judge.plan_packets`` gives a packet of these windows in this run (the shuffle is run-independent)."""
    return "p" + sha256_bytes(f"{J.PROFILE_ID}|{run_id}|rep{replicate}|{','.join(window_ids)}".encode())[:19]


def identical_packet_results(control_packets: list[dict], control_results: dict[str, dict], identical: set[str],
                             window_cues: dict[str, list[str]], candidate_run_id: str) -> dict[str, dict]:
    """candidate packet id -> result file content, for every control packet with a result whose cues are all
    identical in the candidate; the judgement is the control's, the meta says so and costs 0."""
    out = {}
    for packet in control_packets:
        result = control_results.get(packet["packet_id"])
        cues = [c for w in packet["window_ids"] for c in window_cues[w]]
        if result is None or not cues or any(c not in identical for c in cues):
            continue
        new_id = packet_id(candidate_run_id, packet["window_ids"])
        out[new_id] = dict(result, packet_id=new_id, surface="copied-identical",
                           meta={"copied_from_packet": packet["packet_id"], "identical_cues": len(cues),
                                 "total_cost_usd": 0.0})
    return out


def copy_identical_packets(variant: str, against: str, seed: int, *, root: Path = V11_ROOT) -> dict[str, Any]:
    """Before judging the candidate: write the control's judgement for every packet whose cues are all identical."""
    identical = set(identical_cues(variant, against, seed, root=root)["ids"])
    ctl_dir = q2.run_dir(root, against, seed) / "judge" / J.profile_dir_name()
    plan = read_json(ctl_dir / "packets.json")
    results = {}
    for packet in plan["packets"]:
        path = ctl_dir / f"{packet['packet_id']}.json"
        if path.is_file():
            row = read_json(path)
            if row.get("profile_hash") == J.PROFILE_HASH:
                results[packet["packet_id"]] = row
    windows = E.reference_for(V4_ROOT, q2.SET)
    window_cues = {k: [u["id"] for u in w.units] for k, w in windows.items()}
    cand_dir = q2.run_dir(root, variant, seed)
    run_id = read_json(cand_dir / "run.json")["run_id"]
    copies = identical_packet_results(plan["packets"], results, identical, window_cues, run_id)
    out_dir = cand_dir / "judge" / J.profile_dir_name()
    written = 0
    for pid, row in copies.items():
        if not (out_dir / f"{pid}.json").is_file():
            atomic_write_json(out_dir / f"{pid}.json", row)
            written += 1
    report = {"variant": variant, "against": against, "seed": seed, "control_packets": len(plan["packets"]),
              "control_judged": len(results), "identical_cues": len(identical), "copied_packets": len(copies),
              "written": written}
    atomic_write_json(root / "checks" / f"copied-packets-{variant}-vs-{against}-s{seed}.json", report)
    return report


# --- dev: paired comparison with identical cues at Δ = 0 -----------------------------------------

def apply_identical(cand: dict[str, dict], ctrl: dict[str, dict], identical: set[str]) -> int:
    """Set the candidate's row of every identical cue to the control's row; returns how many were set."""
    n = 0
    for k in identical:
        if k in cand and k in ctrl:
            cand[k] = dict(ctrl[k])
            n += 1
    return n


def compare11(variant: str, seeds: list[int], *, against: str = Q0, root: Path = V11_ROOT,
              label: str = "") -> dict[str, Any]:
    """``v9.compare`` with identical cues forced to Δ = 0, plus name-error counts (same override) and the dev
    name inconsistency of both arms; ``summaries/v11-<variant>-vs-<against>.json``."""
    all_windows = E.reference_for(V4_ROOT, q2.SET)
    cand: dict[str, dict[str, float]] = {}
    ctrl: dict[str, dict[str, float]] = {}
    errs_c: dict[str, list] = {}
    errs_k: dict[str, list] = {}
    scenes: set[str] = set()
    missing: dict[str, int] = {}
    identical: set[str] = set()
    for seed in seeds:
        run_scenes = set(read_json(q2.run_dir(root, variant, seed) / "run.json")["scene_ids"])
        if run_scenes != set(read_json(q2.run_dir(root, against, seed) / "run.json")["scene_ids"]):
            raise ValueError(f"seed {seed}: arms cover different scenes")
        scenes |= run_scenes
        windows = {k: w for k, w in all_windows.items() if w.meta.scene_id in run_scenes}
        for target, errs, name in ((cand, errs_c, variant), (ctrl, errs_k, against)):
            rows = v9.arm_rows(q2.run_dir(root, name, seed), windows)
            if rows["missing"]:
                missing[f"{name}__s{seed}"] = len(rows["missing"])
            target.update(rows["values"])
            errs.update(v9._errors(q2.run_dir(root, name, seed), windows))
        identical |= set(identical_cues(variant, against, seed, root=root)["ids"])
    if missing:
        return {"state": "insufficient", "missing_windows": missing}
    overridden = apply_identical(cand, ctrl, identical)
    for k in identical:
        if k in errs_k:
            errs_c[k] = errs_k[k]
    name = f"v11-{variant}-vs-{against}{('-' + label) if label else ''}.json"
    report = v9.report_from_rows(variant, against, seeds, cand, ctrl, scenes, all_windows, root=root, name=name)
    report["identical_cues"] = {"total": len(identical), "overridden": overridden}
    category = {u["id"]: w.meta.category for w in all_windows.values() for u in w.units}
    counts: dict[str, Counter] = {variant: Counter(), against: Counter()}
    for arm, errs in ((variant, errs_c), (against, errs_k)):
        for k, es in errs.items():
            if k in cand and k in ctrl:
                counts[arm][category[k]] += sum(bool(v9.NAME_ERROR.search(e["evidence_zh"])) for e in es)
    report["name_errors"] = {a: dict(c) for a, c in counts.items()}
    names = v9.name_errors(list(seeds), arms=(variant, against), root=root)
    report["inconsistency_by_category"] = {a: r["inconsistency_by_category"] for a, r in names["arms"].items()}
    atomic_write_json(root / "summaries" / name, report)
    return report


def summary11(report: dict[str, Any]) -> dict[str, Any]:
    out = v10.summary(report)
    for key in ("identical_cues", "name_errors", "inconsistency_by_category", "delivery"):
        if key in report:
            out[key] = report[key]
    return out


# --- product stage (C): asr10 bound to the v11 root and seeds ----------------------------------

def product(command: str, *, x: str | None = None, y: str | None = None, arms: list[str] = (),
            name: str | None = None) -> Any:
    root, seeds = C_ROOT, PRODUCT_SEEDS
    if command == "plan":
        return str(asr10.plan(x, y, PRODUCT_QUOTAS, root=root, seeds=seeds, skip_identical=True))
    if command == "judge":
        return asr10.judge(name or f"{y}-vs-{x}", root=root)
    if command == "estimate":
        return asr10.estimate(name or f"{y}-vs-{x}", root=root)
    if command == "estimate08":
        return estimate08(name or f"{y}-vs-{x}", root=root)
    if command == "inconsistency":
        return asr10.inconsistency(list(arms), root=root, seeds=seeds, name=name or "inconsistency")
    if command == "replace":
        return {"written": [asr10.replace_names(a, root=root, seeds=seeds) for a in arms]}
    if command == "failures":
        return {a: asr10.delivery_failures(a, root=root, seeds=seeds) for a in arms}
    raise ValueError(command)


# --- ticket 08: units affected by the cross-segment truncation --------------------------------

def affected_positions(scenes: list, gap: float = 10.0) -> dict[str, set[int]]:
    """scene id -> 0-based cue positions that are targets of a pack whose read-only neighbours ``seg<gap>``
    truncates (fewer before or after neighbours than ``qwen-wide``; the packs themselves are identical)."""
    from experiments.translation_v3 import recipes as R
    from experiments.translation_v3.batching import build_batches
    from .seg11 import seg_recipe
    out: dict[str, set[int]] = {}
    for scene in scenes:
        base, cut = build_batches(scene, R.BUILTIN["qwen-wide"]), build_batches(scene, seg_recipe(gap))
        assert [b.target_ids for b in base] == [c.target_ids for c in cut]
        pos: set[int] = set()
        for b, c in zip(base, cut):
            if len(b.before_ids) != len(c.before_ids) or len(b.after_ids) != len(c.after_ids):
                pos.update(range(c.start, c.stop))
        out[scene.scene_id] = pos
    return out


def split_affected(rows: list[dict], identical: list[dict], units: dict[str, list[dict]],
                   affected: dict[str, set[int]]) -> tuple[tuple[list, list], tuple[list, list]]:
    """((rows, identical) of affected units, (rows, identical) of the rest). A unit is affected when any of its
    product cues (``asr_ids``, positions in the product ``ja.srt``) sits in an affected pack."""
    def hit(r: dict) -> bool:
        unit = units[r["film"]][r["unit"]]
        return any(i in affected[asr10.UNIT_FILM[r["film"]]] for i in unit["asr_ids"])
    return (([r for r in rows if hit(r)], [u for u in identical if hit(u)]),
            ([r for r in rows if not hit(r)], [u for u in identical if not hit(u)]))


def _category_counts(rows: list[dict], categories=("mistranslation", "addition", "omission", "terminology")) -> dict:
    """Per bucket, per category: [control, candidate] error counts over the judged rows."""
    out: dict[str, dict[str, list[int]]] = {}
    for bucket in (*asr10.JUDGED, "all"):
        js = [r for r in rows if bucket == "all" or r["bucket"] == bucket]
        if js:
            out[bucket] = {c: [sum(e["category"] == c for r in js for e in r["x_errors"]),
                               sum(e["category"] == c for r in js for e in r["y_errors"])] for c in categories}
    return out


def estimate08(name: str, *, gap: float = 10.0, root: Path = C_ROOT) -> dict[str, Any]:
    """``asr10.estimate`` split into the units affected by the truncation and the rest (§4 ticket 08), with the
    affected units' mistranslation / addition counts → ``C/judge/<name>/estimate08.json``."""
    from experiments.quality_v5 import asr_source as A
    from .seg11 import product_scenes
    folder = root / "judge" / name
    rows = A.collect(folder / "plan.json", folder / "packets")
    plan_ = read_json(folder / "plan.json")
    units = asr10.load_units()
    affected = affected_positions(product_scenes(), gap)
    (ra, ia), (ru, iu) = split_affected(rows, plan_.get("identical", []), units, affected)
    report = {"comparison": name, "gap": gap,
              "affected_cue_positions": {f: len(p) for f, p in affected.items()},
              "affected_units": {"judged": len(ra), "identical_delta_zero": len(ia)},
              "unaffected_units": {"judged": len(ru), "identical_delta_zero": len(iu)},
              "affected": asr10.summarize(name, ra, ia), "unaffected": asr10.summarize(name, ru, iu),
              "affected_error_counts": _category_counts(ra)}
    atomic_write_json(folder / "estimate08.json", report)
    return report
