"""Audit terminal original-audio VAD ablations and score an immutable registry."""

from __future__ import annotations

import argparse
from array import array
import hashlib
from pathlib import Path
import sys
from typing import Any

from experiments.analysis.build_development import gpu_verified
from experiments.analysis.build_round2 import input_identity
from experiments.analysis.build_validation import upstream_evidence
from experiments.analysis.build_heldout import qwen_asr_phase_complete
from experiments.components import evaluate as generic
from experiments.components import run_vad as runner
from experiments.components.finalize_manifest import _require_entry, checked
from experiments.components.qwen_vad import (
    ASR_CONFIG_SHA256, ASR_ID, ASR_REVISION, ASR_SHA256, MAX_NEW_TOKENS,
    cuda_evidence, validate_vad as qwen_intervals,
)
from experiments.components.run import ROOT, LOCAL, digest, read, write_new
from experiments.components.separate import read_pcm
from experiments.components.w0_vad import validate_vad as w0_contract
from experiments.qwen.run_cross import validate_ctc_evidence

REVISION = "terminal-original-audio-vad-evaluation-v1"
TERMINAL = {"completed", "failed", "blocked"}
REQUIRED_SHARED = (
    "experiments/run_experiment.py", "experiments/components/run.py", "experiments/components/run_vad.py",
    "experiments/components/separate.py", "experiments/components/vad.py", "experiments/components/w0_vad.py",
    "experiments/components/qwen_vad.py", "experiments/whisper/run.py", "experiments/whisper/ctc_audio.py",
    "experiments/whisper/ctc_forced.py", "experiments/whisper/ctc_transition.py", "experiments/qwen/run_qwen.py",
    "experiments/qwen/run_cross.py",
)


def float32_pcm(pcm: bytes) -> bytes:
    """Reproduce exact PCM16 / 32768 float32 bytes without optional NumPy."""
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    waveform = array("f", (value / 32768 for value in samples))
    if sys.byteorder != "little":
        waveform.byteswap()
    return waveform.tobytes()


def verify_qwen(raw: dict[str, Any], vad: dict[str, Any], pcm: bytes,
                identity: dict[str, Any], clip: dict[str, Any], vad_sha: str) -> bool:
    """Prove complete exact VAD windows independently of any downstream CTC."""
    intervals = qwen_intervals(vad, identity, pcm, clip["offset"])
    if raw.get("schema_version") != 1 or raw.get("backend") != "official-qwen-native-hf-vad":
        raise ValueError("Invalid VAD Qwen ASR document")
    expected = {"language": "ja", "dtype": "bfloat16", "attention": "sdpa", "max_new_tokens": MAX_NEW_TOKENS,
        "do_sample": False, "batch_size": 1, "offset": clip["offset"], "asr_only": True,
        "offline": True, "alignment_only": None}
    if any(raw.get("config", {}).get(key) != value for key, value in expected.items()) or raw.get("cache_reused") is not False:
        raise ValueError("VAD Qwen ASR configuration differs from the fixed candidate")
    info = raw.get("models", {}).get("asr", {})
    hashes = raw.get("checkpoint_file_sha256", {}).get("asr", {})
    if (info.get("id") != ASR_ID or info.get("revision") != ASR_REVISION
            or hashes.get("model.safetensors") != ASR_SHA256 or hashes.get("config.json") != ASR_CONFIG_SHA256):
        raise ValueError("VAD Qwen checkpoint identity differs")
    input_identity(raw, {"audio_sha256": identity["file_sha256"], "reference_unchanged": True}, clip)
    experimental = raw.get("experimental_vad", {})
    if (experimental.get("file_sha256") != vad_sha or experimental.get("sample_mapping_exact") is not True
            or experimental.get("concatenated_audio") is not False or experimental.get("reference_text_used") is not False
            or experimental.get("empty_speech") is not (not intervals)):
        raise ValueError("VAD Qwen manifest/source mapping differs")
    waveform = float32_pcm(pcm)
    if (raw.get("input", {}).get("samples") != identity["samples"]
            or raw["input"].get("pcm_sha256") != hashlib.sha256(waveform).hexdigest()):
        raise ValueError("VAD Qwen full decoded float32 identity differs")
    windows = raw.get("windows", [])
    if len(windows) != len(intervals):
        raise ValueError("VAD Qwen ASR did not complete every declared interval")
    for window, interval in zip(windows, intervals):
        for key in ("start_sample", "end_sample", "offset", "source_start_sample", "source_end_sample_exclusive"):
            if window.get(key) != interval[key]:
                raise ValueError("VAD Qwen source window identity differs")
        begin, end = interval["start_sample"], interval["end_sample"]
        if (not isinstance(window.get("text"), str) or not isinstance(window.get("raw_asr"), str)
                or window.get("token_limit_reached") is not False
                or window.get("pcm_sha256") != hashlib.sha256(waveform[4 * begin:4 * end]).hexdigest()
                or window.get("crop_pcm16_sha256") != hashlib.sha256(pcm[2 * begin:2 * end]).hexdigest()):
            raise ValueError("VAD Qwen window text, generation limit or PCM identity invalid")
        cuda_evidence(window.get("asr_input_evidence", {}))
    if ("".join(window["text"] for window in windows) != raw.get("text")
            or raw.get("stage_execution", {}).get("asr") != ("executed" if intervals else "not_executed_empty_vad")):
        raise ValueError("VAD Qwen complete ASR text or execution stage differs")
    return bool(intervals)


