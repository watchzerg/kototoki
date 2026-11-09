"""A0：w0 每个窗口的守卫信号（压缩比、触顶、`avg_logprob`）与对参考的逐窗 CER，按若干阈值规则统计被标记窗口。

- 压缩比：Whisper 定义，窗口文字 UTF-8 字节数／zlib 压缩后字节数（空文字记 0）。
- 触顶：CT2 的 `max_length` 448 是解码器总长度（含 prompt 4 个 token），`sequences_ids` 不含 EOT，所以
  `len(tokens) + len(prompt) >= max_length - 1` 记为触顶（EOT 可能占掉最后一格）。
- `avg_logprob`：`asr.json` 段里的值（`generate` 按 Whisper 的长度归一）。
- 逐窗 CER：把窗口当作 cue，与参考 cue 按时间重叠连成单元（`asr_source.overlap_units`），单元 CER 归到其中每个窗口；
  没有参考重叠的窗口为 inserted（CER 无定义，只记字符数）。
- 置空收益估计：只去掉该窗文字后单元编辑距离的变化（负数＝置空更好）；多窗共一单元时逐窗单独估。

规则以参数表示：`cr_max`（压缩比上限）、`cap`（触顶即标）、`alp_min`（`avg_logprob` 下限）、`alp_requires_cr`
（`avg_logprob` 条件另须压缩比超过此值）。报告只含计数与指标，不含窗口文字。
"""

from __future__ import annotations

import statistics
import zlib
from pathlib import Path
from typing import Any

from experiments.asr_robustness_v14 import common
from experiments.quality_v5 import asr_source
from kototoki import artifacts
from kototoki_eval.schema import normalize

MAX_LENGTH = 448
LIGHT_MAX = asr_source.LIGHT_MAX

RULES: dict[str, dict[str, Any]] = {
    # 研究文档 §4.1 写的 Whisper 默认阈值组合：压缩比 >2.4，或触顶，或（avg_logprob <−1.0 且压缩比 >2.4）
    "doc-default": {"cr_max": 2.4, "cap": True, "alp_min": -1.0, "alp_requires_cr": 2.4},
    # Whisper 原版温度回退的触发条件是"或"：压缩比 >2.4 或 avg_logprob <−1.0
    "whisper-or": {"cr_max": 2.4, "cap": True, "alp_min": -1.0, "alp_requires_cr": None},
    "cr2.0-alp1.0": {"cr_max": 2.0, "cap": True, "alp_min": -1.0, "alp_requires_cr": None},
    "cr1.8-alp0.8": {"cr_max": 1.8, "cap": True, "alp_min": -0.8, "alp_requires_cr": None},
    "alp0.7": {"cr_max": None, "cap": True, "alp_min": -0.7, "alp_requires_cr": None},
    "alp0.5": {"cr_max": None, "cap": True, "alp_min": -0.5, "alp_requires_cr": None},
}


def compression_ratio(text: str) -> float:
    data = text.encode("utf-8")
    return len(data) / len(zlib.compress(data)) if data else 0.0


def cap_reached(trace: dict[str, Any] | None) -> bool:
    if not trace:
        return False
    return len(trace["tokens"]) + len(trace.get("prompt") or []) >= MAX_LENGTH - 1


def flagged(signal: dict[str, Any], rule: dict[str, Any]) -> bool:
    cr, alp = signal["compression_ratio"], signal["avg_logprob"]
    if rule.get("cap") and signal["cap_reached"]:
        return True
    if rule.get("cr_max") is not None and cr > rule["cr_max"]:
        return True
    if rule.get("alp_min") is not None and alp is not None and alp < rule["alp_min"]:
        need = rule.get("alp_requires_cr")
        return need is None or cr > need
    return False


def window_signals(asr: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for index, (segment, trace) in enumerate(zip(asr["original_segments"], asr["asr_traces"])):
        text = segment["text"]
        out.append({"index": index, "start": segment["start"], "end": segment["end"],
                    "duration_s": round(segment["end"] - segment["start"], 3),
                    "raw_chars": len(text), "chars": len(normalize(text).text),
                    "compression_ratio": round(compression_ratio(text), 4),
                    "tokens": len(trace["tokens"]) if trace else None, "cap_reached": cap_reached(trace),
                    "avg_logprob": segment["avg_logprob"], "failed": trace is None})
    return out


def attach_reference(signals: list[dict[str, Any]], asr: dict[str, Any], reference: list[dict[str, Any]]) -> None:
    """按时间重叠把窗口与参考 cue 连成单元，给每个窗口写单元 CER、参考字符数、桶与置空收益估计。"""
    windows = [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in asr["original_segments"]]
    for refs, prods in asr_source.overlap_units(reference, windows):
        ref_text = normalize("".join(reference[i]["text"] for i in refs)).text
        hyp_text = normalize("".join(windows[j]["text"] for j in prods)).text
        edits = asr_source.edit_distance(ref_text, hyp_text)
        unit_cer = edits / len(ref_text) if ref_text else None
        for j in prods:
            without = normalize("".join(windows[k]["text"] for k in prods if k != j)).text
            delta = asr_source.edit_distance(ref_text, without) - edits
            signals[j].update(unit_ref_cues=len(refs), unit_windows=len(prods), unit_ref_chars=len(ref_text),
                              unit_cer=None if unit_cer is None else round(unit_cer, 4), unit_edits=edits,
                              blank_delta_edits=delta,
                              bucket=asr_source.bucket_of("".join(reference[i]["text"] for i in refs),
                                                          "".join(windows[k]["text"] for k in prods), unit_cer))
    for s in signals:
        s.setdefault("unit_ref_cues", 0)
        s.setdefault("unit_windows", 1)
        s.setdefault("unit_ref_chars", 0)
        s.setdefault("unit_cer", None)
        s.setdefault("unit_edits", s["chars"])
        s.setdefault("blank_delta_edits", -s["chars"])
        s.setdefault("bucket", "inserted")


def quantiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"n": 0, "mean": None, "p25": None, "p50": None, "p75": None, "min": None, "max": None}
    ordered = sorted(values)
    pick = lambda p: ordered[min(len(ordered) - 1, int(p * len(ordered)))]  # noqa: E731
    return {"n": len(values), "mean": round(statistics.fmean(values), 4), "p25": round(pick(0.25), 4),
            "p50": round(pick(0.5), 4), "p75": round(pick(0.75), 4), "min": round(ordered[0], 4),
            "max": round(ordered[-1], 4)}


