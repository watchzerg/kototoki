"""Freeze and execute original-audio VAD ablations through the serialized GPU harness."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.components.run import digest, read, write_new
from experiments.components.separate import read_pcm
from experiments.components.w0_vad import validate_vad
from experiments.qwen.run_cross import validate_ctc_evidence

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / ".local/components"
BASE_PLAN = LOCAL / "comp-sep-pilot-v1/plan.json"


def validate_name(name: str) -> None:
    if not name or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in name):
        raise ValueError("Use a nonempty lowercase simple experiment name")


def verify_clip(clip: dict[str, Any]) -> dict[str, Any]:
    _, identity = read_pcm(Path(clip["audio"]))
    if (identity["file_sha256"] != clip["audio_sha256"] or identity["pcm_sha256"] != clip["pcm_sha256"]
            or identity["samples"] != round(clip["duration"] * 16000)):
        raise ValueError("Original clip identity or duration changed")
    for path, expected in ((clip["reference"], clip["reference_sha256"]),
                           (clip["source_srt"], clip["source_srt_sha256"])):
        if digest(path) != expected:
            raise ValueError(f"Reference identity changed: {path}")
    return identity


def make_tasks(name: str, clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tasks = []
    python = {"vad": ROOT / ".local/envs/whisper-latest/Scripts/python.exe",
              "w0": ROOT / ".local/envs/whisper-w0-py312/Scripts/python.exe",
              "qwen": ROOT / ".local/envs/qwen-hf-final/Scripts/python.exe"}
    runtime = ROOT / ".local/tools/whisper-runtime-provisional"
    for clip in clips:
        prefix = f"{name}-{clip['id']}"
        audio, offset = str(clip["audio"]), str(clip["offset"])
        vad_dir = LOCAL / name / "vad" / clip["id"]
        vad_manifest = vad_dir / "manifest.json"
        vad_id, w0_id, asr_id, x0_id = [f"{prefix}-{suffix}" for suffix in ("vad", "w0", "x0-asr", "x0")]
        w0_output = ROOT / ".local/results" / w0_id / "result.json"
        asr_root = ROOT / ".local/results" / asr_id
        asr_output, bridge = asr_root / "result.json", asr_root / "bridge.json"
        x0_output = ROOT / ".local/results" / x0_id / "result.json"
        commands = [
            (vad_id, "vad", vad_manifest, [], [str(python["vad"]), str(ROOT / "experiments/components/vad.py"),
                "--audio", audio, "--out", str(vad_dir), "--offset", offset, "--device-index", "0"]),
            (w0_id, "w0", w0_output, [vad_id], [str(python["w0"]), str(ROOT / "experiments/components/w0_vad.py"),
                "--audio", audio, "--vad-manifest", str(vad_manifest), "--model",
                str(ROOT / ".local/models/faster-whisper-large-v3"), "--output", str(w0_output),
                "--offset", offset, "--device-index", "0", "--dll-dir", str(runtime)]),
            (asr_id, "qwen-asr", asr_output, [vad_id], [str(python["qwen"]), str(ROOT / "experiments/components/qwen_vad.py"),
                "--audio", audio, "--vad-manifest", str(vad_manifest), "--asr-model",
                str(ROOT / ".local/models/qwen3-asr-1.7b-hf"), "--output", str(asr_output),
                "--bridge-output", str(bridge), "--offset", offset]),
            (x0_id, "x0", x0_output, [vad_id, asr_id], [str(python["vad"]), str(ROOT / "experiments/whisper/run.py"),
                "--audio", audio, "--asr-result", str(bridge), "--output", str(x0_output), "--offset", offset,
                "--route", "W1", "--align-model", str(ROOT / ".local/models/wav2vec2-large-xlsr-53-japanese"),
                "--ctc-normalize", "--ctc-forced-align", "--dll-dir", str(runtime)]),
        ]
        for task_id, stage, output, dependencies, command in commands:
            tasks.append({"id": task_id, "stage": stage, "clip": clip["id"], "audio": audio,
                          "output": str(output), "command": command, "depends_on": dependencies,
                          "vad_manifest": str(vad_manifest),
                          "additional_outputs": [str(bridge)] if stage == "qwen-asr" else []})
    return tasks


def prepare(name: str) -> dict[str, Any]:
    validate_name(name)
    destination = LOCAL / name
    if destination.exists():
        raise FileExistsError("Choose a new VAD experiment identity; plans and attempts are immutable")
    if not (ROOT / "experiments/components/qwen_vad.py").is_file():
        raise FileNotFoundError("Finish qwen_vad.py before freezing the VAD experiment")
    corpus_path = ROOT / ".local/round2/corpus/manifest.json"
    corpus = read(corpus_path)
    clips = [clip for clip in corpus["clips"] if clip["id"].endswith(("01", "04"))]
    if len(clips) != 4 or {clip["film"] for clip in clips} != {"hf-ii", "hf-iii"}:
        raise ValueError("Pilot requires exactly II/III windows 01 and 04")
    for clip in clips:
        verify_clip(clip)
    base = read(BASE_PLAN)
    source_paths = {ROOT / relative for relative in (
        "experiments/run_experiment.py", "experiments/components/run_vad.py", "experiments/components/run.py",
        "experiments/components/separate.py", "experiments/components/vad.py", "experiments/components/w0_vad.py",
        "experiments/components/qwen_vad.py", "experiments/whisper/run.py", "experiments/whisper/ctc_audio.py",
        "experiments/whisper/ctc_forced.py", "experiments/whisper/ctc_transition.py",
        "experiments/qwen/run_qwen.py", "experiments/qwen/run_cross.py")}
    for relative in ("experiments/whisper/requirements-whisperx.lock", "experiments/whisper/requirements-w0.lock",
                     "experiments/qwen/requirements.lock"):
        source_paths.add(ROOT / relative)
    sources = {str(path.resolve()): digest(path) for path in sorted(source_paths)}
    # Use the explicit known asset registry, re-read current files, and never infer model identity from source snapshots.
    models = {}
    for filename, expected in base["model_sha256"].items():
        actual = digest(filename)
        if actual != expected:
            raise ValueError(f"Baseline model asset changed; resolve comparison identity before freezing: {filename}")
        models[filename] = actual
    tasks = make_tasks(name, clips)
    for task in tasks:
        if (ROOT / ".local/results" / task["id"]).exists() or Path(task["output"]).exists():
            raise FileExistsError(f"Stale evidence already occupies planned slot: {task['id']}")
        if not Path(task["command"][0]).is_file():
            raise FileNotFoundError(task["command"][0])
    plan = {"schema_version": 1, "id": name, "frozen": True,
            "scope": "exposed four-window development single-component VAD ablation",
            "component": "WhisperX 3.8.6 packaged CUDA Pyannote VAD; onset0.5 offset0.363 native max30s context up to0.2s",
            "input_policy": "original unchanged complete PCM; W0 public clip_timestamps, Qwen exact original speech crops; CTC original PCM",
            "selection_policy": "timing first with CER/coverage guardrails; compare complete four-window registry; no blind confirmation claim",
            "clips": clips, "tasks": tasks, "source_sha256": sources, "model_sha256": models,
            "input_registry": {"path": str(corpus_path), "sha256": digest(corpus_path)},
            "baseline_model_registry": {"path": str(BASE_PLAN), "sha256": digest(BASE_PLAN)},
            "cost_policy": "VAD shared once per clip; include its harness wall separately in each end-to-end route; X0 adds ASR and CTC harnesses",
            "recovery_policy": "immutable progress; recover only completed harness with exact command, sources, inputs, references and all artifacts; otherwise new run identity"}
    write_new(destination / "plan.json", plan)
    return plan


def verify_sources(plan: dict[str, Any], *, models: bool = False) -> None:
    for key in ("input_registry", "baseline_model_registry"):
        registry = plan[key]
        if digest(registry["path"]) != registry["sha256"]:
            raise ValueError(f"Frozen registry changed: {registry['path']}")
    registries = [plan["source_sha256"]]
    if models:
        registries.append(plan["model_sha256"])
    for registry in registries:
        for path, expected in registry.items():
            if digest(path) != expected:
                raise ValueError(f"Frozen identity changed: {path}")


def artifact_hashes(task: dict[str, Any]) -> dict[str, str]:
    return {filename: digest(filename) for filename in [task["output"], *task.get("additional_outputs", [])]}


def verify_artifact(task: dict[str, Any], clip: dict[str, Any]) -> None:
    result = read(task["output"])
    identity = verify_clip(clip)
    if result.get("status", "ok") != "ok":
        raise ValueError("Backend artifact did not finish successfully")
    if task["stage"] == "vad":
        validate_vad(result, identity, clip["offset"])
        for chunk in result["chunks"]:
            audio = chunk["audio"]
            if digest(audio["path"]) != audio["file_sha256"]:
                raise ValueError("VAD crop artifact changed")
    elif task["stage"] == "w0":
        if result.get("input", {}).get("file_sha256") != identity["file_sha256"] or result.get("offset_s") != clip["offset"]:
            raise ValueError("W0 input identity or source origin mismatch")
        if result.get("experimental_vad", {}).get("file_sha256") != digest(task["vad_manifest"]):
            raise ValueError("W0 used a different VAD manifest")
        if not result["experimental_vad"]["empty_speech"] and result["devices"]["asr"].get("device") != "cuda":
            raise ValueError("W0 CUDA evidence is absent")
    elif task["stage"] == "qwen-asr":
        # The bridge contract is the immutable original-audio interface consumed by the existing CTC adapter.
        bridge = read(task["additional_outputs"][0])
        if bridge.get("input", {}).get("pcm_sha256") != identity["pcm_sha256"] or bridge.get("offset_s") != clip["offset"]:
            raise ValueError("Qwen bridge differs from original PCM or source origin")
        if not isinstance(bridge.get("original_segments"), list):
            raise ValueError("Qwen bridge lacks complete original segment registry")
        if (result.get("input", {}).get("sha256") != identity["file_sha256"]
                or result.get("source_start_seconds") != clip["offset"]
                or result.get("experimental_vad", {}).get("file_sha256") != digest(task["vad_manifest"])
                or result.get("adapter_sha256") != digest(ROOT / "experiments/components/qwen_vad.py")
                or bridge.get("provenance", {}).get("source_result_sha256") != digest(task["output"])):
            raise ValueError("Qwen raw result, bridge, VAD or executed adapter identity mismatch")
        vad = read(task["vad_manifest"])
        windows = result.get("windows", [])
        if len(windows) != len(vad["chunks"]) or len(bridge["original_segments"]) != len(windows):
            raise ValueError("Qwen omitted a VAD window from raw text or bridge")
        from experiments.components.qwen_vad import cuda_evidence
        for window, chunk, segment in zip(windows, vad["chunks"], bridge["original_segments"]):
            if (window.get("start_sample") != chunk["start_sample"]
                    or window.get("end_sample") != chunk["end_sample_exclusive"]
                    or window.get("token_limit_reached") is not False
                    or segment.get("start") != chunk["start_sample"] / 16000
                    or segment.get("end") != chunk["end_sample_exclusive"] / 16000
                    or segment.get("text") != window.get("text")):
                raise ValueError("Qwen window identity, completeness or generation limit mismatch")
            cuda_evidence(window.get("asr_input_evidence", {}))
        if ("".join(segment["text"] for segment in bridge["original_segments"]) != result.get("text")
                or result.get("stage_execution", {}).get("asr") !=
                ("executed" if windows else "not_executed_empty_vad")):
            raise ValueError("Qwen changed complete ASR text or claimed inference on empty VAD")
    elif task["stage"] == "x0":
        if result.get("input", {}).get("file_sha256") != identity["file_sha256"] or result.get("offset_s") != clip["offset"]:
            raise ValueError("CTC input identity or source origin mismatch")
        bridge_path = task["command"][task["command"].index("--asr-result") + 1]
        bridge = read(bridge_path)
        if (result.get("native", {}).get("reused_asr_file") != bridge_path
                or result.get("original_segments") != bridge.get("original_segments")
                or result.get("text") != bridge.get("text")):
            raise ValueError("CTC altered the complete Qwen ASR text or consumed a different bridge")
        validate_ctc_evidence(result)


def verify_harness(task: dict[str, Any], clip: dict[str, Any], plan: dict[str, Any]) -> Path:
    directory = ROOT / ".local/results" / task["id"]
    path = directory / "manifest.json"
    manifest = read(path)
    if (manifest.get("id") != task["id"] or manifest.get("status") != "completed"
            or manifest.get("returncode") != 0 or manifest.get("command") != task["command"]
            or manifest.get("audio_sha256") != clip["audio_sha256"]
            or manifest.get("reference_unchanged") is not True
            or manifest.get("reference_sha256_expected") != clip["source_srt_sha256"]
            or manifest.get("reference_sha256_before") != clip["source_srt_sha256"]
            or manifest.get("reference_sha256_after") != clip["source_srt_sha256"]):
        raise ValueError("Harness completion, command, input or reference evidence does not match frozen task")
    source_hashes = manifest.get("source_sha256", {})
    adapter = str(Path(task["command"][1]).relative_to(ROOT))
    if adapter not in source_hashes or str(Path("experiments/run_experiment.py")) not in source_hashes:
        raise ValueError("Harness lacks required source snapshots")
    for relative, expected in source_hashes.items():
        snapshot = directory / "source" / relative
        original = (ROOT / relative).resolve()
        frozen = plan["source_sha256"].get(str(original))
        if (not original.is_relative_to(ROOT) or frozen is not None and frozen != expected
                or digest(snapshot) != expected):
            raise ValueError("Harness source snapshot differs from the frozen plan")
    verify_artifact(task, clip)
    return path


def verify_progress(task: dict[str, Any], record: dict[str, Any], plan_hash: str) -> None:
    if record.get("plan_sha256") != plan_hash or record.get("task_command") != task["command"]:
        raise ValueError("Progress belongs to another frozen plan or command")
    if record.get("status") not in ("completed", "failed", "blocked"):
        raise ValueError("Incomplete progress cannot be resumed; use a new experiment identity")
    for filename, expected in record.get("artifact_sha256", {}).items():
        if digest(filename) != expected:
            raise ValueError("Recorded output or dependency artifact changed")
    for dependency in record.get("dependencies", {}).values():
        if digest(dependency["path"]) != dependency["progress_sha256"]:
            raise ValueError("Recorded dependency progress changed")
    for filename in [task["output"], *task.get("additional_outputs", [])]:
        if Path(filename).exists() and filename not in record.get("artifact_sha256", {}):
            raise ValueError("Unrecorded output appeared after this attempt")
    if record["status"] == "completed" and (
            not record.get("output_sha256")
            or record["output_sha256"] != record.get("artifact_sha256", {}).get(task["output"])):
        raise ValueError("Completed progress lacks a consistent primary output identity")
    if record.get("harness_sha256"):
        path = ROOT / ".local/results" / task["id"] / "manifest.json"
        if digest(path) != record["harness_sha256"]:
            raise ValueError("Recorded harness changed")


def run(name: str) -> None:
    validate_name(name)
    plan_path = LOCAL / name / "plan.json"
    plan = read(plan_path)
    if plan.get("id") != name or plan.get("frozen") is not True:
        raise ValueError("A frozen matching VAD plan is required")
    plan_hash = digest(plan_path)
    verify_sources(plan, models=True)
    clips = {clip["id"]: clip for clip in plan["clips"]}
    for task in plan["tasks"]:
        verify_sources(plan)
        clip = clips[task["clip"]]
        verify_clip(clip)
        progress_path = LOCAL / name / "progress" / f"{task['id']}.json"
        if progress_path.exists():
            prior = read(progress_path)
            verify_progress(task, prior, plan_hash)
            if prior["status"] == "completed":
                verify_harness(task, clip, plan)
            continue
        record: dict[str, Any] = {"plan_sha256": plan_hash, "task_command": task["command"],
                                  "input_sha256": clip["audio_sha256"], "dependencies": {}, "artifact_sha256": {}}
        blocked = []
        for dependency_id in task["depends_on"]:
            dependency = next(entry for entry in plan["tasks"] if entry["id"] == dependency_id)
            dependency_path = LOCAL / name / "progress" / f"{dependency_id}.json"
            parent = read(dependency_path)
            verify_progress(dependency, parent, plan_hash)
            record["dependencies"][dependency_id] = {"path": str(dependency_path),
                "progress_sha256": digest(dependency_path), "status": parent["status"]}
            if parent["status"] != "completed":
                blocked.append(dependency_id)
            else:
                verify_harness(dependency, clip, plan)
                record["artifact_sha256"].update(artifact_hashes(dependency))
        if blocked:
            record.update(status="blocked", reason="upstream_stage_failed", blocked_by=blocked)
            write_new(progress_path, record)
            continue
        if task["stage"] != "vad":
            record["vad_manifest_sha256"] = digest(task["vad_manifest"])
        harness_path = ROOT / ".local/results" / task["id"] / "manifest.json"
        harness_command = [sys.executable, str(ROOT / "experiments/run_experiment.py"), "--id", task["id"],
                           "--audio", task["audio"], "--reference", clip["source_srt"],
                           "--reference-sha256", clip["source_srt_sha256"], "--timeout", "3600", "--", *task["command"]]
        record["command"] = harness_command
        if harness_path.parent.exists():
            try:
                verify_harness(task, clip, plan)
            except (OSError, ValueError, KeyError) as error:
                raise RuntimeError(f"Interrupted/stale evidence retained at {harness_path.parent}; use a new run identity") from error
            record.update(status="completed", returncode=0, recovered_completed_harness=True,
                          harness_sha256=digest(harness_path), output_sha256=digest(task["output"]))
            record["artifact_sha256"].update(artifact_hashes(task))
            write_new(progress_path, record)
            continue
        if any(Path(filename).exists() for filename in [task["output"], *task["additional_outputs"]]):
            raise RuntimeError("Unbound preexisting output retained; choose a new experiment identity")
        print(json.dumps({"starting": task["id"]}), flush=True)
        done = subprocess.run(harness_command, cwd=ROOT, check=False)
        record.update(status="failed", returncode=done.returncode)
        if harness_path.is_file():
            record["harness_sha256"] = digest(harness_path)
        for filename in [task["output"], *task["additional_outputs"]]:
            if Path(filename).is_file():
                record["artifact_sha256"][filename] = digest(filename)
        if Path(task["output"]).is_file():
            record["output_sha256"] = digest(task["output"])
        if done.returncode == 0:
            try:
                verify_harness(task, clip, plan)
                record["status"] = "completed"
            except (OSError, ValueError, KeyError) as error:
                record["failure_reason"] = str(error)
        write_new(progress_path, record)
        print(json.dumps({"finished": task["id"], "status": record["status"]}), flush=True)
    verify_sources(plan, models=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.name)
    else:
        run(args.name)


if __name__ == "__main__":
    main()