def verify_bridge(bridge: dict[str, Any], raw: dict[str, Any], raw_path: Path,
                  identity: dict[str, Any], clip: dict[str, Any]) -> None:
    source = bridge.get("provenance", {})
    expected = [{"start": window["start_sample"] / 16000, "end": window["end_sample"] / 16000,
                 "text": window["text"]} for window in raw["windows"]]
    if (bridge.get("text") != raw["text"] or bridge.get("original_segments") != expected
            or bridge.get("offset_s") != clip["offset"]
            or bridge.get("input", {}).get("file_sha256") != identity["file_sha256"]
            or bridge["input"].get("pcm_sha256") != identity["pcm_sha256"]
            or bridge["input"].get("float32_pcm_sha256") != raw["input"]["pcm_sha256"]
            or source.get("source_result_sha256") != digest(raw_path)
            or Path(source.get("source_result", "")).resolve() != raw_path.resolve()
            or source.get("operation") != "fresh-qwen-vad-to-whisperx-ctc-bridge-v1"
            or source.get("reference_text_used") is not False or source.get("source_fa_times_used") is not False):
        raise ValueError("VAD raw ASR to original-audio CTC bridge identity invalid")


def verify_w0(result: dict[str, Any], vad: dict[str, Any], identity: dict[str, Any],
              clip: dict[str, Any], vad_sha: str) -> bool:
    contract = w0_contract(vad, identity, clip["offset"])
    input_identity(result, {"audio_sha256": identity["file_sha256"], "reference_unchanged": True}, clip)
    experimental = result.get("experimental_vad", {})
    if (experimental.get("file_sha256") != vad_sha
            or any(experimental.get(key) != value for key, value in contract.items())
            or result.get("input", {}).get("pcm_sha256") != identity["pcm_sha256"]):
        raise ValueError("W0 VAD full-input/clip contract identity invalid")
    params = result.get("effective_parameters", {}).get("transcribe", {})
    expected = {"language": "ja", "task": "transcribe", "beam_size": 5, "word_timestamps": True,
        "vad_filter": False, "chunk_length": 30, "condition_on_previous_text": False,
        "clip_timestamps": contract["clip_timestamps"]}
    if (any(params.get(key) != value for key, value in expected.items()) or result.get("offline_requested") is not True
            or "".join(segment["text"] for segment in result.get("original_segments", [])) != result.get("text")):
        raise ValueError("W0 VAD ASR configuration or complete text differs")
    asr = result.get("devices", {}).get("asr", {})
    if contract["empty_speech"]:
        if result["text"] or asr.get("inference_executed") is not False:
            raise ValueError("Empty VAD falsely claims ASR inference or text")
        return False
    if asr.get("device") != "cuda" or asr.get("compute_type") != "float16":
        raise ValueError("W0 VAD CUDA/precision evidence absent")
    return True


