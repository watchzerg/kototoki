"""Pure source-batch auxiliary diagnostics; no I/O, inference or primary scores.

SHA checks authenticate supplied bytes against supplied retained pointers. They
do not authenticate native server responses or establish custody chronology.
The intake caller must verify source authority and original managed-session/raw
transport provenance. Additional packets/units are views of existing generations,
not new independent samples. Only whole fixed batches receive auxiliary grades.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any

from experiments.translation_demo import adapters
from .v2_delivery import aggregate, parse_mapping
from .v2_semantic import parse_plan

SEEDS = (20261008, 20261009, 20261010)
FRAME_SCHEMA = "hy30-native-unit-span-diagnostic-frame-v1"
PACKET_SCHEMA = "p-flow-unit-span-auxiliary-packet-v1"
SEMANTIC_RECIPES = {"semantic", "semantic-anchors", "semantic-structured", "semantic-partition"}


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _pointer(value: Any) -> dict[str, str]:
    if (not isinstance(value, dict) or set(value) != {"path", "sha256"}
            or not isinstance(value["path"], str) or not value["path"].strip()
            or not isinstance(value["sha256"], str) or len(value["sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in value["sha256"])):
        raise ValueError("Expected an exact retained path/SHA256 pointer")
    return deepcopy(value)


def _artifact(value: dict[str, Any], *, lines: bool = False) -> tuple[Any, dict[str, str]]:
    if not isinstance(value, dict) or set(value) != {"identity", "content"} or type(value["content"]) is not bytes:
        raise ValueError("Retained artifacts require original bytes and their frozen identity")
    identity = _pointer(value["identity"])
    if hashlib.sha256(value["content"]).hexdigest() != identity["sha256"]:
        raise ValueError("Supplied artifact bytes differ from retained SHA256")
    text = value["content"].decode("utf-8-sig")
    result = [adapters.strict_json(line) for line in text.splitlines()] if lines else adapters.strict_json(text)
    return result, identity


def _ids(value: Any, name: str, *, nonempty: bool = True) -> list[str]:
    if (not isinstance(value, list) or (nonempty and not value)
            or any(not isinstance(x, str) or not x.strip() for x in value)
            or len(set(value)) != len(value)):
        raise ValueError(f"{name} requires unique explicit ordered IDs")
    return value


def _index(rows: Any, key: str) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Expected object rows")
    keys = _ids([row.get(key) for row in rows], key, nonempty=False)
    return dict(zip(keys, rows, strict=True))


def _no_output_or_reference(value: Any, parent: str = "") -> None:
    forbidden = {"original_zh", "reference", "references", "reference_units", "reference_text",
                 "translations", "native_unit_translations", "semantic_plan", "source_span_to_target_span"}
    if isinstance(value, dict):
        if forbidden & value.keys():
            raise ValueError("The selection frame must contain source only, before outputs/references")
        for key, child in value.items():
            if key == "zh" and not (parent == "source_events" and isinstance(child, list)):
                raise ValueError("Chinese reference text cannot enter the source frame")
            _no_output_or_reference(child, key)
    elif isinstance(value, list):
        for child in value:
            _no_output_or_reference(child, parent)


def _source(packed: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(packed, dict) or packed.get("schema") != "hy30-flow-packed-v2":
        raise ValueError("Expected source-packed v2 geometry")
    _no_output_or_reference(packed)
    if packed.get("split") not in {"screen-a", "screen-b", "screening"}:
        raise ValueError("This helper freezes screening source diagnostics, not confirmation")
    if type(packed.get("seed")) is not int or packed["seed"] not in SEEDS:
        raise ValueError("Source packing requires a declared frozen generation seed")
    scenes = _index(packed.get("scenes"), "id")
    windows = _index(packed.get("windows"), "id")
    batches = _index(packed.get("batches"), "id")
    if not scenes or not windows or not batches or packed.get("scene_ids") != list(scenes):
        raise ValueError("Source scene/batch/window order must be explicit")
    checked_scenes, checked_batches, checked_windows = {}, [], {}
    for sid, scene in scenes.items():
        if scene.get("scene_id", sid) != sid:
            raise ValueError("Conflicting source scene identity")
        if scene.get("source_language") != "ja" or scene.get("target_language") != "zh-Hans":
            raise ValueError("Source scenes must explicitly retain Japanese-to-Simplified-Chinese scope")
        context = scene.get("context")
        cues = _index(context, "id")
        if not cues or scene.get("translate_ids") != list(cues):
            raise ValueError("Full source scene must retain all cues in source order")
        if any(not isinstance(cue.get("text"), str) or not cue["text"].strip() for cue in cues.values()):
            raise ValueError("Source cues must have nonblank Japanese text")
        if any(any(0xD800 <= ord(c) <= 0xDFFF for c in cue["text"]) for cue in cues.values()):
            raise ValueError("Source text contains an invalid Unicode surrogate")
        checked_scenes[sid] = {"context": [{"id": key, "text": cue["text"]} for key, cue in cues.items()],
                               "times": None}
    for wid, window in windows.items():
        sid = window.get("scene_id")
        if sid not in checked_scenes:
            raise ValueError("Scoring window has unknown source scene")
        order = [cue["id"] for cue in checked_scenes[sid]["context"]]
        scored = _ids(window.get("scored_ids"), "scored source IDs")
        if not set(scored) <= set(order) or [key for key in order if key in scored] != scored:
            raise ValueError("Scoring IDs must be ordered source IDs")
        timing = _index(window.get("units"), "id")
        if list(timing) != order:
            raise ValueError("Source times must cover the same entire frozen scene")
        times = []
        for uid, unit in timing.items():
            if (any(type(unit.get(key)) is not int for key in ("ja_srt_index", "start_ms", "end_ms"))
                    or unit["ja_srt_index"] <= 0 or not 0 <= unit["start_ms"] < unit["end_ms"]
                    or type(unit.get("score")) is not bool or unit["score"] != (uid in scored)):
                raise ValueError("Source timing/score identity is invalid")
            times.append({"source_id": uid, **{key: unit[key] for key in ("ja_srt_index", "start_ms", "end_ms")}})
            original = next(cue for cue in scenes[sid]["context"] if cue["id"] == uid)
            if any(key in original and (type(original[key]) not in (int, float) or original[key] != unit[field] / 1000)
                   for key, field in (("start", "start_ms"), ("end", "end_ms"))):
                raise ValueError("Scene Japanese cue times disagree with frozen source units")
        if [row["ja_srt_index"] for row in times] != sorted({row["ja_srt_index"] for row in times}):
            raise ValueError("Source SRT indices must be unique and in source order")
        known = checked_scenes[sid]["times"]
        if known is not None and known != times:
            raise ValueError("Windows disagree on full-scene source timing")
        checked_scenes[sid]["times"] = times
        metadata = {key: deepcopy(window[key]) for key in
            ("work", "work_id", "category", "series_cluster", "episode_id", "split", "selection_type") if key in window}
        checked_windows[wid] = {"scene_id": sid, "scored_ids": scored, "metadata": metadata}
    coverage = {sid: [] for sid in scenes}
    for bid, batch in batches.items():
        sid = batch.get("scene_id")
        if sid not in checked_scenes or checked_scenes[sid]["times"] is None:
            raise ValueError("Batch source scope has no frozen scene timing")
        context = checked_scenes[sid]["context"]
        order = [cue["id"] for cue in context]
        target = _ids(batch.get("target_ids"), "target source IDs")
        readonly = _ids(batch.get("readonly_ids"), "readonly source IDs", nonempty=False)
        if not set(target + readonly) <= set(order) or set(target) & set(readonly):
            raise ValueError("Batch source membership is invalid")
        positions = [order.index(uid) for uid in target]
        if positions != list(range(positions[0], positions[0] + len(target))):
            raise ValueError("Batch targets must form an ordered contiguous source span")
        coverage[sid].extend(target)
        producer = {"id": bid, "source_language": "ja", "target_language": "zh-Hans",
            "context": [deepcopy(cue) for cue in context if cue["id"] in target + readonly], "translate_ids": target}
        adapters.validate_window(producer)
        checked_batches.append({"batch_id": bid, "scene_id": sid, "source_ids": target,
                                "producer_input": producer})
    if any(coverage[sid] != [cue["id"] for cue in checked_scenes[sid]["context"]] for sid in scenes):
        raise ValueError("Packed batches must cover each complete scene exactly once in order")
    return {"manifest": _pointer(packed.get("source_manifest")), "scenes_identity": _pointer(packed.get("source_scenes")),
            "packing": deepcopy(packed.get("packing")), "scenes": checked_scenes,
            "windows": checked_windows, "batches": checked_batches}


def freeze_frame(packed_content: bytes, packed_identity: dict[str, str], selected_window_ids: list[str], *,
                 source_authority: dict[str, dict[str, str]]) -> dict[str, Any]:
    """Select source intersections before any outputs; caller registers frame hash."""
    packed, identity = _artifact({"content": packed_content, "identity": packed_identity})
    source = _source(packed)
    selection = _ids(selected_window_ids, "preregistered window IDs")
    if len(selection) not in (48, 96) or not set(selection) <= set(source["windows"]):
        raise ValueError("Screening diagnostics require exactly the preregistered scored48/96 selection")
    if not isinstance(source_authority, dict) or set(source_authority) != {"manifest", "scenes", "freeze"}:
        raise ValueError("Explicit externally accepted source authority is required")
    authority = {key: _pointer(value) for key, value in source_authority.items()}
    if authority["manifest"] != source["manifest"] or authority["scenes"] != source["scenes_identity"]:
        raise ValueError("Source packing changes the externally accepted authority")
    selected = []
    for batch in source["batches"]:
        hits = [wid for wid in selection if source["windows"][wid]["scene_id"] == batch["scene_id"]
                and set(source["windows"][wid]["scored_ids"]) & set(batch["source_ids"])]
        if hits:
            selected.append({**deepcopy(batch), "intersecting_window_ids": hits})
    if not selected:
        raise ValueError("The fixed screening frame cannot be empty")
    slots = [{"batch_id": batch["batch_id"], "scene_id": batch["scene_id"], "seed": seed,
              "expected_source_ids": list(batch["source_ids"])} for seed in SEEDS for batch in selected]
    return {"schema": FRAME_SCHEMA, "role": "screening_source_span_auxiliary", "packed_identity": identity,
        "source_authority": authority, "source_geometry": source,
        "source_geometry_sha256": canonical_sha256(source), "selected_window_ids": selection,
        "batches": selected, "generation_seeds": list(SEEDS), "expected_slots": slots,
        "selection_basis": "source_batch_intersection_before_outputs_units_or_grades",
        "primary_endpoint_changed": False, "new_independent_samples": False,
        "source_authority_verified_by_this_helper": False}


def _frame(frame: dict[str, Any], expected: str) -> dict[str, Any]:
    if canonical_sha256(frame) != expected or frame.get("schema") != FRAME_SCHEMA:
        raise ValueError("Frame differs from the externally registered pre-quality hash")
    return frame


def _intake(frame: dict[str, Any], seed: int, retained: dict[str, Any], *, control: bool = False) -> dict[str, Any]:
    required = {"packed", "run", "inputs", "ledger", "results", "schedule"}
    if not isinstance(retained, dict) or set(retained) != required:
        raise ValueError("Retained intake requires all six exact-byte artifacts, including empty JSONL files")
    data, pointers = {}, {}
    for key in required:
        data[key], pointers[key] = _artifact(retained[key], lines=key in {"inputs", "ledger", "results", "schedule"})
    source = _source(data["packed"])
    if (source["manifest"] != frame["source_authority"]["manifest"]
            or source["scenes_identity"] != frame["source_authority"]["scenes"]
            or (not control and canonical_sha256(source) != frame["source_geometry_sha256"])):
        raise ValueError("Retained generation source geometry differs from the fixed frame")
    run = data["run"]
    settings = run.get("settings", {})
    recipe = run.get("recipe")
    if (run.get("schema") != "hy30-flow-session-v2" or run.get("phase") != "translation" or run.get("lane") != "P-flow"
            or type(settings.get("seed")) is not int or settings["seed"] != seed
            or data["packed"]["seed"] != seed
            or run.get("packed_mapping_sha256") != pointers["packed"]["sha256"]
            or run.get("source_manifest_sha256") != source["manifest"]["sha256"]
            or run.get("input_sha256") != pointers["inputs"]["sha256"]
            or run.get("expected_window_ids") != [batch["batch_id"] for batch in source["batches"]]
            or (recipe != "c0" if control else recipe not in SEMANTIC_RECIPES)):
        raise ValueError("Retained generation run/seed/source identity is inconsistent")
    if data["inputs"] != [batch["producer_input"] for batch in source["batches"]]:
        raise ValueError("Retained producer inputs differ from the frozen source context/targets")
    rows = {key: _index(data[key], "id" if key == "results" else "window_id")
            for key in ("results", "ledger", "schedule")}
    batch_ids = {batch["batch_id"] for batch in source["batches"]}
    if any(set(index) - batch_ids for index in rows.values()) or set(rows["results"]) & set(rows["schedule"]):
        raise ValueError("Retained rows contain unknown or conflicting generation batches")
    targets = {batch["batch_id"]: batch["source_ids"] for batch in source["batches"]}
    for bid, terminal in rows["ledger"].items():
        if (terminal.get("recipe", recipe) != recipe
                or "scored_ids" in terminal and terminal["scored_ids"] != targets[bid]):
            raise ValueError("Terminal recipe/source identity differs from original generation")
    for bid, predicted in rows["results"].items():
        terminal = rows["ledger"].get(bid)
        if (terminal is None or predicted.get("status", terminal.get("status")) != terminal.get("status")
                or predicted.get("translations") != terminal.get("translations")):
            raise ValueError("Original result and terminal status/text disagree")
    return {"data": data, "pointers": pointers, "source": source, **rows}


def _boundary(frame: dict[str, Any], batch: dict[str, Any], units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for unit in units:
        ids = set(unit["source_ids"])
        hits = [wid for wid in batch["intersecting_window_ids"]
                if ids & set(frame["source_geometry"]["windows"][wid]["scored_ids"])]
        contained = len(hits) == 1 and ids <= set(frame["source_geometry"]["windows"][hits[0]]["scored_ids"])
        result.append({"unit_id": unit["id"], "intersecting_window_ids": hits,
            "window_native_semantic": None,
            "window_attribution": "contained_auxiliary_only" if contained else "boundary_unknown"})
    return result


def _packet(frame: dict[str, Any], batch: dict[str, Any], seed: int, phase: str,
            groups: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema": PACKET_SCHEMA, "phase": phase, "batch_id": batch["batch_id"], "seed": seed,
        "target_source_ids": list(batch["source_ids"]),
        "source_context": deepcopy(frame["source_geometry"]["scenes"][batch["scene_id"]]["context"]),
        "output_groups": deepcopy(groups), "scope": "full_fixed_source_batch_auxiliary_only"}


def build_packets(frame: dict[str, Any], *, expected_frame_sha256: str, batch_id: str, seed: int,
                  retained: dict[str, Any] | None = None,
                  c0_retained: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build intact native and attribution views, preserving every failed slot."""
    _frame(frame, expected_frame_sha256)
    if type(seed) is not int or not any(row["batch_id"] == batch_id and row["seed"] == seed for row in frame["expected_slots"]):
        raise ValueError("Diagnostic job is not a fixed pre-quality batch/seed slot")
    batch = next(row for row in frame["batches"] if row["batch_id"] == batch_id)
    result = {"batch_id": batch_id, "seed": seed, "expected_source_ids": list(batch["source_ids"]),
        "status": "missing", "native_state": "unknown_no_retained_native_evidence", "attribution_state": "not_available",
        "planned_unit_count": None, "native_packet": None, "attribution_packet": None,
        "c0_packet": None, "c0_state": "missing", "boundary_diagnostics": [], "provenance": {},
        "retained_inputs_validated": False, "native_protocol_validated": False,
        "attribution_protocol_validated": False, "protocol_validated": False, "actual_native_authenticated": False,
        "native_authentication_requirement": "custodian_original_session_raw_transport_and_source_authority",
        "primary_score_changed": False, "new_independent_samples": False}
    if retained is not None:
        intake = _intake(frame, seed, retained)
        result["retained_inputs_validated"] = True
        result["provenance"]["candidate"] = intake["pointers"]
        terminal, predicted, schedule = (intake[key].get(batch_id) for key in ("ledger", "results", "schedule"))
        row = schedule or terminal
        if row is not None:
            status = row.get("status")
            if status not in {"delivered", "translation_failed", "mapping_unjudgeable", "not_run", "setup_failed"}:
                raise ValueError("Retained terminal status is unknown")
            if (schedule and terminal and terminal.get("status") != status) or (status != "delivered" and not row.get("reason")):
                raise ValueError("Nonexecution/failure needs an explicit consistent reason")
            result["status"] = status
            result["reason"] = row.get("reason")
            result["failure_stage"] = row.get("failure_stage")
            if status in {"not_run", "setup_failed"}:
                result["native_state"] = "explicitly_not_run"
            elif row.get("failure_stage") == "source-planning":
                result["native_state"] = "planning_failed_no_valid_units"
            elif row.get("failure_stage") == "joint-unit-translation":
                result["native_state"] = "native_translation_failed"
            if status in {"not_run", "setup_failed"} and terminal and any(
                    terminal.get(key) is not None for key in ("semantic_plan", "native_unit_translations")):
                raise ValueError("Unexecuted slots cannot claim produced native units")
        elif predicted:
            raise ValueError("A retained result cannot replace missing terminal provenance")
        if terminal and terminal.get("semantic_plan") is not None:
            plan = parse_plan(json.dumps(terminal["semantic_plan"], ensure_ascii=False), batch["producer_input"])
            result["planned_unit_count"] = len(plan["units"])
            result["boundary_diagnostics"] = _boundary(frame, batch, plan["units"])
            native_value = terminal.get("native_unit_translations")
            if native_value is not None:
                try:
                    native = adapters.translations(json.dumps({"translations": native_value}, ensure_ascii=False),
                                                   [unit["id"] for unit in plan["units"]])
                    if any(any(0xD800 <= ord(c) <= 0xDFFF for c in text) for text in native.values()):
                        raise ValueError("Invalid native Unicode surrogate")
                except ValueError:
                    result["native_state"] = "invalid_or_empty_native"
                else:
                    groups = [{"group_id": unit["id"], "source_ids": list(unit["source_ids"]),
                        "text": native[unit["id"]], "evidence_ids": list(unit["evidence_ids"]),
                        "uncertain": unit["uncertain"]} for unit in plan["units"]]
                    result["native_packet"] = _packet(frame, batch, seed, "native_fidelity", groups)
                    result["native_state"] = "available_intact"
                    result["native_protocol_validated"] = True
                    if result["status"] == "delivered":
                        try:
                            spans = terminal.get("source_span_to_target_span")
                            if not isinstance(spans, list):
                                raise ValueError("No exact native partition retained")
                            segments = []
                            for span in spans:
                                if (not isinstance(span, dict) or set(span) != {"unit_id", "source_ids", "target_spans"}
                                        or len(span["source_ids"]) != 1 or len(span["target_spans"]) != 1
                                        or len(span["target_spans"][0]) != 2):
                                    raise ValueError("Invalid retained native source/target span")
                                start, end = span["target_spans"][0]
                                segments.append({"unit_id": span["unit_id"], "source_id": span["source_ids"][0], "start": start, "end": end})
                            checked = parse_mapping(json.dumps({"segments": segments}), batch["producer_input"], plan, native)
                            if (predicted is None or predicted.get("status", "delivered") != "delivered"
                                    or terminal.get("scored_ids") != batch["source_ids"]
                                    or terminal.get("translations") != checked["translations"]
                                    or predicted.get("translations") != checked["translations"]):
                                raise ValueError("Final cue outputs differ from the unchanged native partition")
                        except (ValueError, KeyError, TypeError) as exc:
                            result["attribution_state"] = "invalid_partition_or_final_delivery"
                            result["attribution_reason"] = str(exc)
                        else:
                            packet = _packet(frame, batch, seed, "cue_attribution", groups)
                            times = {row["source_id"]: row for row in frame["source_geometry"]["scenes"][batch["scene_id"]]["times"]}
                            packet["mapped_cues"] = [{"group_id": span["unit_id"], "source_id": span["source_ids"][0],
                                "target_span": span["target_spans"][0], "text": checked["translations"][span["source_ids"][0]],
                                **deepcopy(times[span["source_ids"][0]])} for span in checked["source_span_to_target_span"]]
                            result["attribution_packet"] = packet
                            result["attribution_state"] = "available_exact_partition_not_semantic_pass"
                            result["attribution_protocol_validated"] = True
                            result["protocol_validated"] = True
            elif result["status"] == "delivered":
                result["native_state"] = "delivered_without_retained_native"
        elif terminal and terminal.get("native_unit_translations") is not None:
            raise ValueError("Native unit text without its original source-only plan is unauthenticated")
        elif terminal and result["status"] == "delivered":
            result["native_state"] = "delivered_without_retained_source_plan"
    if c0_retained is not None:
        control = _intake(frame, seed, c0_retained, control=True)
        result["provenance"]["c0"] = control["pointers"]
        if control["source"]["scenes"].get(batch["scene_id"]) != frame["source_geometry"]["scenes"][batch["scene_id"]]:
            raise ValueError("C0 control must retain the identical full Japanese scene and source times")
        if any(any(key in row for key in ("semantic_plan", "native_unit_translations")) for row in control["ledger"].values()):
            raise ValueError("C0 cue-output control cannot be relabeled as native joint generation")
        states = aggregate(control["data"]["packed"], control["data"]["results"], control["data"]["ledger"],
                           control["data"]["schedule"])["scenes"][batch["scene_id"]]
        if all(states[uid]["status"] == "delivered" for uid in batch["source_ids"]):
            groups = [{"group_id": f"cue-{uid}", "source_ids": [uid], "text": states[uid]["text"],
                       "evidence_ids": [uid], "uncertain": None} for uid in batch["source_ids"]]
            result["c0_packet"] = _packet(frame, batch, seed, "native_fidelity", groups)
            result["c0_state"] = "whole_fixed_batch_original_cue_output_control_not_joint_generation"
        else:
            result["c0_state"] = "incomplete_whole_batch_control"
    return result


