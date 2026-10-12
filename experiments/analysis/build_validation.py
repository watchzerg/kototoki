"""Prepare immutable analysis of exactly the six frozen validation candidates."""

import argparse
import json
import math
from pathlib import Path
from typing import Any

from kototoki_eval import evaluate
from kototoki_eval.scoring import RULE_VERSION

from .aggregate import aggregate_manifest
from .build_development import (
    ROOT, bridge_source, crisp_asr_path, cuda_observed, decoding_sanity, digest, gpu_verified,
    is_crisp, proof, read, write,
)
from .development_selection import role_key

CHAPTERS = (3, 14, 23)
FREEZE_SHA256 = "e2bbfa0c5b0e34f696390cf5089ad07d71e8b603e796a05ed458da68f0f06662"
CANDIDATES = (
    ("W0-no-context", "fw121-ct2482-largev3-cuda-fp16-beam5-ctx-off-vad-off-temp-fallback", "v1-w0-ch{chapter:02d}-r1"),
    ("W1-W0-no-context", "wx386-jactc-cuda-fp32-nearest-pad0-reuse-w0-ctx-off", "v1-w1component-ch{chapter:02d}-r1"),
    ("W1-normalized-forced", "wx386-largev3-pyannote-native-officialnorm-torchaudio28-forced-cuda", "v1-w1norm-ch{chapter:02d}-r1"),
    ("Q0-window30", "hf518-qwen17-fa06-cuda-bf16-sdpa-greedy-window30", "v1-q0-ch{chapter:02d}-r1"),
    ("Q1-no-vad", "crisp0841-qwen17-fa06-f16-vulkan0-vad-off-fa-replay", "v1-q1-ch{chapter:02d}-r1"),
    ("X0-Q0-window30-normalized-forced", "qwen17-hf518-window30-reused-officialnorm-torchaudio28-forced-cuda", "v1-x0-ch{chapter:02d}-r1"),
)


def values(document: Any) -> set[str]:
    """Collect exact scalar identities independently of manifest layout."""
    if isinstance(document, dict):
        return set().union(*(values(value) for value in document.values())) if document else set()
    if isinstance(document, list):
        return set().union(*(values(value) for value in document)) if document else set()
    return {document} if isinstance(document, str) else set()


def harness_complete(harness: dict[str, Any]) -> bool:
    return (harness.get("status") == "completed" and harness.get("returncode") == 0
            and harness.get("reference_unchanged") is True)


def pipeline_complete(result: dict[str, Any] | None, harness: dict[str, Any]) -> bool:
    return bool(harness_complete(harness) and result and result.get("schema_version") == 1
                and result.get("status") != "failed"
                and result.get("manifest", {}).get("status") != "failed"
                and not result.get("manifest", {}).get("failures"))


def qwen_asr_verified(result: dict[str, Any], harness: dict[str, Any]) -> bool:
    """Verify only the saved ASR graph, whether source FA was requested or not."""
    windows = result.get("windows", [])
    return bool(harness_complete(harness) and result.get("config", {}).get("offline")
                and windows and all(cuda_observed(window.get("asr_input_evidence", {})) for window in windows))


def preserved_failure_status(result: dict[str, Any] | None, *, complete: bool) -> str:
    if complete:
        return "completed"
    # A failed aligner must retain already recognized text. A failed or missing
    # ASR invocation instead counts every reference character as a deletion.
    asr_complete = bool(result and result.get("saved_asr_complete"))
    asr_complete = asr_complete or bool(result and result.get("input_sha256") and result.get("windows")
                                       and all("text" in window for window in result["windows"]))
    return "alignment_failed" if asr_complete else "invocation_failed"


