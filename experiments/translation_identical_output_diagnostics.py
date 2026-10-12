"""Offline reviewer-noise diagnostics for exact per-ID translation equality.

Only map serialization is canonicalized: key order is ignored; IDs, Unicode,
whitespace and all text characters are preserved. Judge records are never copied
between aliases. No source/reference text or model execution is needed.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
from itertools import combinations
import json
from pathlib import Path
from typing import Any

from experiments.translation_eval.runner import dump, load_jsonl

STAGES = ("primary", "review", "final")
SEVERITIES = {"minor", "major", "critical"}
EXCLUDED_STATUSES = {"delivery_zero", "mapping_unjudgeable", "not_run", "setup_failed"}
LIMITATIONS_ZH = [
    "完全相同译文仍由各匿名候选独立主评；本诊断只读取已有记录，不复制评分，不改变终评。",
    "原始主评与盲复评分别报告；终评可能继承主评、采用复评一致结果或经过裁决，不能统称为独立盲评。",
    "多个候选及复评使用同一 Sol 模型家族；同模型偏差不会因请求独立而消失，本脚本未核验传输面的独立调用证据。",
    "译文相同或裁判一致均不能证明译文／参考正确；文本相同窗口是条件化诊断子集，不能代表总体误差率或通用误差界。",
    "同一窗口可产生多个相同译文组和多个候选对；这些对互相关联，不能当成独立样本作显著性检验。",
    "缺失输出及不可比交付不假定相同；缺失主评、复评或终分保持未知，不伪造零分。完整预期分母始终保留。",
    "相等判断只忽略 JSON map 键顺序；不做空白、标点、Unicode、简繁或措辞归一化。",
]


def key(row: dict[str, Any]) -> tuple[str, str]:
    return row["candidate_alias"], row["window_id"]


def record_index(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    result = {}
    for row in rows:
        current = key(row)
        if current in result:
            raise ValueError(f"duplicate candidate/window record: {current}")
        result[current] = row
    return result


def canonical_map(translations: dict[str, str]) -> str:
    """Exact map equality with stable key ordering and no text normalization."""
    return json.dumps(translations, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate_judge_records(rows: list[dict[str, Any]], expected: dict[tuple[str, str], dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    indexed = record_index(rows)
    if set(indexed) - set(expected):
        raise ValueError("judge records contain unexpected candidate/window")
    for current, row in indexed.items():
        if "semantic" not in row or "errors" not in row:
            raise ValueError("judge record requires semantic and errors fields")
        semantic = row.get("semantic")
        if semantic is not None and (type(semantic) is not int or not 0 <= semantic <= 4):
            raise ValueError("invalid semantic score")
        scope = expected[current]
        if any(field in row and row[field] != scope[field] for field in ("work", "category", "scored_ids")):
            raise ValueError("judge/expected scope mismatch")
        errors = row.get("errors", [])
        if not isinstance(errors, list):
            raise ValueError("errors must be an array")
        for error in errors:
            if (not isinstance(error, dict) or error.get("severity") not in SEVERITIES
                    or not isinstance(error.get("ids"), list) or not error["ids"]
                    or any(not isinstance(uid, str) for uid in error["ids"])
                    or not set(error["ids"]) <= set(scope["scored_ids"])):
                raise ValueError("invalid error severity/source IDs")
    return indexed


def output_maps(expected: dict[tuple[str, str], dict[str, Any]], candidates: dict[str, list[dict[str, Any]]]) -> tuple[dict[tuple[str, str], str], dict[tuple[str, str], str]]:
    comparable, excluded = {}, {}
    for alias, outputs in sorted(candidates.items()):
        indexed = {}
        for row in outputs:
            window_id = row.get("id", row.get("window_id"))
            if not isinstance(window_id, str) or not window_id:
                raise ValueError("candidate result missing window ID")
            if "id" in row and "window_id" in row and row["id"] != row["window_id"]:
                raise ValueError("candidate result ID disagreement")
            if window_id in indexed:
                raise ValueError("duplicate candidate result window")
            if (alias, window_id) not in expected:
                raise ValueError("candidate result contains unexpected window")
            indexed[window_id] = row
        for current, scope in expected.items():
            if current[0] != alias:
                continue
            row = indexed.get(current[1])
            status = scope.get("structural_status")
            if status in EXCLUDED_STATUSES:
                excluded[current] = status
                continue
            if row is None:
                excluded[current] = "missing_result"
                continue
            translations = row.get("translations")
            if (not isinstance(translations, dict) or "translation_groups" in row
                    or any(not isinstance(uid, str) or not isinstance(text, str) for uid, text in translations.items())):
                excluded[current] = "unsupported_or_invalid_map"
                continue
            if set(translations) - set(scope["scored_ids"]):
                excluded[current] = "extra_translation_ids"
                continue
            # Readability only controls comparability. It never modifies the
            # map used for equality, so trailing spaces remain significant.
            if not any(text.strip() for text in translations.values()):
                excluded[current] = "wholly_absent_or_unreadable_map"
                continue
            comparable[current] = canonical_map(translations)
    return comparable, excluded


def severe_signatures(row: dict[str, Any] | None) -> tuple[tuple[str, ...], set[tuple[Any, ...]]] | None:
    if row is None or row.get("semantic") is None:
        return None
    severe = [error for error in row.get("errors", []) if error["severity"] in {"major", "critical"}]
    return tuple(sorted({error["severity"] for error in severe})), {
        (tuple(sorted(error["ids"])), error.get("type"), error["severity"]) for error in severe}


def compare_records(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    scores = [None if row is None else row.get("semantic") for row in (left, right)]
    known = all(score is not None for score in scores)
    signatures = [severe_signatures(row) for row in (left, right)]
    return {"left_semantic": scores[0], "right_semantic": scores[1],
        "semantic_difference": scores[1] - scores[0] if known else None,
        "missing_semantic_scores": sum(score is None for score in scores),
        "missing_records": sum(row is None for row in (left, right)),
        "severe_classification_disagreement": signatures[0][0] != signatures[1][0] if known else None,
        "serious_presence_disagreement": bool(signatures[0][0]) != bool(signatures[1][0]) if known else None,
        "major_presence_disagreement": ("major" in signatures[0][0]) != ("major" in signatures[1][0]) if known else None,
        "critical_presence_disagreement": ("critical" in signatures[0][0]) != ("critical" in signatures[1][0]) if known else None,
        "severe_claim_scope_disagreement": signatures[0][1] != signatures[1][1] if known else None}


def comparison_summary(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    deltas = [pair["semantic_difference"] for pair in pairs if pair["semantic_difference"] is not None]
    return {"expected_pairs": len(pairs), "known_semantic_pairs": len(deltas),
        "missing_semantic_pairs": len(pairs) - len(deltas),
        "known_pair_coverage": len(deltas) / len(pairs) if pairs else None,
        "missing_score_sides": sum(pair["missing_semantic_scores"] for pair in pairs),
        "missing_record_sides": sum(pair["missing_records"] for pair in pairs),
        "signed_difference_distribution": {str(value): count for value, count in sorted(Counter(deltas).items())},
        "absolute_difference_distribution": {str(value): count for value, count in sorted(Counter(abs(value) for value in deltas).items())},
        "mean_signed_difference": sum(deltas) / len(deltas) if deltas else None,
        "mean_absolute_difference": sum(abs(value) for value in deltas) / len(deltas) if deltas else None,
        "nonzero_difference_pairs": sum(value != 0 for value in deltas),
        **{field + "_pairs": sum(pair[field] is True for pair in pairs) for field in (
            "severe_classification_disagreement", "serious_presence_disagreement", "major_presence_disagreement",
            "critical_presence_disagreement", "severe_claim_scope_disagreement")}}


def final_origin(row: dict[str, Any] | None) -> str:
    if row is None:
        return "missing_final_record"
    status = row.get("status")
    if status in EXCLUDED_STATUSES:
        return "program_delivery_zero" if status == "delivery_zero" else status
    if isinstance(row.get("adjudication"), dict):
        return "adjudicated" if row["adjudication"].get("resolved") is True else "unresolved_adjudication"
    if status in {"judge_failed", "review_failed", "unresolved"}:
        return status
    return "review_agreement" if row.get("reviewed") is True else "primary_only"


def analyze_scope(scope: dict[tuple[str, str], dict[str, Any]], aliases: list[str], maps: dict[tuple[str, str], str],
                  excluded: dict[tuple[str, str], str], stages: dict[str, dict[tuple[str, str], dict[str, Any]]]) -> dict[str, Any]:
    windows = sorted({current[1] for current in scope})
    groups, pairs = [], []
    known_identity_pairs, unknown_identity_pairs, unequal_pairs = 0, 0, 0
    participants: set[tuple[str, str]] = set()
    for window_id in windows:
        matching: dict[str, list[str]] = defaultdict(list)
        for alias in aliases:
            if (alias, window_id) in maps:
                matching[maps[alias, window_id]].append(alias)
        for left, right in combinations(aliases, 2):
            if (left, window_id) not in maps or (right, window_id) not in maps:
                unknown_identity_pairs += 1
            else:
                known_identity_pairs += 1
                unequal_pairs += maps[left, window_id] != maps[right, window_id]
        for canonical, grouped in sorted(matching.items(), key=lambda item: item[1]):
            if len(grouped) < 2:
                continue
            participants.update((alias, window_id) for alias in grouped)
            metadata = scope[grouped[0], window_id]
            groups.append({"window_id": window_id, "aliases": grouped, "work": metadata["work"],
                "category": metadata["category"], "translation_map_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                "pairs": len(grouped) * (len(grouped) - 1) // 2})
            for left, right in combinations(grouped, 2):
                pairs.append({"window_id": window_id, "left_alias": left, "right_alias": right,
                    "stages": {stage: compare_records(records.get((left, window_id)), records.get((right, window_id)))
                               for stage, records in stages.items()},
                    "final_origins": [final_origin(stages["final"].get((alias, window_id))) for alias in (left, right)]})
    stage_summaries = {stage: comparison_summary([pair["stages"][stage] for pair in pairs]) for stage in STAGES}
    for stage, records in stages.items():
        for label, current_keys in (("full_expected_candidate_windows", set(scope)),
                                    ("identical_participant_candidate_windows", participants)):
            available = [records[current] for current in current_keys if current in records]
            scored = sum(record.get("semantic") is not None for record in available)
            stage_summaries[stage][label] = {"expected_windows": len(current_keys),
                "records_available": len(available), "semantic_scored_windows": scored,
                "semantic_null_records": len(available) - scored,
                "missing_records": len(current_keys) - len(available),
                "semantic_coverage": scored / len(current_keys) if current_keys else None}
    stage_summaries["primary"]["interpretation"] = "independent_primary_invocations_under_frozen_contract"
    stage_summaries["review"]["interpretation"] = "fresh_blind_review_invocations_under_frozen_contract"
    stage_summaries["final"]["interpretation"] = "final_pipeline_outcomes_not_independent_blind_judgments"
    possible_pairs = len(windows) * len(aliases) * (len(aliases) - 1) // 2
    return {"expected_windows": len(windows), "expected_candidate_windows": len(scope),
        "expected_window_pairs": possible_pairs, "identity_known_pairs": known_identity_pairs,
        "identity_unknown_pairs": unknown_identity_pairs, "observed_unequal_pairs": unequal_pairs,
        "identical_output_windows": len({group["window_id"] for group in groups}),
        "identical_output_groups": len(groups), "identical_output_pairs": len(pairs),
        "identical_pair_fraction_of_expected": len(pairs) / possible_pairs if possible_pairs else None,
        "identical_participant_candidate_windows": len(participants),
        "candidate_output_coverage": {alias: {"expected_windows": len(windows),
            "comparable_map_windows": sum((alias, wid) in maps for wid in windows),
            "excluded_windows": dict(sorted(Counter(excluded[alias, wid] for wid in windows if (alias, wid) in excluded).items()))}
            for alias in aliases},
        "stage_comparisons": stage_summaries,
        "final_origin_pair_counts": dict(sorted(Counter("|".join(pair["final_origins"]) for pair in pairs).items())),
        "final_origin_candidate_window_counts": dict(sorted(Counter(final_origin(stages["final"].get(current))
                                                                    for current in participants).items())),
        "within_alias_primary_review": comparison_summary([compare_records(stages["primary"].get(current), stages["review"].get(current))
                                                           for current in sorted(participants)]),
        "groups": groups, "pairs": pairs}


def analyze_identical_outputs(expected: list[dict[str, Any]], candidate_results: dict[str, list[dict[str, Any]]], *,
                              primary: list[dict[str, Any]] | None = None, review: list[dict[str, Any]] | None = None,
                              final: list[dict[str, Any]] | None = None, set_name: str = "unspecified") -> dict[str, Any]:
    """Analyze exact equality, retaining expected scopes and null judge outcomes."""
    wanted = record_index(expected)
    aliases = sorted({current[0] for current in wanted})
    if not wanted or len(aliases) != 4 or set(candidate_results) != set(aliases):
        raise ValueError("four anonymous aliases and all expected candidate result inputs are required")
    scopes: dict[str, dict[str, tuple[Any, ...]]] = defaultdict(dict)
    sets: dict[str, dict[tuple[str, str], dict[str, Any]]] = defaultdict(dict)
    for current, row in wanted.items():
        if (not isinstance(row.get("scored_ids"), list) or not row["scored_ids"]
                or any(not isinstance(uid, str) for uid in row["scored_ids"])
                or len(set(row["scored_ids"])) != len(row["scored_ids"])):
            raise ValueError("invalid expected scored IDs")
        name = row.get("set", row.get("split", set_name))
        if not isinstance(name, str) or not name:
            raise ValueError("set/split must be a nonempty string")
        scopes[current[0]][current[1]] = row["work"], row["category"], tuple(row["scored_ids"]), name
        sets[name][current] = row
    if any(scope != scopes[aliases[0]] for scope in scopes.values()):
        raise ValueError("expected candidate scopes differ")
    stages = {name: validate_judge_records(rows or [], wanted) for name, rows in
              (("primary", primary), ("review", review), ("final", final))}
    maps, excluded = output_maps(wanted, candidate_results)
    return {"schema_version": "identical-output-diagnostics-v1", "candidate_aliases": aliases,
        "configuration": {"equality": "exact_full_translations_map_key_order_only", "quality_round": 1,
            "difference_direction": "right_alias_minus_left_alias_sorted_lexically", "set_name_default": set_name,
            "judge_family": "gpt-6.1-sol", "judge_effort": "high", "model_identity_is_contract_not_verified_transport": True,
            "missing_score_side_unit": "candidate_side_of_identical_pair_not_unique_job",
            "semantic_score_range": [0, 4], "grouped_native_text_supported": False},
        "expected_total_candidate_windows": len(wanted),
        "sets": {name: analyze_scope(scope, aliases, maps, excluded, stages) for name, scope in sorted(sets.items())},
        "limitations_zh": LIMITATIONS_ZH}


def report(summary: dict[str, Any]) -> str:
    lines = ["# 相同译文的独立评分差异诊断", "", "比较方向为按匿名 ID 排序后的右侧减左侧；均值无候选优劣方向含义。", ""]
    for name, scope in summary["sets"].items():
        lines += [f"## {name}", "", f"预期 {scope['expected_windows']} 窗口／{scope['expected_candidate_windows']} 候选窗口／"
            f"{scope['expected_window_pairs']} 窗口候选对。观察到相同译文 {scope['identical_output_windows']} 窗口、"
            f"{scope['identical_output_groups']} 组、{scope['identical_output_pairs']} 对；"
            f"译文相等性未知 {scope['identity_unknown_pairs']} 对。", "",
            "| 阶段 | 有分／相同译文对 | 分数不同对 | 平均绝对语义差 | 严重错误类别分歧对 | 严重错误位置／类型分歧对 | 缺分配对侧数 |",
            "| --- | --- | --- | --- | --- | --- | --- |"]
        for stage in STAGES:
            item = scope["stage_comparisons"][stage]
            average = "未知" if item["mean_absolute_difference"] is None else f"{item['mean_absolute_difference']:.4f}"
            label = {"primary": "独立主评", "review": "独立盲复评", "final": "终评流程结果"}[stage]
            lines.append(f"| {label} | {item['known_semantic_pairs']}/{item['expected_pairs']} | {item['nonzero_difference_pairs']} | "
                f"{average} | {item['severe_classification_disagreement_pairs']} | {item['severe_claim_scope_disagreement_pairs']} | "
                f"{item['missing_score_sides']} |")
        lines += ["", "| 阶段 | 有分候选窗口／完整预期 | 空分记录 | 缺失记录 | 相同译文参与者有分／预期 |",
                  "| --- | --- | --- | --- | --- |"]
        for stage in STAGES:
            item = scope["stage_comparisons"][stage]
            full = item["full_expected_candidate_windows"]
            participants = item["identical_participant_candidate_windows"]
            label = {"primary": "独立主评", "review": "独立盲复评", "final": "终评流程结果"}[stage]
            lines.append(f"| {label} | {full['semantic_scored_windows']}/{full['expected_windows']} | "
                f"{full['semantic_null_records']} | {full['missing_records']} | "
                f"{participants['semantic_scored_windows']}/{participants['expected_windows']} |")
        lines += ["", "每组匿名 ID、map SHA256、配对差值分布、缺分覆盖和终评来源分类见 `summary.json`；报告不包含字幕文本。", ""]
    lines += ["## 解释边界", ""] + [f"- {text}" for text in summary["limitations_zh"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="完全相同译文的独立评分差异；只读既有账本。")
    parser.add_argument("--expected", required=True, type=Path)
    parser.add_argument("--candidate", action="append", required=True, help="匿名 ID=首轮 results.jsonl 路径")
    parser.add_argument("--primary", required=True, type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--final", required=True, type=Path)
    parser.add_argument("--set-name", default="unspecified")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    candidates = {}
    for value in args.candidate:
        alias, separator, path = value.partition("=")
        if not separator or not alias or not path or alias in candidates:
            parser.error("--candidate requires unique anonymous ID=path")
        candidates[alias] = Path(path)
    paths = {"expected": args.expected, "primary": args.primary, "final": args.final,
             **{"candidate:" + alias: path for alias, path in candidates.items()}}
    if args.review:
        paths["review"] = args.review
    hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}
    summary = analyze_identical_outputs(load_jsonl(args.expected), {alias: load_jsonl(path) for alias, path in candidates.items()},
        primary=load_jsonl(args.primary), review=load_jsonl(args.review) if args.review else None,
        final=load_jsonl(args.final), set_name=args.set_name)
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != hashes[name] for name, path in paths.items()):
        raise ValueError("inputs changed during diagnostics; use frozen first-round records")
    source = Path(__file__).read_bytes()
    summary["input_provenance"] = {name: {"path": str(path.resolve()), "sha256": hashes[name]} for name, path in paths.items()}
    summary["diagnostics_source_sha256"] = hashlib.sha256(source).hexdigest()
    args.output.mkdir(parents=True, exist_ok=False)
    dump(args.output / "summary.json", summary)
    dump(args.output / "diagnostics-config.json", {"configuration": summary["configuration"],
        "input_provenance": summary["input_provenance"], "diagnostics_source_sha256": summary["diagnostics_source_sha256"]})
    (args.output / "report.md").write_text(report(summary), encoding="utf-8")
    (args.output / "aggregation-executed-identical-output-diagnostics.py").write_bytes(source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
