"""v12: the Q1 translation step on Strata + Qwen3.8-Flash-Next IQ3_S (docs/research/2026-11-08-strata-flash-next-v12.md).

Layout under ``.local/strata-flash-next-v12`` (v9/v11 layout): ``recipes/`` (dev F1 / F2), ``runs/<recipe>__s<seed>__dev``
(F1, F2 and the Q1 dev runs copied from v11 for same-period re-judging), ``smoke/pass<k>/<run id>`` and
``smoke/report.json``, ``checks/``, ``summaries/``; the product stage under ``D/`` with the ``asr10`` layout
(``D/root`` for ``translate-srt`` deliveries and the F1 product recipe, ``D/zh/<arm>/<film>.s<seed>.zh.srt``,
``D/judge/<y>-vs-<x>/``) on seeds 20261054-56; the Q1 product SRTs are copied from v11 ``C/zh/q0-names-high``.

F1 (``flash-names-high``) is the v11 Q1 recipe file with ``model`` switched to Strata (same base, options and name
table); F2 adds ``qwen_options.thinking`` = {budget 1024, min_visible 1} (every pack thinks, §4.5). Generation goes
through ``qwen.session_factory``, which attaches to the running ``kototoki-translate`` Strata launch.

``run_stats`` / ``aa_diff`` / ``feasibility`` read the run files only (counts, no text); ``smoke`` runs the three v11
smoke scenes (§4.2) into ``smoke/pass<k>``.
"""

from __future__ import annotations

import json
import shutil
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from experiments.translation_v3 import qwen
from experiments.translation_v3 import recipes as R
from experiments.translation_v3.common import REPO, atomic_write_json, read_json
from experiments.translation_v3.generate import run_generation, run_id_for
from experiments.translation_v3.recipes import load_recipe
from experiments.translation_v4.common import DEFAULT_ROOT as V4_ROOT
from experiments.translation_v4.gen import set_scenes

from . import asr10, q2, v9, v11

V12_ROOT = REPO / ".local/strata-flash-next-v12"
D_ROOT = V12_ROOT / "D"
F1 = "flash-names-high"
F2 = "flash-names-high-think"
Q1_DEV = "qwen-names-dev-high"
Q1_PRODUCT = "q0-names-high"
MAIN_SEEDS = v9.MAIN_SEEDS
PRODUCT_SEEDS = v11.PRODUCT_SEEDS
SMOKE_SEED = MAIN_SEEDS[0]
SMOKE_SCOPE = "smoke3"
# Three of the five v11 smoke scenes (two series, one film; the v11 smoke used one pack of each, §4.2 asks for whole
# scenes): the first two series scenes and the first film scene of v9.smoke_batches(20261011).
SMOKE_SCENES = ("F2-W01_E022-S00127", "F2-W02_E014-S00084", "F2-M01-S00001")
THINKING = {"budget": 1024, "min_visible": 1}
FEASIBILITY_MAX_FIRST_FAIL = 0.05


# --- recipes ---------------------------------------------------------------------------------

def strata_recipe_data(q1: dict[str, Any], name: str, comment: str, thinking: dict[str, int] | None = None) -> dict[str, Any]:
    """A v11 Q1 recipe file with the model switched to Strata (and, for F2, bounded thinking added)."""
    if q1.get("base") != "qwen-wide" or set(q1) - {"name", "base", "comment", "qwen_options"}:
        raise ValueError("expected a v11 Q1 recipe file: base qwen-wide plus qwen_options only")
    options = dict(q1["qwen_options"])
    if thinking is not None:
        options["thinking"] = dict(thinking)
    return {"name": name, "base": "qwen-wide", "comment": comment, "model": R.STRATA_MODEL, "qwen_options": options}


def _write_once(path: Path, data: dict[str, Any]) -> None:
    if path.is_file():
        if read_json(path) != data:
            raise SystemExit(f"{path} exists with other content; recipes are written once")
        return
    atomic_write_json(path, data)


