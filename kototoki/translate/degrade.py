"""三级降级（产品配方 `dp10-cut-degrade-v1`，规格 §6）：批次终态失败 → 两个子批次 → 单条 → 保留日文。

终态失败指 `run_step` 用完尝试次数后仍是 `context`／`limit`／`parse`；基础设施失败不在这里处理，
由 `attempt` 原样抛给 `generate.translate_document` 的重启循环。拆分规则：

- 第 0 级（原批次，≤10 条）拆成前后两半 `父ID.a`／`父ID.b`（奇数条时前半多 1 条）；
- 第 1 级（半批）拆成单条 `父ID.a.1`…；
- 单条仍失败，该 cue 的译文 = 日文原文（回退）。只有 1 条的批次失败即回退，不再拆。

子批次按配方的同一条邻文规则（`batching.neighbours`）取只读邻文、seed 不变，因此提示、grammar 与采样构造与
原批次完全相同。
每个子批次的结果（以及失败的原批次）一出来就经 `record` 追加到降级日志，续跑时 `recorded` 里已有的节点
不再请求；整个批次完成后由调用方写成 `batches.jsonl` 的一行，回退由此对该配方 hash 与 seed 成为终态。
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from .batching import Batch, Scene, neighbours
from .recipes import Recipe

REPORT_SCHEMA = "kototoki-translate-report-v1"

log = logging.getLogger(__name__)


def children(scene: Scene, node: Batch, level: int, recipe: Recipe) -> list[Batch]:
    """`node` 终态失败后要请求的子批次；空列表表示该条只能回退。"""
    if len(node.target_ids) == 1:
        return []
    if level == 0:
        middle = node.start + (len(node.target_ids) + 1) // 2
        parts = [("a", node.start, middle), ("b", middle, node.stop)]
    else:
        parts = [(str(number), position, position + 1)
                 for number, position in enumerate(range(node.start, node.stop), 1)]
    ids = scene.ids
    result = []
    for suffix, start, stop in parts:
        left, right = neighbours(scene, start, stop, recipe)
        result.append(Batch(index=node.index, batch_id=f"{node.batch_id}.{suffix}", scene_id=node.scene_id,
                            target_ids=tuple(ids[start:stop]), before_ids=tuple(ids[left:start]),
                            after_ids=tuple(ids[stop:right]), start=start, stop=stop))
    return result


def translate_with_degrade(scene: Scene, batch: Batch, recipe: Recipe, attempt: Callable[[Batch], dict[str, Any]],
                           recorded: dict[str, dict[str, Any]], record: Callable[[dict[str, Any]], None]
                           ) -> dict[str, Any]:
    """翻译一个批次，终态失败时降级；返回 `batches.jsonl` 的一行。

    `attempt(node)` 接受时返回含 `translations` 的行，终态失败时返回含 `error_kind`／`error`、不含
    `translations` 的行，基础设施失败直接抛出。`recorded` 是本批次已在降级日志里的节点（batch_id → 行），
    `record(row)` 追加一个节点结果。未降级的批次原样返回首个请求的行，不写降级日志。
    """
    def run(node: Batch, level: int) -> dict[str, Any]:
        row = recorded.get(node.batch_id)
        if row is not None:
            if row.get("target_ids") != list(node.target_ids) or row.get("level") != level:
                raise ValueError(f"Degrade journal row {node.batch_id} does not match the degrade plan")
            return row
        row = attempt(node)
        if level == 0 and "translations" in row:
            return row
        row = {**row, "parent_index": batch.index, "level": level}
        record(row)
        return row

    first = run(batch, 0)
    if "translations" in first:
        return first
    text = {cue.id: cue.text for cue in scene.cues}
    translations: dict[str, str] = {}
    nodes: list[dict[str, Any]] = []
    fallback: list[dict[str, Any]] = []

    def solve(node: Batch, level: int) -> None:
        row = first if level == 0 else run(node, level)
        accepted = "translations" in row
        nodes.append({"batch_id": node.batch_id, "level": level, "target_ids": list(node.target_ids),
                      "status": "accepted" if accepted else "failed", "error_kind": row.get("error_kind"),
                      "attempts": len(row["request"].get("attempts", [])), "session": row.get("session"),
                      "request": row["request"]})
        if accepted:
            translations.update(row["translations"])
            return
        kids = children(scene, node, level, recipe)
        if kids:
            log.warning("[translate] batch %s failed (%s) at level %d; splitting into %d sub-batch(es)",
                        node.batch_id, row["error_kind"], level, len(kids))
        else:
            cue = node.target_ids[0]
            translations[cue] = text[cue]
            fallback.append({"id": cue, "batch_id": node.batch_id, "reason": row["error_kind"],
                             "error": row.get("error")})
        for kid in kids:
            solve(kid, level + 1)

    solve(batch, 0)
    if fallback:
        log.warning("[translate] batch %s: %d cue(s) kept in Japanese (fallback)", batch.batch_id, len(fallback))
    for item in fallback:
        item["attempts"] = sum(node["attempts"] for node in nodes if item["id"] in node["target_ids"])
    # 原批次的请求记录在 `nodes[0]`，不在行顶层重复。
    return {**batch.record(), "translations": {key: translations[key] for key in batch.target_ids},
            "degrade": {"nodes": nodes, "fallback": fallback}}


def build_report(rows: list[dict[str, Any]], completion: dict[str, Any]) -> dict[str, Any]:
    """`report.json`：降级批次、回退 cue（ID、原因、尝试次数）与计数；`rows` 是按批次顺序的已完成行。

    `degrade_requests` 只数子批次请求；每个降级批次的 `requests`／`attempts` 含失败的原批次。
    """
    degraded = [row for row in rows if "degrade" in row]
    fallback = [item for row in degraded for item in row["degrade"]["fallback"]]
    return {"schema": REPORT_SCHEMA, "completion": completion,
            "counts": {"batches": len(rows), "degraded_batches": len(degraded), "fallback_cues": len(fallback),
                       "degrade_requests": sum(len(row["degrade"]["nodes"]) - 1 for row in degraded)},
            "degraded_batches": [{"batch_id": row["batch_id"], "target_ids": row["target_ids"],
                                  "requests": len(row["degrade"]["nodes"]),
                                  "attempts": sum(node["attempts"] for node in row["degrade"]["nodes"]),
                                  "nodes": [{key: node[key] for key in ("batch_id", "level", "status", "error_kind",
                                                                        "attempts")}
                                            for node in row["degrade"]["nodes"]],
                                  "fallback_ids": [item["id"] for item in row["degrade"]["fallback"]]}
                                 for row in degraded],
            "fallback": fallback}
