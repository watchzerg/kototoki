"""Candidate ASR plus unchanged shared MMS, over the complete frozen film plan."""
from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import time
import json

from experiments.fullfilm_comparison import worker as shared
from experiments.w0_demo.run import read_audio, setup_runtime
from experiments.x0_demo.chunks import validate_chunks
from experiments.x0_demo.storage import ROOT, check_sources, read_json, sha256
from .adapters import NativeAsr, validate_job


def load_plan(job: dict, audio_reader=read_audio) -> tuple[dict, object, dict]:
    validate_job(job)
    path = Path(job["plan_path"])
    if sha256(path) != job["plan_sha256"]:
        raise ValueError("Frozen candidate full-film plan changed")
    plan = read_json(path)
    sources = shared.source_manifest(job, plan)
    check_sources(sources)
    if plan.get("segmentation") != "pyannote-current":
        raise ValueError("First candidate batch must use the current new-Pyannote baseline windows")
    offset = plan.get("offset_s")
    if isinstance(offset, bool) or not isinstance(offset, (int, float)) or not math.isfinite(offset) or offset < 0:
        raise ValueError("Source offset must be finite and nonnegative")
    audio, identity = audio_reader(Path(plan["input"]["path"]))
    if any(identity.get(key) != plan["input"].get(key) for key in shared.IDENTITY_KEYS):
        raise ValueError("Candidate audio differs from frozen complete-film identity")
    validate_chunks(plan["chunks"], len(audio), retain_all=False)
    if hasattr(audio, "flags"):
        audio.flags.writeable = False
    return plan, audio, sources


def run_asr(audio, plan: dict, candidate: str, out: Path, factory) -> dict:
    # The shared resident loop's X0 branch enables the progress callback used to
    # retain partial decoder output on exceptions. This is an internal protocol
    # switch only; every public artifact carries the actual candidate identity.
    result = shared.run_asr(audio, plan, "X0", out, factory)
    result.update(route=candidate, candidate_id=candidate)
    return result


def execute(stage: str, job: dict, out: Path) -> dict:
    out = shared.private_output(out)
    out.mkdir(parents=True, exist_ok=False)
    (out / "chunks").mkdir()
    started = time.perf_counter()
    handles = []
    try:
        validate_job(job)
        lock = read_json(ROOT / ".local/gpu.lock")
        if str(lock["pid"]) != os.environ.get("KOTOTOKI_FULLFILM_PARENT_PID"):
            raise RuntimeError("Candidate child requires its parent's shared GPU lock")
        handles = setup_runtime(out, Path(job.get("dll_dir", ROOT / ".local/tools/whisper-runtime-provisional")))
        mark = time.perf_counter()
        plan, audio, sources = load_plan(job)
        input_read_s = time.perf_counter() - mark
        if stage == "asr":
            result = run_asr(audio, plan, job["candidate_id"], out, lambda: NativeAsr(job))
            result.update(plan_sha256=job["plan_sha256"], input=plan["input"], segmentation=plan["segmentation"])
        else:
            path = Path(job["asr_stage_path"])
            if sha256(path) != job["asr_stage_sha256"]:
                raise ValueError("Candidate ASR evidence changed before shared MMS")
            saved = read_json(path)
            if saved["plan_sha256"] != job["plan_sha256"] or saved["route"] != job["candidate_id"]:
                raise ValueError("Candidate ASR differs from frozen plan or candidate identity")
            mark = time.perf_counter()
            mms_identity = shared.model_identity(Path(job["mms_model"])) if saved["original_segments"] else {}
            identity_s = time.perf_counter() - mark
            result = shared.run_alignment(audio, plan, saved, job["candidate_id"], out,
                lambda: shared.alignment_factory(job))
            result.update(candidate_id=job["candidate_id"], plan_sha256=job["plan_sha256"],
                asr_stage_sha256=job["asr_stage_sha256"],
                model_files_sha256={"asr": saved["effective_parameters"].get("model_files_sha256", {}), "mms": mms_identity})
            result["stages"]["alignment_model_identity_s"] = identity_s
            if sha256(path) != job["asr_stage_sha256"]:
                raise ValueError("Candidate ASR evidence changed during shared MMS")
        result["source_sha256"] = sources
        result["stages"]["input_read_s"] = input_read_s
        shared.recheck(job, plan, sources)
        result["stages"]["worker_wall_s"] = time.perf_counter() - started
        shared.atomic_json(out / ("asr.json" if stage == "asr" else "alignment.json"), result)
        shared.atomic_json(out / "progress.json", {"status": result["status"], "completed": True,
            "attempted_chunks": result["attempted_chunks"], "total_chunks": result["total_chunks"]}, replace=True)
        return result
    except BaseException as error:
        shared.atomic_json(out / "failure.json", {"status": "failed", "stage": stage,
            "candidate_id": job.get("candidate_id"),
            "failure_kind": "model_initialization_failed" if isinstance(error, shared.ModelInitializationError)
                else "fatal_cuda" if isinstance(error, shared.FatalCudaError) else "stage_failed",
            **shared.failure_info(error), "worker_wall_s": time.perf_counter() - started})
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
    print(json.dumps({"status": result["status"], "stage": args.stage, "candidate_id": result["candidate_id"],
        "attempted_chunks": result["attempted_chunks"], "total_chunks": result["total_chunks"],
        "asr_failed_chunks": len(result["failed_chunks"]), "stages": result["stages"]}))
    if result["status"] != "ok":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
