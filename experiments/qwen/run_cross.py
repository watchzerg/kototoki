"""Fresh offline Qwen ASR -> normalized standard CTC, inside the root GPU queue."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time
import unicodedata


PROJECT = Path(__file__).resolve().parents[2]
SOURCE_FILES = (
    "experiments/qwen/run_qwen.py", "experiments/qwen/export_ctc_input.py",
    "experiments/qwen/run_cross.py", "experiments/whisper/run.py",
    "experiments/whisper/ctc_audio.py", "experiments/whisper/ctc_forced.py",
    "experiments/whisper/ctc_transition.py",
)


def sha256(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def load_completed(path: Path) -> dict:
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("status", "ok") != "ok":
        raise ValueError(f"Stage did not complete: {path}")
    return result


def validate_fresh_asr(result: dict, adapter_hash: str) -> None:
    if result.get("adapter_sha256") != adapter_hash:
        raise ValueError("ASR source identity differs from the executed frozen copy.")
    config = result.get("config", {})
    expected = {"asr_only": True, "window_seconds": 30.0, "language": "ja", "dtype": "bfloat16",
                "attention": "sdpa", "max_new_tokens": 4096, "do_sample": False,
                "batch_size": 1, "offline": True, "alignment_only": None}
    if any(config.get(key) != value for key, value in expected.items()):
        raise ValueError("ASR configuration differs from the frozen X0 ASR arm.")
    if result.get("cache_reused") is not False or result.get("stage_execution") != {
            "asr": "executed", "aligner": "not_requested_asr_only"}:
        raise ValueError("Pipeline requires fresh ASR and no Qwen alignment stage.")
    if not result.get("windows") or any(w.get("token_limit_reached") is not False for w in result["windows"]):
        raise ValueError("ASR generation cap or missing windows; do not continue the pipeline.")


class AlignmentEvidenceError(ValueError):
    def __init__(self, reason: str, details: dict | None = None):
        self.reason = reason
        self.details = details or {}
        super().__init__(f"Alignment evidence failure: {reason}")


def validate_ctc_evidence(result: dict) -> dict:
    aligner = result.get("devices", {}).get("aligner", {})
    forwards = aligner.get("forward_observation", [])
    records = result.get("experimental_alignment", {}).get("records", [])
    preprocessing = result.get("experimental_preprocessing", {}).get("records", [])
    if not str(aligner.get("model", "")).startswith("cuda:"):
        raise AlignmentEvidenceError("model_device_unverified")
    lexical_text = any(unicodedata.category(char)[0] in "LN" for char in result["text"])
    if not forwards and not records and not preprocessing and not lexical_text:
        return {"status": "no_forward_empty_or_nonlexical_text", "executed": False,
                "forward_count": 0, "decoder_count": 0, "normalization_count": 0}
    if not forwards or any(not str(device).startswith("cuda:") for device in forwards):
        raise AlignmentEvidenceError("model_forward_device_unverified")
    failures = [{"segment_index": record.get("segment_index"), "failure": record.get("failure")}
                for record in records if "failure" not in record or record["failure"] is not None]
    if failures:
        raise AlignmentEvidenceError("decoder_failed", {"decoder_failures": failures})
    if not records or not preprocessing:
        raise AlignmentEvidenceError("missing_decoder_or_normalization_records")
    if any(not str(record.get("actual_input_device", "")).startswith("cuda:") for record in preprocessing):
        raise AlignmentEvidenceError("normalization_input_device_unverified")
    if any(not str(record.get("decoder_input_device", "")).startswith("cuda:")
           or not str(record.get("decoder_output_device", "")).startswith("cuda:") for record in records):
        raise AlignmentEvidenceError("decoder_device_unverified")
    decoder_indices = [record.get("segment_index") for record in records]
    normalization_indices = [record.get("segment_index") for record in preprocessing]
    if (len(records) != len(forwards) or len(preprocessing) != len(forwards)
            or any(type(index) is not int or index < 0 for index in decoder_indices)
            or len(set(decoder_indices)) != len(decoder_indices)
            or decoder_indices != normalization_indices):
        raise AlignmentEvidenceError("normalization_decoder_forward_mapping_mismatch")
    return {"status": "executed_cuda_verified", "executed": True,
            "forward_count": len(forwards), "decoder_count": len(records),
            "normalization_count": len(preprocessing)}


def run_pipeline(args: argparse.Namespace) -> dict:
    started = time.perf_counter()
    output = args.output.resolve()
    if not output.is_relative_to(PROJECT / ".local"):
        raise ValueError("Private pipeline output must be inside the project .local directory.")
    if not args.audio.is_file() or not math.isfinite(args.offset):
        raise ValueError("Provide an existing WAV and finite source offset.")
    for interpreter in (args.qwen_python, args.whisper_python):
        if not interpreter.is_file():
            raise FileNotFoundError(interpreter)
    stage_root = output.parent / (output.stem + "-stages")
    if output.exists() or stage_root.exists():
        raise FileExistsError("Choose a fresh output and stage directory; evidence is never overwritten.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as file:
        json.dump({"status": "starting", "route": "X0"}, file)
    stage_root.mkdir()
    manifest = {"schema_version": 1, "route": "X0", "status": "starting",
                "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "audio": str(args.audio.resolve()), "audio_sha256": sha256(args.audio),
                "offset_s": args.offset, "cache_classification": "fresh_end_to_end",
                "new_asr_inference": None, "new_alignment_inference": None,
                "source_files": {}, "stages": [],
                "performance_context": "Sequential cold subprocesses; root harness owns GPU serialization and sampling",
                "wall_scope": "Input validation, source snapshots, cold subprocesses, export and final stage checks; final result serialization and wrapper startup excluded, use root harness wall for full process"}
    manifest_path = stage_root / "pipeline-manifest.json"
    try:
        source_root = stage_root / "source"
        for relative in SOURCE_FILES:
            original = PROJECT / relative
            copied = source_root / relative
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, copied)
            manifest["source_files"][relative] = {"path": str(copied), "sha256": sha256(copied)}
        # The copied Whisper CLI restricts outputs to its own project-relative .local.
        products = source_root / ".local/stages"
        products.mkdir(parents=True)
        asr_path, bridge_path, ctc_path = [products / name for name in ("asr.json", "bridge.json", "ctc.json")]
        environment = os.environ.copy()
        environment.update({"HF_HOME": str(PROJECT / ".local/cache/qwen-hf"),
                            "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1"})

        def execute(stage: str, command: list[str], artifact: Path) -> dict:
            log = stage_root / (stage + ".log")
            record = {"stage": stage, "command": command, "output": str(artifact), "log": str(log), "status": "running"}
            manifest["stages"].append(record)
            write_json(manifest_path, manifest)
            mark = time.perf_counter()
            with log.open("x", encoding="utf-8") as stream:
                completed = subprocess.run(command, cwd=PROJECT, env=environment, stdout=stream,
                                           stderr=subprocess.STDOUT, check=False)
            record.update({"returncode": completed.returncode, "wall_seconds": time.perf_counter() - mark,
                           "status": "completed" if completed.returncode == 0 else "failed"})
            if artifact.exists():
                record["output_sha256"] = sha256(artifact)
            write_json(manifest_path, manifest)
            if completed.returncode:
                raise RuntimeError(f"{stage} failed with exit {completed.returncode}; see {log}")
            return load_completed(artifact)

        qwen_source = source_root / "experiments/qwen/run_qwen.py"
        asr = execute("asr", [str(args.qwen_python.resolve()), str(qwen_source), "--audio", str(args.audio.resolve()),
            "--output", str(asr_path), "--asr-model", str(args.asr_model.resolve()),
            "--aligner-model", str(args.qwen_aligner.resolve()), "--offset", str(args.offset),
            "--window-seconds", "30", "--asr-only"], asr_path)
        manifest["new_asr_inference"] = True
        validate_fresh_asr(asr, manifest["source_files"]["experiments/qwen/run_qwen.py"]["sha256"])
        bridge = execute("export", [str(args.qwen_python.resolve()), str(source_root / "experiments/qwen/export_ctc_input.py"),
            "--asr-result", str(asr_path), "--audio", str(args.audio.resolve()),
            "--offset", str(args.offset), "--output", str(bridge_path)], bridge_path)
        provenance = bridge["provenance"]
        if (provenance["source_result_sha256"] != sha256(asr_path)
                or provenance["exporter_sha256"] != manifest["source_files"]["experiments/qwen/export_ctc_input.py"]["sha256"]):
            raise ValueError("Bridge provenance differs from this pipeline's fresh artifacts.")
        ctc_command = [str(args.whisper_python.resolve()), str(source_root / "experiments/whisper/run.py"),
            "--route", "W1", "--audio", str(args.audio.resolve()), "--output", str(ctc_path),
            "--align-model", str(args.ctc_model.resolve()), "--asr-result", str(bridge_path),
            "--offset", str(args.offset), "--ctc-normalize", "--ctc-forced-align",
            "--cache", str(args.whisper_cache.resolve()), "--nltk-data", str(args.nltk_data.resolve())]
        for directory in args.dll_dir:
            ctc_command.extend(["--dll-dir", str(directory.resolve())])
        ctc = execute("ctc", ctc_command, ctc_path)
        manifest["new_alignment_inference"] = True
        if ctc["text"] != asr["text"] or ctc["input"]["file_sha256"] != manifest["audio_sha256"]:
            raise ValueError("CTC changed the full ASR text or audio identity.")
        if ctc["implementation"]["sha256"] != manifest["source_files"]["experiments/whisper/run.py"]["sha256"]:
            raise ValueError("CTC adapter source differs from its frozen copy.")
        aligner = ctc.get("devices", {}).get("aligner", {})
        observations = aligner.get("forward_observation", [])
        manifest["new_alignment_inference"] = bool(observations)
        if not ctc["effective_parameters"].get("asr_reused") or not ctc["effective_parameters"].get("ctc_normalize"):
            raise ValueError("CTC stage does not match the frozen component configuration.")
        if ctc["experimental_alignment"]["time_semantics"] != "ctc_nonblank_token_span":
            raise ValueError("CTC stage lacks standard forced token-span evidence.")
        alignment_evidence = validate_ctc_evidence(ctc)
        manifest["alignment_evidence"] = alignment_evidence
        manifest["new_alignment_inference"] = alignment_evidence["executed"]
        if sha256(args.audio) != manifest["audio_sha256"]:
            raise ValueError("Input audio changed during the pipeline.")
        manifest.update({"status": "completed", "wall_seconds": time.perf_counter() - started,
                         "ctc_forward_count": len(observations)})
        write_json(manifest_path, manifest)
        result = {**ctc, "route": "X0", "alignment_route": "W1", "cached_inference": False,
                  "pipeline": {**manifest, "manifest": str(manifest_path), "manifest_sha256": sha256(manifest_path),
                    "asr_result": str(asr_path), "bridge_result": str(bridge_path), "ctc_result": str(ctc_path),
                    "stage_cache": {"asr": "fresh", "ctc_asr_input": "reused_from_this_run_fresh_asr",
                                    "ctc_alignment": "fresh" if observations else "no_forward_observed"},
                    "asr_cuda_evidence": asr["environment"]["devices"]["asr"],
                    "ctc_cuda_evidence": aligner},
                  "cross_implementation": {"path": str(Path(__file__)), "sha256": sha256(Path(__file__))}}
        write_json(output, result)
        return result
    except Exception as error:
        manifest.update({"status": "failed", "wall_seconds": time.perf_counter() - started,
                         "error_type": type(error).__name__, "error": str(error)})
        if isinstance(error, AlignmentEvidenceError):
            manifest.update({"failure_classification": "alignment_failure",
                             "alignment_evidence": {"status": "failed", "reason": error.reason, **error.details}})
        write_json(manifest_path, manifest)
        write_json(output, {"status": "failed", "route": "X0", "error_type": type(error).__name__,
                            "error": str(error), "pipeline_manifest": str(manifest_path),
                            "failure_classification": manifest.get("failure_classification", "pipeline_failure")})
        raise


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--audio", type=Path, required=True)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument("--offset", type=float, default=0.0)
    result.add_argument("--qwen-python", type=Path, default=PROJECT / ".local/envs/qwen-hf-final/Scripts/python.exe")
    result.add_argument("--whisper-python", type=Path, default=PROJECT / ".local/envs/whisper-latest/Scripts/python.exe")
    result.add_argument("--asr-model", type=Path, default=PROJECT / ".local/models/qwen3-asr-1.7b-hf")
    result.add_argument("--qwen-aligner", type=Path, default=PROJECT / ".local/models/qwen3-forcedaligner-0.6b-hf",
                        help="Unused compatibility argument passed to ASR-only; never loaded.")
    result.add_argument("--ctc-model", type=Path, default=PROJECT / ".local/models/wav2vec2-large-xlsr-53-japanese")
    result.add_argument("--whisper-cache", type=Path, default=PROJECT / ".local/cache/whisper-runtime")
    result.add_argument("--nltk-data", type=Path, default=PROJECT / ".local/cache/whisper-nltk")
    result.add_argument("--dll-dir", type=Path, action="append", default=[])
    return result


if __name__ == "__main__":
    value = run_pipeline(parser().parse_args())
    print(json.dumps({"status": "ok", "output": value["pipeline"]["manifest"],
                      "wall_seconds": value["pipeline"]["wall_seconds"]}))
