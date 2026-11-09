"""票据 01 A3：对盘点到的每个 w0 样本逐窗算四个信号，按规则候选统计被标记窗口，并把被任一规则标记的窗口文字写到
`.local/asr-robustness-v15/01/flagged/`（只供 Opus 判读；报告 `scan.json` 与逐窗表 `windows/<sample>.json` 不含文字）。

四个信号：压缩比、触顶、`avg_logprob`（复用 v14 `signals`），显式重复检测（`repeat.signals`）。
规则候选（`RULES`）：v14 的 `doc-default`、`whisper-or`；`repeat`（只看重复检测）；`repeat-or-cr2.4`（重复检测 或 压缩比 >2.4）；
另给两档校准用的重复阈值 `repeat-loose`／`repeat-strict`，Opus 判读覆盖全部候选的并集，便于事后比较每条规则的误报。

安全网判据（§4.1）：规则须标记 HF III 第 51 窗（`product-hf-iii` 的 index 51），且在全部样本上对 Opus 判为"正常语音"的窗口
零标记；多条满足时取标记最多的（召回优先）。`judge_rules` 把 Opus 的判读合并回来算这件事。
"""

from __future__ import annotations

from typing import Any

from experiments.asr_robustness_v14 import signals as v14_signals
from experiments.asr_robustness_v15 import common, inventory, repeat
from experiments.quality_v5 import asr_source
from kototoki_eval.schema import normalize

TICKET = "01"
KNOWN_LOOP = ("product-hf-iii", 51)

REPEAT_RULES: dict[str, dict[str, Any]] = {
    "repeat": dict(repeat.RULE_DEFAULT),
    "repeat-loose": {"min_period": 2, "min_copies": 4, "min_coverage": 0.4, "min_count": 4, "min_length": 3},
    "repeat-strict": {"min_period": 2, "min_copies": 10, "min_coverage": 0.5, "min_count": 10, "min_length": 3},
}
RULES: dict[str, dict[str, Any]] = {
    "doc-default": {"v14": "doc-default"},
    "whisper-or": {"v14": "whisper-or"},
    "repeat": {"repeat": "repeat"},
    "repeat-or-cr2.4": {"repeat": "repeat", "cr_max": 2.4},
    "repeat-loose": {"repeat": "repeat-loose"},
    "repeat-strict": {"repeat": "repeat-strict"},
}
VERDICTS = ("hallucination", "normal", "unsure")


def flagged(window: dict[str, Any], rule: dict[str, Any]) -> bool:
    if "v14" in rule and v14_signals.flagged(window, v14_signals.RULES[rule["v14"]]):
        return True
    if "repeat" in rule and repeat.flagged(window["repeat"][rule["repeat"]], REPEAT_RULES[rule["repeat"]]):
        return True
    return rule.get("cr_max") is not None and window["compression_ratio"] > rule["cr_max"]


def repeat_signals(text: str) -> dict[str, dict[str, Any]]:
    """每档重复阈值各算一份信号（见 `repeat.signals`）。"""
    return {name: repeat.signals(text, params) for name, params in REPEAT_RULES.items()}


