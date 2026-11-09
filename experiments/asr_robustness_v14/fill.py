"""票据 03：B1 空子段补窗重解码（GPU 1 run）。

每个空子段（01 的 B0 表里 `empty` 且时长 ≥1 s）单独作为一个窗口（整数样本坐标，两端不加 pad），w0 同配方解一次；
结果过 A0 的守卫（规则名由参数给出，默认 `whisper-or`），仍触阈值即不采纳。被采纳的文字并入所在窗口的段：
**按时间插入**——取该窗口里时间中点在子段结束之后的第一个有时间字符，把补解文字插在它前面，没有就追加到段尾。
选这种方式的理由：`align` 与 cue 阶段都要求段与窗口一一对应、段文字即该窗全文，不能追加独立段；MMS 会对改动后的
整窗文字重新对齐，插在时间对应位置能让 CTC 的单调路径与音频顺序一致。
产品形状 `asr.json`（研究配方 `w0-faster-whisper-large-v3-fill-v1`，只记在 `metadata.experiment`），经产品 `align`，官方 CER。
"""

from __future__ import annotations

from typing import Any

from experiments.asr_robustness_v14 import common, gaps, guard, signals
from kototoki import artifacts

TICKET = common.ROOT / "03"
RECIPE_LABEL = "w0-faster-whisper-large-v3-fill-v1"
SAMPLE_RATE = common.SAMPLE_RATE


def insert_position(window_text: str, char_times: list[float | None], segment_end: float) -> int:
    """窗口文字里补解文字的插入位置：第一个时间中点 > 子段结束的字符之前；都不满足则段尾。"""
    for position, t in enumerate(char_times):
        if t is not None and t > segment_end:
            return position
    return len(window_text)


def merge_fill(window_text: str, char_times: list[float | None], fills: list[tuple[float, str]]) -> str:
    """把若干 (子段结束时刻, 文字) 按时间插入窗口文字；同一位置按时间先后排列。"""
    inserts: dict[int, list[tuple[float, str]]] = {}
    for end, text in fills:
        inserts.setdefault(insert_position(window_text, char_times, end), []).append((end, text))
    out, cursor = [], 0
    for position in sorted(inserts):
        out.append(window_text[cursor:position])
        out.extend(text for _, text in sorted(inserts[position]))
        cursor = position
    out.append(window_text[cursor:])
    return "".join(out)


def run(rule: str = "whisper-or", films: tuple[str, ...] = ("hf-ii", "hf-iii"), *,
        min_s: float = gaps.FILL_MIN_S) -> dict[str, Any]:
    from experiments.asr_robustness_v14 import decode, workers

    preflight = common.other_gpu_jobs()
    blocking = [p for p in preflight["suspect_processes"] if "llama" in p.lower() or "strata" in p.lower()]
    if preflight["gpu_lock"] or blocking:
        raise SystemExit(f"GPU not free (lock {preflight['gpu_lock']}, processes {blocking}); nothing started")
    out_root = TICKET / f"fill-{rule}"
    per_film: dict[str, Any] = {}
    sampler = common.VramSampler()
    sampler.start()
    started = common.timed()
    with common.gpu_lock(f"v14-03 B1 fill ({rule})"):
        decoder = decode.W0Decoder(common.product_models()["models"])
        work_outs = []
        for film in films:
            work = common.FILMS[film]["work"]
            asr = common.read_json(work / artifacts.ASR)
            align_doc = common.read_json(work / artifacts.ALIGN)
            audio, pcm = decode.read_audio(work)
            if pcm != common.PCM_SHA256[film]:
                raise ValueError(f"{film}: audio-16k.wav differs from the control")
            times = gaps.timed_chars(align_doc)
            ranges = gaps.window_char_ranges(asr)
            empty = gaps.empty_segments(film, min_s)
            segments = [dict(s) for s in asr["original_segments"]]
            records, by_window = [], {}
            for seg in empty:
                start_sample, end_sample = int(seg["start"] * SAMPLE_RATE), int(seg["end"] * SAMPLE_RATE)
                decoded = decoder.decode(audio, start_sample, end_sample)
                rejected = signals.flagged(decode.signal_of(decoded), signals.RULES[rule])
                accepted = (not rejected) and bool(decoded["text"].strip())
                records.append({"window": seg["window"], "segment": seg["segment"], "duration_s": seg["duration_s"],
                                "start_sample": start_sample, "end_sample": end_sample, "chars": len(decoded["text"]),
                                "tokens": len(decoded["tokens"]), "avg_logprob": decoded["avg_logprob"],
                                "compression_ratio": decoded["compression_ratio"], "cap_reached": decoded["cap_reached"],
                                "rejected_by_guard": rejected, "empty_output": not decoded["text"].strip(),
                                "accepted": accepted, "seconds": decoded["seconds"]})
                if accepted:
                    by_window.setdefault(seg["window"], []).append((seg["end"], decoded["text"]))
            for index, fills in by_window.items():
                lo, hi = ranges[index]
                segments[index] = {**segments[index], "text": merge_fill(segments[index]["text"], times[lo:hi], fills)}
            work_out = out_root / film / work.name
            decode.link_audio(work_out, work)
            experiment = {"recipe": RECIPE_LABEL, "guard_rule": rule, "rule_params": signals.RULES[rule],
                          "min_segment_s": min_s, "merge": "insert-at-first-char-after-segment-end",
                          "records": records, "decoder_load_s": decoder.load_s}
            decode.write_asr(work_out, asr, segments, list(asr["asr_traces"]), [], experiment, f"{RECIPE_LABEL}:{rule}")
            work_outs.append(work_out)
            per_film[film] = {"empty_segments": len(empty), "accepted": sum(1 for r in records if r["accepted"]),
                              "rejected_by_guard": sum(1 for r in records if r["rejected_by_guard"]),
                              "empty_output": sum(1 for r in records if r["empty_output"]),
                              "filled_chars": sum(r["chars"] for r in records if r["accepted"]),
                              "windows_changed": len(by_window), "records": records}
        del decoder
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
        results[film] = {**per_film[film], "before": before, "after": after,
                         "delta": {k: after[k] - before[k] for k in ("S", "D", "I")}}
    report = {"rule": rule, "min_segment_s": min_s, "films": results, "gate": guard.gate(results), "gpu_run": 1,
              "wall_s": wall, "vram_peak_mib": peak,
              "align": {k: align_result[k] for k in ("wall_s", "vram_peak_mib", "exit_code")}, "preflight": preflight}
    common.write_json(TICKET / f"fill-{rule}.json", report)
    return report


__all__ = ["RECIPE_LABEL", "insert_position", "merge_fill", "run"]
