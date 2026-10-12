"""Inventory of the external evaluation library: which source SRT cue ranges are already used.

Read-only. "Used" = visible context of any v2/v3 screening or confirmation scene (source-manifest
``visible_start_index``..``visible_end_index``, 1-based SRT numbers of the cleaned ``ja.srt``), the
historical fixed-set episodes (anime: whole episode excluded) and the historical fixed movie windows
(pair-rank ranges). New v4 segments must avoid every used range (plus a margin).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from experiments.translation_v3.common import V2_ROOT, read_json, sha256_file

LIBRARY = Path(r"D:\subtitle-samples\翻译模型评估库_v2")
ANIME_DIR = LIBRARY / "动画v1"
MOVIE_DIR = LIBRARY / "电影补充"
MOVIE_WORKS = {"M01": "Sword Art Online The Movie Progressive - Aria of a Starless Night (2021)",
               "M02": "Sword Art Online the Movie Progressive - Scherzo of Deep Night (2022)",
               "M03": "Suzume (2022)", "M04": "The Birth of Kitarou Mystery of GeGeGe (2023)"}
# M05 (Weathering With You) is quarantined in the library (broken Japanese track): never used.
V2_MANIFESTS = (V2_ROOT / "source/screening-qualified-v1/source-manifest.json",
                V2_ROOT / "evaluation-only/reference-v1/source-manifest-confirmation.json",
                V2_ROOT / "evaluation-only/reference-v1/source-manifest.json")
TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


@dataclass(frozen=True)
class SrtCue:
    index: int  # 0-based position in the file
    start: float
    end: float
    text: str


def read_srt(path: Path) -> list[SrtCue]:
    blocks = re.split(r"\r?\n\s*\r?\n", Path(path).read_text(encoding="utf-8-sig").strip())
    cues = []
    for block in blocks:
        lines = block.splitlines()
        timing = next((i for i, line in enumerate(lines) if TIME.search(line)), None)
        if timing is None:
            raise ValueError(f"No timing line in a block of {path}")
        h1, m1, s1, f1, h2, m2, s2, f2 = TIME.search(lines[timing]).groups()
        start = int(h1) * 3600 + int(m1) * 60 + int(s1) + int(f1) / 1000
        end = int(h2) * 3600 + int(m2) * 60 + int(s2) + int(f2) / 1000
        cues.append(SrtCue(len(cues), start, end, "\n".join(lines[timing + 1:]).strip()))
    return cues


@dataclass(frozen=True)
class Source:
    source_id: str  # episode id (W01_E001) or movie id (M01)
    work_id: str
    work: str
    category: str
    ja_srt: Path
    zh_srt: Path


def sources() -> list[Source]:
    rows = list(csv.DictReader((ANIME_DIR / "作品与集目录.csv").open(encoding="utf-8-sig")))
    result = []
    for row in rows:
        folder = ANIME_DIR / "清洗候选" / row["作品ID"] / row["集ID"]
        result.append(Source(row["集ID"], row["作品ID"], row["作品"], "anime_series", folder / "ja.srt", folder / "zh.srt"))
    for work_id, work in MOVIE_WORKS.items():
        folder = MOVIE_DIR / work_id / "清洗候选"
        result.append(Source(work_id, work_id, work, "animation_movie", folder / "ja.srt", folder / "zh.srt"))
    return result


def _key(path: str | Path) -> str:
    return str(Path(path)).lower()


def used_ranges() -> dict[str, list[tuple[int, int, str]]]:
    """source ja.srt path (lowercased) -> [(first, last, why)] inclusive 0-based cue indices."""
    used: dict[str, list[tuple[int, int, str]]] = {}
    for manifest in V2_MANIFESTS:
        for row in read_json(manifest)["windows"]:
            path = row["source_srt"]
            if not Path(path).is_absolute():
                path = LIBRARY / path
            used.setdefault(_key(path), []).append((row["visible_start_index"] - 1, row["visible_end_index"] - 1,
                                                    f"v2/v3 {row['split']} {row['scene_id']}"))
    historical = read_json(ANIME_DIR / "固定评测集/来源清单.json")
    by_sha = {row["sha256"]: row for row in historical}
    catalog = list(csv.DictReader((ANIME_DIR / "作品与集目录.csv").open(encoding="utf-8-sig")))
    for row in catalog:
        if row["选用SHA256"] in by_sha:
            folder = ANIME_DIR / "清洗候选" / row["作品ID"] / row["集ID"]
            used.setdefault(_key(folder / "ja.srt"), []).append((0, 10**9, f"historical fixed set ({by_sha[row['选用SHA256']]['split']})"))
    for movie in read_json(MOVIE_DIR / "电影抽样.json"):
        path = MOVIE_DIR / movie["work_id"] / "清洗候选" / "ja.srt"
        for window in movie["windows"]:
            low, high = window["source_context_pair_rank_range"]
            used.setdefault(_key(path), []).append((low - 1, high - 1, f"historical movie window {window['window_id']}"))
    return used


def free_runs(n_cues: int, ranges: list[tuple[int, int, str]], margin: int,
              historical_margin: int | None = None) -> list[tuple[int, int]]:
    """Maximal [start, stop) 0-based runs not within ``margin`` of any v2/v3 range (historical
    fixed-set ranges use ``historical_margin``, default ``margin``)."""
    blocked = [False] * n_cues
    for low, high, why in ranges:
        pad = historical_margin if historical_margin is not None and why.startswith("historical") else margin
        for i in range(max(0, low - pad), min(n_cues, high + pad + 1)):
            blocked[i] = True
    runs, start = [], None
    for i, b in enumerate(blocked + [True]):
        if not b and start is None:
            start = i
        elif b and start is not None:
            runs.append((start, i))
            start = None
    return runs


def summary(margin: int = 20) -> list[dict[str, Any]]:
    used = used_ranges()
    rows = []
    for source in sources():
        cues = read_srt(source.ja_srt)
        runs = free_runs(len(cues), used.get(_key(source.ja_srt), []), margin)
        rows.append({"source_id": source.source_id, "work_id": source.work_id, "category": source.category,
                     "cues": len(cues), "used_ranges": len(used.get(_key(source.ja_srt), [])),
                     "free_cues": sum(b - a for a, b in runs), "free_runs": runs})
    return rows


if __name__ == "__main__":
    from collections import defaultdict
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for row in summary():
        t = totals[row["work_id"]]
        t[0] += 1
        t[1] += row["cues"]
        t[2] += row["free_cues"]
        t[3] += row["used_ranges"] > 0
    for work, (n, cues, free, touched) in sorted(totals.items()):
        print(f"{work}: sources {n} (touched {touched}), cues {cues}, free {free}")