def rule_table(signals: list[dict[str, Any]]) -> dict[str, Any]:
    table = {}
    for name, rule in RULES.items():
        hit = [s for s in signals if flagged(s, rule)]
        rest = [s for s in signals if not flagged(s, rule)]
        table[name] = {
            "rule": rule, "flagged_windows": len(hit), "flagged_chars": sum(s["chars"] for s in hit),
            "flagged_unit_ref_chars": sum(s["unit_ref_chars"] for s in hit),
            "flagged_cer": quantiles([s["unit_cer"] for s in hit if s["unit_cer"] is not None]),
            "flagged_heavy_or_inserted": sum(1 for s in hit if s["bucket"] in ("heavy", "inserted")),
            "unflagged_cer": quantiles([s["unit_cer"] for s in rest if s["unit_cer"] is not None]),
            "blank_delta_edits_sum": sum(s["blank_delta_edits"] for s in hit),
            "flagged_indices": [s["index"] for s in hit],
        }
    return table


def bucket_signals(signals: list[dict[str, Any]]) -> dict[str, Any]:
    out = {}
    for bucket in ("exact", "light", "heavy", "inserted"):
        rows = [s for s in signals if s["bucket"] == bucket]
        out[bucket] = {"windows": len(rows), "chars": sum(s["chars"] for s in rows),
                       "avg_logprob": quantiles([s["avg_logprob"] for s in rows if s["avg_logprob"] is not None]),
                       "compression_ratio": quantiles([s["compression_ratio"] for s in rows])}
    return out


def analyze(film: str) -> dict[str, Any]:
    work = common.FILMS[film]["work"]
    asr = common.read_json(work / artifacts.ASR)
    reference = common.reference_cues(film)
    signals = window_signals(asr)
    attach_reference(signals, asr, reference)
    worst = sorted((s for s in signals if s["unit_cer"] is not None), key=lambda s: -s["unit_cer"])[:15]
    report = {
        "film": film, "windows": len(signals), "failed_windows": sum(1 for s in signals if s["failed"]),
        "empty_text_windows": sum(1 for s in signals if s["chars"] == 0 and not s["failed"]),
        "cap_reached_windows": sum(1 for s in signals if s["cap_reached"]),
        "tokens": quantiles([s["tokens"] for s in signals if s["tokens"] is not None]),
        "compression_ratio": quantiles([s["compression_ratio"] for s in signals]),
        "avg_logprob": quantiles([s["avg_logprob"] for s in signals if s["avg_logprob"] is not None]),
        "unit_cer": quantiles([s["unit_cer"] for s in signals if s["unit_cer"] is not None]),
        "buckets": bucket_signals(signals),
        "rules": rule_table(signals),
        "worst_windows": [{k: s[k] for k in ("index", "duration_s", "chars", "unit_ref_chars", "unit_cer", "bucket",
                                              "compression_ratio", "avg_logprob", "tokens", "blank_delta_edits")}
                          for s in worst],
    }
    common.write_json(common.ROOT / "01" / f"signals-{film}.json", report)
    common.write_json(common.ROOT / "01" / f"windows-{film}.json", signals)
    return report


def select_windows(film: str, rule: str) -> list[int]:
    """A1／A2 用：按规则名返回被标记窗口的序号（从 01 的逐窗表读，没有就现算）。"""
    path = common.ROOT / "01" / f"windows-{film}.json"
    if path.is_file():
        signals = common.read_json(path)
    else:
        work = common.FILMS[film]["work"]
        asr = common.read_json(work / artifacts.ASR)
        signals = window_signals(asr)
        attach_reference(signals, asr, common.reference_cues(film))
    return [s["index"] for s in signals if flagged(s, RULES[rule])]


def run(films: tuple[str, ...]) -> dict[str, Any]:
    reports = {film: analyze(film) for film in films}
    summary = {film: {"windows": r["windows"], "cap_reached": r["cap_reached_windows"],
                      "cr_max": r["compression_ratio"]["max"], "alp_min": r["avg_logprob"]["min"],
                      "rules": {name: {k: row[k] for k in ("flagged_windows", "flagged_chars", "blank_delta_edits_sum",
                                                             "flagged_heavy_or_inserted")}
                                for name, row in r["rules"].items()}}
               for film, r in reports.items()}
    common.write_json(common.ROOT / "01" / "signals.json", summary)
    return summary


__all__ = ["RULES", "analyze", "attach_reference", "cap_reached", "compression_ratio", "flagged", "run",
           "select_windows", "window_signals", "Path"]
