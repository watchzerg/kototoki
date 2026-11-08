"""真实模型验证：产品专名一致性模块 `kototoki.names` 在真实 Qwen llama-server 上建一张表（占 GPU、加载
12 GB 模型，每次运行前须经用户批准；不属于任何 gate）。

入口：`just smoke names_product`（`scripts/smoke/run_all.py` 持有 `.local/gpu.lock` 并以
`python scripts/smoke/names_product.py --out <dir>` 启动本脚本；锁不存在时拒绝运行）。
与 `translate_product` 同形，走产品代码：`plan.names_identity` → `names.Session`（`ManagedServer`：引擎与模型身份核对、
空闲显存轮询、驻留校验）→ `names.build_document`（`/tokenize` 计数与 chat completions、`name-table-v2` JSON schema 输出）
→ `artifacts.write_artifact` → 按 Q2 规则取注入行（`translate.recipes.name_rows`，ADR-0019：产品只注入、不替换）；
模型、引擎、端口与 seed 取 `config.load` 的默认值。

输入是下面内置的 12 条合成日语短句（不含任何真实字幕）：同一人名エミリア的两种写法（正确写法与一处 ASR 式误写エミリヤ）、
一个职阶名セイバー，其余为中性句。产物写入 `<out>/names_product/`（临时配置、工作目录与 server 日志），
结果写 `<out>/names_product.json`：只含计数、哈希、耗时与引擎元数据，不含条目文字与原文。

通过条件：server 驻留校验通过、`build.status == ok`、表至少一条 kind 为 person 的条目、写回的表对其身份为 current、
无异常。注入行数（high 条目的写法）只记录：置信度由模型给出，合成输入不保证有 high 条目。
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

import smokelib

sys.path.insert(0, str(smokelib.REPO))

from kototoki import artifacts, config, names, plan, srt  # noqa: E402
from kototoki.translate import recipes as translate_recipes  # noqa: E402

NAME = "names_product"
GPU_LOCK = smokelib.REPO / ".local" / "gpu.lock"
# エミリア 出现 5 次、ASR 误写 エミリヤ 1 次；セイバー 3 次。
LINES = (
    "エミリアは窓の外を見ていた。",
    "「エミリア、準備はできましたか。」",
    "エミリアは小さくうなずいた。",
    "エミリヤが先に行くそうです。",
    "セイバーは剣を構えて待っていた。",
    "今日はいい天気ですね。",
    "セイバー、ここは任せました。",
    "エミリアの声が聞こえた。",
    "セイバーは何も言わなかった。",
    "電車が少し遅れているようです。",
    "エミリアはゆっくり立ち上がった。",
    "ありがとう、また明日。",
)
CUE_S, GAP_S = 2.0, 1.0


def synthetic_srt() -> str:
    entries, start = [], 1.0
    for ja in LINES:
        entries.append((start, start + CUE_S, ja))
        start += CUE_S + GAP_S
    return srt.format_srt(entries)


def write_config(root: Path) -> config.Config:
    (root / "in").mkdir(parents=True, exist_ok=True)
    path = root / "kototoki.toml"
    path.write_text('[paths]\ninput_dir = "in"\nwork_dir = "work"\n', encoding="utf-8", newline="\n")
    return config.load(path)


def main() -> int:
    args = smokelib.parse_args(__doc__)
    if not GPU_LOCK.is_file():
        print(f"{GPU_LOCK} absent; run via `just smoke {NAME}`, which holds the GPU lock", file=sys.stderr)
        return 1
    timer = smokelib.Timer()
    failures: list[str] = []
    root = args.out.resolve() / NAME
    cfg = write_config(root)
    ja_text = synthetic_srt()
    work_dir = cfg.paths.work_dir / "doc"  # 单部影片的工作目录；server 运行日志落在 work_dir 下的目标目录键子目录
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "ja.srt").write_text(ja_text, encoding="utf-8", newline="\n")
    document = srt.read_srt(work_dir / "ja.srt")
    identity = plan.names_identity(document.source_sha256, cfg)
    result: dict[str, Any] = {
        "recipe_hash": names.BUILD_RECIPE_HASH, "seed": cfg.names.seed,
        "engine": str(cfg.paths.llama_server), "model": str(cfg.models.names),
        "input": {"cues": len(document.cues), "source_sha256": document.source_sha256, "synthetic": True}}

    built = None
    try:
        with names.Session(cfg) as session:
            built = names.build_document(work_dir, document, session, cfg.names.seed)
    except Exception as error:  # 记录失败类别后照常写结果
        failures.append(f"build {type(error).__name__}: {str(error)[:500]}")
    timer.mark("build")

    finals = sorted(cfg.paths.work_dir.rglob("engine-final.json"))
    engines = [json.loads(path.read_text(encoding="utf-8")) for path in finals]
    result["engine_sessions"] = [{"cold_load_seconds": e.get("cold_load_seconds"),
                                  "free_vram_mib_before_start": e.get("free_vram_mib_before_start"),
                                  "peak_device_memory_mib": e.get("peak_device_memory_mib"),
                                  "server_stop": e.get("server_stop"), "residency": e.get("residency")}
                                 for e in engines]
    residency = (engines[0].get("residency") if engines else None) or {}
    result["residency_ok"] = bool(residency.get("gpu_layers_offloaded")) and not residency.get("partial_layer_offload")
    if not result["residency_ok"]:
        failures.append("residency evidence missing or partial")

    if built is not None:
        meta = built.payload.get("meta") or {}
        entries = built.payload.get("entries") or []
        kinds: dict[str, int] = {}
        for entry in entries:
            kinds[entry.get("kind", "?")] = kinds.get(entry.get("kind", "?"), 0) + 1
        result["build"] = {"status": built.status, "attempts": built.attempts, "seconds": round(built.seconds, 2),
                           "prompt_tokens": meta.get("prompt_tokens"), "completion_tokens": meta.get("completion_tokens"),
                           "entries": len(entries), "kinds": kinds,
                           "dropped": {key: len(meta.get(key) or [])
                                       for key in ("dropped_shape", "dropped_honorific", "dropped_ja_shape")}}
        if built.status != "ok":
            failures.append(f"build status {built.status}")
        persons = [entry for entry in entries if entry.get("kind") == "person"]
        if not persons:
            failures.append("name table has no person entry")
        try:
            artifacts.write_artifact(work_dir / artifacts.NAME_TABLE, identity, built.payload)
            result["table_sha256"] = artifacts.sha256_file(work_dir / artifacts.NAME_TABLE)
            result["table_current"] = artifacts.is_current(work_dir / artifacts.NAME_TABLE, identity)
            if not result["table_current"]:
                failures.append("written name table is not current for its identity")
        except Exception as error:
            failures.append(f"write_artifact {type(error).__name__}: {str(error)[:300]}")

        rows = translate_recipes.name_rows(built.payload)
        result["injection_rows"] = {"rows": len(rows), "names_sha256": translate_recipes.names_sha256(rows),
                                    "high_entries": sum(1 for e in entries if e.get("confidence") == "high")}
    timer.mark("write")
    result.update(passed=not failures, failures=failures, elapsed_s=timer.marks, out=str(root))
    return smokelib.finish(args.out, NAME, result)


if __name__ == "__main__":
    sys.exit(main())
