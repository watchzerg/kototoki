"""v9: general model (Qwen3.8-27B) on the dp10-cut packs (docs/research/2026-10-21-general-model-translation-v9.md).

Layout under ``<v9 root>`` (``.local/general-model-translation-v9``), as q2/v7: ``runs/<recipe>__s<seed>__dev`` for
the three arms (``dp10-cut`` is generated fresh, there is no control copy), ``smoke/<recipe>.json``,
``checks/batches-s<seed>.json``, ``summaries/v9-<variant>-vs-<against>.json``.

* ``generate``: Hy-MT2 recipes use the v3 managed session (compat b11429), ``model`` recipes ``qwen.session_factory``.
* ``check_batches``: the per-scene target-ID sequences of the arms must be identical (offline on the whole dev set
  from the recipes, and on the run files); a difference is an implementation error.
* ``judge_run``: full-set judgement of one run (packets depend only on the split, so every arm shares them).
* ``compare``: paired Δ (candidate − against) per cue for accuracy, each accuracy and fluency category, fluency,
  major+ and critical, work-equal by category with the window bootstrap; the L1 gate and L2 decisions of §5; cost.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import statistics
import time
from typing import Any

from experiments.translation_v3 import qwen
from experiments.translation_v3 import recipes as R
from experiments.translation_v3.batching import build_batches
from experiments.translation_v3.common import REPO, atomic_write_json, read_json, utc_now
from experiments.translation_v3.generate import (StepFailed, load_run_translations, managed_session_factory,
                                                 run_generation, run_id_for)
from experiments.translation_v3.judge import ACCURACY, FLUENCY
from experiments.translation_v3.recipes import load_recipe
from experiments.translation_v3.stats import PENALTY
from experiments.translation_v4 import evaluate as E
from experiments.translation_v4 import stats4 as S4
from experiments.translation_v4.common import DEFAULT_ROOT as V4_ROOT
from experiments.translation_v4.gen import set_scenes
from experiments.translation_v4.stats4 import run_cues

from . import q2

V9_ROOT = REPO / ".local/general-model-translation-v9"
ARMS = ("dp10-cut", "qwen-narrow", "qwen-wide")
CONTROL = "dp10-cut"
MAIN_SEEDS = (20261011, 20261012, 20261013)
METRICS = ("accuracy", *ACCURACY, "fluency", *FLUENCY[:3], "major_plus", "critical")
NONINFERIORITY_MARGIN = 0.05
L1_CLOSE_MARGIN = 0.05
# smoke: 5 packs from the main-seed block, the first eligible pack of the first works in each category.
SMOKE_PACKS = {"anime_series": 3, "animation_movie": 2}


def generate(recipe_name: str, seed: int, *, root: Path = V9_ROOT, port: int = 8080,
             break_stale_lock: bool = False) -> dict[str, Any]:
    recipe = load_recipe(recipe_name, root)
    scenes, sources = set_scenes(V4_ROOT, q2.SET, seed)
    run_id = run_id_for(recipe, seed, q2.SET)
    factory = (qwen.session_factory(root, run_id, recipe, port=port, break_stale_lock=break_stale_lock) if recipe.model
               else managed_session_factory(root, run_id, port=port, break_stale_lock=break_stale_lock))
    run = run_generation(root / "runs" / run_id, recipe, seed, scenes, scope=q2.SET, sources=sources,
                         session_factory=factory)
    return {"run_id": run_id, "completion": run["completion"], "resumed": run["resumed"],
            "wall_clock_seconds": run.get("wall_clock_seconds")}


# --- batch identity ---------------------------------------------------------------------------

def target_sequences(scenes, recipe: R.Recipe) -> dict[str, list[list[str]]]:
    return {s.scene_id: [list(b.target_ids) for b in build_batches(s, recipe)] for s in scenes}


def check_batches(seed: int | None = None, *, root: Path = V9_ROOT, arms: tuple[str, ...] = ARMS) -> dict[str, Any]:
    """Offline: target sequences of every dev scene under each arm's recipe; with ``seed``: also the run files."""
    scenes = [s for block_seed in MAIN_SEEDS for s in set_scenes(V4_ROOT, q2.SET, block_seed)[0]]
    recipes = {a: load_recipe(a, root) for a in arms}
    planned = {a: target_sequences(scenes, r) for a, r in recipes.items()}
    base = planned[arms[0]]
    report: dict[str, Any] = {"scenes": len(scenes), "batches": sum(len(v) for v in base.values()),
                              "offline_identical": all(planned[a] == base for a in arms),
                              "offline_differences": {a: sorted(k for k in base if planned[a][k] != base[k]) for a in arms[1:]}}
    visible = {a: Counter(len(b.before_ids) + len(b.target_ids) + len(b.after_ids)
                          for s in scenes for b in build_batches(s, r)) for a, r in recipes.items()}
    report["visible_histogram"] = {a: dict(sorted(v.items())) for a, v in visible.items()}
    if seed is not None:
        runs = {}
        for a in arms:
            path = q2.run_dir(root, a, seed)
            if (path / "run.json").is_file():
                runs[a] = {read_json(p)["scene_id"]: [b["target_ids"] for b in read_json(p)["batches"]]
                           for p in sorted((path / "scenes").glob("*.json"))}
        if runs:
            first = next(iter(runs.values()))
            report["runs"] = {a: {"scenes": len(r), "identical_to_" + next(iter(runs)): all(
                r.get(k) == first[k] for k in first.keys() & r.keys()),
                "matches_plan": all(v == base[k] for k, v in r.items())} for a, r in runs.items()}
    name = f"batches-s{seed}.json" if seed is not None else "batches-offline.json"
    atomic_write_json(root / "checks" / name, report)
    return report


