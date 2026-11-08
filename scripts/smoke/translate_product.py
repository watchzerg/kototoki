"""真实模型验证：产品翻译子系统 `kototoki.translate` 在产品自动启停的 Strata 上跑几批（占 GPU、加载
Qwen3.8-Flash-Next，每次运行前须经用户批准；不属于任何 gate）。这是 ADR-0017／ADR-0019 要求的 Q2 首用 smoke。

入口：`just smoke translate_product`（`scripts/smoke/run_all.py` 持有 `.local/gpu.lock` 并以
`python scripts/smoke/translate_product.py --out <dir>` 启动本脚本；锁不存在时拒绝运行）。走产品代码：
`translate.plan` → `translate.Session`（`StrataServer`：`--status` 为空才启动、`strata launch --no-tui`、ADR-0017 接入
检查、结束 `--stop` 并核实显存释放）→ `translate.translate_document`，配方为产品配方 `q2-degrade-v1`，seed 取
`config.load` 的默认值。开始前若已有 Strata launch 在服务，产品拒绝运行，本脚本照实记为失败。

输入是下面内置的 12 条中性合成日语短句（不含任何真实字幕），第 6 条后留 20 s 停顿，dp10-cut 必在此切包，
因此至少两批；专名表只有一行 high 条目（駅 → 车站），用来走一遍注入。产物写入 `<out>/translate_product/`
（临时配置与工作目录），结果写 `<out>/translate_product.json`：只含计数、哈希、耗时、资源峰值与 Strata 身份，
不含原文与译文。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import smokelib

sys.path.insert(0, str(smokelib.REPO))

from kototoki import artifacts, config, srt, translate  # noqa: E402
from kototoki.translate import recipes as R  # noqa: E402

NAME = "translate_product"
GPU_LOCK = smokelib.REPO / ".local" / "gpu.lock"
SENTENCES = (
    "おはようございます。",
    "今日はいい天気ですね。",
    "駅までは歩いて十分ほどです。",
    "この本はとても面白かった。",
    "明日の会議は午後三時からです。",
    "少し休憩しましょうか。",
    "窓を開けてもいいですか。",
    "昼ご飯は何にしますか。",
    "電車が少し遅れているようです。",
    "週末は家でゆっくり過ごします。",
    "この道をまっすぐ行ってください。",
    "ありがとう、また明日。",
)
PAUSE_AFTER = 6       # 第 6 条后留长停顿
PAUSE_S = 20.0
CUE_S, GAP_S = 2.0, 1.0
NAME_TABLE = {"entries": [{"entity_ja": "駅", "kind": "place", "confidence": "high", "zh": "车站",
                           "forms": [{"ja": "駅", "zh": "车站"}], "zh_variants": [], "evidence": []}]}


def synthetic_srt() -> str:
    entries, start = [], 1.0
    for number, text in enumerate(SENTENCES, 1):
        entries.append((start, start + CUE_S, text))
        start += CUE_S + (PAUSE_S if number == PAUSE_AFTER else GAP_S)
    return srt.format_srt(entries)


def write_config(root: Path) -> config.Config:
    (root / "in").mkdir(parents=True, exist_ok=True)
    path = root / "kototoki.toml"
    path.write_text('[paths]\ninput_dir = "in"\nwork_dir = "work"\n', encoding="utf-8", newline="\n")
    return config.load(path)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def batch_stats(run_dir: Path) -> dict[str, Any]:
    """每包耗时与首次格式失败：取 `batches.jsonl` 每行原批次请求（降级的取 `degrade.nodes[0]`）的尝试记录。"""
    path = run_dir / "batches.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []
    packs = []
    for row in rows:
        request = row.get("request") or ((row.get("degrade") or {}).get("nodes") or [{}])[0].get("request") or {}
        attempts = request.get("attempts") or []
        first = attempts[0] if attempts else {}
        packs.append({"targets": len(row.get("target_ids") or []), "attempts": len(attempts),
                      "first_status": first.get("status"), "first_error_kind": first.get("error_kind"),
                      "seconds": sum(a.get("completion_seconds") or 0.0 for a in attempts),
                      "input_tokens": first.get("input_tokens"), "output_tokens": first.get("output_tokens"),
                      "reasoning_chars": sum(a.get("reasoning_chars") or 0 for a in attempts),
                      "names_injected": request.get("names_injected"), "degraded": "degrade" in row})
    seconds = [p["seconds"] for p in packs]
    return {"packs": packs,
            "first_attempt_format_failures": sum(1 for p in packs if p["first_error_kind"] in ("parse", "limit")),
            "degraded_packs": sum(1 for p in packs if p["degraded"]),
            "reasoning_chars": sum(p["reasoning_chars"] for p in packs),
            "seconds_per_pack": {"mean": sum(seconds) / len(seconds) if seconds else None,
                                 "max": max(seconds) if seconds else None}}


def main() -> int:
    args = smokelib.parse_args(__doc__)
    if not GPU_LOCK.is_file():
        print(f"{GPU_LOCK} absent; run via `just smoke {NAME}`, which holds the GPU lock", file=sys.stderr)
        return 1
    timer = smokelib.Timer()
    failures: list[str] = []
    root = args.out.resolve() / NAME
    cfg = write_config(root)
    document = srt.parse_srt(synthetic_srt())
    work_dir = cfg.paths.work_dir / "smoke"
    plan = translate.plan(work_dir, document, NAME_TABLE, cfg)
    result: dict[str, Any] = {
        "recipe": R.RECIPE_NAME, "recipe_hash": R.RECIPE_HASH, "seed": cfg.translate.seed, "model": R.MODEL,
        "names_sha256": plan.identity["names_sha256"],
        "input": {"cues": len(document.cues), "source_sha256": document.source_sha256,
                  "synthetic": True, "pause_after_cue": PAUSE_AFTER, "name_rows": 1}}
    translated = None
    try:
        with translate.Session(cfg) as session:
            translated = translate.translate_document(plan, session)
    except Exception as error:  # 记录失败类别后照常写结果
        failures.append(f"{type(error).__name__}: {str(error)[:500]}")
    timer.mark("translate")

    run = read(plan.run_dir / "run.json")
    if run is not None:
        result["completion"] = run.get("completion")
        result["server_start_failures"] = run.get("server_start_failures")
        result["sessions"] = [{"batches_written": s.get("batches_written"), "wall_seconds": s.get("wall_seconds"),
                               "stop_reason": s.get("stop_reason"), "cache_reset": s.get("cache_reset"),
                               "cold_load_seconds": (s.get("engine") or {}).get("cold_load_seconds"),
                               "free_vram_mib_before_start": (s.get("engine") or {}).get("free_vram_mib_before_start"),
                               "available_ram_gib_before_start": (s.get("engine") or {}).get(
                                   "available_ram_gib_before_start"),
                               "strata": {k: ((s.get("engine") or {}).get("strata") or {}).get(k)
                                          for k in ("version", "drafting", "expert_arena", "kv", "spec", "models")}}
                              for s in run.get("sessions", [])]
    sessions_root = artifacts.work_root(cfg.paths.work_dir, cfg.paths.input_dir) / "translate-sessions"
    result["resources"] = [read(p) for p in sorted(sessions_root.rglob("resources.json"))]
    result["strata_final"] = [read(p) for p in sorted(sessions_root.rglob("strata-final.json"))]
    result["batches"] = batch_stats(plan.run_dir)
    if not result["strata_final"] or not all(f.get("released") for f in result["strata_final"]):
        failures.append("Strata stop / GPU memory release not confirmed")
    arenas = [(s.get("strata") or {}).get("expert_arena") for s in result.get("sessions", [])]
    if any(arena != "ram" for arena in arenas):
        failures.append(f"Strata experts not held in RAM: {arenas!r} (mmap fallback is several times slower)")
    if result["batches"]["reasoning_chars"]:
        failures.append("reasoning_content was not empty (thinking must be off)")
    if translated is not None:
        ids = [cue.id for cue in document.cues]
        texts = [translated.translations.get(cue_id, "") for cue_id in ids]
        result["output"] = {"translations": len(translated.translations),
                            "nonempty": sum(1 for text in texts if text.strip()),
                            "translations_sha256": sha256_text(json.dumps(texts, ensure_ascii=False)),
                            "counts": translated.report.get("counts"), "fallback_cues": translated.fallback_count}
        if set(translated.translations) != set(ids):
            failures.append("translations do not cover every cue id")
        if not all(text.strip() for text in texts):
            failures.append("some translations are empty")
        if translated.fallback_count:
            failures.append(f"{translated.fallback_count} cue(s) fell back to Japanese")
        if (translated.report.get("counts") or {}).get("batches", 0) < 2:
            failures.append("expected at least two batches")
        if not any(p["names_injected"] for p in result["batches"]["packs"]):
            failures.append("the high-confidence name row was never injected")
    result.update(passed=not failures, failures=failures, elapsed_s=timer.marks, out=str(root))
    return smokelib.finish(args.out, NAME, result)


if __name__ == "__main__":
    sys.exit(main())
