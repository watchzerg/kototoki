"""翻译输入与分批：一部影片的 `ja.srt` 即一个场景（`Scene`／`Cue` 复制自 `experiments/translation_v3/data.py`），
前后带只读邻文。两种切法（复制自 `translation_v3/batching.py`，由 `recipe.gap_pack` 选择）：

- 按条数：从第 0 条起每批 `batch_count` 条、前后各 `context_before`／`context_after` 条邻文（`b10-joint`）；
- gap-pack-v2（`dp10-cut`，ADR-0010）：整个场景用动态规划取总惩罚最低的切法（`gap_pack_cuts`），邻文按与
  批次之间的停顿取舍（`neighbours`）。停顿取自 `ja.srt` 自身的时间轴（秒），只用于比较长短，不做任何坐标换算。

`source_key` 是翻译子系统对一份 `ja.srt` 的唯一键 `srt-<sha12>`：既是场景 ID（与 v3 `translate-srt` 的 delivery
标签同形），也是 run 目录在 `translate/` 下的分键，只在这里拼一次。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kototoki.srt import SourceDocument

from .recipes import Recipe


def source_key(ja_srt_sha256: str) -> str:
    return f"srt-{ja_srt_sha256[:12]}"


@dataclass(frozen=True)
class Cue:
    id: str
    text: str
    start: float | None = None
    end: float | None = None


@dataclass(frozen=True)
class Scene:
    scene_id: str
    cues: tuple[Cue, ...]

    @property
    def ids(self) -> list[str]:
        return [cue.id for cue in self.cues]


def scene_from_document(document: SourceDocument) -> Scene:
    """场景 ID 取 `source_key`，cue ID 是 `srt.py` 的 `<sha8>-cue-<n>` 别名，时间与 v3 `translate-srt` 同样取秒。"""
    return Scene(source_key(document.source_sha256),
                 tuple(Cue(cue.id, cue.text, cue.start_ms / 1000, cue.end_ms / 1000) for cue in document.cues))


@dataclass(frozen=True)
class Batch:
    index: int
    batch_id: str
    scene_id: str
    target_ids: tuple[str, ...]
    before_ids: tuple[str, ...]
    after_ids: tuple[str, ...]
    start: int
    stop: int

    def to_window(self, scene: Scene) -> dict[str, Any]:
        text = {cue.id: cue.text for cue in scene.cues}
        visible = self.before_ids + self.target_ids + self.after_ids
        return {"id": self.batch_id, "source_language": "ja", "target_language": "zh-Hans",
                "context": [{"id": key, "text": text[key]} for key in visible],
                "translate_ids": list(self.target_ids)}

    def record(self) -> dict[str, Any]:
        return {"index": self.index, "batch_id": self.batch_id, "target_ids": list(self.target_ids),
                "before_ids": list(self.before_ids), "after_ids": list(self.after_ids),
                "start": self.start, "stop": self.stop}


def silence(scene: Scene, i: int) -> float | None:
    """第 i 条与第 i+1 条之间的停顿（秒）；缺时间戳为 None，重叠为负。"""
    left, right = scene.cues[i], scene.cues[i + 1]
    return None if left.end is None or right.start is None else right.start - left.end


def gap_pack_cuts(scene: Scene, target: int, pack: dict[str, Any]) -> list[int]:
    """gap-pack-v2 的批次起点：对整个场景动态规划，取总惩罚最低的切法。

    一个批次 [a, b) 的代价 = (b − a − target)² ＋ 条数 < `min` 时的 `small_penalty` ＋ 批内每个 ≥ `soft_gap` 的停顿
    按 `soft_weight` × 秒数；超过 `max` 条或批内有 ≥ `hard_gap` 的停顿不可行。每个内部切点另加 `cut_penalty` 中
    第一个 `停顿 < below` 档的罚分（缺时间戳按第一档）。同分取先找到的解（最后一批最短）。
    """
    n = len(scene.cues)
    gaps = [silence(scene, i) for i in range(n - 1)]
    tiers = pack["cut_penalty"]
    best: list[tuple[float, int] | None] = [None] * (n + 1)
    best[0] = (0.0, -1)
    for stop in range(1, n + 1):
        at_cut = gaps[stop - 1] if stop < n else None
        cut = 0.0 if stop == n else next((p for below, p in tiers if at_cut is None or at_cut < below), 0.0)
        inner = 0.0
        for start in range(stop - 1, max(-1, stop - pack["max"] - 1), -1):
            if start < stop - 1:
                gap = gaps[start]
                if gap is not None and gap >= pack["hard_gap"]:
                    break
                if gap is not None and gap >= pack["soft_gap"]:
                    inner += pack["soft_weight"] * gap
            if best[start] is None:
                continue
            size = stop - start
            cost = (best[start][0] + (size - target) ** 2 + (pack["small_penalty"] if size < pack["min"] else 0)
                    + inner + cut)
            if best[stop] is None or cost < best[stop][0]:
                best[stop] = (cost, start)
    if best[n] is None:
        raise ValueError(f"gap_pack: no feasible cut set for scene {scene.scene_id}")
    cuts, at = [], n
    while at > 0:
        at = best[at][1]
        cuts.append(at)
    return cuts[::-1]


def neighbours(scene: Scene, start: int, stop: int, recipe: Recipe) -> tuple[int, int]:
    """待译 [start, stop) 的可见范围 [left, right)。按条数分批时前后各取 `context_before`／`context_after` 条；
    gap-pack 时前一条只在停顿 < `context_before_below` 时可见、后一条只在停顿 < `context_both_below` 时可见
    （缺时间戳按无停顿），可见总数超过 `max_visible` 时先去后邻、再去前邻。降级的子批次用同一规则。"""
    n = len(scene.cues)
    left, right = max(0, start - recipe.context_before), min(n, stop + recipe.context_after)
    pack = recipe.gap_pack
    if pack is None:
        return left, right

    def below(i: int, limit: float) -> bool:
        gap = silence(scene, i)
        return gap is None or gap < limit

    low, high = start, stop
    while low > left and below(low - 1, pack["context_before_below"]):
        low -= 1
    while high < right and below(high - 1, pack["context_both_below"]):
        high += 1
    while high - low > pack["max_visible"] and high > stop:
        high -= 1
    while high - low > pack["max_visible"] and low < start:
        low += 1
    return low, high


def build_batches(scene: Scene, recipe: Recipe) -> list[Batch]:
    ids = scene.ids
    if not ids or len(ids) != len(set(ids)):
        raise ValueError(f"Empty or duplicate cue IDs in scene {scene.scene_id}")
    cuts = gap_pack_cuts(scene, recipe.batch_count, recipe.gap_pack) + [len(ids)] if recipe.gap_pack else None
    batches: list[Batch] = []
    start = 0
    while start < len(ids):
        stop = cuts[len(batches) + 1] if cuts is not None else min(len(ids), start + recipe.batch_count)
        left, right = neighbours(scene, start, stop, recipe)
        batches.append(Batch(
            index=len(batches), batch_id=f"{scene.scene_id}-b{len(batches) + 1:04d}", scene_id=scene.scene_id,
            target_ids=tuple(ids[start:stop]), before_ids=tuple(ids[left:start]), after_ids=tuple(ids[stop:right]),
            start=start, stop=stop))
        start = stop
    return batches


def cue_positions(batches: list[Batch]) -> dict[str, dict[str, Any]]:
    """每条待译 cue 所在批次与批内位置（first/mid/last，或 single）。"""
    result = {}
    for batch in batches:
        last = len(batch.target_ids) - 1
        for offset, key in enumerate(batch.target_ids):
            position = "single" if last == 0 else "first" if offset == 0 else "last" if offset == last else "mid"
            result[key] = {"batch_index": batch.index, "position": position, "offset": offset,
                           "batch_size": last + 1}
    return result