# --- smoke ---------------------------------------------------------------------------------------

def smoke_batches(seed: int = MAIN_SEEDS[0]) -> list[tuple[Any, Any]]:
    """(scene, batch) pairs: per category the first pack with >= 6 targets in the first works of the block."""
    scenes, _ = set_scenes(V4_ROOT, q2.SET, seed)
    base = R.BUILTIN[CONTROL]
    chosen, works = [], set()
    for category, count in SMOKE_PACKS.items():
        for scene in scenes:
            if scene.category != category or scene.work_id in works:
                continue
            batch = next((b for b in build_batches(scene, base) if len(b.target_ids) >= 6), None)
            if batch is not None:
                chosen.append((scene, batch.index))
                works.add(scene.work_id)
            if sum(s.category == category for s, _ in chosen) == count:
                break
    return chosen


def smoke(recipe_name: str, *, root: Path = V9_ROOT, port: int = 8080, break_stale_lock: bool = False,
          seed: int = MAIN_SEEDS[0]) -> dict[str, Any]:
    """GPU: render and generate the smoke packs once on a fresh server; raw replies kept for manual reading."""
    recipe = load_recipe(recipe_name, root)
    if not recipe.model:
        raise ValueError("smoke is for the Qwen arms")
    run_dir = root / "smoke" / recipe_name
    index = len(list((run_dir / "runtime").glob("session-*"))) + 1 if (run_dir / "runtime").is_dir() else 1
    factory = qwen.session_factory(root, f"smoke-{recipe_name}", recipe, port=port, break_stale_lock=break_stale_lock)
    out: dict[str, Any] = {"recipe": recipe.to_json(), "seed": seed, "session": index, "started_at_utc": utc_now(),
                           "packs": []}
    started = time.perf_counter()
    with factory(run_dir, index) as handle:
        out["engine"] = {k: handle.identity.get(k) for k in ("command", "cold_load_seconds", "engine_sha256")}
        cache_state: dict[str, Any] = {"checked": False}
        for scene, batch_index in smoke_batches(seed):
            batch = build_batches(scene, recipe)[batch_index]
            window = batch.to_window(scene)
            ids = list(batch.target_ids)
            record: dict[str, Any] = {"stage": "translation", "batch_index": batch_index}
            row = {"scene_id": scene.scene_id, "category": scene.category, "batch_index": batch_index,
                   "target_ids": ids, "before_ids": list(batch.before_ids), "after_ids": list(batch.after_ids),
                   "messages": qwen.messages(window), "record": record}
            try:
                row["translations"] = qwen.run_step(handle.client, row["messages"], R.translation_grammar(recipe, ids),
                                                    seed, ids, cache_state, record, recipe)
            except StepFailed as exc:
                row["failure"] = {"kind": exc.kind, "error": str(exc)[:2000]}
            for attempt in record.get("attempts", []):
                raw = Path(attempt["exchange"]) / "response.raw" if attempt.get("exchange") else None
                if raw and raw.is_file():
                    reply = json.loads(raw.read_text(encoding="utf-8"))
                    message = (reply.get("choices") or [{}])[0].get("message") or {}
                    attempt["reply_content"] = message.get("content")
                    attempt["reply_reasoning"] = message.get("reasoning_content")
            out["packs"].append(row)
    out["wall_seconds"] = time.perf_counter() - started
    atomic_write_json(root / "smoke" / f"{recipe_name}.json", out)
    return {"packs": len(out["packs"]), "failed": sum("failure" in p for p in out["packs"]),
            "wall_seconds": out["wall_seconds"]}


