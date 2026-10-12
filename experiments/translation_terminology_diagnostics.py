"""Bounded, candidate-blind source-term scope and literal rendering diagnostics.

This is an evaluator sidecar, never a translator glossary. Source selection and
target alias detectors are declared before candidate access. Unclassified or
varying surfaces do not become semantic errors, omissions or untranslated names.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from experiments.translation_eval.runner import dump, load_jsonl, read_json

MAX_TERMS = 64
LIMITATIONS = [
    "封闭目录只覆盖预声明且源侧重复出现的词，不是全部术语或实体的完整评估。",
    "同族合法别名变化允许；跨族变化只是潜在不一致线索，不能据此自动判语义错误。",
    "未命中、多族命中、无译文均单列；未命中不证明漏译、未翻译或陌生专名错误。",
    "日文源别名、作品和上下文选择规则分别分组；上下文仍可能使多种译法合理。",
    "字面匹配不能证明目标短语对应正确实体；参考词汇也可出错，不是人工金标准。",
    "目录及源范围应在正式译文之前冻结并纳入正式 freeze；时间戳本身不是先后顺序证明。",
    "诊断目录和参考词汇不得进入翻译器、反思、修补或产品术语准备；本报告不更改评分。",
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_catalog(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    if catalog.get("candidate_outputs_used") is not False or catalog.get("translator_use_allowed") is not False:
        raise ValueError("catalog must be candidate-blind and forbidden for translator use")
    terms = catalog.get("terms")
    if not isinstance(terms, list) or not 1 <= len(terms) <= MAX_TERMS:
        raise ValueError("closed catalog requires 1..64 declared terms")
    seen = set()
    for term in terms:
        identity = term.get("term_id")
        forms, groups = term.get("source_forms"), term.get("target_alias_groups")
        if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", identity) or identity in seen:
            raise ValueError("term IDs must be unique safe identifiers")
        seen.add(identity)
        if (not isinstance(forms, list) or not 1 <= len(forms) <= 8 or len(set(forms)) != len(forms)
                or any(not isinstance(form, str) or not form for form in forms)):
            raise ValueError("term requires 1..8 unique literal source forms")
        if not isinstance(groups, dict) or not 1 <= len(groups) <= 4:
            raise ValueError("term requires 1..4 target rendering families")
        aliases = []
        for label, values in groups.items():
            if (not re.fullmatch(r"[A-Za-z0-9_-]+", label) or not isinstance(values, list) or not 1 <= len(values) <= 16
                    or any(not isinstance(value, str) or not value for value in values)):
                raise ValueError("invalid target alias group")
            aliases.extend(values)
        if len(aliases) != len(set(aliases)):
            raise ValueError("target aliases cannot belong to multiple families")
        for field in ("works", "required_context_any", "excluded_context_any"):
            values = term.get(field, [])
            if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
                raise ValueError("invalid source context/works selector")
    return sorted(terms, key=lambda term: term["term_id"])


def prepare_manifest(inputs: list[dict[str, Any]], sources: Any, catalog: dict[str, Any], set_name: str) -> dict[str, Any]:
    """Select eligible occurrences from original Japanese scored units only."""
    terms = validate_catalog(catalog)
    metadata = sources.get("windows") if isinstance(sources, dict) else sources
    if not isinstance(metadata, list):
        raise ValueError("source manifest requires windows")
    indexed = {}
    for row in metadata:
        wid = row.get("window_id", row.get("id"))
        if not isinstance(wid, str) or wid in indexed:
            raise ValueError("invalid or duplicate source window ID")
        indexed[wid] = row
    occurrences, window_scope, seen = [], {}, set()
    for row in inputs:
        legacy_fields = {"id", "context", "translate_ids"}
        formal_fields = legacy_fields | {"source_language", "target_language"}
        if set(row) not in (legacy_fields, formal_fields):
            raise ValueError("term preparation accepts source-only model input fields")
        if set(row) == formal_fields and (row["source_language"] != "ja" or row["target_language"] != "zh-Hans"):
            raise ValueError("formal source input requires ja to zh-Hans language identity")
        wid = row["id"]
        if wid in seen or wid not in indexed:
            raise ValueError("input/source scope mismatch or duplicate")
        seen.add(wid)
        units = row["context"]
        if any(set(unit) != {"id", "text"} or not isinstance(unit["text"], str) for unit in units):
            raise ValueError("source context must contain only IDs and Japanese text")
        ids = [unit["id"] for unit in units]
        if len(set(ids)) != len(ids) or not row["translate_ids"] or not set(row["translate_ids"]) <= set(ids):
            raise ValueError("invalid scored source IDs")
        source = indexed[wid]
        if "scored_ids" in source and source["scored_ids"] != row["translate_ids"]:
            raise ValueError("input/source scored ID scope mismatch")
        work = source["work"]
        window_scope[wid] = {"work": work, "category": source["category"], "scored_ids": row["translate_ids"]}
        context = "\n".join(unit["text"] for unit in units)
        for term in terms:
            if term.get("works") and work not in term["works"]:
                continue
            if term.get("required_context_any") and not any(value in context for value in term["required_context_any"]):
                continue
            if any(value in context for value in term.get("excluded_context_any", [])):
                continue
            for unit in units:
                if unit["id"] not in row["translate_ids"]:
                    continue
                matched = [number for number, form in enumerate(term["source_forms"]) if form in unit["text"]]
                if matched:
                    occurrences.append({"window_id": wid, "subtitle_id": unit["id"], "work": work,
                        "term_id": term["term_id"], "source_form_indices": matched})
    if seen != set(indexed):
        raise ValueError("input/source manifest window scope mismatch")
    counts = {term["term_id"]: len({item["window_id"] for item in occurrences if item["term_id"] == term["term_id"]}) for term in terms}
    eligible = {term for term, count in counts.items() if count >= 2}
    return {"schema_version": "source-term-scope-v1", "state": "candidate_blind_source_scope_prepared",
        "prepared_at_utc": datetime.now(timezone.utc).isoformat(), "set": set_name,
        "translator_use_allowed": False, "candidate_outputs_used": False,
        "expected_windows": len(inputs), "expected_scored_ids": sum(len(row["translate_ids"]) for row in inputs),
        "windows": window_scope, "terms": [term for term in terms if term["term_id"] in eligible],
        "eligible_occurrences": [item for item in occurrences if item["term_id"] in eligible],
        "source_selection": {"minimum_distinct_windows": 2, "max_declared_terms": MAX_TERMS,
            "declared_terms": len(terms), "eligible_terms": len(eligible), "source_window_counts": counts,
            "excluded_terms_below_two_windows": sorted(set(counts) - eligible)}, "limitations_zh": LIMITATIONS}


def analyze(manifest: dict[str, Any], candidates: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    if manifest.get("state") != "candidate_blind_source_scope_prepared" or manifest.get("translator_use_allowed") is not False:
        raise ValueError("a source-only prepared manifest is required")
    if len(candidates) != 4:
        raise ValueError("four anonymous candidate inputs required")
    terms = {term["term_id"]: term for term in manifest["terms"]}
    by_candidate = {}
    for alias, rows in sorted(candidates.items()):
        results = {}
        for row in rows:
            wid = row["id"]
            if wid in results or wid not in manifest["windows"]:
                raise ValueError("duplicate or unexpected candidate window")
            results[wid] = row
        groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
        counts = Counter()
        for occurrence in manifest["eligible_occurrences"]:
            term = terms[occurrence["term_id"]]
            row = results.get(occurrence["window_id"], {})
            translated = row.get("translations", {})
            text = translated.get(occurrence["subtitle_id"]) if isinstance(translated, dict) else None
            hits = {label: [number for number, value in enumerate(values) if isinstance(text, str) and value in text]
                    for label, values in term["target_alias_groups"].items()}
            hits = {label: values for label, values in hits.items() if values}
            status = "missing_translation" if not isinstance(text, str) or not text.strip() else "unclassified" if not hits else "ambiguous_multiple_families" if len(hits) > 1 else "single_declared_family"
            counts[status] += 1
            group_key = occurrence["term_id"], occurrence["work"], tuple(occurrence["source_form_indices"])
            groups[group_key].append({**occurrence, "status": status, "matched_family": next(iter(hits)) if len(hits) == 1 else None,
                                     "matched_alias_indices": hits})
        diagnostics = []
        for current, observations in sorted(groups.items()):
            known = [row for row in observations if row["status"] == "single_declared_family"]
            families = sorted({row["matched_family"] for row in known})
            family_windows = {family: sorted({row["window_id"] for row in known if row["matched_family"] == family}) for family in families}
            known_windows = {row["window_id"] for row in known}
            diagnostics.append({"term_id": current[0], "work": current[1], "source_form_indices": list(current[2]),
                "expected_occurrences": len(observations), "expected_windows": len({row["window_id"] for row in observations}),
                "single_family_known_occurrences": len(known), "single_family_known_windows": len(known_windows),
                "status_counts": dict(sorted(Counter(row["status"] for row in observations).items())),
                "family_windows": family_windows, "observed_alias_variants": len({(row["matched_family"], tuple(row["matched_alias_indices"][row["matched_family"]])) for row in known}),
                "potential_inconsistency": len(families) > 1 and len(known_windows) > 1,
                "semantic_error": None, "observations": observations})
        by_candidate[alias] = {"expected_windows": manifest["expected_windows"], "result_windows": len(results),
            "expected_eligible_occurrences": len(manifest["eligible_occurrences"]), "status_counts": dict(sorted(counts.items())),
            "potential_inconsistency_groups": sum(row["potential_inconsistency"] for row in diagnostics), "groups": diagnostics}
    return {"schema_version": "terminology-literal-diagnostics-v1", "set": manifest["set"],
        "source_selection": manifest["source_selection"], "candidate_results": by_candidate,
        "temporal_formal_freeze_binding_verified_by_this_tool": False, "semantic_scoring_performed": False,
        "limitations_zh": LIMITATIONS}


def report(summary: dict[str, Any]) -> str:
    lines = ["# 跨窗口术语字面诊断", "", f"分轨：`{summary['set']}`；源侧目录 {summary['source_selection']['eligible_terms']}/{summary['source_selection']['declared_terms']} 词满足至少两窗口门槛。", "",
        "| 匿名候选 | 源侧预期词出现次数 | 单族命中 | 未分类 | 多族歧义 | 无译文 | 潜在不一致组 |",
        "| --- | --- | --- | --- | --- | --- | --- |"]
    for alias, item in summary["candidate_results"].items():
        counts = item["status_counts"]
        lines.append(f"| {alias} | {item['expected_eligible_occurrences']} | {counts.get('single_declared_family', 0)} | {counts.get('unclassified', 0)} | {counts.get('ambiguous_multiple_families', 0)} | {counts.get('missing_translation', 0)} | {item['potential_inconsistency_groups']} |")
    lines += ["", "本表不包含字幕或目标词文本；详细匿名 ID、别名序号及源范围见 JSON。未运行语义评分。", ""] + ["- " + value for value in LIMITATIONS]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="有限封闭目录的术语诊断，不调用模型。")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--inputs", type=Path, required=True)
    prepare.add_argument("--source-manifest", type=Path, required=True)
    prepare.add_argument("--catalog", type=Path, required=True)
    prepare.add_argument("--set-name", required=True)
    prepare.add_argument("--output", type=Path, required=True)
    diagnostic = commands.add_parser("analyze")
    diagnostic.add_argument("--manifest", type=Path, required=True)
    diagnostic.add_argument("--candidate", action="append", required=True)
    diagnostic.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    sources = {field: value for field, value in vars(args).items() if isinstance(value, Path) and field != "output"}
    candidates = {}
    for value in getattr(args, "candidate", []):
        alias, separator, path = value.partition("=")
        if not separator or not alias or not path or alias in candidates:
            raise ValueError("candidate requires unique anonymous alias=path")
        candidates[alias] = Path(path)
        sources["candidate:" + alias] = Path(path)
    before = {name: sha(path) for name, path in sources.items()}
    if args.command == "prepare":
        summary = prepare_manifest(load_jsonl(args.inputs), read_json(args.source_manifest), read_json(args.catalog), args.set_name)
    else:
        summary = analyze(read_json(args.manifest), {alias: load_jsonl(path) for alias, path in candidates.items()})
    if any(sha(path) != before[name] for name, path in sources.items()):
        raise ValueError("inputs changed during terminology diagnostics")
    summary["input_provenance"] = {name: {"path": str(path.resolve()), "sha256": before[name]} for name, path in sources.items()}
    summary["implementation_sha256"] = sha(Path(__file__))
    args.output.mkdir(parents=True, exist_ok=False)
    dump(args.output / ("source-term-manifest.json" if args.command == "prepare" else "summary.json"), summary)
    dump(args.output / "config.json", {"command": args.command, "input_provenance": summary["input_provenance"], "implementation_sha256": summary["implementation_sha256"]})
    (args.output / "executed-terminology-diagnostics.py").write_bytes(Path(__file__).read_bytes())
    if args.command == "analyze":
        (args.output / "report.md").write_text(report(summary), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
