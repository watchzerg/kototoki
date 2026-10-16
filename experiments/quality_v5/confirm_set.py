"""v5 剧集确认集（票据 07）：在评测库 v2 里选 v2／v3 与 v4 dev／confirm 都没碰过的整集，按 v4 规则切段。

电影已被 v4 confirm 用尽（M05 隔离），所以只建剧集：每部剧集作品 EPISODES 集、每集一段 LENGTH 条连续 cue。
选段只看目录元数据与 cue 数（固定 seed 的 RNG），文本只用于写模型输入与参考复核输入（`evaluation-only/confirm`，
不打印）。切段、对齐检查、seed 块／半区分配与写盘全部复用 v4 `build_sets` 的函数；manifest 的 selection 改记 v5 规则。
集合写入 `ROOT/sets/confirm`，已存在且内容不同则拒绝覆盖（v4 `_write_set` 的行为）。

命令（仓库根目录，`.venv`；离线）：
  python -X utf8 -m experiments.quality_v5.confirm_set --root ROOT
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import random
from typing import Any

from experiments.translation_v3.common import atomic_write_json, read_json
from experiments.translation_v4 import build_sets as B
from experiments.translation_v4 import inventory as inv

V4_ROOT = Path(".local/translation-evaluation/hy30-flow-v4")
SEED = "v5-confirm-selection-20261016"
EPISODES = 2
LENGTH = 120
RULE = __doc__


def v4_sources(v4_root: Path) -> set[str]:
    """v4 dev 与 confirm 用过的 ja.srt（整集视为已用）。"""
    keys = set()
    for name in ("dev", "confirm"):
        for line in (v4_root / "sets" / name / "scenes.jsonl").read_text(encoding="utf-8").splitlines():
            keys.add(inv._key(json.loads(line)["source_ja_srt"]))
    return keys


def select(used: dict[str, list], sources: list[inv.Source], episodes: int = EPISODES) -> list[dict[str, Any]]:
    by_work: dict[str, list[inv.Source]] = defaultdict(list)
    for source in sources:
        by_work[source.work_id].append(source)
    rng = random.Random(SEED)
    scenes = []
    for work in sorted(w for w in by_work if w.startswith("W")):
        scenes += [s | {"origin": "v5-new"} for s in
                   B._pick_episode_segments(rng, "V5C", by_work[work], episodes, LENGTH, used)]
    return scenes


def build(root: Path, v4_root: Path = V4_ROOT) -> dict[str, Any]:
    used = inv.used_ranges()
    for key in v4_sources(v4_root):
        used.setdefault(key, []).append((0, 10**9, "v4 set"))
    scenes = select(used, inv.sources())
    for scene in scenes:
        if used.get(inv._key(scene["source_ja_srt"])):
            raise ValueError(f"{scene['scene_id']} comes from a used episode")
    B._assign_blocks(scenes)
    result = B._write_set(root, "confirm", scenes)
    manifest_path = root / "sets" / "confirm" / "manifest.json"
    manifest = read_json(manifest_path)
    manifest["selection"] = {"seed": SEED, "confirm_episodes": EPISODES, "confirm_length": LENGTH,
                             "edge_fraction": B.EDGE_FRACTION, "excluded": "v2/v3 ranges, historical fixed sets, "
                             "every episode used by v4 dev or confirm", "rule": RULE}
    atomic_write_json(manifest_path, manifest)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="v5 剧集确认集（票据 07）")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--v4-root", type=Path, default=V4_ROOT)
    args = parser.parse_args()
    print(json.dumps(build(args.root, args.v4_root), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
