"""按条解决（产品配方 `q3-translate-v1`，ADR-0029）：一个批次 → 若干节点 → 每条 cue 收下译文或不出中文。

节点是场景内连续的一段待译 cue（`batching.Batch`），初始节点即切包产出的批次。`attempt(node)` 对一个节点最多请求
两次（seed、seed＋1，见 `generate.run_step`）：

- 某次回复结构合法且收下至少 1 条：节点结束，行含 `translations`（收下的 cue）与 `unresolved`（cue →
  `missing`／`empty`／`blank_line`）；未解决的 cue 按场景顺序切成最大连续段，每段成为子节点 `父ID.1`、`父ID.2`…；
- 终态失败（两次都结构失败或一条都没收下；超出 context 只请求一次）：行含 `error_kind`／`error`、不含
  `translations`；多于 1 条的节点对半拆成 `父ID.a`／`父ID.b`（奇数条时前半多 1 条），只有 1 条的节点该 cue 不出
  中文（译文为 `None`）。

子节点必比父节点小，过程必然终止。子节点按同一条邻文规则（`batching.neighbours`）取只读邻文、seed 从原 seed 起，
提示、专名注入与请求构造与原批次相同。只按条取第一个合格译文、不比较不同尝试，不属于 ADR-0008 的"翻译多次再挑选"。

首个请求即全部收下的批次原样返回、不写节点日志；其余每个节点的结果一出来就经 `record` 追加到节点日志，续跑时
`recorded` 里已有的节点不再请求。整个批次完成后由调用方写成 `batches.jsonl` 的一行，未翻译由此对该配方 hash 与
seed 成为终态。基础设施失败不在这里处理，由 `attempt` 原样抛给 `generate.translate_document` 的重启循环。
"""

from __future__ import annotations

from collections import Counter
import logging
from typing import Any, Callable, Iterable

from .batching import Batch, Scene, neighbours

REPORT_SCHEMA = "kototoki-translate-report-v2"

log = logging.getLogger(__name__)


def _node(scene: Scene, parent: Batch, suffix: str, start: int, stop: int) -> Batch:
    left, right = neighbours(scene, start, stop)
    ids = scene.ids
    return Batch(index=parent.index, batch_id=f"{parent.batch_id}.{suffix}", scene_id=parent.scene_id,
                 target_ids=tuple(ids[start:stop]), before_ids=tuple(ids[left:start]),
                 after_ids=tuple(ids[stop:right]), start=start, stop=stop)


def halves(scene: Scene, node: Batch) -> list[Batch]:
    """终态失败的节点拆成前后两半；只有 1 条时为空列表（该 cue 不出中文）。"""
    if len(node.target_ids) == 1:
        return []
    middle = node.start + (len(node.target_ids) + 1) // 2
    return [_node(scene, node, "a", node.start, middle), _node(scene, node, "b", middle, node.stop)]


def runs(scene: Scene, node: Batch, unresolved: Iterable[str]) -> list[Batch]:
    """节点内未解决的 cue 按场景顺序切成最大连续段，每段一个子节点。"""
    position = {cue_id: node.start + offset for offset, cue_id in enumerate(node.target_ids)}
    spans: list[list[int]] = []
    for point in sorted(position[cue_id] for cue_id in unresolved):
        if spans and spans[-1][1] == point:
            spans[-1][1] = point + 1
        else:
            spans.append([point, point + 1])
    return [_node(scene, node, str(number), start, stop) for number, (start, stop) in enumerate(spans, 1)]


def reason_counts(unresolved: dict[str, str]) -> str:
    """`{"empty": 2, "missing": 1}` → `empty 2, missing 1`（日志与错误消息用，不含台词）。"""
    return ", ".join(f"{reason} {count}" for reason, count in sorted(Counter(unresolved.values()).items()))


def _last_reason(row: dict[str, Any], cue: str) -> str:
    """单条节点终态失败时该 cue 的原因：最后一次尝试结构合法但没收下它时取按条判的类别，否则取失败种类。"""
    last = (row["request"].get("attempts") or [{}])[-1]
    return (last.get("unresolved") or {}).get(cue) or row["error_kind"]


