"""Prepare source-only SRT trials and export complete, traceable deliveries."""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from experiments.translation_demo import adapters
from .recipes import RECIPES, SAMPLING_PROFILES
from . import srt
from .worker import CANDIDATE, SCHEMA, load_plan


PREPARED_SCHEMA = "hy30-srt-prepared-v1"
APEX_SHA256 = "8a51a390b285fb1eb566a1683f8da476be9e87c1fbee5507967d6129872dfa1a"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path: Path) -> Any:
    return adapters.strict_json(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            row = adapters.strict_json(line)
            if not isinstance(row, dict):
                raise ValueError("JSONL rows must be objects")
            rows.append(row)
    return rows


def scoped_document(document: srt.SourceDocument, start: int | None,
                    end: int | None) -> srt.SourceDocument:
    indices = {cue.index: position for position, cue in enumerate(document.cues)}
    first = 0 if start is None else indices.get(start)
    last = len(document.cues) - 1 if end is None else indices.get(end)
    if first is None or last is None or first > last:
        raise ValueError("Cue bounds must be existing original SRT indices in source order")
    return replace(document, cues=document.cues[first:last + 1])


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    source, output = args.source.resolve(), args.output.resolve()
    if source.suffix.lower() != ".srt":
        raise ValueError("Prepare accepts only a Japanese source SRT, never reference JSONL")
    if output.exists():
        raise FileExistsError("Prepared output must be a new directory")
    full = srt.read_srt(source, encoding=args.encoding)
    document = scoped_document(full, args.start_cue, args.end_cue)
    batches = srt.plan_batches(document, target_size=args.target_size,
                               context_size=args.context_size, policy=args.policy,
                               gap_ms=args.gap_ms)
    budgets = {name: getattr(args, name) for name in (
        "max_translation_calls", "max_judge_calls", "max_estimated_tokens", "max_wall_seconds")}
    item = {"label": args.recipe, "inputs": "model-input.jsonl", "input_sha256": "",
            "recipe": args.recipe, "sampling": args.sampling, "seed": args.seed,
            "n_predict": args.n_predict, "max_attempts": args.max_attempts}
    output.mkdir(parents=True, exist_ok=False)
    inputs = output / item["inputs"]
    with inputs.open("x", encoding="utf-8", newline="\n") as stream:
        for batch in batches:
            window = batch.to_window()
            adapters.validate_window(window)
            stream.write(json.dumps(window, ensure_ascii=False) + "\n")
    item["input_sha256"] = digest(inputs)
    plan = {"schema": SCHEMA, "lane": "P-flow", "stage": args.stage,
            "budgets": budgets, "workloads": [item]}
    write_json(output / "session-plan.json", plan)
    # The same worker validator checks budgets, stage caps, recipes and firewall.
    load_plan(output / "session-plan.json")
    provenance = srt.source_provenance(document)
    provenance["full_source_cue_count"] = len(full.cues)
    provenance["scope"] = "full_source" if len(document.cues) == len(full.cues) else "continuous_excerpt"
    write_json(output / "source-provenance.json", provenance)
    write_json(output / "batch-mapping.json", {
        "source_sha256": full.source_sha256,
        "batches": [{"id": b.id, "target_ids": list(b.target_ids),
                     "readonly_ids": list(b.readonly_ids)} for b in batches],
        "context_scope": "selected_source_scope_only",
    })
    write_json(output / "source-diagnostics.json", srt.diagnostics(document))
    if digest(source) != full.source_sha256:
        raise ValueError("Source changed during preparation; this directory is unpublished")
    manifest = {
        "schema": PREPARED_SCHEMA, "lane": "P-flow", "source_path": str(source),
        "source_sha256": full.source_sha256, "encoding": args.encoding,
        "full_source_cue_count": len(full.cues),
        "scope": {"kind": provenance["scope"], "indices": [c.index for c in document.cues],
                  "start_cue": document.cues[0].index, "end_cue": document.cues[-1].index},
        "batching": {"target_size": args.target_size, "context_size": args.context_size,
                     "policy": args.policy, "gap_ms": args.gap_ms},
        "candidate": CANDIDATE, "model_sha256": APEX_SHA256,
        "artifacts": {name: digest(output / name) for name in (
            "model-input.jsonl", "session-plan.json", "source-provenance.json",
            "batch-mapping.json", "source-diagnostics.json")},
        "quality_status": "source-only preparation; semantic quality unverified",
    }
    # Publication marker is written only after the complete immutable preparation.
    write_json(output / "prepared.json", manifest)
    return manifest


def load_prepared(directory: Path) -> tuple[dict[str, Any], srt.SourceDocument, list[dict[str, Any]], dict[str, Any]]:
    manifest = read_json(directory / "prepared.json")
    if not isinstance(manifest, dict) or manifest.get("schema") != PREPARED_SCHEMA or manifest.get("lane") != "P-flow":
        raise ValueError("Expected a published source-only SRT preparation")
    expected_files = {"model-input.jsonl", "session-plan.json", "source-provenance.json",
                      "batch-mapping.json", "source-diagnostics.json"}
    if set(manifest.get("artifacts", {})) != expected_files:
        raise ValueError("Prepared artifact identities are incomplete")
    for name, sha in manifest["artifacts"].items():
        if digest(directory / name) != sha:
            raise ValueError(f"Prepared artifact changed: {name}")
    full = srt.read_srt(manifest["source_path"], encoding=manifest["encoding"])
    if full.source_sha256 != manifest["source_sha256"]:
        raise ValueError("Original source SRT hash changed after preparation")
    scope = manifest["scope"]
    document = scoped_document(full, scope["start_cue"], scope["end_cue"])
    if [c.index for c in document.cues] != scope["indices"] or len(full.cues) != manifest["full_source_cue_count"]:
        raise ValueError("Prepared source scope differs from original provenance")
    batches = srt.plan_batches(document, **manifest["batching"])
    windows = read_rows(directory / "model-input.jsonl")
    if windows != [batch.to_window() for batch in batches]:
        raise ValueError("Frozen model input differs from original source scope")
    plan, _ = load_plan(directory / "session-plan.json")
    if plan.get("lane") != "P-flow" or len(plan["workloads"]) != 1:
        raise ValueError("Prepared SRT requires one explicitly named P-flow workload")
    return manifest, document, windows, plan["workloads"][0]


def atomic_publish(path: Path, text: str) -> None:
    """A complete flushed file appears under the final name without overwriting."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         prefix=".chn-", suffix=".tmp", dir=path.parent,
                                         delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def export(args: argparse.Namespace) -> dict[str, Any]:
    prepared, run_dir, output = args.prepared.resolve(), args.translation_run.resolve(), args.output.resolve()
    if output.exists():
        raise FileExistsError("Export output must be a new directory")
    manifest, document, windows, workload = load_prepared(prepared)
    run = read_json(run_dir / "run.json")
    expected_ids = [w["id"] for w in windows]
    if (run.get("lane") != "P-flow" or run.get("candidate") != CANDIDATE
            or run.get("input_sha256") != manifest["artifacts"]["model-input.jsonl"]
            or run.get("session_plan_sha256") != manifest["artifacts"]["session-plan.json"]
            or run.get("expected_window_ids") != expected_ids or run.get("settings") != workload
            or run.get("asset", {}).get("sha256") != APEX_SHA256
            or run.get("engine", {}).get("model_sha256") != APEX_SHA256):
        raise ValueError("Translation run identity differs from the frozen SRT plan")
    if digest(run_dir / "inputs.jsonl") != manifest["artifacts"]["model-input.jsonl"]:
        raise ValueError("Translation run input copy changed")
    targets = {w["id"]: set(w["translate_ids"]) for w in windows}
    translations: dict[str, str] = {}
    problems = []
    ledger: dict[str, dict[str, Any]] = {}

    def output_rows(name: str) -> list[dict[str, Any]]:
        try:
            return read_rows(run_dir / name)
        except (ValueError, OSError) as exc:
            problems.append({"reason": "unreadable_output_artifact", "artifact": name,
                             "error": str(exc)})
            return []

    for row in output_rows("ledger.jsonl"):
        key = row.get("window_id")
        if not isinstance(key, str) or key not in targets or key in ledger:
            problems.append({"reason": "unknown_or_duplicate_ledger_window", "id": key})
        else:
            ledger[key] = row
    seen = set()
    raw_hashes = {name: digest(run_dir / name) if (run_dir / name).is_file() else None
                  for name in ("run.json", "inputs.jsonl", "results.jsonl", "ledger.jsonl")}
    response_hashes = {}
    for row in output_rows("results.jsonl"):
        key = row.get("id")
        if set(row) - {"id", "translations", "elapsed_seconds"} or not {"id", "translations"} <= set(row):
            problems.append({"reason": "result_contains_noncontract_fields", "id": key})
            continue
        if not isinstance(key, str) or key not in targets or key in seen:
            problems.append({"reason": "unknown_or_duplicate_result_window", "id": key})
            continue
        seen.add(key)
        values = row["translations"]
        entry = ledger.get(key)
        if not isinstance(values, dict) or entry is None or entry.get("translations") != values:
            problems.append({"reason": "result_ledger_conflict", "id": key})
            continue
        if entry.get("status") != "delivered":
            problems.append({"reason": "batch_not_delivered", "id": key, "status": entry.get("status")})
            continue
        if set(values) != targets[key]:
            problems.append({"reason": "batch_target_id_mismatch", "id": key})
            continue
        overlap = set(values) & set(translations)
        if overlap:
            problems.append({"reason": "duplicate_cue_assignment", "ids": sorted(overlap)})
            continue
        translations.update(values)
        for attempt in entry.get("attempts", []):
            pointer = attempt.get("original_response")
            if not isinstance(pointer, str):
                continue
            raw = (Path(pointer) / "response.raw").resolve()
            if not raw.is_relative_to(run_dir):
                problems.append({"reason": "raw_response_outside_run", "id": key})
            elif raw.is_file():
                response_hashes[str(raw.relative_to(run_dir))] = digest(raw)
    coverage = srt.validate_translations(document, translations)
    coverage.update(missing_batch_ids=[key for key in expected_ids if key not in seen],
                    problems=problems, scope=manifest["scope"])
    if problems:
        coverage["status"] = "partial"
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "coverage.json", coverage)
    sidecar = {"schema": "hy30-srt-export-v1", "lane": "P-flow", "coverage": coverage,
               "prepared_manifest_sha256": digest(prepared / "prepared.json"),
               "source": srt.source_provenance(document),
               "run_path": str(run_dir), "raw_output_sha256": raw_hashes,
               "raw_response_sha256": response_hashes,
               "batch_mapping": read_json(prepared / "batch-mapping.json"),
               "semantic_quality_checked": False, "exported_srt": None}
    if coverage["status"] == "complete":
        sidecar["display_diagnostics"] = srt.diagnostics(document, translations)
        rendered = srt.render_srt(document, translations)
        if digest(Path(manifest["source_path"])) != manifest["source_sha256"]:
            raise ValueError("Source changed before final export")
        sidecar["exported_srt"] = "chn.srt"
        sidecar["exported_srt_sha256"] = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        write_json(output / "export-sidecar.json", sidecar)
        atomic_publish(output / "chn.srt", rendered)
    else:
        write_json(output / "export-sidecar.json", sidecar)
    return coverage


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="准备源 SRT，或从冻结运行导出完整中文字幕；不启动模型。")
    sub = result.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="冻结源字幕、批次和显式预算")
    prep.add_argument("--source", type=Path, required=True)
    prep.add_argument("--output", type=Path, required=True, help="尚不存在的准备目录")
    prep.add_argument("--encoding", default="utf-8-sig")
    prep.add_argument("--start-cue", type=int, help="首条原始 SRT 序号，含该条")
    prep.add_argument("--end-cue", type=int, help="末条原始 SRT 序号，含该条")
    prep.add_argument("--target-size", type=int, default=5)
    prep.add_argument("--context-size", type=int, default=1, help="批次每侧只读源 cue 数")
    prep.add_argument("--policy", choices=("fixed", "natural"), default="fixed")
    prep.add_argument("--gap-ms", type=int, default=1000)
    prep.add_argument("--recipe", choices=RECIPES, default="b0-cached")
    prep.add_argument("--sampling", choices=SAMPLING_PROFILES, default="official")
    prep.add_argument("--seed", type=int, default=20261006)
    prep.add_argument("--n-predict", type=int, default=4096)
    prep.add_argument("--max-attempts", type=int, choices=(1, 2), default=2)
    prep.add_argument("--stage", choices=("P0", "P1", "P2", "P3", "P4", "P5"), required=True)
    prep.add_argument("--max-translation-calls", type=int, required=True)
    prep.add_argument("--max-judge-calls", type=int, required=True)
    prep.add_argument("--max-estimated-tokens", type=int, required=True)
    prep.add_argument("--max-wall-seconds", type=float, required=True)
    out = sub.add_parser("export", help="校验完整覆盖后保存 chn.srt 和来源 sidecar")
    out.add_argument("--prepared", type=Path, required=True)
    out.add_argument("--translation-run", type=Path, required=True, help="包含 run.json/results.jsonl/ledger.jsonl 的单配方目录")
    out.add_argument("--output", type=Path, required=True, help="尚不存在的导出目录")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = prepare(args) if args.command == "prepare" else export(args)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"操作未完成：{exc}")
        return 2
    print(json.dumps({"status": result.get("status", "prepared"),
                      "output": str(args.output.resolve())}, ensure_ascii=False))
    return 1 if result.get("status") == "partial" else 0