def write_recipes(*, root: Path = V12_ROOT, source: Path = v11.V11_ROOT) -> dict[str, str]:
    """F1 / F2 dev recipes (from v11 ``qwen-names-dev-high``) and the F1 product recipe (from v11 ``q0-names-high``);
    the Q1 recipe files are copied next to them. Returns recipe hashes (no table content)."""
    dev_q1 = read_json(source / "recipes" / f"{Q1_DEV}.json")
    prod_q1 = read_json(source / "C/root/recipes" / f"{Q1_PRODUCT}.json")
    _write_once(root / "recipes" / f"{Q1_DEV}.json", dev_q1)
    _write_once(root / "recipes" / f"{F1}.json", strata_recipe_data(
        dev_q1, F1, "v12 F1: v11 Q1 (dev tables, high only) with the model switched to Strata Flash-Next IQ3_S"))
    _write_once(root / "recipes" / f"{F2}.json", strata_recipe_data(
        dev_q1, F2, "v12 F2: F1 + bounded thinking (budget 1024, every pack)", THINKING))
    _write_once(root / "D/root/recipes" / f"{Q1_PRODUCT}.json", prod_q1)
    _write_once(root / "D/root/recipes" / f"{F1}.json", strata_recipe_data(
        prod_q1, F1, "v12 F1: v11 Q1 (product tables, high only) with the model switched to Strata Flash-Next IQ3_S"))
    return {"dev/" + n: load_recipe(n, root).recipe_hash for n in (Q1_DEV, F1, F2)} | {
        "product/" + n: load_recipe(n, root / "D/root").recipe_hash for n in (Q1_PRODUCT, F1)}


# --- Q1 material (read only from v11) ----------------------------------------------------------

def copy_q1_dev(seed: int, *, root: Path = V12_ROOT, source: Path = v11.V11_ROOT) -> Path:
    return v11.copy_run(Q1_DEV, seed, root=root, source=source)


def copy_q1_product(*, root: Path = D_ROOT, source: Path = v11.C_ROOT) -> list[str]:
    out = []
    for film in asr10.FILMS:
        for seed in PRODUCT_SEEDS:
            src, dst = asr10.zh_path(Q1_PRODUCT, film, seed, source), asr10.zh_path(Q1_PRODUCT, film, seed, root)
            if not dst.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
            out.append(dst.name)
    return out


# --- GPU entries (attach to the running Strata launch) -----------------------------------------

def smoke(pass_no: int, *, root: Path = V12_ROOT, port: int = 8080, seed: int = SMOKE_SEED) -> dict[str, Any]:
    recipe = load_recipe(F1, root)
    scenes = [s for s in set_scenes(V4_ROOT, q2.SET, seed)[0] if s.scene_id in SMOKE_SCENES]
    if {s.scene_id for s in scenes} != set(SMOKE_SCENES):
        raise ValueError(f"smoke scenes not found in the dev block of seed {seed}")
    run_id = run_id_for(recipe, seed, SMOKE_SCOPE)
    run_dir = root / "smoke" / f"pass{pass_no}" / run_id
    run = run_generation(run_dir, recipe, seed, scenes, scope=SMOKE_SCOPE, sources={"scenes": list(SMOKE_SCENES)},
                         session_factory=qwen.session_factory(root, run_id, recipe, port=port))
    return {"run_id": run_id, "pass": pass_no, "completion": run["completion"],
            "wall_clock_seconds": run.get("wall_clock_seconds")}


def aa_dir(recipe: str, seed: int, *, root: Path = V12_ROOT) -> Path:
    return root / "runs-aa" / f"{recipe}__s{seed}__{q2.SET}"


def generate_aa(recipe_name: str, seed: int, *, root: Path = V12_ROOT, port: int = 8080) -> dict[str, Any]:
    """The A/A repeat of a dev run (§4.3: s20261011 once more, diff only, not judged) under ``runs-aa/``."""
    recipe = load_recipe(recipe_name, root)
    scenes, sources = set_scenes(V4_ROOT, q2.SET, seed)
    run_id = run_id_for(recipe, seed, q2.SET)
    run = run_generation(aa_dir(recipe_name, seed, root=root), recipe, seed, scenes, scope=q2.SET, sources=sources,
                         session_factory=qwen.session_factory(root, run_id, recipe, port=port))
    return {"run_id": run_id, "completion": run["completion"], "wall_clock_seconds": run.get("wall_clock_seconds")}


