"""票据 02 A4：对选中规则在两部电影上标记的窗口做三种动作，全部变体写产品形状 `asr.json`，一次产品 `align` 批处理，官方 CER。

- `blank`：置空（协议 `fail_window`，reason `guard:<rule>`；v14 已证离线置空与真实运行逐字相同，这里仍走 align 批以统一口径）。
- `collapse`：按 `repeat.collapse` 折叠相邻重复（保留第一个单元之前的文字与第一个单元），折叠后重算压缩比、沿用原
  `avg_logprob` 再过同一规则：仍被标记（如没有可折叠的 tandem 区段、或折叠后压缩比仍高）即置空。
- `redecode`：同一模型、同一提示、同一 beam 只加 `no_repeat_ngram_size=5` 单次补解（复用 v14 `decode.W0Decoder`），
  补解文字再按 `collapse` 处理（折叠 → 守卫 → 仍标记即置空）。只解一次、无条件采用或置空，不挑选（§4.0）。

研究配方标签 `w0-faster-whisper-large-v3-guard-v2`（只记在 `metadata.experiment`），变体名与逐窗记录在 `experiment.records`。
被改窗口的前后文字写 `02/<rule>/changed-windows.json`（只供 Opus 读感），报告 `actions-<rule>.json` 只含计数与 CER。
"""

from __future__ import annotations

from typing import Any

from experiments.asr_robustness_v14 import decode, guard, signals as v14_signals, workers
from experiments.asr_robustness_v15 import common, inventory, repeat, scan
from kototoki import artifacts

TICKET = "02"
RECIPE_LABEL = "w0-faster-whisper-large-v3-guard-v2"
NO_REPEAT = guard.NO_REPEAT
VARIANTS = ("blank", "collapse", "redecode")


def repeat_params(rule: str) -> dict[str, Any]:
    """折叠用的重复检测参数：规则带重复检测就用它的，否则用 A3 的默认定义。"""
    return scan.REPEAT_RULES[scan.RULES[rule].get("repeat", "repeat")]


def guard_signal(text: str, avg_logprob: float | None, trace: dict[str, Any] | None) -> dict[str, Any]:
    return {"compression_ratio": round(v14_signals.compression_ratio(text), 4), "cap_reached": v14_signals.cap_reached(trace),
            "avg_logprob": avg_logprob, "repeat": scan.repeat_signals(text)}


def collapse_window(text: str, avg_logprob: float | None, trace: dict[str, Any] | None, rule: str) -> dict[str, Any]:
    """折叠 → 守卫。返回 `{text, collapsed, still_flagged, record}`；`still_flagged` 为真时调用方置空。"""
    new_text, record = repeat.collapse(text, repeat_params(rule))
    still = scan.flagged(guard_signal(new_text, avg_logprob, trace), scan.RULES[rule])
    return {"text": new_text, "collapsed": record["collapsed"], "still_flagged": still, "record": record,
            "compression_ratio_after": round(v14_signals.compression_ratio(new_text), 4)}


def write_align_jobs(work_outs: dict[tuple[str, str], Any], path: Any) -> Any:
    """align 批的 jobs：三个变体共用同一个工作目录名，jobs 的 id 须唯一，所以 id 取 `<variant>-<film>`（v14 `write_jobs` 用目录名作 id，不能直接用）。"""
    from kototoki import plan

    files = [{"id": f"{variant}-{film}", "work_dir": str(work),
              "inputs": {"wav": str(work / artifacts.AUDIO_16K), "asr": str(work / artifacts.ASR)}}
             for (variant, film), work in sorted(work_outs.items())]
    common.write_json(path, {"stage": "align", "recipe_hash": plan.recipe_hash("align"),
                             "config": common.v14.product_models(), "files": files})
    return path


def flagged_windows(film: str, rule: str) -> tuple[list[int], list[dict[str, Any]]]:
    sample = next(s for s in inventory.discover() if s["id"] == f"product-{film}")
    rows = scan.window_rows(sample, inventory.load_sample(sample))
    return [r["index"] for r in rows if scan.flagged(r, scan.RULES[rule])], rows


