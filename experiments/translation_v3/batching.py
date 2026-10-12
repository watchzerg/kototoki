"""Scene batching in source order from cue 0 with read-only neighbours.

Packing matches v2 ``v2_prepare.pack_scene`` (offset 0, no common context); a test
compares both. A single cue above the token target stays intact and is flagged.
"""

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
    source_token_count: int | None = None
    single_cue_over_token_target: bool = False

    def to_window(self, scene: Scene) -> dict[str, Any]:
        text = {cue.id: cue.text for cue in scene.cues}
        visible = self.before_ids + self.target_ids + self.after_ids
        return {"id": self.batch_id, "source_language": "ja", "target_language": "zh-Hans",
                "context": [{"id": key, "text": text[key]} for key in visible],
                "translate_ids": list(self.target_ids)}

    def record(self) -> dict[str, Any]:
        return {"index": self.index, "batch_id": self.batch_id, "target_ids": list(self.target_ids),
                "before_ids": list(self.before_ids), "after_ids": list(self.after_ids),
                "start": self.start, "stop": self.stop, "source_token_count": self.source_token_count,
                "single_cue_over_token_target": self.single_cue_over_token_target}


def build_batches(scene: Scene, recipe: Recipe, token_counts: dict[str, int] | None = None) -> list[Batch]:
    ids = scene.ids
    if not ids or len(ids) != len(set(ids)):
        raise ValueError(f"Empty or duplicate cue IDs in scene {scene.scene_id}")
    if recipe.token_target is not None:
        if token_counts is None or any(type(token_counts.get(key)) is not int or token_counts[key] < 1 for key in ids):
            raise ValueError("Token batching needs a positive measured count for every cue")
    batches: list[Batch] = []
    start = 0
    while start < len(ids):
        if recipe.token_target is None:
            stop = min(len(ids), start + recipe.batch_count)
        else:
            stop, total = start, 0
            while stop < len(ids):
                count = token_counts[ids[stop]]
                if stop > start and total + count > recipe.token_target:
                    break
                total += count
                stop += 1
        left = max(0, start - recipe.context_before)
        right = min(len(ids), stop + recipe.context_after)
        targets = tuple(ids[start:stop])
        batches.append(Batch(
            index=len(batches), batch_id=f"{scene.scene_id}-b{len(batches) + 1:04d}", scene_id=scene.scene_id,
            target_ids=targets, before_ids=tuple(ids[left:start]), after_ids=tuple(ids[stop:right]),
            start=start, stop=stop,
            source_token_count=sum(token_counts[k] for k in targets) if token_counts else None,
            single_cue_over_token_target=bool(recipe.token_target and len(targets) == 1
                                              and token_counts[targets[0]] > recipe.token_target)))
        start = stop
    return batches


def cue_positions(batches: list[Batch]) -> dict[str, dict[str, Any]]:
    """Map every target cue to its batch index and position (first/mid/last, or single)."""
    result = {}
    for batch in batches:
        last = len(batch.target_ids) - 1
        for offset, key in enumerate(batch.target_ids):
            position = "single" if last == 0 else "first" if offset == 0 else "last" if offset == last else "mid"
            result[key] = {"batch_index": batch.index, "position": position, "offset": offset,
                           "batch_size": last + 1}
    return result