def translate_resolving(scene: Scene, batch: Batch, attempt: Callable[[Batch], dict[str, Any]],
                        recorded: dict[str, dict[str, Any]], record: Callable[[dict[str, Any]], None]
                        ) -> dict[str, Any]:
    """翻译一个批次，按条解决；返回 `batches.jsonl` 的一行。

    `attempt(node)` 收下至少 1 条时返回含 `translations`、`unresolved` 的行，终态失败时返回含 `error_kind`／`error`、
    不含 `translations` 的行，基础设施失败直接抛出。`recorded` 是本批次已在节点日志里的节点（batch_id → 行），
    `record(row)` 追加一个节点结果。
    """
    def run(node: Batch, depth: int) -> tuple[dict[str, Any], bool]:
        row = recorded.get(node.batch_id)
        if row is not None:
            if row.get("target_ids") != list(node.target_ids) or row.get("depth") != depth:
                raise ValueError(f"Node journal row {node.batch_id} does not match the resolution plan")
            return row, False
        row = attempt(node)
        if depth == 0 and "translations" in row and not row["unresolved"]:
            return row, True
        row = {**row, "parent_index": batch.index, "depth": depth}
        record(row)
        return row, True

    first, first_fresh = run(batch, 0)
    if "translations" in first and not first["unresolved"]:
        return {key: value for key, value in first.items() if key != "unresolved"}
    translations: dict[str, str | None] = {}
    nodes: list[dict[str, Any]] = []
    untranslated: list[dict[str, Any]] = []

    def solve(node: Batch, depth: int) -> None:
        row, fresh = (first, first_fresh) if depth == 0 else run(node, depth)
        accepted = "translations" in row
        unresolved: dict[str, str] = row.get("unresolved") or {}
        nodes.append({"batch_id": node.batch_id, "depth": depth, "target_ids": list(node.target_ids),
                      "status": ("partial" if unresolved else "accepted") if accepted else "failed",
                      "error_kind": row.get("error_kind"), "unresolved": unresolved,
                      "attempts": len(row["request"].get("attempts", [])), "session": row.get("session"),
                      "request": row["request"]})
        if accepted:
            translations.update(row["translations"])
            kids = runs(scene, node, unresolved)
            if kids and fresh:
                log.warning("[translate] batch %s: %d cue(s) unresolved (%s); asking again in %d sub-batch(es)",
                            node.batch_id, len(unresolved), reason_counts(unresolved), len(kids))
        else:
            kids = halves(scene, node)
            if kids:
                if fresh:
                    log.warning("[translate] batch %s failed (%s); splitting into %d sub-batch(es)", node.batch_id,
                                row["error_kind"], len(kids))
            else:
                cue = node.target_ids[0]
                translations[cue] = None
                untranslated.append({"id": cue, "batch_id": node.batch_id, "reason": _last_reason(row, cue),
                                     "error": row.get("error")})
        for kid in kids:
            solve(kid, depth + 1)

    solve(batch, 0)
    if untranslated:
        log.warning("[translate] batch %s: %d cue(s) left untranslated: %s", batch.batch_id, len(untranslated),
                    ", ".join(f"{item['id']} ({item['reason']})" for item in untranslated))
    for item in untranslated:
        item["attempts"] = sum(node["attempts"] for node in nodes if item["id"] in node["target_ids"])
    # 原批次的请求记录在 `nodes[0]`，不在行顶层重复。
    return {**batch.record(), "translations": {key: translations[key] for key in batch.target_ids},
            "resolution": {"nodes": nodes, "untranslated": untranslated}}


def build_report(rows: list[dict[str, Any]], completion: dict[str, Any]) -> dict[str, Any]:
    """`report.json`：需要追问的批次（节点摘要）、未翻译 cue（ID、原因、尝试次数）与计数；`rows` 是按批次顺序的已完成行。

    `followup_requests` 只数原批次之外的节点请求；每个批次的 `requests`／`attempts` 含原批次。
    """
    followed = [row for row in rows if "resolution" in row]
    untranslated = [item for row in followed for item in row["resolution"]["untranslated"]]
    return {"schema": REPORT_SCHEMA, "completion": completion,
            "counts": {"batches": len(rows), "followup_batches": len(followed), "untranslated_cues": len(untranslated),
                       "followup_requests": sum(len(row["resolution"]["nodes"]) - 1 for row in followed)},
            "followup_batches": [{"batch_id": row["batch_id"], "target_ids": row["target_ids"],
                                  "requests": len(row["resolution"]["nodes"]),
                                  "attempts": sum(node["attempts"] for node in row["resolution"]["nodes"]),
                                  "nodes": [{key: node[key] for key in ("batch_id", "depth", "status", "error_kind",
                                                                        "unresolved", "attempts")}
                                            for node in row["resolution"]["nodes"]],
                                  "untranslated_ids": [item["id"] for item in row["resolution"]["untranslated"]]}
                                 for row in followed],
            "untranslated": untranslated}
