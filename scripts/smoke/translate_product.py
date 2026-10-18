"""真实模型验证：产品翻译子系统 `kototoki.translate` 在真实 llama-server 上跑几批（占 GPU、加载翻译模型，
每次运行前须经用户批准；不属于任何 gate）。

入口：`just smoke translate_product`（`scripts/smoke/run_all.py` 持有 `.local/gpu.lock` 并以
`python scripts/smoke/translate_product.py --out <dir>` 启动本脚本；锁不存在时拒绝运行）。
与 `llama_stock` 不同，本脚本走产品代码：`translate.plan` → `translate.Session`（`ManagedServer`：引擎与模型身份
核对、空闲显存轮询、驻留校验）→ `translate.translate_document`，配方为产品配方 `dp10-cut-degrade-v1`，
模型、引擎、端口与 seed 取 `config.load` 的默认值。

输入是下面内置的 12 条中性合成日语短句（不含任何真实字幕），第 6 条后留 20 s 停顿，dp10-cut 必在此切包，
因此至少两批。产物写入 `<out>/translate_product/`（临时配置、工作目录与 server 日志），结果写
`<out>/translate_product.json`：只含计数、哈希、耗时与引擎元数据，不含原文与译文。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import smokelib

sys.path.insert(0, str(smokelib.REPO))

from kototoki import config, srt, translate  # noqa: E402
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


def synthetic_srt() -> str:
    entries, start = [], 1.0
    for number, text in enumerate(SENTENCES, 1):
        entries.append((start, start + CUE_S, text))
        start += CUE_S + (PAUSE_S if number == PAUSE_AFTER else GAP_S)
    return srt.format_srt(entries)


def write_config(root: Path) -> config.Config:
    (root / "in").mkdir(parents=True, exist_ok=True)
    path = root / "kototoki.toml"
    path.write_text('[paths]\ninput_dir = "in"\noutput_dir = "out"\n', encoding="utf-8", newline="\n")
    return config.load(path)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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
    work_dir = cfg.paths.output_dir / "work"
    plan = translate.plan(work_dir, document, cfg)
    result: dict[str, Any] = {
        "recipe": R.PRODUCT.name, "recipe_hash": R.PRODUCT.recipe_hash, "seed": cfg.translate.seed,
        "engine": str(cfg.paths.llama_server), "model": str(cfg.models.translate),
        "input": {"cues": len(document.cues), "source_sha256": document.source_sha256,
                  "synthetic": True, "pause_after_cue": PAUSE_AFTER}}
    translated = None
    try:
        with translate.Session(cfg) as session:
            translated = translate.translate_document(plan, session)
    except Exception as error:  # 记录失败类别后照常写结果
        failures.append(f"{type(error).__name__}: {str(error)[:500]}")
    timer.mark("translate")

    run_path = plan.run_dir / "run.json"
    if run_path.is_file():
        run = json.loads(run_path.read_text(encoding="utf-8"))
        result["completion"] = run.get("completion")
        result["sessions"] = [{"batches_written": s.get("batches_written"), "wall_seconds": s.get("wall_seconds"),
                               "stop_reason": s.get("stop_reason"),
                               "cold_load_seconds": (s.get("engine") or {}).get("cold_load_seconds"),
                               "free_vram_mib_before_start": (s.get("engine") or {}).get("free_vram_mib_before_start"),
                               "residency": (s.get("engine") or {}).get("residency")}
                              for s in run.get("sessions", [])]
    finals = sorted((cfg.paths.output_dir / ".work").rglob("engine-final.json"))
    result["peak_device_memory_mib"] = [json.loads(p.read_text(encoding="utf-8")).get("peak_device_memory_mib")
                                        for p in finals]
    if translated is not None:
        ids = [cue.id for cue in document.cues]
        texts = [translated.translations.get(cue_id, "") for cue_id in ids]
        result["output"] = {"translations": len(translated.translations),
                            "nonempty": sum(1 for text in texts if text.strip()),
                            "translations_sha256": sha256_text(json.dumps(texts, ensure_ascii=False)),
                            "counts": translated.report.get("counts")}
        if set(translated.translations) != set(ids):
            failures.append("translations do not cover every cue id")
        if not all(text.strip() for text in texts):
            failures.append("some translations are empty")
        if translated.fallback_count:
            failures.append(f"{translated.fallback_count} cue(s) fell back to Japanese")
        if (translated.report.get("counts") or {}).get("batches", 0) < 2:
            failures.append("expected at least two batches")
    result.update(passed=not failures, failures=failures, elapsed_s=timer.marks, out=str(root))
    return smokelib.finish(args.out, NAME, result)


if __name__ == "__main__":
    sys.exit(main())
