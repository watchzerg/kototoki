"""Evaluation-only, scene-scoped P-flow adapter; never repairs translations.

The fixed-window evaluator owns judgment, review and aggregation. This adapter
validates a separate full-scene contract before reusing its per-ID preparation
core. Internal normalized serialization is temporary; published originals,
packets, manifests and expected rows retain the actual P-flow lane and hashes.
References are read only by this evaluator process, never by source preparation.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
import shutil
import tempfile
from typing import Any

from experiments.translation_eval import runner
from .srt import read_srt
from .v2_delivery import aggregate, project_windows

SCENE_CONTRACT = "p-flow-full-scene-source-id-preserved-v2"
SCOPE = "frozen-full-scene-japanese"
REFERENCE_VERSION = "hy30-flow-v2-reference-v1"


def identity(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": runner.sha(path)}


def checked_pointer(value: Any, root: Path) -> Path:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise ValueError("artifact requires path and SHA256")
    path = Path(value["path"])
    path = path.resolve() if path.is_absolute() else (root / path).resolve()
    if runner.sha(path) != value.get("sha256"):
        raise ValueError("frozen artifact hash changed")
    return path


def reference_freeze(path: Path, references: Path) -> dict[str, Any]:
    """Check the successful evaluator-owned freeze without logging its contents."""
    frozen = runner.read_json(path)
    if (frozen.get("state") != "frozen_double_fresh_reference_review"
            or frozen.get("inference_allowed") is not True
            or frozen.get("corpus_version") != REFERENCE_VERSION):
        raise ValueError("references lack a successful double-fresh-review freeze")
    files = frozen.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("reference freeze requires artifact hashes")
    seen = set()
    for value in files:
        artifact = checked_pointer(value, path.parent)
        if not artifact.is_relative_to(path.parent.resolve()) or artifact in seen:
            raise ValueError("reference freeze has duplicate or escaping artifact paths")
        seen.add(artifact)
    if references.resolve() not in seen:
        raise ValueError("reference windows are not part of the successful freeze")
    return {**identity(path), "corpus_version": frozen["corpus_version"],
            "state": frozen["state"]}


def source_contract(
    manifest_path: Path, inputs_path: Path, references_path: Path,
    freeze_path: Path, window_ids: list[str] | None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Bind IDs, times, Japanese text and provenance to immutable full scenes."""
    freeze = reference_freeze(freeze_path, references_path)
    source_freeze_path = manifest_path.parent / "freeze-manifest.json"
    source_freeze = runner.read_json(source_freeze_path)
    accepted = source_freeze.get("reference_qualification")
    if (source_freeze.get("state") != "source_frozen_reference_qualified"
            or not isinstance(accepted, dict)
            or not isinstance(accepted.get("path"), str)
            or not Path(accepted["path"]).is_absolute()
            or Path(accepted["path"]).resolve() != freeze_path.resolve()
            or accepted.get("sha256") != freeze["sha256"]
            or accepted.get("version") != freeze["corpus_version"]
            or accepted.get("state") != freeze["state"]
            or accepted.get("inference_allowed") is not True):
        raise ValueError("reference freeze identity differs from accepted source qualification")
    manifest = runner.read_json(manifest_path)
    windows = runner.indexed(manifest["windows"])
    all_requests = runner.indexed(runner.load_jsonl(inputs_path))
    refs = runner.indexed(runner.load_jsonl(references_path))
    selected = list(all_requests) if window_ids is None else window_ids
    if (not selected or len(selected) != len(set(selected))
            or not set(selected) <= set(all_requests) & set(windows) & set(refs)):
        raise ValueError("explicit evaluation selection does not match frozen source/reference IDs")
    requests = {wid: all_requests[wid] for wid in selected}
    source_root = Path(manifest["external_corpus"])
    if not source_root.is_absolute():
        source_root = manifest_path.parent / source_root
    scopes, mappings, documents, event_tracks = {}, {}, {}, {}
    for wid, request in requests.items():
        runner.safe_id(wid)
        window, ref = windows[wid], refs[wid]
        sid = runner.safe_id(window["scene_id"])
        context, units = runner.indexed(request["context"]), runner.indexed(window["units"])
        reference_units = runner.indexed(ref["units"])
        ids = request["translate_ids"]
        if (set(request) != {"id", "source_language", "target_language", "context", "translate_ids"}
                or request["source_language"] != "ja" or request["target_language"] != "zh-Hans"
                or any(set(cue) != {"id", "text"} for cue in request["context"])
                or not ids or len(ids) != len(set(ids)) or ids != window["scored_ids"]
                or ids != ref["scored_ids"] or not set(ids) <= set(context)
                or set(context) != set(units) or set(context) != set(reference_units)
                or [uid for uid in context if uid in ids] != ids
                or ref.get("work") != window["work"]
                or ref.get("category") != window["category"]
                or ref.get("category") not in runner.CATEGORY_MAP
                or {uid for uid, unit in reference_units.items() if unit.get("score") is True} != set(ids)
                or any(type(unit.get("score")) is not bool for unit in reference_units.values())
                or {uid for uid, unit in units.items() if unit.get("score") is True} != set(ids)
                or any(context[uid]["text"] != reference_units[uid].get("ja") for uid in context)
                or any(not isinstance(reference_units[uid].get("zh"), str)
                       or not reference_units[uid]["zh"].strip() for uid in ids)):
            raise ValueError(f"full-scene source/reference scope disagreement: {wid}")
        source = checked_pointer({"path": window["source_srt"],
                                  "sha256": window["source_srt_sha256"]}, source_root)
        event_map = checked_pointer({"path": window["source_mapping"],
                                     "sha256": window["source_mapping_sha256"]}, source_root)
        if source not in documents:
            documents[source] = read_srt(source)
        if event_map not in event_tracks:
            provenance = runner.read_json(event_map)
            if provenance.get("源SHA256") != window["source_sha256"]:
                raise ValueError("source event map original source hash disagreement")
            track = provenance.get("语言轨", {}).get("ja")
            if not isinstance(track, list) or not track:
                raise ValueError("source event map requires its explicit Japanese track")
            event_tracks[event_map] = runner.indexed(track, "SRT序号")
        original = {cue.index: cue for cue in documents[source].cues}
        previous, mapping = 0, []
        for uid, item in context.items():
            unit = units[uid]
            cue = original.get(unit.get("ja_srt_index"))
            event = event_tracks[event_map].get(unit.get("ja_srt_index"), {})
            if (cue is None or cue.ordinal <= previous or cue.text != item["text"]
                    or any(unit.get(name) != getattr(cue, name) for name in (
                        "start_ms", "end_ms", "index_text", "time_line"))
                    or unit.get("start") != cue.start_ms / 1000
                    or unit.get("end") != cue.end_ms / 1000
                    or not isinstance(unit.get("source_events", {}).get("ja"), list)
                    or not unit["source_events"]["ja"]
                    or event.get("源事件") != unit["source_events"]["ja"]
                    or event.get("开始毫秒") != cue.start_ms or event.get("结束毫秒") != cue.end_ms
                    or event.get("文本") != cue.text):
                raise ValueError(f"source cue identity/text/time/provenance disagreement: {wid}")
            previous = cue.ordinal
            mapping.append({"eval_id": uid, "source_cue_id": uid,
                            "ja_srt_index": cue.index, "start_ms": cue.start_ms,
                            "end_ms": cue.end_ms, "source_events": deepcopy(unit["source_events"]["ja"])})
        if ([units[uid]["ja_srt_index"] for uid in context] != list(range(
                window["visible_start_index"], window["visible_end_index"] + 1))):
            raise ValueError("full scene differs from frozen visible source boundaries")
        scope = {"scene_id": sid, "work": window["work"], "episode_id": window.get("episode_id"),
                 "scope": SCOPE, "source": identity(source), "source_mapping": identity(event_map),
                 "source_sha256": window["source_sha256"],
                 "source_ids": list(context), "context": request["context"],
                 "visible_start_index": window["visible_start_index"],
                 "visible_end_index": window["visible_end_index"]}
        if sid in scopes and scopes[sid] != scope:
            raise ValueError("windows in one scene disagree on fixed full-scene Japanese scope")
        scopes[sid] = scope
        mappings[wid] = {"window_id": wid, "scene_id": sid, "work": window["work"], "cues": mapping}
    contract = {"schema": SCENE_CONTRACT, "lane": "P-flow",
                "delivery_contract": runner.P_FLOW_CONTRACT, "judge_source_scope": SCOPE,
                "source_manifest": identity(manifest_path), "source_inputs": identity(inputs_path),
                "references": identity(references_path), "reference_freeze": freeze,
                "source_qualification_freeze": identity(source_freeze_path),
                "window_ids": selected, "allowed_source_scope": list(scopes.values()),
                "window_mapping": mappings}
    return contract, requests, {wid: refs[wid] for wid in selected}


