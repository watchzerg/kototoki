"""Derive one immutable CPU analysis snapshot for the five declared dev chapters."""

import argparse
import hashlib
import itertools
import json
from pathlib import Path
from typing import Any

from kototoki_eval import evaluate
from kototoki_eval.__main__ import json_safe
from kototoki_eval.scoring import RULE_VERSION

from .aggregate import aggregate_manifest

ROOT = Path(__file__).resolve().parents[2]
CHAPTERS = (1, 2, 5, 7, 17)
ROUTES = (
    ("W0-native", "fw121-ct2482-largev3-cuda-fp16-beam5-ctx-on-vad-off-temp-fallback", "w0-ch{chapter:02d}-cuda-native-r1"),
    ("W0-no-context", "fw121-ct2482-largev3-cuda-fp16-beam5-ctx-off-vad-off-temp-fallback", "w0-ch{chapter:02d}-cuda-no-context-r1"),
    ("W1-native", "wx386-fw121-ct2482-largev3-cuda-fp16-pyannote0500363-batch1-jactc-fp32-nearest-pad0", "w1native-ch{chapter:02d}-cuda-r1"),
)
EXTRA_WHISPER_ROUTES = (
    ("W0-no-context-temp0", "fw121-ct2482-largev3-cuda-fp16-beam5-ctx-off-vad-off-temp0", "w0-ch{chapter:02d}-cuda-no-context-temp0-r1"),
)
CRISP_ROUTES = (
    ("Q1-native", "crisp0841-qwen17-fa06-f16-vulkan0-vad-on-fa-replay", "q1-ch{chapter:02d}-cli-native-explicit-fa-r1"),
    ("Q1-no-vad", "crisp0841-qwen17-fa06-f16-vulkan0-vad-off-fa-replay", "q1-ch{chapter:02d}-cli-novad-explicit-fa-r1"),
)
CROSS_FAMILY_ROUTES = (
    ("X0-Q0-window30-CTC", "qwen17-hf518-window30-reused-wx386-jactc-cuda-fp32-nearest-pad0", "x0-q0window30-ch{chapter:02d}-ctc-native-r1"),
)
WHISPER_COMPONENT_ROUTES = (
    ("W1-W0-no-context", "wx386-jactc-cuda-fp32-nearest-pad0-reuse-w0-ctx-off", "w1-ch{chapter:02d}-w0nocontext-ctc-r1"),
)
NORMALIZED_CTC_ROUTES = (
    ("W1-normalized-forced", "wx386-largev3-pyannote-native-officialnorm-torchaudio28-forced-cuda", "w1native-ch{chapter:02d}-ctc-normalize-forced-r1"),
    ("X0-Q0-window30-normalized-forced", "qwen17-hf518-window30-reused-officialnorm-torchaudio28-forced-cuda", "x0-q0window30-ch{chapter:02d}-ctc-normalize-forced-r1"),
)
COMPONENTS = (
    ("W1-W0-native", "wx386-jactc-cuda-fp32-nearest-pad0-reuse-w0-ctx-on", "w1-ch01-w0native-ctc-r1"),
    ("W1-W0-no-context", "wx386-jactc-cuda-fp32-nearest-pad0-reuse-w0-ctx-off", "w1-ch01-w0nocontext-ctc-r1"),
)
QWEN_ROUTES = (
    ("Q0-native", "hf518-qwen17-fa06-cuda-bf16-sdpa-greedy-native-single", "q0-ch{chapter:02d}-cuda-native-r1"),
    ("Q0-window30", "hf518-qwen17-fa06-cuda-bf16-sdpa-greedy-window30", "q0-ch{chapter:02d}-cuda-window30-r1"),
    ("Q0-window120", "hf518-qwen17-fa06-cuda-bf16-sdpa-greedy-window120", "q0-ch{chapter:02d}-cuda-window120-r1"),
)


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(json_safe(document), stream, ensure_ascii=False, indent=2, allow_nan=False)


def is_crisp(result: dict[str, Any]) -> bool:
    return result.get("manifest", {}).get("route") == "crisp-cli-asr-explicit-gpu-fa-replay"


