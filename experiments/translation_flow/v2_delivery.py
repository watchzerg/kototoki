"""Source-only v2 scene delivery and frozen scoring-window projection.

Shared batches are accounted once. Projection carries no timing attribution,
reference text, semantic scores, or duplicated native paragraph translations.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from experiments.translation_eval.runner import (
    P_FLOW_CONTRACT, dump, dump_jsonl, indexed, load_jsonl, read_json, safe_id, sha,
)
from .costs import metric
from .srt import SourceCue, SourceDocument, diagnostics, parse_srt, render_srt, source_provenance
from .v2_semantic import parse_mapping


SCHEDULE_STATUSES = {"not_run", "setup_failed"}
TERMINAL_STATUSES = {"delivered", "translation_failed", "mapping_unjudgeable"}
FLOW_DIAGNOSTIC_FIELDS = ("planning_provenance", "planning_cost", "mapping_provenance",
                          "mapping_protocol", "mapping_cost", "native_protocol", "mapping_grammar_build")


def _session_transport(run_dir: Path, run: dict[str, Any]) -> tuple[Path, list[Path]]:
    """Authorize only the sibling transport of this verified worker session."""
    root = run_dir.parent
    plan_path, session_path = root / "session-plan.json", root / "session.json"
    if not plan_path.is_file() or not session_path.is_file():
        raise ValueError("shared transport lacks verified session provenance")
    plan, session = read_json(plan_path), read_json(session_path)
    plan_hash = sha(plan_path)
    workloads = plan.get("workloads")
    if (run.get("schema") != "hy30-flow-session-v2" or session.get("schema") != run["schema"]
            or plan.get("schema") != run["schema"] or plan.get("lane") != run.get("lane")
            or run.get("session_plan_sha256") != plan_hash or session.get("plan_sha256") != plan_hash
            or not isinstance(workloads, list) or len(workloads) != 1
            or workloads[0] != run.get("settings") or workloads[0].get("label") != run_dir.name
            or plan.get("experiment_identity", {}).get("source_manifest_sha256") != run.get("source_manifest_sha256")
            or not run.get("compatibility_sha256")
            or session.get("compatibility_sha256") != run["compatibility_sha256"]
            or not run.get("code_sha256") or session.get("code_sha256") != run["code_sha256"]):
        raise ValueError("shared transport session and workload identity disagree")
    identity = session.get("identity", {})
    asset, engine = identity.get("asset", {}), identity.get("engine", {})
    if (asset.get("id") != run.get("candidate") or not asset.get("sha256")
            or engine.get("asset", {}).get("sha256") != asset["sha256"]
            or engine.get("model_sha256") != asset["sha256"]):
        raise ValueError("shared transport verified model identity disagrees")
    transport = (root / "transport").resolve()
    if not transport.is_dir() or transport.parent != root.resolve():
        raise ValueError("shared transport root escapes the verified session")
    return transport, [plan_path, session_path]


def _trace_artifacts(pointer: Path, key: str, attempt: dict[str, Any]) -> list[Path]:
    """Bind a recorded exchange to its own request/response before hashing."""
    paths = [pointer / name for name in ("request.json", "response.raw", "transport.json")]
    if not pointer.is_dir() or any(not path.is_file() or path.resolve().parent != pointer for path in paths):
        raise ValueError("raw translation trace is missing or escapes its exchange directory")
    request = read_json(paths[0])
    expected_endpoint = "/completion" if key == "original_response" else "/tokenize"
    if request.get("endpoint") != expected_endpoint:
        raise ValueError("raw translation trace endpoint disagrees with attempted stage")
    if key == "original_response":
        if request.get("body") != attempt.get("request"):
            raise ValueError("raw completion request disagrees with its recorded attempt")
        if "response" in attempt and read_json(paths[1]) != attempt["response"]:
            raise ValueError("raw completion response disagrees with its recorded attempt")
    else:
        body = request.get("body")
        if not isinstance(body, dict) or not isinstance(body.get("content"), str):
            raise ValueError("raw tokenization request lacks source prompt provenance")
        prompt_hash = hashlib.sha256(json.dumps(body["content"], ensure_ascii=False, sort_keys=True,
                                                separators=(",", ":")).encode("utf-8")).hexdigest()
        if prompt_hash != attempt.get("prompt_sha256"):
            raise ValueError("raw tokenization prompt disagrees with its recorded attempt")
    return paths


def aggregate(
    packed: dict[str, Any], results: list[dict[str, Any]],
    ledger: list[dict[str, Any]], schedules: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate batch identity and retain every expected cue's delivery state."""
    batches = indexed(packed["batches"])
    scenes = indexed(packed["scenes"])
    predictions, terminals, scheduled = (indexed(results), indexed(ledger, "window_id"),
                                         indexed(schedules, "window_id"))
    for rows in (predictions, terminals, scheduled):
        if set(rows) - set(batches):
            raise ValueError("run contains unknown batch IDs")
    if set(predictions) & set(scheduled):
        raise ValueError("batch cannot have a result and a schedule entry")
    states: dict[str, dict[str, dict[str, Any]]] = {
        sid: {uid: {"status": "missing", "batch_id": None} for uid in scene["translate_ids"]}
        for sid, scene in scenes.items()
    }
    ownership: set[tuple[str, str]] = set()
    native_diagnostics = []
    for bid, batch in batches.items():
        sid, targets = batch["scene_id"], batch["target_ids"]
        if sid not in scenes or not targets or len(targets) != len(set(targets)):
            raise ValueError("invalid scene/batch target mapping")
        readonly = batch["readonly_ids"]
        if (not isinstance(readonly, list) or len(readonly) != len(set(readonly))
                or set(readonly) & set(targets) or set(readonly) - set(states[sid])):
            raise ValueError("invalid read-only source context mapping")
        for uid in targets:
            key = (sid, uid)
            if uid not in states[sid] or key in ownership:
                raise ValueError("duplicate or unknown source cue assignment")
            ownership.add(key)
        terminal, result, schedule = terminals.get(bid), predictions.get(bid), scheduled.get(bid)
        if schedule:
            status = schedule.get("status")
            if status not in SCHEDULE_STATUSES or not schedule.get("reason"):
                raise ValueError("schedule requires an explicit nonexecution status and reason")
            if terminal and terminal.get("status") != status:
                raise ValueError("schedule and attempted batch status conflict")
        elif terminal:
            status = terminal.get("status")
            if status not in TERMINAL_STATUSES | SCHEDULE_STATUSES:
                raise ValueError("unknown terminal batch status")
            if status != "delivered" and not terminal.get("reason"):
                raise ValueError("unsuccessful batch requires a reason")
        else:
            status = "missing"
        if result and terminal is None:
            raise ValueError("batch result lacks terminal ledger provenance")
        values = result.get("translations", {}) if result else {}
        if (not isinstance(values, dict) or set(values) - set(targets)
                or (terminal and result and terminal.get("translations") != values)):
            raise ValueError("result/ledger/source translations disagree")
        if result and result.get("status", status) != status:
            raise ValueError("result and ledger terminal status disagree")
        if terminal:
            native = {name: deepcopy(terminal[name]) for name in (
                "semantic_plan", "native_unit_translations", "source_span_to_target_span",
                "native_text", "mapping_reason", "delivery_contract", "reason", "failure_stage", "error_kind",
                *FLOW_DIAGNOSTIC_FIELDS,
            ) if name in terminal}
            if isinstance(terminal.get("source_preparation"), dict):
                # The shared preparation ledger owns its measurements once.
                # Carry only links and the exact per-request options identity.
                native["source_preparation"] = {key: deepcopy(terminal["source_preparation"][key])
                                                for key in ("identity", "visible_options_sha256", "cost_attribution", "protocol", "projection", "source_visibility")
                                                if key in terminal["source_preparation"]}
            if native:
                native_diagnostics.append({"batch_id": bid, "scene_id": sid,
                                           "status": status, **native})
            semantic = (any(name in terminal for name in ("semantic_plan", "native_unit_translations",
                                                          "source_span_to_target_span"))
                        or terminal.get("delivery_contract") == "source-cue-exact-unit-partition-v2")
            if status == "delivered" and semantic:
                if not isinstance(terminal.get("semantic_plan"), dict) or not isinstance(terminal.get("native_unit_translations"), dict):
                    raise ValueError("semantic delivery lacks native unit/plan provenance")
                spans = terminal.get("source_span_to_target_span")
                if not isinstance(spans, list):
                    raise ValueError("semantic delivery lacks exact mapping provenance")
                segments = []
                for item in spans:
                    if (not isinstance(item, dict) or len(item.get("source_ids", [])) != 1
                            or len(item.get("target_spans", [])) != 1
                            or len(item["target_spans"][0]) != 2):
                        raise ValueError("semantic delivery requires one native substring per cue")
                    start, end = item["target_spans"][0]
                    segments.append({"unit_id": item["unit_id"], "source_id": item["source_ids"][0],
                                     "start": start, "end": end})
                included = set(targets) | set(batch["readonly_ids"])
                window = {"id": bid, "source_language": "ja", "target_language": "zh-Hans",
                          "context": [{"id": cue["id"], "text": cue["text"]}
                                      for cue in scenes[sid]["context"] if cue["id"] in included],
                          "translate_ids": targets}
                checked = parse_mapping(json.dumps({"segments": segments}), window,
                                        terminal.get("semantic_plan"), terminal["native_unit_translations"])
                if checked["translations"] != values:
                    raise ValueError("semantic delivery differs from unchanged native partition")
        for uid in targets:
            state = {"status": status, "batch_id": bid}
            if status != "delivered":
                state["reason"] = (schedule or terminal or {}).get("reason", "No terminal batch evidence")
            elif uid not in values:
                state.update(status="missing", reason="Delivered batch omitted this cue")
            else:
                text = values[uid]
                if (not isinstance(text, str) or not text.strip()
                        or any(not line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))):
                    state.update(status="invalid", reason="Empty or invalid SRT cue text")
                else:
                    state["text"] = text
            states[sid][uid] = state
    expected = {(sid, uid) for sid, scene in scenes.items() for uid in scene["translate_ids"]}
    if ownership != expected:
        raise ValueError("packed batches must cover every frozen scene cue exactly once")
    cost_rows = list(terminals.values())
    costs = {"unit": "unique_source_batch", "expected_batches": len(batches),
             "recorded_batches": len(cost_rows), "missing_batch_ids": [bid for bid in batches if bid not in terminals],
             "status_counts": dict(Counter(row["status"] for row in cost_rows)),
             **{name: metric([terminals[bid].get(name) if bid in terminals
                              else 0 if bid in scheduled else None for bid in batches]) for name in (
                 "elapsed_seconds", "generation_seconds", "auxiliary_seconds")}}
    costs["attempts"] = metric([len(terminals[bid]["attempts"]) if bid in terminals
                                and isinstance(terminals[bid].get("attempts"), list)
                                else 0 if bid in scheduled else None for bid in batches])
    attempts = [attempt for row in cost_rows for attempt in row.get("attempts", [])
                if isinstance(attempt, dict) and attempt.get("completion_dispatched")]
    costs["dispatched_completions"] = len(attempts)
    costs["input_tokens"] = metric([attempt.get("input_tokens") for attempt in attempts])
    costs["output_tokens"] = metric([attempt.get("response", {}).get("tokens_predicted")
                                     if isinstance(attempt.get("response"), dict) else None for attempt in attempts])
    return {"scenes": states, "costs": costs, "native_diagnostics": native_diagnostics}


