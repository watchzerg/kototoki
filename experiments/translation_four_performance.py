"""Offline, privacy-safe engineering aggregation of immutable four-quant runs.

Usage: python -m experiments.translation_four_performance --freeze freeze.json
       --attempt attempt-dir [--attempt other-dir] --output-dir new-dir
Only the supplied freeze's complete, clean four performance rounds support
comparative speed claims. Other freezes remain visible as engineering evidence.
"""

import argparse
from bisect import bisect_left, bisect_right
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from statistics import median
from typing import Any

from experiments.translation_four_quantization.core import CANDIDATES, is_oom, sha256

BASELINE = CANDIDATES[0]
GPU_FIELDS = ("memory_used_mib", "memory_free_mib", "memory_total_mib",
              "utilization_percent", "power_watts", "temperature_celsius",
              "sm_clock_mhz", "memory_clock_mhz")
MEMORY_FIELDS = ("dedicated_gpu_bytes", "shared_gpu_bytes", "working_set_bytes",
                 "private_commit_bytes", "system_ram_available_bytes",
                 "system_commit_available_bytes")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()] if path.exists() else []


def epoch(value: str | None) -> float | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("UTC timestamp requires an explicit offset")
    return parsed.timestamp()


def utc(value: float | None) -> str | None:
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None


def numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    at = (len(ordered) - 1) * q
    low = int(at)
    return ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (at - low)


def distribution(values: list[float]) -> dict[str, Any]:
    return {"count": len(values), "p50": quantile(values, .5), "p95": quantile(values, .95),
            "p99": quantile(values, .99), "minimum": min(values, default=None),
            "maximum": max(values, default=None)}


def range_median(values: list[float]) -> dict[str, Any]:
    return {"count": len(values), "values": values, "median": median(values) if values else None,
            "minimum": min(values, default=None), "maximum": max(values, default=None)}


def measurement(values: list[Any], scale: float = 1, empty_known: bool = False) -> dict[str, Any]:
    """An observed partial sum is distinct from a completely measured total."""
    known = [value * scale for value in values if numeric(value)]
    observed = sum(known) if known or empty_known else None
    complete = len(known) == len(values) and (bool(values) or empty_known)
    return {"expected_attempts": len(values), "known_attempts": len(known),
            "missing_attempts": len(values)-len(known), "observed_total": observed,
            "total": observed if complete else None,
            "missing_reason": None if complete else "引擎／请求字段缺失，未以 0 填补"}