def prepare(
    source_manifest_path: Path, source_inputs_path: Path, references_path: Path,
    candidate_deliveries: dict[str, Path], output: Path, *, reference_freeze_path: Path,
    split: str = "dev", window_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Freeze candidate-independent P-flow packets with explicit unresolved states.

    Candidate directories are the source-only ``v2_delivery.deliver`` outputs.
    All candidates must cover precisely the explicit frozen window selection.
    Missing and unresolved deliveries stay in the expected denominator.
    """
    if output.exists():
        raise FileExistsError("evaluation output must be a new directory")
    if not candidate_deliveries:
        raise ValueError("evaluation needs at least one candidate")
    contract, requests, refs = source_contract(source_manifest_path, source_inputs_path,
                                             references_path, reference_freeze_path, window_ids)
    all_source_requests = runner.indexed(runner.load_jsonl(source_inputs_path))
    source_windows = runner.indexed(runner.read_json(source_manifest_path)["windows"])
    candidate_meta = {}
    derivation_validator = None
    for alias, directory in candidate_deliveries.items():
        runner.safe_id(alias)
        delivery_path = directory / "delivery.json"
        delivery = runner.read_json(delivery_path)
        if (delivery.get("schema") != "hy30-flow-delivery-v2"
                or checked_pointer(delivery["source_manifest"], directory) != source_manifest_path.resolve()):
            raise ValueError("delivery source manifest differs from frozen scoring authority")
        if "derivation" in delivery:
            from . import v2_reproject
            v2_reproject.validate_derivation(delivery, directory)
            derivation_validator = identity(Path(v2_reproject.__file__))
        artifacts = [identity(delivery_path)]
        if not isinstance(delivery.get("artifacts"), list) or not delivery["artifacts"]:
            raise ValueError("candidate requires immutable raw artifact provenance")
        for pointer in delivery["artifacts"]:
            artifacts.append(identity(checked_pointer(pointer, directory)))
        packed_path = checked_pointer(delivery["packed_mapping"], directory)
        packed = runner.read_json(packed_path)
        if (packed.get("schema") != "hy30-flow-packed-v2"
                or checked_pointer(packed["source_manifest"], packed_path.parent) != source_manifest_path.resolve()
                or packed.get("recipe_id") != delivery.get("recipe_id")
                or packed.get("seed") != delivery.get("seed")
                or not set(requests) <= {row["id"] for row in packed["windows"]}
                or not {row["id"] for row in packed["windows"]} <= set(all_source_requests)):
            raise ValueError("candidate packing differs from frozen selected source identity")
        if any(row != source_windows[row["id"]] for row in packed["windows"]):
            raise ValueError("candidate packed scoring IDs differ from final frozen source selection")
        original_run = Path(delivery["run"])
        if not original_run.is_absolute():
            original_run = directory / original_run
        recorded_paths = {Path(item["path"]).resolve() for item in artifacts}
        raw_rows = {}
        for name in ("results", "ledger", "schedule"):
            raw = original_run / f"{name}.jsonl"
            if raw.is_file() and raw.resolve() not in recorded_paths:
                raise ValueError("candidate raw delivery lacks its frozen artifact hash")
            raw_rows[name] = runner.load_jsonl(raw) if raw.is_file() else []
        projected = project_windows(packed, aggregate(packed, raw_rows["results"], raw_rows["ledger"], raw_rows["schedule"]))
        for name in ("results", "ledger", "schedule"):
            if runner.load_jsonl(directory / f"{name}.jsonl") != projected[name]:
                raise ValueError("candidate scoring projection differs from untouched original delivery")
        delivered_inputs = runner.indexed(runner.load_jsonl(directory / "inputs.jsonl"))
        packed_ids = {row["id"] for row in packed["windows"]}
        if delivered_inputs != {wid: all_source_requests[wid] for wid in packed_ids}:
            raise ValueError("candidate judge inputs differ from fixed full-scene Japanese scope")
        mapping = runner.indexed(runner.load_jsonl(directory / "mapping.jsonl"), "window_id")
        if set(mapping) != packed_ids:
            raise ValueError("candidate mapping must preserve every frozen window")
        for wid in packed_ids:
            expected = source_windows[wid]
            row = mapping[wid]
            projection = [{"eval_id": cue["id"], "source_cue_id": cue["id"]}
                          for cue in all_source_requests[wid]["context"]]
            if (row.get("scene_id") != expected["scene_id"] or row.get("work") != expected["work"]
                    or row.get("cues") != projection):
                raise ValueError("candidate mapping differs from exact ordered source cue identities")
        for name in ("inputs.jsonl", "mapping.jsonl", "results.jsonl", "ledger.jsonl", "schedule.jsonl"):
            path = directory / name
            if not path.is_file():
                raise ValueError("candidate delivery lacks a required provenance artifact")
            artifacts.append(identity(path))
            if name in {"results.jsonl", "ledger.jsonl"}:
                for row in runner.load_jsonl(path):
                    if (row.get("delivery_contract") != runner.P_FLOW_CONTRACT
                            or "translation_groups" in row or "mapping_groups" in row):
                        raise ValueError("P-flow scoring requires explicit per-ID delivery or unresolved status")
        candidate_meta[alias] = {"directory": str(directory.resolve()), "artifacts": artifacts,
                                 "recipe_id": delivery.get("recipe_id"), "seed": delivery.get("seed"),
                                 "delivery_window_ids": list(delivered_inputs), "evaluation_window_ids": list(requests),
                                 "original_generation_cost_identity": identity(original_run / "run.json"),
                                 "cost_attribution": "original_run_once"}
        if "derivation" in delivery:
            candidate_meta[alias].update(derivation=deepcopy(delivery["derivation"]),
                                        evaluation_projection="within_seed_cached_scoring_reprojection",
                                        new_inference_calls=0, new_generated_samples=0)
    contract["candidate_artifacts"] = candidate_meta
    if derivation_validator is not None:
        contract["derivation_validator"] = derivation_validator
    output.parent.mkdir(parents=True, exist_ok=True)
    # Reuse existing structural status/rubric handling without changing its older
    # full-source contract. These temporary rows change serialization only.
    with tempfile.TemporaryDirectory(prefix="flow-evaluation-", dir=output.parent) as temporary:
        staging = Path(temporary)
        input_path, reference_path = staging / "inputs.jsonl", staging / "references.jsonl"
        runner.dump_jsonl(input_path, list(requests.values()))
        runner.dump_jsonl(reference_path, list(refs.values()))
        candidates, ledgers, schedules = {}, {}, {}
        for alias, directory in candidate_deliveries.items():
            for name, index in (("results", candidates), ("ledger", ledgers), ("schedule", schedules)):
                rows = runner.load_jsonl(directory / f"{name}.jsonl")
                row_key = "id" if name == "results" else "window_id"
                normalized = [{key: value for key, value in row.items() if key != "delivery_contract"}
                              for row in rows if row[row_key] in requests]
                index[alias] = staging / alias / f"{name}.jsonl"
                runner.dump_jsonl(index[alias], normalized)
        runner.prepare(input_path, reference_path, candidates, output, split=split,
                       candidate_ledgers=ledgers, candidate_schedules=schedules,
                       corpus_manifest=source_manifest_path)
    expected = runner.load_jsonl(output / "expected.jsonl")
    run = runner.read_json(output / "run.json")
    for alias, directory in candidate_deliveries.items():
        meta = run["candidates"][alias]
        for name in ("results", "ledger", "schedule"):
            original = directory / f"{name}.jsonl"
            preserved = output / "originals" / alias / f"{name}.jsonl"
            shutil.copyfile(original, preserved)
            meta[name] = str(original.resolve())
            meta["sha256" if name == "results" else f"{name}_sha256"] = runner.sha(original)
        meta.update(delivery_contract=runner.P_FLOW_CONTRACT, raw_flow_artifacts=candidate_meta[alias]["artifacts"])
        meta.update({key: value for key, value in candidate_meta[alias].items()
                     if key in {"derivation", "evaluation_projection", "new_inference_calls", "new_generated_samples",
                                "original_generation_cost_identity", "cost_attribution", "recipe_id", "seed"}})
        meta.update(delivery_window_ids=candidate_meta[alias]["delivery_window_ids"],
                    evaluation_window_ids=candidate_meta[alias]["evaluation_window_ids"])
    for row in expected:
        alias, wid = row["candidate_alias"], row["window_id"]
        row.update(lane="P-flow", delivery_contract=runner.P_FLOW_CONTRACT,
                   scene_id=contract["window_mapping"][wid]["scene_id"], judge_source_scope=SCOPE,
                   source_mapping=contract["window_mapping"][wid],
                   raw_flow_artifacts=candidate_meta[alias]["artifacts"],
                   original_results=str((candidate_deliveries[alias] / "results.jsonl").resolve()))
        packet_path = output / row["packet"]
        packet = runner.read_json(packet_path)
        packet.update(lane="P-flow", delivery_contract=runner.P_FLOW_CONTRACT,
                      judge_source_scope=SCOPE, scene_id=row["scene_id"],
                      source_mapping=row["source_mapping"])
        runner.dump(packet_path, packet)
    runner.dump_jsonl(output / "expected.jsonl", expected)
    runner.dump(output / "p-flow-scene-contract.json", contract)
    shutil.copyfile(Path(__file__), output / "scene-evaluation-adapter.py")
    # Freeze selected source/ref bytes too; later changes cannot silently alter
    # scope. Unscored references never enter judge packets.
    runner.dump_jsonl(output / "inputs.jsonl", list(requests.values()))
    runner.dump_jsonl(output / "references.jsonl", list(refs.values()))
    shutil.copyfile(reference_freeze_path, output / "reference-freeze.json")
    shutil.copyfile(Path(contract["source_qualification_freeze"]["path"]), output / "source-qualification-freeze.json")
    frozen_names = ["p-flow-scene-contract.json", "scene-evaluation-adapter.py", "inputs.jsonl",
                    "references.jsonl", "reference-freeze.json", "source-qualification-freeze.json"]
    if derivation_validator is not None:
        shutil.copyfile(Path(derivation_validator["path"]), output / "scoring-reprojection-validator.py")
        frozen_names.append("scoring-reprojection-validator.py")
    frozen_names.extend(f"originals/{alias}/{name}.jsonl" for alias in candidate_deliveries
                        for name in ("results", "ledger", "schedule"))
    # Detect source or original-delivery changes during preparation rather than
    # publishing a run whose packets and provenance refer to different bytes.
    for pointer in (contract["source_manifest"], contract["source_inputs"], contract["references"],
                    contract["reference_freeze"], contract["source_qualification_freeze"]):
        checked_pointer(pointer, output)
    for scope in contract["allowed_source_scope"]:
        checked_pointer(scope["source"], output)
        checked_pointer(scope["source_mapping"], output)
    for meta in candidate_meta.values():
        for pointer in meta["artifacts"]:
            checked_pointer(pointer, output)
    run.update(lane="P-flow", delivery_contract=runner.P_FLOW_CONTRACT,
               judge_source_scope=SCOPE, p_flow_contract=contract,
               inputs=str(source_inputs_path.resolve()), inputs_sha256=runner.sha(source_inputs_path),
               references=str(references_path.resolve()), references_sha256=runner.sha(references_path),
               reference_windows_in_file=len(runner.load_jsonl(references_path)),
               expected_sha256=runner.sha(output / "expected.jsonl"),
               packet_sha256={row["packet"]: runner.sha(output / row["packet"]) for row in expected},
               adapter_sha256=runner.sha(Path(__file__)),
               preparation_core="translation_eval.runner.prepare per-ID; scene adapter validates and refreezes P-flow",
               frozen_artifact_sha256={name: runner.sha(output / name) for name in frozen_names})
    runner.dump(output / "run.json", run)
    return {"lane": "P-flow", "contract": SCENE_CONTRACT, "windows": len(requests),
            "scored_ids": sum(len(row["translate_ids"]) for row in requests.values()),
            "candidates": len(candidate_deliveries), "expected_records": len(expected),
            "primary_jobs": len(runner.load_jsonl(output / "jobs.jsonl"))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--source-inputs", type=Path, required=True)
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--reference-freeze", type=Path, required=True)
    parser.add_argument("--candidate-delivery", action="append", required=True, help="opaque-alias=delivery-directory")
    parser.add_argument("--window-id", action="append")
    parser.add_argument("--split", choices=["smoke", "dev", "test"], default="dev")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    candidates = {}
    for pointer in args.candidate_delivery:
        alias, directory = pointer.split("=", 1)
        if alias in candidates:
            parser.error("duplicate candidate alias")
        candidates[alias] = Path(directory)
    prepare(args.source_manifest, args.source_inputs, args.references, candidates, args.output,
            reference_freeze_path=args.reference_freeze, split=args.split, window_ids=args.window_id)


if __name__ == "__main__":
    main()
