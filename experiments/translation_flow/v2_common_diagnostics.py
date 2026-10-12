"""Released common-source diagnostics; arithmetic references never redefine C0.

Native custody verifies requests and source text upstream. This module reads its
externally pinned hash-only visibility proof, then sealed score ledgers. It does
not open reference, translation output, native request or source-dialogue files.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from experiments.translation_eval.runner import dump, load_jsonl, read_json, sha
from experiments.translation_judge.integrity import inside
from . import v2_compare as comparison, v2_statistics as statistics

DESIGN_SHA256 = "8e683eb23b243aeca306944422d3421e3426461ac661138ef2acbf2ca6aa7b74"
SOURCE_SHA256 = "da2ff2a616403aa7d3fbee6d3f8064efb5667fc6100aa8b69a480b920e135d6c"
COMPARATOR_SHA256 = "13e238db651a283d9b1c5e769dc43f9906bb1c94a437ba50fdddbeb75a0b23e5"
STATISTICS_SHA256 = "f808494c13eab95037e086450a783fdd543c8888fa8599e697f8fb9fdff21524"
CONTROL_RELEASE_SHA256 = "84c7ff4a976c1911404050edba8ab50c2d92ca6bbedf008f6f88eec657ff4f17"
ROLES = ("original_C0", "common_b3", "common_b5", "common_b20")
TARGETS = {"common_b3": 3, "common_b5": 5, "common_b20": 20}
CONTRASTS = (("common_b5", "common_b3"), ("common_b5", "common_b20"),
             ("original_C0", "common_b3"), ("original_C0", "common_b5"), ("original_C0", "common_b20"))


def _checked(pointer: dict[str, Any], root: Path, digest: str | None = None) -> Path:
    if not isinstance(pointer, dict) or not isinstance(pointer.get("path"), str) or not isinstance(pointer.get("sha256"), str):
        raise ValueError("hash-bound diagnostic artifact pointer required")
    if digest is not None and pointer.get("sha256") != digest:
        raise ValueError("external authority SHA256 mismatch")
    return comparison._pointer(pointer, root)


def _same(left: dict[str, Any], right: dict[str, Any], root: Path) -> None:
    if _checked(left, root) != _checked(right, root) or left["sha256"] != right["sha256"]:
        raise ValueError("diagnostic provenance identity mismatch")


def _scene_units(windows: dict[str, Any]) -> dict[str, list[str]]:
    scenes = {}
    for row in windows.values():
        ids = [unit["id"] for unit in row["units"]]
        if (not ids or len(ids) != len(set(ids)) or
            (row["scene_id"] in scenes and scenes[row["scene_id"]] != ids)):
            raise ValueError("source windows must retain identical complete ordered scene metadata")
        scenes[row["scene_id"]] = ids
    return scenes


def _frame(design: dict[str, Any], root: Path, source_sha: str) -> tuple[Path, dict[str, Any], list[str], set[tuple[str, str]]]:
    scope = design["scope"]
    source_path = _checked(scope["source_manifest"], root, source_sha)
    windows = {row["id"]: row for row in read_json(source_path)["windows"] if row["split"] == "screen-a"}
    if scope.get("split") != "screen-a" or len(windows) != 48 or set(scope.get("window_ids", [])) != set(windows):
        raise ValueError("diagnostic requires exact frozen screen-a48 source frame")
    scenes = sorted({row["scene_id"] for row in windows.values()})
    cues = {(scene, uid) for scene, ids in _scene_units(windows).items() for uid in ids}
    if len(scenes) != 29 or not cues or any(not row.get("scored_ids") for row in windows.values()):
        raise ValueError("diagnostic requires complete29 source scenes and scored IDs")
    return source_path, windows, scenes, cues


def _preflight(entry: dict[str, Any], groups: dict[str, str], root: Path, windows: dict[str, Any],
               source_pointer: dict[str, Any], policy_path: Path) -> dict[str, Any]:
    evaluation_root = Path(entry["evaluation_root"]).resolve()
    paths = {}
    for name, filename in (("run", "run.json"), ("expected", "expected.jsonl"), ("final", "final.jsonl"),
                           ("seal", "finalization-manifest.json")):
        paths[name] = _checked(entry[name], root)
        if inside(evaluation_root, paths[name]) != inside(evaluation_root, evaluation_root / filename):
            raise ValueError("release points outside its exact evaluation artifacts")
    run, seal = read_json(paths["run"]), read_json(paths["seal"])
    if seal.get("state") != "required_fresh_judgments_completed":
        raise ValueError("all nine common and three matched C0 seals must be terminal")
    for name in ("run", "expected", "final"):
        _same(seal[name], entry[name], root)
    comparison._seal_inventory(seal, evaluation_root, exact=True)
    contract = run["p_flow_contract"]
    _same(contract["source_manifest"], source_pointer, root)
    if set(contract["window_ids"]) != set(windows) or len(contract["candidate_artifacts"]) != 1:
        raise ValueError("diagnostic roots must have exact48 and one genuine evaluated alias")
    alias, artifact = next(iter(contract["candidate_artifacts"].items()))
    _same(artifact["original_generation_cost_identity"], entry["original_generation"], root)
    original = read_json(_checked(entry["original_generation"], root))
    if (artifact.get("seed") != entry["seed"] or original.get("settings", {}).get("seed") != entry["seed"]
        or original.get("recipe") != "c0"):
        raise ValueError("diagnostic native seed or recipe differs")
    card_path = _checked(entry["card"], root)
    card = comparison._card(card_path, _checked(source_pointer, root), policy_path, windows)
    if (card["candidate_group"] != groups[entry["role"]] or card["representative_seed"] != entry["seed"]
        or card["recipe_id"] != artifact["recipe_id"] or card["recipe"] != "c0"
        or card["window_ids"] != set(windows) or card["stage"] != "screening"):
        raise ValueError("released role does not match exact native card")
    expected = load_jsonl(paths["expected"])
    if {(row["candidate_alias"], row["window_id"]) for row in expected} != {(alias, wid) for wid in windows} or len(expected) != 48:
        raise ValueError("diagnostic expected ledger must preserve all48 slots")
    for row in expected:
        source = windows[row["window_id"]]
        if (row.get("work") != source.get("work", source.get("work_id")) or
            comparison.CATEGORY_MAP.get(row.get("category")) != comparison.CATEGORY_MAP.get(source.get("category")) or
            row.get("scored_ids") != source.get("scored_ids") or row.get("scene_id") != source.get("scene_id")):
            raise ValueError("released expected ledger differs from exact source scoring scope")
    return {"root": evaluation_root, "run": run, "alias": alias, "artifact": artifact, "card": card,
            "entry": entry, "original": original}


def _visibility(proof: dict[str, Any], preflight: dict[tuple[str, int], dict[str, Any]], root: Path,
                windows: dict[str, Any], scenes: list[str], cues: set[tuple[str, str]]) -> list[str]:
    order = proof.get("scene_ids")
    if (proof.get("schema") != "common-source-full29-visibility-equality-v1"
        or proof.get("state") != "actual_full_scope_verified" or set(proof.get("window_ids", [])) != set(windows)
        or not isinstance(order, list) or len(order) != 29 or set(order) != set(scenes)
        or proof.get("source_cues_checked") != len(cues)):
        raise ValueError("actual full29 per-cue visibility proof required; qualification is insufficient")
    entries = {(row["role"], row["seed"]): row for row in proof.get("entries", [])}
    required = {(role, seed) for role in TARGETS for seed in statistics.SEEDS}
    if set(entries) != required or len(proof["entries"]) != len(required):
        raise ValueError("visibility proof must cover all nine actual common generations")
    reference = None
    scene_units = _scene_units(windows)
    for key in sorted(required):
        entry, prepared = entries[key], preflight[key]
        for name in ("card", "original_generation"):
            _same(entry[name], prepared["entry"][name], root)
        original_path = _checked(entry["original_generation"], root)
        native_pointer = prepared["run"].get("generation_packed_mapping")
        if native_pointer is None:
            native_pointer = {"path": str(original_path.parents[4] / "prepared/packed-mapping.json"),
                              "sha256": prepared["original"]["settings"].get("packed_mapping_sha256")}
        _same(entry["packed_mapping"], native_pointer, root)
        if entry["packed_mapping"]["sha256"] != prepared["original"]["settings"].get("packed_mapping_sha256"):
            raise ValueError("packed mapping differs from actual original generation identity")
        packed = read_json(_checked(entry["packed_mapping"], root))
        expected_packing = {"target_size": TARGETS[key[0]], "context_before": 1, "context_after": 1,
            "token_target": None, "common_context": False, "offset": 0, "common_context_block_size": 60}
        settings = read_json(Path(prepared["card"]["path"]))["prepare"]
        if (packed.get("packing") != expected_packing or packed.get("scene_ids") != order
            or settings.get("common_context_block_size") != 60 or prepared["card"]["selected_scene_ids"] != order):
            raise ValueError("common source packing/card must preserve macroblock60 and exact29 scene order")
        _same(packed["source_manifest"], proof["source_manifest"], root)
        native_inputs = {"path": str(original_path.parent / "inputs.jsonl"),
                         "sha256": prepared["original"]["settings"].get("input_sha256")}
        _same(entry["inputs"], native_inputs, root)
        batches = packed.get("batches", [])
        targets = [(batch["scene_id"], uid) for batch in batches for uid in batch["target_ids"]]
        expected_targets = [(scene, ids[start:start + TARGETS[key[0]]]) for scene in order
                            for ids in [scene_units[scene]] for start in range(0, len(ids), TARGETS[key[0]])]
        if (len(targets) != len(cues) or set(targets) != cues or
            [(batch["scene_id"], batch["target_ids"]) for batch in batches] != expected_targets or
            [batch["id"] for batch in batches] != prepared["original"].get("expected_window_ids")):
            raise ValueError("common native packing must cover every source cue once in authentic batch order")
        authority = read_json(_checked(entry.get("native_verification"), root))
        if (authority.get("schema") != "common-source-native-visibility-verification-v1" or
            authority.get("state") != "actual_native_source_visibility_verified" or
            authority.get("scene_ids") != order or authority.get("source_cues_checked") != len(cues) or
            authority.get("native_expected_batch_ids") != prepared["original"].get("expected_window_ids") or
            authority.get("actual_full_prompt_verified") is not True or authority.get("source_truncated") is not False or
            not authority.get("token_request_projection_proofs")):
            raise ValueError("independent actual native full-prompt/token/request/projection proof required")
        for name in ("card", "original_generation", "inputs", "packed_mapping", "footprints"):
            _same(authority[name], entry[name], root)
        for pointer in authority["token_request_projection_proofs"]:
            _checked(pointer, root)
        footprint, source_text_hashes = {}, {}
        for row in load_jsonl(_checked(entry["footprints"], root)):
            cue = row["scene_id"], row["target_cue_id"]
            visible = row.get("visible_source", [])
            if (cue in footprint or cue not in cues or not visible
                or any(set(unit) != {"id", "text_sha256"} or not isinstance(unit["id"], str)
                       or not isinstance(unit["text_sha256"], str) or len(unit["text_sha256"]) != 64
                       or any(char not in "0123456789abcdef" for char in unit["text_sha256"]) for unit in visible)
                or len({unit["id"] for unit in visible}) != len(visible)
                or cue[1] not in {unit["id"] for unit in visible}):
                raise ValueError("invalid or duplicated ordered source footprint metadata")
            ids = scene_units[cue[0]]
            block = ids.index(cue[1]) // 60 * 60
            if [unit["id"] for unit in visible] != ids[max(0, block - 1):min(len(ids), block + 61)]:
                raise ValueError("ordered source footprint differs from frozen macroblock60 outer1 geometry")
            for unit in visible:
                qualified = cue[0], unit["id"]
                if qualified in source_text_hashes and source_text_hashes[qualified] != unit["text_sha256"]:
                    raise ValueError("same qualified visible source cue has contradictory text hashes")
                source_text_hashes[qualified] = unit["text_sha256"]
            footprint[cue] = visible
        if set(footprint) != cues or (reference is not None and footprint != reference):
            raise ValueError("complete per-target ordered visible source differs between common arms or seeds")
        reference = footprint
    return order


def _original_control_release(release: dict[str, Any], design: dict[str, Any], root: Path,
                              entries: list[dict[str, Any]], digest: str, review_sha: str, matched_sha: str) -> None:
    gate = read_json(_checked(release.get("original_control_release"), root, digest))
    if (gate.get("version") != "matched-paired-quality-inspection-gate-v1" or
        gate.get("state") != "cleared_for_paired_quality_inspection"):
        raise ValueError("original matched C0 quality inspection must already be released")
    _same(gate["source_manifest"], design["scope"]["source_manifest"], root)
    _same(gate["decision_policy"], design["decision_policy"], root)
    _checked(gate["universal_review_scope"], root, review_sha)
    _checked(gate["matched_control_scope"], root, matched_sha)
    authorized = {}
    for group in gate.get("paired_groups", []):
        for pair in group.get("pairs", []):
            seed, baseline = pair["seed"], pair["baseline"]
            if seed in authorized and authorized[seed] != baseline:
                raise ValueError("original release contains contradictory matched C0 lineage")
            authorized[seed] = baseline
    if set(authorized) != set(statistics.SEEDS):
        raise ValueError("original C0 release must authorize all three generation seeds")
    for entry in entries:
        if entry["role"] != "original_C0":
            continue
        baseline = authorized[entry["seed"]]
        if Path(baseline["root"]).resolve() != Path(entry["evaluation_root"]).resolve():
            raise ValueError("diagnostic substituted a previously unreleased original C0 root")
        for old, new in (("run", "run"), ("finalization", "seal"), ("original_generation_cost_identity", "original_generation")):
            _same(baseline[old], entry[new], root)


def summarize(design_pointer: dict[str, Any], release_pointer: dict[str, Any], visibility_pointer: dict[str, Any], *,
              expected_release_sha256: str, expected_visibility_sha256: str,
              expected_design_sha256: str = DESIGN_SHA256, expected_source_sha256: str = SOURCE_SHA256,
              expected_policy_sha256: str = comparison.POLICY_SHA256,
              expected_review_scope_sha256: str = comparison.UNIVERSAL_REVIEW_SHA256,
              expected_matched_scope_sha256: str = comparison.MATCHED_SCOPE_SHA256,
              expected_original_control_release_sha256: str = CONTROL_RELEASE_SHA256,
              expected_comparator_sha256: str = COMPARATOR_SHA256,
              expected_statistics_sha256: str = STATISTICS_SHA256) -> dict[str, Any]:
    """Validate externally released native ledgers, then compute five direct pairs."""
    root = Path.cwd()
    design = read_json(_checked(design_pointer, root, expected_design_sha256))
    release = read_json(_checked(release_pointer, root, expected_release_sha256))
    visibility = read_json(_checked(visibility_pointer, root, expected_visibility_sha256))
    if (design.get("schema") != "hy30-common-source-paired-diagnostic-comparison-design-v1"
        or release.get("schema") != "common-source-diagnostic-quality-release-v1"
        or release.get("state") != "released_for_registered_diagnostics"):
        raise ValueError("externally registered diagnostic design/release authority required")
    for name, path, digest in (("main_comparator", Path(comparison.__file__), expected_comparator_sha256),
                               ("statistics", Path(statistics.__file__), expected_statistics_sha256)):
        if sha(path) != digest:
            raise ValueError("diagnostic dependency changed from its tested implementation")
        _checked(design["implementations"][name], root, digest)
    policy_path = _checked(design["decision_policy"], root, expected_policy_sha256)
    policy = read_json(policy_path)
    source_path, windows, scenes, cues = _frame(design, root, expected_source_sha256)
    for receipt in (release, visibility):
        _same(receipt["design"], design_pointer, root)
        _same(receipt["source_manifest"], design["scope"]["source_manifest"], root)
        _same(receipt["decision_policy"], design["decision_policy"], root)
    _same(release["visibility_proof"], visibility_pointer, root)
    groups = release["groups"]
    if (set(groups) != set(ROLES) or len(set(groups.values())) != 4
        or groups["original_C0"] != policy["baseline"]["alias"]):
        raise ValueError("common-b5 is an arithmetic reference, never the official C0 baseline")
    entries = release.get("entries", [])
    required = {(role, seed) for role in ROLES for seed in statistics.SEEDS}
    if len(entries) != 12 or {(row["role"], row["seed"]) for row in entries} != required:
        raise ValueError("release must retain all nine common and three original matched C0 seals")
    _original_control_release(release, design, root, entries, expected_original_control_release_sha256,
                              expected_review_scope_sha256, expected_matched_scope_sha256)
    prepared = { (entry["role"], entry["seed"]): _preflight(entry, groups, root, windows,
        design["scope"]["source_manifest"], policy_path) for entry in entries }
    order = _visibility(visibility, prepared, root, windows, scenes, cues)
    for item in prepared.values():
        if item["card"]["selected_scene_ids"] != order:
            raise ValueError("all four arms must retain identical unique29 scene order")
    # All external release/whole-scope proof gates above precede any final parse.
    expected, final, provenance, runtime, reference, configurations, recipes = [], [], [], None, None, {}, {}
    for (role, seed), item in sorted(prepared.items()):
        evaluation = comparison._evaluation(item["root"])
        metadata = evaluation["metadata"][item["alias"]]
        comparison._card_generation(metadata, item["card"], matched_control=role == "original_C0")
        if (evaluation["universal_review_scope_sha256"] != expected_review_scope_sha256
            or (role == "original_C0" and (evaluation["matched"] is None or
                evaluation["matched"]["pointer"]["sha256"] != expected_matched_scope_sha256))
            or (role != "original_C0" and evaluation["matched"] is not None)):
            raise ValueError("diagnostic requires compatible common review and genuine matched C0 lineage")
        if evaluation["universal_review_scope"]["decision_policy"]["sha256"] != expected_policy_sha256:
            raise ValueError("diagnostic universal review changes frozen policy identity")
        settings = metadata["recipe_settings"]
        if (settings.get("sampling") != "official" or settings.get("cache_prompt") is not True or
            settings.get("n_predict") != 4096 or metadata["source_preparation"] is not None or
            any(settings.get(name) != value for name, value in item["card"]["options"].items())):
            raise ValueError("common diagnostic generation differs from frozen native recipe settings")
        current = metadata["runtime_identity_sha256"], evaluation["reference_identity"]
        if runtime is not None and current != (runtime, reference):
            raise ValueError("paired diagnostic runtime/reference identities differ")
        runtime, reference = current
        if role in configurations and configurations[role] != item["card"]["configuration_sha256"]:
            raise ValueError("common recipe/card configuration changed across seeds")
        configurations[role] = item["card"]["configuration_sha256"]
        if role in recipes and recipes[role] != metadata["recipe_identity_sha256"]:
            raise ValueError("complete native recipe changed across generation seeds")
        recipes[role] = metadata["recipe_identity_sha256"]
        for wid in sorted(windows):
            expected.append({"candidate_alias": groups[role], "window_id": wid, "seed": seed})
            row = evaluation["final"].get((item["alias"], wid))
            if row is not None:
                final.append({"candidate_alias": groups[role], "window_id": wid, "seed": seed,
                    **{field: row.get(field) for field in ("semantic", "naturalness", "status", "errors", "reviewed", "structural_status")}})
        provenance.append({"role": role, "seed": seed, "original_generation": metadata["original_generation"],
                           "evaluation": evaluation["provenance"]})
    parameters = policy["multiplicity"]
    contrasts = {}
    for left, right in CONTRASTS:
        selected = {groups[left], groups[right]}
        stats = statistics.build_statistics([row for row in expected if row["candidate_alias"] in selected],
            [row for row in final if row["candidate_alias"] in selected], {"windows": list(windows.values())}, groups[left],
            seeds=statistics.SEEDS, bootstrap_iterations=parameters["bootstrap_iterations"], seed=parameters["bootstrap_seed"],
            confidence=parameters["family_confidence"], family_size=parameters["family_size"])
        comparison._series_sensitivity(stats)
        contrasts[right + "_minus_" + left] = stats
    return {"schema": "hy30-common-source-diagnostic-summary-v1", "interpretation": "exploratory_information_matched_diagnostic",
        "arithmetic_reference": "common_b5", "official_baseline": groups["original_C0"], "role_groups": groups,
        "automatic_winner": None, "expected_records_by_role": {role: 144 for role in ROLES},
        "window_ids": sorted(windows), "scene_ids": order, "seeds": list(statistics.SEEDS), "contrasts": contrasts,
        "design": design_pointer, "release_authority": release_pointer, "visibility_proof": visibility_pointer,
        "original_control_release": release["original_control_release"],
        "generation_provenance": provenance, "severe_confirmation_gate_passed": None, "delivery_confirmation_gate_passed": None,
        "search_global_coverage": False, "new_primary_endpoint": False,
        "limitations_zh": ["common-b5仅为诊断统计参考，不能替代正式C0。五项均为直接窗口/seed配对，不相减独立区间。",
            "完整ordered源信息相同，target/readonly角色、grammar、输出竞争、调用次数及request history仍不同；不识别纯batch-size或纯位置因果效应。",
            "family9仅继承探索性显示惯例，不提供这五项新诊断或自适应多配方搜索的同时覆盖与确认胜者规则。",
            "区间只覆盖完整配对子集；全144缺分界和严重错误/交付门禁另行保留。"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("design", "release", "visibility", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--release-sha256", required=True)
    parser.add_argument("--visibility-sha256", required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise ValueError("preserve existing diagnostic summary")
    result = summarize({"path": str(args.design), "sha256": sha(args.design)},
        {"path": str(args.release), "sha256": sha(args.release)}, {"path": str(args.visibility), "sha256": sha(args.visibility)},
        expected_release_sha256=args.release_sha256, expected_visibility_sha256=args.visibility_sha256)
    dump(args.output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