# --- judging -------------------------------------------------------------------------------------

def judge_run(recipe_name: str, seed: int, *, root: Path = V9_ROOT, parallel: int = 3, log=print) -> dict[str, Any]:
    return E.judge(root, q2.run_dir(root, recipe_name, seed), ["A", "B"], parallel=parallel,
                   reference=E.reference_for(V4_ROOT, q2.SET), log=log)


# --- comparison ----------------------------------------------------------------------------------

def cue_row(errors: list[tuple[str, str]] | None) -> dict[str, float]:
    """One cue in one run; ``None`` = undelivered (accuracy 10, major+ and critical, as v3/v4)."""
    row = dict.fromkeys(METRICS, 0.0)
    if errors is None:
        row.update(accuracy=10.0, major_plus=1.0, critical=1.0)
        return row
    for category, severity in errors:
        points = float(PENALTY[severity])
        row["accuracy" if category in ACCURACY else "fluency"] += points
        if category in row:
            row[category] += points
        row["major_plus"] = max(row["major_plus"], float(severity != "minor"))
        row["critical"] += float(severity == "critical")
    return row


def arm_rows(path: Path, windows: dict) -> dict[str, Any]:
    result = run_cues(path, windows)
    return {"values": {c: cue_row(result["errors"].get(c)) for c in result["values"]},
            "missing": result["missing"], "failed_scenes": result["failed_scenes"]}