# --- run statistics (counts only) ---------------------------------------------------------------

def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def run_stats(run_dir: Path) -> dict[str, Any]:
    """Format / delivery / thinking / latency / resource counts of one run (dev, smoke or a translate-srt delivery)."""
    packs = first_fail = delivered_fail = reasoning = limits = over = 0
    kinds: Counter = Counter()
    latency, out_tok, out_sec = [], 0, 0.0
    first_cache = None
    for path in sorted((run_dir / "scenes").glob("*.json")):
        row = read_json(path)
        for record in row.get("requests", []):
            if record.get("stage") != "translation" or not record.get("attempts"):
                continue
            packs += 1
            attempts = record["attempts"]
            if attempts[0].get("status") != "accepted":
                first_fail += 1
                kinds[attempts[0].get("error_kind")] += 1
            if record.get("status") != "accepted":
                delivered_fail += 1
            for a in attempts:
                reasoning += bool(a.get("reasoning_chars"))
                limits += bool(a.get("stopped_limit"))
                over += bool(a.get("over_q1_budget"))
                if first_cache is None and "cache_reset_check" in a:
                    first_cache = a["cache_reset_check"].get("first_cache_n")
                if a.get("status") == "accepted" and isinstance(a.get("output_tokens"), int):
                    out_tok += a["output_tokens"]
                    out_sec += a.get("completion_seconds") or 0.0
            latency.append(sum(a.get("elapsed_seconds") or 0.0 for a in attempts))
    sessions = sorted((run_dir / "runtime").glob("session-*/resources.json"))
    resources = [read_json(p) for p in sessions]
    events: Counter = Counter()
    for r in resources:
        events.update(r.get("log_events") or {})
    run = read_json(run_dir / "run.json") if (run_dir / "run.json").is_file() else {}
    peak = lambda key: max((r[key] for r in resources if r.get(key) is not None), default=None)  # noqa: E731
    return {"packs": packs, "first_attempt_failures": first_fail,
            "first_attempt_failure_rate": first_fail / packs if packs else None,
            "first_attempt_failure_kinds": dict(kinds), "delivery_failures": delivered_fail,
            "attempts_with_reasoning": reasoning, "limit_stops": limits, "over_q1_budget": over,
            "first_cache_n": first_cache, "pack_seconds": {
                "mean": statistics.fmean(latency) if latency else None, "median": _quantile(latency, 0.5),
                "p90": _quantile(latency, 0.9), "max": max(latency, default=None)},
            "accepted_tokens_per_second": out_tok / out_sec if out_sec else None,
            "log_events": dict(events) if resources and all(r.get("log_events") is not None for r in resources) else None,
            "peak_gpu_used_mib": peak("gpu_used_mib"), "peak_ram_used_gib": peak("ram_used_gib"),
            "wall_clock_seconds": run.get("wall_clock_seconds"), "sessions": len(run.get("sessions", []))}


def _pack_translations(run_dir: Path) -> dict[tuple[str, int], dict[str, str]]:
    out = {}
    for path in sorted((run_dir / "scenes").glob("*.json")):
        row = read_json(path)
        for b in row["batches"]:
            out[(row["scene_id"], b["index"])] = {k: row["translations"].get(k) for k in b["target_ids"]}
    return out


def aa_diff(run_a: Path, run_b: Path) -> dict[str, Any]:
    """Share of packs and cues whose text differs between two runs of the same recipe and seed."""
    a, b = _pack_translations(run_a), _pack_translations(run_b)
    keys = sorted(a.keys() & b.keys())
    cues = [(k, c) for k in keys for c in a[k]]
    diff_packs = sum(a[k] != b[k] for k in keys)
    diff_cues = sum(a[k][c] != b[k].get(c) for k, c in cues)
    return {"packs": len(keys), "packs_different": diff_packs, "pack_share": diff_packs / len(keys) if keys else None,
            "cues": len(cues), "cues_different": diff_cues, "cue_share": diff_cues / len(cues) if cues else None}


