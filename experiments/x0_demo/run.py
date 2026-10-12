"""One-command offline X0 orchestration across provisioned backend environments."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from experiments.w0_demo.run import gpu_lock
from . import RECIPES
from .storage import ROOT, check_sources, freeze_sources, private_output, read_json, runtime_identity, sha256, write_json


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--audio", type=Path, required=True, help="Prepared mono 16kHz PCM16 WAV")
    result.add_argument("--offset", type=float, default=0)
    result.add_argument("--out", type=Path, required=True, help="New directory under .local/x0-demo")
    result.add_argument("--segmentation", choices=tuple(RECIPES), default="fixed30")
    result.add_argument("--vad-manifest", type=Path, help="Precomputed VAD manifest; requires --segmentation vad")
    result.add_argument("--qwen-python", type=Path, default=ROOT / ".local/envs/qwen-hf-final/Scripts/python.exe")
    result.add_argument("--mms-python", type=Path, default=ROOT / ".local/envs/whisper-latest/Scripts/python.exe")
    result.add_argument("--asr-model", type=Path, default=ROOT / ".local/models/qwen3-asr-1.7b-hf")
    result.add_argument("--mms-model", type=Path, default=ROOT / ".local/models/mms-1b-all")
    result.add_argument("--dll-dir", type=Path, default=ROOT / ".local/tools/whisper-runtime-provisional")
    return result


def offline_environment(out: Path) -> dict:
    environment = dict(os.environ)
    temp = out / "tmp"
    temp.mkdir()
    environment.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_DATASETS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1", HF_HOME=str(out / "cache/huggingface"),
        TORCH_HOME=str(out / "cache/torch"), XDG_CACHE_HOME=str(out / "cache"),
        TMP=str(temp), TEMP=str(temp), TMPDIR=str(temp), PYTHONNOUSERSITE="1",
        PYTHONDONTWRITEBYTECODE="1", TOKENIZERS_PARALLELISM="false",
        PYANNOTE_METRICS_ENABLED="0", KOTOTOKI_X0_PARENT_PID=str(os.getpid()))
    return environment


class InterruptedStage(BaseException):
    """Carry the launched child's accounting while preserving cancellation."""
    def __init__(self, cause: BaseException, cost: dict):
        self.cause, self.cost = cause, cost
        super().__init__(str(cause))


def execute_stage(command: list[str], out: Path, stage: str, environment: dict) -> dict:
    started = time.perf_counter()
    with (out / f"{stage}-stdout.log").open("x", encoding="utf-8") as stdout, \
            (out / f"{stage}-stderr.log").open("x", encoding="utf-8") as stderr:
        process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=stdout, stderr=stderr)
        try:
            code = process.wait()
        except BaseException as error:
            if process.poll() is None:
                process.terminate()
            try:
                code = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                code = process.wait()
            cost = {"stage": stage, "command": command, "pid": process.pid, "exit_code": code,
                    "wall_s": time.perf_counter() - started, "process_count": 1, "interrupted": True}
            raise InterruptedStage(error, cost) from error
    return {"stage": stage, "command": command, "pid": process.pid, "exit_code": code,
            "wall_s": time.perf_counter() - started, "process_count": 1}


def orchestrate(args: argparse.Namespace, executor=execute_stage) -> dict:
    """Fresh isolated child stages; sole parent owns shared lock for their lifetime."""
    if isinstance(args.offset, bool) or not math.isfinite(args.offset) or args.offset < 0:
        raise ValueError("--offset must be finite and nonnegative")
    if (args.segmentation == "vad") != (args.vad_manifest is not None):
        raise ValueError("--segmentation vad and --vad-manifest must be supplied together")
    out = private_output(args.out)
    out.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    costs, stage = [], "prepare"
    recipe = RECIPES[args.segmentation]
    try:
        for interpreter in (args.qwen_python, args.mms_python):
            if not interpreter.is_file():
                raise FileNotFoundError(f"Provisioned interpreter required: {interpreter}")
        manifest = freeze_sources(out)
        request = {"recipe": recipe, "segmentation": args.segmentation, "audio": str(args.audio.resolve()),
                   "offset_s": args.offset, "asr_model": str(args.asr_model.resolve()),
                   "mms_model": str(args.mms_model.resolve()), "dll_dir": str(args.dll_dir.resolve()),
                   "parent_runtime": runtime_identity()}
        if args.vad_manifest is not None:
            original = args.vad_manifest.resolve()
            frozen = out / "vad-manifest.json"
            with original.open("rb") as source, frozen.open("xb") as target:
                shutil.copyfileobj(source, target)
            request["vad_manifest"] = {"original_path": str(original), "frozen_path": str(frozen),
                                       "sha256": sha256(frozen), "execution": "precomputed_external_manifest"}
        write_json(out / "request.json", request)
        environment = offline_environment(out)
        with gpu_lock(ROOT / ".local/gpu.lock", recipe):
            for stage, interpreter in (("plan", args.mms_python), ("asr", args.qwen_python), ("align", args.mms_python)):
                check_sources(manifest)
                command = [str(interpreter.resolve()), "-m", "experiments.x0_demo.stages",
                           stage, "--run", str(out)]
                try:
                    cost = executor(command, out, stage, environment)
                except InterruptedStage as interruption:
                    costs.append(interruption.cost)
                    raise interruption.cause
                costs.append(cost)
                if cost["exit_code"]:
                    raise RuntimeError(f"{stage} child failed ({cost['exit_code']}); inspect private {stage}-stderr.log")
        check_sources(manifest)
        result = read_json(out / "alignment.json")
        result["process_costs"] = costs
        result["process_count"] = sum(c["process_count"] for c in costs)
        result["runtime_identity"]["orchestrator"] = request["parent_runtime"]
        result["stages"]["wall_s"] = time.perf_counter() - started
        result["stages"]["child_process_wall_s"] = sum(c["wall_s"] for c in costs)
        result["stages"].update({c["stage"] + "_process_wall_s": c["wall_s"] for c in costs})
        write_json(out / "result.json", result)
        with (out / "transcript.txt").open("x", encoding="utf-8") as stream:
            stream.write(result["text"])
        write_json(out / "process-costs.json", {"status": result["status"], "processes": costs,
                                              "process_count": result["process_count"], "wall_s": result["stages"]["wall_s"]})
        return result
    except BaseException as error:
        write_json(out / "failure.json", {"status": "failed", "recipe": recipe, "stage": stage,
                   "exception": type(error).__name__, "message": str(error),
                   "processes": costs, "process_count": sum(c["process_count"] for c in costs),
                   "wall_s": time.perf_counter() - started})
        raise
    finally:
        if (out / "tmp").is_dir():
            shutil.rmtree(out / "tmp")


def main() -> None:
    args = parser().parse_args()
    result = orchestrate(args)
    print(json.dumps({"status": result["status"], "recipe": result["recipe"],
                      "chunks": len(result["chunks"]), "characters": len(result["text"]),
                      "stages": result["stages"], "result": str(args.out.resolve() / "result.json")}))
    if result["status"] != "ok":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