def compare(variant: str, seeds: list[int], *, against: str = CONTROL, root: Path = V9_ROOT,
            label: str = "") -> dict[str, Any]:
    all_windows = E.reference_for(V4_ROOT, q2.SET)
    cand: dict[str, dict[str, float]] = {}
    ctrl: dict[str, dict[str, float]] = {}
    scenes: set[str] = set()
    missing: dict[str, int] = {}
    for seed in seeds:
        run_scenes = set(read_json(q2.run_dir(root, variant, seed) / "run.json")["scene_ids"])
        if run_scenes != set(read_json(q2.run_dir(root, against, seed) / "run.json")["scene_ids"]):
            raise ValueError(f"seed {seed}: arms cover different scenes")
        scenes |= run_scenes
        windows = {k: w for k, w in all_windows.items() if w.meta.scene_id in run_scenes}
        for target, name in ((cand, variant), (ctrl, against)):
            rows = arm_rows(q2.run_dir(root, name, seed), windows)
            if rows["missing"]:
                missing[f"{name}__s{seed}"] = len(rows["missing"])
            target.update(rows["values"])
    if missing:
        return {"state": "insufficient", "missing_windows": missing}
    windows = {k: w for k, w in all_windows.items() if w.meta.scene_id in scenes}
    keys = sorted({u["id"] for w in windows.values() for u in w.units} & cand.keys() & ctrl.keys())
    layout = S4.Layout(windows, set(keys))
    report: dict[str, Any] = {"variant": variant, "against": against, "seeds": seeds, "cues": len(keys),
                              "cue_counts": _counts(layout), "full": {}}
    for metric in METRICS:
        diffs = {k: cand[k][metric] - ctrl[k][metric] for k in keys}
        report["full"][metric] = {
            "candidate": S4.aggregate({k: cand[k][metric] for k in keys}, layout),
            "against": S4.aggregate({k: ctrl[k][metric] for k in keys}, layout),
            "delta": S4.aggregate(diffs, layout),
            "bootstrap": S4.bootstrap(diffs, layout, reps=10000 if metric == "accuracy" else 2000)}
    report["by_work"] = _by_work(cand, ctrl, keys, layout)
    report["decision"] = decision(report)
    report["delivery"] = {f"{n}__s{s}": q2._failed(q2.run_dir(root, n, s)) for n in (variant, against) for s in seeds}
    report["cost"] = {f"{n}__s{s}": cost(q2.run_dir(root, n, s)) for n in (variant, against) for s in seeds}
    name = f"v9-{variant}-vs-{against}{('-' + label) if label else ''}.json"
    atomic_write_json(root / "summaries" / name, report)
    return report


def _counts(layout: S4.Layout) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for scene, cues in layout.scene_cues.items():
        out[layout.category_of[layout.work_of[scene]]] += len(cues)
    return dict(out)


def _by_work(cand, ctrl, keys, layout: S4.Layout) -> dict[str, Any]:
    out = {}
    for work, scenes in sorted(layout.works.items()):
        ks = [c for s in scenes for c in layout.scene_cues[s]]
        out[work] = {"category": layout.category_of[work], "cues": len(ks),
                     "accuracy_delta": statistics.fmean(cand[k]["accuracy"] - ctrl[k]["accuracy"] for k in ks)}
    return out


def decision(report: dict[str, Any]) -> dict[str, Any]:
    """§5: per category CI90 of the accuracy Δ; L1 gate (close) and L2 (non-inferior / improved) flags."""
    boot = report["full"]["accuracy"]["bootstrap"]
    out: dict[str, Any] = {}
    for category in (*S4.CATEGORIES, "overall"):
        ci = (boot.get(category) or {}).get("ci90")
        out[category] = {"delta": report["full"]["accuracy"]["delta"][category], "ci90": ci,
                         "significantly_worse": bool(ci and ci[0] > 0), "significantly_better": bool(ci and ci[1] < 0),
                         "noninferior": bool(ci and ci[1] < NONINFERIORITY_MARGIN),
                         "worse_beyond_margin": bool(ci and ci[0] > L1_CLOSE_MARGIN)}
    s, m = out["anime_series"], out["animation_movie"]
    out["l1_close"] = (s["significantly_worse"] and m["significantly_worse"]) or any(
        a["worse_beyond_margin"] and not b["significantly_better"] for a, b in ((s, m), (m, s)))
    out["l2_noninferior_both"] = s["noninferior"] and m["noninferior"]
    out["l2_improved"] = [c for c in S4.CATEGORIES if out[c]["significantly_better"]]
    out["dimensions_better"] = sorted(
        f"{metric}:{c}" for metric, block in report["full"].items() if metric != "accuracy"
        for c in S4.CATEGORIES if ((block["bootstrap"].get(c) or {}).get("ci90") or [0, 0])[1] < 0)
    out["dimensions_worse"] = sorted(
        f"{metric}:{c}" for metric, block in report["full"].items() if metric != "accuracy"
        for c in S4.CATEGORIES if ((block["bootstrap"].get(c) or {}).get("ci90") or [0, 0])[0] > 0)
    return out


