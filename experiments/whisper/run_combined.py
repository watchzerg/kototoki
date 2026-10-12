"""Fresh offline W0 no-context fallback -> normalized standard CTC experiment."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time


PROJECT = Path(__file__).resolve().parents[2]
SOURCE_FILES = ("experiments/whisper/run_combined.py", "experiments/whisper/run.py",
                "experiments/whisper/ctc_audio.py", "experiments/whisper/ctc_forced.py",
                "experiments/whisper/ctc_transition.py", "experiments/qwen/run_cross.py")


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def load_completed(path: Path) -> dict:
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("status", "ok") != "ok":
        raise ValueError(f"Stage did not complete: {path}")
    return result


def load_ctc_validator(source: Path):
    """Load only stdlib code from this run's frozen validation dependency."""
    spec = importlib.util.spec_from_file_location("kototoki_combined_ctc_validator", source)
    if spec is None or spec.loader is None:
        raise ValueError("Cannot load frozen CTC evidence validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate_ctc_evidence, module.AlignmentEvidenceError


def validate_asr(result: dict, adapter_hash: str, audio_hash: str, offset: float) -> dict:
    expected = {"language": "ja", "task": "transcribe", "beam_size": 5, "word_timestamps": True,
                "vad_filter": False, "chunk_length": 30, "condition_on_previous_text": False}
    options = result.get("effective_parameters", {}).get("transcribe", {})
    if options != expected or result.get("route") != "W0":
        raise ValueError("Fresh W0 configuration differs from no-context native fallback")
    if result.get("implementation", {}).get("sha256") != adapter_hash:
        raise ValueError("ASR source differs from executed frozen snapshot")
    if result.get("input", {}).get("file_sha256") != audio_hash or result.get("offset_s") != offset:
        raise ValueError("ASR audio identity/source offset differs from this pipeline")
    if result.get("cached_inference") is not False or result.get("offline_requested") is not True:
        raise ValueError("ASR must be fresh offline inference")
    device = result.get("devices", {}).get("asr", {})
    if device.get("device") != "cuda" or device.get("compute_type") != "float16" or device.get("device_index") != [0]:
        raise ValueError("ASR actual CUDA:0 float16 execution is unverified")
    packages = {key.lower(): value for key, value in result.get("environment", {}).get("packages", {}).items()}
    if packages.get("faster-whisper") != "1.2.1" or packages.get("ctranslate2") != "4.8.2":
        raise ValueError("ASR package versions differ from frozen W0")
    info = result.get("native", {}).get("info", {}).get("transcription_options", {})
    if info.get("temperatures") != [0.0, .2, .4, .6, .8, 1.0]:
        raise ValueError("Native temperature fallback was not retained")
    segments = result.get("original_segments", [])
    if "text" not in result or "".join(s["text"] for s in segments) != result["text"]:
        raise ValueError("ASR original segments do not preserve complete text")
    threshold = info.get("compression_ratio_threshold")
    risk = [{"segment_id": s.get("id"), "start": s.get("start"), "end": s.get("end"),
             "compression_ratio": s.get("compression_ratio"), "temperature": s.get("temperature"),
             "avg_logprob": s.get("avg_logprob"), "no_speech_prob": s.get("no_speech_prob"),
             "token_count": len(s.get("tokens", []))} for s in segments
            if threshold is not None and s.get("compression_ratio", 0) > threshold]
    return {"native_compression_ratio_threshold": threshold, "above_threshold_segments": risk,
            "unresolved_generation_risk": bool(risk), "text_cleaned": False,
            "token_cap_evidence": "not exposed by native segment API; absence of a cap marker is not proof of no cap",
            "interpretation": "Diagnostic risk; do not infer every repeated phrase is acoustically wrong"}


def validate_ctc_identity(result: dict, asr: dict, source_hash: str, audio_hash: str, offset: float) -> None:
    if (result.get("text") != asr["text"] or result.get("original_segments") != asr["original_segments"]
            or result.get("input", {}).get("file_sha256") != audio_hash
            or result.get("input", {}).get("pcm_sha256") != asr["input"]["pcm_sha256"]
            or result.get("offset_s") != offset):
        raise ValueError("CTC changed original text/segments, audio identity or source offset")
    if result.get("implementation", {}).get("sha256") != source_hash:
        raise ValueError("CTC source differs from executed frozen snapshot")
    options = result.get("effective_parameters", {})
    if (result.get("route") != "W1" or options.get("asr_reused") is not True
            or options.get("ctc_normalize") is not True or options.get("padding") != 0.0
            or options.get("interpolate_method") != "nearest"
            or result.get("experimental_alignment", {}).get("time_semantics") != "ctc_nonblank_token_span"):
        raise ValueError("CTC stage does not match normalized standard token-span configuration")


def run_pipeline(args: argparse.Namespace) -> dict:
    started = time.perf_counter()
    output = args.output.resolve()
    if not output.is_relative_to(PROJECT / ".local"):
        raise ValueError("Private pipeline output must be inside project .local")
    if not args.audio.is_file() or not math.isfinite(args.offset):
        raise ValueError("Provide an existing WAV and finite source offset")
    for interpreter in (args.w0_python, args.whisper_python):
        if not interpreter.is_file():
            raise FileNotFoundError(interpreter)
    stage_root = output.parent / (output.stem + "-stages")
    if output.exists() or stage_root.exists():
        raise FileExistsError("Choose fresh output/stage paths; never overwrite evidence")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump({"status": "starting", "route": "W1-combined"}, stream)
    stage_root.mkdir()
    manifest = {"schema_version": 1, "route": "W1-combined", "status": "starting",
                "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "audio": str(args.audio.resolve()), "audio_sha256": sha256(args.audio), "offset_s": args.offset,
                "cache_classification": "fresh_end_to_end", "new_asr_inference": None,
                "new_alignment_inference": None, "source_files": {}, "stages": [],
                "experiment_status": "postlock_exploratory_branch_not_original_blind_candidate",
                "performance_context": "Sequential cold subprocesses; root harness owns GPU queue/sampling",
                "wall_scope": "Validation, source snapshots and cold stages; use outer harness wall for total process"}
    manifest_path = stage_root / "pipeline-manifest.json"
    asr = ctc = None
    phase = "preparation"
    alignment_error = ()
    try:
        source_root = stage_root / "source"
        for relative in SOURCE_FILES:
            copied = source_root / relative
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PROJECT / relative, copied)
            manifest["source_files"][relative] = {"path": str(copied), "sha256": sha256(copied)}
        validate_evidence, alignment_error = load_ctc_validator(source_root / "experiments/qwen/run_cross.py")
        # The frozen adapter resolves its allowed .local root relative to itself.
        products = source_root / ".local/stages"
        products.mkdir(parents=True)
        asr_path, ctc_path = products / "asr.json", products / "ctc.json"
        manifest.update({"asr_result": str(asr_path), "ctc_result": str(ctc_path)})
        environment = os.environ.copy()
        environment.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1"})

        def execute(stage: str, command: list[str], artifact: Path) -> dict:
            log = stage_root / (stage + ".log")
            record = {"stage": stage, "command": command, "output": str(artifact), "log": str(log), "status": "running"}
            manifest["stages"].append(record)
            write_json(manifest_path, manifest)
            mark = time.perf_counter()
            try:
                with log.open("x", encoding="utf-8") as stream:
                    completed = subprocess.run(command, cwd=PROJECT, env=environment, stdout=stream,
                                               stderr=subprocess.STDOUT, check=False)
                record.update({"returncode": completed.returncode,
                               "status": "completed" if completed.returncode == 0 else "failed"})
            except Exception as error:
                record.update({"status": "failed", "error_type": type(error).__name__, "error": str(error)})
                raise
            finally:
                record["wall_seconds"] = time.perf_counter() - mark
                if artifact.exists():
                    record["output_sha256"] = sha256(artifact)
                write_json(manifest_path, manifest)
            if completed.returncode:
                raise RuntimeError(f"{stage} failed with exit {completed.returncode}; see {log}")
            return load_completed(artifact)

        adapter = source_root / "experiments/whisper/run.py"
        shared = ["--audio", str(args.audio.resolve()), "--offset", str(args.offset),
                  "--cache", str(args.whisper_cache.resolve()), "--nltk-data", str(args.nltk_data.resolve())]
        for directory in args.dll_dir:
            shared.extend(["--dll-dir", str(directory.resolve())])
        phase = "asr"
        asr = execute("asr", [str(args.w0_python.resolve()), str(adapter), "--route", "W0",
                              "--model", str(args.asr_model.resolve()), "--no-condition-previous", "--chunk", "30",
                              "--output", str(asr_path), *shared], asr_path)
        manifest["new_asr_inference"] = True
        source_hash = manifest["source_files"]["experiments/whisper/run.py"]["sha256"]
        manifest["generation_stability_observation"] = validate_asr(asr, source_hash, manifest["audio_sha256"], args.offset)
        phase = "ctc"
        ctc = execute("ctc", [str(args.whisper_python.resolve()), str(adapter), "--route", "W1",
                              "--align-model", str(args.ctc_model.resolve()), "--asr-result", str(asr_path),
                              "--ctc-normalize", "--ctc-forced-align", "--output", str(ctc_path), *shared], ctc_path)
        observations = ctc.get("devices", {}).get("aligner", {}).get("forward_observation", [])
        manifest["new_alignment_inference"] = bool(observations)
        validate_ctc_identity(ctc, asr, source_hash, manifest["audio_sha256"], args.offset)
        evidence = validate_evidence(ctc)
        manifest["alignment_evidence"] = evidence
        manifest["new_alignment_inference"] = evidence["executed"]
        if sha256(args.audio) != manifest["audio_sha256"]:
            raise ValueError("Source audio changed during pipeline")
        manifest.update({"status": "completed", "wall_seconds": time.perf_counter() - started,
                         "ctc_forward_count": len(observations),
                         "stage_cache": {"asr": "fresh", "ctc_asr_input": "reused_from_this_run_fresh_asr",
                                         "ctc_alignment": "fresh" if evidence["executed"] else "no_forward_observed"}})
        write_json(manifest_path, manifest)
        result = {**ctc, "route": "W1-combined", "alignment_route": "W1", "cached_inference": False,
                  "pipeline": {**manifest, "manifest": str(manifest_path), "manifest_sha256": sha256(manifest_path),
                               "asr_cuda_evidence": asr["devices"]["asr"], "ctc_cuda_evidence": ctc["devices"]["aligner"]},
                  "combined_implementation": {"path": str(Path(__file__)), "sha256": sha256(Path(__file__))}}
        write_json(output, result)
        return result
    except Exception as error:
        classification = "alignment_failure" if phase == "ctc" else "asr_failure" if phase == "asr" else "pipeline_failure"
        manifest.update({"status": "failed", "failure_stage": phase, "failure_classification": classification,
                         "wall_seconds": time.perf_counter() - started, "error_type": type(error).__name__, "error": str(error)})
        if isinstance(error, alignment_error):
            manifest["alignment_evidence"] = {"status": "failed", "reason": error.reason, **error.details}
        write_json(manifest_path, manifest)
        # Retain any full stage transcript unchanged. Failed timing is never
        # promoted to success; raw stage output/log/source snapshots also remain.
        retained = ctc or asr or {}
        write_json(output, {**retained, "status": "failed", "route": "W1-combined",
                            "error_type": type(error).__name__, "error": str(error),
                            "failure_classification": classification, "recognition_preserved": asr is not None,
                            "pipeline": {**manifest, "manifest": str(manifest_path), "manifest_sha256": sha256(manifest_path)}})
        raise


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--audio", type=Path, required=True)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument("--offset", type=float, default=0.0)
    result.add_argument("--w0-python", type=Path, default=PROJECT / ".local/envs/whisper-w0-py312/Scripts/python.exe")
    result.add_argument("--whisper-python", type=Path, default=PROJECT / ".local/envs/whisper-latest/Scripts/python.exe")
    result.add_argument("--asr-model", type=Path, default=PROJECT / ".local/models/faster-whisper-large-v3")
    result.add_argument("--ctc-model", type=Path, default=PROJECT / ".local/models/wav2vec2-large-xlsr-53-japanese")
    result.add_argument("--whisper-cache", type=Path, default=PROJECT / ".local/cache/whisper-runtime")
    result.add_argument("--nltk-data", type=Path, default=PROJECT / ".local/cache/whisper-nltk")
    result.add_argument("--dll-dir", type=Path, action="append", default=[])
    return result


if __name__ == "__main__":
    value = run_pipeline(parser().parse_args())
    print(json.dumps({"status": "ok", "manifest": value["pipeline"]["manifest"],
                      "wall_seconds": value["pipeline"]["wall_seconds"]}))
