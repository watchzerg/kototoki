"""Source-metadata-only hierarchical paired statistics for flow exploration v2.

No model calls, reference reads, candidate selection, or decision thresholds.
Seeds are repeated measurements inside windows, never independent bootstrap units.
The estimator weights seeds within windows, windows within works, and works within
categories equally. Scene means and equal-scene sensitivity stay visible.
Representative and source-selected risk windows stay separate.
Bootstrap samples whole work/series clusters, keeping every member's scenes and
seeds together, while preserving the equal-work estimator.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations
import math
import random
from statistics import NormalDist, mean, stdev
from typing import Any

SEEDS = (20261008, 20261009, 20261010)
BASELINE = "C0-official-cached"
SEVERITIES = ("minor", "major", "critical")
ESTIMATOR = "equal_seed_within_window_equal_window_within_work_equal_work_within_category"


def _mean(values: list[float]) -> float | None:
    return mean(values) if values else None


def _name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a nonempty string")
    return value


def _category(value: str) -> str:
    return {"anime": "anime_series", "animation_movie": "movie"}.get(value, value)


def _sources(manifest: dict[str, Any] | list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    windows = manifest.get("windows") if isinstance(manifest, dict) else manifest
    if not isinstance(windows, list) or not windows:
        raise ValueError("source manifest requires a nonempty windows list")
    output = {}
    for raw in windows:
        row = dict(raw)
        wid = _name(row.get("window_id", row.get("id")), "window_id")
        if wid in output:
            raise ValueError(f"duplicate source window: {wid}")
        row["work"] = _name(row.get("work", row.get("work_id")), "work")
        if "work_id" in row:
            _name(row["work_id"], "work_id")
        series_id, series_cluster = row.get("series_id"), row.get("series_cluster")
        if series_id is not None and series_cluster is not None and series_id != series_cluster:
            raise ValueError("contradictory source series_id/series_cluster")
        group = series_id if series_id is not None else series_cluster
        if group is not None:
            row["series_id"] = _name(group, "series_id/series_cluster")
        row["category"] = _category(_name(row.get("category"), "category"))
        if row["category"] not in {"anime_series", "movie"}:
            raise ValueError("category must be anime_series/anime or movie")
        row["stratum"] = _name(row.get("selection_type", row.get("stratum")), "selection_type")
        if row["stratum"] not in {"representative", "risk"}:
            raise ValueError("selection_type must be representative or risk")
        row["split"] = _name(row.get("split"), "split")
        row["scene_id"] = _name(row.get("scene_id"), "scene_id")
        endpoints = (row.get("visible_start_index"), row.get("visible_end_index"))
        if any(value is not None for value in endpoints) and (
            any(type(value) is not int or value < 0 for value in endpoints) or endpoints[0] > endpoints[1]
        ):
            raise ValueError("visible footprint must be an ordered inclusive integer range")
        keys = row.get("source_event_keys", [])
        if not isinstance(keys, list) or any(not isinstance(value, str) or not value for value in keys):
            raise ValueError("source_event_keys must be globally qualified nonempty strings")
        output[wid] = row
    validate_split_isolation(list(output.values()))
    return output


def validate_split_isolation(windows: list[dict[str, Any]]) -> None:
    """Reject screening/confirmation overlap using complete source footprints.

    Index ranges are inclusive and must include all allowed context/preparation/
    memory warm-up. Without footprints this only verifies episode/scene identities;
    it does not certify source isolation or inspect subtitle text.
    """
    for left, right in combinations(windows, 2):
        if (left.get("split") == "confirmation") == (right.get("split") == "confirmation"):
            continue
        left_work = left.get("work", left.get("work_id"))
        right_work = right.get("work", right.get("work_id"))
        if left_work == right_work:
            if left.get("scene_id") and left.get("scene_id") == right.get("scene_id"):
                raise ValueError("screening/confirmation scene leakage")
            episode = left.get("episode_id", left.get("episode"))
            if (_category(left.get("category", "")) == "anime_series" and episode
                and episode == right.get("episode_id", right.get("episode"))):
                raise ValueError("screening/confirmation episode leakage")
        left_keys, right_keys = set(left.get("source_event_keys", [])), set(right.get("source_event_keys", []))
        if left_keys & right_keys:
            raise ValueError("screening/confirmation source event leakage")
        left_source = left.get("source_sha256", left.get("source_srt", left.get("source_id")))
        right_source = right.get("source_sha256", right.get("source_srt", right.get("source_id")))
        if left_source is not None and left_source == right_source:
            fields = ("visible_start_index", "visible_end_index")
            if all(field in left and field in right for field in fields):
                if max(left[fields[0]], right[fields[0]]) <= min(left[fields[1]], right[fields[1]]):
                    raise ValueError("screening/confirmation allowed-source interval leakage")


def _index(rows: list[dict[str, Any]]) -> dict[tuple[str, str, int], dict[str, Any]]:
    output = {}
    for row in rows:
        key = (_name(row.get("candidate_alias"), "candidate_alias"),
               _name(row.get("window_id"), "window_id"), row.get("seed"))
        if type(key[2]) is not int:
            raise ValueError("seed must be an integer")
        if key in output:
            raise ValueError(f"duplicate candidate/window/seed: {key}")
        output[key] = row
    return output


def _score(value: Any, maximum: int, field: str) -> None:
    if value is not None and (type(value) is not int or not 0 <= value <= maximum):
        raise ValueError(f"{field} must be null or integer 0..{maximum}")


def _quantile(values: list[float], probability: float) -> float:
    position = (len(values) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _hierarchy(values: dict[str, float | None], sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for wid, source in sorted(sources.items()):
        grouped[source["work"]][source["scene_id"]].append(wid)
    works = {}
    for work, scenes in sorted(grouped.items()):
        scene_results = {}
        all_values = []
        for scene, ids in sorted(scenes.items()):
            scored = [values[wid] for wid in ids if values[wid] is not None]
            all_values.extend(scored)
            scene_results[scene] = {"mean": _mean(scored), "expected_windows": len(ids),
                                    "scored_windows": len(scored), "window_ids": ids}
        scene_values = [row["mean"] for row in scene_results.values() if row["mean"] is not None]
        for row in scene_results.values():
            row["work_weight"] = row["scored_windows"] / len(all_values) if all_values else None
        works[work] = {"mean": _mean(all_values), "scenes": scene_results,
                       "expected_scenes": len(scenes), "scored_scenes": len(scene_values),
                       "equal_scene_sensitivity_mean": _mean(scene_values)}
    work_values = [row["mean"] for row in works.values() if row["mean"] is not None]
    return {"mean": _mean(work_values), "works": works, "expected_works": len(works),
            "scored_works": len(work_values),
            "omitted_works": [work for work, row in works.items() if row["mean"] is None],
            "equal_scene_sensitivity_mean": _mean([row["equal_scene_sensitivity_mean"] for row in works.values()
                                                   if row["equal_scene_sensitivity_mean"] is not None])}


def _error_key(error: dict[str, Any]) -> tuple[Any, ...]:
    """Explicit roots prevail; fallback retains evidence, not only IDs/type.

    Fallback is conservative: distinct evidence is not merged automatically.
    Shared-root errors spanning different IDs need a judged root_id; no text
    similarity heuristic can establish identical causation.
    """
    if error.get("root_id") is not None:
        return ("root", _name(error["root_id"], "root_id"))
    return ("evidence", tuple(sorted(error.get("ids", []))), error.get("type"),
            error.get("source_evidence"), error.get("candidate_evidence"))


def _global_error_key(error: dict[str, Any], wid: str, source: dict[str, Any]) -> tuple[Any, ...]:
    """Only curator-supported registry roots can join different window IDs.

    A shared root needs root_supported=true, root_scope=work/source, and the
    SHA256 of its curated/judged root registry. These fields assert a shared root
    identity, never a window-local counter. Registry semantics are evaluated by
    the custodian, not inferred from text here. A bare root_id stays window-local.
    Without a root_id, only identical evidence at the same qualified source IDs
    joins; missing source identity keeps the window scope.
    """
    work = source.get("work_id", source["work"])
    root = error.get("root_id")
    registry = error.get("root_registry_sha256")
    supported = (error.get("root_supported") is True and isinstance(registry, str)
                 and len(registry) == 64 and all(char in "0123456789abcdef" for char in registry))
    scope = error.get("root_scope")
    if root is not None:
        if supported and scope == "work":
            return ("supported_work_root", work, registry, root)
        if supported and scope == "source" and source.get("source_sha256"):
            return ("supported_source_root", work, source["source_sha256"], registry, root)
        return ("local_root_id", work, wid, root)
    source_key = source.get("source_sha256") or ("window", wid)
    return ("exact_evidence", work, source_key, *_error_key(error)[1:])


def _errors(rows_by_window: dict[str, list[dict[str, Any]]], sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    counts = Counter()
    global_roots = {}
    per_window, seed_findings = {}, {}
    for wid, rows in sorted(rows_by_window.items()):
        known = [row for row in rows if row["semantic"] is not None or row.get("errors_resolved") is True]
        roots = {}
        indicators = []
        for row in rows:
            accepted = row in known
            findings = {}
            for error in row.get("errors", []) if accepted else []:
                severity = error.get("severity")
                if severity not in SEVERITIES:
                    raise ValueError("unknown error severity")
                key = _error_key(error)
                findings[key] = max(findings.get(key, 0), SEVERITIES.index(severity) + 1)
                global_key = _global_error_key(error, wid, sources[wid])
                global_roots[global_key] = max(global_roots.get(global_key, 0), SEVERITIES.index(severity) + 1)
            for key, severity in findings.items():
                roots[key] = max(roots.get(key, 0), severity)
            serious = any(value >= 2 for value in findings.values()) if accepted else None
            indicators.append(serious)
            seed_findings[f"{wid}/{row['seed']}"] = {
                "known": accepted, "root_counts": dict(Counter(SEVERITIES[value - 1] for value in findings.values())),
                "serious_affected": serious}
        for severity in roots.values():
            counts[SEVERITIES[severity - 1]] += 1
        per_window[wid] = {"known_seeds": len(known), "expected_seeds": len(rows),
            "accepted_root_counts_union_across_seeds": dict(Counter(SEVERITIES[value - 1] for value in roots.values())),
            "serious_seed_rate_lower": sum(value is True for value in indicators) / len(rows),
            "serious_seed_rate_upper": sum(value is not False for value in indicators) / len(rows)}
    lower = _hierarchy({wid: item["serious_seed_rate_lower"] for wid, item in per_window.items()}, sources)
    upper = _hierarchy({wid: item["serious_seed_rate_upper"] for wid, item in per_window.items()}, sources)
    return {"accepted_root_counts_union_across_seeds": {severity: counts[severity] for severity in SEVERITIES},
            "global_root_union": {
                "counts": {severity: sum(value == number for value in global_roots.values())
                           for number, severity in enumerate(SEVERITIES, 1)},
                "supported_shared_root_count": sum(key[0].startswith("supported_") for key in global_roots),
                "exact_evidence_claim_count": sum(key[0] == "exact_evidence" for key in global_roots),
                "unresolved_window_local_root_count": sum(key[0] == "local_root_id" for key in global_roots),
                "scope": "all_windows_and_seeds_in_this_view_source_work_qualified",
                "candidate_specific_new_root_gate_assessed": False},
            "known_seed_records": sum(item["known_seeds"] for item in per_window.values()),
            "expected_seed_records": sum(item["expected_seeds"] for item in per_window.values()),
            "serious_affected_rate_bounds": {"lower": lower["mean"], "upper": upper["mean"]},
            "windows": per_window, "seed_records": seed_findings,
            "deduplication": "explicit_root_id_else_exact_ids_type_source_and_candidate_evidence",
            "root_union_is_diagnostic_not_independent_sample_count": True}


def _candidate(alias: str, index: dict[tuple[str, str, int], dict[str, Any]],
               sources: dict[str, dict[str, Any]], seeds: tuple[int, ...]) -> dict[str, Any]:
    windows, rows_by_window = {}, {}
    for wid in sorted(sources):
        rows = [index[alias, wid, seed] for seed in seeds]
        rows_by_window[wid] = rows
        scores = [row["semantic"] for row in rows]
        naturalness = [row["naturalness"] for row in rows]
        windows[wid] = {"semantic_scored_mean": _mean([value for value in scores if value is not None]),
            "semantic_lower": mean([0 if value is None else value for value in scores]),
            "semantic_upper": mean([4 if value is None else value for value in scores]),
            "semantic_scored_seeds": sum(value is not None for value in scores), "expected_seeds": len(seeds),
            "naturalness_mean": _mean([value for value in naturalness if value is not None]),
            "naturalness_scored_seeds": sum(value is not None for value in naturalness),
            "semantic_by_seed": dict(zip(map(str, seeds), scores))}
    fields = ("semantic_scored_mean", "semantic_lower", "semantic_upper", "naturalness_mean")
    hierarchy = {field: _hierarchy({wid: row[field] for wid, row in windows.items()}, sources) for field in fields}
    return {"windows": windows, **hierarchy,
            "expected_windows": len(sources), "expected_seed_records": len(sources) * len(seeds),
            "semantic_scored_seed_records": sum(row["semantic_scored_seeds"] for row in windows.values()),
            "naturalness_scored_seed_records": sum(row["naturalness_scored_seeds"] for row in windows.values()),
            "status_counts": dict(sorted(Counter(row["status"] for rows in rows_by_window.values() for row in rows).items())),
            "severe_errors": _errors(rows_by_window, sources)}


def _bootstrap(work_values: dict[str, float], series: dict[str, str], iterations: int,
               seed: int, confidence: float) -> dict[str, Any]:
    groups: dict[str, list[str]] = defaultdict(list)
    for work in sorted(work_values):
        groups["series:" + series[work] if work in series else "work:" + work].append(work)
    clusters = list(groups.values())
    if not clusters:
        return {"lower": None, "upper": None, "confidence": confidence, "cluster_count": 0, "members": {}}
    rng = random.Random(seed)
    samples = []
    for _ in range(iterations):
        selected = [clusters[rng.randrange(len(clusters))] for _ in clusters]
        samples.append(mean([work_values[work] for cluster in selected for work in cluster]))
    samples.sort()
    return {"lower": _quantile(samples, (1 - confidence) / 2),
            "upper": _quantile(samples, (1 + confidence) / 2), "confidence": confidence,
            "cluster_count": len(clusters), "members": dict(groups),
            "estimator": "equal_work_mean_after_whole_cluster_resampling"}


def _pair(left: str, right: str, index: dict[tuple[str, str, int], dict[str, Any]],
          sources: dict[str, dict[str, Any]], seeds: tuple[int, ...], series: dict[str, str],
          iterations: int, seed: int, confidence: float, family_size: int) -> dict[str, Any]:
    complete, lower, upper, by_seed = {}, {}, {}, {str(value): {} for value in seeds}
    complete_seeds = 0
    for wid in sorted(sources):
        differences, lows, highs = [], [], []
        for generation_seed in seeds:
            a, b = index[left, wid, generation_seed]["semantic"], index[right, wid, generation_seed]["semantic"]
            diff = None if a is None or b is None else b - a
            by_seed[str(generation_seed)][wid] = diff
            if diff is not None:
                differences.append(diff)
                complete_seeds += 1
            lows.append((0 if b is None else b) - (4 if a is None else a))
            highs.append((4 if b is None else b) - (0 if a is None else a))
        complete[wid] = mean(differences) if len(differences) == len(seeds) else None
        lower[wid], upper[wid] = mean(lows), mean(highs)
    paired = _hierarchy(complete, sources)
    values = {work: row["mean"] for work, row in paired["works"].items() if row["mean"] is not None}
    bounds = {"lower": _hierarchy(lower, sources)["mean"], "upper": _hierarchy(upper, sources)["mean"]}
    work_intervals = _bootstrap(values, {}, iterations, seed, confidence)
    series_intervals = _bootstrap(values, series, iterations, seed, confidence)
    adjusted = 1 - (1 - confidence) / family_size
    return {"left_alias": left, "right_alias": right, "difference_direction": "right_minus_left",
            "semantic_difference": paired["mean"], "hierarchy": paired,
            "expected_windows": len(sources), "complete_paired_windows": sum(value is not None for value in complete.values()),
            "expected_seed_pairs": len(sources) * len(seeds), "complete_seed_pairs": complete_seeds,
            "missing_0_4_difference_bounds": bounds,
            "interval_scope": "complete_all_seeds_paired_window_subset_only",
            "work_cluster_interval": work_intervals, "series_cluster_interval": series_intervals,
            "simultaneous_interval": _bootstrap(values, series, iterations, seed, adjusted),
            "family_size": family_size, "multiplicity_method": "bonferroni_percentile_interval",
            "per_seed": {name: _hierarchy(values_by_window, sources) for name, values_by_window in by_seed.items()},
            "leave_one_work_out": {work: _mean([value for name, value in values.items() if name != work])
                                   for work in sorted(paired["works"])}}


def build_statistics(expected: list[dict[str, Any]], final: list[dict[str, Any]],
                     source_manifest: dict[str, Any] | list[dict[str, Any]], baseline_alias: str = BASELINE,
                     *, seeds: tuple[int, ...] = SEEDS, bootstrap_iterations: int = 10000,
                     seed: int = 20261008, confidence: float = .95, family_size: int = 1,
                     shared_series: dict[str, str] | None = None, combine_screening: bool = False) -> dict[str, Any]:
    """Summarize validated final score ledgers without opening semantic assets.

    Expected must contain every alias/window/seed combination. Absent final rows
    become scheduling nulls; explicitly delivered failures must have semantic 0.
    ``family_size`` is supplied by the frozen policy, never guessed from winners.
    Combined screen-a/b is an explicit additional view, never added to confirmation.
    """
    if not seeds or len(set(seeds)) != len(seeds) or any(type(value) is not int for value in seeds):
        raise ValueError("seeds must be distinct integers")
    if type(bootstrap_iterations) is not int or bootstrap_iterations < 1 or type(seed) is not int:
        raise ValueError("positive bootstrap iterations and integer seed required")
    if not 0 < confidence < 1 or type(family_size) is not int or family_size < 1:
        raise ValueError("confidence must be in (0,1), family_size positive integer")
    sources = _sources(source_manifest)
    wanted, delivered = _index(expected), _index(final)
    aliases = sorted({key[0] for key in wanted})
    if baseline_alias not in aliases:
        raise ValueError("expected must contain baseline alias")
    required = {(alias, wid, value) for alias in aliases for wid in sources for value in seeds}
    if set(wanted) != required or set(delivered) - required:
        raise ValueError("expected/final candidate-window-seed scope mismatch")
    works = {}
    for row in sources.values():
        work = row["work"]
        identity = (row["category"], row.get("series_id"))
        if work in works and works[work] != identity:
            raise ValueError("inconsistent work category/series metadata")
        works[work] = identity
    series = {work: group for work, (_, group) in works.items() if group}
    for work, group in (shared_series or {}).items():
        if work not in works or (work in series and series[work] != group):
            raise ValueError("shared_series unknown work or manifest conflict")
        series[work] = _name(group, "series_id")
    index = {}
    for key, scope in sorted(wanted.items()):
        source = sources[key[1]]
        row = delivered.get(key)
        for record in (scope, row or {}):
            for field in ("work", "work_id", "category", "scene_id", "split", "selection_type", "stratum"):
                if field not in record:
                    continue
                expected_value = (source["stratum"] if field in {"selection_type", "stratum"}
                                  else source.get("work_id", source["work"]) if field == "work_id" else source[field])
                value = _category(record[field]) if field == "category" else record[field]
                if value != expected_value:
                    raise ValueError(f"ledger/source {field} mismatch: {key}")
        merged = {**scope, **(row or {})}
        if row is None:
            merged.update(status="not_run", semantic=None, naturalness=None, errors=[])
        for field, maximum in (("semantic", 4), ("naturalness", 2)):
            if field not in merged:
                raise ValueError(f"final row missing {field}: {key}")
            _score(merged[field], maximum, field)
        status = _name(merged.get("status"), "status")
        if status == "delivery_zero" and (merged["semantic"] != 0 or merged["naturalness"] is not None):
            raise ValueError("delivery_zero requires semantic 0 and null naturalness")
        if status in {"not_run", "judge_failed", "review_failed", "unresolved", "mapping_unjudgeable"} and merged["semantic"] is not None:
            raise ValueError(f"{status} must retain null final semantic")
        errors = merged.get("errors", [])
        if not isinstance(errors, list) or any(not isinstance(error, dict) for error in errors):
            raise ValueError("errors must be a list of objects")
        for error in errors:
            if error.get("severity") not in SEVERITIES:
                raise ValueError("unknown error severity")
            if not isinstance(error.get("ids"), list) or any(not isinstance(uid, str) for uid in error["ids"]):
                raise ValueError("error ids must be a list of strings")
            if "scored_ids" in source and set(error["ids"]) - set(source["scored_ids"]):
                raise ValueError("error IDs outside scored source scope")
            _error_key(error)
        index[key] = merged
    splits: dict[str, set[str]] = defaultdict(set)
    for wid, row in sources.items():
        splits[row["split"]].add(wid)
    if combine_screening:
        screen = splits.get("screen-a", set()) | splits.get("screen-b", set())
        if screen:
            splits["screening-combined"] = screen
    output = {}
    for split, ids in sorted(splits.items()):
        strata = {}
        for stratum in ("representative", "risk"):
            categories = {}
            for category in ("anime_series", "movie"):
                subset = {wid: sources[wid] for wid in sorted(ids)
                          if sources[wid]["stratum"] == stratum and sources[wid]["category"] == category}
                if not subset:
                    continue
                candidates = {alias: _candidate(alias, index, subset, seeds) for alias in aliases}
                pairs = {(baseline_alias, right if left == baseline_alias else left)
                         if baseline_alias in {left, right} else (left, right)
                         for left, right in combinations(aliases, 2)}
                comparisons = [_pair(left, right, index, subset, seeds, series, bootstrap_iterations,
                                     seed, confidence, family_size) for left, right in sorted(pairs)]
                categories[category] = {"candidates": candidates, "pairs": comparisons}
            if categories:
                overall = {alias: {field: mean([categories[category]["candidates"][alias][field]["mean"]
                                                for category in categories])
                                   for field in ("semantic_lower", "semantic_upper")}
                           for alias in aliases} if len(categories) == 2 else None
                strata[stratum] = {"diagnostic_only": stratum == "risk", "categories": categories,
                                   "overall_50_50_missing_bounds": overall}
        all_sources = {wid: sources[wid] for wid in sorted(ids)}
        global_roots = {alias: _errors({wid: [index[alias, wid, generation_seed] for generation_seed in seeds]
                                      for wid in all_sources}, all_sources)["global_root_union"] for alias in aliases}
        output[split] = {"strata": strata, "windows_per_candidate": len(ids),
                         "global_error_root_union": global_roots}
    return {"schema_version": "hy30-flow-v2-statistics-v1", "baseline_alias": baseline_alias,
            "candidate_aliases": aliases, "seeds": list(seeds), "estimator": ESTIMATOR, "splits": output,
            "estimand_scope": "frozen_window_frame_and_allocation_only",
            "population_sampling_weights_applied": False,
            "bootstrap": {"iterations": bootstrap_iterations, "seed": seed, "confidence": confidence,
                          "family_size": family_size, "unit": "work_or_whole_series", "resamples_seeds": False},
            "shared_series": dict(sorted(series.items())),
            "limitations_zh": ["缺分0／4界保留全部预期seed和窗口；它不是置信区间。",
                "配对区间仅覆盖全部seed可评的窗口子集；代表窗与风险窗分开，不自动判定胜者。",
                "seed先在窗口内平均，作品内窗口等权、类别内作品等权；场景等权仅为敏感性分析。三seed不是三倍独立样本。",
                "估计仅对应冻结抽样框与窗口分配；未使用总体抽样权重，不外推全部合格源区间或字幕总体。",
                "少量作品／系列、同模型裁判偏差和缺分限制推断；无显著差异不证明等效。",
                "窗口内按显式root_id或完全相同证据合并。跨窗口仅合并有明确work/source作用域、root_supported及root_registry_sha256的共享根身份；裸root_id保持窗口局部。",
                "无root_id时跨窗仅合并同作品与同源身份下完全相同的IDs和证据；不从文本相似度推断根因，候选特异新增严重风险仍须评估侧判定。"]}


def summarize_blind_calibration(first: list[dict[str, Any]], repeat: list[dict[str, Any]],
                                source_manifest: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize two blinded C0 judgments; do not choose acceptance thresholds.

    Repeated judge rows use candidate_alias/window_id/seed identity. The caller
    verifies their identical output packet and independent blinded invocation
    provenance; this arithmetic cannot certify those facts.
    """
    sources = _sources(source_manifest)
    left, right = _index(first), _index(repeat)
    if not left or set(left) != set(right):
        raise ValueError("calibration passes must cover identical nonempty row identities")
    aliases = {key[0] for key in left}
    if len(aliases) != 1 or {key[1] for key in left} != set(sources):
        raise ValueError("calibration requires one C0 alias and exact source window scope")
    for row in list(left.values()) + list(right.values()):
        _score(row.get("semantic"), 4, "semantic")
        _score(row.get("naturalness"), 2, "naturalness")
    by_window: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for key in sorted(left):
        by_window[key[1]].append((left[key], right[key]))

    def summarize_group(subset: dict[str, dict[str, Any]]) -> dict[str, Any]:
        pairs = [(a, b) for wid in subset for a, b in by_window[wid]]
        score_results = {}
        for metric in ("semantic", "naturalness"):
            window_means = {name: {} for name in ("signed_difference", "mean_absolute_difference", "exact_score_flip_rate")}
            known_count, equal_count = 0, 0
            for wid in subset:
                deltas = [b[metric] - a[metric] for a, b in by_window[wid]
                          if a.get(metric) is not None and b.get(metric) is not None]
                known_count += len(deltas)
                equal_count += sum(value == 0 for value in deltas)
                window_means["signed_difference"][wid] = _mean(deltas)
                window_means["mean_absolute_difference"][wid] = _mean([abs(value) for value in deltas])
                window_means["exact_score_flip_rate"][wid] = _mean([float(value != 0) for value in deltas])
            score_results[metric] = {name: _hierarchy(values, subset) for name, values in window_means.items()}
            score_results[metric].update(expected_judge_pairs=len(pairs), comparable_pairs=known_count,
                                         missing_pairs=len(pairs)-known_count, exact_agreement_pairs=equal_count)
        ceiling = {}
        for phase, position in (("first", 0), ("repeat", 1)):
            values, ceiling_count, scored_count = {}, 0, 0
            for wid in subset:
                scores = [pair[position]["naturalness"] for pair in by_window[wid] if pair[position].get("naturalness") is not None]
                values[wid] = _mean([float(value == 2) for value in scores])
                ceiling_count += sum(value == 2 for value in scores)
                scored_count += len(scores)
            ceiling[phase] = {"naturalness_2_frequency": _hierarchy(values, subset),
                              "naturalness_2_records": ceiling_count, "naturalness_scored_records": scored_count,
                              "expected_records": len(pairs)}

        def errors_known(row: dict[str, Any]) -> bool:
            return row.get("semantic") is not None or row.get("errors_resolved") is True

        presence = {}
        for label, severities in (("major", {"major"}), ("critical", {"critical"}),
                                  ("major_or_critical", {"major", "critical"})):
            metrics = {name: {} for name in ("first_presence_rate", "repeat_presence_rate", "no_to_yes_rate", "yes_to_no_rate")}
            known_count, no_to_yes_count, yes_to_no_count = 0, 0, 0
            for wid in subset:
                known = [(a, b) for a, b in by_window[wid] if errors_known(a) and errors_known(b)]
                indicators = [(any(error.get("severity") in severities for error in a.get("errors", [])),
                               any(error.get("severity") in severities for error in b.get("errors", []))) for a, b in known]
                known_count += len(indicators)
                no_to_yes_count += sum(not a and b for a, b in indicators)
                yes_to_no_count += sum(a and not b for a, b in indicators)
                metrics["first_presence_rate"][wid] = _mean([float(a) for a, b in indicators])
                metrics["repeat_presence_rate"][wid] = _mean([float(b) for a, b in indicators])
                metrics["no_to_yes_rate"][wid] = _mean([float(not a and b) for a, b in indicators])
                metrics["yes_to_no_rate"][wid] = _mean([float(a and not b) for a, b in indicators])
            presence[label] = {name: _hierarchy(values, subset) for name, values in metrics.items()}
            presence[label].update(comparable_pairs=known_count, expected_pairs=len(pairs),
                                   unknown_pairs=len(pairs)-known_count,
                                   no_to_yes_pairs=no_to_yes_count, yes_to_no_pairs=yes_to_no_count)

        claims, known_count, changed_count = {}, 0, 0
        for wid in subset:
            disagreements = []
            for a, b in by_window[wid]:
                if not (errors_known(a) and errors_known(b)):
                    continue
                def serious_claims(row: dict[str, Any]) -> set[tuple[Any, ...]]:
                    return {(_error_key(error), error["severity"]) for error in row.get("errors", [])
                            if error.get("severity") in {"major", "critical"}}
                disagreements.append(float(serious_claims(a) != serious_claims(b)))
            known_count += len(disagreements)
            changed_count += sum(disagreements)
            claims[wid] = _mean(disagreements)
        return {"expected_windows": len(subset), "expected_judge_pairs": len(pairs),
                "scores": score_results, "naturalness_ceiling": ceiling,
                "severe_affected_window_presence": presence,
                "severe_evidence_claim_disagreement": {"rate": _hierarchy(claims, subset),
                    "comparable_pairs": known_count, "changed_pairs": int(changed_count),
                    "unknown_pairs": len(pairs)-known_count}}

    grouped = {}
    for stratum in ("representative", "risk"):
        categories = {}
        for category in ("anime_series", "movie"):
            subset = {wid: source for wid, source in sources.items()
                      if source["stratum"] == stratum and source["category"] == category}
            if subset:
                categories[category] = summarize_group(subset)
        if categories:
            grouped[stratum] = {"diagnostic_only": stratum == "risk", "categories": categories}
    known = [(a, b) for a, b in zip([left[key] for key in sorted(left)], [right[key] for key in sorted(right)])
             if a.get("semantic") is not None and b.get("semantic") is not None]
    return {"schema_version": "hy30-flow-v2-blind-calibration-v1", "candidate_alias": next(iter(aliases)),
            "expected_windows": len(sources), "expected_judge_pairs": len(left),
            "semantic_comparable_pairs": len(known), "semantic_missing_pairs": len(left)-len(known),
            "semantic_exact_agreement_pairs": sum(a["semantic"] == b["semantic"] for a, b in known),
            "strata": grouped, "pooled_score_mean_reported": False,
            "rate_denominator": "known_judge_pairs_then_seed_average_within_window_and_equal_window_work_hierarchy",
            "thresholds_selected": False,
            "limitations_zh": ["盲重复诊断裁判分辨能力，不决定用途上的最小实际收益或严重错误容忍度。",
                "按类别和代表／风险层分开诊断，不用校准样本类别分配比例构造总体均分。",
                "严重错误出现／消失率与证据主张变化分开；未知评分不当作没有严重错误。",
                "需另核验同一译文、全新盲请求与包哈希；本函数只验证身份和数值覆盖。"]}