def baseline(route: str, clip: dict[str, Any], historical: dict[str, Any]) -> dict[str, Any]:
    entry = historical[f"{clip['id']}-{route}"]
    result, harness, artifacts = _require_entry(entry, clip)
    source_ok, source_info, source_paths = upstream_evidence(result)
    if route == "x0":
        validate_ctc_evidence(result)
        original_entry = historical[f"{clip['id']}-q0"]
        asr, asr_harness, asr_files = _require_entry(original_entry, clip)
        if (not source_ok or asr["text"] != result["text"]
                or source_info.get("source_result_sha256") != original_entry["output_sha256"]
                or Path(source_info.get("source_result", "")).resolve() != Path(original_entry["output"]).resolve()
                or not qwen_asr_phase_complete(asr, asr_harness, expected_audio_sha256=clip["audio_sha256"],
                    expected_offset=clip["offset"], expected_duration=clip["duration"])):
            raise ValueError("Historical X0 ASR/CTC source chain invalid")
        artifacts.extend(asr_files)
    elif not source_ok or not gpu_verified(result, harness):
        raise ValueError("Historical Whisper candidate GPU/source chain invalid")
    if route == "w1":
        validate_ctc_evidence(result)
    artifacts.extend({"path": str(path), "sha256": digest(path)} for path in source_paths)
    return {"clip_id": clip["id"], "run_id": entry["id"], "status": "completed", "execution_verified": True,
        "result_path": entry["output"], "result_sha256": entry["output_sha256"],
        "input_audio_path": clip["audio"], "input_audio_sha256": clip["audio_sha256"],
        "evidence": {"artifacts": artifacts, "historical_harness_wall_seconds": harness.get("wall_seconds"),
            "cost_scope": "Historical process only; reused Q0 may include native FA work not consumed by X0"}}


def _slot(task: dict[str, Any], record: dict[str, Any], clip: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]]:
    path = Path(task["output"])
    document = read(path) if path.exists() else None
    harness_path = ROOT / ".local/results" / task["id"] / "manifest.json"
    harness = read(harness_path) if harness_path.exists() else {}
    slot = {"clip_id": clip["id"], "run_id": task["id"], "status": "invocation_failed",
        "execution_verified": False, "input_audio_path": clip["audio"], "input_audio_sha256": clip["audio_sha256"],
        "evidence": {"progress_status": record["status"], "artifacts": [
            {"path": path, "sha256": expected} for path, expected in record.get("artifact_sha256", {}).items()],
            "harness_wall_seconds": harness.get("wall_seconds")}}
    if document and document.get("schema_version") == 1 and isinstance(document.get("text"), str):
        slot.update(result_path=str(path), result_sha256=digest(path))
    return slot, document, harness


def preserve_asr(slot: dict[str, Any], raw: dict[str, Any], clip: dict[str, Any], manifest_path: Path) -> None:
    """Persist independently complete ASR text without fabricating alignment times."""
    preserved = manifest_path.parent / "preserved-asr" / (slot["run_id"] + ".json")
    write_new(preserved, {"schema_version": 1, "text": raw["text"], "units": [], "cues": [],
        "input_sha256": clip["audio_sha256"], "source_start_seconds": clip["offset"], "duration_seconds": clip["duration"]})
    slot.update(status="alignment_failed", result_path=str(preserved), result_sha256=digest(preserved),
        failure_reason="independently_complete_vad_asr_preserved_after_dependent_ctc_failure")


def phase_harness(task: dict[str, Any], clip: dict[str, Any], plan: dict[str, Any]) -> None:
    """A failed enclosing process may still bind a complete persisted ASR phase."""
    path = ROOT / ".local/results" / task["id"] / "manifest.json"
    harness = read(path)
    if (harness.get("id") != task["id"] or harness.get("command") != task["command"]
            or harness.get("audio_sha256") != clip["audio_sha256"] or harness.get("reference_unchanged") is not True
            or any(harness.get(key) != clip["source_srt_sha256"] for key in
                   ("reference_sha256_expected", "reference_sha256_before", "reference_sha256_after"))):
        raise ValueError("Persisted ASR phase harness command/input/reference identity invalid")
    relative = str(Path(task["command"][1]).resolve().relative_to(ROOT))
    sources = harness.get("source_sha256", {})
    for required in (relative, str(Path("experiments/run_experiment.py"))):
        expected = plan["source_sha256"].get(str((ROOT / required).resolve()))
        if not expected or sources.get(required) != expected or digest(path.parent / "source" / required) != expected:
            raise ValueError("Persisted ASR phase source snapshot identity invalid")