def cost(path: Path) -> dict[str, Any]:
    """§4.4 cost: wall clock, load, tokens, generation speed, memory peak, retries and failures."""
    run = read_json(path / "run.json")
    rows = [read_json(p) for p in sorted((path / "scenes").glob("*.json"))]
    attempts = [a for r in rows for q in r["requests"] for a in q.get("attempts", [])]
    timings = [a.get("timings") or {} for a in attempts]
    predicted_n = sum(t.get("predicted_n") or 0 for t in timings)
    predicted_ms = sum(t.get("predicted_ms") or 0 for t in timings)
    prompt_n = sum(t.get("prompt_n") or 0 for t in timings)
    prompt_ms = sum(t.get("prompt_ms") or 0 for t in timings)
    peaks = [read_json(p).get("peak_device_memory_mib") for p in sorted(path.glob("runtime/session-*/engine-final.json"))]
    requests = [q for r in rows for q in r["requests"]]
    return {"wall_clock_seconds": run.get("wall_clock_seconds"), "resumed": run.get("resumed"),
            "sessions": len(run["sessions"]),
            "load_seconds": [(s.get("engine") or {}).get("cold_load_seconds") for s in run["sessions"]],
            "scene_seconds": sum(r.get("elapsed_seconds") or 0 for r in rows),
            "requests": len(requests), "attempts": len(attempts),
            "retried_requests": sum(len(q.get("attempts", [])) > 1 for q in requests),
            "failed_requests": sum(q.get("status") == "failed" for q in requests),
            "failed_scenes": [r["scene_id"] for r in rows if r.get("status") == "failed"],
            "failure_kinds": dict(Counter((r.get("failure") or {}).get("kind") for r in rows if r.get("status") == "failed")),
            "input_tokens": sum(a.get("input_tokens") or 0 for a in attempts),
            "output_tokens": sum(a.get("output_tokens") or 0 for a in attempts),
            "prompt_tokens_evaluated": prompt_n,
            "generation_tok_per_s": predicted_n / predicted_ms * 1000 if predicted_ms else None,
            "prompt_tok_per_s": prompt_n / prompt_ms * 1000 if prompt_ms else None,
            "reasoning_chars": sum(a.get("reasoning_chars") or 0 for a in attempts),
            "prompt_token_mismatches": sum("prompt_token_mismatch" in a for a in attempts),
            "peak_device_memory_mib": peaks}


def judge_spend(root: Path = V9_ROOT) -> dict[str, Any]:
    """Listed price of every judged packet under the root (budget ledger, §5)."""
    from experiments.translation_v3.judge import PACKET_FILE
    per_run: dict[str, float] = defaultdict(float)
    packets: Counter = Counter()
    for path in sorted(root.glob("runs/*/judge/*/p*.json")):
        if PACKET_FILE.fullmatch(path.name):
            meta = read_json(path).get("meta") or {}
            per_run[path.parts[-4]] += meta.get("total_cost_usd") or 0.0
            packets[path.parts[-4]] += 1
    return {"total_usd": sum(per_run.values()), "per_run_usd": dict(per_run), "packets": dict(packets)}


def identical_share(a: str, b: str, seed: int, *, root: Path = V9_ROOT) -> dict[str, Any]:
    ta, _ = load_run_translations(q2.run_dir(root, a, seed))
    tb, _ = load_run_translations(q2.run_dir(root, b, seed))
    keys = ta.keys() & tb.keys()
    return {"cues": len(keys), "identical": sum(ta[k] == tb[k] for k in keys)}


# --- §4.4 secondary endpoints ------------------------------------------------------------------

