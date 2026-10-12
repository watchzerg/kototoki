"""Deterministic four-candidate statistics; reads ledgers, never invokes models.

Source manifests contain a ``windows`` list (or are that list), with ``id`` or
``window_id``, optional ``set``/``split``, and source-side diagnostic metadata.
Regression, expanded and dev scopes are always reported separately. Bootstrap
resamples work means within categories, preserving candidate pairing; it never
resamples subtitle IDs as independent observations.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
from pathlib import Path
import random
from typing import Any

from experiments.translation_eval.runner import aggregate, disagree, dump, load_jsonl, read_json

SEED = 20261006
BOOTSTRAP_ITERATIONS = 10000
CONFIDENCE_LEVELS = {"95": .95, "98.33": 1 - .05 / 3, "99.1667": 1 - .05 / 6}
CATEGORIES = ("anime_series", "movie")
SEVERITIES = ("minor", "major", "critical")
SCOPE_FIELDS = ("work", "category", "scored_ids")
SOURCE_LENGTH_BINS = {"0-80": [0, 80], "81-160": [81, 160], "161+": [161, None]}
LIMITATIONS_ZH = [
    "语义缺分界保留全部预期窗口，以 0／4 填补；它不是置信区间，且优先于完整配对子集的区间。",
    "bootstrap 在类别内重采样作品簇并保持配对、作品等权；作品少、共享系列和同模型裁判偏差限制推断。",
    "95% 区间为描述性主表；98.33% 对应每类别三项预指定比较，99.1667% 对应跨两类别六项比较的 Bonferroni 近似。",
    "复评为同模型独立请求，裁决不是独立金标准；没有显著差异不能证明等效，本报告不自动宣布胜者。",
    "集数、位置、长度和源侧风险标签切片仅作诊断，标签可重叠，不能相加或替代概率抽样主集。",
    "历史回归、新增主集和 dev 分别报告；仅使用首轮终评账本，不从重复性能轮次挑选译文。",
]


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def record_key(row: dict[str, Any]) -> tuple[str, str]:
    return row["candidate_alias"], row["window_id"]


def index_records(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    indexed = {}
    for row in rows:
        key = record_key(row)
        if key in indexed:
            raise ValueError(f"duplicate candidate/window: {key}")
        indexed[key] = row
    return indexed


def error_claim(item: dict[str, Any]) -> tuple[Any, ...]:
    return (tuple(sorted(item["ids"])), item["type"], item["severity"],
            item["source_evidence"], item["candidate_evidence"])


def reconcile(expected: list[dict[str, Any]], final: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Retain missing final records as scheduling unknowns, never delivery zeros."""
    wanted, delivered = index_records(expected), index_records(final)
    if not wanted:
        raise ValueError("empty expected ledger")
    if set(delivered) - set(wanted):
        raise ValueError("final contains unexpected candidate/window")
    output = []
    for key, scope in sorted(wanted.items()):
        row = delivered.get(key)
        if row is not None and any(row[name] != scope[name] for name in SCOPE_FIELDS):
            raise ValueError(f"expected/final scope mismatch: {key}")
        merged = dict(scope, **(row or {}))
        if row is None:
            merged.update(status="not_run", semantic=None, naturalness=None,
                          expected_structural_status=scope.get("structural_status"), structural_status="not_run",
                          schedule_reason="final evaluation record absent",
                          reason_zh="终评账本尚无此预期窗口记录；调度未完成，不伪造翻译失败。")
        for name, default in (("errors", []), ("missing_ids", []), ("reviewed", False),
                              ("initial_disagreement", False), ("structural_status", "unknown")):
            merged.setdefault(name, default)
        # Ignore explanation wording and list order when deduplicating a claim.
        claims = {error_claim(item): item for item in merged["errors"]}
        merged["errors"] = [claims[item] for item in sorted(claims)]
        if merged["status"] == "not_run" and (merged["semantic"] is not None or merged["naturalness"] is not None):
            raise ValueError("not_run must retain null final scores")
        output.append(merged)
    # Reuse the authoritative schema/range and candidate-scope checks.
    aggregate(output)
    return output


