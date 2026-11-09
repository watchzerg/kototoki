"""票据 02：A1 被标记窗口置空的离线模拟（官方口径）与 A2 问题窗口单次补解（GPU 1 run）。

A1 不动任何正常窗口的 token，只把被标记窗口的字符从 `align.json` 的 `text`／`units` 里删掉（MMS 逐窗独立，
其余 unit 的时间不变），所以离线结果与真实运行逐字相同；评官方 CER。
A2 只对同一批窗口用同一模型、同一提示、同一 beam，只加 `no_repeat_ngram_size=5` 再解一次，补解结果仍过同一守卫
（仍触阈值即置空），写产品形状 `asr.json`（研究配方 `w0-faster-whisper-large-v3-guard-v1`，只记在
`metadata.experiment`），经产品 `align` worker，评官方 CER。
"""

from __future__ import annotations

from typing import Any

from experiments.asr_robustness_v14 import common, signals
from kototoki import artifacts

TICKET = common.ROOT / "02"
RECIPE_LABEL = "w0-faster-whisper-large-v3-guard-v1"
NO_REPEAT = 5
TOTAL_REF_CHARS = {"hf-ii": 10781, "hf-iii": 11353}


def blank_align(align: dict[str, Any], asr: dict[str, Any], windows: list[int], reason: str) -> dict[str, Any]:
    """返回去掉若干窗口文字后的 `align.json` 内容（新 dict）：text／units 重编号，段文字置空并记 `failed_windows`。"""
    ranges, cursor = [], 0
    for segment in asr["original_segments"]:
        ranges.append((cursor, cursor + len(segment["text"])))
        cursor += len(segment["text"])
    if align["text"] != "".join(s["text"] for s in asr["original_segments"]):
        raise ValueError("align.json text differs from asr.json retained text")
    removed = sorted(ranges[i] for i in windows)
    keep = [True] * len(align["text"])
    for lo, hi in removed:
        for position in range(lo, hi):
            keep[position] = False
    shift, offsets = 0, []
    for flag in keep:
        offsets.append(shift)
        shift += 0 if flag else 1
    offsets.append(shift)
    text = "".join(ch for ch, flag in zip(align["text"], keep) if flag)
    units = []
    for unit in align["units"]:
        lo, hi = unit["char_start"], unit["char_end"]
        if not all(keep[lo:hi]):
            if any(keep[lo:hi]):
                raise ValueError("unit spans a blanked window boundary")
            continue
        units.append({**unit, "char_start": lo - offsets[lo], "char_end": hi - offsets[hi]})
    segments = [dict(s) for s in align["original_segments"]]
    failed = [dict(f) for f in align.get("failed_windows", [])]
    for i in windows:
        failed.append({"chunk_index": i, "reason": reason, "text": segments[i]["text"]})
        segments[i]["text"] = ""
    out = {k: v for k, v in align.items() if k != "identity"}
    out.update(text=text, units=units, original_segments=segments, failed_windows=failed)
    return out


