"""Scene batching in source order from cue 0 with read-only neighbours.

Packing matches v2 ``v2_prepare.pack_scene`` (offset 0, no common context); a test
compares both. A single cue above the token target stays intact and is flagged.

``recipe.gap_split`` (v6, ``gap-split-v1``) moves count cuts to nearby silence gaps (``gap_cuts``)
and keeps a read-only neighbour only while the silence towards it is below ``context_gap``.

``recipe.gap_pack`` (v7, ``gap-pack-v1``) chooses all cuts of a scene at once by dynamic programming
(``gap_pack_cuts``); ``gap-pack-v2`` (ADR-0010) adds a per-cut penalty by the silence at the cut
(``cut_penalty``). ``recipe.pause_marks`` (v7) records the visible silences that get a pause line.

``recipe.groups`` (v8, ``group-reorder-v1``) splits each pack's targets into "same sentence" groups
(``sentence_groups``, rule R2+) and records the groups of two or more cues for the prompt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .data import Scene
from .recipes import Recipe

# group-reorder-v1 (v8): sentence-end marks and the closers stripped before checking them.
SENTENCE_END = "。？！?!."
CLOSERS = "」』）)】〕\"'”’"


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
    # (index into the visible list, seconds): a pause line goes before that visible cue (pause_marks).
    pauses: tuple[tuple[int, float], ...] = ()
    # Target-ID sentence groups of >= 2 cues (groups recipes); empty: the batch renders as without groups.
    groups: tuple[tuple[str, ...], ...] = ()

    def to_window(self, scene: Scene) -> dict[str, Any]:
        text = {cue.id: cue.text for cue in scene.cues}
        visible = self.before_ids + self.target_ids + self.after_ids
        return {"id": self.batch_id, "source_language": "ja", "target_language": "zh-Hans",
                "context": [{"id": key, "text": text[key]} for key in visible],
                "translate_ids": list(self.target_ids)}

    def record(self) -> dict[str, Any]:
        row = {"index": self.index, "batch_id": self.batch_id, "target_ids": list(self.target_ids),
               "before_ids": list(self.before_ids), "after_ids": list(self.after_ids),
               "start": self.start, "stop": self.stop, "source_token_count": self.source_token_count,
               "single_cue_over_token_target": self.single_cue_over_token_target}
        if self.pauses:
            row["pauses"] = [list(p) for p in self.pauses]
        if self.groups:
            row["groups"] = [list(g) for g in self.groups]
        return row


def silence(scene: Scene, i: int) -> float | None:
    """Seconds between cue i and cue i+1 (None when a timestamp is missing)."""
    left, right = scene.cues[i], scene.cues[i + 1]
    return None if left.end is None or right.start is None else right.start - left.end


def line_tail(text: str, strip_closers: bool = True) -> str:
    """Last character after trailing whitespace (and, optionally, closing brackets/quotes); "" if none."""
    text = text.rstrip(" 　")
    while strip_closers and text and text[-1] in CLOSERS:
        text = text[:-1].rstrip(" 　")
    return text[-1] if text else ""


def ends_sentence(text: str) -> bool:
    """R2+ sentence end: 。？！?!. after stripping trailing whitespace and closers; … and 、 are not ends."""
    char = line_tail(text)
    return bool(char) and char in SENTENCE_END


def sentence_joined(scene: Scene, i: int, gap: float) -> bool:
    """R2+ (group-reorder-v1): cue i and i+1 belong to one sentence group when the silence is < gap
    (overlap counts, a missing timestamp counts as no silence) and cue i does not end a sentence."""
    silent = silence(scene, i)
    return (silent is None or silent < gap) and not ends_sentence(scene.cues[i].text)


def sentence_groups(scene: Scene, low: int, high: int, gap: float) -> list[tuple[int, int]]:
    """R2+ sentence groups [a, b) inside [low, high) (a pack's targets); no size limit."""
    out, a = [], low
    for i in range(low, high - 1):
        if not sentence_joined(scene, i, gap):
            out.append((a, i + 1))
            a = i + 1
    return out + [(a, high)]


def gap_cuts(scene: Scene, target: int, split: dict[str, Any]) -> list[int]:
    """Batch starts under gap-split-v1: the plain count grid (target, 2*target, ...) with each grid
    point moved to the largest silence >= cut_gap within +-snap cues (ties: nearest to the grid point,
    then earlier). A move is allowed only while no batch exceeds ``max`` cues; otherwise the grid point
    stays. Batch count therefore equals plain count batching, and unchanged grid points keep their
    batches."""
    n = len(scene.cues)
    cuts = [0]
    for grid in range(target, n, target):
        prev, best, best_key = cuts[-1], grid, None
        last = grid + target >= n
        for cut in range(max(prev + 1, grid - split["snap"]), min(grid + split["snap"], n - 1) + 1):
            if cut - prev > split["max"] or (last and n - cut > split["max"]):
                continue
            gap = silence(scene, cut - 1)
            if gap is None or gap < split["cut_gap"]:
                continue
            key = (gap, -abs(cut - grid), -cut)
            if best_key is None or key > best_key:
                best, best_key = cut, key
        cuts.append(best)
    return cuts


def gap_groups(scene: Scene, group_gap: float, group_max: int, target: int) -> list[int]:
    """Starts of the gap-pack-v1 groups: runs of cues whose silences are all < group_gap (a missing
    timestamp counts as no silence). A group longer than group_max is split into ceil(n/target)
    near-equal parts, longer parts first."""
    n = len(scene.cues)
    runs = [0] + [i + 1 for i in range(n - 1) if (gap := silence(scene, i)) is not None and gap >= group_gap]
    starts = []
    for a, b in zip(runs, runs[1:] + [n]):
        size = b - a
        parts = -(-size // target) if size > group_max else 1
        base, extra = divmod(size, parts)
        for k in range(parts):
            starts.append(a)
            a += base + (k < extra)
    return starts


def gap_pack_cuts(scene: Scene, target: int, pack: dict[str, Any]) -> list[int]:
    """Batch starts under gap-pack-v1: the cut set with the lowest total penalty, found by dynamic
    programming over the scene. A batch [a, b) costs (b - a - target)**2, plus small_penalty when it is
    shorter than ``min``, plus soft_weight * gap for every silence gap >= soft_gap between two of its
    cues; it is infeasible above ``max`` cues or with a silence >= hard_gap inside. With group_gap set,
    cuts fall only on gap_groups starts. With cut_penalty (gap-pack-v2) every inner cut also costs the
    penalty of the first tier whose bound exceeds the silence at the cut (a missing timestamp: the first
    tier). Ties keep the earliest-found (shortest last batch) solution."""
    n = len(scene.cues)
    allowed = set(gap_groups(scene, pack["group_gap"], pack["group_max"], target)) if pack["group_gap"] else set(range(n))
    allowed.add(n)
    gaps = [silence(scene, i) for i in range(n - 1)]
    tiers = pack.get("cut_penalty", ())
    best: list[tuple[float, int] | None] = [None] * (n + 1)
    best[0] = (0.0, -1)
    for stop in range(1, n + 1):
        if stop not in allowed:
            continue
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
            if start not in allowed or best[start] is None:
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


def _pack_neighbours(scene: Scene, start: int, stop: int, recipe: Recipe) -> tuple[int, int]:
    """gap-pack-v1 neighbours: the cue before is visible while its silence is < context_before_below,
    the cue after only while its silence is < context_both_below (a missing timestamp counts as no
    silence); above max_visible the after-side goes first."""
    pack, n = recipe.gap_pack, len(scene.cues)
    def below(i: int, limit: float) -> bool:
        gap = silence(scene, i)
        return gap is None or gap < limit
    left, right = start, stop
    while left > max(0, start - recipe.context_before) and below(left - 1, pack["context_before_below"]):
        left -= 1
    while right < min(n, stop + recipe.context_after) and below(right - 1, pack["context_both_below"]):
        right += 1
    while right - left > pack["max_visible"] and right > stop:
        right -= 1
    while right - left > pack["max_visible"] and left < start:
        left += 1
    return left, right


def visible_pauses(scene: Scene, left: int, right: int, min_gap: float) -> tuple[tuple[int, float], ...]:
    """(visible index, seconds) for every silence >= min_gap between two visible cues of [left, right)."""
    return tuple((i + 1 - left, round(gap, 3)) for i in range(left, right - 1)
                 if (gap := silence(scene, i)) is not None and gap >= min_gap)


def _neighbours(scene: Scene, start: int, stop: int, recipe: Recipe) -> tuple[int, int]:
    """[left, right) visible range; with gap_split, neighbours stop at a gap >= context_gap and the
    after-side is dropped first while more than max_visible cues would be visible."""
    n = len(scene.cues)
    if recipe.gap_pack is not None:
        return _pack_neighbours(scene, start, stop, recipe)
    left, right = max(0, start - recipe.context_before), min(n, stop + recipe.context_after)
    split = recipe.gap_split
    if split is None:
        return left, right
    if split["context_gap"] is not None:
        def near(i: int) -> bool:
            gap = silence(scene, i)
            return gap is None or gap < split["context_gap"]
        low = start
        while low > left and near(low - 1):
            low -= 1
        high = stop
        while high < right and near(high - 1):
            high += 1
        left, right = low, high
    while right - left > split["max_visible"] and right > stop:
        right -= 1
    while right - left > split["max_visible"] and left < start:
        left += 1
    return left, right


def build_batches(scene: Scene, recipe: Recipe, token_counts: dict[str, int] | None = None) -> list[Batch]:
    ids = scene.ids
    if not ids or len(ids) != len(set(ids)):
        raise ValueError(f"Empty or duplicate cue IDs in scene {scene.scene_id}")
    if recipe.token_target is not None:
        if token_counts is None or any(type(token_counts.get(key)) is not int or token_counts[key] < 1 for key in ids):
            raise ValueError("Token batching needs a positive measured count for every cue")
    batches: list[Batch] = []
    cuts = gap_cuts(scene, recipe.batch_count, recipe.gap_split) + [len(ids)] if recipe.gap_split else None
    if recipe.gap_pack:
        cuts = gap_pack_cuts(scene, recipe.batch_count, recipe.gap_pack) + [len(ids)]
    start = 0
    while start < len(ids):
        if cuts is not None:
            stop = cuts[len(batches) + 1]
        elif recipe.token_target is None:
            stop = min(len(ids), start + recipe.batch_count)
        else:
            stop, total = start, 0
            while stop < len(ids):
                count = token_counts[ids[stop]]
                if stop > start and total + count > recipe.token_target:
                    break
                total += count
                stop += 1
        left, right = _neighbours(scene, start, stop, recipe)
        targets = tuple(ids[start:stop])
        batches.append(Batch(
            index=len(batches), batch_id=f"{scene.scene_id}-b{len(batches) + 1:04d}", scene_id=scene.scene_id,
            target_ids=targets, before_ids=tuple(ids[left:start]), after_ids=tuple(ids[stop:right]),
            start=start, stop=stop,
            source_token_count=sum(token_counts[k] for k in targets) if token_counts else None,
            single_cue_over_token_target=bool(recipe.token_target and len(targets) == 1
                                              and token_counts[targets[0]] > recipe.token_target),
            pauses=visible_pauses(scene, left, right, recipe.pause_marks["min_gap"]) if recipe.pause_marks else (),
            groups=tuple(tuple(ids[a:b]) for a, b in sentence_groups(scene, start, stop, recipe.groups["gap"])
                         if b - a > 1) if recipe.groups else ()))
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