def response_schema(packet: dict[str, Any]) -> dict[str, Any]:
    """Portable JSON schema; duplicate IDs and exact quotes are checked locally."""
    if packet.get("schema") != PACKET_SCHEMA or packet.get("phase") not in {"native_fidelity", "cue_attribution"}:
        raise ValueError("Unknown auxiliary packet phase")
    properties = {"packet_sha256": {"type": "string", "const": canonical_sha256(packet)},
        "assessment": {"type": "string", "enum": ["assessable", "unresolved"] if packet["phase"] == "native_fidelity"
                       else ["supported", "misattributed", "unresolved"]},
        "reason": {"type": "string"}, "errors": {"type": "array", "items": {"type": "object",
            "additionalProperties": False, "required": ["root_id", "group_id", "source_ids", "severity", "source_evidence", "target_evidence", "explanation"],
            "properties": {"root_id": {"type": "string"}, "group_id": {"type": "string"},
                "source_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "severity": {"type": "string", "enum": ["minor", "major", "critical", "unknown"]},
                "explanation": {"type": "string"},
                "source_evidence": {"type": "array", "minItems": 1, "items": {"type": "object",
                    "additionalProperties": False, "required": ["source_id", "quote"],
                    "properties": {"source_id": {"type": "string"}, "quote": {"type": "string"}}}},
                "target_evidence": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                    "required": ["start", "end", "quote"], "properties": {"start": {"type": "integer"},
                    "end": {"type": "integer"}, "quote": {"type": "string"}}}}}}}}
    if packet["phase"] == "native_fidelity":
        properties["native_semantic"] = {"type": ["integer", "null"], "minimum": 0, "maximum": 4}
    return {"type": "object", "additionalProperties": False, "required": list(properties), "properties": properties}


