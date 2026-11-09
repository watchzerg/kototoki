"""票据 01 的输入核实：HF II 对照产物身份与官方 CER；HF III 缺产品形状产物时用产品 worker 重算（1 GPU run）。

HF III 的 `audio-16k.wav` 取 v5 第 12 步工作目录里的硬链接（PCM SHA256 `e8e841fd…`），VAD→ASR→对齐三个产品 worker
依次运行，再用产品 `cues.build_cues`（默认 `[cues]` 规则）得到 `ja.srt`／`ja-cues.json`。重算结果的官方 CER 须与基线
13.77%（S 777／D 444／I 342）逐项相同。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from experiments.asr_robustness_v14 import common, workers
from kototoki import artifacts, plan
from kototoki.config import DEFAULTS
from kototoki.cues import build_cues

TICKET = common.ROOT / "01"


def build_ja_srt(work: Path) -> tuple[dict[str, Any], str]:
    """产品 cue 阶段（默认规则）：`align.json` → (`ja-cues.json` payload, `ja.srt` 文本)。"""
    align = common.read_json(work / artifacts.ALIGN)
    return build_cues(align, dict(DEFAULTS["cues"]))


def verify_hf_ii() -> dict[str, Any]:
    """对照产物身份：asr 配方 hash 等于当前 W0、官方 CER 与基线逐项相同、`ja.srt` 可由 `align.json` 按默认规则复现。"""
    work = common.FILMS["hf-ii"]["work"]
    asr = common.read_json(work / artifacts.ASR)
    align = common.read_json(work / artifacts.ALIGN)
    reference = common.load_reference_doc("hf-ii")
    text = common.official_cer(reference, align)
    baseline = common.read_json(common.FILMS["hf-ii"]["baseline_eval"])["text"]
    payload, srt = build_ja_srt(work)
    product_srt = (work / "ja.srt").read_text(encoding="utf-8-sig")
    report = {
        "film": "hf-ii", "work": str(work),
        "asr_recipe_hash": asr["identity"]["recipe_hash"], "w0_recipe_hash": plan.recipe_hash("asr", engine="w0"),
        "asr_recipe_matches_w0": asr["identity"]["recipe_hash"] == plan.recipe_hash("asr", engine="w0"),
        "pcm_sha256_matches": asr["identity"]["upstream"][artifacts.AUDIO_16K] == common.PCM_SHA256["hf-ii"],
        "windows": len(asr["chunks"]), "failed_windows": len(asr["failed_windows"]),
        "official": common.cer_summary(text), "baseline": common.cer_summary(baseline),
        "official_matches_baseline": all(text[k] == baseline[k] for k in ("S", "D", "I", "reference_characters",
                                                                           "candidate_characters")),
        "ja_srt_reproduced": srt.replace("\r\n", "\n") == product_srt.replace("\r\n", "\n"),
        "cues": len(payload["cues"]),
    }
    common.write_json(TICKET / "verify-hf-ii.json", report)
    return report


def reproduce_hf_iii(*, source_wav: Path = common.HF_III_WAV_SOURCE) -> dict[str, Any]:
    """GPU run：VAD→ASR→align 三个产品 worker 依次跑 HF III，再建 cue，评官方 CER 并与基线逐项比。"""
    work = common.FILMS["hf-iii"]["work"]
    work.mkdir(parents=True, exist_ok=True)
    wav = work / artifacts.AUDIO_16K
    if not wav.exists():
        os.link(source_wav, wav)
    preflight = common.other_gpu_jobs()
    blocking = [p for p in preflight["suspect_processes"] if "llama" in p.lower() or "strata" in p.lower()]
    if preflight["gpu_lock"] or blocking:
        raise SystemExit(f"GPU not free (lock {preflight['gpu_lock']}, processes {blocking}); nothing started")
    log_dir = TICKET / "hf-iii" / "logs"
    results = []
    with common.gpu_lock("v14-01 reproduce HF III product STT (vad/asr/align)"):
        for stage in ("vad", "asr", "align"):
            jobs = workers.write_jobs(stage, [work], TICKET / "hf-iii" / f"jobs-{stage}.json")
            results.append(workers.run_worker(stage, jobs, log_dir))
    vad = common.read_json(work / artifacts.VAD)
    asr = common.read_json(work / artifacts.ASR)
    align = common.read_json(work / artifacts.ALIGN)
    payload, srt = build_ja_srt(work)
    common.write_text(work / "ja.srt", srt)
    common.write_json(work / artifacts.JA_CUES, payload)
    reference = common.load_reference_doc("hf-iii")
    text = common.official_cer(reference, align)
    baseline = common.read_json(common.FILMS["hf-iii"]["baseline_eval"])["text"]
    # 窗口与 v5 第 12 步复制自 01 产品 vad.json 的窗口逐个相等（身份核对的旁证）
    v5_chunks = common.read_json(source_wav.parent / artifacts.ASR)["chunks"]
    report = {
        "film": "hf-iii", "work": str(work), "preflight": preflight,
        "pcm_sha256_matches": vad["identity"]["upstream"][artifacts.AUDIO_16K] == common.PCM_SHA256["hf-iii"],
        "windows": len(vad["chunks"]), "chunks_equal_v5_step12": vad["chunks"] == v5_chunks,
        "failed_windows": len(asr["failed_windows"]),
        "text_only_units": sum(1 for u in align["units"] if u["status"] == "text_only"),
        "official": common.cer_summary(text), "baseline": common.cer_summary(baseline),
        "official_matches_baseline": all(text[k] == baseline[k] for k in ("S", "D", "I", "reference_characters",
                                                                           "candidate_characters")),
        "cues": len(payload["cues"]),
        "stages": [{k: r[k] for k in ("stage", "exit_code", "wall_s", "vram_peak_mib")} for r in results],
        "gpu_run": 1,
    }
    common.write_json(TICKET / "reproduce-hf-iii.json", report)
    common.write_json(TICKET / "eval" / "hf-iii-reproduced.json", {"text": text})
    return report


def cue_rules() -> dict[str, Any]:
    return dict(DEFAULTS["cues"])


__all__ = ["verify_hf_ii", "reproduce_hf_iii", "build_ja_srt", "cue_rules"]
