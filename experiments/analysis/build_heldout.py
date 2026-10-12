"""Evaluate the five prelocked held-out configurations without reselection."""

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

from kototoki_eval import evaluate
from kototoki_eval.scoring import RULE_VERSION
from kototoki_eval.schema import finite_time, validate_transcript

from .aggregate import aggregate_manifest
from .build_development import ROOT, cuda_observed, digest, gpu_verified, is_crisp, proof, read, write
from .build_validation import experimental_proof, harness_complete, pipeline_complete, preserved_failure_status, upstream_evidence

FREEZE_SHA256 = "f639c655017c789c095cfc62a241595484d3835b5423a9c3478ece08dd20bad5"
TEMPLATES = {"W0": "h1-w0-ch{chapter:02d}-r1", "W1": "h1-w1norm-ch{chapter:02d}-r1",
             "Q0": "h1-q0-ch{chapter:02d}-r1", "Q1": "h1-q1-ch{chapter:02d}-r1",
             "X0": "h1-x0-ch{chapter:02d}-r1"}
EXPECTED_CONFIGS = {
    "W0": "fw121-ct2482-largev3-cuda-fp16-beam5-ctx-off-vad-off-temp-fallback",
    "W1": "wx386-largev3-pyannote-native-officialnorm-torchaudio28-forced-cuda",
    "Q0": "hf518-qwen17-fa06-cuda-bf16-sdpa-greedy-window30",
    "Q1": "crisp0841-qwen17-fa06-f16-vulkan0-vad-off-fa-replay",
    "X0": "qwen17-hf518-window30-reused-officialnorm-torchaudio28-forced-cuda",
}
TERMINAL_STATUSES = {"completed", "failed", "timeout", "harness_error"}