def parse_response(content: str, packet: dict[str, Any]) -> dict[str, Any]:
    """Validate evidence binding, not bilingual truth or attribution correctness."""
    if packet.get("schema") != PACKET_SCHEMA or packet.get("phase") not in {"native_fidelity", "cue_attribution"}:
        raise ValueError("Expected a separate native-fidelity or cue-attribution packet")
    obj = adapters.strict_json(content)
    schema = response_schema(packet)
    if not isinstance(obj, dict) or set(obj) != set(schema["required"]) or obj["packet_sha256"] != canonical_sha256(packet):
        raise ValueError("Response must bind the exact auxiliary packet and envelope")
    if obj["assessment"] not in schema["properties"]["assessment"]["enum"] or not isinstance(obj["reason"], str):
        raise ValueError("Invalid explicit auxiliary assessment")
    if obj["assessment"] == "unresolved" and not obj["reason"].strip():
        raise ValueError("Unresolved evidence must preserve its reason")
    if packet["phase"] == "native_fidelity":
        score = obj["native_semantic"]
        if (obj["assessment"] == "unresolved" and score is not None
                or obj["assessment"] == "assessable" and (type(score) is not int or not 0 <= score <= 4)):
            raise ValueError("Only assessed whole-batch native fidelity can receive an auxiliary 0–4 score")
    errors = obj["errors"]
    groups = _index(packet["output_groups"], "group_id")
    source = _index(packet["source_context"], "id")
    if not isinstance(errors, list):
        raise ValueError("Expected explicit auxiliary root-evidence list")
    if obj["assessment"] == "misattributed" and not errors:
        raise ValueError("Misattribution needs explicit source-grounded error evidence")
    _ids([error.get("root_id") if isinstance(error, dict) else None for error in errors], "root IDs", nonempty=False)
    required = set(schema["properties"]["errors"]["items"]["required"])
    for error in errors:
        if (set(error) != required or error["group_id"] not in groups
                or error["severity"] not in {"minor", "major", "critical", "unknown"}
                or not isinstance(error["explanation"], str) or not error["explanation"].strip()):
            raise ValueError("Invalid auxiliary error fields/severity/group")
        ids = _ids(error["source_ids"], "error source IDs")
        group = groups[error["group_id"]]
        if not set(ids) <= set(group["source_ids"]):
            raise ValueError("Unit evidence cannot silently grade another candidate-defined source scope")
        quotes = error["source_evidence"]
        if not isinstance(quotes, list) or not quotes:
            raise ValueError("Source-grounded evidence needs supplied Japanese quotes")
        _ids([q.get("source_id") if isinstance(q, dict) else None for q in quotes], "quoted source IDs")
        if not any(quote["source_id"] in ids for quote in quotes):
            raise ValueError("Error evidence must quote its asserted target source scope")
        for quote in quotes:
            if (set(quote) != {"source_id", "quote"} or quote["source_id"] not in source
                    or not isinstance(quote["quote"], str) or not quote["quote"].strip()
                    or quote["quote"] not in source[quote["source_id"]]["text"]):
                raise ValueError("Source quote must be an exact visible Japanese substring")
        spans = error["target_evidence"]
        if not isinstance(spans, list):
            raise ValueError("Target evidence uses exact unit-local codepoint spans")
        if packet["phase"] == "cue_attribution" and obj["assessment"] == "misattributed" and not spans:
            raise ValueError("Misattribution needs retained native text/span evidence")
        seen = set()
        for span in spans:
            if (not isinstance(span, dict) or set(span) != {"start", "end", "quote"}
                    or type(span["start"]) is not int or type(span["end"]) is not int
                    or not 0 <= span["start"] < span["end"] <= len(group["text"])
                    or not isinstance(span["quote"], str) or not span["quote"].strip()
                    or group["text"][span["start"]:span["end"]] != span["quote"]):
                raise ValueError("Native quote must match an exact unit-local Unicode codepoint span")
            key = (span["start"], span["end"])
            if key in seen:
                raise ValueError("Repeated target evidence span")
            seen.add(key)
    return {**deepcopy(obj), "response_protocol_validated": True, "semantic_accuracy_verified": False,
            "primary_score_changed": False, "new_independent_samples": False}
