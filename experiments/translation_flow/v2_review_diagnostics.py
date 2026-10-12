"""Source-only same-run F8 before/after views, without new generation or timing.

These views support later blind correction/harm/missed-error analysis. They do
not assert review quality, replace F8-final versus C0, or represent fresh C0
generation: F8's initial translation shares its own interleaved cache history.
"""

from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import tempfile
from typing import Any

from experiments.translation_demo import adapters
from experiments.translation_eval.runner import dump, dump_jsonl, indexed, load_jsonl, read_json, safe_id, sha
from .srt import render_srt, source_provenance
from .v2_delivery import aggregate, project_windows, scene_document
from .v2_reproject import _original, _pointer, identity


SCHEMA = "hy30-flow-review-pre-post-v1"
PHASES = ("before", "after")


def _parsed_attempt(attempt: dict[str, Any], ids: list[str], recipe: str) -> dict[str, str]:
    response = attempt.get("response")
    if not isinstance(response, dict) or not isinstance(response.get("content"), str):
        raise ValueError("accepted review diagnostic attempt lacks immutable native output")
    if attempt.get("stage") == "translation" and recipe == "id-text-flex":
        from .v2_id_text import parse_id_text
        return parse_id_text(response["content"], ids)
    if attempt.get("stage") == "translation" and recipe == "id-text":
        from .v2_recipes import parse_id_text
        return parse_id_text(response["content"], ids)
    return adapters.translations(response["content"], ids)


def _same_run(directory: Path) -> tuple[dict, dict, dict, dict, list[Path]]:
    original, packed, final, artifacts = _original(directory)
    if "review_diagnostic" in original:
        raise ValueError("review views require the original F8 delivery, not another diagnostic view")
    run_dir = Path(original["run"]).resolve()
    run = read_json(run_dir / "run.json")
    if (run.get("settings", {}).get("review") is not True or run.get("candidate") != original["candidate"]
            or run.get("lane") != "P-flow" or run.get("input_sha256") != sha(run_dir / "inputs.jsonl")):
        raise ValueError("review views require one verified same-run F8 review workload")
    scenes, batches = indexed(packed["scenes"]), indexed(packed["batches"])
    input_rows = load_jsonl(run_dir / "inputs.jsonl")
    inputs = indexed(input_rows)
    if [row["id"] for row in input_rows] != [row["id"] for row in packed["batches"]]:
        raise ValueError("review diagnostic request sequence differs from frozen packing")
    for bid, batch in batches.items():
        visible = set(batch["target_ids"] + batch["readonly_ids"])
        expected = {"id": bid, "source_language": "ja", "target_language": "zh-Hans",
                    "context": [{"id": cue["id"], "text": cue["text"]} for cue in scenes[batch["scene_id"]]["context"]
                                if cue["id"] in visible], "translate_ids": batch["target_ids"]}
        if inputs[bid] != expected:
            raise ValueError("review diagnostic source/request scope changed")
    rows = load_jsonl(run_dir / "ledger.jsonl")
    pre_results, pre_ledger, native = [], [], []
    for row in rows:
        bid, before = row["window_id"], row.get("before_review")
        ids = batches[bid]["target_ids"]
        record = {"batch_id": bid, "source_ids": ids, "final_status": row["status"],
                  "before_review": deepcopy(before), "after_review": deepcopy(row["translations"])}
        if before is not None:
            accepted = [(number, attempt) for number, attempt in enumerate(row["attempts"])
                        if attempt.get("status") == "accepted"]
            initial = [(number, attempt) for number, attempt in accepted if attempt.get("stage") == "translation"]
            reviewed = [(number, attempt) for number, attempt in accepted if attempt.get("stage") == "source-review"]
            if (not isinstance(before, dict) or set(before) != set(ids) or len(initial) != 1
                    or initial[0][1].get("completion_dispatched") is not True
                    or not isinstance(initial[0][1].get("original_response"), str)
                    or _parsed_attempt(initial[0][1], ids, run["recipe"]) != before):
                raise ValueError("before_review differs from its accepted original translation attempt")
            if reviewed and any(number <= initial[0][0] for number, _ in reviewed):
                raise ValueError("review attempt precedes its exact same-run initial translation")
            if row["status"] == "delivered":
                if (len(reviewed) != 1 or reviewed[0][1].get("completion_dispatched") is not True
                        or not isinstance(reviewed[0][1].get("original_response"), str)
                        or _parsed_attempt(reviewed[0][1], ids, run["recipe"]) != row["translations"]):
                    raise ValueError("after_review differs from its accepted same-run review attempt")
            elif row.get("failure_stage") != "source-review":
                raise ValueError("saved before_review requires an explicit review-stage failure")
            record["initial_attempt_index"] = initial[0][0]
            record["initial_raw_response"] = initial[0][1].get("original_response")
            record["review_raw_responses"] = [attempt.get("original_response") for attempt in row["attempts"]
                                               if attempt.get("stage") == "source-review"]
            status, values, reason = "delivered", before, None
        else:
            if row["status"] == "delivered":
                raise ValueError("delivered F8 batch lacks immutable before_review provenance")
            status, values, reason = row["status"], {}, row.get("reason")
        pre_results.append({"id": bid, "translations": values, "status": status, "elapsed_seconds": None})
        pre_ledger.append({"window_id": bid, "translations": values, "status": status, "reason": reason,
                           "elapsed_seconds": None, "generation_seconds": None, "auxiliary_seconds": None,
                           "attempts": []})
        native.append(record)
    schedules_path = run_dir / "schedule.jsonl"
    schedules = load_jsonl(schedules_path) if schedules_path.is_file() else []
    before = aggregate(packed, pre_results, pre_ledger, schedules)
    # Measured costs remain owned by the complete original F8 run, once.
    return original, packed, {"before": before, "after": final}, {"rows": native}, artifacts


