"""Publish accepted source scoring IDs without reading reference semantics."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .flow_v2_source import VERSION, audit_isolation
from .prepare import digest, read_json, read_jsonl, write_json, write_jsonl

Json = dict[str, Any]
ROLE_WINDOWS = {"screening": 96, "confirmation": 48}


def expected_quotas(role: str) -> Counter:
    if role not in ROLE_WINDOWS:
        raise ValueError("Qualified source role must be screening or confirmation")
    if role == "confirmation":
        return Counter({("confirmation", "representative"): 48})
    return Counter({("screen-a", "representative"): 36, ("screen-a", "risk"): 12,
                    ("screen-b", "representative"): 36, ("screen-b", "risk"): 12})


def checked_pointer(pointer: Json) -> Path:
    path = Path(pointer["path"]).resolve()
    if digest(path) != pointer["sha256"]:
        raise ValueError(f"Artifact hash mismatch: {path.name}")
    return path


def metadata_identity(row: Json) -> Json:
    """Only fields bound by original source/reserve selection are compared."""
    scalar = ("id", "scene_id", "work_id", "work", "category", "episode_id", "source_sha256", "source_mapping", "source_srt", "source_srt_sha256", "source_mapping_sha256", "selection_type", "selection_group", "scored_ids", "visible_start_index", "visible_end_index", "source_event_keys", "position_stratum")
    unit_keys = ("id", "ja_srt_index", "zh_srt_index", "start", "end", "start_ms", "end_ms", "index_text", "time_line", "source_events", "flags", "score")
    return {**{k: row.get(k) for k in scalar}, "units": [{k: u.get(k) for k in unit_keys} for u in row["units"]]}


def validate_accepted(original: list[Json], reserve: list[Json], accepted: list[Json], replacements: list[Json], *, role: str = "screening") -> dict[str, str]:
    quotas_expected = expected_quotas(role)
    choices = {(r["id"], r["selection_type"]): r for r in original + reserve}
    original_by_id = {r["id"]: r for r in original}
    mapping = {r["id"]: r["id"] for r in original}
    active = {r["id"]: r for r in original}
    consumed = set(active)
    for step in replacements:
        removed, added = step["removed"], step["added"]
        if removed not in active or added in active:
            raise ValueError("Replacement chain does not match active selected IDs")
        old = active.pop(removed)
        if any(step[k] != old[k] for k in ("split", "selection_group", "selection_type")):
            raise ValueError("Replacement changes frozen split, scene or role")
        new = choices.get((added, step["selection_type"]))
        if new is None or new["scene_id"] != old["scene_id"]:
            raise ValueError("Replacement absent from same-scene frozen reserve")
        occupied = {sid for r in active.values() for sid in r["scored_ids"]}
        if occupied & set(new["scored_ids"]):
            raise ValueError("Replacement overlaps occupied scored source IDs")
        available = sorted([r for r in reserve if r["selection_group"] == old["selection_group"] and r["selection_type"] == old["selection_type"] and r["id"] not in consumed and not occupied.intersection(r["scored_ids"])], key=lambda r: r.get("reserve_rank", 0))
        if not available or available[0]["id"] != added:
            raise ValueError("Replacement skipped the frozen eligible reserve order")
        active[added] = {**new, "split": old["split"]}
        consumed.add(added)
        mapping = {key: added if value == removed else value for key, value in mapping.items()}
    accepted_by_id = {r["id"]: r for r in accepted}
    if len(accepted_by_id) != len(accepted) or set(accepted_by_id) != set(active):
        raise ValueError("Accepted IDs differ from frozen replacement chains")
    for wid, row in accepted_by_id.items():
        expected = active[wid]
        if row["split"] != expected["split"] or metadata_identity(row) != metadata_identity(expected):
            raise ValueError("Accepted source provenance differs from frozen selection")
    if len(original_by_id) != ROLE_WINDOWS[role] or len(accepted) != ROLE_WINDOWS[role]:
        raise ValueError(f"Qualified {role} must contain {ROLE_WINDOWS[role]} windows")
    quotas = Counter((r["split"], r["selection_type"]) for r in accepted)
    if quotas != quotas_expected:
        raise ValueError(f"Accepted {role} role/split quotas changed")
    for work in {r["work_id"] for r in original}:
        before = Counter((r["split"], r["selection_type"]) for r in original if r["work_id"] == work)
        after = Counter((r["split"], r["selection_type"]) for r in accepted if r["work_id"] == work)
        if before != after:
            raise ValueError("Accepted per-work quotas changed")
    audit_isolation(accepted)
    return mapping


def publish(original: Path, qualification_file: Path, output: Path, *, role: str = "screening") -> Json:
    """Publish only the explicitly selected role; callers control sealed access."""
    expected_quotas(role)
    original, qualification_file, output = original.resolve(), qualification_file.resolve(), output.resolve()
    if output.exists():
        raise ValueError("Qualified source output must be new")
    if original in output.parents or output in original.parents:
        raise ValueError("Qualified output must not modify the original source tree")
    freeze_file = original / "freeze-manifest.json"
    freeze = read_json(freeze_file)
    if (freeze["version"], freeze["state"], freeze["role"]) != (VERSION, "source_frozen_reference_unreviewed", role):
        raise ValueError(f"Expected original source-only {role} freeze")
    for artifact in freeze["artifacts"]:
        path = (original / artifact["path"]).resolve()
        if original not in path.parents or digest(path) != artifact["sha256"]:
            raise ValueError("Original source artifact failed hash verification")
    qualification = read_json(qualification_file)
    reference = qualification["reference_qualification"]
    if (reference["version"], reference["state"], reference["inference_allowed"]) != ("hy30-flow-v2-reference-v1", "frozen_double_fresh_reference_review", True):
        raise ValueError("Reference qualification is not a successful full freeze")
    checked_pointer(reference)  # Hash bytes only; never parse reference/review contents.
    accepted_path = checked_pointer(qualification[f"{role}_manifest"])
    replacements_path = checked_pointer(qualification[f"{role}_replacements"])
    accepted_manifest = read_json(accepted_path)
    if accepted_manifest["corpus_version"] != "hy30-flow-v2-reference-v1" or qualification[f"{role}_windows"] != ROLE_WINDOWS[role]:
        raise ValueError("Unexpected reference-qualified source identity")
    accepted = accepted_manifest["windows"]
    # Reject semantic fields recursively instead of accidentally transporting a mixed candidate.
    def semantic_fields(obj: Any, parent: str = "") -> bool:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in {"original_zh", "reason_zh", "text", "translations", "reference"}:
                    return True
                if key in {"ja", "zh"} and not (parent == "source_events" and isinstance(value, list)):
                    return True
                if semantic_fields(value, key):
                    return True
            return False
        return isinstance(obj, list) and any(semantic_fields(v, parent) for v in obj)
    if semantic_fields(accepted_manifest):
        raise ValueError("Accepted source metadata contains forbidden semantic fields")
    replacements = read_jsonl(replacements_path)
    initial = read_json(original / "source-manifest.json")
    corpus = Path(initial["external_corpus"]).resolve()
    if output == corpus or corpus in output.parents or output in corpus.parents:
        raise ValueError("Qualified output must be separate from the external corpus")
    reserves = read_jsonl(original / "audit/reserve-manifest.jsonl")
    mapping = validate_accepted(initial["windows"], reserves, accepted, replacements, role=role)
    scenes_path = original / "model-input/scenes.jsonl"
    scenes = read_jsonl(scenes_path)
    scenes_by_id = {s["scene_id"]: s for s in scenes}
    if {r["scene_id"] for r in accepted} != set(scenes_by_id):
        raise ValueError("Qualified scene identity changed")
    windows = []
    for row in accepted:
        scene = scenes_by_id[row["scene_id"]]
        windows.append({"id": row["id"], "source_language": "ja", "target_language": "zh-Hans", "context": [{"id": cue["id"], "text": cue["text"]} for cue in scene["context"]], "translate_ids": row["scored_ids"]})
    calibration = None
    if role == "screening":
        calibration = read_json(original / "calibration-selection.json")
        original_calibration = calibration["window_ids"]
        calibration["window_ids"] = [mapping[wid] for wid in original_calibration]
        if len(set(calibration["window_ids"])) != 16:
            raise ValueError("Replacement broke 16 distinct calibration windows")
        work_by_id = {r["id"]: r["work_id"] for r in accepted}
        if len({work_by_id[wid] for wid in calibration["window_ids"]}) != 10:
            raise ValueError("Replacement broke calibration cross-work coverage")
        calibration["original_window_ids"] = original_calibration
        calibration["replacement_mapping"] = {wid: mapping[wid] for wid in original_calibration}
    write_json(output / "source-manifest.json", {"version": VERSION, "external_corpus": initial["external_corpus"], "windows": accepted})
    (output / "model-input").mkdir(parents=True, exist_ok=True)
    (output / "model-input/scenes.jsonl").write_bytes(scenes_path.read_bytes())
    write_jsonl(output / "model-input/windows.jsonl", windows)
    if calibration is not None:
        write_json(output / "calibration-selection.json", calibration)
    write_jsonl(output / f"audit/{role}-replacements.jsonl", replacements)
    write_json(output / "audit/accepted-id-map.json", mapping)
    artifacts = [{"path": p.relative_to(output).as_posix(), "sha256": digest(p)} for p in sorted(output.rglob("*")) if p.is_file()]
    qualified = {"version": VERSION, "state": "source_frozen_reference_qualified", "role": role, "windows": ROLE_WINDOWS[role], "scenes": len(scenes), "scored_ids": sum(len(r["scored_ids"]) for r in accepted), "policy_sha256": freeze["policy_sha256"], "artifacts": artifacts, "reference_qualification": reference, "original_source_freeze": {"path": str(freeze_file), "sha256": digest(freeze_file)}, "qualification_metadata": {"path": str(qualification_file), "sha256": digest(qualification_file)}, "replacement_count": len(replacements), "builder_sha256": digest(Path(__file__))}
    write_json(output / "freeze-manifest.json", qualified)
    return {k: qualified[k] for k in ("version", "state", "role", "windows", "scenes", "scored_ids", "replacement_count")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--role", choices=tuple(ROLE_WINDOWS), default="screening")
    args = parser.parse_args()
    print(json.dumps(publish(args.source, args.qualification, args.output, role=args.role), indent=2))


if __name__ == "__main__":
    main()
