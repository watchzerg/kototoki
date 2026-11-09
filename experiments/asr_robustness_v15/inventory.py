"""票据 01：盘点盘上仍存在的 w0 转写产物（同一模型 faster-whisper large-v3 的所有独立解码）。

两种落盘形状都读（`common.segments_and_traces`）：产品 `asr.json`（`identity.recipe_hash` 为 W0 配方）与 W0 demo 的
`result.json`／`asr/asr.json`（`recipe` 为 `w0-pyannote-current-mms-v1` 或 `route` 为 w0）。分组：

- `product`：HF II 产品整片与 HF III 的 v14 重算（v15 的对照，A4 的动作在这两部上做）；
- `vad-variant`：v5 第 11 步的 6 组 VAD 参数 × 两部（同一部电影不同 VAD 参数算独立样本，分开报告）；
- `fullfilm-demo`：`.local/fullfilm-comparison/` 下 W0 demo 的整片运行（pyannote-current 与 cut-merge 分窗）；
- `window-demo`：`.local/w0-demo/` 下 5 分钟窗口的 demo 运行（不同 VAD 候选）与 worker smoke；
- `parliament`：国会录音整段（3 小时，与电影不同的领域，作误报扫描用）。

x0／其他模型的产物（`x0-*`、anime-whisper、qwen、cohere 等）不纳入。ATKD-089 的 `asr.json` 已不在盘上
（`.local/logcheck-atkd089/out/` 只剩 `ja-zh.srt`），只记入盘点表的 `missing`。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from experiments.asr_robustness_v15 import common
from kototoki import artifacts, plan

W0_RECIPE_HASH = plan.recipe_hash("asr", engine="w0")
V5_RUNS = common.LOCAL / "quality-exploration-v5" / "11" / "runs"
FULLFILM = common.LOCAL / "fullfilm-comparison"
W0_DEMO = common.LOCAL / "w0-demo"
MISSING = {"ATKD-089": str(common.LOCAL / "logcheck-atkd089" / "out")}
REFERENCE_FILM = {"8d2f3e76dd0c": "hf-ii", "fb2e0da74018": "hf-iii"}
GROUP_ORDER = {"product": 0, "vad-variant": 1, "fullfilm-demo": 2, "window-demo": 3, "parliament": 4}


def film_of(name: str) -> str | None:
    for key, film in (("hf-iii", "hf-iii"), ("hf-ii", "hf-ii")):
        if key in name:
            return film
    return None


def discover() -> list[dict[str, Any]]:
    """盘点表（不读文件内容）：`{id, group, film, path, format}`，按组与 id 排序。"""
    samples: list[dict[str, Any]] = []
    for film in ("hf-ii", "hf-iii"):
        samples.append({"id": f"product-{film}", "group": "product", "film": film,
                        "path": str(common.FILMS[film]["work"] / artifacts.ASR), "format": "product"})
    if V5_RUNS.is_dir():
        for run in sorted(p for p in V5_RUNS.iterdir() if p.is_dir()):
            for work in sorted(p for p in run.iterdir() if p.is_dir()):
                path = work / artifacts.ASR
                if path.is_file() and work.name in REFERENCE_FILM:
                    samples.append({"id": f"vad-{run.name}-{REFERENCE_FILM[work.name]}", "group": "vad-variant",
                                    "film": REFERENCE_FILM[work.name], "path": str(path), "format": "product"})
    for family in sorted(p for p in FULLFILM.iterdir() if p.is_dir()) if FULLFILM.is_dir() else []:
        runs = family / "runs"
        for run in sorted(p for p in runs.iterdir() if p.is_dir()) if runs.is_dir() else []:
            path = run / "asr" / artifacts.ASR
            if run.name.startswith("w0-") and path.is_file():
                samples.append({"id": f"fullfilm-{family.name}-{run.name}", "group": "fullfilm-demo",
                                "film": film_of(run.name), "path": str(path), "format": "demo"})
        smoke = family / "w0" / "asr" / artifacts.ASR
        if smoke.is_file():
            samples.append({"id": f"fullfilm-{family.name}-w0", "group": "window-demo", "film": None,
                            "path": str(smoke), "format": "demo"})
    for run in sorted(p for p in W0_DEMO.iterdir() if p.is_dir()) if W0_DEMO.is_dir() else []:
        path = run / "result.json"
        if not path.is_file() or "x0" in run.name:
            continue
        group = "parliament" if run.name.startswith("parliament") else "window-demo"
        samples.append({"id": f"demo-{run.name}", "group": group, "film": film_of(run.name), "path": str(path),
                        "format": "demo"})
    return sorted(samples, key=lambda s: (GROUP_ORDER[s["group"]], s["id"]))


def load_sample(sample: dict[str, Any]) -> dict[str, Any]:
    """读一个样本：段、trace、身份标签与（demo 窗口）源起点秒。"""
    document = common.read_json(Path(sample["path"]))
    segments, traces = common.segments_and_traces(document)
    identity = document.get("identity") if isinstance(document.get("identity"), dict) else {}
    recipe = identity.get("recipe_hash") or document.get("recipe") or document.get("route")
    return {"segments": segments, "traces": traces, "windows": len(segments),
            "recipe": recipe, "recipe_is_w0": recipe == W0_RECIPE_HASH,
            "source_start_s": float(document.get("source_start_seconds") or 0.0),
            "pcm_sha256": (identity.get("upstream") or {}).get(artifacts.AUDIO_16K) if identity else None}


__all__ = ["GROUP_ORDER", "MISSING", "W0_RECIPE_HASH", "discover", "film_of", "load_sample"]