def quantile(sorted_values: list[float], probability: float) -> float:
    """Linear interpolated empirical quantile (including fractional tails)."""
    position = (len(sorted_values) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (position - lower)


def clustered_intervals(values: list[float], iterations: int, seed: int) -> dict[str, Any]:
    if not values:
        return {label: {"confidence": confidence, "lower": None, "upper": None}
                for label, confidence in CONFIDENCE_LEVELS.items()}
    rng = random.Random(seed)
    size = len(values)
    samples = sorted(sum(values[rng.randrange(size)] for _ in range(size)) / size
                     for _ in range(iterations))
    return {label: {"confidence": confidence,
                   "lower": quantile(samples, (1 - confidence) / 2),
                   "upper": quantile(samples, (1 + confidence) / 2)}
            for label, confidence in CONFIDENCE_LEVELS.items()}


def paired_category(rows: list[dict[str, Any]], baseline: str, candidate: str,
                    iterations: int, seed: int, shared_series: dict[str, str]) -> dict[str, Any]:
    by_key = index_records(rows)
    baseline_rows = [row for row in rows if row["candidate_alias"] == baseline]
    works: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in baseline_rows:
        works[row["work"]].append(row)
    work_results = {}
    for work, windows in sorted(works.items()):
        differences = []
        for left in windows:
            right = by_key[candidate, left["window_id"]]
            if left["semantic"] is not None and right["semantic"] is not None:
                differences.append(right["semantic"] - left["semantic"])
        counts = {"win": sum(value > 0 for value in differences),
                  "tie": differences.count(0), "loss": sum(value < 0 for value in differences)}
        work_results[work] = {"expected_windows": len(windows), "paired_windows": len(differences),
            "paired_coverage": len(differences) / len(windows), **counts,
            "semantic_difference": mean(differences),
            "win_rate": counts["win"] / len(differences) if differences else None,
            "tie_rate": counts["tie"] / len(differences) if differences else None,
            "loss_rate": counts["loss"] / len(differences) if differences else None}
    values = [item["semantic_difference"] for item in work_results.values()
              if item["semantic_difference"] is not None]
    included = [name for name, item in work_results.items() if item["semantic_difference"] is not None]
    leave_one = {name: {"remaining_paired_works": sum(work != name for work in included),
                        "semantic_difference": mean([item["semantic_difference"] for work, item in work_results.items()
                            if work != name and item["semantic_difference"] is not None])}
                 for name in work_results}
    # An explicitly supplied series becomes one equally weighted cluster. Within
    # a series keep the equal-work means; large works do not gain more weight.
    groups: dict[str, list[str]] = defaultdict(list)
    for work in included:
        group = "series:" + shared_series[work] if work in shared_series else "work:" + work
        groups[group].append(work)
    group_means = {group: mean([work_results[name]["semantic_difference"] for name in names])
                   for group, names in sorted(groups.items())}
    paired_count = sum(item["paired_windows"] for item in work_results.values())
    expected_count = len(baseline_rows)
    counts = {name: sum(item[name] for item in work_results.values()) for name in ("win", "tie", "loss")}
    sensitivity = {"enabled": bool(shared_series), "group_members": dict(sorted(groups.items())),
        "cluster_count": len(groups), "semantic_difference": mean(list(group_means.values())),
        "intervals": clustered_intervals(list(group_means.values()), iterations, seed) if shared_series else None,
        "estimator": "equal_series_groups_of_equal_work_means"}
    if not shared_series:
        sensitivity.update(group_members={}, cluster_count=None, semantic_difference=None, estimator=None)
    return {"baseline_alias": baseline, "candidate_alias": candidate,
        "expected_windows": expected_count, "paired_windows": paired_count,
        "paired_coverage": paired_count / expected_count if expected_count else None,
        "paired_works": len(values), "expected_works": len(works),
        "omitted_works": [name for name in work_results if name not in included],
        **counts, "semantic_difference": mean(values),
        "equal_work_rates": {label: mean([item[label + "_rate"] for item in work_results.values()
            if item[label + "_rate"] is not None]) for label in ("win", "tie", "loss")},
        "intervals": clustered_intervals(values, iterations, seed),
        "works": work_results, "leave_one_work_out": leave_one,
        "shared_series_sensitivity": sensitivity,
        "confidence_interval_scope": "complete_paired_subset_only"}


def error_statistics(rows: list[dict[str, Any]], expected_count: int) -> dict[str, Any]:
    known = [row for row in rows if row.get("semantic") is not None]
    claims = {severity: sum(sum(item[2] == severity for item in {error_claim(error) for error in row.get("errors", [])})
                            for row in known) for severity in SEVERITIES}
    windows = {severity: sum(any(error["severity"] == severity for error in row.get("errors", []))
                             for row in known) for severity in SEVERITIES}
    serious = sum(any(error["severity"] in {"major", "critical"} for error in row.get("errors", [])) for row in known)
    return {"expected_windows": expected_count, "known_windows": len(known),
        "unresolved_windows": expected_count - len(known), "counts": claims,
        "affected_windows": windows, "affected_rates_known": {
            severity: windows[severity] / len(known) if known else None for severity in SEVERITIES},
        "serious_affected_windows": serious,
        "serious_rate_known": serious / len(known) if known else None,
        "serious_rate_expected_lower": serious / expected_count if expected_count else None,
        "serious_rate_expected_upper": (serious + expected_count - len(known)) / expected_count if expected_count else None}


def reviewer_variation(rows: list[dict[str, Any]], primary: dict[tuple[str, str], dict[str, Any]],
                       review: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    before = [primary[record_key(row)] for row in rows if record_key(row) in primary]
    comparable, deltas = [], defaultdict(list)
    changed, null_transitions, disagreements = 0, 0, 0
    reviewed_available = 0
    for row in rows:
        key = record_key(row)
        first = primary.get(key) or row.get("primary") or row.get("provisional_primary")
        second = review.get(key) or row.get("review")
        if first is not None:
            changed += any(first[field] != row[field] for field in ("semantic", "naturalness"))
            null_transitions += (first["semantic"] is None) != (row["semantic"] is None)
            if first["semantic"] is not None and row["semantic"] is not None:
                value = row["semantic"] - first["semantic"]
                comparable.append(value)
                deltas[row["work"]].append(value)
        if first is not None and second is not None:
            reviewed_available += 1
            disagreements += disagree(first, second)
    return {"expected_windows": len(rows), "primary_records_available": len(before),
        "reviewed_windows": sum(row["reviewed"] for row in rows),
        "primary_review_comparable_windows": reviewed_available,
        "primary_review_disagreement_windows": disagreements,
        "ledger_initial_disagreement_windows": sum(row["initial_disagreement"] for row in rows),
        "primary_final_score_changed_windows": changed, "semantic_null_transition_windows": null_transitions,
        "primary_final_semantic_comparable_windows": len(comparable),
        "primary_final_mean_absolute_semantic_change": mean([abs(value) for value in comparable]),
        "primary_final_equal_work_semantic_change": mean([mean(values) for values in deltas.values()]),
        "primary_alleged_errors": error_statistics(before, len(rows)),
        "final_accepted_errors": error_statistics(rows, len(rows)),
        "primary_embedded_only_windows": sum(record_key(row) not in primary and
            bool(row.get("primary") or row.get("provisional_primary")) for row in rows)}


def source_windows(manifest: Any) -> list[dict[str, Any]]:
    windows = manifest.get("windows") if isinstance(manifest, dict) else manifest
    if not isinstance(windows, list) or any(not isinstance(row, dict) for row in windows):
        raise ValueError("source manifest requires a windows list")
    return windows


def diagnostic_strata(rows: list[dict[str, Any]], sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    work_by_window = {row["window_id"]: row["work"] for row in rows}
    for window_id, source in sorted(sources.items()):
        nested = source.get("source_metadata", {})
        if not isinstance(nested, dict):
            raise ValueError("source_metadata must be an object")
        metadata = {**source, **nested}
        metadata.setdefault("episode", metadata.get("episode_id"))
        metadata.setdefault("position_stratum", metadata.get("position_decile"))
        length = metadata.get("source_length_chars")
        if length is not None:
            if type(length) is not int or length < 0:
                raise ValueError("source_length_chars must be a nonnegative integer")
            metadata.setdefault("length_stratum", "0-80" if length <= 80 else "81-160" if length <= 160 else "161+")
        for field in ("episode", "position_stratum", "length_stratum"):
            value = metadata.get(field)
            label = "unknown" if value is None else str(value)
            if field == "episode":
                label = work_by_window[window_id] + "/" + label
            grouped[field][label].add(window_id)
        tags = metadata.get("risk_tags", metadata.get("diagnostic_tags", []))
        if not isinstance(tags, list) or any(not isinstance(tag, str) or not tag for tag in tags):
            raise ValueError("source risk_tags must be nonempty strings")
        empty_label = "untagged" if "risk_tags" in metadata or "diagnostic_tags" in metadata else "unknown"
        for tag in set(tags) or {empty_label}:
            grouped["risk_tags"][tag].add(window_id)
    return {dimension: {label: {"diagnostic_only": True, "windows_per_candidate": len(ids),
        "quality": aggregate([row for row in rows if row["window_id"] in ids])}
        for label, ids in sorted(groups.items())} for dimension, groups in sorted(grouped.items())}


def build_statistics(expected: list[dict[str, Any]], final: list[dict[str, Any]], source_manifest: Any,
                     baseline_alias: str, *, primary: list[dict[str, Any]] | None = None,
                     review: list[dict[str, Any]] | None = None, shared_series: dict[str, str] | None = None,
                     bootstrap_iterations: int = BOOTSTRAP_ITERATIONS, seed: int = SEED,
                     set_name: str = "expanded") -> dict[str, Any]:
    """Build independent per-set reports from first-round validated eval records."""
    if type(bootstrap_iterations) is not int or bootstrap_iterations < 1 or type(seed) is not int:
        raise ValueError("bootstrap iterations must be positive and seed must be integer")
    rows = reconcile(expected, final)
    delivered = index_records(final)
    aliases = sorted({row["candidate_alias"] for row in rows})
    if len(aliases) != 4 or baseline_alias not in aliases:
        raise ValueError("four aliases including the baseline are required")
    scope = {row["window_id"]: row for row in rows if row["candidate_alias"] == baseline_alias}
    sources = {}
    for source in source_windows(source_manifest):
        window_id = source.get("window_id", source.get("id"))
        if not isinstance(window_id, str) or not window_id or window_id in sources:
            raise ValueError("missing or duplicate source window ID")
        sources[window_id] = source
    if set(sources) != set(scope):
        raise ValueError("source manifest/expected window scope mismatch")
    for window_id, source in sources.items():
        for field in SCOPE_FIELDS:
            value = source.get(field)
            if field == "category" and value == "animation_movie":
                value = "movie"
            if value is not None and value != scope[window_id][field]:
                raise ValueError(f"source manifest {field} mismatch: {window_id}")
    mapping = shared_series or {}
    if not isinstance(mapping, dict) or any(not isinstance(group, str) or not group for group in mapping.values()):
        raise ValueError("shared_series requires explicit work-to-series string mapping")
    if set(mapping) - {row["work"] for row in rows}:
        raise ValueError("shared_series names unknown works")
    first, second = index_records(primary or []), index_records(review or [])
    wanted = index_records(expected)
    if set(first) - set(wanted) or set(second) - set(wanted):
        raise ValueError("reviewer records contain unexpected candidate/window")
    sets: dict[str, set[str]] = defaultdict(set)
    for window_id, source in sorted(sources.items()):
        name = source.get("set", source.get("split", set_name))
        if not isinstance(name, str) or not name:
            raise ValueError("source set/split must be a nonempty string")
        sets[name].add(window_id)
    output = {}
    for name, ids in sorted(sets.items()):
        selected = [row for row in rows if row["window_id"] in ids]
        selected_index = index_records(selected)
        quality = aggregate(selected)
        common = {window_id for window_id in ids if all(
            selected_index[alias, window_id]["semantic"] is not None for alias in aliases)}
        categories = {}
        for category in CATEGORIES:
            current = [row for row in selected if row["category"] == category]
            if not current:
                continue
            comparisons = {}
            for candidate in aliases:
                if candidate == baseline_alias:
                    continue
                comparison = paired_category(current, baseline_alias, candidate, bootstrap_iterations, seed, mapping)
                candidate_quality = quality["candidates"][candidate]["categories"][category]
                baseline_quality = quality["candidates"][baseline_alias]["categories"][category]
                comparison["complete_denominator_difference_bounds"] = {
                    "lower": candidate_quality["semantic_lower"] - baseline_quality["semantic_upper"],
                    "upper": candidate_quality["semantic_upper"] - baseline_quality["semantic_lower"]}
                comparisons[candidate] = comparison
            categories[category] = {"paired_vs_baseline": comparisons,
                "reviewer_variation": {alias: reviewer_variation([row for row in current if row["candidate_alias"] == alias], first, second)
                                       for alias in aliases},
                "four_candidate_common_coverage": {
                    "windows": sum(row["window_id"] in common for row in current if row["candidate_alias"] == baseline_alias),
                    "expected_windows": sum(row["candidate_alias"] == baseline_alias for row in current),
                    "errors": {alias: error_statistics([row for row in current if row["candidate_alias"] == alias
                        and row["window_id"] in common], sum(row["window_id"] in common for row in current
                            if row["candidate_alias"] == baseline_alias)) for alias in aliases}},
                "per_work_errors": {alias: {work: error_statistics([row for row in current
                    if row["candidate_alias"] == alias and row["work"] == work],
                    sum(row["candidate_alias"] == alias and row["work"] == work for row in current))
                    for work in sorted({row["work"] for row in current})} for alias in aliases}}
        output[name] = {"quality": quality, "categories": categories,
            "windows_per_candidate": len(ids), "scheduled_missing_final_records": sum(
                record_key(row) not in delivered for row in selected),
            "four_candidate_common_coverage": {"windows": len(common), "expected_windows": len(ids),
                "coverage": len(common) / len(ids), "window_ids": sorted(common),
                "errors": {alias: error_statistics([row for row in selected if row["candidate_alias"] == alias
                                                    and row["window_id"] in common], len(common)) for alias in aliases}},
            "source_diagnostics": diagnostic_strata(selected, {wid: sources[wid] for wid in sorted(ids)})}
    return {"schema_version": "hy30-four-stats-v1", "baseline_alias": baseline_alias,
        "candidate_aliases": aliases, "quality_round": 1, "sets": output,
        "bootstrap": {"iterations": bootstrap_iterations, "seed": seed, "unit": "work",
            "stratification": "within_category", "estimator": "equal_work_mean_of_complete_paired_window_differences",
            "confidence_levels": CONFIDENCE_LEVELS},
        "source_diagnostic_config": {"length_unit": "source_japanese_characters", "length_bins": SOURCE_LENGTH_BINS,
            "explicit_length_stratum_precedence": True, "risk_tags_may_overlap": True},
        "shared_series_map": dict(sorted(mapping.items())), "limitations_zh": LIMITATIONS_ZH}


def format_number(value: float | None) -> str:
    return "未知" if value is None else f"{value:.4f}"


def report(summary: dict[str, Any]) -> str:
    lines = ["# 四候选首轮翻译统计", "", f"基线匿名 ID：`{summary['baseline_alias']}`。首轮质量，分轨报告。",
        f"作品簇 bootstrap：{summary['bootstrap']['iterations']} 次；seed `{summary['bootstrap']['seed']}`。", ""]
    for name, results in summary["sets"].items():
        lines += [f"## {name}", "", f"每候选预期 {results['windows_per_candidate']} 窗口；"
            f"四者共同语义覆盖 {results['four_candidate_common_coverage']['windows']}/{results['windows_per_candidate']}。",
            "", "| 候选 | 作品 | 类别 | 语义覆盖 | 语义缺分界 | 自然度／覆盖 |", "| --- | --- | --- | --- | --- | --- |"]
        for alias, quality in results["quality"]["candidates"].items():
            for work, item in quality["works"].items():
                lines.append(f"| {alias} | {work} | {item['category']} | {item['semantic_scored_windows']}/{item['expected_windows']} | "
                    f"[{item['semantic_lower']:.4f}, {item['semantic_upper']:.4f}] | {format_number(item['naturalness_mean'])}／"
                    f"{item['naturalness_scored_windows']}/{item['expected_windows']} |")
            for category, item in quality["categories"].items():
                lines.append(f"| {alias} | **类别等权** | {category} | {item['semantic_scored_windows']}/{item['expected_windows']} | "
                    f"[{item['semantic_lower']:.4f}, {item['semantic_upper']:.4f}] | {format_number(item['naturalness_mean'])}／"
                    f"{item['naturalness_scored_windows']}/{item['expected_windows']} |")
        for category, item in results["categories"].items():
            lines += ["", f"### {category} 配对比较", "",
                "| 新候选 | 完整配对／预期 | 胜／平／负 | 作品等权差 | 95% | 98.33% | 99.1667% | 完整分母差值界 |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |"]
            sensitivity_notes = []
            for alias, pair in item["paired_vs_baseline"].items():
                intervals = [f"[{format_number(pair['intervals'][level]['lower'])}, {format_number(pair['intervals'][level]['upper'])}]"
                             for level in CONFIDENCE_LEVELS]
                bounds = pair["complete_denominator_difference_bounds"]
                lines.append(f"| {alias} | {pair['paired_windows']}/{pair['expected_windows']} | "
                    f"{pair['win']}/{pair['tie']}/{pair['loss']} | {format_number(pair['semantic_difference'])} | "
                    + " | ".join(intervals) + f" | [{bounds['lower']:.4f}, {bounds['upper']:.4f}] |")
                leave_one = [row["semantic_difference"] for row in pair["leave_one_work_out"].values()
                             if row["semantic_difference"] is not None]
                sensitivity = pair["shared_series_sensitivity"]
                sensitivity_notes.append(f"{category}／{alias}：逐个移除作品差值范围 "
                    f"{format_number(min(leave_one) if leave_one else None)}～{format_number(max(leave_one) if leave_one else None)}；"
                    f"共享系列敏感性{'已提供' if sensitivity['enabled'] else '未提供显式映射'}，"
                    f"组等权差 {format_number(sensitivity['semantic_difference'])}。")
            lines += [""] + [note + "\n" for note in sensitivity_notes]
            lines += ["", f"### {category} 复评与严重错误", "", "| 候选 | 主评／预期 | 复评 | 主复评分歧／可比较 | 终评改分 | 终评 major／critical | 涉及严重错误／已知 | 未决 |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |"]
            for alias, variation in item["reviewer_variation"].items():
                errors = variation["final_accepted_errors"]
                lines.append(f"| {alias} | {variation['primary_records_available']}/{variation['expected_windows']} | "
                    f"{variation['reviewed_windows']} | {variation['primary_review_disagreement_windows']}/"
                    f"{variation['primary_review_comparable_windows']} | {variation['primary_final_score_changed_windows']} | "
                    f"{errors['counts']['major']}/{errors['counts']['critical']} | {errors['serious_affected_windows']}/"
                    f"{errors['known_windows']} | {errors['unresolved_windows']} |")
        lines += ["", "完整的逐作品配对、初评错误、终评错误、共同覆盖、移除作品／共享系列敏感性和源侧诊断见同目录 `summary.json`。", ""]
    lines += ["## 解释边界", ""] + [f"- {item}" for item in summary["limitations_zh"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="四候选首轮账本的确定性离线统计；不调用模型。")
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--final", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--baseline-alias", required=True)
    parser.add_argument("--primary", type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--shared-series", type=Path, help="显式作品到共享系列的 JSON 映射")
    parser.add_argument("--set-name", default="expanded")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    files = {name: path for name, path in vars(args).items() if isinstance(path, Path) and name != "output"}
    original_hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()}
    manifest = load_jsonl(args.source_manifest) if args.source_manifest.suffix == ".jsonl" else read_json(args.source_manifest)
    summary = build_statistics(load_jsonl(args.expected), load_jsonl(args.final), manifest, args.baseline_alias,
        primary=load_jsonl(args.primary) if args.primary else None,
        review=load_jsonl(args.review) if args.review else None,
        shared_series=read_json(args.shared_series) if args.shared_series else None, set_name=args.set_name)
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != original_hashes[name] for name, path in files.items()):
        raise ValueError("statistics inputs changed during aggregation; use frozen ledgers")
    summary["input_provenance"] = {name: {"path": str(path.resolve()),
        "sha256": original_hashes[name]} for name, path in files.items()}
    source_bytes = Path(__file__).read_bytes()
    summary["statistics_source_sha256"] = hashlib.sha256(source_bytes).hexdigest()
    args.output.mkdir(parents=True, exist_ok=False)
    dump(args.output / "summary.json", summary)
    (args.output / "report.md").write_text(report(summary), encoding="utf-8")
    (args.output / "aggregation-executed-translation-four-stats.py").write_bytes(source_bytes)
    dump(args.output / "statistics-config.json", {"bootstrap": summary["bootstrap"],
        "baseline_alias": args.baseline_alias, "set_name": args.set_name,
        "shared_series_map": summary["shared_series_map"], "input_provenance": summary["input_provenance"],
        "statistics_source_sha256": summary["statistics_source_sha256"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