def crisp_asr_path(result: dict[str, Any]) -> Path:
    command = result["manifest"]["asr_manifest"]["command"]
    output = Path(command[command.index("-of") + 1]).parent / "result.json"
    if not output.resolve().is_relative_to((ROOT / ".local" / "results").resolve()):
        raise ValueError("Saved ASR must reside in local result evidence")
    return output


def cuda_observed(observed: dict[str, Any]) -> bool:
    return bool(observed.get("parameter_devices") and observed.get("input_devices")
                and all(str(v).startswith("cuda") for v in observed["parameter_devices"])
                and all(str(v).startswith("cuda") for v in observed["input_devices"].values())
                and str(observed.get("output_device", "")).startswith("cuda"))


def decoding_sanity(result: dict[str, Any]) -> dict[str, Any]:
    options = result.get("effective_parameters", {}).get("info", {}).get("transcription_options", {})
    segments = result.get("original_segments", [])
    compression_limit = options.get("compression_ratio_threshold")
    exceeded = sum(segment.get("compression_ratio", 0) > compression_limit for segment in segments) if compression_limit is not None else 0
    return {"single_temperature_exhausted_compression_fallback": options.get("temperatures") == [0.0] and bool(exceeded),
            "compression_ratio_threshold": compression_limit,
            "compression_threshold_exceeded_segment_count": exceeded,
            "max_segment_compression_ratio": max((segment.get("compression_ratio", 0) for segment in segments), default=None),
            "max_literal_character_repeat": max((sum(1 for _ in group) for segment in segments
                                                 for _, group in itertools.groupby(segment.get("text", ""))), default=0)}


def bridge_source(result: dict[str, Any]) -> tuple[Path, dict[str, Any], Path] | None:
    if result.get("route") != "W1":
        return None
    path = Path(result["native"]["reused_asr_file"])
    bridge = read(path)
    if bridge.get("provenance", {}).get("operation") != "qwen-asr-to-whisperx-ctc-export-v1":
        return None
    source = Path(bridge["provenance"]["source_result"])
    return path, bridge, source


def gpu_verified(result: dict[str, Any], manifest: dict[str, Any]) -> bool:
    if manifest.get("status") != "completed" or manifest.get("returncode") != 0 or not manifest.get("reference_unchanged"):
        return False
    if is_crisp(result):
        fa = result["manifest"]
        asr = fa["asr_manifest"]
        return bool(fa.get("actual_fa_gpu_verified") and fa.get("process_exit_code") == 0
                    and not fa.get("cpu_fallback_allowed") and not fa.get("fallback_warnings")
                    and any("using preferred GPU backend: Vulkan0" in marker for marker in fa.get("actual_gpu_markers", []))
                    and asr.get("process_exit_code") == 0 and asr.get("status") == "ok"
                    and asr.get("device_evidence", {}).get("gpu_only_contexts_verified")
                    and asr["device_evidence"].get("asr") == "Vulkan0"
                    and not asr["device_evidence"].get("fallback_warnings"))
    if result.get("backend") == "official-qwen-native-hf":
        if not result["config"].get("offline"):
            return False
        has_fa = False
        for window in result["windows"]:
            for role in ("asr", "fa"):
                if role == "fa" and not window["text"]:
                    continue
                observed = window.get(role + "_input_evidence", {})
                if (not observed.get("parameter_devices") or not observed.get("input_devices")
                        or not all(str(v).startswith("cuda") for v in observed["parameter_devices"])
                        or not all(str(v).startswith("cuda") for v in observed["input_devices"].values())
                        or not str(observed.get("output_device", "")).startswith("cuda")):
                    return False
                has_fa = has_fa or role == "fa"
        return has_fa
    if not result.get("offline_requested"):
        return False
    devices = result.get("devices", {})
    if result["route"] != "W1":
        if devices.get("asr", {}).get("device") != "cuda":
            return False
    if result["route"] == "W1-native":
        vad = devices.get("vad", {}).get("forward_observation", [])
        if not vad or not all(str(item.get("model", "")).startswith("cuda")
                              and str(item.get("input", "")).startswith("cuda") for item in vad):
            return False
    if result["route"] in {"W1", "W1-native"}:
        aligner = devices.get("aligner", {})
        forwards = aligner.get("forward_observation", [])
        if not str(aligner.get("model", "")).startswith("cuda") or not forwards or not all(str(v).startswith("cuda") for v in forwards):
            return False
    if result.get("experimental_alignment"):
        records = result["experimental_alignment"].get("records", [])
        preprocess = result.get("experimental_preprocessing", {}).get("records", [])
        if (not records or not preprocess
                or not all(str(item.get("actual_input_device", "")).startswith("cuda") for item in preprocess)
                or not all(str(item.get("decoder_input_device", "")).startswith("cuda")
                           and str(item.get("decoder_output_device", "")).startswith("cuda") for item in records if not item.get("failure"))
                or not any(not item.get("failure") for item in records)):
            return False
    return True


