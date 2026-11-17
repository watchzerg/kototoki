"""batch-run-fixes 09 第二层测量：逐窗 Whisper `no_speech_prob`。

子命令（从仓库根目录，用产品环境）：

- `probe`：在少量文件上验证两件事——完整解码（产品参数＋`return_no_speech_prob`）逐 token 复现
  `asr.json` 的 trace；`max_length=1` 的单步解码给出的 `no_speech_prob` 与完整解码相同。GPU。
- `measure`：对全部工作目录逐窗做编码＋单步解码，取 `no_speech_prob`，另算窗口能量；每个文件写一份
  `.local/asr-nospeech/measure/<work_id>.jsonl`，已有的跳过（可续跑）。GPU，持 `.local/gpu.lock`。
- `report`：离线汇总 `measure/` 与 `asr.json`／`align.json`，写 `.local/asr-nospeech/report.md`。

产物含窗口文字，只写 `.local/`。产品包不导入本包；本包只读调用 `kototoki.*`。
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".local" / "asr-nospeech"
SOURCES = [("batch", ROOT / ".local/work/jav_best_copy-15fff3e12253", "*"),
           ("sealed", Path("D:/jav_best_copy_work"), "*/*")]
# 有参考字幕的两部样本片（v14 的对照工作目录）：用来查误杀——被规则拦下的窗口与参考 cue 的时间重叠
REFERENCES = ROOT / ".local/fullfilm-comparison/fullfilm-v1/corpus/references"
FILMS = {"hf-ii": ROOT / ".local/q3-product-fullfilm/work/input-7c924c80249b/8d2f3e76dd0c",
         "hf-iii": ROOT / ".local/asr-robustness-v14/01/hf-iii/fb2e0da74018"}
MODEL = ROOT / ".local/models/faster-whisper-large-v3"
MEL = ROOT / ".local/models/w0-assets"
HALLUCINATION_PREFIXES = ("ご視聴ありがとうございました", "ありがとうございました", "ありがとうございます",
                          "チャンネル登録", "by H.", "おわり", "字幕")


def work_dirs() -> list[tuple[str, Path]]:
    found = [(f"film:{name}", path) for name, path in FILMS.items()]
    for group, base, pattern in SOURCES:
        for path in sorted(base.glob(pattern)):
            if (path / "asr.json").is_file() and (path / "audio-16k.wav").is_file():
                found.append((group, path))
    return found


def work_id(path: Path) -> str:
    return path.name.split("__")[-1]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class NoSpeech:
    """产品 `WhisperAsr`（同模型、同特征、同提示）之上加 `return_no_speech_prob`。"""

    def __init__(self) -> None:
        from kototoki.asr_whisper import WhisperAsr
        from faster_whisper.tokenizer import Tokenizer
        from kototoki.recipes import W0

        self.asr = WhisperAsr(MODEL, MEL)
        model = self.asr._model
        tokenizer = Tokenizer(model.hf_tokenizer, model.model.is_multilingual, task=W0["task"], language=W0["language"])
        options = self.asr.options
        self.prompt = model.get_prompt(tokenizer, [], without_timestamps=options["without_timestamps"],
                                       prefix=options["prefix"], hotwords=options["hotwords"])
        self.kwargs = {name: options[name] for name in (
            "beam_size", "patience", "length_penalty", "suppress_blank", "suppress_tokens",
            "no_repeat_ngram_size", "repetition_penalty")}
        self.model = model

    def window(self, audio: Any, start: int, end: int, full: bool) -> dict[str, Any]:
        from kototoki.asr_whisper import features
        import numpy as np

        mel = features(audio[start:end], self.asr._filters)
        encoder = self.model.encode(mel[np.newaxis])
        max_length = self.model.max_length if full else 1
        result = self.model.model.generate(encoder, [self.prompt], **self.kwargs, max_length=max_length,
                                           return_scores=True, return_no_speech_prob=True)[0]
        return {"no_speech_prob": float(result.no_speech_prob), "tokens": list(result.sequences_ids[0]) if result.sequences_ids else []}


def energy(audio: Any, start: int, end: int, spans: list[list[float]]) -> dict[str, float]:
    import numpy as np

    def dbfs(x: Any) -> float:
        rms = float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if len(x) else 0.0
        return round(20 * math.log10(rms), 2) if rms > 0 else -120.0

    speech = [audio[int(a * 16000):int(b * 16000)] for a, b in spans] or [audio[start:end]]
    return {"rms_dbfs": dbfs(audio[start:end]), "speech_rms_dbfs": dbfs(np.concatenate(speech)),
            "peak_dbfs": dbfs(np.array([np.abs(audio[start:end]).max()]))}


def probe(args: argparse.Namespace) -> None:
    from kototoki.workers.gpu import read_wav

    engine = NoSpeech()
    dirs = work_dirs()
    failed_align = {work_id(p) for _, p in dirs if (p / "align.json").is_file()
                    and any(r["failure"] for r in load_json(p / "align.json")["alignment_records"])}
    picks = [p for _, p in dirs if work_id(p) in failed_align][:2] + [p for _, p in dirs][:1]
    rows, mismatched = [], 0
    for path in picks:
        asr = load_json(path / "asr.json")
        audio, _ = read_wav(path / "audio-16k.wav")
        segments, traces = asr["original_segments"], asr["asr_traces"]
        order = sorted(range(len(segments)), key=lambda i: segments[i]["end"] - segments[i]["start"])
        chosen = sorted(set(order[:args.per_file // 2] + list(range(0, len(segments), max(1, len(segments) // (args.per_file // 2))))))
        for index in chosen:
            seg, trace = segments[index], traces[index]
            if trace is None:
                continue
            full = engine.window(audio, seg["start_sample"], seg["end_sample"], full=True)
            step = engine.window(audio, seg["start_sample"], seg["end_sample"], full=False)
            same_tokens = full["tokens"] == trace["tokens"]
            mismatched += not same_tokens
            rows.append({"work": work_id(path), "index": index, "dur": round(seg["end"] - seg["start"], 3),
                         "same_tokens": same_tokens, "nsp_full": full["no_speech_prob"],
                         "nsp_step": step["no_speech_prob"],
                         "nsp_diff": abs(full["no_speech_prob"] - step["no_speech_prob"])})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "probe.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"windows {len(rows)}, token mismatches {mismatched}, "
          f"max nsp diff {max(r['nsp_diff'] for r in rows):.3g}")
    for row in rows[:12]:
        print(row)


def measure(args: argparse.Namespace) -> None:
    from experiments.asr_robustness_v14.common import gpu_lock
    from kototoki.workers.gpu import read_wav

    target = OUT / "measure"
    target.mkdir(parents=True, exist_ok=True)
    dirs = work_dirs()
    with gpu_lock("asr-nospeech measure"):
        engine = NoSpeech()
        started = time.perf_counter()
        for number, (group, path) in enumerate(dirs, 1):
            out = target / f"{work_id(path)}.jsonl"
            if out.is_file():
                continue
            asr = load_json(path / "asr.json")
            audio, _ = read_wav(path / "audio-16k.wav")
            lines, t0 = [], time.perf_counter()
            for index, (seg, chunk) in enumerate(zip(asr["original_segments"], asr["chunks"], strict=True)):
                row = {"index": index, **engine.window(audio, seg["start_sample"], seg["end_sample"], full=False),
                       **energy(audio, seg["start_sample"], seg["end_sample"], chunk.get("segments") or [])}
                row.pop("tokens")
                lines.append(json.dumps(row))
            tmp = out.with_suffix(".tmp")
            tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
            tmp.replace(out)
            print(f"[{number}/{len(dirs)}] {group} {work_id(path)}: {len(lines)} windows "
                  f"{time.perf_counter() - t0:.1f}s, total {time.perf_counter() - started:.0f}s", flush=True)
    print("done", flush=True)


def report(args: argparse.Namespace) -> None:
    sys.path.insert(0, str(ROOT))
    from kototoki.judge import normalize

    rows = []
    for group, path in work_dirs():
        measured = OUT / "measure" / f"{work_id(path)}.jsonl"
        if not measured.is_file():
            continue
        asr = load_json(path / "asr.json")
        failed_asr = {entry["chunk_index"] for entry in asr["failed_windows"]}
        align_failed = set()
        if (path / "align.json").is_file():
            align_failed = {r["segment_index"] for r in load_json(path / "align.json")["alignment_records"]
                            if r["failure"]}
        signals = [json.loads(line) for line in measured.read_text(encoding="utf-8").splitlines() if line]
        spans = []
        if group.startswith("film:"):
            reference = json.loads((REFERENCES / f"{group[5:]}-full.json").read_text(encoding="utf-8-sig"))
            spans = [(s["start"], s["end"], s.get("original_text") or s.get("text") or "") for s in reference["spans"]]
        for seg, sig in zip(asr["original_segments"], signals, strict=True):
            overlap = [t for a, b, t in spans if a < seg["end"] and b > seg["start"]]
            text = seg["text"]
            if sig["index"] in failed_asr or not text.strip():
                continue
            try:
                chars = len(normalize(text).text)
            except ValueError:
                chars = len(text)
            dur = seg["end"] - seg["start"]
            rows.append({**sig, "group": group, "work": work_id(path), "text": text, "dur": dur, "chars": chars,
                         "cps": chars / dur, "avg_logprob": seg["avg_logprob"],
                         "align_failed": sig["index"] in align_failed, "reference": overlap if spans else None,
                         "phrase": text.strip().startswith(HALLUCINATION_PREFIXES) and len(text.strip()) <= 20})
    (OUT / "rows.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                                     encoding="utf-8")
    lines = [f"# no_speech_prob 测量（batch-run-fixes 09）", "", f"非空窗口 {len(rows)}", ""]

    def table(title: str, rules: dict[str, Any]) -> None:
        lines.extend([f"## {title}", "", "| 规则 | 命中 | 其中 >20 字/秒 | 新增（≤20 字/秒） | 新增中套话 | 新增中 ≥2 s |",
                      "| --- | --- | --- | --- | --- | --- |"])
        for name, rule in rules.items():
            hit = [r for r in rows if rule(r)]
            new = [r for r in hit if r["cps"] <= 20]
            lines.append(f"| {name} | {len(hit)} | {len(hit) - len(new)} | {len(new)} | "
                         f"{sum(r['phrase'] for r in new)} | {sum(r['dur'] >= 2 for r in new)} |")
        lines.append("")

    table("OpenAI 规则（no_speech_prob > N 且 avg_logprob < L）", {
        f"nsp>{n} & lp<{lp}": (lambda r, n=n, lp=lp: r["no_speech_prob"] > n and r["avg_logprob"] < lp)
        for n in (0.4, 0.5, 0.6, 0.8) for lp in (-0.5, -0.8, -1.0)})
    table("只看 no_speech_prob", {f"nsp>{n}": (lambda r, n=n: r["no_speech_prob"] > n)
                                  for n in (0.3, 0.5, 0.6, 0.7, 0.8, 0.9)})
    phrase = [r for r in rows if r["phrase"]]
    lines.extend(["## 套话窗口的信号分布", "", "| 时长 | 窗口数 | nsp 中位 | lp 中位 | 能量中位 dBFS |",
                  "| --- | --- | --- | --- | --- |"])

    def median(values: list[float]) -> float:
        values = sorted(values)
        return values[len(values) // 2] if values else float("nan")

    for label, lo, hi in (("<0.3 s", 0, 0.3), ("0.3–2 s", 0.3, 2), ("≥2 s", 2, 1e9)):
        for name, subset in (("套话", phrase), ("其他", [r for r in rows if not r["phrase"]])):
            sel = [r for r in subset if lo <= r["dur"] < hi]
            lines.append(f"| {label} {name} | {len(sel)} | {median([r['no_speech_prob'] for r in sel]):.3f} | "
                         f"{median([r['avg_logprob'] for r in sel]):.2f} | {median([r['speech_rms_dbfs'] for r in sel]):.1f} |")
    lines.append("")
    lines.extend(["## no_speech_prob 分布（全部非空窗口）", "", "| 区间 | 窗口数 | 套话 |", "| --- | --- | --- |"])
    for lo in (0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        sel = [r for r in rows if lo <= r["no_speech_prob"] < lo + 0.1 or (lo == 0.9 and r["no_speech_prob"] >= 1)]
        lines.append(f"| {lo:.1f}–{lo + 0.1:.1f} | {len(sel)} | {sum(r['phrase'] for r in sel)} |")
    lines.append("")
    lines.extend(["## 高 no_speech_prob（>0.6）且 ≤20 字/秒的窗口文字（前 60 种）", ""])
    for text, count in Counter(r["text"][:30] for r in rows
                               if r["no_speech_prob"] > 0.6 and r["cps"] <= 20).most_common(60):
        lines.append(f"- {count} × {text}")
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUT / "report.md")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m experiments.asr_nospeech")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("probe")
    p.add_argument("--per-file", type=int, default=20)
    sub.add_parser("measure")
    sub.add_parser("report")
    args = parser.parse_args()
    {"probe": probe, "measure": measure, "report": report}[args.command](args)


if __name__ == "__main__":
    main()
