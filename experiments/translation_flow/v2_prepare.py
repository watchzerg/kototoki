"""Freeze source-only v2 packing separately from scoring and model execution."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any

from experiments.translation_demo import adapters
from .cli import digest, read_json, read_rows, write_json


def identity(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


SOURCE_FREEZE_VERSION = "hy30-flow-v2-source-v1"
SOURCE_FREEZE_STATES = {"source_frozen_reference_unreviewed", "source_frozen_reference_qualified"}
SPLIT_ROLES = {"screen-a": "screening", "screen-b": "screening", "screening": "screening",
               "confirmation": "confirmation"}


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def verify_source_freeze(manifest: Path, scenes: Path, split: str = "screening", *,
                         stage: str = "qualification") -> None:
    """Accept only the published source state, independently of reference review."""
    freeze = read_json(manifest.parent / "freeze-manifest.json")
    if (not isinstance(freeze, dict) or freeze.get("version") != SOURCE_FREEZE_VERSION
            or not isinstance(freeze.get("state"), str) or freeze.get("state") not in SOURCE_FREEZE_STATES
            or split not in SPLIT_ROLES or freeze.get("role") != SPLIT_ROLES[split]):
        raise ValueError("source freeze version/state/role does not authorize the selected split")
    if freeze["state"] == "source_frozen_reference_unreviewed":
        if stage != "qualification":
            raise ValueError("unreviewed source permits engineering qualification only")
    else:
        approved = freeze.get("reference_qualification")
        original = freeze.get("original_source_freeze")
        if (not isinstance(approved, dict)
                or set(approved) != {"path", "sha256", "version", "state", "inference_allowed"}
                or approved["version"] != "hy30-flow-v2-reference-v1"
                or approved["state"] != "frozen_double_fresh_reference_review"
                or approved["inference_allowed"] is not True
                or not isinstance(original, dict) or set(original) != {"path", "sha256"}):
            raise ValueError("qualified source requires accepted reference metadata and original source identity")
        for pointer in (approved, original):
            if (not isinstance(pointer["path"], str) or not Path(pointer["path"]).is_absolute()
                    or not _sha256(pointer["sha256"])):
                raise ValueError("qualified source requires absolute paths and exact SHA256 metadata")
            # Hash metadata bytes only; reference contents never enter preparation.
            if digest(Path(pointer["path"])) != pointer["sha256"]:
                raise ValueError("qualified source approval metadata hash changed")
    artifacts = freeze.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("source freeze requires published artifact hashes")
    recorded = {}
    for entry in artifacts:
        if (not isinstance(entry, dict) or set(entry) != {"path", "sha256"}
                or not isinstance(entry["path"], str) or not entry["path"]
                or not _sha256(entry["sha256"])):
            raise ValueError("source freeze requires exact artifact paths and SHA256 hashes")
        name = entry["path"]
        artifact = Path(name)
        if (artifact.is_absolute() or artifact.drive or ".." in artifact.parts
                or name in recorded):
            raise ValueError("source freeze artifact paths must be unique and relative")
        recorded[name] = entry["sha256"]
    for path in (manifest, scenes):
        relative = path.resolve().relative_to(manifest.parent.resolve()).as_posix()
        if recorded.get(relative) != digest(path):
            raise ValueError("source artifact does not match its published freeze")


def verified_counts(path: Path, source_scenes: list[dict]) -> dict[str, int]:
    """Check each selected cue; additionally check the header for a complete map.

    A valid map may cover a larger source set than this recipe's scene subset.
    In that case the whole-map hash cannot be recomputed from the selected
    subset, so exact per-cue source hashes are the authoritative binding.
    """
    measured = read_json(path)
    if (not isinstance(measured, dict)
            or measured.get("schema") != "hy30-source-token-counts-v2" or measured.get("complete") is not True
            or not isinstance(measured.get("asset"), dict)
            or measured.get("asset", {}).get("sha256") != "8a51a390b285fb1eb566a1683f8da476be9e87c1fbee5507967d6129872dfa1a"
            or not _sha256(measured.get("template_sha256"))
            or not _sha256(measured.get("engine_manifest_sha256"))
            or not _sha256(measured.get("source_text_sha256"))
            or measured.get("tokenize_parameters") != {"add_special": False, "parse_special": True}):
        raise ValueError("token counts lack completed compatible tokenizer provenance")
    rows, counts = measured.get("attempts"), measured.get("cue_token_counts")
    if (not isinstance(rows, list) or not rows or not isinstance(counts, dict) or not counts
            or any(not isinstance(key, str) or not key for key in counts)):
        raise ValueError("token counts require explicit cue counts and tokenizer attempts")
    if any(type(count) is not int or count < 1 for count in counts.values()):
        raise ValueError("token packing requires measured positive counts for every source cue")
    attempts = {}
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("cue_id"), str) or not row["cue_id"]
                or not _sha256(row.get("source_text_sha256"))):
            raise ValueError("tokenizer attempt lacks exact cue/source identity")
        if row["cue_id"] in attempts:
            raise ValueError("duplicate tokenizer attempt cue IDs are ambiguous")
        attempts[row["cue_id"]] = row
    if set(attempts) != set(counts):
        raise ValueError("tokenizer attempt and count coverage differ")
    if any(row.get("status") != "accepted" or type(row.get("tokens")) is not int
           or row["tokens"] != counts[key] for key, row in attempts.items()):
        raise ValueError("token count source text or accepted result changed")
    sources = {}
    for scene in source_scenes:
        for cue in scene["context"]:
            if cue["id"] in sources and sources[cue["id"]] != cue["text"]:
                raise ValueError("selected source cue ID has conflicting text")
            sources[cue["id"]] = cue["text"]
            row = attempts.get(cue["id"], {})
            if (row.get("source_text_sha256") != identity(cue["text"])
                    or row.get("status") != "accepted" or row.get("tokens") != counts.get(cue["id"])):
                raise ValueError("token count source text or accepted result changed")
    if set(sources) == set(counts) and measured["source_text_sha256"] != identity(sources):
        raise ValueError("complete token count source header hash changed")
    return counts


COMMON_SOURCE_PROTOCOL = "hy30-common-source-macroblock-v1"


def _common_source_policy(*, target_size: int, context_before: int,
                          context_after: int, token_target: int | None,
                          common_context: bool, offset: int,
                          common_context_block_size: int | None) -> dict | None:
    """Describe an explicit source footprint without changing target packing."""
    if common_context_block_size is None:
        return None
    if type(common_context_block_size) is not int or common_context_block_size < 1:
        raise ValueError("common_context_block_size must be a positive integer")
    if type(target_size) is not int or target_size < 1 or common_context_block_size % target_size:
        raise ValueError("common source block must be divisible by fixed target_size")
    if common_context or token_target is not None or offset != 0:
        raise ValueError("common source blocks exclude full-scene common_context, token packing and offsets")
    return {"protocol": COMMON_SOURCE_PROTOCOL, "origin_position": 0,
            "block_size": common_context_block_size, "target_size": target_size,
            "outer_previous": context_before, "outer_next": context_after,
            "tail_block": "clipped-to-frozen-scene", "target_packing": "unchanged-scene-origin",
            "capacity_verification": "native-full-prompt-output-reservation-guard",
            "source_truncation": False}


def pack_scene(scene: dict, *, target_size: int = 5, context_before: int = 1,
               context_after: int = 1, token_target: int | None = None,
               token_counts: dict[str, int] | None = None,
               common_context: bool = False, offset: int = 0,
               common_context_block_size: int | None = None) -> tuple[list[dict], list[dict]]:
    """Pack from the frozen scene origin; scoring IDs never influence boundaries.

    An offset is a leading warm-up batch, not dropped source. Token packing
    uses frozen tokenizer measurements, then the worker verifies the entire
    rendered request with its output reservation. A single over-target source
    cue stays intact and is explicitly reported.
    """
    if type(target_size) is not int or target_size < 1:
        raise ValueError("target_size must be positive")
    if any(type(n) is not int or n < 0 for n in (context_before, context_after, offset)):
        raise ValueError("context and offset must be nonnegative integers")
    if token_target is not None and (type(token_target) is not int or token_target < 1):
        raise ValueError("token_target must be positive")
    visibility_policy = _common_source_policy(
        target_size=target_size, context_before=context_before, context_after=context_after,
        token_target=token_target, common_context=common_context, offset=offset,
        common_context_block_size=common_context_block_size)
    scene_id = scene.get("scene_id", scene["id"])
    cues = scene["context"]
    ids = [c["id"] for c in cues]
    if not ids or len(ids) != len(set(ids)) or offset >= len(ids):
        raise ValueError("empty/duplicate scene IDs or offset outside scene")
    if scene.get("translate_ids", ids) != ids:
        raise ValueError("scene must translate all source cues in original order")
    if token_target is not None:
        if token_counts is None or any(type(token_counts.get(i)) is not int or token_counts[i] < 1 for i in ids):
            raise ValueError("token packing requires measured positive counts for every source cue")
    windows, mappings = [], []
    start = 0
    while start < len(cues):
        if start == 0 and offset:
            stop = offset
        elif token_target is None:
            stop = min(len(cues), start + target_size)
        else:
            stop, total = start, 0
            while stop < len(cues):
                count = token_counts[ids[stop]]
                if stop > start and total + count > token_target:
                    break
                total += count
                stop += 1
        left, right = (0, len(cues)) if common_context else (
            max(0, start - context_before), min(len(cues), stop + context_after))
        if visibility_policy is not None:
            block_start = start // common_context_block_size * common_context_block_size
            block_stop = min(len(cues), block_start + common_context_block_size)
            if stop > block_stop:
                raise ValueError("target batch crosses common source block")
            left, right = max(0, block_start - context_before), min(len(cues), block_stop + context_after)
        batch_id = f"{scene_id}-b{len(windows) + 1:04d}"
        target = ids[start:stop]
        row = {"id": batch_id, "source_language": "ja", "target_language": "zh-Hans",
               "context": [{"id": c["id"], "text": c["text"]} for c in cues[left:right]],
               "translate_ids": target}
        adapters.validate_window(row)
        windows.append(row)
        mappings.append({"id": batch_id, "scene_id": scene_id,
                         "target_ids": target,
                         "readonly_ids": ids[left:start] + ids[stop:right],
                         "start_position": start, "end_position": stop,
                         "full_batch": stop - start == target_size if token_target is None else stop < len(cues),
                         "warmup": bool(offset and start == 0),
                         "source_token_count": sum(token_counts[i] for i in target) if token_counts else None,
                         "single_cue_over_token_target": bool(token_target and len(target) == 1 and token_counts[target[0]] > token_target)})
        if visibility_policy is not None:
            mappings[-1]["common_source_visibility"] = {
                "protocol": COMMON_SOURCE_PROTOCOL, "block_start_position": block_start,
                "block_end_position": block_stop, "context_start_position": left,
                "context_end_position": right, "visible_ids": ids[left:right],
                "full_scene_visible": left == 0 and right == len(cues),
                "visible_source_cue_count": right - left,
                "visible_source_text_token_count": sum(token_counts[i] for i in ids[left:right]) if token_counts else None}
        start = stop
    return windows, mappings


def prepare(*, manifest: Path, scenes: Path, output: Path, split: str,
            recipe_id: str, recipe: str = "c0", seed: int = 20261008,
            n_predict: int = 4096,
            target_size: int = 5, context_before: int = 1, context_after: int = 1,
            token_target: int | None = None, token_counts_path: Path | None = None,
            common_context: bool = False, offset: int = 0,
            common_context_block_size: int | None = None,
            selected_scene_ids: list[str] | None = None, stage: str = "screening",
            options: dict | None = None, measure_source_tokens: Path | None = None,
            source_preparation_path: Path | None = None,
            source_preparation_sha256: str | None = None,
            source_preparation_projection: str | None = None) -> dict:
    """Create immutable source inputs, run card, plan, and scoring-position audit."""
    started = time.perf_counter()
    if type(n_predict) is not int or n_predict < 1:
        raise ValueError("n_predict must be a positive integer")
    if recipe == "c0" and n_predict != 4096:
        raise ValueError("C0 must retain output4096")
    visibility_policy = _common_source_policy(
        target_size=target_size, context_before=context_before, context_after=context_after,
        token_target=token_target, common_context=common_context, offset=offset,
        common_context_block_size=common_context_block_size)
    if visibility_policy is not None and (source_preparation_path is not None
                                          or source_preparation_sha256 is not None
                                          or source_preparation_projection is not None):
        raise ValueError("common source blocks cannot combine with source preparation visibility overlays")
    verify_source_freeze(manifest, scenes, split, stage=stage)
    if options and set(options) - {"terms", "background", "style", "review", "partition_grammar_limits"}:
        raise ValueError("options cannot overwrite frozen workload identities")
    if options and "partition_grammar_limits" in options and recipe != "semantic-partition":
        raise ValueError("Partition grammar limits belong only to semantic-partition")
    source = read_json(manifest)
    all_scenes = read_rows(scenes)
    source_windows = source["windows"]
    selected_windows = [w for w in source_windows if w["split"] == split or (
        split == "screening" and w["split"] in ("screen-a", "screen-b"))]
    ids = {w["scene_id"] for w in selected_windows}
    if selected_scene_ids is not None:
        if not set(selected_scene_ids) <= ids:
            raise ValueError("requested scene absent from selected split")
        ids &= set(selected_scene_ids)
        selected_windows = [w for w in selected_windows if w["scene_id"] in ids]
    selected_scenes = [s for s in all_scenes if s.get("scene_id", s["id"]) in ids]
    if not selected_scenes or len(selected_scenes) != len(ids):
        raise ValueError("source scenes do not exactly cover selected window scenes")
    auxiliary = None
    if source_preparation_path is not None or source_preparation_sha256 is not None:
        if source_preparation_path is None or source_preparation_sha256 is None:
            raise ValueError("Source preparation requires both immutable artifact path and SHA256")
        if recipe == "c0":
            raise ValueError("C0 must not consume source preparation")
        if options and (options.get("terms") or options.get("background")):
            raise ValueError("Do not combine generated source preparation with untracked static source cards")
        from .v2_source_preparation import load_options
        auxiliary = load_options(source_preparation_path, source_preparation_sha256)
        ordered = [scene.get("scene_id", scene["id"]) for scene in selected_scenes]
        if (auxiliary["source"]["manifest_sha256"] != digest(manifest)
                or auxiliary["source"]["scenes_sha256"] != digest(scenes)
                or auxiliary["settings"]["seed"] != seed or auxiliary.get("stage") != stage
                or auxiliary["scene_ids"] != ordered
                or [record["scene_id"] for record in auxiliary["preparations"]] != ordered):
            raise ValueError("Source preparation source/seed/stage/ordered scene identity differs")
        expected_contexts = [[{"id": cue["id"], "text": cue["text"]} for cue in scene["context"]]
                             for scene in selected_scenes]
        if [record["source_context"] for record in auxiliary["preparations"]] != expected_contexts:
            raise ValueError("Source preparation visible context differs from exact frozen scenes")
        if auxiliary["schema"] == "hy30-source-preparation-options-v3":
            from .v2_source_projection import validate_projection_mode
            validate_projection_mode(auxiliary["mode"], auxiliary["protocol"], source_preparation_projection)
        elif source_preparation_projection is not None:
            raise ValueError("Legacy preparation cannot acquire a new projection implicitly")
    elif source_preparation_projection is not None:
        raise ValueError("Source preparation projection requires its immutable preparation artifact")
    counts = verified_counts(token_counts_path, selected_scenes) if token_counts_path else None
    settings = dict(target_size=target_size, context_before=context_before,
                    context_after=context_after, token_target=token_target,
                    common_context=common_context, offset=offset)
    if visibility_policy is not None:
        settings["common_context_block_size"] = common_context_block_size
    inputs, batches = [], []
    for scene in selected_scenes:
        rows, mapping = pack_scene(scene, token_counts=counts, **settings)
        inputs.extend(rows)
        batches.extend(mapping)
    per_batch = {}
    if auxiliary is not None and source_preparation_projection is not None:
        from .v2_source_projection import project
        prepared_scenes = {record["scene_id"]: record for record in auxiliary["preparations"]}
        projected_inputs = []
        for window, batch in zip(inputs, batches, strict=True):
            projected = project(auxiliary["mode"], auxiliary["protocol"], source_preparation_projection,
                                prepared_scenes[batch["scene_id"]], window)
            actual = projected["window"]
            batch["original_readonly_ids"] = list(batch["readonly_ids"])
            batch["readonly_ids"] = [cue["id"] for cue in actual["context"] if cue["id"] not in actual["translate_ids"]]
            batch["source_visibility"] = projected["visibility"]
            batch["visible_source_cue_count"] = len(actual["context"])
            batch["visible_source_text_token_count"] = (sum(counts[cue["id"]] for cue in actual["context"])
                                                        if counts is not None else None)
            projected_inputs.append(actual)
            per_batch[window["id"]] = {"scene_id": batch["scene_id"], "options": projected["options"],
                                       "visibility": projected["visibility"]}
        inputs = projected_inputs
    # Caller may select an engineering subset, never silently change denominators.
    mapping = {"schema": "hy30-flow-packed-v2",
               "source_manifest": {"path": str(manifest.resolve()), "sha256": digest(manifest)},
               "source_scenes": {"path": str(scenes.resolve()), "sha256": digest(scenes)},
               "split": split, "recipe_id": recipe_id, "seed": seed, "packing": settings,
               "scene_ids": [s.get("scene_id", s["id"]) for s in selected_scenes],
               "batches": batches, "windows": selected_windows, "scenes": selected_scenes,
               "token_counts": {"path": str(token_counts_path.resolve()), "sha256": digest(token_counts_path)} if token_counts_path else None}
    if visibility_policy is not None:
        mapping["source_visibility_policy"] = visibility_policy
    if auxiliary is not None:
        mapping["source_preparation"] = {"path": str(source_preparation_path.resolve()), "sha256": source_preparation_sha256}
        if source_preparation_projection is not None:
            mapping["source_preparation_projection"] = source_preparation_projection
            mapping["source_preparation_protocol"] = auxiliary["protocol"]
    positions = []
    target_index = {(b["scene_id"], cue): (b, pos) for b in batches for pos, cue in enumerate(b["target_ids"])}
    for window in selected_windows:
        scored = window.get("scored_ids", window.get("translate_ids"))
        window_batches = []
        for cue in scored:
            b, pos = target_index[(window["scene_id"], cue)]
            window_batches.append(b["id"])
            positions.append({"window_id": window.get("window_id", window["id"]),
                              "cue_id": cue, "batch_id": b["id"], "position": pos,
                              "batch_length": len(b["target_ids"]), "first": pos == 0,
                              "last": pos == len(b["target_ids"]) - 1})
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "packed-mapping.json", mapping)
    input_path = output / "inputs.jsonl"
    with input_path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in inputs:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    item = {"label": recipe_id, "inputs": "inputs.jsonl", "input_sha256": digest(input_path),
            "recipe": recipe, "sampling": "official", "cache_prompt": True,
            "n_predict": n_predict, "seed": seed, "max_attempts": 2,
            "packed_mapping_sha256": digest(output / "packed-mapping.json"),
            "source_manifest_sha256": digest(manifest), **(options or {})}
    if auxiliary is not None:
        from .v2_source_preparation import options_for_window
        prepared_scenes = {record["scene_id"]: record for record in auxiliary["preparations"]}
        if source_preparation_projection is None:
            per_batch = {window["id"]: {"scene_id": batch["scene_id"],
                                       "options": options_for_window(prepared_scenes[batch["scene_id"]], window)}
                         for window, batch in zip(inputs, batches, strict=True)}
        sidecar = {"schema": "hy30-flow-batch-options-v3" if source_preparation_projection else "hy30-flow-batch-options-v2",
                   "source_preparation": mapping["source_preparation"],
                   "packed_mapping_sha256": item["packed_mapping_sha256"],
                   "source_manifest_sha256": digest(manifest), "source_scenes_sha256": digest(scenes),
                   "scene_ids": auxiliary["scene_ids"], "seed": seed, "mode": auxiliary["mode"],
                   "windows": per_batch}
        if source_preparation_projection is not None:
            sidecar.update(protocol=auxiliary["protocol"], projection=source_preparation_projection)
        write_json(output / "batch-options.json", sidecar)
        item["source_preparation"] = {"artifact": mapping["source_preparation"],
                                      "batch_options": {"path": "batch-options.json", "sha256": digest(output / "batch-options.json")}}
    # These generous per-run guards prevent runaway work, not exploration stopping.
    calls = len(inputs) * (16 if recipe in ("semantic", "semantic-anchors", "semantic-structured", "semantic-partition") else 4)
    plan = {"schema": "hy30-flow-session-v2", "stage": stage, "lane": "P-flow",
            "budgets": {"max_translation_calls": calls, "max_judge_calls": 0,
                        "max_estimated_tokens": calls * 8192, "max_wall_seconds": max(1800, calls * 120)},
            "experiment_identity": {"source_manifest_sha256": digest(manifest),
                                    "split": split, "seed": seed, "recipe_id": recipe_id,
                                    "source_order_sha256": identity([row["id"] for row in inputs])},
            "cache_reset": {"method": "fresh-managed-server", "verification": "first-completion-cache-n-zero"},
            "workloads": [item]}
    if measure_source_tokens is not None:
        plan["token_count_source"] = {"inputs": str(measure_source_tokens.resolve()),
                                      "input_sha256": digest(measure_source_tokens)}
    write_json(output / "session-plan.json", plan)
    from .v2_worker import GUARD_TOKENS, load_plan
    load_plan(output / "session-plan.json")
    write_json(output / "position-audit.json", {"scored_cues": positions,
               "batches": len(batches), "full_batches": sum(b["full_batch"] for b in batches),
               "scoring_windows": len(selected_windows), "source_cues": sum(len(b["target_ids"]) for b in batches)})
    preparation = {"schema": "hy30-flow-preparation-v2",
               "session_plan_sha256": digest(output / "session-plan.json"),
               "mapping_sha256": digest(output / "packed-mapping.json"),
               "code_sha256": digest(Path(__file__)), "quality_evidence": False,
               "preparation_seconds": time.perf_counter() - started,
               "timing_scope": "source freeze validation, selection, packing and artifact writes before this final record"}
    if visibility_policy is not None:
        preparation["source_visibility_policy"] = visibility_policy
    if n_predict != 4096:
        preparation["generation_budget"] = {
            "protocol": "hy30-main-output-budget-v1", "n_predict": n_predict,
            "input_margin_tokens": GUARD_TOKENS, "source_truncation": False,
            "capacity_verification": "native-full-prompt-output-reservation-guard"}
    write_json(output / "preparation.json", preparation)
    return {"output": str(output), "windows": len(selected_windows), "scenes": len(selected_scenes), "batches": len(batches)}


def main() -> None:
    parser = argparse.ArgumentParser(description="冻结第二轮源文分批与评分位置")
    for name in ("manifest", "scenes", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--split", required=True)
    parser.add_argument("--recipe-id", required=True)
    parser.add_argument("--recipe", default="c0")
    parser.add_argument("--seed", type=int, default=20261008)
    parser.add_argument("--n-predict", type=int, default=4096,
                        help="显式输出上限；默认4096，C0固定4096，容量仍由原生完整提示guard核验")
    parser.add_argument("--target-size", type=int, default=5)
    parser.add_argument("--context-before", type=int, default=1)
    parser.add_argument("--context-after", type=int, default=1)
    parser.add_argument("--token-target", type=int)
    parser.add_argument("--token-counts-path", type=Path)
    parser.add_argument("--common-context", action="store_true")
    parser.add_argument("--common-context-block-size", type=int)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--selected-scene-ids", nargs="+")
    parser.add_argument("--stage", default="screening")
    parser.add_argument("--measure-source-tokens", type=Path)
    args = vars(parser.parse_args())
    print(json.dumps(prepare(**args), ensure_ascii=False))


if __name__ == "__main__":
    main()