def _source_views(packed: dict) -> tuple[list[dict], list[dict]]:
    scenes = indexed(packed["scenes"])
    inputs, mappings = [], []
    for window in packed["windows"]:
        wid, sid = window["id"], window["scene_id"]
        context = [{"id": cue["id"], "text": cue["text"]} for cue in scenes[sid]["context"]]
        inputs.append({"id": wid, "source_language": "ja", "target_language": "zh-Hans", "context": context,
                       "translate_ids": window["scored_ids"]})
        mappings.append({"window_id": wid, "scene_id": sid, "work": window.get("work", window.get("work_id")),
                         "cues": [{"eval_id": cue["id"], "source_cue_id": cue["id"]} for cue in context]})
    return inputs, mappings


def _cost_view(original: dict, directory: Path) -> dict:
    return {"scope": "diagnostic_view_no_standalone_flow_cost",
            "original_cost_identity": identity(Path(original["run"]) / "run.json"),
            "original_costs": identity(directory / "costs.json"), "count_original_cost_once": True,
            "elapsed_seconds": None, "generation_seconds": None, "auxiliary_seconds": None,
            "new_inference_calls": 0, "new_generated_samples": 0}


def validate_review_view(delivery: dict, directory: Path) -> dict[str, list[dict[str, Any]]]:
    """Evaluator hook returning canonical projected rows for a same-run view."""
    diagnostic = delivery.get("review_diagnostic")
    if (not isinstance(diagnostic, dict) or diagnostic.get("schema") != SCHEMA
            or diagnostic.get("phase") not in PHASES or diagnostic.get("within_seed_same_run") is not True
            or diagnostic.get("new_inference_calls") != 0 or diagnostic.get("new_generated_samples") != 0
            or diagnostic.get("standalone_flow_timing") is not False
            or diagnostic.get("comparison_role") != "exploration_only_same_run_review_diagnostic"):
        raise ValueError("unknown same-run review diagnostic contract")
    original_path = _pointer(diagnostic["original_delivery"], directory)
    original, packed, views, native, artifacts = _same_run(original_path.parent)
    for key in ("source_manifest", "packed_mapping", "run", "candidate", "recipe_id", "seed"):
        if delivery.get(key) != original[key]:
            raise ValueError("review diagnostic changed original source, run, recipe or seed identity")
    if _pointer(diagnostic["original_cost_identity"], directory) != Path(original["run"]) / "run.json":
        raise ValueError("review diagnostic cost identity differs from the original F8 run")
    if delivery.get("artifacts") != [identity(path) for path in artifacts]:
        raise ValueError("review diagnostic immutable evidence chain changed")
    cost = _cost_view(original, original_path.parent)
    if delivery.get("costs") != cost or read_json(directory / "costs.json") != cost:
        raise ValueError("review view must link original costs without standalone timing or generation")
    projected = project_windows(packed, views[diagnostic["phase"]])
    for name in ("results", "ledger", "schedule", "mechanical"):
        if load_jsonl(directory / f"{name}.jsonl") != projected[name]:
            raise ValueError("review view differs from immutable same-run translation provenance")
    inputs, mappings = _source_views(packed)
    if load_jsonl(directory / "inputs.jsonl") != inputs or load_jsonl(directory / "mapping.jsonl") != mappings:
        raise ValueError("review view changed frozen full-scene source/score anchoring")
    if load_jsonl(directory / "native-review-provenance.jsonl") != native["rows"]:
        raise ValueError("review view changed native before/after provenance")
    scenes = indexed(packed["scenes"])
    reports = []
    for sid in packed["scene_ids"]:
        window = next(row for row in packed["windows"] if row["scene_id"] == sid)
        document = scene_document(scenes[sid], window)
        states = views[diagnostic["phase"]]["scenes"][sid]
        complete = all(state["status"] == "delivered" for state in states.values())
        report = {"scene_id": sid, "status": "complete" if complete else "incomplete", "expected_cues": len(states),
                  "exported_srt": f"scenes/{sid}/chn.srt" if complete else None}
        sidecar = read_json(directory / "scenes" / safe_id(sid) / "sidecar.json")
        if (sidecar.get("source") != source_provenance(document)
                or sidecar.get("coverage") != {**report, "cue_states": states}
                or sidecar.get("review_diagnostic") != diagnostic):
            raise ValueError("review scene changed exact source timing, coverage or same-run identity")
        srt = directory / "scenes" / sid / "chn.srt"
        if complete:
            values = {uid: state["text"] for uid, state in states.items()}
            if srt.read_bytes() != render_srt(document, values).encode("utf-8"):
                raise ValueError("review scene SRT differs from exact source timing and same-run cue text")
        elif srt.exists():
            raise ValueError("incomplete review scene cannot publish a successful partial SRT")
        reports.append(report)
    if delivery.get("scenes") != reports or delivery.get("expected_windows") != len(packed["windows"]):
        raise ValueError("review view changed complete scene or scoring window scope")
    return projected