def experimental_proof(result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("experimental_alignment"):
        return {}
    alignment = result["experimental_alignment"]
    records = alignment["records"]
    return {"experimental_alignment": {
        **{key: alignment[key] for key in alignment if key not in {"records", "derived_character_segments"}},
        "record_count": len(records), "failure_count": sum(bool(item.get("failure")) for item in records),
        "actual_decoder_devices": [{"input": item.get("decoder_input_device"), "output": item.get("decoder_output_device")} for item in records],
        "emission_sha256": [item["emission_sha256"] for item in records],
        "path_sha256": [item.get("path_sha256") for item in records],
        "oov_wildcard_slots": sum(token.get("evidence_kind") == "wildcard" for item in records for token in item.get("tokens", []))},
        "experimental_preprocessing": result["experimental_preprocessing"]}


def upstream_evidence(result: dict[str, Any]) -> tuple[bool, dict[str, Any], list[Path]]:
    """Bind saved ASR text/device to this alignment without claiming fresh ASR."""
    if is_crisp(result):
        source = crisp_asr_path(result)
        saved, harness = read(source), read(source.parent / "manifest.json")
        fa = result["manifest"]
        if (saved["text"] != result["text"] or digest(source) != fa["asr_text_sha256"]
                or saved["manifest"] != fa["asr_manifest"]
                or fa["input_sha256"] != harness["audio_sha256"]):
            raise ValueError("Saved Crisp ASR identities changed")
        return harness_complete(harness), {"source_result": str(source), "source_result_sha256": digest(source),
                "source_harness_sha256": digest(source.parent / "manifest.json"),
                "devices": saved["manifest"]["device_evidence"], "asr_reused": True}, [source, source.parent / "manifest.json"]
    if result.get("route") != "W1":
        return True, {}, []
    source = Path(result["native"]["reused_asr_file"])
    saved = read(source)
    if result["text"] != saved["text"] or result["input"]["pcm_sha256"] != saved["input"]["pcm_sha256"]:
        raise ValueError("CTC changed saved ASR text or PCM")
    bridge = bridge_source(result)
    if bridge:
        _, saved, original = bridge
        provenance = saved["provenance"]
        original_result, harness = read(original), read(original.parent / "manifest.json")
        if (digest(original) != provenance["source_result_sha256"]
                or original_result["text"] != result["text"]
                or not saved["input"]["decoded_float32_exactly_equal"]
                or saved["input"]["float32_pcm_sha256"] != original_result["input"]["pcm_sha256"]
                or provenance["reference_text_used"] or provenance["source_fa_times_used"]):
            raise ValueError("Cross-family input identity or no-reference constraint failed")
        observed = provenance["window_asr_cuda_evidence"]
        verified = qwen_asr_verified(original_result, harness) and bool(observed) and all(cuda_observed(item) for item in observed)
        return verified, {"bridge_path": str(source), "bridge_sha256": digest(source), "bridge_input": saved["input"],
            "source_result": str(original), "source_result_sha256": digest(original),
            "source_harness_sha256": digest(original.parent / "manifest.json"),
            "asr_cuda_evidence": observed, "checkpoint": provenance["checkpoint"],
            "asr_config": provenance["asr_config"], "reference_text_used": False, "source_fa_times_used": False,
            "asr_reused": True}, [source, original, original.parent / "manifest.json"]
    harness = read(source.parent / "manifest.json")
    return gpu_verified(saved, harness), {"source_result": str(source), "source_result_sha256": digest(source),
        "source_harness_sha256": digest(source.parent / "manifest.json"), "devices": saved["devices"],
        "parameters": saved["effective_parameters"], "asr_reused": True}, [source, source.parent / "manifest.json"]


def select_validation_lock(report: dict[str, Any]) -> dict[str, Any]:
    """Apply the frozen post-validation role: W0 content, other routes timing."""
    if any(route["summary"]["missing_run_count"] for route in report["routes"]):
        return {"status": "not_run_pending_all_scheduled_validation_attempts"}
    groups = {"W0": ["W0-no-context"], "W1": ["W1-W0-no-context", "W1-normalized-forced"],
              "Q0": ["Q0-window30"], "Q1": ["Q1-no-vad"], "X0": ["X0-Q0-window30-normalized-forced"]}
    lookup = {route["route_id"]: route for route in report["routes"]}
    choices = {}
    for group, names in groups.items():
        eligible = [lookup[name] for name in names if lookup[name]["summary"]["all_execution_verified"]
                    and not report.get("observed_generation_failures", {}).get(name)]
        if not eligible:
            choices[group] = {"status": "no_fully_verified_complete_candidate"}
            continue
        role = "content_preservation" if group == "W0" else "timing"
        selected = min(eligible, key=lambda route: role_key(route, role))
        choices[group] = {"status": "proposed_for_parent_freeze", "role": role,
                          "route_id": selected["route_id"], "configuration_id": selected["configuration_id"]}
    return choices


def build(freeze_path: Path, output: Path, *, validation_started: bool = False) -> None:
    if not validation_started:
        raise ValueError("Do not consume validation outputs before the parent confirms validation started")
    allowed = (ROOT / ".local/analysis/validation").resolve()
    output = output.resolve()
    if not output.is_relative_to(allowed) or output == allowed:
        raise ValueError("Validation snapshots must be new directories below private validation analysis")
    frozen = read(freeze_path)
    if digest(freeze_path) != FREEZE_SHA256:
        raise ValueError("Validation-v1 freeze identity changed")
    identities = values(frozen)
    if any(config not in identities for _, config, _ in CANDIDATES) or RULE_VERSION not in identities:
        raise ValueError("Candidate configurations or evaluation rule differ from frozen manifest")
    if frozen.get("expected_reference_spans") != 151 or set(frozen.get("candidates", [])) != {route for route, _, _ in CANDIDATES}:
        raise ValueError("Frozen candidate set or denominator differs")
    frozen_scenes = {int(scene["chapter"]): scene for scene in frozen["validation_scenes"]}
    if set(frozen_scenes) != set(CHAPTERS):
        raise ValueError("Frozen validation chapter registry differs")
    for item in frozen["files"]:
        path = Path(item["path"])
        path = path if path.is_absolute() else ROOT / path
        relative = path.resolve().relative_to(ROOT).as_posix()
        if (relative.startswith("kototoki_eval/") or relative == "experiments/analysis/aggregate.py"
                or relative == "docs/testing/evaluation-config-v1.md") and digest(path) != item["sha256"]:
            raise ValueError("Frozen scoring core or policy changed")
    scenes, references = [], {}
    for chapter in CHAPTERS:
        path = ROOT / ".local/references/scoring-v2" / f"chapter-{chapter:02d}.json"
        reference = read(path)
        if any(span.get("partition") != "validation" for span in reference["spans"]) or digest(path) not in identities:
            raise ValueError("Reference is not the exact frozen validation input")
        references[chapter] = reference
        scenes.append({"id": f"chapter-{chapter:02d}", "reference_path": str(path), "reference_sha256": digest(path)})
    if sum(len(ref["spans"]) for ref in references.values()) != 151:
        raise ValueError("Full validation denominator changed")
    output.mkdir(parents=True, exist_ok=False)
    registry = {"schema_version": 1, "freeze_path": str(freeze_path.resolve()), "freeze_sha256": digest(freeze_path),
                "rule_version": RULE_VERSION, "scenes": scenes, "runs": [],
                "analysis_source_sha256": {str(path.relative_to(ROOT)): digest(path)
                    for path in (*((ROOT / "kototoki_eval").glob("*.py")), *Path(__file__).parent.glob("*.py"))}}
    loaded = {}
    for route, config, template in CANDIDATES:
        for chapter in CHAPTERS:
            run_id = template.format(chapter=chapter)
            directory = ROOT / ".local/results" / run_id
            files = [directory / "result.json", directory / "manifest.json"]
            entry = {"route": route, "configuration_id": config, "run_id": run_id,
                     "scene_id": f"chapter-{chapter:02d}", "artifacts": [
                         {"path": str(path), "sha256": digest(path) if path.is_file() else None} for path in files]}
            if files[1].is_file():
                result = read(files[0]) if files[0].is_file() else None
                harness = read(files[1])
                if harness.get("status") not in {"completed", "failed", "timeout", "harness_error"}:
                    registry["runs"].append(entry)
                    continue
                source_files = []
                verified_upstream, upstream = False, {}
                if pipeline_complete(result, harness):
                    verified_upstream, upstream, source_files = upstream_evidence(result)
                elif route in {"W1-W0-no-context", "Q1-no-vad", "X0-Q0-window30-normalized-forced"}:
                    source = (ROOT / ".local/results" / f"v1-w0-ch{chapter:02d}-r1/result.json"
                              if route == "W1-W0-no-context" else ROOT / ".local/results" / f"v1-q1asr-ch{chapter:02d}-r1/result.json"
                              if route == "Q1-no-vad" else ROOT / ".local/analysis/qwen" / f"v1-q0-ch{chapter:02d}-to-ctc.json")
                    if source.is_file():
                        saved = read(source)
                        saved_harness_path = source.parent / "manifest.json"
                        source_complete = (saved.get("provenance", {}).get("operation") == "qwen-asr-to-whisperx-ctc-export-v1"
                                           or saved_harness_path.is_file() and harness_complete(read(saved_harness_path)))
                        if saved.get("schema_version") == 1 and "text" in saved and source_complete:
                            # Preserve saved complete ASR; these are text-only
                            # failure records, never invented alignment output.
                            result = {"schema_version": 1, "text": saved["text"], "units": [], "cues": [],
                                      "saved_asr_complete": True, "status": "failed"}
                            source_files = [source]
                            upstream = {"source_result": str(source), "source_result_sha256": digest(source),
                                        "preservation": "complete saved ASR text retained despite failed/missing aligner"}
                entry["upstream_artifacts"] = [{"path": str(path), "sha256": digest(path)} for path in source_files]
                loaded[run_id] = (result, harness, verified_upstream, upstream)
            registry["runs"].append(entry)
    write(output / "source-registry.json", registry)
    records, evidence, generation_failures = {}, {}, {}
    for route, config, template in CANDIDATES:
        for chapter in CHAPTERS:
            run_id = template.format(chapter=chapter)
            record = {"scene_id": f"chapter-{chapter:02d}", "run_id": run_id, "status": "missing",
                      "execution_verified": False}
            if run_id in loaded:
                result, harness, upstream_verified, upstream = loaded[run_id]
                complete = pipeline_complete(result, harness)
                scoring = result if result and result.get("schema_version") == 1 else {"schema_version": 1, "text": "", "units": [], "cues": []}
                input_sha = harness["audio_sha256"]
                if is_crisp(result or {}):
                    fa = result["manifest"]
                    scoring = {**result, "source_start_seconds": fa["source_offset_s"],
                               "duration_seconds": fa["asr_manifest"]["input"]["duration_s"]}
                    input_sha = fa["input_sha256"]
                elif result and result.get("input"):
                    input_sha = result["input"].get("file_sha256", result["input"].get("sha256"))
                elif result and result.get("input_sha256"):
                    input_sha = result["input_sha256"]
                if input_sha != harness["audio_sha256"] or input_sha != frozen_scenes[chapter]["audio_sha256"]:
                    raise ValueError("Candidate input differs from frozen audio")
                if complete and (not math.isclose(scoring.get("source_start_seconds", 0), frozen_scenes[chapter]["offset"], abs_tol=1e-7)
                                 or not math.isclose(scoring.get("duration_seconds", 0), frozen_scenes[chapter]["duration"], abs_tol=1e-7)):
                    raise ValueError("Candidate time coordinates differ from frozen source range")
                score_path = output / "scores" / f"{run_id}-ref2-eval2.json"
                write(score_path, evaluate(references[chapter], scoring))
                verified = complete and result is not None and gpu_verified(result, harness) and upstream_verified
                status = preserved_failure_status(result, complete=complete)
                if complete and not verified:
                    status = "execution_unverified"
                if harness_complete(harness) and (not result or result.get("schema_version") != 1):
                    status = "missing"
                result_path = ROOT / ".local/results" / run_id / "result.json"
                record.update(status=status, execution_verified=verified and complete,
                              evaluation_path=str(score_path), evaluation_sha256=digest(score_path),
                              **({"transcript_path": str(result_path), "transcript_sha256": digest(result_path)} if result_path.is_file() else {}))
                if complete and result and result.get("schema_version") == 1:
                    evidence[run_id] = {**proof(result, harness), **experimental_proof(result), "saved_asr_provenance": upstream}
                    cap_count = evidence[run_id].get("token_limit_reached_windows", 0)
                    if not cap_count and result.get("route") == "W1" and bridge_source(result):
                        source_result = read(Path(upstream["source_result"]))
                        cap_count = sum(bool(window.get("token_limit_reached")) for window in source_result["windows"])
                    compression_failure = evidence[run_id].get("decoding_sanity", {}).get("compression_threshold_exceeded_segment_count", 0)
                    if result.get("route") == "W1" and not bridge_source(result):
                        sanity = decoding_sanity(read(Path(upstream["source_result"])))
                        evidence[run_id]["saved_asr_decoding_sanity"] = sanity
                        compression_failure = sanity["compression_threshold_exceeded_segment_count"]
                    if cap_count or compression_failure:
                        generation_failures.setdefault(route, []).append({"run_id": run_id,
                            "token_limit_reached_windows": cap_count, "compression_threshold_exceeded_segments": compression_failure})
                else:
                    evidence[run_id] = {"invocation_status": harness.get("status"), "returncode": harness.get("returncode"),
                                        "harness_wall_seconds": harness.get("wall_seconds"), "saved_asr_provenance": upstream,
                                        "failure_accounting": status}
            records[(route, chapter)] = record
    manifest = {"schema_version": 1, "manifest_id": "validation-six-candidates-ref2-eval2", "frozen": True,
                "reference_kind": "srt_display", "evaluation_config": {"status": "frozen_validation", "rule_version": RULE_VERSION,
                                                                      "freeze_sha256": digest(freeze_path)},
                "scenes": scenes, "routes": [{"id": route, "configuration_id": config,
                    "runs": [records[(route, chapter)] for chapter in CHAPTERS]} for route, config, _ in CANDIDATES]}
    write(output / "main-manifest.json", manifest)
    report = aggregate_manifest(manifest, base=output, bootstrap=True)
    if any(route["summary"]["timing"]["denominator"] != 151 for route in report["routes"]):
        raise ValueError("Validation full denominator was lost")
    report["observed_generation_failures"] = generation_failures
    report["post_validation_lock_proposal"] = select_validation_lock(report)
    write(output / "main-report.json", report)
    write(output / "execution-evidence.json", {"schema_version": 1, "runs": evidence})
    print(json.dumps({"output": str(output), "table_rows": report["table_rows"],
                      "lock_proposal": report["post_validation_lock_proposal"]}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--validation-started", action="store_true")
    args = parser.parse_args()
    build(args.freeze, args.output, validation_started=args.validation_started)


if __name__ == "__main__":
    main()
