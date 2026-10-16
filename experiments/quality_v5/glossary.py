"""按作品术语表（票据 10）：第一遍译文 → 每部作品的人名／专名译法 → 注入第二遍翻译的配方。

第一遍用对照配方的已有 run（dev 每个 seed 只覆盖 1／3 场景，3 个 seed 合起来正好覆盖每部作品的全部 dev 场景，
每条 cue 一份译文）。术语与译法沿用 04 的 `consistency.analyze_work`：术语从日文抽（片假名串、汉字名＋敬称，
作品内 ≥3 条 cue），译法取出现处中文里支持最多的特异 n-gram（多数票 R1）；只收 R1 至少出现 2 次的术语。
写出配方 `<root>/recipes/<name>.json`：`{"base": 对照, "glossary": {work_id: [{source, translation}]}}`，术语表内容
进 recipe_hash（v3 `Recipe.glossary`，`work-glossary-v1`）；生成时每批只注入日文上下文里出现的条目。

命令（仓库根目录，`.venv`；离线）：
  python -X utf8 -m experiments.quality_v5.glossary --root ROOT --source b10-joint --name gl10 --report OUT.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from experiments.translation_v3.recipes import load_recipe

from .consistency import DEV_SEEDS, analyze_work, load_set, load_v4_translations, works_from_set

MIN_MAIN = 2


def build_glossary(works: dict[str, list[tuple[str, str]]]) -> dict[str, list[dict[str, str]]]:
    glossary = {}
    for work, cues in sorted(works.items()):
        rows = [{"source": r.term, "translation": r.rendering} for r in analyze_work(cues)
                if r.rendering and r.main >= MIN_MAIN]
        if rows:
            glossary[work] = sorted(rows, key=lambda row: row["source"])
    return glossary


def write_recipe(root: Path, name: str, base: str, glossary: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
    path = root / "recipes" / f"{name}.json"
    path.write_text(json.dumps({"name": name, "base": base, "glossary": glossary,
                                "comment": f"v5 step 10: per-work glossary from {base} dev translations"},
                               ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    recipe = load_recipe(name, root)
    return {"recipe": name, "recipe_hash": recipe.recipe_hash, "works": len(glossary),
            "entries": {work: len(rows) for work, rows in glossary.items()}}


def main() -> int:
    parser = argparse.ArgumentParser(description="按作品术语表（票据 10）")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source", default="b10-joint", help="第一遍译文所用的配方（dev 3 seed 已有 run）")
    parser.add_argument("--name", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    works, _ = works_from_set(load_set(args.root, "dev"), load_v4_translations(args.root, args.source, DEV_SEEDS))
    report = write_recipe(args.root, args.name, args.source, build_glossary(works))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
