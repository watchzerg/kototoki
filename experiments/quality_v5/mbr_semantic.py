"""语义效用 MBR（票据 08）：同一批 mbr8 样本，只把逐条 MBR 的效用从 chrF 换成 embedding 余弦相似度。

embedding 用本地 `BAAI/bge-m3`（dense，CLS 池化后 L2 归一化；权重与 sha256 见
`.local/models/embedding-v5/bge-m3-ready.json`）。每条 cue 取前 n 个成功样本，选与其余样本平均余弦最高的一个，
并列取最小序号（同 v3 `mbr_index`）。不新增生成：v3 配方只接受 chrF 选择器，所以伪 run
`<name>__s<seed>__<scope>` 沿用同一基准 run、同 n 的逐条 chrF 派生配方（name 末尾 s 换成 c，如 mbr8s → mbr8c、
t03mbr8s → t03mbr8c）与其 hash（只换 name，同 07 的早停伪 run），`pseudo.kind` 记为
`semantic-selection`、`pseudo.selector` 记语义选择器名，并记与该 chrF 逐条选择选中文本不同的 cue 比例和选择器耗时。

命令（仓库根目录，`.venv`；embedding 用 GPU，约 2.3 GB 权重）：
  python -X utf8 -m experiments.quality_v5.mbr_semantic --root ROOT --n 8 --name mbr8s [--base mbr8] [--scope dev]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from typing import Any, Callable

from experiments.translation_v3.common import atomic_write_json, read_json, utc_now
from experiments.translation_v3.mbr import select

from .mbr_cheap import BASE, SELECTOR as CHRF_SELECTOR, base_runs, batch_samples

MODEL_DIR = Path(".local/models/embedding-v5/bge-m3")
SELECTOR = "mbr-emb-bge-m3-cue"


def mbr_index(vectors: list[list[float]]) -> int:
    """与其余样本平均余弦（向量已归一化，即点积）最高者；并列取最小序号。"""
    if len(vectors) == 1:
        return 0
    scores = []
    for i, v in enumerate(vectors):
        scores.append(sum(sum(a * b for a, b in zip(v, u)) for j, u in enumerate(vectors) if j != i) / (len(vectors) - 1))
    return scores.index(max(scores))


def load_encoder(model_dir: Path = MODEL_DIR, device: str = "cuda") -> Callable[[list[str]], list[list[float]]]:
    import torch
    from transformers import AutoModel, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModel.from_pretrained(model_dir, torch_dtype=torch.float16).to(device).eval()

    def encode(texts: list[str]) -> list[list[float]]:
        out = []
        with torch.inference_mode():
            for start in range(0, len(texts), 128):
                batch = tokenizer(texts[start:start + 128], padding=True, truncation=True, max_length=256,
                                  return_tensors="pt").to(device)
                cls = model(**batch).last_hidden_state[:, 0].float()
                out += torch.nn.functional.normalize(cls, dim=-1).cpu().tolist()
        return out

    return encode


def derive_semantic(root: Path, base_run: Path, name: str, n: int,
                    encode: Callable[[list[str]], list[list[float]]]) -> dict[str, Any]:
    from experiments.translation_v3.recipes import load_recipe
    from experiments.translation_v4.derive import derived_recipe

    run = read_json(base_run / "run.json")
    recipe = derived_recipe(load_recipe(run["recipe"]["name"], root), name[:-1] + "c", n, CHRF_SELECTOR)
    total = run["recipe"]["recipe"]["candidates"]
    run_id = f"{name}__s{run['seed']}__{run['scope']}"
    out = root / "runs" / run_id
    rows = {scene_id: read_json(base_run / "scenes" / f"{scene_id}.json") for scene_id in run["scene_ids"]}
    texts = sorted({s[key] for row in rows.values() if row["status"] == "complete" for batch in row["batches"]
                    for k, s in batch_samples(row, batch, total) if k < n for key in batch["target_ids"]})
    started = time.perf_counter()
    vectors = dict(zip(texts, encode(texts)))
    embed_seconds = time.perf_counter() - started
    cues = differ = 0
    for scene_id, row in rows.items():
        if row["status"] != "complete":
            atomic_write_json(out / "scenes" / f"{scene_id}.json", {
                "scene_id": scene_id, "status": "failed", "cue_ids": row["cue_ids"], "translations": {},
                "failure": row.get("failure"), "run_id": run_id})
            continue
        translations: dict[str, str] = {}
        for batch in row["batches"]:
            ids = batch["target_ids"]
            samples = [s for k, s in batch_samples(row, batch, total) if k < n]
            chrf_pick, _ = select(CHRF_SELECTOR, samples, ids)
            for key in ids:
                texts_k = [s[key] for s in samples]
                translations[key] = texts_k[mbr_index([vectors[t] for t in texts_k])]
                cues += 1
                differ += translations[key] != chrf_pick[key]
        atomic_write_json(out / "scenes" / f"{scene_id}.json", {
            "scene_id": scene_id, "status": "complete", "cue_ids": row["cue_ids"], "translations": translations,
            "run_id": run_id})
    seconds = sum(a.get("elapsed_seconds") or 0 for row in rows.values() for r in row.get("requests", [])
                  if r.get("sample", 0) < n for a in r.get("attempts", []))
    atomic_write_json(out / "run.json", {
        "schema": run["schema"], "run_id": run_id, "recipe": {**recipe.to_json(), "name": name}, "recipe_hash": recipe.recipe_hash,
        "pseudo": {"kind": "semantic-selection", "base_run_id": run["run_id"], "n": n, "selector": SELECTOR,
                   "model": "BAAI/bge-m3@5617a9f61b028005a4858fdac845db406aefb181", "embed_seconds": embed_seconds,
                   "unique_texts": len(texts), "cues": cues, "differ_from_chrf": differ},
        "seed": run["seed"], "scope": run["scope"], "sources": run["sources"], "scene_ids": run["scene_ids"],
        "created_at_utc": utc_now(), "sessions": [], "resumed": False, "performance_comparable": False,
        "wall_clock_seconds": seconds, "completion": run["completion"]})
    return {"run_id": run_id, "cues": cues, "differ_from_chrf": differ, "differ_rate": round(differ / cues, 3),
            "unique_texts": len(texts), "embed_seconds": round(embed_seconds, 1)}


def main() -> int:
    parser = argparse.ArgumentParser(description="语义效用 MBR（票据 08）")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--n", type=int, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--base", default=BASE, help="多样本基准配方名（默认 mbr8）")
    parser.add_argument("--scope", choices=("dev", "confirm"), default="dev")
    args = parser.parse_args()
    encode = load_encoder()
    for base_run in base_runs(args.root, args.scope, args.base):
        print(json.dumps(derive_semantic(args.root, base_run, args.name, args.n, encode)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