def run(rule: str, films: tuple[str, ...] = ("hf-ii", "hf-iii")) -> dict[str, Any]:
    """GPU 1 run：补解（被标记窗口）＋三种变体 × 两部的一次 align 批。"""
    preflight = common.other_gpu_jobs()
    blocking = [p for p in preflight["suspect_processes"] if "llama" in p.lower() or "strata" in p.lower()]
    if preflight["gpu_lock"] or blocking:
        raise SystemExit(f"GPU not free (lock {preflight['gpu_lock']}, processes {blocking}); nothing started")
    out_root = common.ticket_dir(TICKET) / rule
    per_film: dict[str, Any] = {}
    changed: list[dict[str, Any]] = []
    sampler = common.VramSampler()
    sampler.start()
    started = common.timed()
    with common.gpu_lock(f"v15-02 A4 actions ({rule})"):
        decoder = decode.W0Decoder(common.v14.product_models()["models"])
        work_outs: dict[tuple[str, str], Any] = {}
        for film in films:
            work = common.FILMS[film]["work"]
            asr = common.read_json(work / artifacts.ASR)
            audio, pcm = decode.read_audio(work)
            if pcm != common.PCM_SHA256[film]:
                raise ValueError(f"{film}: audio-16k.wav differs from the control")
            windows, _rows = flagged_windows(film, rule)
            base_segments = [dict(s) for s in asr["original_segments"]]
            base_traces = list(asr["asr_traces"])
            records: dict[str, list[dict[str, Any]]] = {v: [] for v in VARIANTS}
            variant_docs: dict[str, tuple[list, list, list]] = {}
            for variant in VARIANTS:
                segments = [dict(s) for s in base_segments]
                traces = list(base_traces)
                failures: list[tuple[int, str]] = []
                for i in windows:
                    before = base_segments[i]
                    trace = base_traces[i]
                    rec: dict[str, Any] = {"window": i, "chars_before": len(before["text"]),
                                           "cr_before": round(v14_signals.compression_ratio(before["text"]), 4),
                                           "avg_logprob": before["avg_logprob"]}
                    if variant == "blank":
                        failures.append((i, f"guard:{rule}"))
                        rec.update(action="blank")
                        text_after = ""
                    else:
                        text, alp, tr = before["text"], before["avg_logprob"], trace
                        if variant == "redecode":
                            chunk = asr["chunks"][i]
                            decoded = decoder.decode(audio, chunk["start_sample"], chunk["end_sample"],
                                                     no_repeat_ngram_size=NO_REPEAT)
                            text, alp = decoded["text"], decoded["avg_logprob"]
                            tr = {"tokens": decoded["tokens"], "prompt": decoded["prompt"], "kwargs": decoded["kwargs"],
                                  "feature_sha256": decoded["feature_sha256"], "start_sample": chunk["start_sample"],
                                  "end_sample": chunk["end_sample"], "redecoded": True}
                            rec.update(redecode={"chars": len(text), "avg_logprob": alp, "compression_ratio": decoded["compression_ratio"],
                                                 "tokens": len(decoded["tokens"]), "cap_reached": decoded["cap_reached"],
                                                 "seconds": decoded["seconds"], "same_text": text == before["text"]})
                            traces[i] = tr
                        folded = collapse_window(text, alp, tr, rule)
                        rec.update(collapsed=folded["collapsed"], collapse=folded["record"],
                                   cr_after=folded["compression_ratio_after"], still_flagged=folded["still_flagged"])
                        if folded["still_flagged"]:
                            segments[i] = {**before, "text": text, "avg_logprob": alp}
                            failures.append((i, f"guard:{rule} after {variant}"))
                            rec.update(action="blank")
                            text_after = ""
                        else:
                            segments[i] = {**before, "text": folded["text"], "avg_logprob": alp}
                            rec.update(action=variant)
                            text_after = folded["text"]
                    rec["chars_after"] = len(text_after)
                    records[variant].append(rec)
                    changed.append({"film": film, "variant": variant, "window": i, "before": before["text"], "after": text_after,
                                    "action": rec["action"]})
                variant_docs[variant] = (segments, traces, failures)
                work_out = out_root / variant / film / work.name
                decode.link_audio(work_out, work)
                experiment = {"recipe": RECIPE_LABEL, "variant": variant, "rule": rule, "rule_def": scan.RULES[rule],
                              "repeat_params": repeat_params(rule), "no_repeat_ngram_size": NO_REPEAT if variant == "redecode" else None,
                              "windows": windows, "records": records[variant], "decoder_load_s": decoder.load_s}
                decode.write_asr(work_out, asr, segments, traces, failures, experiment, f"{RECIPE_LABEL}:{rule}:{variant}")
                work_outs[(variant, film)] = work_out
            per_film[film] = {"windows": windows, "records": records}
        del decoder
        import gc

        gc.collect()
        align_result = workers.run_worker("align", write_align_jobs(work_outs, out_root / "jobs-align.json"), out_root / "logs")
    wall = round(common.timed() - started, 1)
    peak = sampler.stop()
    results: dict[str, Any] = {}
    for film in films:
        work = common.FILMS[film]["work"]
        reference = common.v14.load_reference_doc(film)
        before = common.v14.cer_summary(common.v14.official_cer(reference, common.read_json(work / artifacts.ALIGN)))
        row: dict[str, Any] = {"windows": per_film[film]["windows"], "before": before, "variants": {}}
        for variant in VARIANTS:
            align_doc = common.read_json(work_outs[(variant, film)] / artifacts.ALIGN)
            after = common.v14.cer_summary(common.v14.official_cer(reference, align_doc))
            recs = per_film[film]["records"][variant]
            row["variants"][variant] = {"after": after, "delta": {k: after[k] - before[k] for k in ("S", "D", "I")},
                                        "delta_edits": sum(after[k] - before[k] for k in ("S", "D", "I")),
                                        "blanked": sum(1 for r in recs if r["action"] == "blank"),
                                        "kept": sum(1 for r in recs if r["action"] != "blank"),
                                        "chars_before": sum(r["chars_before"] for r in recs),
                                        "chars_after": sum(r["chars_after"] for r in recs), "records": recs}
        results[film] = row
    common.write_json(out_root / "changed-windows.json", changed)
    report = {"rule": rule, "rule_def": scan.RULES[rule], "repeat_params": repeat_params(rule), "variants": VARIANTS,
              "films": results, "gpu_run": 1, "wall_s": wall, "vram_peak_mib": peak,
              "align": {k: align_result[k] for k in ("wall_s", "vram_peak_mib", "exit_code")}, "preflight": preflight}
    common.write_json(common.ticket_dir(TICKET) / f"actions-{rule}.json", report)
    return report


__all__ = ["NO_REPEAT", "RECIPE_LABEL", "VARIANTS", "collapse_window", "flagged_windows", "guard_signal", "repeat_params", "run",
           "write_align_jobs"]