def repeated_unit_observation(text: str, *, max_unit_characters: int = 32) -> dict[str, int]:
    """Observe literal adjacent repetitions, without choosing an error threshold."""
    best = {"unit_characters": 0, "repetitions": 0, "repeated_characters": 0}
    for size in range(1, min(max_unit_characters, len(text) // 2) + 1):
        for match in re.finditer(r"(.{" + str(size) + r"})(?:\1)+", text, flags=re.DOTALL):
            count = len(match.group(0))
            if count > best["repeated_characters"]:
                best = {"unit_characters": size, "repetitions": count // size, "repeated_characters": count}
    return best


def qwen_decode_observations(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Count raw/final text and literal repetition; never export their contents."""
    return [{"window_index": index, "start_sample": window["start_sample"], "end_sample": window["end_sample"],
             "generated_tokens": window.get("generated_tokens"), "token_limit_reached": window.get("token_limit_reached"),
             "raw_decoded_characters": len(window.get("raw_asr", "")), "official_parsed_characters": len(window.get("text", "")),
             "raw_literal_repetition": repeated_unit_observation(window.get("raw_asr", "")),
             "parsed_literal_repetition": repeated_unit_observation(window.get("text", "")),
             "classification": "descriptive_only; no new eligibility threshold or acoustic hallucination label"}
            for index, window in enumerate(result.get("windows", []))]


def load_json_artifact(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.is_file():
        return None, "missing"
    try:
        document = read(path)
    except (ValueError, UnicodeError):
        return None, "corrupt_json_or_encoding"
    if not isinstance(document, dict):
        return None, "corrupt_top_level_schema"
    return document, None


def upstream_path(group: str, chapter: int) -> Path | None:
    if group == "Q1":
        return ROOT / ".local/results" / f"h1-q1asr-ch{chapter:02d}-r1/result.json"
    if group == "X0":
        return ROOT / ".local/analysis/qwen" / f"h1-q0-ch{chapter:02d}-to-ctc.json"
    return None


def qwen_asr_phase_complete(saved: dict[str, Any], harness: dict[str, Any], *, expected_audio_sha256: str,
                            expected_offset: float, expected_duration: float) -> bool:
    """Prove the persisted ASR phase independently of subsequent FA outcome."""
    if (harness.get("status") not in TERMINAL_STATUSES or harness.get("reference_unchanged") is not True
            or harness.get("audio_sha256") != expected_audio_sha256):
        return False
    input_info = saved.get("input", {})
    if not isinstance(input_info, dict):
        return False
    input_sha = saved.get("input_sha256", input_info.get("sha256"))
    windows = saved.get("windows", [])
    if (input_sha != expected_audio_sha256 or not isinstance(saved.get("text"), str)
            or not isinstance(windows, list) or not windows
            or not finite_time(saved.get("source_start_seconds")) or not finite_time(saved.get("duration_seconds"))
            or not math.isclose(saved.get("source_start_seconds", -1), expected_offset, abs_tol=1e-7)
            or not math.isclose(saved.get("duration_seconds", -1), expected_duration, abs_tol=1e-7)):
        return False
    cursor = 0
    for window in windows:
        if not isinstance(window, dict):
            return False
        lo, hi = window.get("start_sample"), window.get("end_sample")
        if (not isinstance(lo, int) or not isinstance(hi, int) or isinstance(lo, bool) or isinstance(hi, bool)
                or lo != cursor or hi <= lo or not isinstance(window.get("text"), str)
                or not isinstance(window.get("raw_asr"), str) or window.get("asr_skipped")
                or not isinstance(window.get("generated_tokens"), int) or window["generated_tokens"] < 0
                or isinstance(window["generated_tokens"], bool) or not finite_time(window.get("offset"))
                or not isinstance(window.get("asr_input_evidence"), dict)
                or not isinstance(window["asr_input_evidence"].get("input_devices"), dict)
                or not isinstance(window["asr_input_evidence"].get("parameter_devices"), list)
                or not cuda_observed(window.get("asr_input_evidence", {}))
                or not math.isclose(window.get("offset", -1), expected_offset + lo / 16000, abs_tol=1e-7)):
            return False
        cursor = hi
    return cursor == round(expected_duration * 16000) and "".join(window["text"] for window in windows) == saved["text"]


def preserve_saved_asr(group: str, chapter: int, *, expected_audio_sha256: str,
                       expected_offset: float, expected_duration: float) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    # A rejected export or never-started dependent FA does not erase a completed
    # upstream ASR. Bind directly to its independent result and harness.
    if group not in {"Q1", "X0"}:
        return None, {}
    source = ROOT / ".local/results" / (f"h1-q1asr-ch{chapter:02d}-r1/result.json" if group == "Q1"
                                          else f"h1-q0-ch{chapter:02d}-r1/result.json")
    saved, error = load_json_artifact(source)
    if error or saved.get("schema_version") != 1 or not isinstance(saved.get("text"), str):
        return None, {}
    harness_path = source.parent / "manifest.json"
    harness, _ = load_json_artifact(harness_path)
    if not harness or harness.get("audio_sha256") != expected_audio_sha256:
        return None, {}
    if group == "Q1":
        manifest = saved.get("manifest", {})
        if not isinstance(manifest, dict) or not isinstance(manifest.get("input", {}), dict):
            return None, {}
        complete = (harness_complete(harness) and manifest.get("status") == "ok" and manifest.get("route") == "crisp-qwen-f16-cli-asr-only"
                    and manifest.get("input", {}).get("sha256") == expected_audio_sha256)
    else:
        complete = qwen_asr_phase_complete(saved, harness, expected_audio_sha256=expected_audio_sha256,
                                           expected_offset=expected_offset, expected_duration=expected_duration)
    if not complete:
        return None, {}
    return {"schema_version": 1, "text": saved["text"], "units": [], "cues": [],
            "saved_asr_complete": True, "status": "failed"}, {
                "source_result": str(source), "source_result_sha256": digest(source),
                "source_harness": str(harness_path), "source_harness_sha256": digest(harness_path),
                "audio_sha256": expected_audio_sha256,
                "preservation": "Complete saved ASR retained with no invented alignment intervals"}


def reference_identity(path: Path, scene: dict[str, Any], files: list[dict[str, Any]]) -> None:
    relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
    expected_path = Path(scene["reference"])
    expected_path = expected_path if expected_path.is_absolute() else ROOT / expected_path
    identities = {}
    for item in files:
        candidate = Path(item["path"])
        candidate = candidate if candidate.is_absolute() else ROOT / candidate
        key = candidate.resolve().relative_to(ROOT.resolve()).as_posix()
        if key in identities and identities[key] != item["sha256"]:
            raise ValueError("Contradictory frozen path identities")
        identities[key] = item["sha256"]
    if path.resolve() != expected_path.resolve() or identities.get(relative) != digest(path):
        raise ValueError("Not the exact frozen held-out reference path and hash")


def normalized_artifact_error(result: dict[str, Any] | None) -> str | None:
    if result is None:
        return None
    try:
        if not isinstance(result.get("units", []), list) or not all(isinstance(unit, dict) for unit in result.get("units", [])):
            return "corrupt_normalized_transcript_schema"
        if not isinstance(result.get("manifest", {}), dict):
            return "corrupt_normalized_transcript_schema"
        validate_transcript(result)
    except (ValueError, TypeError, AttributeError):
        return "corrupt_normalized_transcript_schema"
    return None


def build(freeze_path: Path, output: Path, *, batch_complete: bool = False) -> None:
    if not batch_complete:
        raise ValueError("Final held-out analysis waits for the parent-confirmed complete batch")
    output = output.resolve()
    allowed = (ROOT / ".local/analysis/heldout").resolve()
    if not output.is_relative_to(allowed) or output == allowed:
        raise ValueError("Held-out snapshots must be new private analysis subdirectories")
    if digest(freeze_path) != FREEZE_SHA256:
        raise ValueError("Pre-inference held-out lock changed")
    frozen = read(freeze_path)
    if frozen.get("rule_version") != RULE_VERSION or frozen.get("expected_reference_spans") != 620:
        raise ValueError("Held-out scoring rule or full denominator changed")
    groups = frozen["groups"]
    if set(groups) != set(TEMPLATES) or any(groups[group]["configuration_id"] != config for group, config in EXPECTED_CONFIGS.items()):
        raise ValueError("Prelocked candidate set changed; no reselection is permitted")
    frozen_scenes = {int(scene["chapter"]): scene for scene in frozen["heldout_scenes"]}
    chapters = tuple(sorted(frozen_scenes))
    if len(chapters) != 16:
        raise ValueError("Expected sixteen locked held-out scenes")
    for item in frozen["files"]:
        path = Path(item["path"])
        path = path if path.is_absolute() else ROOT / path
        relative = path.resolve().relative_to(ROOT).as_posix()
        if (relative.startswith("kototoki_eval/") or relative == "experiments/analysis/aggregate.py"
                or relative == "docs/testing/evaluation-config-v1.md") and digest(path) != item["sha256"]:
            raise ValueError("Frozen scoring core or rules changed")
    references, scenes = {}, []
    for chapter in chapters:
        path = ROOT / ".local/references/scoring-v2" / f"chapter-{chapter:02d}.json"
        reference_identity(path, frozen_scenes[chapter], frozen["files"])
        reference = read(path)
        if any(span.get("partition") != "heldout" for span in reference["spans"]):
            raise ValueError("Not the exact frozen held-out reference")
        references[chapter] = reference
        scenes.append({"id": f"chapter-{chapter:02d}", "reference_path": str(path), "reference_sha256": digest(path)})
    if sum(len(reference["spans"]) for reference in references.values()) != 620:
        raise ValueError("Held-out complete reference denominator was lost")
    output.mkdir(parents=True, exist_ok=False)
    registry = {"schema_version": 1, "freeze_path": str(freeze_path.resolve()), "freeze_sha256": digest(freeze_path),
                "rule_version": RULE_VERSION, "prelocked_groups": groups, "scenes": scenes, "runs": [],
                "analysis_source_sha256": {str(path.relative_to(ROOT)): digest(path)
                    for path in (*((ROOT / "kototoki_eval").glob("*.py")), *Path(__file__).parent.glob("*.py"))}}
    loaded = {}
    for group, template in TEMPLATES.items():
        for chapter in chapters:
            run_id = template.format(chapter=chapter)
            result_path, harness_path = (ROOT / ".local/results" / run_id / filename for filename in ("result.json", "manifest.json"))
            result, result_error = load_json_artifact(result_path)
            result_error = result_error or normalized_artifact_error(result)
            if result_error:
                result = None
            harness, harness_error = load_json_artifact(harness_path)
            entry = {"group": group, "route_id": groups[group]["route_id"], "configuration_id": groups[group]["configuration_id"],
                     "run_id": run_id, "scene_id": f"chapter-{chapter:02d}", "artifacts": [{"path": str(path),
                         "sha256": digest(path) if path.is_file() else None} for path in (result_path, harness_path)],
                     "result_integrity": result_error or "readable", "harness_integrity": harness_error or "readable"}
            if result:
                manifest = result.get("manifest", {})
                entry["recorded_adapter_outcome"] = {"status": result.get("status", manifest.get("status")),
                    "failure_count": len(manifest.get("failures", [])),
                    "actual_fa_gpu_verified": manifest.get("actual_fa_gpu_verified"),
                    "actual_gpu_verification_does_not_imply_per_unit_alignment_success": True}
            upstream_verified, upstream = False, {}
            complete = bool(harness and pipeline_complete(result, harness))
            if group in {"Q1", "X0"}:
                source_directory = ROOT / ".local/results" / (f"h1-q1asr-ch{chapter:02d}-r1" if group == "Q1" else f"h1-q0-ch{chapter:02d}-r1")
                declared = [source_directory / "result.json", source_directory / "manifest.json"]
                if group == "X0":
                    declared.append(upstream_path(group, chapter))
                entry["declared_upstream_artifacts"] = [{"path": str(path), "sha256": digest(path) if path.is_file() else None,
                    "integrity": load_json_artifact(path)[1] or "readable"} for path in declared]
            if complete:
                try:
                    upstream_verified, upstream, source_files = upstream_evidence(result)
                    entry["upstream_artifacts"] = [{"path": str(path), "sha256": digest(path)} for path in source_files]
                except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                    # A valid final transcript is still measurable, but source
                    # corruption can never certify saved-ASR device/identity.
                    upstream = {"integrity_failure": type(error).__name__, "execution_verified": False}
            else:
                preserved, upstream = preserve_saved_asr(group, chapter, expected_audio_sha256=frozen_scenes[chapter]["audio_sha256"],
                                                         expected_offset=frozen_scenes[chapter]["offset"], expected_duration=frozen_scenes[chapter]["duration"])
                if preserved:
                    upstream["dependent_outcome"] = ("dependent_artifact_missing_or_corrupt" if result_error
                                                       else "dependent_execution_failed" if result
                                                       else "dependent_output_unavailable")
                    result = preserved
                    entry["upstream_artifacts"] = [{"path": upstream[key], "sha256": upstream[key + "_sha256"]}
                                                   for key in ("source_result", "source_harness")]
            loaded[run_id] = (result, harness, upstream_verified, upstream, result_error, harness_error)
            registry["runs"].append(entry)
    write(output / "source-registry.json", registry)
    records, evidence, generation_failures, artifact_failures = {}, {}, {}, []
    for group, template in TEMPLATES.items():
        for chapter in chapters:
            run_id = template.format(chapter=chapter)
            result, harness, upstream_verified, upstream, result_error, harness_error = loaded[run_id]
            record = {"scene_id": f"chapter-{chapter:02d}", "run_id": run_id, "status": "missing", "execution_verified": False}
            terminal = bool(harness and harness.get("status") in TERMINAL_STATUSES)
            saved_asr_complete = bool(result and result.get("saved_asr_complete"))
            if result_error:
                artifact_failures.append({"run_id": run_id, "reason": result_error,
                    "classification": "artifact_integrity_failure; complete independent ASR retained only when separately proven"})
            if harness_error and harness_error != "missing":
                artifact_failures.append({"run_id": run_id, "reason": harness_error, "classification": "harness_artifact_integrity_failure"})
            if upstream.get("integrity_failure"):
                artifact_failures.append({"run_id": run_id, "reason": upstream["integrity_failure"], "classification": "upstream_identity_or_artifact_failure"})
            if terminal or saved_asr_complete:
                complete = bool(terminal and pipeline_complete(result, harness))
                scoring = result if result and result.get("schema_version") == 1 else {"schema_version": 1, "text": "", "units": [], "cues": []}
                input_sha = upstream["audio_sha256"] if saved_asr_complete else harness.get("audio_sha256")
                if is_crisp(result or {}):
                    fa = result["manifest"]
                    input_sha = fa["input_sha256"]
                    scoring = {**result, "source_start_seconds": fa["source_offset_s"],
                               "duration_seconds": fa["asr_manifest"]["input"]["duration_s"]}
                elif result and result.get("input"):
                    input_sha = result["input"].get("file_sha256", result["input"].get("sha256"))
                elif result and result.get("input_sha256"):
                    input_sha = result["input_sha256"]
                if (terminal and harness.get("audio_sha256") != input_sha) or input_sha != frozen_scenes[chapter]["audio_sha256"]:
                    raise ValueError("Held-out candidate input differs from its locked scene")
                if complete and (not math.isclose(scoring.get("source_start_seconds", 0), frozen_scenes[chapter]["offset"], abs_tol=1e-7)
                                 or not math.isclose(scoring.get("duration_seconds", 0), frozen_scenes[chapter]["duration"], abs_tol=1e-7)):
                    raise ValueError("Held-out source time mapping changed")
                score_path = output / "scores" / f"{run_id}-ref2-eval2.json"
                write(score_path, evaluate(references[chapter], scoring))
                verified = bool(complete and gpu_verified(result, harness) and upstream_verified)
                status = preserved_failure_status(result, complete=complete)
                if complete and not verified:
                    status = "execution_unverified"
                if result_error and not saved_asr_complete:
                    status = "missing"
                record.update(status=status, execution_verified=verified, evaluation_path=str(score_path), evaluation_sha256=digest(score_path))
                if complete:
                    evidence[run_id] = {**proof(result, harness), **experimental_proof(result), "saved_asr_provenance": upstream}
                    qwen_source = result if group == "Q0" else read(Path(upstream["source_result"])) if group == "X0" and upstream.get("source_result") else None
                    if qwen_source:
                        observations = qwen_decode_observations(qwen_source)
                        evidence[run_id]["qwen_decode_observations"] = observations
                        cap_count = sum(bool(item["token_limit_reached"]) for item in observations)
                    else:
                        cap_count = 0
                    compression_count = evidence[run_id].get("decoding_sanity", {}).get("compression_threshold_exceeded_segment_count", 0)
                    if cap_count or compression_count:
                        generation_failures.setdefault(group, []).append({"run_id": run_id,
                            "token_limit_reached_windows": cap_count, "compression_threshold_exceeded_segments": compression_count,
                            "eligibility_rule": "same pre-validation cap/compression rule; raw repetition observations do not add a new threshold"})
                else:
                    dependency_reason = upstream.get("dependent_outcome", "dependent_execution_failed") if terminal else "dependent_harness_missing_or_nonterminal"
                    record["failure_reason"] = dependency_reason if saved_asr_complete else "invocation_failed"
                    evidence[run_id] = {"status": (harness or {}).get("status", "not_observed"), "returncode": (harness or {}).get("returncode"),
                                        "saved_asr_provenance": upstream, "failure_accounting": status,
                                        "dependency_reason": dependency_reason,
                                        "dependent_invocation_observed": terminal,
                                        "harness_wall_seconds": (harness or {}).get("wall_seconds")}
                    if group == "X0" and saved_asr_complete:
                        observations = qwen_decode_observations(read(Path(upstream["source_result"])))
                        evidence[run_id]["qwen_decode_observations"] = observations
                        cap_count = sum(bool(item["token_limit_reached"]) for item in observations)
                        if cap_count:
                            generation_failures.setdefault(group, []).append({"run_id": run_id,
                                "token_limit_reached_windows": cap_count, "classification": "saved_upstream_generation_cap; dependent_alignment_unavailable",
                                "eligibility_rule": "same pre-validation cap rule; full ASR text still retained"})
            else:
                record["failure_reason"] = "missing_or_nonterminal_harness" if not harness_error else harness_error
            records[(group, chapter)] = record
            print(json.dumps({"derived_run": run_id, "status": record["status"]}), flush=True)
    manifest = {"schema_version": 1, "manifest_id": "heldout-five-prelocked-candidates-ref2-eval2", "frozen": True,
                "reference_kind": "srt_display", "evaluation_config": {"status": "prelocked_heldout", "rule_version": RULE_VERSION,
                                                                      "freeze_sha256": digest(freeze_path)},
                "scenes": scenes, "routes": [{"id": groups[group]["route_id"], "configuration_id": groups[group]["configuration_id"],
                    "runs": [records[(group, chapter)] for chapter in chapters]} for group in TEMPLATES]}
    write(output / "main-manifest.json", manifest)
    # The frozen core performs scene-paired 2000-replicate bootstrap with its
    # fixed seed. It retains nonfinite outcomes and within-scene dependence.
    report = aggregate_manifest(manifest, base=output, bootstrap=True)
    if any(route["summary"]["timing"]["denominator"] != 620 for route in report["routes"]):
        raise ValueError("Complete held-out denominator was lost")
    report.update(prelocked_groups=groups, reselection="forbidden", observed_generation_failures=generation_failures,
                  artifact_integrity_failures=artifact_failures,
                  decoding_observation_scope="Literal raw/postprocessed repetition is descriptive only; no post-hoc threshold or acoustic label")
    write(output / "main-report.json", report)
    write(output / "execution-evidence.json", {"schema_version": 1, "runs": evidence})
    print(json.dumps({"output": str(output), "table_rows": report["table_rows"], "reselection": "forbidden"}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-complete", action="store_true")
    args = parser.parse_args()
    build(args.freeze, args.output, batch_complete=args.batch_complete)


if __name__ == "__main__":
    main()