def export_review_views(original_f8_delivery: Path, output: Path) -> dict[str, Any]:
    """Publish exact before/after F8 views for later blind diagnostic scoring."""
    original_f8_delivery, output = original_f8_delivery.resolve(), output.resolve()
    if output.exists():
        raise FileExistsError("review diagnostics output must be a new directory")
    original, packed, views, native, artifacts = _same_run(original_f8_delivery)
    snapshots = {path: sha(path) for path in artifacts}
    output.mkdir(parents=True)
    inputs, mappings = _source_views(packed)
    scenes = indexed(packed["scenes"])
    diagnostics = {}
    for phase in PHASES:
        directory = output / phase
        directory.mkdir()
        tag = {"schema": SCHEMA, "phase": phase, "within_seed_same_run": True,
               "original_delivery": identity(original_f8_delivery / "delivery.json"),
               "original_cost_identity": identity(Path(original["run"]) / "run.json"),
               "new_inference_calls": 0, "new_generated_samples": 0, "standalone_flow_timing": False,
               "comparison_role": "exploration_only_same_run_review_diagnostic",
               "primary_comparison": "original F8-final versus separately generated C0 remains primary"}
        provenance = {key: deepcopy(original[key]) for key in
                      ("source_manifest", "packed_mapping", "run", "candidate", "recipe_id", "seed")}
        provenance.update(review_diagnostic=tag, artifacts=[identity(path) for path in artifacts])
        projected = project_windows(packed, views[phase])
        for name in ("results", "ledger", "schedule", "mechanical"):
            dump_jsonl(directory / f"{name}.jsonl", projected[name])
        dump_jsonl(directory / "inputs.jsonl", inputs)
        dump_jsonl(directory / "mapping.jsonl", mappings)
        dump_jsonl(directory / "native-review-provenance.jsonl", native["rows"])
        cost = _cost_view(original, original_f8_delivery)
        dump(directory / "costs.json", cost)
        scene_reports = []
        pending_srt = []
        for sid in packed["scene_ids"]:
            safe_id(sid)
            window = next(row for row in packed["windows"] if row["scene_id"] == sid)
            document = scene_document(scenes[sid], window)
            states = views[phase]["scenes"][sid]
            complete = all(state["status"] == "delivered" for state in states.values())
            report = {"scene_id": sid, "status": "complete" if complete else "incomplete", "expected_cues": len(states),
                      "exported_srt": f"scenes/{sid}/chn.srt" if complete else None}
            sidecar = {"schema": SCHEMA, **provenance, "source": source_provenance(document),
                       "coverage": {**report, "cue_states": states}, "semantic_quality_checked": False}
            dump(directory / "scenes" / sid / "sidecar.json", sidecar)
            if complete:
                pending_srt.append((directory / report["exported_srt"], render_srt(document, {uid: state["text"] for uid, state in states.items()})))
            scene_reports.append(report)
        delivery = {"schema": "hy30-flow-delivery-v2", **provenance, "scenes": scene_reports,
                    "expected_windows": len(packed["windows"]), "costs": cost,
                    "quality_status": "mechanical_review_views_only_no_quality_judgments"}
        dump(directory / "delivery.json", delivery)
        if any(sha(path) != digest for path, digest in snapshots.items()):
            raise ValueError("original F8 evidence changed during review diagnostic export")
        for destination, text in pending_srt:
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=destination.parent,
                                                 prefix=".review-", delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(text)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.link(temporary, destination)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        validate_review_view(delivery, directory)
        diagnostics[phase] = identity(directory / "delivery.json")
    summary = {"schema": SCHEMA, "before": diagnostics["before"], "after": diagnostics["after"],
               "original_cost_identity": identity(Path(original["run"]) / "run.json"),
               "new_inference_calls": 0, "new_generated_samples": 0,
               "same_seed_same_run": True, "quality_diagnosis_pending": True}
    dump(output / "review-diagnostics.json", summary)
    return summary