# A judge error counts as a name error when its evidence mentions a person name / form of address.
NAME_ERROR = re.compile(r"人名|名字|姓名|称呼|译名|名称|专名|角色名|昵称|地名|音译")
LEAK_NGRAM = 3


def _errors(path: Path, windows: dict) -> dict[str, list[dict[str, Any]]]:
    from experiments.translation_v3.judge import load_judgements
    judged, _ = load_judgements(path)
    return {cue_id: row["errors"] for key, cues in judged.items() if key in windows for cue_id, row in cues.items()}


def name_errors(seeds: list[int], *, arms: tuple[str, ...] = ARMS, root: Path = V9_ROOT) -> dict[str, Any]:
    """Per arm and category: judge errors whose evidence matches NAME_ERROR, and the work-level name
    inconsistency of the quality_v5 consistency metric (no replacement) over the covered scenes."""
    from experiments.quality_v5 import consistency
    all_windows = E.reference_for(V4_ROOT, q2.SET)
    report: dict[str, Any] = {"rule": NAME_ERROR.pattern, "arms": {}}
    for arm in arms:
        counts: dict[str, Counter] = defaultdict(Counter)
        works: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        category_of: dict[str, str] = {}
        for seed in seeds:
            path = q2.run_dir(root, arm, seed)
            scenes = set(read_json(path / "run.json")["scene_ids"])
            windows = {k: w for k, w in all_windows.items() if w.meta.scene_id in scenes}
            translations, _ = load_run_translations(path)
            errs = _errors(path, windows)
            for w in windows.values():
                category_of[w.meta.work_id] = w.meta.category
                c = counts[w.meta.category]
                for u in w.units:
                    c["cues"] += 1
                    hits = [e for e in errs.get(u["id"], []) if NAME_ERROR.search(e["evidence_zh"])]
                    c["name_errors"] += len(hits)
                    c["name_error_cues"] += bool(hits)
                    c["name_penalty"] += sum(PENALTY[e["severity"]] for e in hits)
                    for e in hits:
                        c[f"name:{e['category']}"] += 1
                    if u["id"] in translations:
                        works[w.meta.work_id].append((w.meta.window_id, u["ja"], translations[u["id"]]))
        incons = {}
        for work, rows in works.items():
            rows.sort(key=lambda r: r[0])
            incons[work] = consistency.work_summary(consistency.analyze_work([(ja, zh) for _, ja, zh in rows]))
        report["arms"][arm] = {"errors": {k: dict(v) for k, v in counts.items()},
                               "inconsistency_by_work": incons,
                               "inconsistency_by_category": consistency.category_means(incons, category_of)}
    atomic_write_json(root / "summaries" / f"v9-names-s{'-'.join(map(str, seeds))}.json", report)
    return report


