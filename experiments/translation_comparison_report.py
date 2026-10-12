"""Deterministic comparison report and execution-evidence inventory; no inference."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import math
from pathlib import Path
import re
from typing import Any

from experiments.translation_eval.runner import aggregate, attempt_count, dump, load_jsonl, read_json


CANDIDATES = {
    "hy-mt2-7b-q8", "hy-mt2-30b-a3b-q3-k-m", "tower-plus-9b-q8",
    "translategemma-12b-q8", "translategemma-27b-q3-k-l",
}
LIMITATIONS = [
    "评分是 Sol/high 自动判断；参考也经同模型复核，复评为同模型独立请求，不是人工准确率或独立模型家族证据。",
    "固定 test 的文本窗口不代表整部作品；未验证音画同步或逐 cue 显示效果。",
    "语义缺分上下界以 0／4 填补完整分母，不是置信区间；自然度单独汇总，不能相加成总分。",
    "TranslateGemma 为原生段落加辅助映射的 assisted 流程；映射的结构核验不能证明语义边界准确，辅助收益与成本不能归为裸模型能力。",
    "显存为 nvidia-smi 采样的整张 GPU memory.used 峰值，包含其他进程；不是模型独占显存，也不是持续监测的绝对峰值。",
    "冷加载是 server 启动到 health 可用的实测时间，不能保证操作系统文件缓存为冷状态。",
    "裁判 attempt 时间含调度、文件操作与观察延迟；并行 attempt 时间之和不等于总墙钟或纯推理时间。",
    "费用、token 使用和实际返回模型版本若接口未暴露，保持 null；未留执行证据的历史调用成本仍未知。",
    "报告不自动宣布优胜者；缺分、复评不稳、小差距与同模型偏差均限制排名解释。",
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measured(value: Any) -> float | None:
    if value is None:
        return None
    if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
        raise ValueError("invalid measured nonnegative number")
    return value


def known_sum(values: list[Any]) -> float | None:
    known = [measured(value) for value in values if value is not None]
    return sum(known) if known else None


def reconcile(evaluation: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    expected = load_jsonl(evaluation / "expected.jsonl")
    final = load_jsonl(evaluation / "final.jsonl")
    fields = ("candidate_alias", "window_id", "work", "category", "scored_ids")
    def scopes(rows: list[dict[str, Any]]) -> dict[tuple[str, str], tuple[Any, ...]]:
        result = {}
        for row in rows:
            key = (row["candidate_alias"], row["window_id"])
            if key in result:
                raise ValueError("duplicate expected/final candidate window")
            result[key] = tuple(tuple(row[name]) if name == "scored_ids" else row[name] for name in fields)
        return result
    if scopes(expected) != scopes(final):
        raise ValueError("expected/final scope mismatch; preserve the complete denominator")
    computed = aggregate(final)
    saved = read_json(evaluation / "summary.json")
    for key, value in computed.items():
        if saved.get(key) != value:
            raise ValueError(f"final/summary mismatch: {key}")
    return saved, final


def runtime_record(directory: Path, root: Path, phase: str | None = None,
                   translation_directory: Path | None = None) -> dict[str, Any]:
    path = directory / "runtime" / "runtime-final.json"
    runtime = read_json(path) if path.exists() else {}
    translation = translation_directory or directory / "translation"
    run_path = translation / "run.json"
    run = read_json(run_path) if run_path.exists() else {}
    completion = translation / "completion.json"
    ledger = translation / "ledger.jsonl"
    rows = load_jsonl(ledger) if ledger.exists() else []
    observed = []
    for name in ("server.log", "stderr.log"):
        log = directory / "runtime" / name
        if log.exists():
            for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
                if re.search(r"offload(?:ed|ing).*GPU|(?:CPU_Mapped|CUDA\d+).*model buffer size", line):
                    observed.append({"file": str(log.relative_to(root)), "line": line})
    phase = phase or ("auxiliary_mapping" if run.get("phase") == "pure-mapping" else "native_generation")
    attempts = [attempt_count(row.get("attempts")) for row in rows]
    timing_field = "auxiliary_seconds" if phase == "auxiliary_mapping" else "generation_seconds"
    times = [row.get(timing_field) for row in rows]
    return {
        "directory": str(directory.relative_to(root)), "phase": phase, "available": bool(runtime),
        "runtime_sha256": sha(path) if path.exists() else None,
        "candidate": run.get("candidate"), "active_model": runtime.get("asset", {}).get("id"),
        "asset": runtime.get("asset"), "engine": {key: runtime.get(key) for key in
            ("engine", "release", "build", "commit", "cuda", "executable_sha256", "custom_runtime_identity")},
        "recipe": run.get("recipe"), "settings": run.get("settings"),
        "cold_load_seconds": measured(runtime.get("cold_load_seconds")),
        "whole_gpu_sampled_peak_mib": measured(runtime.get("peak_device_memory_mib")),
        "total_runtime_seconds": measured(runtime.get("total_runtime_seconds")),
        "exit_code": runtime.get("translation_exit_code"), "runtime_error": runtime.get("runtime_error"),
        "completion": read_json(completion) if completion.exists() else None,
        "ledger_windows": len(rows) if ledger.exists() else None,
        "ledger_status_counts": dict(Counter(row["status"] for row in rows)) if ledger.exists() else None,
        "phase_seconds_measured": known_sum(times), "phase_timing_known_windows": sum(t is not None for t in times),
        "attempts_measured": sum(n for n in attempts if n is not None) if any(n is not None for n in attempts) else None,
        "retries_measured": sum(max(n - 1, 0) for n in attempts if n is not None) if any(n is not None for n in attempts) else None,
        "attempts_known_windows": sum(n is not None for n in attempts), "observed_offload_logs": observed,
        "ledger_sha256": sha(ledger) if ledger.exists() else None,
        "billing_cost": None, "billing_cost_reason": "local execution has no measured monetary cost record",
    }


def manual_stage_inventory(root: Path) -> list[dict[str, Any]]:
    covered = {(path.parent.parent / "translation").resolve() for path in root.rglob("runtime-final.json")}
    manual = []
    for ledger in sorted(root.rglob("ledger.jsonl")):
        parts = ledger.relative_to(root).parts
        directory = ledger.parent
        if (parts[0].startswith("test") or directory.resolve() in covered
                or any(part in {"originals", "packets", "subagent-execution", "judge-execution"} for part in parts)
                or not (directory / "run.json").exists()):
            continue
        run = read_json(directory / "run.json")
        if run.get("phase") not in {"translation", "pure-mapping"} or run.get("candidate") not in CANDIDATES:
            continue
        row = runtime_record(directory, root, translation_directory=directory)
        row["accounting_scope"] = "manual stage ledger; complete runtime, cold load and device sampling unavailable"
        manual.append(row)
    return manual


def judge_inventory(evaluation: Path) -> dict[str, Any]:
    # Invocation files identify individual attempts, including failed validations.
    # Summary totals and per-attempt totals must never be added together.
    attempts, prepared = [], []
    for path in sorted(evaluation.glob("subagent-execution/**/invocation.json")):
        value = read_json(path)
        if value.get("dispatch_status") == "interrupted_before_spawn" and not value.get("agent_id"):
            prepared.append({"path": str(path.relative_to(evaluation)), "sha256": sha(path),
                "status": "prepared_not_dispatched", "dispatch_status": value["dispatch_status"],
                "agent_id": None, "elapsed_seconds": None,
                "reason": "dispatch preparation cancelled before any worker was spawned"})
            continue
        validation_path = path.parent / "validation.json"
        validation = read_json(validation_path) if validation_path.exists() else {}
        attempts.append({"path": str(path.relative_to(evaluation)), "sha256": sha(path),
            "elapsed_seconds": measured(value.get("elapsed_seconds")),
            "status": validation.get("status"), "error": validation.get("error"),
            "requested_model": value.get("requested_model"), "requested_effort": value.get("requested_effort"),
            "returned_model": value.get("returned_model"), "returned_effort": value.get("returned_effort"),
            "returned_version": value.get("returned_version"), "agent_id": value.get("agent_id"),
            "timing_scope": value.get("timing_scope")})
    for path in sorted(evaluation.glob("judge-execution/**/attempt.json")):
        value = read_json(path)
        attempts.append({"path": str(path.relative_to(evaluation)), "sha256": sha(path),
            "elapsed_seconds": measured(value.get("elapsed_seconds")),
            "status": "judge_failed" if value.get("status") == "failed" else value.get("status"),
            "error": value.get("error"), "returned_model": value.get("returned_models"),
            "returned_effort": value.get("returned_efforts"), "returned_version": None,
            "timing_scope": "CLI attempt wall time"})
    for path in sorted(evaluation.glob("subagent-execution/**/validation.json")):
        if not (path.parent / "invocation.json").exists():
            value = read_json(path)
            attempts.append({"path": str(path.relative_to(evaluation)), "sha256": sha(path),
                "elapsed_seconds": measured(value.get("elapsed_seconds")), "status": value.get("status"),
                "error": value.get("error"), "returned_version": None,
                "timing_scope": "validation record without invocation metadata"})
    summaries = []
    # Two coordinator summaries in one directory can describe the same invocations.
    preferred = next((evaluation / name for name in ("judge-execution-summary.json", "execution-summary.json")
                      if (evaluation / name).exists()), None)
    paths = ([preferred] if preferred else []) + sorted(evaluation.glob("judge-execution/*-summary.json"))
    for path in paths:
        value = read_json(path)
        summaries.append({"path": str(path.relative_to(evaluation)), "sha256": sha(path), "value": value})
    if attempts or prepared:
        seconds = known_sum([item["elapsed_seconds"] for item in attempts])
        source = "unique invocation/CLI attempt files; coordinator totals excluded"
        count = len(attempts)
        failed = sum(item["status"] == "judge_failed" for item in attempts)
    else:
        seconds = known_sum([next((item["value"][key] for key in
            ("total_attempt_seconds", "total_attempt_wall_seconds", "all_attempt_seconds") if key in item["value"]), None)
            for item in summaries])
        source = "execution summaries only; no per-attempt invocation inventory available"
        counts = [item["value"].get("attempt_count", item["value"].get("total_jobs")) for item in summaries]
        count = sum(counts) if counts and all(n is not None for n in counts) else None
        failures = [item["value"].get("judge_failed") for item in summaries]
        failed = sum(failures) if failures and all(n is not None for n in failures) else None
    return {"attempts": attempts, "execution_summaries": summaries, "attempt_count": count,
        "prepared_not_dispatched": prepared, "prepared_not_dispatched_count": len(prepared),
        "known_failed_attempts": failed, "all_known_attempt_seconds": seconds, "accounting_source": source,
        "attempt_status_counts": dict(Counter(item["status"] or "unknown" for item in attempts)),
        "timing_known_attempts": sum(item["elapsed_seconds"] is not None for item in attempts) if attempts else None,
        "billing_cost": None, "returned_model_version": None,
        "unknown_reason": "unrecorded invocations, absent timings, billing and actual model-version identity are not inferred"}


def build_metrics(evaluation: Path, root: Path, alias_path: Path) -> dict[str, Any]:
    summary, final = reconcile(evaluation)
    aliases = read_json(alias_path)
    if set(aliases.values()) != CANDIDATES or len(aliases) != 5 or set(aliases) != set(summary["candidates"]):
        raise ValueError("comparison requires the exact five candidate identities and matching aliases")
    formal = []
    for candidate in sorted(CANDIDATES):
        formal.append(runtime_record(root / "test-v1" / candidate, root, "native_generation"))
        if candidate.startswith("translategemma"):
            formal.append(runtime_record(root / "test-map-v1" / candidate, root, "auxiliary_mapping"))
    historical = [runtime_record(path.parent.parent, root) for path in sorted(root.rglob("runtime-final.json"))
                  if not path.relative_to(root).parts[0].startswith("test")]
    manual = manual_stage_inventory(root)
    log_pointers = [str(path.relative_to(root)) for path in sorted(root.rglob("*.log"))
                    if "runtime" not in path.relative_to(root).parts
                    and not path.relative_to(root).parts[0].startswith("test")
                    and re.search(r"host|server|startup|probe|compat", path.name, re.IGNORECASE)]
    judge_dirs = {path.parent for name in ("judge-execution-summary.json", "execution-summary.json") for path in root.rglob(name)}
    judge_dirs.update(path.parent.parent for path in root.glob("**/judge-execution/*-summary.json"))
    judge_dirs.update(path.parent for path in root.rglob("subagent-execution") if path.is_dir())
    judge_dirs.update(path.parent for path in root.rglob("judge-execution") if path.is_dir())
    history_judges = [{"directory": str(path.relative_to(root)), **judge_inventory(path)}
                      for path in sorted(judge_dirs) if path.resolve() != evaluation.resolve()
                      and not path.relative_to(root).parts[0].startswith("test")]
    counts = Counter(row["candidate_alias"] for row in final)
    first = next(iter(summary["candidates"].values()))
    return {"schema_version": "translation-comparison-report-v1", "candidate_aliases": aliases,
        "evaluation_directory": str(evaluation), "run_root": str(root),
        "evidence_sha256": {name: sha(evaluation / name) for name in ("expected.jsonl", "final.jsonl", "summary.json")},
        "alias_key_sha256": sha(alias_path), "report_helper_sha256": sha(Path(__file__)),
        "denominators": {"candidate_windows": dict(counts), "windows_per_candidate": first["expected_windows"],
            "scored_ids_per_candidate": sum(work["expected_scored_ids"] for work in first["works"].values())},
        "reconciliation": {"expected_final_scopes_match": True, "final_summary_match": True},
        "evaluation_configuration": read_json(evaluation / "run.json") if (evaluation / "run.json").exists() else None,
        "quality": summary, "formal_runtime_records": formal, "formal_judge": judge_inventory(evaluation),
        "development_history": {"runtime_records": historical, "manual_stage_records": manual, "judge_runs": history_judges,
            "known_runtime_seconds": known_sum([row["total_runtime_seconds"] for row in historical]),
            "known_manual_phase_seconds": known_sum([row["phase_seconds_measured"] for row in manual]),
            "unstructured_startup_probe_log_pointers": log_pointers,
            "unstructured_cost_reason": "startup/probe log pointers are evidence locations only; without structured timing no calls, runtime or cost is inferred",
            "known_judge_attempt_seconds": known_sum([row["all_known_attempt_seconds"] for row in history_judges]),
            "uncovered_cost": None, "scope": "known evidence outside formal translation/mapping and the selected evaluation; smoke/dev are not scored again"},
        "limitations": LIMITATIONS}


def display(value: Any) -> str:
    return "未知" if value is None else f"{value:.4f}" if isinstance(value, float) else str(value)


def report(metrics: dict[str, Any]) -> str:
    quality, aliases = metrics["quality"], metrics["candidate_aliases"]
    lines = ["# 五候选字幕翻译比较与执行证据", "",
        f"评估轨：`{quality['lane']}`；规约：`{quality['profile']}`；划分：`{quality['split']}`。",
        f"每候选 {metrics['denominators']['windows_per_candidate']} 窗口／{metrics['denominators']['scored_ids_per_candidate']} 计分 IDs；五候选分母与 final／summary 核对通过。",
        "比较状态：" + ("语义终分覆盖完整。" if quality["comparison_complete"] else "存在语义缺分，比较为暂定。"),
        "不自动宣布优胜者；分数为自动评估结果。完整数值、身份、版本及文件哈希见 metrics.json。", "",
        "## 类别分层结果", "", "先按作品内窗口平均，再对类别内作品等权平均。", "",
        "| 候选 | 类别 | 作品 | 语义覆盖 | 语义下界／上界 | 自然度 | 自然度覆盖 |", "|---|---|---:|---:|---:|---:|---:|"]
    for alias, candidate in quality["candidates"].items():
        for category, value in candidate["categories"].items():
            lines.append(f"| {aliases[alias]} | {category} | {value['works']} | {value['semantic_scored_windows']}/{value['expected_windows']} | {display(value['semantic_lower'])}／{display(value['semantic_upper'])} | {display(value['naturalness_mean'])} | {value['naturalness_scored_windows']}/{value['expected_windows']} |")
    for alias, candidate in quality["candidates"].items():
        lines += ["", f"## {aliases[alias]}", "", f"终态：{candidate['status_counts']}；结构状态：{candidate['structural_status_counts']}；缺失 IDs：{candidate['missing_ids']}。",
            f"复评 {candidate['reviewed_windows']}/{candidate['expected_windows']}；初始分歧 {candidate['initial_disagreement_windows']}；改分 {candidate['score_changed_windows']}。",
            f"已采纳错误数量：{candidate['accepted_error_counts']}；受影响窗口：{candidate['accepted_error_windows']}；已知语义窗口错误率：{candidate['accepted_error_window_rates_known']}；语义缺分 {candidate['semantic_null_windows']}。",
            f"原生生成 {display(candidate['generation_seconds_measured'])} 秒（时间覆盖 {candidate['generation_timing_known_windows']}/{candidate['expected_windows']}），辅助步骤 {display(candidate['auxiliary_seconds_measured'])} 秒（覆盖 {candidate['auxiliary_timing_known_windows']}/{candidate['expected_windows']}）。",
            f"生成重试 {display(candidate['generation_retries_measured'])}，记录覆盖 {candidate['generation_attempts_known_windows']}/{candidate['expected_windows']}；映射重试 {display(candidate['mapping_retries_measured'])}，记录覆盖 {candidate['mapping_attempts_known_windows']}/{candidate['expected_windows']}。", "",
            "| 作品 | 类别 | 窗口／IDs | 语义覆盖 | 语义下界／上界 | 自然度 | 自然度覆盖 |", "|---|---|---:|---:|---:|---:|---:|"]
        for name, value in candidate["works"].items():
            lines.append(f"| {name.replace('|', '／')} | {value['category']} | {value['expected_windows']}/{value['expected_scored_ids']} | {value['semantic_scored_windows']}/{value['expected_windows']} | {display(value['semantic_lower'])}／{display(value['semantic_upper'])} | {display(value['naturalness_mean'])} | {value['naturalness_scored_windows']}/{value['expected_windows']} |")
        omitted = {category: value["naturalness_omitted_works"] for category, value in candidate["categories"].items()}
        lines += ["", f"自然度省略作品：{omitted}。"]
    lines += ["", "## 七次正式本地执行", "", "原生模型与辅助映射分列；阶段耗时包含该阶段全部已记录 attempts，不能与 final 的原生／辅助时间重复相加。", "",
        "| 目录 | 阶段 | 活跃模型 | 冷加载秒 | GPU 采样峰值 MiB | 本次运行秒 | 阶段秒／覆盖 | attempts／重试 | exit |", "|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for row in metrics["formal_runtime_records"]:
        lines.append(f"| {row['directory']} | {row['phase']} | {display(row['active_model'])} | {display(row['cold_load_seconds'])} | {display(row['whole_gpu_sampled_peak_mib'])} | {display(row['total_runtime_seconds'])} | {display(row['phase_seconds_measured'])}／{row['phase_timing_known_windows']} | {display(row['attempts_measured'])}／{display(row['retries_measured'])} | {display(row['exit_code'])} |")
    for row in metrics["formal_runtime_records"]:
        asset = row["asset"] or {}
        lines += ["", f"运行身份 `{row['directory']}`：模型 revision `{display(asset.get('revision'))}`，SHA256 `{display(asset.get('sha256'))}`；引擎 {row['engine']}；配方 `{display(row['recipe'])}`；设置 {row['settings']}。",
            f"设备驻留日志 `{row['directory']}`：", ""] + [f"- `{item['line']}`" for item in row["observed_offload_logs"]]
        if not row["observed_offload_logs"]:
            lines.append("- 无可用 offload／model buffer 日志证据。")
    judge = metrics["formal_judge"]
    lines += ["", "## 裁判执行与开发历史", "",
        f"正式裁判已知 attempts：{display(judge['attempt_count'])}；已知失败 attempts：{display(judge['known_failed_attempts'])}；已知 attempt 秒：{display(judge['all_known_attempt_seconds'])}。计数来源：{judge['accounting_source']}。",
        f"已准备但未派发 {judge['prepared_not_dispatched_count']} 项，不计作实际裁判调用、耗时或费用。",
        "裁判账单、token 与实际返回版本：未知。保存的执行 summary 与单次 invocation 见 metrics.json；二者不会相加。", ""]
    for item in judge["execution_summaries"]:
        value = item["value"]
        wall = next((value[key] for key in ("pipeline_dispatch_to_last_response_wall_seconds", "stage_wall_seconds", "elapsed_seconds_this_invocation") if key in value), None)
        lines.append(f"- 执行汇总 `{item['path']}`：请求模型 {display(value.get('requested_model'))}／{display(value.get('requested_effort'))}；所记录墙钟 {display(wall)} 秒；范围 {value.get('timing_scope', '见原执行记录')}。")
    history = metrics["development_history"]
    lines += ["", f"已知开发本地运行 {len(history['runtime_records'])} 次，总运行 {display(history['known_runtime_seconds'])} 秒；开发裁判已知 attempt {display(history['known_judge_attempt_seconds'])} 秒。未覆盖的历史成本仍未知；开发数据不并入 test 分数。", "",
        "| 开发目录 | exit | runtime_error | 交付终态 | 运行秒 |", "|---|---:|---|---|---:|"]
    for row in history["runtime_records"]:
        lines.append(f"| {row['directory']} | {display(row['exit_code'])} | {display(row['runtime_error'])} | {row['ledger_status_counts']} | {display(row['total_runtime_seconds'])} |")
    lines += ["", f"另有手工开发阶段 {len(history['manual_stage_records'])} 次，已知阶段耗时 {display(history['known_manual_phase_seconds'])} 秒；已排除 runtime-covered 与原件副本。阶段耗时不代表完整运行墙钟，冷加载与设备采样保持未知。", "",
        "| 手工目录 | 阶段 | 交付终态 | 窗口 | 阶段秒／时间覆盖 | attempts／重试 | attempt 覆盖 | 冷加载／完整运行秒 |", "|---|---|---|---:|---:|---:|---:|---|"]
    for row in history["manual_stage_records"]:
        lines.append(f"| {row['directory']} | {row['phase']} | {row['ledger_status_counts']} | {display(row['ledger_windows'])} | {display(row['phase_seconds_measured'])}／{row['phase_timing_known_windows']} | {display(row['attempts_measured'])}／{display(row['retries_measured'])} | {row['attempts_known_windows']} | 未知／未知 |")
    lines += ["", "未结构化的启动／probe 日志仅保留路径，无法据此推算调用、时间或成本：", ""]
    lines += [f"- `{path}`" for path in history["unstructured_startup_probe_log_pointers"]] or ["- 无额外日志路径记录；未记录的历史成本仍未知。"]
    for row in history["judge_runs"]:
        lines.append(f"- 开发裁判 `{row['directory']}`：attempts {display(row['attempt_count'])}，已知失败 {display(row['known_failed_attempts'])}，已知 attempt 秒 {display(row['all_known_attempt_seconds'])}；已准备但未派发 {row['prepared_not_dispatched_count']} 项，排除于实际调用与成本。")
    lines += ["", "## 解释边界", ""] + [f"- {text}" for text in metrics["limitations"]]
    config = metrics["evaluation_configuration"] or {}
    lines += ["", f"评估版本：prompt `{display(config.get('prompt_version'))}`，validator `{display(config.get('judgment_validator_version'))}`；汇总执行身份 {quality.get('aggregation_execution')}。"]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="生成确定性的五候选比较报告与执行证据清单")
    for name in ("evaluation-dir", "run-root", "candidate-alias-key", "output-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        output = args.output_dir.resolve()
        if output.exists():
            raise ValueError("report output directory already exists; preserve original evidence")
        metrics = build_metrics(args.evaluation_dir.resolve(), args.run_root.resolve(), args.candidate_alias_key.resolve())
        output.mkdir(parents=True)
        dump(output / "metrics.json", metrics)
        (output / "report.md").write_text(report(metrics), encoding="utf-8")
        print(f"报告与证据清单已保存：{output}")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(2, f"报告生成失败：{exc}\n")


if __name__ == "__main__":
    main()