def feasibility(stats: list[dict[str, Any]]) -> dict[str, Any]:
    """§4.2 gate over the smoke passes: no delivery failure, first-attempt format failures <= 5 %, no thinking output,
    no non-finite-logits stop (unknown when the server log was not readable)."""
    packs = sum(s["packs"] for s in stats)
    first = sum(s["first_attempt_failures"] for s in stats)
    nonfinite = None if any(s["log_events"] is None for s in stats) else sum(
        s["log_events"].get("nonfinite_logits", 0) for s in stats)
    checks = {"delivery_failures_zero": sum(s["delivery_failures"] for s in stats) == 0,
              "first_attempt_failure_rate_ok": packs > 0 and first / packs <= FEASIBILITY_MAX_FIRST_FAIL,
              "no_thinking_output": sum(s["attempts_with_reasoning"] for s in stats) == 0,
              "no_nonfinite_logits": None if nonfinite is None else nonfinite == 0}
    return {"packs": packs, "first_attempt_failures": first, "first_attempt_failure_rate": first / packs if packs else None,
            "checks": checks, "passed": all(v is True for v in checks.values())}


def smoke_report(*, root: Path = V12_ROOT, seed: int = SMOKE_SEED) -> dict[str, Any]:
    run_id = run_id_for(load_recipe(F1, root), seed, SMOKE_SCOPE)
    dirs = [root / "smoke" / f"pass{k}" / run_id for k in (1, 2)]
    stats = [run_stats(d) for d in dirs]
    report = {"run_id": run_id, "passes": stats, "aa": aa_diff(*dirs), "gate": feasibility(stats)}
    atomic_write_json(root / "smoke" / "report.json", report)
    return report


def dev_stats(recipe: str, seeds: list[int], *, root: Path = V12_ROOT) -> dict[str, Any]:
    out = {f"s{s}": run_stats(q2.run_dir(root, recipe, s)) for s in seeds}
    atomic_write_json(root / "checks" / f"stats-{recipe}.json", out)
    return out


def dev_aa(recipe: str, seed: int, *, root: Path = V12_ROOT) -> dict[str, Any]:
    out = aa_diff(q2.run_dir(root, recipe, seed), aa_dir(recipe, seed, root=root))
    atomic_write_json(root / "checks" / f"aa-{recipe}-s{seed}.json", out)
    return out


def product_stats(arm: str, *, root: Path = D_ROOT, seeds: tuple[int, ...] = PRODUCT_SEEDS) -> dict[str, Any]:
    """``run_stats`` of every translate-srt delivery of an arm (one per film x seed)."""
    out = {}
    for path in sorted((root / "root" / "deliveries").glob(f"{arm}__s*")):
        seed = int(path.name.split("__s", 1)[1].split("__", 1)[0])
        if seed in seeds:
            out[path.name] = run_stats(path)
    atomic_write_json(root / f"stats-{arm}.json", out)
    return out


def product(command: str, *, x: str | None = None, y: str | None = None, arms: list[str] = (),
            name: str | None = None) -> Any:
    """``asr10`` bound to the v12 product root and seeds (same commands as v11 ``product``)."""
    root, seeds = D_ROOT, PRODUCT_SEEDS
    if command == "plan":
        return str(asr10.plan(x, y, v11.PRODUCT_QUOTAS, root=root, seeds=seeds, skip_identical=True))
    if command == "judge":
        return asr10.judge(name or f"{y}-vs-{x}", root=root)
    if command == "estimate":
        return asr10.estimate(name or f"{y}-vs-{x}", root=root)
    if command == "inconsistency":
        return asr10.inconsistency(list(arms), root=root, seeds=seeds, name=name or "inconsistency")
    if command == "failures":
        return {a: asr10.delivery_failures(a, root=root, seeds=seeds) for a in arms}
    if command == "stats":
        return {a: product_stats(a) for a in arms}
    raise ValueError(command)


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1, default=str)