def sum_window_measurements(windows: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for key in ("retry_seconds", "input_tokens", "output_tokens", "prompt_eval_seconds", "decode_seconds", "request_seconds"):
        parts = [row["measurement_coverage"][key] for row in windows]
        known = sum(part["known_attempts"] for part in parts)
        expected = sum(part["expected_attempts"] for part in parts)
        observed_values = [part["observed_total"] for part in parts if numeric(part["observed_total"])]
        observed = sum(observed_values) if observed_values else None
        complete = bool(parts) and all(part["total"] is not None for part in parts)
        result[key] = {"expected_attempts": expected, "known_attempts": known,
                       "missing_attempts": expected-known, "observed_total": observed,
                       "total": observed if complete else None,
                       "missing_reason": None if complete else "无测量或存在缺失字段；仅 observed_total 汇总已知部分"}
    return result


class Evidence:
    """Hash exactly the files read, including incomplete live snapshots."""

    def __init__(self) -> None:
        self.files: dict[str, str] = {}
        self.snapshot_notes: list[dict[str, Any]] = []

    def json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        content = path.read_bytes()
        self.files[str(path.resolve())] = hashlib.sha256(content).hexdigest()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            self.snapshot_notes.append({"path": str(path.resolve()), "reason": "实时快照中的 JSON 尚未完整落盘，按缺失保留"})
            return {}

    def lines(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        content = path.read_bytes()
        self.files[str(path.resolve())] = hashlib.sha256(content).hexdigest()
        rows = []
        pieces = content.decode("utf-8").splitlines()
        for index, line in enumerate(pieces):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                if index != len(pieces)-1 or content.endswith(b"\n"):
                    raise
                self.snapshot_notes.append({"path": str(path.resolve()), "reason": "实时追加中的最后不完整行未参与汇总"})
        return rows


class ResourceCurve(list):
    """Index UTC observations once for long repeated-block runs."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        super().__init__(sorted(rows, key=lambda row: row["utc_epoch_seconds"] or 0))
        self.times = [row["utc_epoch_seconds"] or 0 for row in self]
        distinct = {}
        for row in self:
            at = row.get("gpu_utc_epoch_seconds")
            if numeric(at) and numeric(row.get("gpu_age_seconds")) and row["gpu_age_seconds"] <= .75:
                distinct.setdefault(at, row)
        self.gpu_times = sorted(distinct)
        self.gpu_rows = [distinct[at] for at in self.gpu_times]


def resource_curve(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Store measurements only; GPU timestamps are distinct from PDH observations."""
    curve = []
    for sample in samples:
        gpu, memory = sample.get("gpu", {}), sample.get("memory", {})
        at = sample.get("utc_epoch_seconds", epoch(sample.get("utc")))
        gpu_at = gpu.get("utc_epoch_seconds", epoch(gpu.get("utc")))
        row = {"utc_epoch_seconds": at, "utc": utc(at), "gpu_utc_epoch_seconds": gpu_at,
               "gpu_utc": utc(gpu_at), "phase": sample.get("phase"),
               "gpu_age_seconds": gpu.get("age_seconds"),
               "gpu_uuid": gpu.get("uuid"), "gpu_name": gpu.get("name"),
               "driver_version": gpu.get("driver_version"),
               "probe_work_seconds": sample.get("probe_work_seconds"),
               "null_reasons": {**gpu.get("null_reasons", {}), **memory.get("null_reasons", {})}}
        row.update({key: gpu.get(key) for key in GPU_FIELDS})
        row.update({key: memory.get(key) for key in MEMORY_FIELDS})
        curve.append(row)
    return ResourceCurve(curve)


def summarize_resources(curve: list[dict[str, Any]]) -> dict[str, Any]:
    fields = {}
    for key in (*GPU_FIELDS, *MEMORY_FIELDS):
        # A stale repeated GPU reading is excluded; missing age is disclosed.
        values = [row[key] for row in curve if numeric(row.get(key)) and
                  (key not in GPU_FIELDS or (numeric(row.get("gpu_age_seconds")) and row["gpu_age_seconds"] <= .75))]
        reasons = sorted({str(row["null_reasons"][key]) for row in curve if key in row.get("null_reasons", {})})
        fields[key] = {**distribution(values), "missing": len(curve) - len(values),
                       "missing_reasons": reasons or ([] if values else ["没有可用的新鲜测量值"])}
    times = [row["utc_epoch_seconds"] for row in curve if numeric(row.get("utc_epoch_seconds"))]
    gpu_times = sorted({row["gpu_utc_epoch_seconds"] for row in curve if numeric(row.get("gpu_utc_epoch_seconds"))})
    return {"sample_count": len(curve), "fields": fields,
            "sample_interval_seconds": distribution([b-a for a, b in zip(times, times[1:])]),
            "gpu_interval_seconds": distribution([b-a for a, b in zip(gpu_times, gpu_times[1:])]),
            "scope": "整卡新鲜采样值，非模型独占或绝对峰值；WDDM PID counters 不证明物理驻留"}


def align_window(row: dict[str, Any], curve: list[dict[str, Any]]) -> dict[str, Any]:
    start, finish = epoch(row.get("started_at_utc")), epoch(row.get("finished_at_utc"))
    if start is None or finish is None:
        return {"sample_count": 0, "reason": "窗口开始／结束 UTC 缺失", "fields": {}}
    # Use receive time for asynchronous GPU values, observation time for PID memory.
    indexed = curve if isinstance(curve, ResourceCurve) else ResourceCurve(curve)
    selected = indexed[bisect_left(indexed.times, start):bisect_right(indexed.times, finish)]
    gpu = indexed.gpu_rows[bisect_left(indexed.gpu_times, start):bisect_right(indexed.gpu_times, finish)]
    fields = {}
    for key in (*GPU_FIELDS, *MEMORY_FIELDS):
        values = [item[key] for item in (gpu if key in GPU_FIELDS else selected) if numeric(item.get(key))]
        fields[key] = distribution(values)
    return {"sample_count": len(selected), "gpu_sample_count": len(gpu), "fields": fields,
            "reason": None if selected else "窗口内无资源采样；不跨窗口借用最近值",
            "scope": "GPU receive UTC 与 PID observation UTC 分别对齐窗口；短于采样间隔的峰值可能遗漏"}


def sanitize_window(row: dict[str, Any], artifact: Path, curve: list[dict[str, Any]]) -> dict[str, Any]:
    attempts = row.get("attempts", [])
    responses = [attempt.get("response") or {} for attempt in attempts]
    timing = [response.get("timings") or {} for response in responses]
    measurements = {
        "retry_seconds": measurement([a.get("elapsed_seconds") for a in attempts[1:]], empty_known=True),
        "input_tokens": measurement([a.get("input_tokens") for a in attempts]),
        "output_tokens": measurement([response.get("tokens_predicted") for response in responses]),
        "prompt_eval_seconds": measurement([t.get("prompt_ms") for t in timing], scale=.001),
        "decode_seconds": measurement([t.get("predicted_ms") for t in timing], scale=.001),
        "request_seconds": measurement([a.get("elapsed_seconds") for a in attempts]),
    }
    translations = row.get("translations", {})
    output_hash = hashlib.sha256(json.dumps(translations, sort_keys=True, ensure_ascii=False,
                                           separators=(",", ":")).encode()).hexdigest()
    return {"window_id": row["window_id"], "status": row.get("status"), "artifact": str(artifact.resolve()),
            "started_at_utc": utc(epoch(row.get("started_at_utc"))),
            "finished_at_utc": utc(epoch(row.get("finished_at_utc"))),
            "persisted_at_utc": utc(epoch(row.get("persisted_at_utc"))),
            "elapsed_seconds": row.get("elapsed_seconds"), "attempt_count": len(attempts),
            "retry_count": max(0, len(attempts)-1),
            **{key: value["total"] for key, value in measurements.items()},
            "measurement_coverage": measurements,
            "engine_request_latency_seconds": [a["elapsed_seconds"] for a in attempts if numeric(a.get("elapsed_seconds"))],
            "response_content_sha256": [hashlib.sha256(response["content"].encode()).hexdigest() for response in responses if isinstance(response.get("content"), str)],
            "oom": is_oom(row), "structured_output_sha256": output_hash if row.get("status") == "delivered" else None,
            "resources": align_window(row, curve)}


def summarize_workload(directory: Path, expected_ids: list[str], scored_ids: int,
                       curve: list[dict[str, Any]], evidence: Evidence) -> dict[str, Any]:
    summary = evidence.json(directory / "workload-summary.json")
    run = evidence.json(directory / "run.json")
    windows = []
    for window_id in expected_ids:
        artifact = directory / f"window-{window_id}.json"
        raw = evidence.json(artifact)
        if raw:
            if raw.get("window_id") != window_id:
                raise ValueError(f"Window identity mismatch: {artifact}")
            windows.append(sanitize_window(raw, artifact, curve))
    successful = sum(row["status"] == "delivered" for row in windows)
    complete = len(windows) == len(expected_ids)
    wall = summary.get("translation_wall_seconds")
    # Do not substitute sum of requests for the durable full-set wall definition.
    valid_wall = numeric(wall) and wall >= 0 and bool(summary.get("terminal_artifacts_observed_at_utc"))
    latencies = [row["elapsed_seconds"] for row in windows if numeric(row.get("elapsed_seconds"))]
    measurement_coverage = sum_window_measurements(windows)
    totals = {key: sum(row[key] for row in windows) for key in ("retry_count", "attempt_count")}
    totals.update({key: value["total"] for key, value in measurement_coverage.items()})
    return {"artifact_dir": str(directory.resolve()), "expected": len(expected_ids), "scored_ids_expected": scored_ids,
            "attempted": len(windows), "success": successful, "failed": len(windows)-successful,
            "not_run": len(expected_ids)-len(windows), "not_run_ids": [key for key in expected_ids if key not in {row["window_id"] for row in windows}],
            "complete": complete, "translation_wall_seconds": wall if valid_wall else None,
            "full_set_wall_seconds": wall if complete and valid_wall else None,
            "timing_reason": None if valid_wall else "缺少完整墙钟或终态落盘时间证据",
            "started_at_utc": summary.get("started_at_utc"),
            "terminal_artifacts_at_utc": summary.get("terminal_artifacts_observed_at_utc"),
            "latency_seconds": distribution(latencies), "totals": totals, "windows": windows,
            "measurement_coverage": measurement_coverage,
            "engine_request_latency_seconds": distribution([value for row in windows for value in row["engine_request_latency_seconds"]]),
            "input_sha256": run.get("input_sha256"),
            "oom": summary.get("oom") is True or any(row["oom"] for row in windows),
            "windows_per_second": len(expected_ids)/wall if complete and valid_wall and wall else None,
            "scored_ids_per_second": scored_ids/wall if complete and valid_wall and wall else None,
            "input_tokens_per_second": totals["input_tokens"]/wall if valid_wall and wall and numeric(totals["input_tokens"]) else None,
            "output_tokens_per_second": totals["output_tokens"]/wall if valid_wall and wall and numeric(totals["output_tokens"]) else None}


def stress_summary(workloads: list[dict[str, Any]], ledger: list[dict[str, Any]],
                   curve: list[dict[str, Any]]) -> dict[str, Any]:
    rows = sorted([row for work in workloads for row in work["windows"]],
                  key=lambda row: row.get("started_at_utc") or "")
    phase = next((row for row in reversed(ledger) if row.get("label") == "repeated-source-block" and row.get("status") == "phase_finished"), {})
    duration = phase.get("elapsed_seconds")
    requested = phase.get("requested_seconds")
    timed_rows = [row for row in rows if row.get("started_at_utc") and row.get("finished_at_utc")]
    start = epoch(timed_rows[0].get("started_at_utc")) if timed_rows else None
    end = epoch(timed_rows[-1].get("finished_at_utc")) if timed_rows else None
    span = end-start if start is not None and end is not None else None
    periods = {}
    if span is not None and span > 0:
        for name, low, high in (("front", 0, 1/3), ("middle", 1/3, 2/3), ("back", 2/3, 1),
                                ("first_half", 0, .5), ("second_half", .5, 1)):
            subset = [row for row in timed_rows if low*span <= (epoch(row["started_at_utc"])-start) and
                      ((epoch(row["started_at_utc"])-start) < high*span or high == 1)]
            resource = [item for item in curve if start+low*span <= (item["utc_epoch_seconds"] or 0) <= start+high*span]
            periods[name] = {"windows": len(subset), "input_ids": sorted({row["window_id"] for row in subset}),
                             "latency_seconds": distribution([row["elapsed_seconds"] for row in subset if numeric(row.get("elapsed_seconds"))]),
                             "input_tokens": distribution([row["input_tokens"] for row in subset if numeric(row.get("input_tokens"))]),
                             "output_tokens": distribution([row["output_tokens"] for row in subset if numeric(row.get("output_tokens"))]),
                             "input_tokens_missing_windows": sum(not numeric(row.get("input_tokens")) for row in subset),
                             "output_tokens_missing_windows": sum(not numeric(row.get("output_tokens")) for row in subset),
                             "resources": summarize_resources(resource)}
    first, second = periods.get("first_half", {}), periods.get("second_half", {})
    ratio = None
    same_ids = bool(first and second and first["input_ids"] == second["input_ids"])
    if same_ids and first["latency_seconds"]["p50"]:
        ratio = second["latency_seconds"]["p50"]/first["latency_seconds"]["p50"]
    return {"requested_seconds": requested, "actual_phase_seconds": duration, "window_utc_span_seconds": span,
            "at_least_1800_seconds": bool(rows) and numeric(duration) and duration >= 1800 and requested == 1800,
            "phase_finished": bool(phase), "repeated_blocks": len(workloads), "actual_window_requests": len(rows),
            "windows_missing_utc": len(rows)-len(timed_rows),
            "actual_engine_request_attempts": sum(row["attempt_count"] for row in rows),
            "success": sum(row["status"] == "delivered" for row in rows),
            "failed": sum(row["status"] != "delivered" for row in rows),
            "unique_input_ids": sorted({row["window_id"] for row in rows}), "quality_samples": 0,
            "periods": periods, "identical_input_ids_both_halves": same_ids,
            "second_half_first_half_median_latency_ratio": ratio,
            "caveat": "重复固定输入不新增质量样本；相同 ID 仍须结合输入／输出 token 长度、温度／时钟解释延迟比"}


def collect_attempts(paths: list[Path], evidence: Evidence) -> list[tuple[Path, dict[str, Any], list[dict[str, Any]]]]:
    collected = []
    visited, active = set(), set()

    def visit(path: Path) -> None:
        path = path.resolve()
        if path in active:
            raise ValueError("Cyclic immutable attempt history")
        if path in visited:
            return
        active.add(path)
        attempt = evidence.json(path / "attempt.json")
        if not attempt:
            raise ValueError(f"Missing attempt identity: {path}")
        declared = Path(attempt["freeze"])
        evidence.json(declared)
        if sha256(declared) != attempt["freeze_sha256"]:
            raise ValueError(f"Attempt freeze hash changed: {path}")
        for parent in attempt.get("history", []):
            visit(Path(parent))
        ledger = evidence.lines(path / "schedule-ledger.jsonl")
        for event in ledger:
            for name, digest in event.get("artifact_sha256", {}).items():
                artifact = Path(name)
                if sha256(artifact) != digest:
                    raise ValueError(f"Immutable artifact changed: {artifact}")
        collected.append((path, attempt, ledger))
        active.remove(path)
        visited.add(path)

    for path in paths:
        visit(path)
    return sorted(collected, key=lambda item: epoch(item[1].get("created_at_utc")) or float("inf"))


def loader_buffers(path: Path, evidence: Evidence) -> dict[str, Any]:
    if not path.exists():
        return {"buffers_mib": {}, "reason": "loader log 不可用"}
    content = path.read_bytes()
    evidence.files[str(path.resolve())] = hashlib.sha256(content).hexdigest()
    buffers = {}
    for backend, kind, value in re.findall(r"\b(CUDA\d+|CUDA_Host|CPU_Mapped|CPU)\s+(model|KV|compute|output) buffer size\s*=\s*([\d.]+) MiB", content.decode("utf-8", errors="replace")):
        buffers.setdefault(backend, {})[kind] = float(value)
    return {"buffers_mib": buffers, "reason": None if buffers else "未匹配 loader buffer 记录", "scope": "loader allocation／mapping，非物理驻留"}


def aggregate(freeze: Path, attempts: list[Path]) -> dict[str, Any]:
    """Read-only aggregation; retain every attempt, never choose by speed."""
    evidence = Evidence()
    implementation_hash = sha256(Path(__file__))
    formal = evidence.json(freeze)
    formal_hash = sha256(freeze)
    candidates = formal.get("candidate_ids", list(CANDIDATES))
    runs, curves = [], []
    histories = collect_attempts(attempts, evidence)
    for directory, attempt, events in histories:
        local_freeze = evidence.json(Path(attempt["freeze"]))
        schedule = {task["id"]: task for task in local_freeze.get("schedule", [])}
        # A live started-only task is retained as interrupted/in_progress evidence.
        task_events: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            task_events.setdefault(event["task_id"], []).append(event)
        for task_id, task_history in task_events.items():
            terminal = [event for event in task_history if event.get("status") not in ("started", "retained")]
            event = terminal[-1] if terminal else task_history[-1]
            if event.get("status") == "retained":
                runs.append({"attempt": str(directory), "task_id": task_id, "status": "retained", "workloads": {}, "candidate": event["candidate"], "stage": event["stage"]})
                continue
            task = schedule.get(task_id, {})
            artifact = Path(event.get("artifact_dir", directory / task_id))
            runtime_dir = artifact / "session" / "runtime"
            runtime = evidence.json(runtime_dir / "runtime-final.json")
            monitor = evidence.json(runtime_dir / "resource-summary.json") or runtime.get("resource_summary", {})
            curve = resource_curve(evidence.lines(runtime_dir / "resource-samples.jsonl"))
            curve_id = f"{len(curves):04d}"
            curves.append({"curve_id": curve_id, "attempt": str(directory), "task_id": task_id,
                           "candidate": event["candidate"], "samples": curve})
            translation = artifact / "session" / "translation"
            worker_ledger = evidence.lines(translation / "workload-ledger.jsonl")
            workloads = {}
            for label in ("warmup", "smoke", "dev", "regression", "expanded", "near-budget-probe", "repeated-source-block"):
                targets = sorted((translation / label).glob("run-*"))
                if not targets and label in ("regression", "expanded") and task.get("stage") == "performance":
                    targets = [translation / label / "run-00001"]
                items = []
                for target in targets:
                    record = local_freeze.get("inputs", {}).get(label, {})
                    ids = record.get("window_ids")
                    if ids is None:
                        inputs = evidence.lines(target / "inputs.jsonl")
                        ids = [row["id"] for row in inputs]
                        scored = sum(len(row["translate_ids"]) for row in inputs)
                    else:
                        scored = record.get("scored_ids", 0)
                    items.append(summarize_workload(target, ids, scored, curve, evidence))
                if items:
                    workloads[label] = items
            timing = event.get("session_timing", {})
            runs.append({"attempt": str(directory), "task_id": task_id, "candidate": event["candidate"],
                         "stage": event["stage"], "round": task.get("round"),
                         "status": event.get("status"), "exit_code": event.get("exit_code"),
                         "formal_freeze_match": attempt["freeze_sha256"] == formal_hash,
                         "freeze_sha256": attempt["freeze_sha256"], "capacity_failed": event.get("capacity_failed", False),
                         "contaminated": event.get("pollution", {}).get("contaminated", False) or event.get("status") == "contaminated",
                         "pollution_reasons": event.get("pollution", {}).get("reasons", []),
                         "idle_baseline": event.get("pollution", {}).get("idle_baseline"),
                         "oom": event.get("oom", False) or is_oom(runtime) or any(work["oom"] for values in workloads.values() for work in values),
                         "cold_load_seconds": timing.get("cold_load_seconds", runtime.get("cold_load_seconds")),
                         "warmup_seconds": timing.get("warmup_seconds"),
                         "end_to_end_seconds": timing.get("end_to_end_load_to_terminal_seconds"),
                         "server_process_exited": runtime.get("server_process_exited"),
                         "loader_residency": runtime.get("residency", {}),
                         "loader_buffers": loader_buffers(runtime_dir / "server.log", evidence),
                         "loader_caveat": "loader 全层 offload 与 CPU_Mapped buffer 均不证明物理显存／CPU 驻留，不能排除 WDDM 迁移",
                         "sampling": {key: monitor.get(key) for key in ("requested_interval_seconds", "sample_intervals", "gpu_stream_intervals", "sampling_work", "host", "limitations")},
                         "resources": summarize_resources(curve), "curve_id": curve_id, "workloads": workloads,
                         "stress": stress_summary(workloads.get("repeated-source-block", []), worker_ledger, curve) if event["stage"] == "stability" else None})
            if runs[-1]["stress"] is not None:
                stress = runs[-1]["stress"]
                stress["stability_passed"] = bool(stress["at_least_1800_seconds"] and not stress["failed"] and
                                                   event.get("status") == "completed" and not runs[-1]["contaminated"] and not runs[-1]["oom"])
    comparisons = {}
    for split in ("regression", "expanded"):
        expected = formal.get("inputs", {}).get(split, {})
        ids = expected.get("window_ids", [])
        table = {}
        for candidate in candidates:
            formal_runs = [run for run in runs if run.get("formal_freeze_match") and run["stage"] == "performance" and run["candidate"] == candidate]
            # First complete clean attempt per predeclared round; retain all other attempts above.
            accepted = {}
            for run in formal_runs:
                work = run["workloads"].get(split, [{}])[0]
                if run["status"] == "completed" and not run["contaminated"] and not run["oom"] and not run.get("capacity_failed") and work.get("complete") and not work.get("failed") and work.get("full_set_wall_seconds") is not None and work.get("input_sha256") == expected.get("sha256"):
                    accepted.setdefault(run["round"], (run, work))
            qualified = all(number in accepted for number in (1, 2, 3, 4)) and bool(ids)
            selected = [accepted[number] for number in (1, 2, 3, 4) if number in accepted]
            walls = [work["full_set_wall_seconds"] for _, work in selected]
            all_latencies = [row["elapsed_seconds"] for _, work in selected for row in work["windows"] if numeric(row.get("elapsed_seconds"))]
            hashes = {}
            for key in ids:
                values = [next((row["structured_output_sha256"] for row in work["windows"] if row["window_id"] == key), None) for _, work in selected]
                byte_values = [next((row["response_content_sha256"][-1] if row["response_content_sha256"] else None for row in work["windows"] if row["window_id"] == key), None) for _, work in selected]
                hashes[key] = {"hashes": values, "four_rounds_observed": len(values) == 4 and all(values),
                               "identical": len(values) == 4 and all(values) and len(set(values)) == 1,
                               "response_content_hashes": byte_values,
                               "byte_identical": len(set(byte_values)) == 1 if len(byte_values) == 4 and all(byte_values) else None}
            paired = []
            for run, work in selected:
                base_run = next((item for item in runs if item.get("formal_freeze_match") and item.get("round") == run["round"] and item["candidate"] == BASELINE and item["stage"] == "performance" and item["status"] == "completed" and not item.get("contaminated") and not item.get("oom") and item["workloads"].get(split, [{}])[0].get("complete") and not item["workloads"].get(split, [{}])[0].get("failed") and item["workloads"].get(split, [{}])[0].get("input_sha256") == expected.get("sha256")), None)
                if base_run:
                    base_work = base_run["workloads"][split][0]
                    base_rows = {row["window_id"]: row for row in base_work["windows"]}
                    for row in work["windows"]:
                        base = base_rows.get(row["window_id"], {})
                        if numeric(row.get("elapsed_seconds")) and base.get("elapsed_seconds"):
                            paired.append({"round": run["round"], "window_id": row["window_id"],
                                           "latency_ratio": row["elapsed_seconds"]/base["elapsed_seconds"],
                                           "candidate_input_tokens": row["input_tokens"], "baseline_input_tokens": base["input_tokens"],
                                           "candidate_output_tokens": row["output_tokens"], "baseline_output_tokens": base["output_tokens"]})
            # First durable round-1 result, including failures, remains the quality source.
            first_quality = {}
            for run in formal_runs:
                if run.get("round") == 1:
                    for work in run["workloads"].get(split, []):
                        for row in work["windows"]:
                            first_quality.setdefault(row["window_id"], {"artifact": row["artifact"], "status": row["status"], "structured_output_sha256": row["structured_output_sha256"]})
            table[candidate] = {"expected_windows_per_round": len(ids), "scored_ids_per_round": expected.get("scored_ids"),
                                "complete_clean_rounds": sorted(accepted), "comparative_speed_eligible": qualified,
                                "full_set_wall_seconds": range_median(walls), "comparative_median_seconds": median(walls) if qualified else None,
                                "all_request_latency_seconds": distribution(all_latencies),
                                "all_request_costs": sum_window_measurements([row for _, work in selected for row in work["windows"]]),
                                "all_engine_request_latency_seconds": distribution([value for _, work in selected for row in work["windows"] for value in row["engine_request_latency_seconds"]]),
                                "session_costs": {key: range_median([run[key] for run, _ in selected if numeric(run.get(key))]) for key in ("cold_load_seconds", "warmup_seconds", "end_to_end_seconds")},
                                "rounds": [{"round": run["round"], "attempt": run["attempt"], "session_costs": {key: run.get(key) for key in ("cold_load_seconds", "warmup_seconds", "end_to_end_seconds")}, "workload": {key: value for key, value in work.items() if key != "windows"}} for run, work in selected],
                                "relative_to_baseline": None, "paired_window_latency": paired,
                                "paired_ratio_distribution": distribution([row["latency_ratio"] for row in paired]),
                                "determinism": {"expected": len(ids), "four_round_covered": sum(bool(item["four_rounds_observed"]) for item in hashes.values()),
                                                "identical": sum(bool(item["identical"]) for item in hashes.values()),
                                                "different_ids": [key for key, item in hashes.items() if item["four_rounds_observed"] and not item["identical"]], "windows": hashes},
                                "first_quality_artifacts": first_quality,
                                "first_quality_not_run_ids": [key for key in ids if key not in first_quality]}
        base_median = table.get(BASELINE, {}).get("comparative_median_seconds")
        for candidate, item in table.items():
            value = item["comparative_median_seconds"]
            if value is not None and base_median:
                item["relative_to_baseline"] = {"ratio": value/base_median, "delta_seconds": value-base_median,
                                                 "delta_percent": (value/base_median-1)*100}
        comparisons[split] = table
    schedule_coverage = []
    for task in formal.get("schedule", []):
        observations = [run for run in runs if run.get("formal_freeze_match") and run["task_id"] == task["id"]]
        schedule_coverage.append({"task_id": task["id"], "candidate": task["candidate"], "stage": task["stage"],
                                  "round": task.get("round"), "observed_attempts": [{"attempt": run["attempt"], "status": run["status"]} for run in observations],
                                  "status": observations[-1]["status"] if observations else "not_run",
                                  "reason": None if observations else "无该冻结任务的运行证据；未执行不伪造成翻译失败"})
    source_hashes = {str(Path(__file__).resolve()): implementation_hash}
    test_source = Path(__file__).resolve().parent.parent / "tests" / "test_translation_four_performance.py"
    if test_source.exists():
        source_hashes[str(test_source)] = sha256(test_source)
    return {"schema": "hy30-four-performance-v1", "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "formal_freeze_sha256": formal_hash, "candidate_ids": candidates,
            "comparisons": comparisons, "runs": runs, "schedule_coverage": schedule_coverage, "resource_curves": curves,
            "provenance": {"files_sha256": evidence.files, "aggregator_sha256": implementation_hash, "source_sha256": source_hashes,
                           "snapshot_notes": evidence.snapshot_notes,
                           "config": {"formal_freeze": str(freeze.resolve()), "attempts": [str(path.resolve()) for path in attempts],
                                      "required_clean_rounds": [1, 2, 3, 4], "fresh_gpu_age_limit_seconds": .75}},
            "limitations_zh": ["首轮质量产物不被后轮替换；预检与压力重复不进入新增质量分母。",
                               "容量失败、污染、不完整与未执行记录全部保留；不足四轮不宣称更快。",
                               "仅明确引擎／错误证据认定 OOM；慢或共享内存增长仅是相关线索。",
                               "不同输出长度、量化内核、后台负载和热降频均可能影响延迟。"]}


def engineering_report(report: dict[str, Any]) -> str:
    lines = ["# 四量化工程与性能证据汇总", "", "本报告由离线聚合器生成；完整数值、逐窗与全部运行记录见 performance.json。", ""]
    for split, table in report["comparisons"].items():
        lines += [f"## {'旧回归集' if split == 'regression' else '新增主集'}", "", "| 候选 | 预期窗口／轮 | 完整干净轮次 | 可比较中位秒 | 范围秒 | 相对基线 |", "| --- | ---: | --- | ---: | --- | --- |"]
        for candidate, item in table.items():
            wall, relative = item["full_set_wall_seconds"], item["relative_to_baseline"]
            lines.append(f"| {candidate} | {item['expected_windows_per_round']} | {item['complete_clean_rounds']} | {item['comparative_median_seconds']} | {wall['minimum']}–{wall['maximum']} | {relative or '证据不足'} |")
        lines += [""]
    lines += ["## 全部工程运行", "", "| 候选／任务 | 状态 | OOM | 采样整卡峰值 MiB | 最低空闲 MiB | 冷加载／预热／端到端秒 | 达到 30 分钟 | 稳定性通过 |", "| --- | --- | --- | ---: | ---: | --- | --- | --- |"]
    for run in report["runs"]:
        fields = run.get("resources", {}).get("fields", {})
        peak = fields.get("memory_used_mib", {}).get("maximum")
        free = fields.get("memory_free_mib", {}).get("minimum")
        lines.append(f"| {run['task_id']} | {run['status']} | {run.get('oom')} | {peak} | {free} | {run.get('cold_load_seconds')} / {run.get('warmup_seconds')} / {run.get('end_to_end_seconds')} | {(run.get('stress') or {}).get('at_least_1800_seconds')} | {(run.get('stress') or {}).get('stability_passed')} |")
    lines += ["", "## 判定边界", ""] + [f"- {item}" for item in report["limitations_zh"]]
    lines += ["- 缺失的 token 与引擎计时字段保留 null；measurement_coverage 分别报告已知／缺失尝试数及已观测部分总和，不能将部分总和当完整成本。", "- 达到 30 分钟只表明时长门槛；稳定性通过还要求完成、无失败、无污染且无明确 OOM。", "- 49/49 loader offload 不证明所有权重始终物理驻留；CPU_Mapped 数字不等于 CPU 实际驻留。", "- resource-curves.csv 与 window-alignment.csv 使用 UTC；GPU 接收时间与进程内存观察时间分别对齐，未采样字段保持空值。", "- 稳定性固定输入块的前／中／后段、后半／前半延迟与 token 长度分布见 JSON；重复次数不算独立质量样本。", ""]
    return "\n".join(lines)


def write_report(report: dict[str, Any], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    for name, data in (("performance.json", report), ("source-config-snapshot.json", report["provenance"])):
        with (output/name).open("x", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    (output/"engineering-report.md").write_text(engineering_report(report), encoding="utf-8")
    curve_columns = ["curve_id", "candidate", "task_id", "utc", "utc_epoch_seconds", "gpu_utc", "gpu_utc_epoch_seconds", "phase", "gpu_age_seconds", *GPU_FIELDS, *MEMORY_FIELDS, "null_reasons"]
    with (output/"resource-curves.csv").open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=curve_columns, extrasaction="ignore")
        writer.writeheader()
        for curve in report["resource_curves"]:
            for row in curve["samples"]:
                writer.writerow({**row, **{key: curve[key] for key in ("curve_id", "candidate", "task_id")},
                                 "null_reasons": json.dumps(row["null_reasons"], ensure_ascii=False)})
    window_columns = ["candidate", "task_id", "attempt", "round", "split", "iteration", "window_id", "status", "started_at_utc", "finished_at_utc", "elapsed_seconds", "input_tokens", "output_tokens", "prompt_eval_seconds", "decode_seconds", "request_seconds", "retry_count", "retry_seconds", "measurement_coverage", "oom", "sample_count", "gpu_sample_count"]
    window_columns += [f"{key}_{bound}" for key in (*GPU_FIELDS, *MEMORY_FIELDS) for bound in ("minimum", "maximum", "p50")]
    with (output/"window-alignment.csv").open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=window_columns, extrasaction="ignore")
        writer.writeheader()
        for run in report["runs"]:
            for split, workloads in run["workloads"].items():
                for iteration, work in enumerate(workloads, 1):
                    for row in work["windows"]:
                        aligned = row["resources"]
                        flattened = {f"{key}_{bound}": value[bound] for key, value in aligned["fields"].items() for bound in ("minimum", "maximum", "p50")}
                        writer.writerow({**row, **{key: run.get(key) for key in ("candidate", "task_id", "attempt", "round")}, "split": split, "iteration": iteration,
                                         "measurement_coverage": json.dumps(row["measurement_coverage"], ensure_ascii=False),
                                         "sample_count": aligned["sample_count"], "gpu_sample_count": aligned.get("gpu_sample_count"), **flattened})


def main() -> int:
    parser = argparse.ArgumentParser(description="离线汇总四量化耗时、资源曲线与稳定性；不启动模型或裁判")
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--attempt", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    write_report(aggregate(args.freeze, args.attempt), args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
