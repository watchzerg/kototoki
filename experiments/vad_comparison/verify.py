"""Independent stdlib audit of frozen study evidence; never prints transcripts."""
from __future__ import annotations

import argparse
from array import array
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import wave

ROOT = Path(__file__).resolve().parents[2]
ROUTES = tuple(f"{family}-{vad}" for family in ("w0", "x0")
               for vad in ("original", "pyannote-current", "silero", "fsmn", "firered"))


def package_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value.lower())


def read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Expected object")
    return value


def resolve(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


class Files:
    """Cache hashes by stat identity so large shared weights are read once."""
    def __init__(self):
        self.hashes = {}

    def digest(self, path: Path) -> str:
        path = path.resolve()
        stat = path.stat()
        key = (path, stat.st_size, stat.st_mtime_ns)
        if key not in self.hashes:
            with path.open("rb") as stream:
                self.hashes[key] = hashlib.file_digest(stream, "sha256").hexdigest()
        return self.hashes[key]


def float32_pcm(pcm16: bytes) -> bytes:
    """PCM16 division is exact in binary float32, including negative zero policy."""
    values = array("h")
    values.frombytes(pcm16)
    if sys.byteorder != "little":
        values.byteswap()
    floats = array("f", (value / 32768.0 for value in values))
    if sys.byteorder != "little":
        floats.byteswap()
    return floats.tobytes()


def boundaries(row: dict, samples: int, *, require_integer: bool = False) -> tuple[int, int]:
    start, end = row.get("start_sample"), row.get("end_sample")
    if start is None and end is None and not require_integer:
        start, end = int(row["start"] * 16000), int(row["end"] * 16000)
    if (any(isinstance(v, bool) or not isinstance(v, int) for v in (start, end))
            or not 0 <= start < end <= samples or end-start > 480000):
        raise ValueError("Invalid integer crop")
    return start, end


def audit_sources(document: dict, folder: Path, files: Files, issues: list[str]) -> dict:
    checked = current_differences = 0
    sources = document.get("source_sha256", {})
    if not sources:
        issues.append("source_hashes_missing")
    for name, expected in sources.items():
        target = folder / "source" / name
        if not target.is_file() or files.digest(target) != expected:
            issues.append("source_snapshot_hash_mismatch")
        else:
            checked += 1
        current = ROOT / name if "/" in name else ROOT / "experiments/w0_demo" / name
        if current.is_file() and files.digest(current) != expected:
            current_differences += 1
    for name, expected in document.get("shared_source_sha256", {}).items():
        target = folder / "source" / name.replace("/", "_")
        if not target.is_file() or files.digest(target) != expected:
            issues.append("shared_source_snapshot_hash_mismatch")
        else:
            checked += 1
    return {"snapshot_hashes_checked": checked, "current_source_differences": current_differences}


def audit_runtime(document: dict, command: list, files: Files, issues: list[str]) -> dict:
    checked = models = 0
    metadata = document.get("effective_parameters", {})
    for family, hashes in document.get("model_files_sha256", {}).items():
        options = metadata.get("asr" if family == "asr" else "alignment", {})
        base = options.get("path", options.get("model_path"))
        if not base and hashes:
            issues.append("model_path_missing")
            continue
        for name, expected in hashes.items():
            path = resolve(base) / name
            if not path.is_file() or files.digest(path) != expected:
                issues.append("model_asset_hash_mismatch")
            else:
                models += 1
    runtime = document.get("runtime_identity", {})
    implementation = metadata.get("asr", {}).get("installed_implementation_sha256", {})
    executable = runtime.get("asr", {}).get("executable") if isinstance(runtime.get("asr"), dict) else None
    if implementation:
        if not executable:
            issues.append("implementation_runtime_executable_missing")
        else:
            base = resolve(executable).parents[1] / "Lib/site-packages/transformers/models/qwen3_asr"
            for name, expected in implementation.items():
                path = base / name
                if not path.is_file() or files.digest(path) != expected:
                    issues.append("installed_implementation_hash_mismatch")
                else:
                    checked += 1
    runtimes = [runtime] if "packages" in runtime else [v for v in runtime.values() if isinstance(v, dict)]
    packages_checked = 0
    for observation in runtimes:
        executable = observation.get("executable", command[0] if command else None)
        if not executable:
            issues.append("runtime_executable_missing")
            continue
        base = resolve(executable).parents[1] / "Lib/site-packages"
        installed = {}
        for path in base.glob("*.dist-info/METADATA"):
            name = version = None
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    if line == "\n":
                        break
                    if line.startswith("Name: "):
                        name = package_name(line[6:].strip())
                    if line.startswith("Version: "):
                        version = line[9:].strip()
            if name:
                installed[name] = version
        for name, version in observation.get("packages", {}).items():
            if installed.get(package_name(name)) != version:
                issues.append("runtime_package_version_mismatch")
            else:
                packages_checked += 1
    return {"model_asset_hashes_checked": models, "installed_implementation_hashes_checked": checked,
            "runtime_package_versions_checked": packages_checked}


def compare_original(document: dict, family: str, clip_id: str) -> dict:
    if not clip_id.endswith("window-01"):
        return {"status": "not_applicable"}
    suffix = "-fixed30" if family == "x0" else ""
    path = ROOT / f".local/{family}-demo/verified-v1-{clip_id}{suffix}/result.json"
    if not path.is_file():
        return {"status": "historical_reference_missing"}
    historical = read(path)
    token_key = "token_ids" if family == "x0" else "tokens"
    matches = {key: document.get(key) == historical.get(key) for key in (
        "text", "units", "chunks", "original_segments", "alignment_records")}
    def without_timers(traces):
        return [{key: value for key, value in row.items() if key not in ("preprocess_s", "inference_s")}
                for row in traces]
    matches["asr_traces_without_timers"] = (without_timers(document.get("asr_traces", []))
                                            == without_timers(historical.get("asr_traces", [])))
    matches["tokens"] = ([row.get(token_key) for row in document.get("asr_traces", [])]
                         == [row.get(token_key) for row in historical.get("asr_traces", [])])
    return {"status": "identical" if all(matches.values()) else "changed", "matches": matches}


def audit_crops(document: dict, clip: dict, pcm: bytes, manifest: dict | None, issues: list[str]) -> dict:
    samples = len(pcm)//2
    chunks, segments, traces = (document.get(key, []) for key in ("chunks", "original_segments", "asr_traces"))
    new_vad = manifest is not None
    expected = [boundaries(chunk, samples, require_integer=True) for chunk in manifest["chunks"]] if new_vad else None
    actual = [boundaries(chunk, samples, require_integer=new_vad) for chunk in chunks]
    if expected is not None and actual != expected:
        issues.append("manifest_result_windows_differ")
    if len(segments) != len(chunks) or len(traces) != len(chunks):
        issues.append("window_segment_trace_count_mismatch")
    if new_vad and [boundaries(segment, samples, require_integer=True) for segment in segments] != expected:
        issues.append("manifest_asr_segment_windows_differ")
    if [boundaries(trace, samples, require_integer=True) for trace in traces] != actual:
        issues.append("asr_trace_windows_differ")
    records = document.get("alignment_records", [])
    if len(records) != len(segments):
        issues.append("alignment_record_count_mismatch")
    hashes = mms = no_text = no_eligible = failures = 0
    raw_cache = {}
    def raw_hash(start: int, end: int) -> str:
        key = (start, end)
        if key not in raw_cache:
            raw_cache[key] = hashlib.sha256(float32_pcm(pcm[start*2:end*2])).hexdigest()
        return raw_cache[key]
    for index, trace in enumerate(traces):
        if "pcm_float32_sha256" in trace:
            start, end = actual[index]
            if trace["pcm_float32_sha256"] != raw_hash(start, end):
                issues.append("asr_source_float32_pcm_hash_mismatch")
            hashes += 1
    for index, record in enumerate(records):
        if record.get("failure"):
            failures += 1
        normalization = record.get("normalization")
        if not normalization:
            if index < len(segments) and not segments[index].get("text"):
                no_text += 1
            elif record.get("skip_reason") == "no_eligible_characters" and not record.get("tokens"):
                no_eligible += 1
            elif record.get("failure"):
                pass
            else:
                issues.append("mms_normalization_unexplained_missing")
            continue
        start, end = normalization.get("source_sample_start"), normalization.get("source_sample_end")
        if (any(isinstance(value, bool) or not isinstance(value, int) for value in (start, end))
                or not 0 <= start < end <= samples):
            issues.append("mms_source_samples_invalid")
            continue
        if new_vad and (start, end) != expected[index]:
            issues.append("manifest_mms_source_windows_differ")
        if normalization.get("valid_samples") != end-start:
            issues.append("mms_valid_sample_count_mismatch")
        if normalization.get("raw_float32_sha256") != raw_hash(start, end):
            issues.append("mms_source_float32_pcm_hash_mismatch")
        mms += 1
    if document.get("text") != "".join(row.get("text", "") for row in segments):
        issues.append("full_asr_text_not_preserved")
    covered = [0]*len(document.get("text", ""))
    for unit in document.get("units", []):
        lo, hi = unit.get("char_start"), unit.get("char_end")
        if (any(isinstance(value, bool) or not isinstance(value, int) for value in (lo, hi))
                or not 0 <= lo < hi <= len(covered)):
            issues.append("character_unit_bounds_invalid")
            continue
        for char in range(lo, hi):
            covered[char] += 1
    if any(value != 1 for value in covered):
        issues.append("character_accounting_incomplete_or_duplicate")
    if document.get("input", {}).get("pcm_sha256") != hashlib.sha256(pcm).hexdigest():
        issues.append("result_input_pcm_hash_mismatch")
    if document.get("offset_s") != clip["offset"]:
        issues.append("result_source_offset_mismatch")
    return {"source_windows_checked": len(actual), "asr_pcm_hashes_checked": hashes,
            "mms_pcm_hashes_checked": mms, "mms_no_text_skips": no_text, "mms_failure_records": failures,
            "mms_no_eligible_character_skips": no_eligible,
            "characters_accounted": len(covered)}


def study_provision_dirs(study: dict) -> dict[str, Path]:
    """Resolve explicit candidate pins without falling back on invalid overrides."""
    overrides = study.get("vad_provision_dirs", {})
    if not isinstance(overrides, dict):
        raise ValueError("vad_provision_dirs must be an object keyed by candidate id")
    candidates = {route.split("-", 1)[1] for route in ROUTES} - {"original"}
    folders = {}
    for candidate, value in overrides.items():
        if candidate not in candidates or not isinstance(value, str) or not value.strip():
            raise ValueError("vad_provision_dirs requires known candidate ids and nonempty directory paths")
        folder = resolve(value)
        if not folder.is_dir() or any(not (folder / name).is_file() for name in (
                "models-manifest.json", "packages-manifest.json")):
            raise ValueError(f"VAD provision directory must contain both manifests: {folder}")
        folders[candidate] = folder
    return folders


def audit_vad_assets(manifest: dict, files: Files, issues: list[str],
                     *, provision_dir: Path | None = None) -> dict:
    folder = provision_dir if provision_dir is not None else ROOT / ".local/vad-comparison/provision"
    metadata = manifest["metadata"]
    models = json.loads((folder / "models-manifest.json").read_text(encoding="utf-8-sig"))
    packages = json.loads((folder / "packages-manifest.json").read_text(encoding="utf-8-sig"))
    model = next((row for row in models if row["id"] == manifest["vad_id"]), None)
    checked = pins = cache_artifacts = 0
    if model is None:
        issues.append("vad_provisioned_model_identity_missing")
    else:
        if metadata.get("model_revision") != model["revision"]:
            issues.append("vad_provisioned_model_revision_mismatch")
        hashes = metadata.get("model_files_sha256", {})
        if not hashes:
            issues.append("vad_model_hashes_missing")
        model_path = resolve(metadata["model_path"])
        base = model_path.parent if model_path.is_file() else model_path
        for name, expected in hashes.items():
            matching = [row for row in model["files"] if row["path"].replace("\\", "/").endswith(name.replace("\\", "/"))]
            if name.startswith(".cache/"):
                cache_artifacts += 1
            elif len(matching) != 1 or matching[0]["sha256"] != expected:
                issues.append("vad_provisioned_asset_hash_mismatch")
            path = base / name
            if not path.is_file() or files.digest(path) != expected:
                issues.append("vad_runtime_asset_hash_mismatch")
            else:
                checked += 1
        if manifest["vad_id"] == "silero":
            packaged = resolve(manifest["executable"]).parents[1] / "Lib/site-packages/silero_vad/data/silero_vad.jit"
            if not packaged.is_file() or files.digest(packaged) != hashes.get("silero_vad.jit"):
                issues.append("silero_packaged_jit_copy_hash_mismatch")
    observed = metadata.get("package_versions", {})
    selected_pins = {}
    for package in packages:
        selected_pins[package["package"]] = package["version"]
        if package["package"] in observed:
            if observed[package["package"]] != package["version"]:
                issues.append("vad_provisioned_package_pin_mismatch")
            else:
                pins += 1
        elif provision_dir is not None:
            issues.append("vad_provisioned_package_pin_not_observed")
    if provision_dir is not None and not selected_pins:
        issues.append("vad_provisioned_package_pins_missing")
    return {"vad_runtime_asset_hashes_checked": checked, "vad_package_pins_checked": pins,
            "vad_download_cache_hashes_checked": cache_artifacts,
            "vad_provision_dir": str(folder.resolve()),
            "vad_provision_manifest_sha256": {name: files.digest(folder / name) for name in (
                "models-manifest.json", "packages-manifest.json")},
            "vad_provisioned_model_identity": {"id": model["id"], "revision": model["revision"]} if model else None,
            "vad_provisioned_package_pins": selected_pins}


def audit_study(path: Path) -> dict:
    files = Files()
    study_hash = files.digest(path)
    study = read(path)
    provision_dirs = study_provision_dirs(study)
    clips = {clip["id"]: clip for clip in study["clips"]}
    issues, rows, input_checks, loaded_results = [], [], 0, {}
    if "source_plan_sha256" in study:
        if files.digest(ROOT / ".local/round2/plan.json") != study["source_plan_sha256"]:
            issues.append("frozen_source_plan_hash_mismatch")
    if len(clips) != 12 or sorted(route["id"] for route in study["routes"]) != sorted(ROUTES):
        issues.append("registry_not_ten_routes_twelve_clips")
    status_counts = Counter()
    for route in study["routes"]:
        slots = {slot["clip_id"]: slot for slot in route["runs"]}
        if set(slots) != set(clips) or len(slots) != len(route["runs"]):
            issues.append("route_slots_not_complete_unique")
        family, vad_id = route["model_metadata"]["family"], route["model_metadata"]["vad"]
        for clip_id, clip in clips.items():
            slot = slots.get(clip_id, {"status": "missing"})
            status_counts[slot["status"]] += 1
            row = {"route_id": route["id"], "clip_id": clip_id, "execution_status": slot["status"],
                   "audit_status": "not_executed", "issues": []}
            rows.append(row)
            if slot["status"] not in ("completed", "partial"):
                continue
            problems = row["issues"]
            try:
                result_path = resolve(slot["result_path"])
                if files.digest(result_path) != slot.get("result_sha256"):
                    problems.append("persisted_result_hash_mismatch")
                document = read(result_path)
                loaded_results[(route["id"], clip_id)] = document
                audio_path = resolve(clip["audio"])
                for key in ("audio", "reference", "source_audio", "source_srt"):
                    target = resolve(clip[key])
                    actual_hash = files.digest(target)
                    if actual_hash != clip[f"{key}_sha256"]:
                        problems.append("frozen_study_input_hash_mismatch")
                    for checkpoint in ("input_checks_before", "input_checks_after"):
                        if checkpoint in study and study[checkpoint].get(str(target)) != actual_hash:
                            problems.append("recorded_study_input_hash_mismatch")
                    input_checks += 1
                with wave.open(str(audio_path), "rb") as wav:
                    if (wav.getnchannels(), wav.getframerate(), wav.getsampwidth()) != (1, 16000, 2):
                        raise ValueError("Unsupported source WAV")
                    pcm = wav.readframes(wav.getnframes())
                if hashlib.sha256(pcm).hexdigest() != clip["pcm_sha256"]:
                    problems.append("clip_pcm_hash_mismatch")
                manifest = None
                if vad_id != "original":
                    manifest_path = resolve(slot["vad_manifest_path"])
                    manifest = read(manifest_path)
                    if files.digest(manifest_path) != slot.get("vad_manifest_sha256"):
                        problems.append("persisted_vad_manifest_hash_mismatch")
                    frozen = result_path.parent / "vad-manifest.json"
                    if files.digest(frozen) != files.digest(manifest_path):
                        problems.append("runner_manifest_snapshot_hash_mismatch")
                    row["vad_sources"] = audit_sources(manifest, manifest_path.parent, files, problems)
                    row.update(audit_vad_assets(manifest, files, problems,
                                               provision_dir=provision_dirs.get(vad_id)))
                    if manifest.get("vad_id") != vad_id or manifest.get("offset_s") != clip["offset"]:
                        problems.append("vad_manifest_route_identity_mismatch")
                    if manifest.get("input", {}).get("pcm_sha256") != clip["pcm_sha256"]:
                        problems.append("vad_manifest_pcm_identity_mismatch")
                row.update(audit_sources(document, result_path.parent, files, problems))
                row.update(audit_runtime(document, slot.get("process", {}).get("command", []), files, problems))
                row.update(audit_crops(document, clip, pcm, manifest, problems))
                if family == "x0":
                    for artifact_key, artifact in (("plan_sha256", "plan.json"), ("asr_stage_sha256", "asr.json")):
                        if document.get(artifact_key) != files.digest(result_path.parent / artifact):
                            problems.append("x0_stage_artifact_hash_mismatch")
                    plan = read(result_path.parent / "plan.json")
                    saved_asr = read(result_path.parent / "asr.json")
                    if plan.get("request_sha256") != files.digest(result_path.parent / "request.json"):
                        problems.append("x0_request_artifact_hash_mismatch")
                    if saved_asr.get("plan_sha256") != files.digest(result_path.parent / "plan.json"):
                        problems.append("x0_asr_plan_artifact_hash_mismatch")
                    if plan.get("source_sha256") != document.get("source_sha256"):
                        problems.append("x0_plan_result_source_identity_mismatch")
                    if document.get("runtime_identity", {}).get("plan") != plan.get("runtime_identity"):
                        problems.append("x0_plan_runtime_identity_mismatch")
                    if document.get("runtime_identity", {}).get("asr") != saved_asr.get("runtime_identity"):
                        problems.append("x0_asr_runtime_identity_mismatch")
                if vad_id == "original":
                    row["original_regression"] = compare_original(document, family, clip_id)
                    if row["original_regression"]["status"] == "changed":
                        problems.append("original_baseline_regression")
                row["audit_status"] = "failed" if problems else "passed"
            except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
                problems.append("audit_artifact_error_"+type(error).__name__)
                row["audit_status"] = "failed"
    checked = sum(row["audit_status"] == "passed" for row in rows)
    failed = sum(row["audit_status"] == "failed" for row in rows)
    not_executed = sum(row["audit_status"] == "not_executed" for row in rows)
    family_models = {}
    for row in rows:
        if row["audit_status"] == "not_executed":
            continue
        document = loaded_results.get((row["route_id"], row["clip_id"]))
        if document is None:
            continue
        family = row["route_id"].split("-", 1)[0]
        identity = document.get("model_files_sha256", {}).get("asr", {})
        if not identity:
            continue
        if family in family_models and family_models[family] != identity:
            row["issues"].append("family_asr_model_identity_not_shared")
            row["audit_status"] = "failed"
        family_models.setdefault(family, identity)
    checked = sum(row["audit_status"] == "passed" for row in rows)
    failed = sum(row["audit_status"] == "failed" for row in rows)
    return {"schema_version": 1, "study_id": study["study_id"], "study_sha256": study_hash,
            "study_changed_during_audit": files.digest(path) != study_hash,
            "status": "failed" if issues or failed else "incomplete" if not_executed else "ok",
            "expected_slot_count": 120, "registry_slot_count": sum(len(route["runs"]) for route in study["routes"]),
            "passed_artifact_slots": checked, "failed_artifact_slots": failed, "not_executed_slots": not_executed,
            "execution_status_counts": dict(status_counts), "input_hash_checks": input_checks,
            "registry_issues": issues, "rows": rows,
            "scope": "Persisted evidence and source crops only; no acoustic-quality certification. Pending, missing, blocked and failed invocations never count as artifact passes. Current source differences are reported separately from frozen snapshot validity."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = audit_study(resolve(args.study))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({key: report[key] for key in ("status", "expected_slot_count", "passed_artifact_slots",
                                                  "failed_artifact_slots", "not_executed_slots")}))
    if report["status"] == "failed":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
