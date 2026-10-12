"""Prepare one named, source-only screening variant; never run models or judges."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from experiments.translation_demo.run import read_inputs
from experiments.translation_eval.runner import dump, indexed, read_json, sha
from .cli import prepare, scoped_document
from .srt import plan_batches, read_srt
from .worker import positive_number

VARIANTS = {
    "fixed5context1": {"policy": "fixed", "target_size": 5, "context_size": 1},
    "natural5context1": {"policy": "natural", "target_size": 5, "context_size": 1},
    "fixed5context3": {"policy": "fixed", "target_size": 5, "context_size": 3},
    "fixed10context1": {"policy": "fixed", "target_size": 10, "context_size": 1},
}
STAGE_BATCH_CAPS = {"P0": 6, "P1": 20, "P2": 40, "P3": 20, "P4": None, "P5": None}


def build(inputs: Path, mapping_path: Path, output: Path, variant: str,
          budgets: dict[str, Any], stage: str = "P1") -> dict[str, Any]:
    if variant not in VARIANTS or stage not in STAGE_BATCH_CAPS:
        raise ValueError("choose one supported screening variant and stage")
    if output.exists():
        raise ValueError("screening output must be a new directory")
    expected_budgets = {"max_translation_calls", "max_judge_calls", "max_estimated_tokens", "max_wall_seconds"}
    if set(budgets) != expected_budgets:
        raise ValueError("all four explicit workload budgets are required")
    for name in expected_budgets - {"max_judge_calls"}:
        positive_number(budgets[name], name, integer=name != "max_wall_seconds")
    if type(budgets["max_judge_calls"]) is not int or budgets["max_judge_calls"] < 0:
        raise ValueError("max_judge_calls must be explicitly nonnegative")
    input_digest, mapping_digest = sha(inputs), sha(mapping_path)
    requests = indexed(read_inputs(inputs))  # Existing strict source-only firewall.
    mapping = read_json(mapping_path)
    if not isinstance(mapping, dict) or set(mapping) != {"windows"} or not isinstance(mapping["windows"], list):
        raise ValueError("source-only mapping accepts only a windows list")
    selected = indexed(mapping["windows"], "window_id")
    if not selected or set(selected) != set(requests):
        raise ValueError("source-only mapping must exactly cover the explicit selected input windows")
    sources, scopes = {}, {}
    for wid, row in selected.items():
        if (set(row) - {"window_id", "source_srt", "cue_map", "encoding"}
                or not {"window_id", "source_srt", "cue_map"} <= set(row)):
            raise ValueError("mapping contains unsupported fields; references do not belong in source preparation")
        source = Path(row["source_srt"])
        source = source.resolve() if source.is_absolute() else (mapping_path.parent / source).resolve()
        encoding = row.get("encoding", "utf-8-sig")
        document = read_srt(source, encoding=encoding)
        cues = {cue.id: cue for cue in document.cues}
        cue_map = row["cue_map"]
        request = requests[wid]
        if (not isinstance(cue_map, dict) or set(cue_map) != {item["id"] for item in request["context"]}
                or any(not isinstance(value, str) for value in cue_map.values())
                or len(set(cue_map.values())) != len(cue_map)):
            raise ValueError("explicit cue mapping must uniquely cover original context IDs")
        previous = 0
        for item in request["context"]:
            cue = cues.get(cue_map[item["id"]])
            if cue is None or cue.text != item["text"] or cue.ordinal <= previous:
                raise ValueError("frozen selection source text/ID/order differs from the SRT")
            previous = cue.ordinal
        ordinals = [cues[cue_map[uid]].ordinal for uid in request["translate_ids"]]
        first, last = max(1, min(ordinals) - 5), min(len(document.cues), max(ordinals) + 5)
        digest = document.source_sha256
        sources.setdefault(digest, {"path": source, "encoding": encoding, "document": document})
        scopes.setdefault(digest, []).append({"first": first, "last": last, "window_ids": [wid]})
    planned = []
    for digest in sorted(scopes):
        ranges = sorted(scopes[digest], key=lambda item: (item["first"], item["last"], item["window_ids"]))
        merged: list[dict[str, Any]] = []
        for scope in ranges:
            if merged and scope["first"] <= merged[-1]["last"]:
                merged[-1]["last"] = max(scope["last"], merged[-1]["last"])
                merged[-1]["window_ids"] += scope["window_ids"]
            else:
                merged.append({**scope, "window_ids": list(scope["window_ids"])})
        source = sources[digest]
        document = source["document"]
        for scope in merged:
            start_index, end_index = document.cues[scope["first"] - 1].index, document.cues[scope["last"] - 1].index
            excerpt = scoped_document(document, start_index, end_index)
            batches = plan_batches(excerpt, **VARIANTS[variant], gap_ms=1000)
            cap = STAGE_BATCH_CAPS[stage]
            if cap is not None and len(batches) > cap:
                raise ValueError(f"merged source excerpt exceeds {stage} per-workload cap of {cap} batches")
            planned.append({"source_sha256": digest, "source": source, "first_ordinal": scope["first"],
                            "last_ordinal": scope["last"], "start_cue": start_index, "end_cue": end_index,
                            "window_ids": sorted(scope["window_ids"]), "batch_count": len(batches),
                            "target_cue_count": len(excerpt.cues)})
    output.mkdir(parents=True)
    entries = []
    for number, excerpt in enumerate(planned, 1):
        label = f"excerpt-{number:03d}"
        directory = output / label
        source = excerpt["source"]
        args = argparse.Namespace(source=source["path"], output=directory, encoding=source["encoding"],
                                  start_cue=excerpt["start_cue"], end_cue=excerpt["end_cue"],
                                  **VARIANTS[variant], gap_ms=1000, recipe="b0-prompt",
                                  sampling="official-temperature0", seed=20261006,
                                  n_predict=1024, max_attempts=2, stage=stage, **budgets)
        manifest = prepare(args)
        entries.append({key: value for key, value in excerpt.items() if key != "source"} | {
            "label": label, "prepared": str(directory.resolve()),
            "prepared_sha256": sha(directory / "prepared.json"),
            "source_path": str(source["path"]), "encoding": source["encoding"],
            "inputs": str((directory / "model-input.jsonl").resolve()),
            "input_sha256": manifest["artifacts"]["model-input.jsonl"],
            "session_plan": str((directory / "session-plan.json").resolve()),
            "session_plan_sha256": manifest["artifacts"]["session-plan.json"],
            "prepared_workload_label": "b0-prompt"})
    if sha(inputs) != input_digest or sha(mapping_path) != mapping_digest:
        raise ValueError("source-only selection changed during preparation; root manifest is unpublished")
    result = {"schema": "hy30-source-screening-v1", "variant": variant, "stage": stage, "lane": "P-flow",
              "selection_inputs": {"path": str(inputs.resolve()), "sha256": input_digest},
              "source_mapping": {"path": str(mapping_path.resolve()), "sha256": mapping_digest},
              "recipe": "b0-prompt", "sampling": "official-temperature0", "seed": 20261006,
              "n_predict": 1024, "source_padding_each_side": 5, "batching": VARIANTS[variant],
              "selected_windows": len(selected), "excerpt_count": len(entries),
              "total_batches": sum(entry["batch_count"] for entry in entries),
              "total_target_cues": sum(entry["target_cue_count"] for entry in entries), "excerpts": entries,
              "budget_scope_zh": "这些预算分别约束每个准备 workload；协调层仍须合并阶段成本，不能因新建 excerpt 而重置共享额度。",
              "runtime_assembly_note_zh": "每个准备目录原始 workload label 为 b0-prompt。直接合并这些同名 workload 会违反 worker 的唯一标签校验；重命名又会违反导出与评估的 prepared settings 身份校验。可分别执行原始计划；共用一个 GPU 会话需要另行明确版本化的调度契约，不能静默改名。",
              "quality_status": "source-only preparation; no inference, reference access, or semantic judgment"}
    dump(output / "screening.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="单变体源文筛选准备；合并重叠片段，不启动模型或裁判")
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variant", choices=VARIANTS, required=True)
    parser.add_argument("--stage", choices=STAGE_BATCH_CAPS, default="P1")
    parser.add_argument("--max-translation-calls", type=int, required=True)
    parser.add_argument("--max-judge-calls", type=int, required=True)
    parser.add_argument("--max-estimated-tokens", type=int, required=True)
    parser.add_argument("--max-wall-seconds", type=float, required=True)
    args = parser.parse_args()
    budgets = {name: getattr(args, name) for name in (
        "max_translation_calls", "max_judge_calls", "max_estimated_tokens", "max_wall_seconds")}
    try:
        build(args.inputs, args.mapping, args.output, args.variant, budgets, args.stage)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        parser.exit(2, f"screening preparation error: {exc}\n")


if __name__ == "__main__":
    main()