def window_rows(sample: dict[str, Any], loaded: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    offset = loaded["source_start_s"]
    for index, (segment, trace) in enumerate(zip(loaded["segments"], loaded["traces"])):
        text = segment["text"]
        rows.append({"sample": sample["id"], "index": index, "start": round(segment["start"] + offset, 3),
                     "end": round(segment["end"] + offset, 3), "duration_s": round(segment["end"] - segment["start"], 3),
                     "raw_chars": len(text), "chars": len(normalize(text).text),
                     "compression_ratio": round(v14_signals.compression_ratio(text), 4),
                     "tokens": len(trace["tokens"]) if trace else None, "cap_reached": v14_signals.cap_reached(trace),
                     "avg_logprob": segment.get("avg_logprob"), "failed": trace is None, "repeat": repeat_signals(text)})
    return rows


PARLIAMENT_REFERENCE = common.LOCAL / "parliament-baselines" / "2026-10-05-v1" / "reference-raw.json"


def reference_text(sample: dict[str, Any], start: float, end: float, cache: dict[str, list[dict[str, Any]]]) -> str | None:
    """与窗口时间重叠的参考文字（HF II／III 用正式参考，国会用 YODAS2 原字幕，准确度未知）；没有参考为 None。"""
    key = sample["film"] or ("parliament" if sample["group"] == "parliament" else None)
    if key is None:
        return None
    if key not in cache:
        cache[key] = (common.v14.reference_cues(key) if key != "parliament"
                      else [{"start": s["start"], "end": s["end"], "text": s["text"]}
                            for s in common.read_json(PARLIAMENT_REFERENCE)["spans"]])
    hit = [c["text"] for c in cache[key] if min(end, c["end"]) - max(start, c["start"]) > 0]
    return "".join(hit) if hit else ""


def run(limit_groups: tuple[str, ...] | None = None) -> dict[str, Any]:
    out = common.ticket_dir(TICKET)
    samples = [s for s in inventory.discover() if limit_groups is None or s["group"] in limit_groups]
    cues_by_film: dict[str, list[dict[str, Any]]] = {}
    inventory_rows, per_sample, flagged_all = [], {}, []
    seen_texts: set[str] = set()
    for sample in samples:
        loaded = inventory.load_sample(sample)
        rows = window_rows(sample, loaded)
        common.write_json(out / "windows" / f"{sample['id']}.json", rows)
        table = {}
        for name, rule in RULES.items():
            hit = [r for r in rows if flagged(r, rule)]
            table[name] = {"flagged_windows": len(hit), "flagged_chars": sum(r["chars"] for r in hit),
                           "flagged_indices": [r["index"] for r in hit]}
        union = sorted({i for row in table.values() for i in row["flagged_indices"]})
        for i in union:
            text = loaded["segments"][i]["text"]
            flagged_all.append({"sample": sample["id"], "group": sample["group"], "film": sample["film"], "index": i,
                                "start": rows[i]["start"], "end": rows[i]["end"], "duration_s": rows[i]["duration_s"],
                                "signals": {k: rows[i][k] for k in ("chars", "compression_ratio", "avg_logprob", "tokens",
                                                                   "cap_reached", "repeat")},
                                "rules": [name for name, row in table.items() if i in row["flagged_indices"]],
                                "text": text, "duplicate_text": text in seen_texts,
                                "reference": reference_text(sample, rows[i]["start"], rows[i]["end"], cues_by_film)})
            seen_texts.add(text)
        per_sample[sample["id"]] = {"group": sample["group"], "film": sample["film"], "windows": len(rows),
                                    "failed_windows": sum(1 for r in rows if r["failed"]),
                                    "cap_reached": sum(1 for r in rows if r["cap_reached"]),
                                    "cr_max": max((r["compression_ratio"] for r in rows), default=None),
                                    "tandem_copies_max": max((r["repeat"]["repeat"]["tandem"]["copies"] for r in rows
                                                              if r["repeat"]["repeat"]["tandem"]), default=None),
                                    "rules": table, "union_flagged": len(union)}
        inventory_rows.append({**sample, "windows": loaded["windows"], "recipe": loaded["recipe"],
                               "recipe_is_w0": loaded["recipe_is_w0"], "pcm_sha256": loaded["pcm_sha256"]})
    common.write_json(out / "inventory.json", {"samples": inventory_rows, "missing": inventory.MISSING,
                                                "w0_recipe_hash": inventory.W0_RECIPE_HASH})
    common.write_json(out / "flagged" / "windows.json", flagged_all)
    totals = {name: {"flagged_windows": sum(s["rules"][name]["flagged_windows"] for s in per_sample.values()),
                     "flagged_chars": sum(s["rules"][name]["flagged_chars"] for s in per_sample.values()),
                     "samples_with_flags": sum(1 for s in per_sample.values() if s["rules"][name]["flagged_windows"])}
              for name in RULES}
    known = per_sample.get(KNOWN_LOOP[0], {}).get("rules", {})
    report = {"samples": len(per_sample), "windows": sum(s["windows"] for s in per_sample.values()),
              "rules": {name: dict(RULES[name], repeat_params=REPEAT_RULES.get(RULES[name].get("repeat"))) for name in RULES},
              "totals": totals, "known_loop_flagged": {name: KNOWN_LOOP[1] in known.get(name, {}).get("flagged_indices", [])
                                                      for name in RULES},
              "union_flagged_windows": len(flagged_all), "union_unique_texts": len({f["text"] for f in flagged_all}),
              "per_sample": per_sample}
    common.write_json(out / "scan.json", report)
    return {k: v for k, v in report.items() if k != "per_sample"}


def judge_rules(judgements_path: str | None = None) -> dict[str, Any]:
    """合并 Opus 判读（`flagged/judgements.json`：`[{sample, index, verdict, reason}]`），算每条规则的误报与安全网判据。"""
    out = common.ticket_dir(TICKET)
    flagged_all = common.read_json(out / "flagged" / "windows.json")
    judgements = common.read_json(judgements_path or out / "flagged" / "judgements.json")
    verdict = {(j["sample"], j["index"]): j["verdict"] for j in judgements}
    missing = [(f["sample"], f["index"]) for f in flagged_all if (f["sample"], f["index"]) not in verdict]
    bad = [v for v in verdict.values() if v not in VERDICTS]
    if missing or bad:
        raise ValueError(f"judgements incomplete: missing {len(missing)}, invalid {bad[:5]}")
    per_rule = {}
    for name in RULES:
        hit = [f for f in flagged_all if name in f["rules"]]
        counts = {v: sum(1 for f in hit if verdict[(f["sample"], f["index"])] == v) for v in VERDICTS}
        normal = [{"sample": f["sample"], "index": f["index"]} for f in hit if verdict[(f["sample"], f["index"])] == "normal"]
        catches_known = any(f["sample"] == KNOWN_LOOP[0] and f["index"] == KNOWN_LOOP[1] for f in hit)
        per_rule[name] = {"flagged": len(hit), **counts, "normal_windows": normal, "catches_known_loop": catches_known,
                          "safety_net": catches_known and counts["normal"] == 0}
    total_hallucination = sum(1 for v in verdict.values() if v == "hallucination")
    unique_texts = {(f["sample"], f["index"]): f["text"] for f in flagged_all}
    for name, row in per_rule.items():
        row["hallucination_recall"] = round(row["hallucination"] / total_hallucination, 4) if total_hallucination else None
        row["unique_texts_flagged"] = len({unique_texts[(f["sample"], f["index"])] for f in flagged_all if name in f["rules"]})
    passing = [name for name, row in per_rule.items() if row["safety_net"]]
    selected = max(passing, key=lambda n: per_rule[n]["flagged"]) if passing else None
    report = {"judged": len(verdict), "verdicts": {v: sum(1 for x in verdict.values() if x == v) for v in VERDICTS},
              "rules": per_rule, "passing": passing, "selected": selected,
              "fallback": None if selected else "doc-default (conservative safety net; no rule had zero normal-speech flags)"}
    common.write_json(out / "safety-net.json", report)
    return report


__all__ = ["KNOWN_LOOP", "REPEAT_RULES", "RULES", "VERDICTS", "flagged", "judge_rules", "repeat_signals", "run", "window_rows"]