def proof(result: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    samples = []
    for sample in manifest.get("gpu_samples", []):
        fields = sample.get("csv", "").split(",")
        if len(fields) >= 5:
            try:
                samples.append(float(fields[3].strip()))
            except ValueError:
                pass
    if is_crisp(result):
        fa = result["manifest"]
        asr = fa["asr_manifest"]
        asr_harness = read(crisp_asr_path(result).parent / "manifest.json")
        return {"route": "Q1", "platform": manifest["platform"], "pins": fa["pins"],
                "binary_sha256": asr["binary_sha256"], "dll_sha256": fa["dll_sha256"],
                "devices": fa.get("device_evidence"), "actual_fa_gpu_markers": fa.get("actual_gpu_markers"),
                "asr_devices": asr["device_evidence"],
                "parameters": asr["config"], "input": asr["input"],
                "source_start_seconds": fa["source_offset_s"], "offline_requested": "local CLI assets; no network block test",
                "fresh_inference": False, "asr_reused": fa["asr_inference_reused"],
                "fresh_asr_source": not asr["cached_inference"], "fresh_fa": not fa["fa_inference_reused"],
                "performance_scope": fa["timing_scope"],
                "stages": {"saved_asr_wall_s": asr["wall_s"], "new_fa_wall_s": fa["wall_s"],
                           "separate_stage_sum_s": asr["wall_s"] + fa["wall_s"]},
                "harness_wall_seconds": manifest["wall_seconds"],
                "saved_asr_harness_wall_seconds": asr_harness["wall_seconds"],
                "device_sample_max_mib": max(samples) if samples else None,
                "device_sample_count": len(samples), "measurement": manifest.get("measurement"),
                "performance_context": manifest.get("performance_context"),
                "alignment_warning_count": len(fa["alignment_warnings"]),
                "alignment_window_count": len(fa["alignment_windows"]),
                "alignment_failures": fa["failures"], "fallback_warnings": fa["fallback_warnings"],
                "fa_text_segmentation": fa["fa_text_segmentation"],
                "fa_timestamp_correction": fa["fa_timestamp_correction"],
                "source_sha256": manifest.get("source_sha256", {}),
                "reference_unchanged": manifest["reference_unchanged"]}
    if result.get("backend") == "official-qwen-native-hf":
        timings = result["timings"]
        stages = {"total_s": timings["total_seconds"], "identity_verification_s": timings["identity_verification_seconds"],
                  "asr_load_s": timings["asr_load_seconds"], "align_load_s": timings["fa_load_seconds"],
                  "asr_s": sum(w.get("asr_inference_seconds", 0) for w in result["windows"]),
                  "align_s": sum(w.get("fa_inference_seconds", 0) for w in result["windows"])}
        duration = result["input"]["duration"]
        return {"route": "Q0", "platform": result["environment"]["platform"],
                "python": result["environment"]["python"], "packages": result["environment"]["packages"],
                "models": result["models"], "devices": result["environment"]["devices"],
                "parameters": result["config"], "generation_config": result["generation_config"],
                "input": {**result["input"], "duration_s": duration, "file_sha256": result["input"]["sha256"],
                          "pcm_identity_representation": "float32 bytes; Whisper PCM hash uses PCM16 bytes"},
                "source_start_seconds": result["source_start_seconds"], "offline_requested": result["config"]["offline"],
                "fresh_inference": not result["cache_reused"], "asr_reused": False,
                "stages": stages, "harness_wall_seconds": manifest["wall_seconds"],
                "adapter_rtf": stages["total_s"] / duration, "harness_rtf": manifest["wall_seconds"] / duration,
                "device_sample_max_mib": max(samples) if samples else None, "device_sample_count": len(samples),
                "allocator_measurements": {k: v for k, v in timings.items() if "bytes" in k},
                "window_count": len(result["windows"]),
                "token_limit_reached_windows": sum(bool(w["token_limit_reached"]) for w in result["windows"]),
                "generated_tokens": sum(w["generated_tokens"] for w in result["windows"]),
                "corrected_timestamp_count": sum(w.get("corrected_timestamp_count", 0) for w in result["windows"]),
                "raw_timestamp_class_count": sum(len(w.get("raw_timestamp_class_ids", [])) for w in result["windows"]),
                "measurement": manifest.get("measurement"), "performance_context": manifest.get("performance_context"),
                "source_sha256": manifest.get("source_sha256", {}), "adapter_identity": result["adapter_sha256"],
                "reference_unchanged": manifest["reference_unchanged"]}
    models = {key: {"repo": value.get("acquisition", {}).get("repo"),
                    "revision": value.get("acquisition", {}).get("revision"),
                    "sha256": value.get("sha256")}
              for key, value in result.get("model_identity", {}).items()}
    stages = result.get("stages", {})
    duration = result["input"]["duration_s"]
    sanity = decoding_sanity(result)
    return {"route": result["route"], "platform": result["environment"]["platform"],
            "python": result["environment"]["python"].split(" ")[0],
            "packages": {key: result["environment"]["packages"].get(key) for key in (
                "faster-whisper", "ctranslate2", "whisperx", "torch", "transformers", "pyannote-audio")},
            "models": models, "devices": result.get("devices", {}),
            "parameters": result.get("effective_parameters", {}),
            "decoding_sanity": sanity,
            "input": result["input"], "source_start_seconds": result["source_start_seconds"],
            "offline_requested": result.get("offline_requested"),
            "fresh_inference": not result.get("cached_inference", False),
            "asr_reused": result.get("effective_parameters", {}).get("asr_reused", False),
            "stages": stages, "harness_wall_seconds": manifest.get("wall_seconds"),
            "adapter_rtf": stages.get("total_s", 0) / duration,
            "harness_rtf": manifest.get("wall_seconds", 0) / duration,
            "device_sample_max_mib": max(samples) if samples else None,
            "device_sample_count": len(samples),
            "measurement": manifest.get("measurement"),
            "performance_context": manifest.get("performance_context", "not_recorded_early_run"),
            "source_sha256": manifest.get("source_sha256", {}),
            "adapter_identity": result.get("implementation"),
            "reference_unchanged": manifest.get("reference_unchanged")}



def build(output: Path, *, include_qwen: bool = False, include_crisp: bool = False,
          include_extra_whisper: bool = False, include_cross_family: bool = False,
          include_whisper_components: bool = False, include_normalized_ctc: bool = False) -> None:
    allowed = (ROOT / ".local" / "analysis" / "dev-comparison").resolve()
    output = output.resolve()
    if not output.is_relative_to(allowed) or output == allowed:
        raise ValueError("Snapshot must be below .local/analysis/dev-comparison")
    output.mkdir(parents=True, exist_ok=False)
    references = {}
    scenes = []
    for chapter in CHAPTERS:
        path = ROOT / ".local" / "references" / "scoring-v2" / f"chapter-{chapter:02d}.json"
        ref = read(path)
        if any(span.get("partition") != "dev" for span in ref["spans"]):
            raise ValueError("Refuse any non-development reference")
        references[chapter] = ref
        scenes.append({"id": f"chapter-{chapter:02d}", "reference_path": str(path), "reference_sha256": digest(path)})
    if sum(len(ref["spans"]) for ref in references.values()) != 195:
        raise ValueError("Declared development denominator changed from 195")
    routes = (*ROUTES, *QWEN_ROUTES) if include_qwen else ROUTES
    routes = (*routes, *(EXTRA_WHISPER_ROUTES if include_extra_whisper else ()),
              *(CRISP_ROUTES if include_crisp else ()),
              *(CROSS_FAMILY_ROUTES if include_cross_family else ()),
              *(WHISPER_COMPONENT_ROUTES if include_whisper_components else ()),
              *(NORMALIZED_CTC_ROUTES if include_normalized_ctc else ()))
    declared = [(route, config, template.format(chapter=chapter), chapter)
                for route, config, template in routes for chapter in CHAPTERS]
    declared.extend((route, config, run_id, 1) for route, config, run_id in COMPONENTS
                    if route not in {item[0] for item in routes})
    registry = {"schema_version": 1, "rule_version": RULE_VERSION,
                "analysis_source_sha256": {str(path.relative_to(ROOT)): digest(path)
                                           for path in (*((ROOT / "kototoki_eval").glob("*.py")), *Path(__file__).parent.glob("*.py"))},
                "scope": "fixed development only; no rankings or formal criteria",
                "scenes": scenes, "runs": []}
    if include_normalized_ctc:
        supplemental = ROOT / ".local/analysis/whisper/torchaudio-decoder-source-identity.json"
        identity = read(supplemental)
        if any(digest(Path(item["path"])) != item["sha256"] for item in identity["files"]):
            raise ValueError("Underlying decoder source/binary identity changed")
        registry["supplementary_decoder_identity"] = {"path": str(supplemental), "sha256": digest(supplemental), "identity": identity}
    loaded = {}
    for route, config, run_id, chapter in declared:
        directory = ROOT / ".local" / "results" / run_id
        result_path, manifest_path = directory / "result.json", directory / "manifest.json"
        registry["runs"].append({"route": route, "configuration_id": config, "run_id": run_id,
                                  "scene_id": f"chapter-{chapter:02d}",
                                  "result_path": str(result_path), "result_sha256": digest(result_path) if result_path.is_file() else None,
                                  "manifest_path": str(manifest_path), "manifest_sha256": digest(manifest_path) if manifest_path.is_file() else None})
        if result_path.is_file() and manifest_path.is_file():
            result = read(result_path)
            if is_crisp(result):
                asr_path = crisp_asr_path(result)
                asr_manifest_path = asr_path.parent / "manifest.json"
                registry["runs"][-1].update(saved_asr_path=str(asr_path), saved_asr_sha256=digest(asr_path),
                                            saved_asr_manifest_path=str(asr_manifest_path),
                                            saved_asr_manifest_sha256=digest(asr_manifest_path))
            bridge = bridge_source(result)
            if bridge:
                bridge_path, _, source = bridge
                registry["runs"][-1].update(bridge_path=str(bridge_path), bridge_sha256=digest(bridge_path),
                                            saved_asr_path=str(source), saved_asr_sha256=digest(source),
                                            saved_asr_manifest_sha256=digest(source.parent / "manifest.json"))
            elif result.get("route") == "W1":
                source = Path(result["native"]["reused_asr_file"])
                registry["runs"][-1].update(saved_asr_path=str(source), saved_asr_sha256=digest(source),
                                            saved_asr_manifest_sha256=digest(source.parent / "manifest.json"))
            loaded[run_id] = (result, read(manifest_path))
    # Freeze the exact declared registry before deriving or inspecting metrics.
    write(output / "source-registry.json", registry)
    run_records = {}
    evidence = {}
    for route, config, run_id, chapter in declared:
        scene_id = f"chapter-{chapter:02d}"
        record = {"scene_id": scene_id, "run_id": run_id, "status": "missing"}
        if route == "Q0-native" and chapter == 17:
            record["failure_reason"] = "unsupported_native_fa_input_above_300_seconds; no inference attempted"
        if run_id in loaded:
            result, manifest = loaded[run_id]
            result_path = ROOT / ".local" / "results" / run_id / "result.json"
            if is_crisp(result):
                fa = result["manifest"]
                asr = read(crisp_asr_path(result))
                saved_harness = read(crisp_asr_path(result).parent / "manifest.json")
                if (asr["text"] != result["text"]
                        or digest(crisp_asr_path(result)) != fa["asr_text_sha256"]
                        or asr["manifest"] != fa["asr_manifest"]
                        or saved_harness.get("status") != "completed" or saved_harness.get("returncode") != 0
                        or not saved_harness.get("reference_unchanged")
                        or saved_harness["audio_sha256"] != fa["input_sha256"]):
                    raise ValueError("Crisp saved ASR text/input/execution identity changed")
                file_sha = fa["input_sha256"]
                scoring_result = {**result, "source_start_seconds": fa["source_offset_s"],
                                  "duration_seconds": fa["asr_manifest"]["input"]["duration_s"]}
            else:
                file_sha = result["input"].get("file_sha256", result["input"].get("sha256"))
                scoring_result = result
            if file_sha != manifest["audio_sha256"]:
                raise ValueError("Backend/harness PCM file input identities differ")
            if result.get("route") == "W1":
                reused_path = Path(result["native"]["reused_asr_file"])
                reused = read(reused_path)
                if result["text"] != reused["text"] or result["input"]["pcm_sha256"] != reused["input"]["pcm_sha256"]:
                    raise ValueError("Component alignment changed frozen ASR text or PCM")
            score = evaluate(references[chapter], scoring_result)
            score_path = output / "scores" / f"{run_id}-ref2-eval2.json"
            write(score_path, score)
            complete = manifest.get("status") == "completed" and manifest.get("returncode") == 0
            verified = gpu_verified(result, manifest)
            bridge = bridge_source(result)
            if bridge:
                _, reused, source = bridge
                provenance = reused["provenance"]
                source_result, source_harness = read(source), read(source.parent / "manifest.json")
                if (digest(source) != provenance["source_result_sha256"]
                        or source_result["text"] != result["text"]
                        or not reused["input"]["decoded_float32_exactly_equal"]
                        or reused["input"]["float32_pcm_sha256"] != source_result["input"]["pcm_sha256"]
                        or reused["input"]["file_sha256"] != source_harness["audio_sha256"]
                        or provenance["reference_text_used"] or provenance["source_fa_times_used"]):
                    raise ValueError("Cross-family bridge changed frozen ASR, PCM or used reference/FA bounds")
                verified = verified and gpu_verified(source_result, source_harness)
                observed = provenance["window_asr_cuda_evidence"]
                verified = verified and bool(observed) and all(cuda_observed(item) for item in observed)
            elif result.get("route") == "W1":
                saved = Path(result["native"]["reused_asr_file"])
                saved_result, saved_harness = read(saved), read(saved.parent / "manifest.json")
                verified = verified and gpu_verified(saved_result, saved_harness)
            record.update(status=("completed" if verified else "execution_unverified") if complete else "invocation_failed",
                          execution_verified=verified, evaluation_path=str(score_path), evaluation_sha256=digest(score_path),
                          transcript_path=str(result_path), transcript_sha256=digest(result_path))
            evidence[run_id] = proof(result, manifest)
            if result.get("experimental_alignment"):
                alignment = result["experimental_alignment"]
                preprocess = result["experimental_preprocessing"]
                records = alignment["records"]
                evidence[run_id]["experimental_alignment"] = {
                    **{key: alignment[key] for key in alignment if key not in {"records", "derived_character_segments"}},
                    "record_count": len(records), "failure_count": sum(bool(item.get("failure")) for item in records),
                    "emission_sha256": [item["emission_sha256"] for item in records],
                    "path_sha256": [item.get("path_sha256") for item in records],
                    "actual_decoder_devices": [{"input": item.get("decoder_input_device"), "output": item.get("decoder_output_device")} for item in records],
                    "tokens": sum(len(item.get("tokens", [])) for item in records),
                    "accepted_lexical_tokens": sum(token.get("lexical_interval_accepted", False) for item in records for token in item.get("tokens", [])),
                    "oov_wildcards": sum(token.get("evidence_kind") == "wildcard" for item in records for token in item.get("tokens", []))}
                evidence[run_id]["experimental_preprocessing"] = {**{key: preprocess[key] for key in preprocess if key != "records"},
                                                                    "records": preprocess["records"]}
            if bridge:
                evidence[run_id]["saved_asr_provenance"] = {key: provenance[key] for key in (
                    "operation", "source_result", "source_result_sha256", "source_adapter_sha256", "exporter_sha256",
                    "checkpoint", "checkpoint_file_sha256", "asr_config", "asr_cuda_evidence", "window_asr_cuda_evidence",
                    "timing_semantics", "reference_text_used", "source_fa_times_used", "cache_classification", "new_asr_inference")}
                evidence[run_id]["bridge_input"] = reused["input"]
                evidence[run_id]["performance_scope"] = "New CTC stage only; upstream ASR cached; source Q0 FA not part of this configuration"
            elif result.get("route") == "W1":
                evidence[run_id]["saved_asr_provenance"] = {
                    "source_result": str(saved), "source_result_sha256": digest(saved),
                    "source_harness_sha256": digest(saved.parent / "manifest.json"),
                    "asr_devices": saved_result["devices"]["asr"], "models": proof(saved_result, saved_harness)["models"],
                    "parameters": saved_result["effective_parameters"], "input": saved_result["input"],
                    "asr_reused": True, "new_asr_inference": False}
                evidence[run_id]["performance_scope"] = "New CTC stage only; saved W0 ASR reused"
        run_records[(route, chapter)] = record
        print(json.dumps({"derived_run": run_id, "status": record["status"]}), flush=True)
    main = {"schema_version": 1, "manifest_id": "dev-five-chapters-ref2-eval2", "frozen": True,
            "reference_kind": "srt_display", "evaluation_config": {"status": "exploratory", "rule_version": RULE_VERSION},
            "scenes": scenes, "routes": [{"id": route, "configuration_id": config,
                                            "runs": [run_records[(route, chapter)] for chapter in CHAPTERS]}
                                           for route, config, _ in routes]}
    write(output / "main-manifest.json", main)
    report = aggregate_manifest(main, base=output, bootstrap=True)
    # Stability is independent of scoring and hardware execution qualification.
    # Retain all metrics even when a generated window demonstrably hits its cap.
    stability = {route: {"stability_eligibility": False if any(evidence.get(template.format(chapter=c), {}).get("token_limit_reached_windows", 0)
                                                             for c in CHAPTERS) else None,
                         "reason": "generation_token_limit_reached" if any(evidence.get(template.format(chapter=c), {}).get("token_limit_reached_windows", 0)
                                                                          for c in CHAPTERS) else "no_recorded_token_limit_hit; full_film_unverified"}
                 for route, _, template in routes}
    for route, _, template in routes:
        if any(evidence.get(template.format(chapter=c), {}).get("decoding_sanity", {}).get("single_temperature_exhausted_compression_fallback")
               for c in CHAPTERS):
            stability[route] = {"stability_eligibility": False,
                                "reason": "single_temperature_exhausted_upstream_compression_fallback",
                                "criterion": "observed compression exceeds this run's upstream configured threshold; no alternate temperatures available"}
        elif route == "W0-native" and any(evidence.get(template.format(chapter=c), {}).get("decoding_sanity", {}).get("compression_threshold_exceeded_segment_count")
                                          for c in CHAPTERS):
            stability[route] = {"stability_eligibility": False,
                                "reason": "unresolved_repetitive_generation_above_upstream_compression_threshold",
                                "limitation": "Repeated output is observed; acoustic truth has not been adjudicated"}
    report["generation_stability_observation"] = stability
    if any(route["summary"]["timing"]["denominator"] != 195 for route in report["routes"]):
        raise ValueError("Full denominator was lost")
    write(output / "main-report.json", report)
    component = {**main, "manifest_id": "dev-ch01-fixed-asr-component-ref2-eval2", "scenes": scenes[:1],
                 "routes": [{"id": route, "configuration_id": config, "runs": [run_records[(route, 1)]]}
                            for route, config, _ in (*ROUTES, *COMPONENTS)]}
    write(output / "component-manifest.json", component)
    write(output / "component-report.json", aggregate_manifest(component, base=output, bootstrap=True))
    write(output / "execution-evidence.json", {"schema_version": 1, "runs": evidence})
    print(json.dumps(json_safe({"output": str(output), "table_rows": report["table_rows"]}), ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-qwen", action="store_true")
    parser.add_argument("--include-crisp", action="store_true")
    parser.add_argument("--include-extra-whisper", action="store_true")
    parser.add_argument("--include-cross-family", action="store_true")
    parser.add_argument("--include-whisper-components", action="store_true")
    parser.add_argument("--include-normalized-ctc", action="store_true")
    args = parser.parse_args()
    build(args.output, include_qwen=args.include_qwen, include_crisp=args.include_crisp,
          include_extra_whisper=args.include_extra_whisper, include_cross_family=args.include_cross_family,
          include_whisper_components=args.include_whisper_components, include_normalized_ctc=args.include_normalized_ctc)


if __name__ == "__main__":
    main()
