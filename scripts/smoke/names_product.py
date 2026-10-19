"""真实模型验证：产品专名一致性模块 `kototoki.names` 在真实 Qwen llama-server 上建一张表并替换（占 GPU、加载
12 GB 模型，每次运行前须经用户批准；不属于任何 gate）。

入口：`just smoke names_product`（`scripts/smoke/run_all.py` 持有 `.local/gpu.lock` 并以
`python scripts/smoke/names_product.py --out <dir>` 启动本脚本；锁不存在时拒绝运行）。
与 `translate_product` 同形，走产品代码：`plan.names_identity` → `names.Session`（`ManagedServer`：引擎与模型身份核对、
空闲显存轮询、驻留校验）→ `names.build_document`（`/tokenize` 计数与 chat completions、`name-table-v2` JSON schema 输出）
→ `artifacts.write_artifact` → `names.apply`；模型、引擎、端口与 seed 取 `config.load` 的默认值。

输入是下面内置的 12 条合成日语短句（不含任何真实字幕）：同一人名エミリア的两种写法（正确写法与一处 ASR 式误写エミリヤ）、
一个职阶名セイバー，其余为中性句；并附一份人工给定的中文译文，其中人名的写法不一致，供 `apply` 统一。
产物写入 `<out>/names_product/`（临时配置、工作目录与 server 日志），结果写 `<out>/names_product.json`：
只含计数、哈希、耗时与引擎元数据，不含条目文字、原文与译文。

通过条件：server 驻留校验通过、`build.status == ok`、表至少一条 kind 为 person 的条目、`apply` 至少改动一个 cue、
改动后含该人名的 cue 只剩一种中文写法、无异常。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import smokelib

sys.path.insert(0, str(smokelib.REPO))

from kototoki import artifacts, config, names, plan, srt  # noqa: E402

NAME = "names_product"
GPU_LOCK = smokelib.REPO / ".local" / "gpu.lock"
# (日文, 人工给定的中文译文)；エミリア 出现 5 次、ASR 误写 エミリヤ 1 次，中文写了两种（艾米莉亚 4 处、爱蜜莉雅 2 处）。
# 两种写法不共享相邻二字组、被替换的写法两侧是标点或「的」，这样 `apply` 的统计层（至少两处支持、整词边界）才有落点；
# 只出现一次的误写 cue 其译文已是主写法——单次出现的写法 `apply` 本就不动。
LINES = (
    ("エミリアは窓の外を見ていた。", "艾米莉亚望着窗外。"),
    ("「エミリア、準備はできましたか。」", "“艾米莉亚,你准备好了吗?”"),
    ("エミリアは小さくうなずいた。", "爱蜜莉雅,轻轻点了点头。"),
    ("エミリヤが先に行くそうです。", "听说艾米莉亚要先走。"),
    ("セイバーは剣を構えて待っていた。", "剑兵拔剑等候着。"),
    ("今日はいい天気ですね。", "今天天气真好啊。"),
    ("セイバー、ここは任せました。", "剑兵,这里就交给你了。"),
    ("エミリアの声が聞こえた。", "爱蜜莉雅的声音传来了。"),
    ("セイバーは何も言わなかった。", "剑士什么也没说。"),
    ("電車が少し遅れているようです。", "电车好像晚点了。"),
    ("エミリアはゆっくり立ち上がった。", "艾米莉亚缓缓站了起来。"),
    ("ありがとう、また明日。", "谢谢,明天见。"),
)
NAME_FORMS_JA = ("エミリア", "エミリヤ")
NAME_ZH_WRITINGS = ("艾米莉亚", "爱蜜莉雅")  # 人工译文里的两种写法
CUE_S, GAP_S = 2.0, 1.0


def synthetic_srt() -> str:
    entries, start = [], 1.0
    for ja, _zh in LINES:
        entries.append((start, start + CUE_S, ja))
        start += CUE_S + GAP_S
    return srt.format_srt(entries)


def write_config(root: Path) -> config.Config:
    (root / "in").mkdir(parents=True, exist_ok=True)
    path = root / "kototoki.toml"
    path.write_text('[paths]\ninput_dir = "in"\noutput_dir = "out"\n', encoding="utf-8", newline="\n")
    return config.load(path)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def writings_used(texts: list[str], candidates: set[str]) -> set[str]:
    """这些译文里出现的候选写法集合；长的优先，已计入的区段不再被短串重复计入（艾米莉 不算 艾米莉亚 的一部分）。"""
    used: set[str] = set()
    for text in texts:
        for candidate in sorted(candidates, key=lambda c: (-len(c), c)):
            if candidate in text:
                used.add(candidate)
                text = text.replace(candidate, "")
    return used


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
    work_dir = cfg.paths.output_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "ja.srt").write_text(ja_text, encoding="utf-8", newline="\n")
    document = srt.read_srt(work_dir / "ja.srt")
    translations = {cue.id: zh for cue, (_ja, zh) in zip(document.cues, LINES)}
    identity = plan.names_identity(document.source_sha256, cfg)
    result: dict[str, Any] = {
        "recipe_hash": names.BUILD_RECIPE_HASH, "apply_recipe_hash": names.APPLY_RECIPE_HASH, "seed": cfg.names.seed,
        "engine": str(cfg.paths.llama_server), "model": str(cfg.models.names),
        "input": {"cues": len(document.cues), "source_sha256": document.source_sha256, "synthetic": True,
                  "translations_sha256": sha256_text(json.dumps(list(translations.values()), ensure_ascii=False))}}

    built = None
    try:
        with names.Session(cfg) as session:
            built = names.build_document(work_dir, document, session, cfg.names.seed)
    except Exception as error:  # 记录失败类别后照常写结果
        failures.append(f"build {type(error).__name__}: {str(error)[:500]}")
    timer.mark("build")

    finals = sorted((cfg.paths.output_dir / ".work").rglob("engine-final.json"))
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

        timer.mark("write")
        try:
            applied = names.apply(built.payload, document, translations)
        except Exception as error:
            applied = None
            failures.append(f"apply {type(error).__name__}: {str(error)[:300]}")
        if applied is not None:
            name_cues = [cue for cue in document.cues if any(form in cue.text for form in NAME_FORMS_JA)]
            before = [translations[cue.id] for cue in name_cues]
            after = [applied.translations[cue.id] for cue in name_cues]
            # 候选写法：人工译文里的三种，加上表里 person 条目各写法的中文目标。
            candidates = set(NAME_ZH_WRITINGS)
            for entry in persons:
                candidates.update(form["zh"] for form in entry.get("forms", []) if form.get("zh"))
            writings_before, writings_after = writings_used(before, candidates), writings_used(after, candidates)
            changed = sum(1 for cue in document.cues if applied.translations[cue.id] != translations[cue.id])
            result["apply"] = {"changes": len(applied.changes), "cues_changed": changed,
                               "unresolved": len(applied.unresolved), "name_cues": len(name_cues),
                               "writings_before": len(writings_before), "writings_after": len(writings_after),
                               "translations_sha256": sha256_text(json.dumps(
                                   [applied.translations[cue.id] for cue in document.cues], ensure_ascii=False)),
                               "totals": (applied.summary or {}).get("totals")}
            if set(applied.translations) != {cue.id for cue in document.cues}:
                failures.append("apply output does not cover every cue id")
            if not applied.changes or changed < 1:
                failures.append("apply changed nothing")
            if len(writings_after) != 1:
                failures.append(f"name not consistent after apply: {len(writings_after)} writings remain")
    timer.mark("apply")
    result.update(passed=not failures, failures=failures, elapsed_s=timer.marks, out=str(root))
    return smokelib.finish(args.out, NAME, result)


if __name__ == "__main__":
    sys.exit(main())
