"""Source-only scoring rescope of immutable within-seed cached deliveries.

This module changes scoring selection only. It does not infer, acquire assets,
read references, alter prior evidence, or attribute another translation sample.
"""

from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import tempfile
from typing import Any

from experiments.translation_eval.runner import dump, dump_jsonl, indexed, load_jsonl, read_json, safe_id, sha
from .v2_delivery import aggregate, project_windows, scene_document
from .srt import render_srt, source_provenance


SCHEMA = "hy30-flow-scoring-reprojection-v1"
SCOPE_KEYS = ("scene_id", "source_sha256", "source_srt", "source_srt_sha256", "source_mapping",
              "source_mapping_sha256", "visible_start_index", "visible_end_index", "source_event_keys",
              "episode_id", "work", "work_id", "category", "position_stratum", "selection_group")


def identity(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": sha(path)}


def _pointer(value: Any, root: Path) -> Path:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise ValueError("reprojection requires explicit immutable artifact pointers")
    path = Path(value["path"])
    path = path.resolve() if path.is_absolute() else (root / path).resolve()
    if sha(path) != value.get("sha256"):
        raise ValueError("reprojection artifact hash changed")
    return path


def _source_scope(window: dict[str, Any]) -> dict[str, Any]:
    return {**{key: window.get(key) for key in SCOPE_KEYS},
            "units": [{key: value for key, value in unit.items() if key != "score"} for unit in window["units"]]}


def _qualified_packing(original: dict[str, Any], manifest: Path, scenes: Path) -> dict[str, Any]:
    """Permit changed score membership only within identical complete scenes."""
    source = read_json(manifest)
    all_qualified_scenes = load_jsonl(scenes)
    original_scene_path = _pointer(original["source_scenes"], manifest.parent)
    if sha(scenes) != sha(original_scene_path) or all_qualified_scenes != load_jsonl(original_scene_path):
        raise ValueError("qualified source scenes changed text, timing, scope or order")
    old_windows = indexed(original["windows"])
    scene_scope = {}
    for window in old_windows.values():
        scope = _source_scope(window)
        if window["scene_id"] in scene_scope and scene_scope[window["scene_id"]] != scope:
            raise ValueError("original windows disagree on complete scene source scope")
        scene_scope[window["scene_id"]] = scope
    scoped_windows = [window for window in source["windows"] if window["scene_id"] in original["scene_ids"]]
    if not scoped_windows or set(scene_scope) != {window["scene_id"] for window in scoped_windows}:
        raise ValueError("qualified scoring selection changed generated scene coverage")
    indexed(scoped_windows)
    originals = indexed(original["scenes"])
    score_membership = set()
    for window in scoped_windows:
        sid = window["scene_id"]
        safe_id(window["id"])
        if window.get("window_id", window["id"]) != window["id"]:
            raise ValueError("qualified scoring ID aliases disagree")
        if _source_scope(window) != scene_scope[sid]:
            raise ValueError("qualified window changed complete source scope or provenance")
        units = indexed(window["units"])
        ids = window["scored_ids"]
        if (not ids or len(ids) != len(set(ids)) or not set(ids) <= set(originals[sid]["translate_ids"])
                or [uid for uid in originals[sid]["translate_ids"] if uid in ids] != ids
                or {uid for uid, unit in units.items() if unit.get("score") is True} != set(ids)
                or any(type(unit.get("score")) is not bool for unit in units.values())):
            raise ValueError("qualified scoring targets are not ordered generated source cues")
        if score_membership & {(sid, uid) for uid in ids}:
            raise ValueError("qualified scoring windows duplicate source cue membership")
        score_membership.update((sid, uid) for uid in ids)
        scene_document(originals[sid], window)
    derived = deepcopy(original)
    derived.update(source_manifest=identity(manifest), source_scenes=identity(scenes), windows=scoped_windows)
    return derived


def _original(directory: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[Path]]:
    delivery_path = directory / "delivery.json"
    delivery = read_json(delivery_path)
    if delivery.get("schema") != "hy30-flow-delivery-v2" or "derivation" in delivery:
        raise ValueError("reprojection requires an original verified delivery, not a derived chain")
    original_manifest = _pointer(delivery["source_manifest"], directory)
    packed_path = _pointer(delivery["packed_mapping"], directory)
    packed = read_json(packed_path)
    if (_pointer(packed["source_manifest"], packed_path.parent) != original_manifest
            or delivery.get("seed") != packed.get("seed") or delivery.get("recipe_id") != packed.get("recipe_id")):
        raise ValueError("original delivery differs from original packed/source identity")
    artifacts = [delivery_path, packed_path, original_manifest]
    for value in delivery["artifacts"]:
        artifacts.append(_pointer(value, directory))
    run_dir = Path(delivery["run"])
    run_dir = run_dir.resolve() if run_dir.is_absolute() else (directory / run_dir).resolve()
    run = read_json(run_dir / "run.json")
    if (run.get("source_manifest_sha256") != sha(original_manifest)
            or run.get("packed_mapping_sha256") != sha(packed_path)
            or run.get("expected_window_ids") != [row["id"] for row in packed["batches"]]):
        raise ValueError("original run differs from unchanged source/batch identity")
    raw = {}
    recorded = set(artifacts)
    for name in ("results", "ledger", "schedule"):
        path = run_dir / f"{name}.jsonl"
        if path.is_file() and path not in recorded:
            raise ValueError("original batch evidence lacks an immutable artifact hash")
        raw[name] = load_jsonl(path) if path.is_file() else []
    aggregated = aggregate(packed, raw["results"], raw["ledger"], raw["schedule"])
    projected = project_windows(packed, aggregated)
    for name in ("results", "ledger", "schedule", "mechanical"):
        path = directory / f"{name}.jsonl"
        if load_jsonl(path) != projected[name]:
            raise ValueError("original scoring projection differs from frozen batch evidence")
        artifacts.append(path)
    if read_json(directory / "costs.json") != aggregated["costs"] or delivery["costs"] != aggregated["costs"]:
        raise ValueError("original cost accounting differs from unique batch evidence")
    artifacts.extend([directory / "costs.json", directory / "native-diagnostics.jsonl"])
    if load_jsonl(directory / "native-diagnostics.jsonl") != aggregated["native_diagnostics"]:
        raise ValueError("original native diagnostics differ from frozen batch evidence")
    for sid in packed["scene_ids"]:
        sidecar_path = directory / "scenes" / safe_id(sid) / "sidecar.json"
        sidecar = read_json(sidecar_path)
        if sidecar["coverage"]["cue_states"] != aggregated["scenes"][sid]:
            raise ValueError("original scene cue states differ from frozen batch evidence")
        window = next(row for row in packed["windows"] if row["scene_id"] == sid)
        document = scene_document(indexed(packed["scenes"])[sid], window)
        if sidecar["source"] != source_provenance(document):
            raise ValueError("original scene source provenance differs from frozen source scope")
        artifacts.append(sidecar_path)
        export = sidecar["coverage"].get("exported_srt")
        if export:
            path = directory / export
            if not path.resolve().is_relative_to(directory) or sha(path) != sidecar["coverage"].get("exported_srt_sha256"):
                raise ValueError("original complete scene SRT changed")
            values = {uid: state["text"] for uid, state in aggregated["scenes"][sid].items()}
            if path.read_bytes() != render_srt(document, values).encode("utf-8"):
                raise ValueError("original scene SRT differs from untouched translated cue states")
            artifacts.append(path)
    return delivery, packed, aggregated, list(dict.fromkeys(artifacts))


def validate_derivation(delivery: dict[str, Any], directory: Path) -> dict[str, Any]:
    """Evaluator-facing strict derivation check; return unchanged original pack."""
    chain = delivery.get("derivation")
    if (not isinstance(chain, dict) or chain.get("schema") != SCHEMA
            or chain.get("new_inference_calls") != 0 or chain.get("new_generated_samples") != 0
            or chain.get("reuse_scope") != "within_seed_cached_source_cue_delivery"):
        raise ValueError("unknown scoring reprojection derivation contract")
    original_delivery_path = _pointer(chain["original_delivery"], directory)
    original_delivery, original, _, _ = _original(original_delivery_path.parent)
    if (_pointer(chain["original_packed_mapping"], directory) != _pointer(original_delivery["packed_mapping"], original_delivery_path.parent)
            or _pointer(chain["original_source_manifest"], directory) != _pointer(original_delivery["source_manifest"], original_delivery_path.parent)
            or _pointer(chain["original_run"], directory) != Path(original_delivery["run"]) / "run.json"
            or delivery["run"] != original_delivery["run"] or delivery["seed"] != original_delivery["seed"]
            or delivery["candidate"] != original_delivery["candidate"] or delivery["recipe_id"] != original_delivery["recipe_id"]):
        raise ValueError("scoring derivation changed original run, recipe or seed identity")
    manifest = _pointer(delivery["source_manifest"], directory)
    scenes = _pointer(chain["qualified_scenes"], directory)
    freeze_path = _pointer(chain["qualified_source_freeze"], directory)
    _check_freeze(freeze_path, manifest, scenes)
    _check_original_freeze(freeze_path, _pointer(original_delivery["source_manifest"], original_delivery_path.parent))
    derived_path = _pointer(delivery["packed_mapping"], directory)
    if read_json(derived_path) != _qualified_packing(original, manifest, scenes):
        raise ValueError("derived packing changed more than frozen scoring selection")
    return original


def _check_freeze(freeze_path: Path, manifest: Path, scenes: Path) -> None:
    freeze = read_json(freeze_path)
    if freeze.get("state") != "source_frozen_reference_qualified" or freeze.get("role") != "screening":
        raise ValueError("scoring reprojection requires qualified source-only freeze metadata")
    artifacts = freeze.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("qualified source freeze lacks artifact hashes")
    pointers = {}
    for value in artifacts:
        path = Path(value["path"])
        path = path.resolve() if path.is_absolute() else (freeze_path.parent / path).resolve()
        pointers[path] = value
    for path in (manifest, scenes):
        if path not in pointers or _pointer(pointers[path], freeze_path.parent) != path:
            raise ValueError("qualified manifest/scenes are outside the frozen source identity")


def _check_original_freeze(qualified_freeze_path: Path, original_manifest: Path) -> None:
    qualified = read_json(qualified_freeze_path)
    original_freeze_path = _pointer(qualified.get("original_source_freeze"), qualified_freeze_path.parent)
    if original_freeze_path != original_manifest.parent / "freeze-manifest.json":
        raise ValueError("qualified source freeze does not derive from the original source authority")
    original_freeze = read_json(original_freeze_path)
    if original_freeze.get("role") != "screening":
        raise ValueError("original source freeze is outside the declared screening scope")
    for value in original_freeze.get("artifacts", []):
        path = Path(value["path"])
        path = path.resolve() if path.is_absolute() else (original_freeze_path.parent / path).resolve()
        if path == original_manifest:
            _pointer(value, original_freeze_path.parent)
            return
    raise ValueError("original manifest is not bound by the source freeze derivation")


def reproject_scoring(
    original_delivery: Path, accepted_manifest: Path, qualified_scenes: Path, output: Path,
    *, qualified_source_freeze: Path | None = None,
) -> dict[str, Any]:
    """Publish scoring-only derivatives of one existing within-seed delivery."""
    original_delivery, accepted_manifest, qualified_scenes, output = (
        path.resolve() for path in (original_delivery, accepted_manifest, qualified_scenes, output))
    if output.exists():
        raise FileExistsError("scoring reprojection output must be new")
    freeze_path = (qualified_source_freeze or accepted_manifest.parent / "freeze-manifest.json").resolve()
    _check_freeze(freeze_path, accepted_manifest, qualified_scenes)
    original_meta, original, aggregated, artifacts = _original(original_delivery)
    _check_original_freeze(freeze_path, _pointer(original_meta["source_manifest"], original_delivery))
    original_freeze_path = _pointer(read_json(freeze_path)["original_source_freeze"], freeze_path.parent)
    artifacts.append(original_freeze_path)
    derived = _qualified_packing(original, accepted_manifest, qualified_scenes)
    projected = project_windows(derived, aggregated)
    frozen_before = {path: sha(path) for path in artifacts + [accepted_manifest, qualified_scenes, freeze_path]}
    output.mkdir(parents=True)
    packed_path = output / "packed-mapping.json"
    dump(packed_path, derived)
    chain = {"schema": SCHEMA, "original_delivery": identity(original_delivery / "delivery.json"),
             "original_source_manifest": original_meta["source_manifest"],
             "original_packed_mapping": original_meta["packed_mapping"],
             "original_run": identity(Path(original_meta["run"]) / "run.json"),
             "qualified_source_freeze": identity(freeze_path), "qualified_scenes": identity(qualified_scenes),
             "reuse_scope": "within_seed_cached_source_cue_delivery",
             "new_inference_calls": 0, "new_generated_samples": 0,
             "timing_attribution": "original_run_only_not_new_measurement"}
    provenance = {"source_manifest": identity(accepted_manifest), "packed_mapping": identity(packed_path),
                  "run": original_meta["run"], "candidate": original_meta["candidate"],
                  "recipe_id": original_meta["recipe_id"], "seed": original_meta["seed"], "derivation": chain,
                  "artifacts": [identity(path) for path in dict.fromkeys(artifacts + [accepted_manifest, qualified_scenes, freeze_path])]}
    for name in ("results", "ledger", "schedule", "mechanical"):
        dump_jsonl(output / f"{name}.jsonl", projected[name])
    inputs, mappings = [], []
    scenes = indexed(derived["scenes"])
    for window in derived["windows"]:
        wid, sid = window["id"], window["scene_id"]
        context = [{"id": cue["id"], "text": cue["text"]} for cue in scenes[sid]["context"]]
        inputs.append({"id": wid, "source_language": "ja", "target_language": "zh-Hans", "context": context,
                       "translate_ids": window["scored_ids"]})
        mappings.append({"window_id": wid, "scene_id": sid, "work": window.get("work", window.get("work_id")),
                         "cues": [{"eval_id": cue["id"], "source_cue_id": cue["id"]} for cue in context]})
    dump_jsonl(output / "inputs.jsonl", inputs)
    dump_jsonl(output / "mapping.jsonl", mappings)
    dump_jsonl(output / "native-diagnostics.jsonl", aggregated["native_diagnostics"])
    dump(output / "costs.json", aggregated["costs"])
    dump(output / "incremental-costs.json", {"inference_calls": 0, "generated_samples": 0,
         "original_cost_identity": chain["original_run"], "count_original_cost_once": True})
    for sid in derived["scene_ids"]:
        sidecar = read_json(original_delivery / "scenes" / sid / "sidecar.json")
        sidecar.update(provenance)
        dump(output / "scenes" / sid / "sidecar.json", sidecar)
    manifest = {**provenance, "schema": "hy30-flow-delivery-v2", "scenes": deepcopy(original_meta["scenes"]),
                "expected_windows": len(derived["windows"]), "costs": aggregated["costs"],
                "quality_status": "mechanical_only_no_semantic_judgments",
                "evaluation": "scoring-only cached reprojection; no additional translation sample or timing"}
    dump(output / "delivery.json", manifest)
    validate_derivation(manifest, output)
    if any(sha(path) != digest for path, digest in frozen_before.items()):
        raise ValueError("immutable source or cached delivery changed during reprojection")
    for report in manifest["scenes"]:
        if not report.get("exported_srt"):
            continue
        source = original_delivery / report["exported_srt"]
        destination = output / report["exported_srt"]
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=destination.parent, prefix=".chn-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(source.read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return manifest