def leak_check(seeds: list[int], *, root: Path = V9_ROOT, wide: str = "qwen-wide",
               arms: tuple[str, ...] = ARMS) -> dict[str, Any]:
    """§4.4 leak rule: for each target cue of a wide batch, the Han 3-grams and digit strings of the
    reference Chinese of its read-only neighbours that are absent from the cue's own reference Chinese
    and Japanese; the cue is flagged in an arm when that arm's translation contains one. Every arm is
    checked against the same wide neighbours, so the narrow arms give the coincidence rate."""
    all_windows = E.reference_for(V4_ROOT, q2.SET)
    ref = {u["id"]: u for w in all_windows.values() for u in w.units}
    cat = {u["id"]: w.meta.category for w in all_windows.values() for u in w.units}
    han, digits = re.compile(r"[一-鿿]+"), re.compile(r"\d+")

    def grams(text: str) -> set[str]:
        out = set(digits.findall(text))
        for run in han.findall(text):
            out |= {run[i:i + LEAK_NGRAM] for i in range(len(run) - LEAK_NGRAM + 1)}
        return out
    counts: dict[str, Counter] = {a: Counter() for a in arms}
    hits: list[dict[str, Any]] = []
    for seed in seeds:
        tr = {a: load_run_translations(q2.run_dir(root, a, seed))[0] for a in arms}
        for p in sorted((q2.run_dir(root, wide, seed) / "scenes").glob("*.json")):
            for b in read_json(p)["batches"]:
                neighbours = [k for k in b["before_ids"] + b["after_ids"] if k in ref]
                pool = set().union(*(grams(ref[k]["zh"]) for k in neighbours)) if neighbours else set()
                for t in b["target_ids"]:
                    if t not in ref:
                        continue
                    own = grams(ref[t]["zh"]) | set(digits.findall(ref[t]["ja"]))
                    candidates = pool - own
                    for a in arms:
                        if t not in tr[a]:
                            continue
                        counts[a][f"{cat[t]}:cues"] += 1
                        found = sorted(g for g in candidates if g in tr[a][t])
                        if found:
                            counts[a][f"{cat[t]}:flagged"] += 1
                            if a == wide:
                                hits.append({"seed": seed, "cue": t, "category": cat[t], "found": found,
                                             "also_in": [x for x in arms if x != a and t in tr[x]
                                                         and any(g in tr[x][t] for g in found)]})
    report: dict[str, Any] = {"ngram": LEAK_NGRAM, "arms": {}, "hits": hits,
                              "wide_only_hits": sum(not h["also_in"] for h in hits)}
    for a, c in counts.items():
        row = dict(c)
        for category in S4.CATEGORIES:
            n = c.get(f"{category}:cues")
            row[f"{category}:rate"] = c.get(f"{category}:flagged", 0) / n if n else None
        report["arms"][a] = row
    atomic_write_json(root / "summaries" / f"v9-leak-s{'-'.join(map(str, seeds))}.json", report)
    return report


def reading_list(seed: int, *, variant: str = "qwen-narrow", against: str = CONTROL, per_category: int = 10,
                 root: Path = V9_ROOT) -> Path:
    """§4.4 manual reading: the packs with the largest |Δ accuracy| (summed over the pack's judged cues)."""
    all_windows = E.reference_for(V4_ROOT, q2.SET)
    a_path, b_path = q2.run_dir(root, variant, seed), q2.run_dir(root, against, seed)
    scenes = set(read_json(a_path / "run.json")["scene_ids"])
    windows = {k: w for k, w in all_windows.items() if w.meta.scene_id in scenes}
    ref = {u["id"]: u for w in windows.values() for u in w.units}
    cat = {u["id"]: w.meta.category for w in windows.values() for u in w.units}
    ea, eb = _errors(a_path, windows), _errors(b_path, windows)
    ta, tb = load_run_translations(a_path)[0], load_run_translations(b_path)[0]

    def score(errs: dict, k: str) -> int:
        return sum(PENALTY[e["severity"]] for e in errs.get(k, []) if e["category"] in ACCURACY)
    packs = []
    for p in sorted((a_path / "scenes").glob("*.json")):
        for b in read_json(p)["batches"]:
            ids = [k for k in b["target_ids"] if k in ref]
            if ids:
                packs.append({"batch_id": b["batch_id"], "category": cat[ids[0]],
                              "delta": sum(score(ea, k) - score(eb, k) for k in ids), "cues": [
                                  {"id": k, "ja": ref[k]["ja"], "ref": ref[k]["zh"], variant: ta.get(k), against: tb.get(k),
                                   f"{variant}_errors": ea.get(k, []), f"{against}_errors": eb.get(k, [])} for k in ids]})
    chosen = []
    for category in S4.CATEGORIES:
        rows = sorted((p for p in packs if p["category"] == category), key=lambda p: (-abs(p["delta"]), p["batch_id"]))
        chosen += rows[:per_category]
    out = root / "reading" / f"{variant}-vs-{against}-s{seed}.json"
    atomic_write_json(out, {"seed": seed, "packs": chosen})
    return out
