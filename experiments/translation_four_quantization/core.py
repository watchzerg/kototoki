"""Pure schedule, source firewall, and immutable recovery contracts."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
from statistics import median
from typing import Any

from experiments.translation_demo.run import read_inputs

SEED = 20261006
CANDIDATES = (
    "hy-mt2-30b-a3b-q3-k-m",
    "hy-mt2-30b-a3b-i1-q3-k-m",
    "hy-mt2-30b-a3b-apex-i-compact",
    "hy-mt2-30b-a3b-i1-q3-k-l",
)
RECIPE = {"temperature": 0, "seed": SEED, "n_predict": 1024,
          "context_size": 4096, "batch": 256, "ubatch": 128,
          "gpu_layers": 99, "flash_attention": "on", "fit": "off",
          "parallel": 1, "max_attempts": 2, "cpu_offload_allowed": False}
RECIPE.update(threads=8, threads_batch=8, cache_type_k="f16", cache_type_v="f16", cache_ram_mib=8192)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, data: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def append_event(path: Path, event: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps({"at_utc": utc_now(), **event}, ensure_ascii=False) + "\n")
        stream.flush()


def input_record(path: Path, expected: int | None = None) -> dict[str, Any]:
    rows = read_inputs(path)  # Exact allowed fields, no references or judge feedback.
    if expected is not None and len(rows) != expected:
        raise ValueError(f"{path}: expected {expected} windows, found {len(rows)}")
    return {"path": str(path.resolve()), "sha256": sha256(path),
            "window_ids": [row["id"] for row in rows], "windows": len(rows),
            "scored_ids": sum(len(row["translate_ids"]) for row in rows)}


def validate_expanded_corpus(path: Path, inputs: dict[str, Any]) -> dict[str, Any]:
    """Formal inference requires published double-reviewed references, never staging."""
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("state") != "frozen_double_fresh_reference_review" or manifest.get("inference_allowed") is not True:
        raise ValueError("Expanded corpus is not finalized for formal inference")
    root = path.resolve().parent
    records = {}
    for entry in manifest["files"]:
        target = (root / entry["path"]).resolve()
        if not target.is_relative_to(root):
            raise ValueError("Corpus manifest path escapes its root")
        if entry["path"] in records or sha256(target) != entry["sha256"]:
            raise ValueError("Corpus freeze file identity mismatch or duplicate")
        records[entry["path"]] = {"path": str(target), "sha256": entry["sha256"]}
    required = ("model-input/expanded.jsonl", "reference/expanded.jsonl", "source-manifest.json", "audit/forbidden-event-keys.json")
    if any(name not in records for name in required):
        raise ValueError("Corpus freeze lacks formal inputs, references, or event audit")
    if records[required[0]]["sha256"] != inputs["sha256"] or manifest.get("windows") != inputs["windows"]:
        raise ValueError("Expanded source inputs differ from reviewed corpus freeze")
    references = [json.loads(line) for line in Path(records[required[1]]["path"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    if [row["id"] for row in references] != inputs["window_ids"] or any(row.get("review_status") != "double_fresh_reviewed_scored_ids" for row in references):
        raise ValueError("Expanded reference identities or double-review statuses differ")
    from experiments.translation_corpus.prepare import audit_overlap, validate_execution
    source = json.loads(Path(records[required[2]]["path"]).read_text(encoding="utf-8"))
    if [row["id"] for row in source["windows"]] != inputs["window_ids"]:
        raise ValueError("Expanded source manifest identities differ")
    forbidden = set(json.loads(Path(records[required[3]]["path"]).read_text(encoding="utf-8")))
    overlap = audit_overlap(source["windows"], forbidden)
    for row in references:
        for phase in ("primary", "review"):
            validate_execution(root, phase, row["id"])
        if (root / "reviews" / "adjudication" / f"{row['id']}.json").exists():
            validate_execution(root, "adjudication", row["id"])
            phase = "adjudication"
        else:
            phase = "primary"
        decision = json.loads((root / "reviews" / phase / f"{row['id']}.json").read_text(encoding="utf-8"))
        if any(unit.get("zh") != decision["translations"].get(unit["id"]) for unit in row["units"] if unit["score"]):
            raise ValueError("Published reference differs from supported reviewed decision")
    return {"path": str(path.resolve()), "sha256": sha256(path), "files": records,
            "windows": inputs["windows"], "source_overlap_audit": overlap,
            "gate": "all finalized double fresh Sol/high execution provenance verified before formal inference"}


def rotation(seed: int = SEED) -> list[list[str]]:
    mapping = list(CANDIDATES)
    random.Random(seed).shuffle(mapping)
    return [mapping[index:] + mapping[:index] for index in range(4)]


def make_schedule(formal: bool = True) -> list[dict[str, Any]]:
    tasks = [{"id": f"preflight-{candidate}", "stage": "preflight", "candidate": candidate,
              "quality_round": False} for candidate in CANDIDATES]
    if formal:
        for number, candidates in enumerate(rotation(), 1):
            tasks.extend({"id": f"round-{number}-{candidate}", "stage": "performance",
                          "candidate": candidate, "round": number,
                          "quality_round": number == 1} for candidate in candidates)
    tasks.extend({"id": f"stability-{candidate}", "stage": "stability", "candidate": candidate,
                  "quality_round": False} for candidate in CANDIDATES)
    return tasks


def inspect_workload(path: Path, expected_ids: list[str]) -> dict[str, Any]:
    """Use durable window files, never infer failures for an unattempted tail."""
    rows = {}
    for window_id in expected_ids:
        artifact = path / f"window-{window_id}.json"
        if artifact.exists():
            row = json.loads(artifact.read_text(encoding="utf-8"))
            if row.get("window_id") != window_id:
                raise ValueError(f"Artifact window identity mismatch: {artifact}")
            rows[window_id] = row
    success = [key for key, row in rows.items() if row.get("status") == "delivered"]
    failed = [key for key in rows if key not in success]
    absent = [key for key in expected_ids if key not in rows]
    return {"expected": len(expected_ids), "attempted": len(rows), "success": len(success),
            "failed": len(failed), "not_run": len(absent), "not_run_ids": absent,
            "complete": not absent, "rows": rows}


def recovery_subset(inputs: Path, historical: list[Path], output: Path) -> dict[str, Any]:
    """First durable terminal result wins, including failures; only absent IDs rerun."""
    windows = read_inputs(inputs)
    ids = [row["id"] for row in windows]
    retained = {}
    for directory in historical:
        audit = inspect_workload(directory, ids)
        for key in audit["rows"]:
            retained.setdefault(key, str((directory / f"window-{key}.json").resolve()))
    pending = [row for row in windows if row["id"] not in retained]
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        for row in pending:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"retained": retained, "pending_ids": [row["id"] for row in pending],
            "expected_ids": ids, "input_sha256": sha256(inputs),
            "subset_sha256": sha256(output), "history": [str(path.resolve()) for path in historical]}


def is_oom(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get("error_kind") == "oom" or value.get("runtime_error_kind") == "oom" or value.get("oom") is True:
            return True
        return any(is_oom(value[key]) for key in ("error", "reason", "runtime_error", "attempts", "rows") if key in value)
    if isinstance(value, list):
        return any(is_oom(item) for item in value)
    if not isinstance(value, str):
        return False
    text = value.lower()
    return any(marker in text for marker in ("out of memory", "cuda_error_out_of_memory",
                                            "cudamalloc failed", "failed to allocate cuda", "vk_error_out_of_device_memory"))


def pollution_evidence(runtime: Path, common_baseline: dict[str, float] | None) -> dict[str, Any]:
    samples = runtime / "resource-samples.jsonl"
    used, free = [], []
    if samples.exists():
        for line in samples.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            gpu = row.get("gpu", {})
            if row.get("phase") != "idle_baseline" or gpu.get("age_seconds", 999) > .75:
                continue
            if isinstance(gpu.get("memory_used_mib"), (int, float)):
                used.append(gpu["memory_used_mib"])
            if isinstance(gpu.get("memory_free_mib"), (int, float)):
                free.append(gpu["memory_free_mib"])
    baseline = {"memory_used_mib": median(used), "memory_free_mib": median(free)} if used and free else None
    reasons = []
    log = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in runtime.glob("*.log"))
    if any(marker in log.lower() for marker in ("port already occupied", "device has been lost", "device removed", "driver reset", "cuda_error_unknown", "xid error")):
        reasons.append("unauthorized_shared_service_or_driver_reset_error")
    if baseline and common_baseline and any(abs(baseline[key] - common_baseline[key]) > 512 for key in baseline):
        reasons.append("preload_median_memory_difference_over_512_mib")
    return {"contaminated": bool(reasons), "reasons": reasons, "idle_baseline": baseline,
            "comparison_baseline": common_baseline,
            "baseline_reason": None if baseline else "fresh idle memory measurements unavailable",
            "policy": "retain every attempt; flagged performance requires independent rerun index; drift alone is not OOM"}


def release_evidence(runtime: Path) -> dict[str, Any]:
    baseline = pollution_evidence(runtime, None)["idle_baseline"]
    samples = runtime / "resource-samples.jsonl"
    released = []
    if samples.exists():
        for line in samples.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            gpu = row.get("gpu", {})
            if row.get("phase") == "released" and gpu.get("age_seconds", 999) <= .75 and isinstance(gpu.get("memory_used_mib"), (int, float)):
                released.append(gpu["memory_used_mib"])
    value = median(released) if released else None
    return {"idle_used_mib": baseline["memory_used_mib"] if baseline else None,
            "released_used_mib": value,
            "memory_returned": bool(baseline and value is not None and value <= baseline["memory_used_mib"] + 512),
            "scope": "sampled whole-device memory returned within baseline+512MiB; not proof of model-exclusive allocation"}