def project_windows(packed: dict[str, Any], aggregated: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Project frozen scoring IDs; mixed nonexecution remains unjudgeable."""
    results, ledger, schedules, mechanical = [], [], [], []
    for window in packed["windows"]:
        wid = window.get("window_id", window.get("id"))
        safe_id(wid)
        sid, ids = window["scene_id"], window["scored_ids"]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("scored window requires unique nonempty source IDs")
        states = [aggregated["scenes"][sid][uid] for uid in ids]
        statuses = {item["status"] for item in states}
        details = {"window_id": wid, "scene_id": sid, "expected_cues": len(ids),
                   "status_counts": dict(Counter(item["status"] for item in states)),
                   "source_batch_ids": list(dict.fromkeys(item["batch_id"] for item in states))}
        mechanical.append(details)
        if statuses <= SCHEDULE_STATUSES:
            schedules.append({"window_id": wid, "status": "setup_failed" if "setup_failed" in statuses else "not_run",
                              "reason": "计分源批次全部明确未执行；逐 cue 原因见交付 sidecar。"})
            continue
        values = {uid: state["text"] for uid, state in zip(ids, states) if state["status"] == "delivered"}
        status = ("mapping_unjudgeable" if ("mapping_unjudgeable" in statuses or statuses & SCHEDULE_STATUSES)
                  else "translation_failed" if "translation_failed" in statuses else "delivered")
        reason = ("计分范围包含无法映射或混合未执行源 cue；保留缺分而不复制原生段落。" if status == "mapping_unjudgeable"
                  else "计分源批次有明确翻译失败。" if status == "translation_failed" else None)
        # No result at all preserves the evaluator's missing_window distinction.
        if statuses != {"missing"}:
            results.append({"id": wid, "translations": values, "delivery_contract": P_FLOW_CONTRACT,
                            "elapsed_seconds": None})
        ledger.append({"window_id": wid, "translations": values, "status": status, "reason": reason,
                       "delivery_contract": P_FLOW_CONTRACT, "elapsed_seconds": None,
                       "generation_seconds": None, "auxiliary_seconds": None, "attempts": None,
                       "generation_timing_reason": "评分窗口共享源批次，成本只在唯一批次汇总中记一次。",
                       **{key: details[key] for key in ("scene_id", "status_counts", "source_batch_ids")}})
    return {"results": results, "ledger": ledger, "schedule": schedules, "mechanical": mechanical}


def scene_document(scene: dict[str, Any], window: dict[str, Any]) -> SourceDocument:
    """Bind immutable canonical source IDs to exact frozen SRT indices/times."""
    units = indexed(window["units"])
    cues = []
    if [cue["id"] for cue in scene["context"]] != scene["translate_ids"]:
        raise ValueError("scene targets must preserve the complete source context order")
    if set(units) != set(scene["translate_ids"]):
        raise ValueError("frozen scene timing units differ from source cues")
    for ordinal, context in enumerate(scene["context"], 1):
        unit = units[context["id"]]
        # Parsing the frozen strings proves validity without inventing timing.
        parsed = parse_srt(f"{unit['index_text']}\n{unit['time_line']}\n{context['text']}\n").cues[0]
        if (parsed.index != unit["ja_srt_index"] or parsed.start_ms != unit["start_ms"]
                or parsed.end_ms != unit["end_ms"]
                or context["start"] != parsed.start_ms / 1000
                or context["end"] != parsed.end_ms / 1000):
            raise ValueError("source scene index/time provenance disagreement")
        cues.append(SourceCue(context["id"], ordinal, parsed.index, parsed.index_text,
                              parsed.time_line, parsed.start_ms, parsed.end_ms, context["text"]))
    return SourceDocument(window["source_sha256"], tuple(cues), "utf-8")


def deliver(
    source_manifest_path: Path, packed_mapping_path: Path, run_dir: Path, output: Path,
    *, candidate_id: str | None = None,
) -> dict[str, Any]:
    """Export each complete frozen scene and reference-free evaluation slices.

    The destination must be new. Incomplete scenes receive sidecars only. The
    source manifest and packed mapping are rechecked before successful SRTs are
    published; no source subtitle, reference, model, or service is modified.
    """
    source_manifest_path, packed_mapping_path, run_dir, output = (
        path.resolve() for path in (source_manifest_path, packed_mapping_path, run_dir, output))
    if output.exists():
        raise FileExistsError("delivery output must be a new directory")
    source_manifest, packed = read_json(source_manifest_path), read_json(packed_mapping_path)
    source_hash, packed_hash = sha(source_manifest_path), sha(packed_mapping_path)
    if packed.get("schema") != "hy30-flow-packed-v2":
        raise ValueError("delivery requires a frozen v2 packed mapping")
    frozen = packed.get("source_manifest", {})
    source_pointer = Path(frozen.get("path", ""))
    if not source_pointer.is_absolute():
        source_pointer = packed_mapping_path.parent / source_pointer
    if source_pointer.resolve() != source_manifest_path or frozen.get("sha256") != source_hash:
        raise ValueError("packed mapping source manifest identity changed")
    frozen_windows = indexed(source_manifest["windows"])
    selected = indexed(packed["windows"])
    if any(wid not in frozen_windows or window != frozen_windows[wid] for wid, window in selected.items()):
        raise ValueError("packed scoring windows differ from frozen source manifest")
    scenes = indexed(packed["scenes"])
    if list(scenes) != packed["scene_ids"]:
        raise ValueError("packed scene order differs from scene IDs")
    source_scenes = packed["source_scenes"]
    scene_path = Path(source_scenes["path"])
    if not scene_path.is_absolute():
        scene_path = packed_mapping_path.parent / scene_path
    if sha(scene_path) != source_scenes["sha256"]:
        raise ValueError("frozen source scene artifact changed")
    originals = indexed(load_jsonl(scene_path))
    if any(sid not in originals or scene != originals[sid] for sid, scene in scenes.items()):
        raise ValueError("packed scenes differ from frozen source-only inputs")
    documents = {}
    for sid, scene in scenes.items():
        members = [window for window in selected.values() if window["scene_id"] == sid]
        if not members:
            raise ValueError("each packed scene requires frozen source timing provenance")
        document = scene_document(scene, members[0])
        if any(scene_document(scene, window) != document for window in members[1:]):
            raise ValueError("scoring windows disagree on shared scene provenance")
        documents[sid] = document
    run = read_json(run_dir / "run.json")
    if (run.get("lane") != "P-flow" or run.get("source_manifest_sha256") != source_hash
            or run.get("packed_mapping_sha256") != packed_hash
            or run.get("expected_window_ids") != [batch["id"] for batch in packed["batches"]]):
        raise ValueError("translation run differs from immutable source/packing identity")
    if candidate_id is not None and run.get("candidate") != candidate_id:
        raise ValueError("candidate identity differs from requested delivery")
    inputs_path = run_dir / "inputs.jsonl"
    if sha(inputs_path) != run.get("input_sha256"):
        raise ValueError("translation run source input hash changed")
    inputs = indexed(load_jsonl(inputs_path))
    if set(inputs) != {batch["id"] for batch in packed["batches"]}:
        raise ValueError("translation run input batch IDs changed")
    for batch in packed["batches"]:
        included = set(batch["target_ids"]) | set(batch["readonly_ids"])
        expected = {"id": batch["id"], "source_language": "ja", "target_language": "zh-Hans",
                    "context": [{"id": cue["id"], "text": cue["text"]}
                                for cue in scenes[batch["scene_id"]]["context"] if cue["id"] in included],
                    "translate_ids": batch["target_ids"]}
        if inputs[batch["id"]] != expected:
            raise ValueError("translation run target/source context differs from frozen packing")
    loaded = {}
    raw_artifacts = [source_manifest_path, packed_mapping_path, scene_path, run_dir / "run.json", inputs_path]
    for name in ("results.jsonl", "ledger.jsonl", "schedule.jsonl"):
        path = run_dir / name
        loaded[name] = load_jsonl(path) if path.is_file() else []
        if path.is_file():
            raw_artifacts.append(path)
    aggregated = aggregate(packed, loaded["results.jsonl"], loaded["ledger.jsonl"], loaded["schedule.jsonl"])
    projected = project_windows(packed, aggregated)
    shared_transport = None
    for row in loaded["ledger.jsonl"]:
        for attempt in row.get("attempts", []):
            for key in ("original_response", "tokenize_exchange"):
                if not isinstance(attempt.get(key), str):
                    continue
                pointer = Path(attempt[key]).resolve()
                if not pointer.is_relative_to(run_dir):
                    if shared_transport is None:
                        shared_transport, session_artifacts = _session_transport(run_dir, run)
                        raw_artifacts.extend(session_artifacts)
                    if pointer.parent != shared_transport:
                        raise ValueError("raw translation response provenance escapes the verified session transport")
                raw_artifacts.extend(_trace_artifacts(pointer, key, attempt))
    raw_artifacts = list(dict.fromkeys(raw_artifacts))
    provenance = {"source_manifest": {"path": str(source_manifest_path), "sha256": source_hash},
                  "packed_mapping": {"path": str(packed_mapping_path), "sha256": packed_hash},
                  "run": str(run_dir), "candidate": run.get("candidate"), "recipe_id": packed["recipe_id"],
                  "seed": packed["seed"], "artifacts": [{"path": str(path), "sha256": sha(path)} for path in raw_artifacts]}
    if isinstance(run.get("source_preparation"), dict):
        provenance["source_preparation"] = {
            "identity": {key: deepcopy(run["source_preparation"][key]) for key in ("artifact", "batch_options")
                         if key in run["source_preparation"]},
            "relative_pointer_root": str(packed_mapping_path.parent),
            "cost_attribution": "shared preparation cost belongs to the trial ledger; not included per batch or scoring window",
        }
    output.mkdir(parents=True)
    scene_reports = []
    rendered = {}
    for sid, document in documents.items():
        safe_id(sid)
        states = aggregated["scenes"][sid]
        counts = dict(Counter(state["status"] for state in states.values()))
        complete = all(state["status"] == "delivered" for state in states.values())
        report = {"scene_id": sid, "status": "complete" if complete else "incomplete",
                  "expected_cues": len(states), "status_counts": counts,
                  "cue_states": states, "exported_srt": f"scenes/{sid}/chn.srt" if complete else None}
        sidecar = {"schema": "hy30-flow-scene-delivery-v2", **provenance, "coverage": report,
                   "source": source_provenance(document), "semantic_quality_checked": False}
        scene_diagnostics = [deepcopy(row) for row in aggregated["native_diagnostics"]
                             if row["scene_id"] == sid and any(key in row for key in
                                (*FLOW_DIAGNOSTIC_FIELDS, "source_preparation"))]
        if scene_diagnostics:
            sidecar["batch_diagnostics"] = scene_diagnostics
        if complete:
            values = {uid: state["text"] for uid, state in states.items()}
            rendered[sid] = render_srt(document, values)
            report["exported_srt_sha256"] = hashlib.sha256(rendered[sid].encode("utf-8")).hexdigest()
            sidecar["display_diagnostics"] = diagnostics(document, values)
        dump(output / "scenes" / sid / "sidecar.json", sidecar)
        scene_reports.append({key: value for key, value in report.items() if key != "cue_states"})
    for name in ("results", "ledger", "schedule", "mechanical"):
        dump_jsonl(output / f"{name}.jsonl", projected[name])
    evaluation_inputs = []
    mappings = []
    for window in packed["windows"]:
        sid = window["scene_id"]
        wid = window.get("window_id", window["id"])
        context = [{"id": cue["id"], "text": cue["text"]} for cue in scenes[sid]["context"]]
        evaluation_inputs.append({"id": wid, "source_language": "ja", "target_language": "zh-Hans",
                                  "context": context, "translate_ids": window["scored_ids"]})
        mappings.append({"window_id": wid, "scene_id": sid, "work": window.get("work", window.get("work_id")),
                         "cues": [{"eval_id": cue["id"], "source_cue_id": cue["id"]} for cue in context]})
    dump_jsonl(output / "inputs.jsonl", evaluation_inputs)
    dump_jsonl(output / "mapping.jsonl", mappings)
    dump_jsonl(output / "native-diagnostics.jsonl", aggregated["native_diagnostics"])
    dump(output / "costs.json", aggregated["costs"])
    manifest = {"schema": "hy30-flow-delivery-v2", **provenance, "scenes": scene_reports,
                "expected_windows": len(packed["windows"]), "costs": aggregated["costs"],
                "quality_status": "mechanical_only_no_semantic_judgments",
                "evaluation": "reference-free source-ID slices; evaluator-only reference/contract assembly required"}
    dump(output / "delivery.json", manifest)
    if sha(source_manifest_path) != source_hash or sha(packed_mapping_path) != packed_hash:
        raise ValueError("source/packing artifact changed before successful SRT publication")
    for sid, text in rendered.items():
        destination = output / "scenes" / sid / "chn.srt"
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=destination.parent,
                                             prefix=".chn-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return manifest