def gate(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """§4.0 的门：两部都降，且合计编辑量降幅 ≥0.3 pp（分母为两部参考字符合计）。"""
    deltas = {film: r["after"]["S"] + r["after"]["D"] + r["after"]["I"] - (r["before"]["S"] + r["before"]["D"] + r["before"]["I"])
              for film, r in results.items()}
    total_ref = sum(TOTAL_REF_CHARS[film] for film in results)
    combined_pp = round(-sum(deltas.values()) / total_ref * 100, 4)
    both = all(d < 0 for d in deltas.values()) and len(results) == 2
    return {"delta_edits": deltas, "combined_drop_pp": combined_pp, "both_drop": both,
            "passes": both and combined_pp >= 0.3,
            "verdict": ("candidate" if both and combined_pp >= 0.3 else "effective-but-insufficient" if both
                        else "no-gain")}


def blank(rule: str, films: tuple[str, ...] = ("hf-ii", "hf-iii")) -> dict[str, Any]:
    results = {}
    for film in films:
        work = common.FILMS[film]["work"]
        asr = common.read_json(work / artifacts.ASR)
        align = common.read_json(work / artifacts.ALIGN)
        windows = signals.select_windows(film, rule)
        blanked = blank_align(align, asr, windows, f"guard:{rule}")
        reference = common.load_reference_doc(film)
        before = common.cer_summary(common.official_cer(reference, align))
        after = common.cer_summary(common.official_cer(reference, blanked))
        out = TICKET / f"blank-{rule}" / film
        common.write_json(out / artifacts.ALIGN, blanked)
        results[film] = {"windows": windows, "blanked_chars": sum(len(asr["original_segments"][i]["text"]) for i in windows),
                         "before": before, "after": after}
    report = {"rule": rule, "rule_params": signals.RULES[rule], "films": results, "gate": gate(results), "gpu_run": 0}
    common.write_json(TICKET / f"blank-{rule}.json", report)
    return report


def redecode(rule: str, films: tuple[str, ...] = ("hf-ii", "hf-iii")) -> dict[str, Any]:
    """GPU：被标记窗口加 `no_repeat_ngram_size=5` 单次补解 → 守卫 → 产品形状 asr.json → 产品 align → 官方 CER。"""
    from experiments.asr_robustness_v14 import decode, workers

    preflight = common.other_gpu_jobs()
    blocking = [p for p in preflight["suspect_processes"] if "llama" in p.lower() or "strata" in p.lower()]
    if preflight["gpu_lock"] or blocking:
        raise SystemExit(f"GPU not free (lock {preflight['gpu_lock']}, processes {blocking}); nothing started")
    out_root = TICKET / f"redecode-{rule}"
    per_film: dict[str, Any] = {}
    sampler = common.VramSampler()
    sampler.start()
    started = common.timed()
    with common.gpu_lock(f"v14-02 A2 redecode ({rule})"):
        decoder = decode.W0Decoder(common.product_models()["models"])
        work_outs = []
        for film in films:
            work = common.FILMS[film]["work"]
            asr = common.read_json(work / artifacts.ASR)
            audio, pcm = decode.read_audio(work)
            if pcm != common.PCM_SHA256[film]:
                raise ValueError(f"{film}: audio-16k.wav differs from the control")
            windows = signals.select_windows(film, rule)
            segments = [dict(s) for s in asr["original_segments"]]
            traces = list(asr["asr_traces"])
            failures: list[tuple[int, str]] = []
            records = []
            for i in windows:
                chunk = asr["chunks"][i]
                decoded = decoder.decode(audio, chunk["start_sample"], chunk["end_sample"], no_repeat_ngram_size=NO_REPEAT)
                still = signals.flagged(decode.signal_of(decoded), signals.RULES[rule])
                before = segments[i]
                records.append({"window": i, "before": {"chars": len(before["text"]), "avg_logprob": before["avg_logprob"],
                                                        "compression_ratio": round(signals.compression_ratio(before["text"]), 4),
                                                        "tokens": len(traces[i]["tokens"]) if traces[i] else None},
                                "after": {"chars": len(decoded["text"]), "avg_logprob": decoded["avg_logprob"],
                                          "compression_ratio": decoded["compression_ratio"], "tokens": len(decoded["tokens"]),
                                          "cap_reached": decoded["cap_reached"], "seconds": decoded["seconds"]},
                                "same_text": decoded["text"] == before["text"], "still_flagged": still})
                segments[i] = {**before, "text": decoded["text"], "avg_logprob": decoded["avg_logprob"]}
                traces[i] = {"tokens": decoded["tokens"], "prompt": decoded["prompt"], "kwargs": decoded["kwargs"],
                             "feature_sha256": decoded["feature_sha256"], "start_sample": chunk["start_sample"],
                             "end_sample": chunk["end_sample"], "redecoded": True}
                if still:
                    failures.append((i, f"guard:{rule} after no_repeat_ngram_size={NO_REPEAT}"))
            work_out = out_root / film / work.name
            decode.link_audio(work_out, work)
            experiment = {"recipe": RECIPE_LABEL, "rule": rule, "rule_params": signals.RULES[rule],
                          "no_repeat_ngram_size": NO_REPEAT, "windows": windows, "records": records,
                          "decoder_load_s": decoder.load_s}
            decode.write_asr(work_out, asr, segments, traces, failures, experiment, f"{RECIPE_LABEL}:{rule}")
            work_outs.append(work_out)
            per_film[film] = {"windows": windows, "records": records, "blanked_after_redecode": [i for i, _ in failures]}
        del decoder  # 释放 CT2 显存后再起 align worker
        import gc

        gc.collect()
        align_result = workers.run_worker("align", workers.write_jobs("align", work_outs, out_root / "jobs-align.json"),
                                          out_root / "logs")
    wall = round(common.timed() - started, 1)
    peak = sampler.stop()
    results = {}
    for film in films:
        work = common.FILMS[film]["work"]
        reference = common.load_reference_doc(film)
        before = common.cer_summary(common.official_cer(reference, common.read_json(work / artifacts.ALIGN)))
        after = common.cer_summary(common.official_cer(reference, common.read_json(out_root / film / work.name / artifacts.ALIGN)))
        results[film] = {**per_film[film], "before": before, "after": after}
    report = {"rule": rule, "rule_params": signals.RULES[rule], "no_repeat_ngram_size": NO_REPEAT, "films": results,
              "gate": gate(results), "gpu_run": 1, "wall_s": wall, "vram_peak_mib": peak,
              "align": {k: align_result[k] for k in ("wall_s", "vram_peak_mib", "exit_code")}, "preflight": preflight}
    common.write_json(TICKET / f"redecode-{rule}.json", report)
    return report


__all__ = ["NO_REPEAT", "RECIPE_LABEL", "blank", "blank_align", "gate", "redecode"]
