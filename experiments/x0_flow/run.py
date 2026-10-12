"""Offline stage CLI across the pinned Whisper and Qwen environments."""
from __future__ import annotations

import argparse
import copy
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import shutil
import sys
import time

from experiments.w0_demo.pipeline import run_pipeline, validate_chunks
from experiments.w0_demo.run import ROOT, frozen_chunks, gpu_lock, read_audio, setup_runtime, sha256, write_json
from . import RECIPE
from .chunks import energy_chunks, fixed_chunks, validate_sample_coverage


def private_output(path: Path) -> Path:
    result = path.resolve()
    root = (ROOT / ".local/x0-flow").resolve()
    if not result.is_relative_to(root) or result == root:
        raise ValueError("Run directory must be a child of .local/x0-flow")
    return result


def source_files() -> list[Path]:
    return sorted([*Path(__file__).parent.glob("*.py"), *(ROOT / "experiments/w0_demo").glob("*.py"),
                   ROOT / "experiments/qwen/run_qwen.py", ROOT / "kototoki_eval/schema.py"])


def freeze_sources(out: Path) -> dict:
    identities = {}
    for path in source_files():
        relative = path.relative_to(ROOT)
        target = out / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        identities[relative.as_posix()] = sha256(path)
    notice = ROOT / "experiments/w0_demo/THIRD_PARTY_NOTICES.txt"
    shutil.copy2(notice, out / "source" / notice.relative_to(ROOT))
    return identities


def check_sources(manifest: dict) -> None:
    for name, expected in manifest.items():
        if sha256(ROOT / name) != expected:
            raise ValueError(f"Source changed after plan freeze: {name}; create a new run identity")


