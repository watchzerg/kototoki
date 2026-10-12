"""Internal fresh child stages; use x0_demo.run for the public CLI."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import time

from experiments.w0_demo.run import read_audio, setup_runtime
from . import RECIPES
from .chunks import cut_merge_chunks, fixed_chunks, validate_chunks
from .pipeline import build_result, validate_asr
from .storage import ROOT, check_sources, private_output, read_json, runtime_identity, sha256, write_json


def load_plan(out: Path) -> tuple[dict, object]:
    plan = read_json(out / "plan.json")
    if plan["recipe"] != RECIPES[plan["segmentation"]]:
        raise ValueError("Plan recipe mismatch")
    if plan["request_sha256"] != sha256(out / "request.json"):
        raise ValueError("Request changed after planning")
    check_sources(plan["source_sha256"])
    audio, identity = read_audio(Path(plan["input"]["path"]))
    if identity != plan["input"]:
        raise ValueError("Input changed after plan freeze")
    validate_chunks(plan["chunks"], len(audio), retain_all=plan["segmentation"] != "vad")
    if plan["segmentation"] == "vad":
        from .vad import import_vad_plan
        chunks, _, provenance = import_vad_plan(plan["vad_provenance"], identity, plan["offset_s"])
        if chunks != plan["chunks"] or provenance != plan["vad_provenance"]:
            raise ValueError("VAD plan differs from frozen external manifest")
    return plan, audio


def plan_stage(out: Path, request: dict) -> None:
    started = time.perf_counter()
    manifest = read_json(out / "source-manifest.json")
    check_sources(manifest)
    audio, identity = read_audio(Path(request["audio"]))
    chunks = None
    provenance = None
    metadata = {"kind": request["segmentation"], "vad": False, "retain_all_samples": True,
                "max_samples": 480000, "sample_rate": 16000, "audio_transform": "none"}
    if request["segmentation"] == "cut-merge":
        chunks = cut_merge_chunks(audio)
        metadata.update(candidate_region_samples=80000, trailing_rms_samples=1600,
                        grid_samples=1600, tie_rule="latest_cut", silence_threshold=None,
                        merge="greedy_adjacent_source_span_at_most_30s",
                        historical_energy_recipe_equivalent=False)
    elif request["segmentation"] == "vad":
        from .vad import import_vad_plan
        chunks, metadata, provenance = import_vad_plan(request["vad_manifest"], identity, request["offset_s"])
    else:
        chunks = fixed_chunks(len(audio))
    check_sources(manifest)
    retained = sum(c["end_sample"] - c["start_sample"] for c in chunks)
    plan = {"recipe": request["recipe"], "segmentation": request["segmentation"],
        "offset_s": request["offset_s"], "input": identity, "chunks": chunks,
        "digital_silence": bool((audio == 0).all()), "retained_samples": retained, "removed_samples": len(audio)-retained,
        "effective_parameters": metadata, "source_sha256": manifest,
        "request_sha256": sha256(out / "request.json"),
        "runtime_identity": runtime_identity(), "stages": {"plan_stage_s": time.perf_counter() - started}}
    if provenance is not None:
        plan.update(vad_id=provenance["vad_id"], vad_provenance=provenance)
    write_json(out / "plan.json", plan)


def asr_stage(out: Path, request: dict) -> None:
    from .asr import QwenAsr

    started = time.perf_counter()
    plan, audio = load_plan(out)
    if not plan["chunks"]:
        write_json(out / "asr.json", {"text": "", "original_segments": [], "asr_traces": [],
            "effective_parameters": {"execution": "skipped_no_speech", "model_files_sha256": {}},
            "plan_sha256": sha256(out / "plan.json"), "runtime_identity": runtime_identity(),
            "stages": {"asr_load_s": 0, "asr_inference_s": 0, "asr_stage_s": time.perf_counter()-started}})
        return
    mark = time.perf_counter()
    asr = QwenAsr(Path(request["asr_model"]))
    stages = {"asr_load_s": time.perf_counter() - mark}
    partial = out / "asr-partial.json"

    def progress(segments, traces, metadata):
        # Only this explicitly partial checkpoint is replaced; completed files are exclusive.
        import json
        checkpoint = {"status": "partial", "text": "".join(s["text"] for s in segments),
                      "original_segments": segments, "asr_traces": traces, "effective_parameters": metadata}
        temp = out / "tmp/asr-progress.json"
        temp.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        temp.replace(partial)

    try:
        mark = time.perf_counter()
        segments, traces = asr.transcribe(audio, plan["chunks"], progress=progress,
                                         retain_all=plan["segmentation"] != "vad")
        stages["asr_inference_s"] = time.perf_counter() - mark
        saved = {"text": "".join(s["text"] for s in segments), "original_segments": segments,
                 "asr_traces": traces, "effective_parameters": dict(asr.metadata),
                 "plan_sha256": sha256(out / "plan.json"), "runtime_identity": runtime_identity()}
        validate_asr(saved, plan["chunks"], len(audio), retain_all=plan["segmentation"] != "vad")
    finally:
        asr.close()
    stages["asr_stage_s"] = time.perf_counter() - started
    saved["stages"] = stages
    check_sources(plan["source_sha256"])
    write_json(out / "asr.json", saved)
    partial.unlink(missing_ok=True)


def align_stage(out: Path, request: dict) -> None:
    from experiments.w0_demo.alignment import MmsAligner

    started = time.perf_counter()
    plan, audio = load_plan(out)
    saved = read_json(out / "asr.json")
    if saved["plan_sha256"] != sha256(out / "plan.json"):
        raise ValueError("Plan changed after ASR")
    validate_asr(saved, plan["chunks"], len(audio), retain_all=plan["segmentation"] != "vad")
    if not plan["chunks"]:
        aligned = {"text": "", "records": [], "units": [], "derived_segments": []}
        write_json(out / "alignment-evidence.json", aligned)
        stages = {**plan["stages"], **saved["stages"], "alignment_load_s": 0, "alignment_inference_s": 0,
                  "alignment_stage_s": time.perf_counter()-started}
        result = build_result(plan, saved, aligned, {"execution": "skipped_no_speech"}, stages)
        result.update(runtime_identity={"plan": plan["runtime_identity"], "asr": saved["runtime_identity"],
                                       "alignment": runtime_identity()}, model_files_sha256={"asr": {}, "mms": {}},
                      plan_sha256=sha256(out / "plan.json"), asr_stage_sha256=sha256(out / "asr.json"))
        check_sources(plan["source_sha256"])
        write_json(out / "alignment.json", result)
        return
    for trace, chunk in zip(saved["asr_traces"], plan["chunks"]):
        data = audio[chunk["start_sample"]:chunk["end_sample"]]
        if trace["pcm_float32_sha256"] != hashlib.sha256(data.tobytes()).hexdigest():
            raise ValueError("ASR PCM evidence differs from alignment source samples")
    mark = time.perf_counter()
    aligner = MmsAligner(Path(request["mms_model"]))
    stages = {**plan["stages"], **saved["stages"], "alignment_load_s": time.perf_counter() - mark}
    try:
        mark = time.perf_counter()
        aligned = aligner.align(audio, saved["original_segments"], plan["offset_s"])
        stages["alignment_inference_s"] = time.perf_counter() - mark
        metadata = dict(aligner.metadata)
    finally:
        aligner.close()
    # Save complete text/CTC evidence before optional final identity work can fail.
    write_json(out / "alignment-evidence.json", aligned)
    model_path = Path(request["mms_model"])
    identity = {p.relative_to(model_path).as_posix(): sha256(p) for p in sorted(model_path.rglob("*"))
                if p.is_file() and p.suffix in {".json", ".bin", ".safetensors", ".txt"}}
    stages["alignment_stage_s"] = time.perf_counter() - started
    result = build_result(plan, saved, aligned, metadata, stages)
    result.update(runtime_identity={"plan": plan["runtime_identity"], "asr": saved["runtime_identity"],
                                   "alignment": runtime_identity()},
                  model_files_sha256={"asr": saved["effective_parameters"]["model_files_sha256"], "mms": identity},
                  plan_sha256=sha256(out / "plan.json"), asr_stage_sha256=sha256(out / "asr.json"))
    check_sources(plan["source_sha256"])
    write_json(out / "alignment.json", result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("plan", "asr", "align"))
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    out = private_output(args.run)
    handles = []
    try:
        lock = read_json(ROOT / ".local/gpu.lock")
        if str(lock["pid"]) != os.environ.get("KOTOTOKI_X0_PARENT_PID"):
            raise RuntimeError("Child stage requires the orchestrator's shared GPU lock")
        request = read_json(out / "request.json")
        if request["recipe"] != RECIPES[request["segmentation"]]:
            raise ValueError("Request recipe mismatch")
        output = {"plan": "plan.json", "asr": "asr.json", "align": "alignment.json"}[args.stage]
        if (out / output).exists():
            raise FileExistsError("Completed stage exists; create a new run")
        handles = setup_runtime(out, Path(request["dll_dir"]))
        {"plan": plan_stage, "asr": asr_stage, "align": align_stage}[args.stage](out, request)
    except BaseException as error:
        failure = out / f"failure-{args.stage}.json"
        if not failure.exists():
            write_json(failure, {"status": "failed", "stage": args.stage,
                                "exception": type(error).__name__, "message": str(error)})
        raise
    finally:
        for handle in handles:
            handle.close()


if __name__ == "__main__":
    main()
