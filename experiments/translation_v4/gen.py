"""v4 generation: v3 resumable per-scene generation on the v4 sets with seed blocks.

dev: a run ``<recipe>__s<seed>__dev`` contains only the scenes of the seed's block (each dev scene is
generated with one seed; blocks are balanced inside every work). The replicate seeds cover the same
blocks. confirm: every run covers all confirm scenes and needs ``locked-candidates.json`` (v4 root).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from experiments.translation_v3.common import check_locked_candidate, sha256_file
from experiments.translation_v3.data import Cue, Scene
from experiments.translation_v3.generate import SessionFactory, managed_session_factory, run_generation, run_id_for
from experiments.translation_v3.recipes import Recipe, load_recipe

from .common import CONFIRM_SEEDS, DEV_REPLICATE_SEEDS, DEV_SEEDS, set_dir
from .reference import load_scenes


def seed_block(set_name: str, seed: int) -> int | None:
    """Block index for dev seeds (None = all scenes, for confirm)."""
    if set_name == "dev":
        for seeds in (DEV_SEEDS, DEV_REPLICATE_SEEDS):
            if seed in seeds:
                return seeds.index(seed)
        raise ValueError(f"dev seed must be one of {DEV_SEEDS + DEV_REPLICATE_SEEDS}")
    if seed not in CONFIRM_SEEDS:
        raise ValueError(f"confirm seed must be one of {CONFIRM_SEEDS}")
    return None


def set_scenes(root: Path, set_name: str, seed: int) -> tuple[list[Scene], dict[str, Any]]:
    block = seed_block(set_name, seed)
    rows = [r for r in load_scenes(root, set_name) if block is None or r["seed_block"] == block]
    scenes = [Scene(r["scene_id"], tuple(Cue(c["id"], c["text"], c.get("start"), c.get("end")) for c in r["cues"]),
                    r["work_id"], r["category"]) for r in rows]
    sources = {"set": set_name, "scenes_sha256": sha256_file(set_dir(root, set_name) / "scenes.jsonl"),
               "seed_block": block}
    return scenes, sources


def do_generate(root: Path, recipe_name: str, seed: int, set_name: str, *, port: int = 8080,
                break_stale_lock: bool = False, retry_failed: bool = False,
                session_factory: SessionFactory | None = None) -> dict[str, Any]:
    recipe: Recipe = load_recipe(recipe_name, root)
    if set_name == "confirm":
        check_locked_candidate(root, recipe.name, recipe.recipe_hash)
    scenes, sources = set_scenes(root, set_name, seed)
    run_id = run_id_for(recipe, seed, set_name)
    factory = session_factory or managed_session_factory(root, run_id, port=port, break_stale_lock=break_stale_lock)
    run = run_generation(root / "runs" / run_id, recipe, seed, scenes, scope=set_name, sources=sources,
                         session_factory=factory, retry_failed=retry_failed)
    return {"run_id": run_id, "completion": run["completion"], "resumed": run["resumed"],
            "wall_clock_seconds": run.get("wall_clock_seconds")}


def seeds_for(set_name: str, replicate: bool = False) -> tuple[int, ...]:
    if set_name == "confirm":
        return CONFIRM_SEEDS
    return DEV_REPLICATE_SEEDS if replicate else DEV_SEEDS
