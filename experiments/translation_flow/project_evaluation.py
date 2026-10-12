"""Evaluation-only projection of immutable SRT cue deliveries onto frozen IDs."""

from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
import re
from typing import Any

from experiments.translation_eval.runner import (P_FLOW_CONTRACT, dump, dump_jsonl, indexed,
                                                  load_jsonl, prepare, read_json, safe_id, sha)
from .cli import APEX_SHA256, load_prepared
from .srt import read_srt
from .worker import CANDIDATE


def project(plan_path: Path, output: Path, *, prepare_evaluation: bool = True) -> dict[str, Any]:
    """References enter only the derived evaluator artifacts, never source preparation."""
    plan = read_json(plan_path)

    def resolve(value: str) -> Path:
        path = Path(value)
        return path.resolve() if path.is_absolute() else (plan_path.parent / path).resolve()

    def identity(path: Path) -> dict[str, str]:
        return {"path": str(path.resolve()), "sha256": sha(path)}

    if output.exists():
        raise ValueError("projection output must be a new directory")
    if not isinstance(plan, dict) or not isinstance(plan.get("windows"), list) or not plan["windows"]:
        raise ValueError("projection requires an explicit frozen window selection")
    original_inputs, original_refs, corpus = (resolve(plan[name]) for name in ("inputs", "references", "corpus_manifest"))
    requests, refs = indexed(load_jsonl(original_inputs)), indexed(load_jsonl(original_refs))
    selected = indexed(plan["windows"], "window_id")
    if not set(selected) <= set(requests) or not set(selected) <= set(refs):
        raise ValueError("projection selected window IDs differ from input/reference corpus")
    sources, window_sources, scopes = {}, {}, {}
    for wid, selection in selected.items():
        safe_id(wid)
        request, ref = requests[wid], refs[wid]
        mapping = selection.get("cue_map")
        context = indexed(request["context"])
        units = indexed(ref["units"])
        if (not isinstance(mapping, dict) or set(mapping) != set(context)
                or len(set(mapping.values())) != len(mapping)
                or set(request["translate_ids"]) != set(ref["scored_ids"])
                or set(context) != set(units)
                or any(item["text"] != units[uid]["ja"] for uid, item in context.items())
                or set(request["translate_ids"]) != {uid for uid, unit in units.items() if unit["score"]}):
            raise ValueError("projection corpus/source ID mapping disagreement")
        source = resolve(selection["source_srt"])
        encoding = selection.get("encoding", "utf-8-sig")
        document = read_srt(source, encoding=encoding)
        cues = {cue.id: cue for cue in document.cues}
        previous = 0
        for item in request["context"]:
            cue = cues.get(mapping[item["id"]])
            if cue is None or cue.text != item["text"] or cue.ordinal <= previous:
                raise ValueError("projection source text/identity/order mismatch")
            # If frozen source windows carry timestamps, preserve those checks too.
            for name in ("start_ms", "end_ms"):
                if name in item and item[name] != getattr(cue, name):
                    raise ValueError("projection frozen source time mismatch")
            previous = cue.ordinal
        work = ref["work"]
        if work in scopes and scopes[work]["sha256"] != document.source_sha256:
            raise ValueError("one evaluation work cannot silently combine different source documents")
        sources[document.source_sha256] = document
        window_sources[wid] = document.source_sha256
        scopes[work] = {**identity(source), "work": work, "scope": "full-source", "encoding": encoding}
    candidate_plan = plan.get("candidates")
    if not isinstance(candidate_plan, dict) or not candidate_plan:
        raise ValueError("projection needs explicit candidate run pointers")
    candidate_data, raw_artifacts = {}, {}
    for alias, runs in candidate_plan.items():
        safe_id(alias)
        if not isinstance(runs, list) or not runs:
            raise ValueError("candidate needs at least one prepared excerpt/run")
        targets, translations, batches, failed, scheduled = set(), {}, [], set(), {}
        raw_paths = set()
        for pointer in runs:
            prepared_dir, run_dir = resolve(pointer["prepared"]), resolve(pointer["translation_run"])
            manifest, document, windows, workload = load_prepared(prepared_dir)
            source_sha = document.source_sha256
            if source_sha not in sources:
                raise ValueError("candidate source does not belong to the selected source documents")
            run = read_json(run_dir / "run.json")
            if (run.get("lane") != "P-flow" or run.get("candidate") != CANDIDATE
                    or run.get("input_sha256") != manifest["artifacts"]["model-input.jsonl"]
                    or run.get("session_plan_sha256") != manifest["artifacts"]["session-plan.json"]
                    or run.get("expected_window_ids") != [window["id"] for window in windows]
                    or run.get("settings") != workload
                    or run.get("asset", {}).get("sha256") != APEX_SHA256
                    or run.get("engine", {}).get("model_sha256") != APEX_SHA256
                    or sha(run_dir / "inputs.jsonl") != manifest["artifacts"]["model-input.jsonl"]):
                raise ValueError("candidate run differs from immutable prepared source/recipe identity")
            raw_paths.add(prepared_dir / "prepared.json")
            raw_paths.update(prepared_dir / name for name in manifest["artifacts"])
            raw_paths.update([run_dir / "run.json", run_dir / "inputs.jsonl"])
            loaded = {}
            for name, key in (("results.jsonl", "id"), ("ledger.jsonl", "window_id"), ("schedule.jsonl", "window_id")):
                path = run_dir / name
                loaded[name] = indexed(load_jsonl(path), key) if path.is_file() else {}
                if path.is_file():
                    raw_paths.add(path)
            result, ledger, schedule = (loaded[name] for name in ("results.jsonl", "ledger.jsonl", "schedule.jsonl"))
            allowed_windows = {window["id"] for window in windows}
            if (set(result) - allowed_windows or set(ledger) - allowed_windows or set(schedule) - allowed_windows
                    or set(schedule) & (set(result) | set(ledger))):
                raise ValueError("candidate result/ledger/schedule has unknown or conflicting batches")
            for window in windows:
                wid = window["id"]
                keys = {(source_sha, uid) for uid in window["translate_ids"]}
                if keys & targets:
                    raise ValueError("candidate excerpts duplicate source target coverage")
                targets.update(keys)
                if wid in schedule:
                    state = schedule[wid]
                    if state.get("status") not in {"not_run", "setup_failed"} or not state.get("reason"):
                        raise ValueError("candidate schedule requires explicit status and reason")
                    scheduled.update({key: state for key in keys})
                row, terminal = result.get(wid), ledger.get(wid)
                if row is not None or terminal is not None:
                    batches.append({"source_sha256": source_sha, "window": window})
                if terminal and terminal.get("status") == "translation_failed":
                    failed.update(keys)
                if row is None:
                    continue  # Missing outputs remain missing, never inherit Japanese.
                values = row.get("translations")
                if (set(row) - {"id", "translations", "elapsed_seconds"}
                        or not isinstance(values, dict) or set(values) - set(window["translate_ids"])
                        or terminal is None or terminal.get("translations") != values):
                    raise ValueError("candidate source IDs or result/ledger translations conflict")
                if (terminal.get("status") not in {"delivered", "translation_failed"}
                        or "translation_groups" in terminal or "mapping_groups" in terminal):
                    raise ValueError("candidate source run is not an unchanged per-ID delivery")
                for uid, text in values.items():
                    if isinstance(text, str) and text.strip():
                        translations[(source_sha, uid)] = text
                for attempt in terminal.get("attempts", []):
                    if isinstance(attempt.get("original_response"), str):
                        raw = (Path(attempt["original_response"]) / "response.raw").resolve()
                        if not raw.is_relative_to(run_dir.resolve()):
                            raise ValueError("candidate raw-response pointer escapes translation run")
                        if raw.is_file():
                            raw_paths.add(raw)
        for wid, selection in selected.items():
            if any((window_sources[wid], selection["cue_map"][uid]) not in targets
                   for uid in requests[wid]["translate_ids"]):
                raise ValueError("each frozen scored source ID must be targeted exactly once per candidate")
        candidate_data[alias] = {"translations": translations, "batches": batches, "failed": failed,
                                 "scheduled": scheduled}
        raw_artifacts[alias] = [identity(path) for path in sorted(raw_paths)]
    derived_inputs, derived_refs, mappings = [], [], []
    for wid, selection in selected.items():
        request, ref = requests[wid], refs[wid]
        source_sha = window_sources[wid]
        document = sources[source_sha]
        inversion = {source_id: eval_id for eval_id, source_id in selection["cue_map"].items()}
        included = set(inversion)
        scored = {selection["cue_map"][uid] for uid in request["translate_ids"]}
        if plan.get("append_batch_context", False):
            for candidate in candidate_data.values():
                for batch in candidate["batches"]:
                    window = batch["window"]
                    if batch["source_sha256"] == source_sha and set(window["translate_ids"]) & scored:
                        included.update(item["id"] for item in window["context"])
        context, units, mapping_items = [], [], []
        original_units = indexed(ref["units"])
        for cue in document.cues:
            if cue.id not in included:
                continue
            compact_id = cue.id if re.fullmatch(r"c[0-9]+", cue.id) else f"c{cue.ordinal:06d}"
            eval_id = inversion.get(cue.id, compact_id)
            if eval_id in original_units and cue.id not in inversion:
                raise ValueError("extra context ID collides with original evaluation IDs")
            context.append({"id": eval_id, "text": cue.text})
            units.append(deepcopy(original_units[eval_id]) if eval_id in original_units else
                         {"id": eval_id, "ja": cue.text, "score": False})
            mapping_items.append({"eval_id": eval_id, "source_cue_id": cue.id})
        derived_inputs.append({**deepcopy(request), "context": context})
        derived_refs.append({**deepcopy(ref), "units": units})
        mappings.append({"window_id": wid, "work": ref["work"], "cues": mapping_items})
    output.mkdir(parents=True)
    inputs_path, refs_path, mapping_path = (output / name for name in ("inputs.jsonl", "references.jsonl", "mapping.jsonl"))
    dump_jsonl(inputs_path, derived_inputs)
    dump_jsonl(refs_path, derived_refs)
    dump_jsonl(mapping_path, mappings)
    candidates, ledgers, schedules = {}, {}, {}
    for alias, data in candidate_data.items():
        results, ledger, schedule = [], [], []
        for wid, selection in selected.items():
            source_sha = window_sources[wid]
            values = {uid: data["translations"][(source_sha, selection["cue_map"][uid])]
                      for uid in requests[wid]["translate_ids"]
                      if (source_sha, selection["cue_map"][uid]) in data["translations"]}
            failure = any((source_sha, selection["cue_map"][uid]) in data["failed"] for uid in requests[wid]["translate_ids"])
            source_schedule = [data["scheduled"].get((source_sha, selection["cue_map"][uid]))
                               for uid in requests[wid]["translate_ids"]]
            scheduled_ids = [state for state in source_schedule if state]
            if len(scheduled_ids) == len(source_schedule) and len({state["status"] for state in scheduled_ids}) == 1:
                schedule.append({"window_id": wid, "status": scheduled_ids[0]["status"],
                                 "reason": "所有计分源 cue 明确未执行；原始原因见源调度清单。"})
                continue
            mixed_schedule = bool(scheduled_ids)
            results.append({"id": wid, "translations": values, "delivery_contract": P_FLOW_CONTRACT, "elapsed_seconds": None})
            ledger.append({"window_id": wid, "translations": values, "delivery_contract": P_FLOW_CONTRACT,
                           "status": "mapping_unjudgeable" if mixed_schedule else "translation_failed" if failure else "delivered",
                           "reason": "本评分窗口混合已执行与明确未执行源批次；当前窗口契约不拆分计分范围。" if mixed_schedule
                                     else "源批次明确翻译失败。" if failure else None,
                           "elapsed_seconds": None, "generation_seconds": None, "auxiliary_seconds": None,
                           "attempts": None, "generation_timing_reason": "共享批次的评分切片不可独立计时；完整原始成本另记。"})
        candidates[alias], ledgers[alias] = output / alias / "results.jsonl", output / alias / "ledger.jsonl"
        dump_jsonl(candidates[alias], results)
        dump_jsonl(ledgers[alias], ledger)
        if schedule:
            schedules[alias] = output / alias / "schedule.jsonl"
            dump_jsonl(schedules[alias], schedule)
    contract = {"schema": P_FLOW_CONTRACT, "lane": "P-flow", "delivery_contract": P_FLOW_CONTRACT,
                "inputs_sha256": sha(inputs_path), "references_sha256": sha(refs_path), "corpus_manifest_sha256": sha(corpus),
                "mapping": identity(mapping_path), "allowed_source_scope": list(scopes.values()), "candidate_artifacts": raw_artifacts}
    contract_path = output / "p-flow-contract.json"
    dump(contract_path, contract)
    projection = {"schema": "p-flow-evaluation-projection-v1", "plan": identity(plan_path),
                  "original_inputs": identity(original_inputs), "original_references": identity(original_refs),
                  "corpus_manifest": identity(corpus), "append_batch_context": plan.get("append_batch_context", False),
                  "evaluation": str((output / "evaluation").resolve()), "contract": identity(contract_path),
                  "quality_status": "mechanical projection only; no semantic judgment"}
    dump(output / "projection.json", projection)
    if prepare_evaluation:
        prepare(inputs_path, refs_path, candidates, output / "evaluation", lane="P-flow",
                split=plan.get("split", "dev"), candidate_ledgers=ledgers, corpus_manifest=corpus,
                p_flow_contract=contract_path, candidate_schedules=schedules)
    return projection


def main() -> None:
    parser = argparse.ArgumentParser(description="只供评估使用的冻结源 cue 投影，不启动翻译或裁判")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-prepare", action="store_true")
    args = parser.parse_args()
    try:
        project(args.plan, args.output, prepare_evaluation=not args.no_prepare)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"projection error: {exc}\n")


if __name__ == "__main__":
    main()