def runtime_identity() -> dict:
    import torch

    packages = {}
    for name in ("torch", "torchaudio", "transformers", "pyannote.audio", "accelerate"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    return {"python": sys.version, "executable": sys.executable, "platform": platform.platform(),
            "packages": packages, "cuda_runtime": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "whisperx_imported": any(k == "whisperx" or k.startswith("whisperx.") for k in sys.modules)}


def load_plan(out: Path) -> tuple[dict, object]:
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    if plan["recipe"] != RECIPE:
        raise ValueError("Plan recipe mismatch")
    check_sources(plan["source_sha256"])
    audio, identity = read_audio(Path(plan["input"]["path"]))
    if identity != plan["input"]:
        raise ValueError("Input changed after plan freeze")
    validate_sample_coverage(plan["chunks"], len(audio), retain_all=plan["variant"] != "pyannote")
    return plan, audio


def plan_stage(args) -> None:
    from experiments.w0_demo.vad import FrozenVad, PyannoteVad

    started = time.perf_counter()
    sources = freeze_sources(args.run)
    audio, identity = read_audio(args.audio)
    mark = time.perf_counter()
    stages = {}
    if args.variant == "fixed30":
        chunks = fixed_chunks(len(audio))
        metadata = {"kind": "fixed30", "fresh_inference": False, "retain_all_samples": True}
    elif args.variant == "energy":
        chunks = energy_chunks(audio)
        metadata = {"kind": "energy", "fresh_inference": False, "retain_all_samples": True,
                    "max_seconds": 30, "search_last_seconds": 5, "rms_window_ms": 100,
                    "grid_ms": 100, "tie_rule": "latest_cut", "threshold": None}
    else:
        with gpu_lock(ROOT / ".local/gpu.lock"):
            vad = (FrozenVad(frozen_chunks(args.frozen_vad, identity, args.offset)) if args.frozen_vad
                   else PyannoteVad(args.vad_checkpoint))
            stages["vad_load_s"] = time.perf_counter() - mark
            try:
                mark = time.perf_counter()
                chunks = vad.segment(audio)
                stages["vad_inference_s"] = time.perf_counter() - mark
                metadata = dict(vad.metadata)
            finally:
                vad.close()
        for chunk in chunks:
            chunk.update(start_sample=int(chunk["start"] * 16000), end_sample=int(chunk["end"] * 16000))
    validate_chunks(chunks, len(audio) / 16000)
    validate_sample_coverage(chunks, len(audio), retain_all=args.variant != "pyannote")
    stages["plan_s"] = time.perf_counter() - started
    result = {"recipe": RECIPE, "variant": args.variant, "input": identity,
              "offset_s": args.offset, "chunks": chunks, "effective_parameters": {"vad": metadata},
              "stages": stages, "source_sha256": sources, "runtime_identity": {"plan": runtime_identity()},
              "retained_samples": sum(c["end_sample"] - c["start_sample"] for c in chunks),
              "removed_samples": len(audio) - sum(c["end_sample"] - c["start_sample"] for c in chunks)}
    if args.frozen_vad:
        result["frozen_vad_source"] = {"path": str(args.frozen_vad.resolve()), "sha256": sha256(args.frozen_vad)}
    check_sources(sources)
    write_json(args.run / "plan.json", result)
    print(json.dumps({"stage": "plan", "variant": args.variant, "chunks": len(chunks), "stages": stages}))


def asr_stage(args) -> None:
    from .asr import QwenAsr

    plan, audio = load_plan(args.run)
    stages = {}
    segments, traces, metadata = [], [], {}
    started = time.perf_counter()
    if plan["chunks"]:
        with gpu_lock(ROOT / ".local/gpu.lock"):
            mark = time.perf_counter()
            asr = QwenAsr(args.asr_model)
            stages["asr_load_s"] = time.perf_counter() - mark
            try:
                mark = time.perf_counter()
                segments, traces = asr.transcribe(audio, plan["chunks"])
                stages["asr_inference_s"] = time.perf_counter() - mark
                metadata = dict(asr.metadata)
            finally:
                asr.close()
    stages["asr_stage_s"] = time.perf_counter() - started
    check_sources(plan["source_sha256"])
    write_json(args.run / "asr.json", {"plan_sha256": sha256(args.run / "plan.json"),
        "text": "".join(s["text"] for s in segments), "original_segments": segments,
        "asr_traces": traces, "effective_parameters": metadata, "stages": stages,
        "runtime_identity": runtime_identity(), "fresh_inference": bool(plan["chunks"])})
    print(json.dumps({"stage": "asr", "segments": len(segments), "characters": sum(len(s["text"]) for s in segments),
                      "stages": stages}))


class ReplayAsr:
    """Feed the freshly frozen cross-environment ASR stage to W0 validation."""
    def __init__(self, saved: dict, expected_chunks: list[dict]):
        self.saved, self.expected_chunks = saved, expected_chunks
        self.metadata = copy.deepcopy(saved["effective_parameters"])

    def transcribe(self, audio, chunks):
        if chunks != self.expected_chunks:
            raise ValueError("Alignment plan differs from frozen ASR windows")
        segments = self.saved["original_segments"]
        if len(segments) != len(chunks) or any(
                s["start"] != c["start"] or s["end"] != c["end"] for s, c in zip(segments, chunks)):
            raise ValueError("ASR segment windows differ from plan")
        if self.saved["text"] != "".join(s["text"] for s in segments):
            raise ValueError("ASR stage full text differs from its segments")
        return copy.deepcopy(segments), copy.deepcopy(self.saved["asr_traces"])

    def close(self) -> None:
        pass


def align_stage(args) -> None:
    from experiments.w0_demo.alignment import MmsAligner
    from experiments.w0_demo.vad import FrozenVad

    plan, audio = load_plan(args.run)
    asr_path = args.run / "asr.json"
    saved = json.loads(asr_path.read_text(encoding="utf-8"))
    if saved["plan_sha256"] != sha256(args.run / "plan.json"):
        raise ValueError("Plan changed after ASR")
    started = time.perf_counter()
    with gpu_lock(ROOT / ".local/gpu.lock"):
        result = run_pipeline(audio, FrozenVad(plan["chunks"]), lambda: ReplayAsr(saved, plan["chunks"]),
                              lambda: MmsAligner(args.mms_model), offset=plan["offset_s"])
    replay_stages = result.pop("stages")
    result.update(recipe=RECIPE, route="X0-flow-" + plan["variant"], variant=plan["variant"],
                  input=plan["input"], source_sha256=plan["source_sha256"],
                  stages={**plan["stages"], **saved["stages"],
                          **{k: v for k, v in replay_stages.items() if k.startswith("alignment_")},
                          "alignment_stage_s": time.perf_counter() - started},
                  runtime_identity={**plan["runtime_identity"], "asr": saved["runtime_identity"],
                                    "alignment": runtime_identity()},
                  retained_samples=plan["retained_samples"], removed_samples=plan["removed_samples"],
                  plan_sha256=sha256(args.run / "plan.json"), asr_stage_sha256=sha256(asr_path),
                  stage_execution={"planning": "fresh" if not plan.get("frozen_vad_source") else "frozen_vad",
                                   "asr": "fresh_separate_process" if plan["chunks"] else "skipped_empty_speech",
                                   "alignment": "fresh_separate_process" if plan["chunks"] else "skipped_empty_speech"},
                  asr_cached_for_alignment_only=True, cached_inference=False)
    result["effective_parameters"]["vad"] = plan["effective_parameters"]["vad"]
    result["model_files_sha256"] = {"mms": {str(p.relative_to(args.mms_model)): sha256(p)
        for p in sorted(args.mms_model.rglob("*")) if p.is_file() and p.suffix in {".json", ".bin", ".safetensors", ".txt"}}}
    result["stages"]["total_pipeline_s"] = (plan["stages"]["plan_s"] + saved["stages"]["asr_stage_s"]
                                              + result["stages"]["alignment_stage_s"])
    check_sources(plan["source_sha256"])
    write_json(args.run / "result.json", result)
    (args.run / "transcript.txt").write_text(result["text"], encoding="utf-8")
    print(json.dumps({"stage": "align", "status": "ok", "characters": len(result["text"]),
                      "stages": result["stages"], "result": str(args.run / "result.json")}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="stage", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--audio", type=Path, required=True)
    plan.add_argument("--offset", type=float, default=0)
    plan.add_argument("--variant", choices=("fixed30", "energy", "pyannote"), required=True)
    plan.add_argument("--out", dest="run", type=Path, required=True)
    plan.add_argument("--frozen-vad", type=Path)
    plan.add_argument("--vad-checkpoint", type=Path, default=ROOT / ".local/models/w0-assets/pytorch_model.bin")
    for command in (plan, sub.add_parser("asr"), sub.add_parser("align")):
        if command is not plan:
            command.add_argument("--run", type=Path, required=True)
        command.add_argument("--dll-dir", type=Path, default=ROOT / ".local/tools/whisper-runtime-provisional")
    sub.choices["asr"].add_argument("--asr-model", type=Path, default=ROOT / ".local/models/qwen3-asr-1.7b-hf")
    sub.choices["align"].add_argument("--mms-model", type=Path, default=ROOT / ".local/models/mms-1b-all")
    args = parser.parse_args()
    args.run = private_output(args.run)
    if args.stage == "plan":
        if not math.isfinite(args.offset) or args.offset < 0:
            parser.error("Source offset must be finite and nonnegative")
        if args.frozen_vad and args.variant != "pyannote":
            parser.error("Frozen VAD only applies to pyannote arm")
        args.run.mkdir(parents=True, exist_ok=False)
    elif not args.run.is_dir():
        parser.error("Run directory does not exist; execute plan first")
    output_name = {"plan": "plan.json", "asr": "asr.json", "align": "result.json"}[args.stage]
    if (args.run / output_name).exists():
        parser.error("Stage output already exists; create a new run instead of overwriting")
    handles = []
    try:
        handles = setup_runtime(args.run, args.dll_dir)
        {"plan": plan_stage, "asr": asr_stage, "align": align_stage}[args.stage](args)
    except Exception as error:
        write_json(args.run / f"failure-{args.stage}.json", {"status": "failed", "recipe": RECIPE,
                   "stage": args.stage, "exception": type(error).__name__, "message": str(error)})
        raise
    finally:
        for handle in handles:
            handle.close()


if __name__ == "__main__":
    main()