def _beta_fraction(a: float, b: float, x: float) -> float:
    # Continued fraction for the regularized incomplete beta function.
    tiny = 1e-300
    c, d = 1.0, 1 - (a + b) * x / (a + 1)
    d = 1 / (d if abs(d) > tiny else tiny)
    result = d
    for m in range(1, 201):
        for numerator in (m * (b - m) * x / ((a + 2*m - 1) * (a + 2*m)),
                          -(a + m) * (a + b + m) * x / ((a + 2*m) * (a + 2*m + 1))):
            d = 1 + numerator * d
            d = d if abs(d) > tiny else tiny
            c = 1 + numerator / c
            c = c if abs(c) > tiny else tiny
            d = 1 / d
            delta = d * c
            result *= delta
        if abs(delta - 1) < 3e-14:
            return result
    raise ValueError("beta continued fraction did not converge")


def _regularized_beta(a: float, b: float, x: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    factor = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                      + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1) / (a + b + 2):
        return factor * _beta_fraction(a, b, x) / a
    return 1 - factor * _beta_fraction(b, a, 1 - x) / b


def student_t_critical(confidence: float, degrees_of_freedom: int) -> float:
    """Two-sided t critical value; standard library only."""
    if not 0 < confidence < 1 or degrees_of_freedom < 1:
        raise ValueError("valid confidence and positive degrees_of_freedom required")
    low, high = 0.0, 1.0
    def covered(t: float) -> float:
        return 1 - _regularized_beta(degrees_of_freedom / 2, .5,
                                     degrees_of_freedom / (degrees_of_freedom + t*t))
    while covered(high) < confidence:
        high *= 2
    for _ in range(80):
        middle = (low + high) / 2
        if covered(middle) < confidence:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def summarize_paired_timing(pairs: list[dict[str, Any]], *, planned_confirmation_repetitions: int | None = None,
                            target_half_width_seconds: float | None = None, confidence: float = .95) -> dict[str, Any]:
    """Separate exploratory precision from independent fixed-repetition timing.

    Each measured pair has pair_id, phase (exploratory/confirmation), order (AB/BA),
    baseline_seconds and candidate_seconds. Times cover the entire command and all
    retries; generation replay and reused artifact measurements are not accepted.
    Positive savings mean faster candidate. The t interval assumes independent
    approximately normal pair differences; diagnostics expose order and drift.
    """
    if not 0 < confidence < 1:
        raise ValueError("confidence must be in (0,1)")
    if planned_confirmation_repetitions is not None and (type(planned_confirmation_repetitions) is not int
                                                        or planned_confirmation_repetitions < 2):
        raise ValueError("fixed confirmation repetitions must be at least two")
    if target_half_width_seconds is not None and (not math.isfinite(target_half_width_seconds) or target_half_width_seconds <= 0):
        raise ValueError("positive finite target half-width required")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    ids, measurements = set(), set()
    for row in pairs:
        pid = _name(row.get("pair_id"), "pair_id")
        if pid in ids:
            raise ValueError("pair IDs must be unique across exploratory and confirmation phases")
        ids.add(pid)
        phase = row.get("phase")
        if phase not in {"exploratory", "confirmation"} or row.get("order") not in {"AB", "BA"}:
            raise ValueError("timing requires explicit exploratory/confirmation phase and AB/BA order")
        if row.get("reused") or row.get("prompt_replay"):
            raise ValueError("reused artifacts/prompt replay are not independent full-flow timing")
        completed = (row.get("status", "completed") == "completed"
                     and row.get("baseline_completed", True) and row.get("candidate_completed", True))
        for field in ("baseline_seconds", "candidate_seconds"):
            if not completed and row.get(field) is None:
                continue
            if type(row.get(field)) not in {int, float} or not math.isfinite(row[field]) or row[field] <= 0:
                raise ValueError("timing seconds must be measured positive finite numbers")
        for field in ("source_scope_sha256", "cache_initial_state", "seed"):
            left_field, right_field = "baseline_" + field, "candidate_" + field
            if left_field in row or right_field in row:
                if row.get(left_field) != row.get(right_field):
                    raise ValueError(f"timing pair {field} mismatch")
        measurement = row.get("measurement_id", pid)
        if measurement in measurements:
            raise ValueError("timing measurement identity reused")
        measurements.add(measurement)
        grouped[phase].append({**row, "_completed": completed})
    output = {}
    for phase in ("exploratory", "confirmation"):
        attempts = grouped[phase]
        rows = [row for row in attempts if row["_completed"]]
        values = [row["baseline_seconds"] - row["candidate_seconds"] for row in rows]
        average = _mean(values)
        deviation = stdev(values) if len(values) >= 2 else None
        half = student_t_critical(confidence, len(values) - 1) * deviation / math.sqrt(len(values)) if deviation is not None else None
        orders = Counter(row["order"] for row in rows)
        by_order = {order: _mean([value for row, value in zip(rows, values) if row["order"] == order]) for order in ("AB", "BA")}
        thirds = [values[len(values)*part//3:len(values)*(part+1)//3] for part in range(3)]
        output[phase] = {"pair_count": len(attempts), "completed_pair_count": len(rows),
            "failed_pair_count": len(attempts) - len(rows),
            "failed_pair_ids": [row["pair_id"] for row in attempts if not row["_completed"]],
            "mean_savings_seconds": average,
            "standard_deviation_seconds": deviation, "half_width_seconds": half,
            "interval": {"lower": average - half if half is not None else None,
                         "upper": average + half if half is not None else None, "confidence": confidence},
            "baseline_p50_seconds": _quantile(sorted(row["baseline_seconds"] for row in rows), .5) if rows else None,
            "candidate_p50_seconds": _quantile(sorted(row["candidate_seconds"] for row in rows), .5) if rows else None,
            "baseline_p95_seconds": _quantile(sorted(row["baseline_seconds"] for row in rows), .95) if rows else None,
            "candidate_p95_seconds": _quantile(sorted(row["candidate_seconds"] for row in rows), .95) if rows else None,
            "order_counts": dict(orders), "order_balanced": abs(orders["AB"] - orders["BA"]) <= 1,
            "savings_by_order_seconds": by_order, "early_middle_late_savings_seconds": [_mean(part) for part in thirds],
            "pair_ids": [row["pair_id"] for row in attempts]}
    exploration = output["exploratory"]
    suggested = None
    if target_half_width_seconds is not None and exploration["standard_deviation_seconds"] is not None:
        deviation = exploration["standard_deviation_seconds"]
        suggested = max(2, math.ceil((NormalDist().inv_cdf((1 + confidence) / 2) * deviation / target_half_width_seconds)**2))
        while student_t_critical(confidence, suggested - 1) * deviation / math.sqrt(suggested) > target_half_width_seconds:
            suggested += 1
    confirmed = output["confirmation"]
    if confirmed["pair_count"] and planned_confirmation_repetitions is None:
        raise ValueError("confirmation timing requires pre-frozen fixed repetitions")
    if planned_confirmation_repetitions is not None and confirmed["pair_count"] > planned_confirmation_repetitions:
        raise ValueError("confirmation exceeds pre-frozen repetitions")
    output.update(schema_version="hy30-flow-v2-paired-timing-v1", target_half_width_seconds=target_half_width_seconds,
        suggested_fixed_repetitions_from_exploratory_variance=suggested,
        planned_confirmation_repetitions=planned_confirmation_repetitions,
        confirmation_schedule_complete=(planned_confirmation_repetitions is not None and confirmed["pair_count"] == planned_confirmation_repetitions),
        confirmation_complete=(planned_confirmation_repetitions is not None
                               and confirmed["completed_pair_count"] == planned_confirmation_repetitions),
        interval_method="student_t_on_independent_paired_command_differences",
        stop_rule="exploratory_precision_then_independent_fixed_repetitions",
        limitations_zh=["探索轮次只用于估计测量精度，不与独立固定重复确认合并。",
                        "t区间依赖配对差值近似正态及轮次独立；顺序、漂移与缓存状态仍需实测核验。"])
    return output
