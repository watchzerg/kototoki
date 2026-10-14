"""翻译输入：一部影片的 `ja.srt` 即一个场景（复制自 `experiments/translation_v3/data.py` 的 `Scene`／`Cue`）。"""

from __future__ import annotations

from dataclasses import dataclass

from kototoki.srt import SourceDocument


@dataclass(frozen=True)
class Cue:
    id: str
    text: str


@dataclass(frozen=True)
class Scene:
    scene_id: str
    cues: tuple[Cue, ...]

    @property
    def ids(self) -> list[str]:
        return [cue.id for cue in self.cues]


def scene_from_document(document: SourceDocument) -> Scene:
    """场景 ID 取 `srt-<sha12>`（与 v3 `translate-srt` 的 delivery 标签同形），cue ID 是 `<sha8>-cue-<n>` 别名。"""
    return Scene(f"srt-{document.source_sha256[:12]}", tuple(Cue(cue.id, cue.text) for cue in document.cues))
