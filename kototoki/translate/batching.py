"""按源顺序从第 0 条起分批，前后带只读邻文（复制自 `experiments/translation_v3/batching.py`，只留按条数分批）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .data import Scene
from .recipes import Recipe


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


def build_batches(scene: Scene, recipe: Recipe) -> list[Batch]:
    ids = scene.ids
    if not ids or len(ids) != len(set(ids)):
        raise ValueError(f"Empty or duplicate cue IDs in scene {scene.scene_id}")
    batches: list[Batch] = []
    start = 0
    while start < len(ids):
        stop = min(len(ids), start + recipe.batch_count)
        left = max(0, start - recipe.context_before)
        right = min(len(ids), stop + recipe.context_after)
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