def assemble(name: str, manifest_path: Path) -> dict[str, Any]:
    """Only complete terminal batches are eligible for a scoring manifest."""
    runner.validate_name(name)
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_relative_to((ROOT / ".local").resolve()) or manifest_path.exists():
        raise ValueError("VAD evaluation manifest must be a new private .local file")
    plan_path = LOCAL / name / "plan.json"
    plan, plan_identity = checked(plan_path)
    if plan.get("frozen") is not True or plan.get("id") != name:
        raise ValueError("A matching frozen VAD plan is required")
    tasks = {(task["clip"], task["stage"]): task for task in plan["tasks"]}
    if len(tasks) != len(plan["tasks"]):
        raise ValueError("Duplicate VAD task registry")
    progress = {}
    for task in plan["tasks"]:
        path = LOCAL / name / "progress" / (task["id"] + ".json")
        if not path.is_file():
            raise ValueError("VAD batch is not terminal; no partial scoring")
        record = read(path)
        if record.get("status") not in TERMINAL:
            raise ValueError("VAD batch contains a nonterminal task")
        runner.verify_progress(task, record, plan_identity["sha256"])
        progress[task["id"]] = record
    runner.verify_sources(plan)
    # New scoring files are bound separately, never inserted into a prior runner freeze.
    required = {str((ROOT / relative).resolve()) for relative in REQUIRED_SHARED}
    required.update(str(Path(task["command"][1]).resolve()) for task in plan["tasks"])
    sources = {}
    for path in sorted(required):
        expected = plan["source_sha256"].get(path)
        if not expected or digest(path) != expected:
            raise ValueError(f"Executed/validation source differs from frozen VAD plan: {path}")
        sources[path] = expected
    previous, previous_identity = checked(ROOT / ".local/round2/progress.json")
    configurations = {route: {"id": route, "configuration_id": route, "runs": []}
        for route in ("w0-baseline", "w0-vad", "w1-baseline", "x0-baseline", "x0-vad")}
    receipts = []
    for clip in plan["clips"]:
        if {(clip["id"], stage) for stage in ("vad", "w0", "qwen-asr", "x0")} - set(tasks):
            raise ValueError("VAD plan lacks a required complete task slot")
        runner.verify_clip(clip)
        pcm, identity = read_pcm(Path(clip["audio"]))
        for route in ("w0", "w1", "x0"):
            configurations[f"{route}-baseline"]["runs"].append(baseline(route, clip, previous["tasks"]))
        vad_task = tasks[(clip["id"], "vad")]
        vad_record = progress[vad_task["id"]]
        vad_ok = vad_record["status"] == "completed"
        vad = read(vad_task["output"]) if vad_ok else None
        vad_sha = digest(vad_task["output"]) if vad_ok else None
        if vad_ok:
            runner.verify_harness(vad_task, clip, plan)
            w0_contract(vad, identity, clip["offset"])
        for stage in ("w0", "x0"):
            task = tasks[(clip["id"], stage)]
            record = progress[task["id"]]
            slot, result, harness = _slot(task, record, clip)
            if record["status"] == "completed":
                if not vad_ok:
                    raise ValueError("Completed downstream VAD route lacks completed VAD")
                runner.verify_harness(task, clip, plan)
                if stage == "w0":
                    eligible = verify_w0(result, vad, identity, clip, vad_sha)
                else:
                    asr_task = tasks[(clip["id"], "qwen-asr")]
                    asr_record = progress[asr_task["id"]]
                    if asr_record["status"] != "completed":
                        raise ValueError("Completed X0 VAD CTC lacks complete upstream ASR")
                    runner.verify_harness(asr_task, clip, plan)
                    raw = read(asr_task["output"])
                    eligible = verify_qwen(raw, vad, pcm, identity, clip, vad_sha)
                    bridge = read(asr_task["additional_outputs"][0])
                    verify_bridge(bridge, raw, Path(asr_task["output"]), identity, clip)
                    if result["text"] != raw["text"] or result.get("original_segments") != bridge["original_segments"]:
                        raise ValueError("X0 VAD CTC altered complete upstream text/windows")
                    validate_ctc_evidence(result)
                slot.update(status="completed" if eligible else "execution_unverified", execution_verified=eligible)
            elif stage == "x0" and vad_ok:
                asr_task = tasks[(clip["id"], "qwen-asr")]
                asr_record = progress[asr_task["id"]]
                raw = read(asr_task["output"]) if Path(asr_task["output"]).is_file() else None
                complete_asr = asr_record["status"] == "completed"
                if complete_asr:
                    runner.verify_harness(asr_task, clip, plan)
                    verify_qwen(raw, vad, pcm, identity, clip, vad_sha)
                elif raw and raw.get("schema_version") == 1 and isinstance(raw.get("text"), str):
                    try:
                        phase_harness(asr_task, clip, plan)
                        if raw.get("adapter_sha256") != sources[str((ROOT / "experiments/components/qwen_vad.py").resolve())]:
                            raise ValueError("Failed ASR source identity differs")
                        verify_qwen(raw, vad, pcm, identity, clip, vad_sha)
                        complete_asr = True
                    except (OSError, KeyError, ValueError) as error:
                        complete_asr = False
                        slot["evidence"]["upstream_complete_retention_rejected"] = {
                            "error_type": type(error).__name__, "reason": str(error)}
                if complete_asr:
                    preserve_asr(slot, raw, clip, manifest_path)
                elif raw and raw.get("schema_version") == 1 and isinstance(raw.get("text"), str):
                    slot.update(result_path=asr_task["output"], result_sha256=digest(asr_task["output"]))
            configurations[f"{stage}-vad"]["runs"].append(slot)
        receipts.append({"clip_id": clip["id"], "vad_status": vad_record["status"],
            "vad_manifest": {"path": vad_task["output"], "sha256": vad_sha},
            "chunks": len(vad["chunks"]) if vad_ok else None,
            "retained_samples": sum(chunk["end_sample_exclusive"] - chunk["start_sample"] for chunk in vad["chunks"]) if vad_ok else None,
            "original_samples": identity["samples"], "cost_scope": "Shared VAD counted once for each complete downstream route",
            "stage_harness_wall_seconds": {stage: read(ROOT / ".local/results" / tasks[(clip["id"], stage)]["id"] / "manifest.json").get("wall_seconds")
                if (ROOT / ".local/results" / tasks[(clip["id"], stage)]["id"] / "manifest.json").is_file() else None
                for stage in ("vad", "w0", "qwen-asr", "x0")}})
    sources[str(Path(__file__).resolve())] = digest(Path(__file__))
    manifest = {"schema_version": 1, "manifest_id": name, "frozen": True, "strict_hashes": True,
        "clips": plan["clips"], "configurations": list(configurations.values()), "source_sha256": sources,
        "evaluation_scope": "Exposed fixed four-window component ablation; W1 keeps its bundled native VAD as an unchanged reference",
        "assembly": {"revision": REVISION, "plan": plan_identity, "historical_progress": previous_identity,
            "receipts": receipts, "failure_policy": "Complete ASR survives dependent CTC failure; incomplete ASR remains invocation failure with numeric partial diagnostics",
            "execution_policy": "Empty VAD is scored with the full denominator but does not claim ASR GPU execution"}}
    write_new(manifest_path, manifest)
    return manifest


def build(name: str, manifest_path: Path, output: Path) -> dict[str, Any]:
    if (not output.resolve().is_relative_to((ROOT / ".local").resolve())
            or output.resolve() == (ROOT / ".local").resolve() or output.resolve().exists()):
        raise FileExistsError("Choose a new VAD analysis snapshot")
    manifest = assemble(name, manifest_path)
    report = generic.build(manifest_path, output)
    write_new(output / "vad-evidence.json", manifest["assembly"])
    return report


def main() -> None:
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build(args.name, args.manifest, args.output)
    print(json.dumps({"revision": REVISION, "output": str(args.output.resolve()),
        "table_rows": report["pooled"]["table_rows"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
