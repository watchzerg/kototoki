"""VAD 召回扫描（票据 11）：Pyannote 帧分数缓存一次，离线换阈值筛选，再把选中的参数物化成产品 `vad.json`。

产品 VAD（`kototoki.vad.PyannoteVad`）对 segmentation-3.0 做 powerset 硬转换、说话人取 max、
滑窗重叠平均，得到每帧 0–1 的"判为语音的窗口比例"，再用 `Binarize(onset=offset=0.5,
min_duration_on=off=0)` 二值化。本模块把重叠平均后的分数存下来（`scores`，GPU），之后
`screen` 在 CPU 上扫 onset／offset／min_duration_on／min_duration_off／两端补边 pad，
用参考字幕的时间轴算覆盖率；`materialize` 把一组参数写成新工作目录里的 `vad.json`
（身份、窗口策略与产品相同，参数记在 `metadata.experiment`），随后直接用产品
`kototoki.workers.asr`／`align` 跑 `jobs-*.json`。

命令（仓库根目录，`.venv`）：
  python -X utf8 -m experiments.quality_v5.vad_sweep scores --work-dir WORK --out scores.npz
  python -X utf8 -m experiments.quality_v5.vad_sweep screen --film NAME SCORES REFERENCE --out screen.json
  python -X utf8 -m experiments.quality_v5.vad_sweep materialize --name NAME --params JSON \\
      --film ID SCORES WORK [...] --out-root ROOT --config JOBS_JSON
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
from pathlib import Path
import time
from typing import Any

SAMPLE_RATE = 16000
CURRENT = {"onset": 0.5, "offset": 0.5, "min_duration_on": 0.0, "min_duration_off": 0.0, "pad": 0.0}
GRID = {"onset": [0.5, 0.4, 0.3, 0.2, 0.1], "offset_delta": [0.0, 0.1, 0.2],
        "min_duration_on": [0.0], "min_duration_off": [0.0, 0.2, 0.5], "pad": [0.0, 0.1, 0.2, 0.4]}
# 票据 12／13 的 cue 内切词样本：HF II w0 的两个字符时间（参考字幕 1968.89–1971.24）
SAMPLE_POINTS = {"hf-ii": [1969.27, 1970.77]}


# --- 分数缓存（GPU） ---------------------------------------------------------------

def compute_scores(work_dir: Path, out: Path) -> dict[str, Any]:
    os.environ.update({"HF_HUB_OFFLINE": "1", "PYANNOTE_METRICS_ENABLED": "0"})
    import numpy as np
    import torch

    from kototoki import artifacts
    from kototoki.vad import PyannoteVad
    from kototoki.workers import gpu

    vad_doc = json.loads((work_dir / artifacts.VAD).read_text(encoding="utf-8"))
    jobs = json.loads((work_dir.parent / "jobs-vad.json").read_text(encoding="utf-8"))
    checkpoint = Path(jobs["config"]["models"]["vad"])
    audio, pcm = gpu.read_wav(work_dir / artifacts.AUDIO_16K)
    if pcm != vad_doc["identity"]["upstream"][artifacts.AUDIO_16K]:
        raise ValueError("audio-16k.wav differs from the one vad.json was computed from")
    started = time.perf_counter()
    vad = PyannoteVad(checkpoint)
    load_s = time.perf_counter() - started
    started = time.perf_counter()
    feature = vad._engine._segmentation({"waveform": torch.from_numpy(audio).unsqueeze(0),
                                          "sample_rate": SAMPLE_RATE, "uri": "kototoki-vad"})
    inference_s = time.perf_counter() - started
    window = feature.sliding_window
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, data=np.asarray(feature.data, dtype=np.float32),
                        start=window.start, duration=window.duration, step=window.step,
                        samples=len(audio))
    meta = {"pcm_sha256": pcm, "frames": int(feature.data.shape[0]), "frame_step_s": window.step,
            "load_s": load_s, "inference_s": inference_s, "checkpoint": str(checkpoint)}
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


# --- 离线二值化 ---------------------------------------------------------------------

def load_scores(path: Path) -> tuple[Any, int]:
    import numpy as np
    from pyannote.core import SlidingWindow, SlidingWindowFeature

    data = np.load(path)
    window = SlidingWindow(start=float(data["start"]), duration=float(data["duration"]),
                           step=float(data["step"]))
    return SlidingWindowFeature(data["data"], window), int(data["samples"])


def intervals(feature: Any, samples: int, params: dict[str, float]) -> list[list[float]]:
    """分数 → 语音区间（秒）。pad 在二值化后两端各补，裁到源范围，重叠的并起来。"""
    from pyannote.audio.utils.signal import Binarize

    binarize = Binarize(onset=params["onset"], offset=params["offset"],
                        min_duration_on=params["min_duration_on"], min_duration_off=params["min_duration_off"])
    support = binarize(feature).get_timeline().support()
    raw = [[segment.start, segment.end] for segment in support]
    pad = params.get("pad", 0.0)
    if not pad:
        return raw
    limit = samples / SAMPLE_RATE
    merged: list[list[float]] = []
    for start, end in raw:
        start, end = max(0.0, start - pad), min(limit, end + pad)
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def union_seconds(spans: list[list[float]]) -> float:
    return sum(end - start for start, end in merge(spans))


def overlap_seconds(a: list[list[float]], b: list[list[float]]) -> float:
    """两组各自不重叠、已排序区间的交集秒数。"""
    i = j = 0
    total = 0.0
    while i < len(a) and j < len(b):
        low, high = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if high > low:
            total += high - low
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return total


def merge(spans: list[list[float]]) -> list[list[float]]:
    out: list[list[float]] = []
    for start, end in sorted(spans):
        if out and start <= out[-1][1]:
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([start, end])
    return out


def coverage(speech: list[list[float]], reference: list[dict], samples: int, film: str) -> dict[str, Any]:
    """语音区间对参考字幕时间轴的覆盖：时间召回、条目命中、参考外语音秒、窗口数与 ASR 输入秒。"""
    from kototoki.vad import chunk_intervals

    ref = merge([[r["start"], r["end"]] for r in reference])
    ref_padded = merge([[r["start"] - 0.5, r["end"] + 0.5] for r in reference])
    speech_s = union_seconds(speech)
    covered = overlap_seconds(speech, ref)
    hits = 0
    for r in reference:
        inside = overlap_seconds(speech, [[r["start"], r["end"]]])
        if inside >= 0.5 * (r["end"] - r["start"]):
            hits += 1
    chunks, metadata = chunk_intervals(speech, samples)
    points = SAMPLE_POINTS.get(film, [])
    return {"speech_s": round(speech_s, 2), "intervals": len(speech),
            "ref_time_recall": round(covered / union_seconds(ref), 4),
            "ref_cue_half_covered": round(hits / len(reference), 4),
            "outside_ref_s": round(speech_s - overlap_seconds(speech, ref_padded), 2),
            "windows": len(chunks), "window_s": round(metadata["accounting"]["chunk_samples"] / SAMPLE_RATE, 1),
            "sample_points_covered": [any(s <= p < e for s, e in speech) for p in points]}


def grid() -> list[dict[str, float]]:
    out = []
    for onset, delta, on, off, pad in itertools.product(GRID["onset"], GRID["offset_delta"], GRID["min_duration_on"],
                                                        GRID["min_duration_off"], GRID["pad"]):
        if onset - delta <= 0:
            continue
        out.append({"onset": onset, "offset": round(onset - delta, 2), "min_duration_on": on,
                    "min_duration_off": off, "pad": pad})
    return out


def screen(films: list[tuple[str, Path, Path]]) -> dict[str, Any]:
    result: dict[str, Any] = {"grid": GRID, "films": {}}
    for name, scores_path, reference_path in films:
        feature, samples = load_scores(scores_path)
        reference = json.loads(reference_path.read_text(encoding="utf-8"))["spans"]
        rows = []
        for params in grid():
            rows.append({"params": params, **coverage(intervals(feature, samples, params), reference, samples, name)})
        result["films"][name] = rows
    return result


# --- 物化成产品 vad.json ----------------------------------------------------------

def additive_chunks(current: list[dict], speech: list[list[float]], samples: int,
                    min_extra_s: float) -> tuple[list[dict], dict[str, Any]]:
    """当前窗口原样保留；新参数检出的语音减去当前窗口覆盖后，长度 ≥ min_extra_s 的部分另成新窗口。

    新窗口按产品窗口策略（`chunk_intervals`）切分，但只在两个相邻当前窗口之间的空隙里合并，
    不会与当前窗口重叠，因此当前窗口的 Whisper 输入与基线逐样本相同。
    """
    from kototoki.vad import chunk_intervals

    bounds = [(c["start"], c["end"]) for c in current]
    extra: list[list[float]] = []
    for start, end in speech:
        pieces = [[start, end]]
        for low, high in bounds:
            next_pieces = []
            for a, b in pieces:
                if b <= low or a >= high:
                    next_pieces.append([a, b])
                    continue
                if a < low:
                    next_pieces.append([a, low])
                if b > high:
                    next_pieces.append([high, b])
            pieces = next_pieces
        extra += [piece for piece in pieces if piece[1] - piece[0] >= min_extra_s]
    added: list[dict] = []
    edges = [0.0] + [edge for low, high in bounds for edge in (low, high)] + [samples / SAMPLE_RATE]
    for gap_start, gap_end in zip(edges[0::2], edges[1::2]):
        inside = [piece for piece in extra if gap_start <= piece[0] and piece[1] <= gap_end]
        if inside:
            chunks, _ = chunk_intervals(inside, samples)
            for chunk in chunks:  # 取整可能越过当前窗口边界一个样本，夹回空隙内
                low = max(chunk["start_sample"], math.ceil(gap_start * SAMPLE_RATE))
                high = min(chunk["end_sample"], math.floor(gap_end * SAMPLE_RATE))
                if high - low < min_extra_s * SAMPLE_RATE:
                    continue
                added.append({**chunk, "start_sample": low, "end_sample": high,
                              "start": _seconds(low, samples), "end": _seconds(high, samples),
                              "segments": [[max(a, _seconds(low, samples)), min(b, _seconds(high, samples))]
                                           for a, b in chunk["segments"]]})
    merged = sorted([dict(c) for c in current] + added, key=lambda c: c["start_sample"])
    return merged, {"added_windows": len(added),
                    "added_s": sum(c["end_sample"] - c["start_sample"] for c in added) / SAMPLE_RATE}


def _seconds(sample: int, samples: int) -> float:
    from kototoki.vad import _seconds as product_seconds

    return product_seconds(sample, samples)


def materialize(name: str, params: dict[str, float], films: list[tuple[str, Path, Path]], out_root: Path,
                config: dict[str, Any], additive_min_s: float | None = None) -> dict[str, Any]:
    """每部在 `out_root/<name>/<id>/` 写 `vad.json`（硬链接 `audio-16k.wav`），并写 asr／align 的 jobs 文件。"""
    from kototoki import artifacts, plan
    from kototoki.vad import chunk_intervals
    from kototoki.schema import validate_windows

    root = out_root / name
    files_asr, files_align, summary = [], [], {}
    for file_id, scores_path, work_dir in films:
        source = json.loads((work_dir / artifacts.VAD).read_text(encoding="utf-8"))
        feature, samples = load_scores(scores_path)
        speech = intervals(feature, samples, params)
        if additive_min_s is None:
            chunks, accounting = chunk_intervals(speech, samples)
        else:
            chunks, added = additive_chunks(source["chunks"], speech, samples, additive_min_s)
            accounting = {key: source[key] for key in ("raw_intervals", "speech_intervals", "accounting")}
            accounting["accounting"] = {**accounting["accounting"], **added}
        validate_windows(chunks, samples)
        target = root / file_id
        target.mkdir(parents=True, exist_ok=True)
        wav = target / artifacts.AUDIO_16K
        if not wav.exists():
            os.link(work_dir / artifacts.AUDIO_16K, wav)
        payload = {key: source[key] for key in ("schema_version", "offset_s", "input")}
        payload.update(chunks=chunks, **accounting,
                       metadata={**source["metadata"], "experiment": {"ticket": "quality-v5-11", "params": params,
                                                                     "additive_min_s": additive_min_s}},
                       stages={"load_s": 0.0, "inference_s": 0.0})
        artifacts.write_artifact(target / artifacts.VAD, source["identity"], payload)
        files_asr.append({"id": file_id, "work_dir": str(target),
                          "inputs": {"wav": str(wav), "vad": str(target / artifacts.VAD)}})
        files_align.append({"id": file_id, "work_dir": str(target),
                            "inputs": {"wav": str(wav), "asr": str(target / artifacts.ASR)}})
        summary[file_id] = {"windows": len(chunks), "speech_s": accounting["accounting"]["speech_samples"] / SAMPLE_RATE,
                            **{k: accounting["accounting"][k] for k in ("added_windows", "added_s")
                               if k in accounting["accounting"]}}
    engine = config["engine"]
    for stage, files in (("asr", files_asr), ("align", files_align)):
        jobs = {"stage": stage, "recipe_hash": plan.recipe_hash(stage, **({"engine": engine} if stage == "asr" else {})),
                "config": config, "files": files}
        (root / f"jobs-{stage}.json").write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "params.json").write_text(json.dumps({"name": name, "params": params, "summary": summary}, indent=2),
                                      encoding="utf-8")
    return summary


# --- 整片结果汇总 ------------------------------------------------------------------

SAMPLE_WINDOW = {"hf-ii": (1968.5, 1971.5)}


def run_report(name: str, work_dirs: dict[str, Path], evals: dict[str, Path]) -> dict[str, Any]:
    """一组参数在各部的 CER／S／D／I、时间可测数，以及用产品默认 cue 规则重建的 cue 统计。"""
    from kototoki import cues
    from kototoki.config import DEFAULTS

    result: dict[str, Any] = {"name": name, "films": {}}
    for film, work_dir in work_dirs.items():
        score = json.loads(evals[film].read_text(encoding="utf-8"))
        align = json.loads((work_dir / "align.json").read_text(encoding="utf-8"))
        payload, _ = cues.build_cues(align, dict(DEFAULTS["cues"]))
        built = payload["cues"]
        lexical = [sum(1 for ch in c["text"] if cues.is_lexical(ch)) for c in built]
        low, high = SAMPLE_WINDOW.get(film, (0.0, 0.0))
        sample = [c["text"] for c in built if c["end_ms"] / 1000 > low and c["start_ms"] / 1000 < high]
        text, timing = score["text"], score["timing"]
        result["films"][film] = {
            "cer": round(text["CER"], 5), "S": text["S"], "D": text["D"], "I": text["I"],
            "candidate_characters": text["candidate_characters"],
            "measurable": timing["measurable_count"],
            "success_0.5": timing["success"]["0.5"]["success_count"],
            "over_2s": timing["over_threshold_counts"]["2.0"], "over_5s": timing["over_threshold_counts"]["5.0"],
            "cues": len(built), "cues_le2_lexical": sum(1 for n in lexical if n <= 2),
            "windows": len(align["chunks"]), "sample_cues": sample}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="VAD 召回扫描（票据 11）")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("scores")
    p.add_argument("--work-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("screen")
    p.add_argument("--film", nargs=3, action="append", required=True, metavar=("NAME", "SCORES", "REFERENCE"))
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("materialize")
    p.add_argument("--name", required=True)
    p.add_argument("--params", required=True, help="JSON：onset/offset/min_duration_on/min_duration_off/pad")
    p.add_argument("--film", nargs=3, action="append", required=True, metavar=("ID", "SCORES", "WORK_DIR"))
    p.add_argument("--out-root", type=Path, required=True)
    p.add_argument("--config", type=Path, required=True, help="取其 config 段的产品 jobs 文件（如 jobs-asr.json）")
    p.add_argument("--additive-min-s", type=float, help="保留当前窗口，只为窗口外新检出的语音（≥ 此秒数）加窗口")
    p = sub.add_parser("report")
    p.add_argument("--run", nargs=2, action="append", required=True, metavar=("NAME", "DIR"),
                   help="DIR 下有 <id>/align.json 与 eval-<film>.json；current 对照可指向 01 的布局（见 --layout）")
    p.add_argument("--film", nargs=2, action="append", required=True, metavar=("FILM", "ID"))
    p.add_argument("--current", nargs=2, metavar=("WORK_ROOT", "EVAL_DIR"),
                   help="把 01 的产品产物作为 current 行：WORK_ROOT/<id>/align.json、EVAL_DIR/product-w0-<film>.json")
    p.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "report":
        rows = []
        if args.current:
            root, evals = map(Path, args.current)
            rows.append(run_report("current", {f: root / i for f, i in args.film},
                                   {f: evals / f"product-w0-{f}.json" for f, _ in args.film}))
        for name, directory in args.run:
            rows.append(run_report(name, {f: Path(directory) / i for f, i in args.film},
                                   {f: Path(directory) / f"eval-{f}.json" for f, _ in args.film}))
        args.out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        for row in rows:
            for film, r in row["films"].items():
                print(row["name"], film, {k: v for k, v in r.items() if k != "sample_cues"}, r["sample_cues"])
        return 0
    if args.command == "scores":
        print(json.dumps(compute_scores(args.work_dir, args.out), indent=2))
    elif args.command == "screen":
        result = screen([(n, Path(s), Path(r)) for n, s, r in args.film])
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        params = {**CURRENT, **json.loads(args.params)}
        config = json.loads(args.config.read_text(encoding="utf-8"))["config"]
        summary = materialize(args.name, params, [(i, Path(s), Path(w)) for i, s, w in args.film],
                              args.out_root, config, args.additive_min_s)
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
