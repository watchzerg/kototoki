"""Serial offline full-film candidates with imported fresh W0/X0 controls."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import os
from pathlib import Path

from experiments.fullfilm_comparison.run import check_sources, execute, read, write
from experiments.vad_comparison.run import verify_clips
from experiments.w0_demo.run import gpu_lock, sha256

ROOT = Path(__file__).resolve().parents[2]
MODELS = {
    "cohere": ("CohereLabs/cohere-transcribe-03-2026", "b1eacc2686a3d08ceaae5f24a88b1d519620bc09"),
    "granite": ("ibm-granite/granite-speech-4.1-2b", "de575db64086f84fdc79da4932d1076e965bc546"),
    "nemotron": ("nvidia/nemotron-3.5-asr-streaming-0.6b", "ea30d66debe3740a08b573244286791d423d6b3e"),
}
CONTROL_IDS = ("w0-pyannote-current", "x0-pyannote-current")
FINISHED = {"completed", "partial", "invocation_failed"}


def source_paths() -> list[Path]:
    """Freeze inference dependencies, excluding the independent result evaluator."""
    from experiments.fullfilm_comparison.run import source_paths as baseline_sources
    paths = baseline_sources()
    paths.extend(p for p in (ROOT / "experiments/asr_candidates").glob("*.py")
                 if not p.name.startswith("test_") and p.name != "evaluate.py")
    return sorted(set(paths))


def checked_file(path: str | Path, digest: str, description: str) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_file() or sha256(resolved) != digest:
        raise ValueError(f"Frozen {description} changed: {resolved}")
    return resolved


def record_failure(slot: dict, stage: str, path: Path) -> None:
    slot.update(status="invocation_failed", failure_stage=stage, failure_path=str(path),
        failure_kind="process_failed_without_evidence",
        failure_reason=f"{stage} process did not produce usable terminal evidence")
    if path.is_file():
        failure = read(path)
        slot.update(failure_sha256=sha256(path), failure_kind=failure.get("failure_kind", "stage_failed"),
            failure_exception=failure.get("exception"), failure_reason=str(failure.get("message", ""))[:4000])


def verify_provision(candidate: str, manifest: dict) -> None:
    expected_id, expected_revision = MODELS[candidate]
    if (manifest.get("status") != "ready" or manifest.get("model_id") != expected_id
            or manifest.get("model_revision") != expected_revision):
        raise ValueError(f"Ready {candidate} manifest must match the pinned model and revision")
    model_path = Path(manifest["path"]).resolve()
    files = manifest.get("files_sha256")
    if not model_path.is_dir() or not isinstance(files, dict) or not files:
        raise ValueError(f"Ready {candidate} requires a local model directory and file hashes")
    for name, digest in files.items():
        path = (model_path / name).resolve()
        if not path.is_relative_to(model_path) or path == model_path:
            raise ValueError("Model file manifest escapes the model directory")
        checked_file(path, digest, "model file")


def provision(folder: Path, candidate: str) -> dict | None:
    path = folder / f"{candidate}-ready.json"
    if not path.exists():
        return None
    manifest = read(path)
    if manifest.get("status") != "ready":
        return None
    verify_provision(candidate, manifest)
    return {"manifest_path": str(path.resolve()), "manifest_sha256": sha256(path),
            "manifest": manifest}


def verify_evidence(study: dict) -> None:
    check_sources(study["source_sha256"])
    checked_file(study["corpus_plan_path"], study["corpus_plan_sha256"], "corpus")
    checked_file(study["candidate_path"], study["candidate_sha256"], "VAD candidate")
    snapshot = study["control_import"]
    checked_file(snapshot["snapshot_path"], snapshot["snapshot_sha256"], "control snapshot")
    for name, digest in study["imported_artifacts_sha256"].items():
        checked_file(name, digest, "imported control evidence")
    for route in study["routes"]:
        for slot in route["runs"]:
            for key in ("plan", "asr", "result", "failure"):
                if f"{key}_path" in slot and f"{key}_sha256" in slot:
                    checked_file(slot[f"{key}_path"], slot[f"{key}_sha256"], "stage evidence")
    for segment in study["segmentation_runs"].values():
        checked_file(segment["manifest_path"], segment["manifest_sha256"], "derived segmentation plan")
        original = read(Path(segment["origin_plan_path"]))
        derived = read(Path(segment["manifest_path"]))
        expected = {**original, "source_sha256": study["source_sha256"],
                    "origin_plan_path": segment["origin_plan_path"],
                    "origin_plan_sha256": segment["origin_plan_sha256"]}
        if derived != expected:
            raise ValueError("Derived segmentation plan changed original input or windows")
    for candidate, record in study.get("provisions", {}).items():
        checked_file(record["manifest_path"], record["manifest_sha256"], "model provision")
        verify_provision(candidate, record["manifest"])


def initialize(folder: Path, baseline_path: Path, provision_root: Path) -> dict:
    baseline_path = baseline_path.resolve()
    baseline = read(baseline_path)
    check_sources(baseline["source_sha256"])
    if baseline.get("candidate", {}).get("status") != "ready" or baseline["candidate"].get("device") != "cuda:0":
        raise ValueError("Fresh controls require the frozen ready CUDA Pyannote candidate")
    clips = baseline["clips"]
    ids = [c["id"] for c in clips]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("Control corpus must have unique full-film clip ids")
    controls = []
    imported = {}
    for route_id in CONTROL_IDS:
        matches = [r for r in baseline["routes"] if r["id"] == route_id]
        if len(matches) != 1:
            raise ValueError(f"Fresh control route missing or duplicated: {route_id}")
        route = copy.deepcopy(matches[0])
        if sorted(s["clip_id"] for s in route["runs"]) != sorted(ids):
            raise ValueError("Control slots must cover every full film exactly once")
        for slot in route["runs"]:
            if slot["status"] not in FINISHED:
                raise ValueError(f"Fresh control slot is not terminal: {route_id} {slot['clip_id']}")
            for key in ("plan", "asr", "result"):
                if f"{key}_path" in slot:
                    file = checked_file(slot[f"{key}_path"], slot[f"{key}_sha256"], "control evidence")
                    imported[str(file)] = slot[f"{key}_sha256"]
            if slot["status"] in {"completed", "partial"} and "result_path" not in slot:
                raise ValueError("Completed control slot requires a hashed alignment result")
            if slot["status"] == "invocation_failed" and "failure_path" in slot:
                stage = "align" if "asr_path" in slot else "asr"
                record_failure(slot, stage, Path(slot["failure_path"]))
                if "failure_sha256" in slot:
                    imported[str(Path(slot["failure_path"]).resolve())] = slot["failure_sha256"]
            slot["import_provenance"] = {"study_path": str(baseline_path),
                "study_sha256_at_import": sha256(baseline_path), "route_id": route_id,
                "fresh_control": True, "inference_reused_for_comparison": True}
        controls.append(route)
    segments = {}
    for clip in clips:
        key = f"pyannote-current-{clip['id']}"
        segment = copy.deepcopy(baseline["segmentation_runs"].get(key, {}))
        if segment.get("status") != "completed":
            raise ValueError(f"Fresh segmentation not completed: {key}")
        plan = checked_file(segment["manifest_path"], segment["manifest_sha256"], "segmentation plan")
        original = read(plan)
        if (original.get("segmentation") != "pyannote-current" or original.get("clip_id") != clip["id"]
                or original.get("source_sha256") != baseline["source_sha256"]
                or original.get("input", {}).get("file_sha256") != clip["audio_sha256"]
                or original.get("input", {}).get("pcm_sha256") != clip["pcm_sha256"]
                or original.get("input", {}).get("samples") != clip["samples"]
                or original.get("offset_s") != clip["offset"]):
            raise ValueError("Segmentation plan differs from the frozen full-film corpus")
        imported[str(plan)] = segment["manifest_sha256"]
        segment.update(origin_plan_path=str(plan), origin_plan_sha256=segment["manifest_sha256"])
        segments[key] = segment
    before = verify_clips(clips)
    sources = dict(baseline["source_sha256"])
    for path in source_paths():
        name = path.relative_to(ROOT).as_posix()
        digest = sha256(path)
        if name in sources and sources[name] != digest:
            raise ValueError(f"Current inference source differs from controls: {name}")
        sources[name] = digest
    for name, digest in sources.items():
        source = checked_file(ROOT / name, digest, "inference source")
        target = folder / "source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(source.read_bytes())
    snapshot = folder / "control-study-at-import.json"
    with snapshot.open("xb") as stream:
        stream.write(baseline_path.read_bytes())
    for key, segment in segments.items():
        origin = read(Path(segment["origin_plan_path"]))
        derived = {**origin, "source_sha256": sources,
                   "origin_plan_path": segment["origin_plan_path"],
                   "origin_plan_sha256": segment["origin_plan_sha256"]}
        destination = folder / "segmentation" / key / "plan.json"
        write(destination, derived)
        segment.update(manifest_path=str(destination.resolve()), manifest_sha256=sha256(destination),
                       import_provenance={"study_path": str(baseline_path), "fresh_control": True})
    study = {"schema_version": 1, "study_id": folder.name, "terminal": False,
        "created_utc": datetime.now(timezone.utc).isoformat(), "clips": copy.deepcopy(clips),
        "corpus_plan_path": baseline["corpus_plan_path"], "corpus_plan_sha256": baseline["corpus_plan_sha256"],
        "candidate_path": baseline["candidate_path"], "candidate_sha256": baseline["candidate_sha256"],
        "candidate": copy.deepcopy(baseline["candidate"]), "source_sha256": sources,
        "control_import": {"study_path": str(baseline_path), "study_sha256_at_import": sha256(snapshot),
                           "snapshot_path": str(snapshot.resolve()), "snapshot_sha256": sha256(snapshot)},
        "imported_artifacts_sha256": imported, "segmentation_runs": segments,
        "input_checks_before": before, "provision_root": str(provision_root.resolve()), "provisions": {},
        "protocol": {"full_audio": True, "inference_plan_scope": "whole film; no scoring-bin reset",
            "failure_policy": "record failed source chunk, continue remaining chunks without retry",
            "scoring_bins_s": 300, "reference_denominator": "all reference characters in both full films",
            "translation": False, "external_inference": False}, "routes": controls}
    for name, (model_id, revision) in MODELS.items():
        study["routes"].append({"id": name, "family": name, "candidate_id": name,
            "model_id": model_id, "model_revision": revision, "segmentation": "pyannote-current",
            "runs": [{"clip_id": c["id"], "status": "pending"} for c in clips]})
    verify_evidence(study)
    return study


def environment(folder: Path) -> dict:
    temp, cache = folder / "tmp", folder / "cache"
    temp.mkdir(exist_ok=True)
    cache.mkdir(exist_ok=True)
    return dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1",
        KOTOTOKI_FULLFILM_PARENT_PID=str(os.getpid()), TEMP=str(temp), TMP=str(temp), TMPDIR=str(temp),
        HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HOME=str(cache / "huggingface"),
        HF_HUB_CACHE=str(cache / "huggingface/hub"), TORCH_HOME=str(cache / "torch"),
        XDG_CACHE_HOME=str(cache), NUMBA_CACHE_DIR=str(cache / "numba"))


def run_study(folder: Path, args: argparse.Namespace) -> None:
    folder = folder.resolve()
    private = (ROOT / ".local/fullfilm-comparison").resolve()
    if folder == private or not folder.is_relative_to(private):
        raise ValueError("Study must be a child of .local/fullfilm-comparison")
    path = folder / "study.json"
    if not path.exists() and folder.exists() and any(folder.iterdir()):
        raise FileExistsError("Orphan evidence exists without a study registry; inspect it before proceeding")
    folder.mkdir(parents=True, exist_ok=True)
    study = read(path) if path.exists() else initialize(folder, args.baseline_study, args.provision_root)
    if any(s["status"] == "running" for r in study["routes"] for s in r["runs"]):
        raise RuntimeError("Inspect interrupted running work; refusing duplicate inference")
    verify_evidence(study)
    study["input_checks_before_resume"] = verify_clips(study["clips"])
    study.update(terminal=False, controller_pid=os.getpid(), controller_started_utc=datetime.now(timezone.utc).isoformat())
    write(path, study)
    env = environment(folder)
    native = ROOT / ".local/envs/asr-candidates-py312-v1/Scripts/python.exe"
    whisper = ROOT / ".local/envs/whisper-latest/Scripts/python.exe"
    for route in study["routes"]:
        name = route["family"]
        if name not in MODELS or (args.candidates and name not in args.candidates):
            continue
        eligible = [s for s in route["runs"] if s["status"] in {"pending", "blocked_access"}]
        if not eligible:
            continue
        ready = study["provisions"].get(name)
        if ready is None:
            ready = provision(Path(study["provision_root"]), name)
        if ready is None:
            for slot in eligible:
                slot.update(status="blocked_access", failure_reason="Pinned local model provision is not ready",
                            provision_path=str(Path(study["provision_root"]) / f"{name}-ready.json"))
            write(path, study)
            print(f"BLOCKED {name}", flush=True)
            continue
        study["provisions"][name] = ready
        write(path, study)
        for slot in eligible:
            check_sources(study["source_sha256"])
            segment = study["segmentation_runs"][f"pyannote-current-{slot['clip_id']}"]
            plan_path = checked_file(segment["manifest_path"], segment["manifest_sha256"], "segmentation plan")
            out = folder / "runs" / f"{route['id']}-{slot['clip_id']}"
            out.mkdir(parents=True, exist_ok=False)
            job = {"schema_version": 1, "route": name, "candidate_id": name,
                "model_id": route["model_id"], "model_revision": route["model_revision"],
                "asr_model": ready["manifest"]["path"], "plan_path": str(plan_path),
                "model_files_sha256": ready["manifest"]["files_sha256"],
                "plan_sha256": segment["manifest_sha256"], "source_sha256": study["source_sha256"],
                "mms_model": str(ROOT / ".local/models/mms-1b-all"),
                "dll_dir": str(ROOT / ".local/tools/whisper-runtime-provisional")}
            job_path = out / "asr-job.json"
            write(job_path, job)
            slot.update(status="running", plan_path=str(plan_path), plan_sha256=segment["manifest_sha256"],
                        origin_plan_path=segment["origin_plan_path"], origin_plan_sha256=segment["origin_plan_sha256"],
                        segmentation_process_wall_s=segment["wall_s"], processes={})
            write(path, study)
            print(f"ASR {name} {slot['clip_id']}", flush=True)
            cost = execute([str(native), "-m", "experiments.asr_candidates.worker", "asr", "--job",
                            str(job_path), "--out", str(out / "asr")], out / "asr", env)
            slot["processes"]["asr"] = cost
            asr_path = out / "asr/asr.json"
            if cost["exit_code"] not in {0, 2} or not asr_path.exists():
                record_failure(slot, "asr", out / "asr/failure.json")
                write(path, study)
                continue
            slot.update(asr_path=str(asr_path), asr_sha256=sha256(asr_path))
            write(path, study)
            job.update(asr_stage_path=str(asr_path), asr_stage_sha256=slot["asr_sha256"])
            job_path = out / "align-job.json"
            write(job_path, job)
            check_sources(study["source_sha256"])
            print(f"ALIGN {name} {slot['clip_id']}", flush=True)
            cost = execute([str(whisper), "-m", "experiments.asr_candidates.worker", "align", "--job",
                            str(job_path), "--out", str(out / "align")], out / "align", env)
            slot["processes"]["align"] = cost
            result_path = out / "align/alignment.json"
            if cost["exit_code"] in {0, 2} and result_path.exists():
                result = read(result_path)
                if result.get("status") not in {"ok", "partial"}:
                    raise ValueError("Alignment stage emitted an invalid terminal status")
                slot.update(status="partial" if result["status"] == "partial" else "completed",
                            result_path=str(result_path), result_sha256=sha256(result_path))
            else:
                record_failure(slot, "align", out / "align/failure.json")
            write(path, study)
            print(f"DONE {name} {slot['clip_id']} {slot['status']}", flush=True)
    verify_evidence(study)
    study["input_checks_after"] = verify_clips(study["clips"])
    states = [s["status"] for r in study["routes"] for s in r["runs"]]
    study.update(terminal=all(s in FINISHED | {"blocked_access"} for s in states),
        all_model_slots_attempted=all(s in FINISHED for s in states),
        all_models_tested=all(s["status"] in {"completed", "partial"} or "asr_path" in s
                              for r in study["routes"] for s in r["runs"]),
        resumable="blocked_access" in states)
    write(path, study)
    print(f"STUDY {path} terminal={study['terminal']} all_models_tested={study['all_models_tested']}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-id", default="asr-candidates-v1")
    parser.add_argument("--baseline-study", type=Path,
                        default=ROOT / ".local/fullfilm-comparison/asr-controls-v1/study.json")
    parser.add_argument("--provision-root", type=Path, default=ROOT / ".local/asr-candidates-provision")
    parser.add_argument("--candidates", nargs="+", choices=tuple(MODELS))
    args = parser.parse_args()
    if not args.study_id or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in args.study_id):
        parser.error("study-id must be lowercase ASCII letters, digits and hyphens")
    folder = ROOT / ".local/fullfilm-comparison" / args.study_id
    with gpu_lock(ROOT / ".local/gpu.lock", "asr-candidates-v1"):
        run_study(folder, args)


if __name__ == "__main__":
    main()
