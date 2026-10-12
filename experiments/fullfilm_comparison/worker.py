"""Fresh resident-model ASR/MMS stages for frozen full-film source windows.

The parent owns the shared GPU lock and segmentation. This module changes no
canonical decoding settings: each adapter receives one exact crop, independently,
and the same model is reused until all planned windows have been attempted.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable

from experiments.w0_demo.run import read_audio, setup_runtime
from experiments.x0_demo.chunks import RATE, make_chunk, validate_chunks
from experiments.x0_demo.storage import ROOT, check_sources, read_json, runtime_identity, sha256

IDENTITY_KEYS = ("path", "file_sha256", "pcm_sha256", "sample_rate", "channels", "samples", "duration_s")
BOUNDS = ("start", "end", "start_sample", "end_sample")


class ModelInitializationError(RuntimeError):
    """Model creation failed before any chunk inference was attempted."""


class FatalCudaError(RuntimeError):
    """The CUDA context cannot safely serve subsequent independent requests."""


def private_output(path: Path) -> Path:
    resolved = path.resolve()
    root = (ROOT / ".local/fullfilm-comparison").resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise ValueError("Output must be a new child directory of .local/fullfilm-comparison")
    return resolved


def atomic_json(path: Path, value: object, *, replace: bool = False) -> None:
    """Atomically publish evidence; replacement is limited to progress.json."""
    if path.exists() and not replace:
        raise FileExistsError(f"Completed evidence already exists: {path}")
    temporary = path.with_name(path.name + ".writing")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    if replace:
        temporary.replace(path)
    else:
        # rename rejects an existing destination on native Windows.
        temporary.rename(path)


def fatal_cuda(error: BaseException) -> bool:
    message = str(error).lower()
    return any(term in message for term in (
        "device-side assert", "illegal memory access", "unspecified launch failure",
        "context is destroyed", "launch timed out", "launch timeout", "misaligned address"))


def failure_info(error: BaseException) -> dict:
    # A repeated decoder can emit enormous text; retain text/tokens separately,
    # while bounding diagnostics and avoiding traceback-owned GPU tensors.
    return {"exception": type(error).__name__, "message": str(error)[:4000]}


def checkpoint(out: Path, index: int, record: dict, counts: dict) -> None:
    atomic_json(out / "chunks" / f"{index:06d}.json", record)
    atomic_json(out / "progress.json", {"status": "running", "last_attempted_chunk_index": index,
        **counts}, replace=True)


def model_identity(path: Path) -> dict:
    return {p.relative_to(path).as_posix(): sha256(p) for p in sorted(path.rglob("*"))
            if p.is_file() and p.suffix in {".json", ".bin", ".safetensors", ".txt", ".npz"}}


def source_manifest(job: dict, plan: dict) -> dict:
    sources = job.get("source_sha256", plan.get("source_sha256", {}))
    if not isinstance(sources, dict):
        raise ValueError("source_sha256 must be a source path/hash mapping")
    if "source_sha256" in job and "source_sha256" in plan and job["source_sha256"] != plan["source_sha256"]:
        raise ValueError("Job and plan frozen sources differ")
    return sources


def load_plan(job: dict, audio_reader=read_audio) -> tuple[dict, Any, dict]:
    path = Path(job["plan_path"])
    if sha256(path) != job["plan_sha256"]:
        raise ValueError("Frozen full-film plan changed")
    plan = read_json(path)
    sources = source_manifest(job, plan)
    check_sources(sources)
    if job.get("schema_version") != 1 or job.get("route") not in {"W0", "X0"}:
        raise ValueError("Stage job requires schema_version=1 and route W0 or X0")
    if plan.get("segmentation") not in {"pyannote-current", "cut-merge"}:
        raise ValueError("Full-film plan requires pyannote-current or cut-merge")
    offset = plan.get("offset_s")
    if isinstance(offset, bool) or not isinstance(offset, (int, float)) or not math.isfinite(offset) or offset < 0:
        raise ValueError("Source offset must be finite and nonnegative")
    audio, identity = audio_reader(Path(plan["input"]["path"]))
    if any(identity.get(key) != plan["input"].get(key) for key in IDENTITY_KEYS):
        raise ValueError("Full-film audio differs from frozen input identity")
    validate_chunks(plan["chunks"], len(audio), retain_all=plan["segmentation"] == "cut-merge")
    if hasattr(audio, "flags"):
        audio.flags.writeable = False
    return plan, audio, sources


def recheck(job: dict, plan: dict, sources: dict) -> None:
    check_sources(sources)
    if sha256(Path(job["plan_path"])) != job["plan_sha256"]:
        raise ValueError("Frozen full-film plan changed during inference")
    if sha256(Path(plan["input"]["path"])) != plan["input"]["file_sha256"]:
        raise ValueError("Full-film audio changed during inference")


def global_segment(segment: dict, chunk: dict, index: int) -> dict:
    result = {**segment, **{key: chunk[key] for key in BOUNDS}, "chunk_index": index}
    if not isinstance(result.get("text"), str):
        raise ValueError("ASR segment must preserve original text")
    return result


def global_trace(trace: dict, chunk: dict, index: int, data: Any) -> dict:
    result = {**trace, "chunk_index": index, "start_sample": chunk["start_sample"],
              "end_sample": chunk["end_sample"],
              "pcm_float32_sha256": hashlib.sha256(data.tobytes()).hexdigest()}
    return result


def asr_factory(job: dict):
    if job["route"] == "W0":
        from experiments.w0_demo.asr import WhisperAsr
        return WhisperAsr(Path(job["asr_model"]), Path(job["mel_path"]))
    from experiments.x0_demo.asr import QwenAsr
    return QwenAsr(Path(job["asr_model"]))


def alignment_factory(job: dict):
    from experiments.w0_demo.alignment import MmsAligner
    return MmsAligner(Path(job["mms_model"]))


def initialize(factory: Callable[[], Any], stage: str):
    try:
        return factory()
    except Exception as error:
        raise ModelInitializationError(f"{stage}: {type(error).__name__}: {str(error)[:4000]}") from error


def allocator_peaks() -> dict:
    torch = sys.modules.get("torch")
    if torch is not None and torch.cuda.is_initialized():
        return {"peak_allocated_bytes": torch.cuda.max_memory_allocated(),
                "peak_reserved_bytes": torch.cuda.max_memory_reserved()}
    return {}


def close_model(model: Any) -> None:
    """Keep the original failure when a broken CUDA context also rejects close."""
    unwinding = sys.exc_info()[0] is not None
    try:
        model.close()
    except Exception:
        if not unwinding:
            raise


def run_asr(audio: Any, plan: dict, route: str, out: Path, factory: Callable[[], Any]) -> dict:
    """Attempt each frozen window once, excluding partial output from complete text."""
    started = time.perf_counter()
    chunks = plan["chunks"]
    segments, traces, records, failures = [], [], [], []
    stages = {"asr_load_s": 0.0, "asr_inference_s": 0.0}
    metadata: dict = {"execution": "skipped_no_speech"}
    asr = None
    peaks: dict = {}
    if chunks:
        mark = time.perf_counter()
        asr = initialize(factory, "asr")
        stages["asr_load_s"] = time.perf_counter() - mark
    try:
        for index, chunk in enumerate(chunks):
            data = audio[chunk["start_sample"]:chunk["end_sample"]]
            local = make_chunk(0, len(data))
            captured: dict = {}

            def progress(partial_segments, partial_traces, _metadata):
                captured.update(segments=copy.deepcopy(partial_segments), traces=copy.deepcopy(partial_traces))

            mark = time.perf_counter()
            record = {"chunk_index": index, **{key: chunk[key] for key in BOUNDS}}
            fatal = False
            try:
                if route == "X0":
                    completed, evidence = asr.transcribe(data, [local], progress=progress, retain_all=False)
                else:
                    completed, evidence = asr.transcribe(data, [local])
                if len(completed) != 1 or len(evidence) != 1:
                    raise ValueError("ASR must return one segment and trace per source window")
                if any(completed[0].get(key) != local[key] for key in BOUNDS):
                    raise ValueError("ASR changed exact local source window")
                if evidence[0].get("token_limit_reached"):
                    captured.update(segments=completed, traces=evidence)
                    raise ValueError("Qwen generation reached 4096-token cap; partial output retained")
                segment = global_segment(completed[0], chunk, index)
                trace = global_trace(evidence[0], chunk, index, data)
                segments.append(segment)
                traces.append(trace)
                record.update(status="ok", segment=segment, trace=trace)
            except Exception as error:
                partial_segments = [global_segment(s, chunk, index) for s in captured.get("segments", [])]
                partial_traces = [global_trace(t, chunk, index, data) for t in captured.get("traces", [])]
                fatal = fatal_cuda(error)
                record.update(status="failed", failure_kind="fatal_cuda" if fatal else "chunk_inference_failed",
                    **failure_info(error), partial_segments=partial_segments, partial_traces=partial_traces,
                    partial_output_is_complete=False)
                failures.append(record)
            elapsed = time.perf_counter() - mark
            stages["asr_inference_s"] += elapsed
            record["attempt_wall_s"] = elapsed
            records.append(record)
            checkpoint(out, index, record, {"attempted_chunks": len(records), "successful_chunks": len(segments),
                                          "failed_chunks": len(failures), "total_chunks": len(chunks)})
            if fatal:
                raise FatalCudaError(f"CUDA context failure at ASR chunk {index}; checkpoint retained")
            peaks = {key: max(peaks.get(key, 0), value) for key, value in allocator_peaks().items()}
        if asr is not None:
            metadata = copy.deepcopy(asr.metadata)
            metadata.update(peaks)
    finally:
        if asr is not None:
            close_model(asr)
    stages["asr_stage_s"] = time.perf_counter() - started
    return {"schema_version": 1, "route": route, "status": "partial" if failures else "ok",
        "text": "".join(s["text"] for s in segments), "original_segments": segments, "asr_traces": traces,
        "chunk_records": records, "failed_chunks": failures, "asr_failed_chunk_indices": [r["chunk_index"] for r in failures],
        "attempted_chunks": len(records), "total_chunks": len(chunks), "all_chunks_attempted": len(records) == len(chunks),
        "effective_parameters": metadata, "runtime_identity": runtime_identity(), "stages": stages,
        "cached_inference": False, "fresh": True, "offline_requested": True}


def validate_asr(saved: dict, plan: dict, audio: Any) -> None:
    records = saved["chunk_records"]
    chunks = plan["chunks"]
    if (not saved.get("all_chunks_attempted") or len(records) != len(chunks)
            or saved.get("status") not in {"ok", "partial"}):
        raise ValueError("ASR stage did not attempt the complete frozen plan")
    complete = []
    failures = []
    for index, (record, chunk) in enumerate(zip(records, chunks)):
        if record.get("chunk_index") != index or any(record.get(key) != chunk[key] for key in BOUNDS):
            raise ValueError("ASR chunk evidence differs from frozen source span")
        if record.get("status") == "ok":
            complete.append(index)
        elif record.get("status") == "failed":
            failures.append(index)
        else:
            raise ValueError("Unknown ASR chunk status")
    if (len(saved["original_segments"]) != len(complete) or len(saved["asr_traces"]) != len(complete)
            or saved["asr_failed_chunk_indices"] != failures
            or saved["failed_chunks"] != [records[index] for index in failures]
            or saved["status"] != ("partial" if failures else "ok")):
        raise ValueError("ASR complete/failed chunk accounting differs")
    for index, segment, trace in zip(complete, saved["original_segments"], saved["asr_traces"]):
        chunk = chunks[index]
        if (segment.get("chunk_index") != index or trace.get("chunk_index") != index
                or not isinstance(segment.get("text"), str)
                or any(segment.get(key) != chunk[key] for key in BOUNDS)
                or any(trace.get(key) != chunk[key] for key in ("start_sample", "end_sample"))
                or trace.get("token_limit_reached")):
            raise ValueError("ASR successful output changed source window or includes capped partial output")
        data = audio[chunk["start_sample"]:chunk["end_sample"]]
        if hashlib.sha256(data.tobytes()).hexdigest() != trace["pcm_float32_sha256"]:
            raise ValueError("ASR and MMS source PCM differ")
        if records[index].get("segment") != segment or records[index].get("trace") != trace:
            raise ValueError("ASR checkpoint and stage output differ")
    if saved["text"] != "".join(s["text"] for s in saved["original_segments"]):
        raise ValueError("ASR stage text differs from complete segments")


def global_record(record: dict, segment: dict, index: int) -> dict:
    result = copy.deepcopy(record)
    begin = segment["start_sample"]
    result.update(segment_index=index, chunk_index=segment["chunk_index"],
                  window_start=segment["start"], window_end=segment["end"],
                  window_start_sample=begin, window_end_sample=segment["end_sample"])
    normalization = result.get("normalization")
    if normalization:
        normalization["source_sample_start"] += begin
        normalization["source_sample_end"] += begin
    return result


def validate_result(result: dict) -> None:
    from kototoki_eval.schema import validate_transcript
    validate_transcript(result)
    text = result["text"]
    if text != "".join(s["text"] for s in result["original_segments"]):
        raise ValueError("MMS must preserve all complete ASR text")
    if len(result["units"]) != len(text):
        raise ValueError("MMS must account for every character exactly once")
    for index, unit in enumerate(result["units"]):
        if unit["char_start"] != index or unit["char_end"] != index + 1:
            raise ValueError("MMS changed character order or coverage")
        if unit["status"] == "ok":
            start, end = unit.get("start"), unit.get("end")
            if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (start, end))
                    or not result["source_start_seconds"] <= start <= end <= result["source_end_seconds"] + .001):
                raise ValueError("MMS timed units left full-film source range")
        elif unit.get("start") is not None or unit.get("end") is not None:
            raise ValueError("MMS text_only must not fabricate timestamps")


def run_alignment(audio: Any, plan: dict, saved: dict, route: str, out: Path,
                  factory: Callable[[], Any]) -> dict:
    from experiments.w0_demo.alignment import map_records

    started = time.perf_counter()
    validate_asr(saved, plan, audio)
    segments = saved["original_segments"]
    records = []
    stages = {**saved["stages"], "alignment_load_s": 0.0, "alignment_inference_s": 0.0}
    aligner = None
    metadata = {"execution": "skipped_no_complete_asr_chunks"}
    if segments:
        mark = time.perf_counter()
        aligner = initialize(factory, "alignment")
        stages["alignment_load_s"] = time.perf_counter() - mark
    try:
        for index, segment in enumerate(segments):
            data = audio[segment["start_sample"]:segment["end_sample"]]
            local = {**segment, **make_chunk(0, len(data))}
            mark = time.perf_counter()
            fatal = False
            try:
                aligned = aligner.align(data, [local], 0)
                if aligned["text"] != segment["text"] or len(aligned["records"]) != 1:
                    raise ValueError("MMS did not preserve the complete ASR segment")
                record = global_record(aligned["records"][0], segment, index)
                fatal = bool(record.get("failure") and fatal_cuda(RuntimeError(record["failure"])))
            except Exception as error:
                fatal = fatal_cuda(error)
                record = global_record({"tokens": [], "failure": f"{type(error).__name__}: {str(error)[:4000]}"}, segment, index)
            elapsed = time.perf_counter() - mark
            record["attempt_wall_s"] = elapsed
            stages["alignment_inference_s"] += elapsed
            records.append(record)
            one_record = {**record, "segment_index": 0}
            checkpoint(out, segment["chunk_index"], {"status": "failed" if record.get("failure") else "ok",
                "chunk_index": segment["chunk_index"], **{key: segment[key] for key in BOUNDS},
                "alignment": map_records([segment], [one_record], plan["offset_s"])},
                {"attempted_segments": len(records), "total_segments": len(segments),
                 "failed_segments": sum(bool(r.get("failure")) for r in records)})
            if fatal:
                raise FatalCudaError(f"CUDA context failure at MMS chunk {segment['chunk_index']}; checkpoint retained")
        if aligner is not None:
            metadata = copy.deepcopy(aligner.metadata)
            metadata.update(allocator_peaks())
    finally:
        if aligner is not None:
            close_model(aligner)
    aligned = map_records(segments, records, plan["offset_s"])
    failures = [r for r in records if r.get("failure")]
    stages["alignment_stage_s"] = time.perf_counter() - started
    retained = sum(c["end_sample"] - c["start_sample"] for c in plan["chunks"])
    result = {"schema_version": 1, "recipe": plan.get("recipe", f"fullfilm-{route.lower()}-{plan['segmentation']}-mms-v1"),
        "route": route, "segmentation": plan["segmentation"],
        "status": "partial" if saved["failed_chunks"] or failures else "ok", "text": aligned["text"],
        "units": aligned["units"], "cues": [], "original_segments": segments, "chunks": plan["chunks"],
        "asr_traces": saved["asr_traces"], "alignment_records": records, "derived_segments": aligned["derived_segments"],
        "chunk_records": saved["chunk_records"], "failed_chunks": saved["failed_chunks"],
        "asr_failed_chunk_indices": saved["asr_failed_chunk_indices"],
        "alignment_failure_count": len(failures), "alignment_failed_segment_indices": [r["segment_index"] for r in failures],
        "alignment_failed_chunk_indices": [r["chunk_index"] for r in failures],
        "all_chunks_attempted": saved["all_chunks_attempted"], "attempted_chunks": saved["attempted_chunks"],
        "total_chunks": len(plan["chunks"]), "input": plan["input"], "offset_s": plan["offset_s"],
        "source_start_seconds": plan["offset_s"], "duration_seconds": len(audio) / RATE,
        "source_end_seconds": plan["offset_s"] + len(audio) / RATE,
        "retained_samples": retained, "removed_samples": len(audio) - retained,
        "effective_parameters": {"segmentation": plan.get("effective_parameters", {}).get("segmentation", plan.get("effective_parameters", {})),
                                 "asr": saved["effective_parameters"], "alignment": metadata},
        "runtime_identity": {"asr": saved["runtime_identity"], "alignment": runtime_identity()},
        "stages": stages, "fresh": True, "cached_inference": False, "offline_requested": True,
        "stage_execution": {"segmentation": "frozen_global_fullfilm_plan", "asr": "fresh_resident_stage",
                            "alignment": "fresh_resident_stage"}}
    result["text_only_characters"] = sum(u["status"] == "text_only" for u in result["units"])
    validate_result(result)
    return result


def execute(stage: str, job: dict, out: Path) -> dict:
    out = private_output(out)
    out.mkdir(parents=True, exist_ok=False)
    (out / "chunks").mkdir()
    started = time.perf_counter()
    handles = []
    try:
        lock = read_json(ROOT / ".local/gpu.lock")
        if str(lock["pid"]) != os.environ.get("KOTOTOKI_FULLFILM_PARENT_PID"):
            raise RuntimeError("Full-film child requires the parent's shared GPU lock")
        handles = setup_runtime(out, Path(job.get("dll_dir", ROOT / ".local/tools/whisper-runtime-provisional")))
        mark = time.perf_counter()
        plan, audio, sources = load_plan(job)
        input_read_s = time.perf_counter() - mark
        if stage == "asr":
            mark = time.perf_counter()
            asr_identity = model_identity(Path(job["asr_model"])) if job["route"] == "W0" and plan["chunks"] else None
            identity_s = time.perf_counter() - mark
            result = run_asr(audio, plan, job["route"], out, lambda: asr_factory(job))
            metadata = result["effective_parameters"]
            if plan["chunks"]:
                metadata["model_files_sha256"] = metadata.get("model_files_sha256") or asr_identity
                if job["route"] == "W0":
                    metadata["mel_sha256"] = metadata.get("mel_sha256") or sha256(Path(job["mel_path"]))
            result["stages"]["asr_model_identity_s"] = identity_s
            result.update(plan_sha256=job["plan_sha256"], input=plan["input"], segmentation=plan["segmentation"])
        else:
            path = Path(job["asr_stage_path"])
            if sha256(path) != job["asr_stage_sha256"]:
                raise ValueError("Frozen ASR stage changed before alignment")
            saved = read_json(path)
            if saved["plan_sha256"] != job["plan_sha256"] or saved["route"] != job["route"]:
                raise ValueError("ASR stage differs from frozen plan/route")
            mark = time.perf_counter()
            mms_identity = model_identity(Path(job["mms_model"])) if saved["original_segments"] else {}
            identity_s = time.perf_counter() - mark
            result = run_alignment(audio, plan, saved, job["route"], out, lambda: alignment_factory(job))
            result.update(plan_sha256=job["plan_sha256"], asr_stage_sha256=job["asr_stage_sha256"],
                model_files_sha256={"asr": saved["effective_parameters"].get("model_files_sha256", {}),
                                    "mms": mms_identity})
            result["stages"]["alignment_model_identity_s"] = identity_s
            if sha256(path) != job["asr_stage_sha256"]:
                raise ValueError("Frozen ASR stage changed during alignment")
        result["source_sha256"] = sources
        result["stages"]["input_read_s"] = input_read_s
        recheck(job, plan, sources)
        result["stages"]["worker_wall_s"] = time.perf_counter() - started
        atomic_json(out / ("asr.json" if stage == "asr" else "alignment.json"), result)
        atomic_json(out / "progress.json", {"status": result["status"], "completed": True,
            "attempted_chunks": result["attempted_chunks"], "total_chunks": result["total_chunks"]}, replace=True)
        return result
    except BaseException as error:
        atomic_json(out / "failure.json", {"status": "failed", "stage": stage,
            "failure_kind": "model_initialization_failed" if isinstance(error, ModelInitializationError)
                else "fatal_cuda" if isinstance(error, FatalCudaError) else "stage_failed",
            **failure_info(error), "worker_wall_s": time.perf_counter() - started})
        raise
    finally:
        for handle in handles:
            handle.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("asr", "align"))
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = execute(args.stage, read_json(args.job), args.out)
    print(json.dumps({"status": result["status"], "stage": args.stage,
        "attempted_chunks": result["attempted_chunks"], "total_chunks": result["total_chunks"],
        "asr_failed_chunks": len(result["failed_chunks"]), "stages": result["stages"]}))
    if result["status"] != "ok":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
