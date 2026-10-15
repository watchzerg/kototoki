"""ASR 候选第二轮（票据 12）：在产品当前 VAD 窗口上逐窗独立转写，写产品形状的 `asr.json`，再交给产品对齐 worker。

候选与当前 w0／x0 读同一份 `vad.json` 窗口（整数样本边界），各自原生接口、逐窗独立、无前文 conditioning、
无初始 prompt；输出 `asr.json` 与产品 `kototoki.workers.asr` 同结构（`original_segments` 与窗口一一对应），
因此 `kototoki.workers.align` 与 `kototoki_eval` 可原样复用。身份字段沿用源 `vad.json` 的上游 PCM，
`models` 换成候选 ready manifest 的文件 SHA256，`recipe_hash` 是候选标签的 SHA256（标签记在 `metadata.recipe_label`，不是产品配方）。

引擎：
- `qwen`：复用 `kototoki.asr_qwen.QwenAsr`（同 x0 的 BF16／SDPA／greedy／原生 processor），只换 checkpoint 目录。
- `hf-whisper`：Transformers `WhisperForConditionalGeneration` FP16，language ja、task transcribe、greedy、
  `no_repeat_ngram_size` 按模型卡评测设置（anime-whisper 为 5），不设初始 prompt。

命令（仓库根目录，`.venv`）：
  python -X utf8 -m experiments.quality_v5.asr_round2 transcribe --engine qwen|hf-whisper --manifest READY.json \\
      --source-work WORK_ID_DIR --out OUT_ID_DIR [--limit N]
  python -X utf8 -m experiments.quality_v5.asr_round2 jobs --out-root ROOT --config PRODUCT_JOBS_JSON
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
from typing import Any

SAMPLE_RATE = 16000
NO_REPEAT_NGRAM = 5
MAX_NEW_TOKENS = 440


class HfWhisperAsr:
    """Transformers Whisper checkpoint，逐窗 log-mel（原生 feature extractor，补齐到 30 s）＋greedy。"""

    def __init__(self, model_path: Path) -> None:
        import torch
        from transformers import WhisperForConditionalGeneration, WhisperProcessor

        if not torch.cuda.is_available():
            raise RuntimeError("ASR requires CUDA; CPU fallback is prohibited")
        self._torch = torch
        self._processor = WhisperProcessor.from_pretrained(model_path, local_files_only=True)
        self._model = WhisperForConditionalGeneration.from_pretrained(
            model_path, dtype=torch.float16, local_files_only=True).to("cuda:0").eval()
        self.metadata: dict[str, Any] = {"device": "cuda:0", "dtype": "float16", "language": "ja",
                                         "task": "transcribe", "num_beams": 1, "do_sample": False,
                                         "no_repeat_ngram_size": NO_REPEAT_NGRAM, "max_new_tokens": MAX_NEW_TOKENS,
                                         "initial_prompt": None, "previous_text_conditioning": False}

    def transcribe(self, audio: Any, chunks: list[dict[str, Any]]
                   ) -> tuple[list[dict[str, Any]], list[dict[str, Any] | None], list[tuple[int, str]]]:
        torch = self._torch
        segments, traces, failures = [], [], []
        for index, chunk in enumerate(chunks):
            start, end = chunk["start_sample"], chunk["end_sample"]
            segment = {"text": "", "start": chunk["start"], "end": chunk["end"],
                       "start_sample": start, "end_sample": end, "avg_logprob": None}
            try:
                features = self._processor.feature_extractor(
                    audio[start:end], sampling_rate=SAMPLE_RATE, return_tensors="pt").input_features
                with torch.inference_mode():
                    tokens = self._model.generate(features.to("cuda:0", torch.float16), language="ja",
                                                  task="transcribe", do_sample=False, num_beams=1,
                                                  no_repeat_ngram_size=NO_REPEAT_NGRAM,
                                                  max_new_tokens=MAX_NEW_TOKENS)
                text = self._processor.batch_decode(tokens, skip_special_tokens=True)[0].strip()
            except RuntimeError as error:
                segments.append(segment)
                traces.append(None)
                failures.append((index, f"{type(error).__name__}: {error}"))
                continue
            if tokens.shape[-1] >= MAX_NEW_TOKENS:
                failures.append((index, "max_new_tokens reached"))
            segments.append({**segment, "text": text})
            traces.append({"tokens": tokens[0].tolist(), "start_sample": start, "end_sample": end})
        return segments, traces, failures


def load_engine(engine: str, model_path: Path) -> Any:
    if engine == "qwen":
        from kototoki.asr_qwen import QwenAsr

        return QwenAsr(model_path)
    return HfWhisperAsr(model_path)


def transcribe(engine: str, manifest_path: Path, source: Path, out: Path, limit: int | None) -> dict[str, Any]:
    from kototoki import artifacts
    from kototoki.workers import gpu
    from kototoki.workers.protocol import fail_window, retained_text, validate_failed_windows

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    vad_bytes = (source / artifacts.VAD).read_bytes()
    vad = json.loads(vad_bytes)
    out.mkdir(parents=True, exist_ok=True)
    wav = out / artifacts.AUDIO_16K
    if not wav.exists():
        os.link(source / artifacts.AUDIO_16K, wav)
    audio, pcm = gpu.read_wav(wav)
    if pcm != vad["identity"]["upstream"][artifacts.AUDIO_16K]:
        raise ValueError("audio-16k.wav differs from the one vad.json was computed from")
    chunks = vad["chunks"][:limit] if limit else vad["chunks"]
    started = time.perf_counter()
    asr = load_engine(engine, Path(manifest["path"]))
    load_s = time.perf_counter() - started
    import torch

    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    segments, traces, failures = asr.transcribe(audio, chunks)
    inference_s = time.perf_counter() - started
    document: dict[str, Any] = {"schema_version": 1, "engine": engine, "offset_s": vad["offset_s"],
                                "input": vad["input"], "chunks": chunks, "original_segments": segments,
                                "asr_traces": traces, "failed_windows": []}
    for index, reason in failures:
        fail_window(document, index, reason)
    validate_failed_windows(document)
    metadata = {key: value for key, value in asr.metadata.items() if key not in ("model", "revision")}
    document.update(text=retained_text(document),
                    metadata={**metadata, "model": manifest["model_id"], "revision": manifest["model_revision"],
                              "candidate_engine": engine, "max_allocated_mib": torch.cuda.max_memory_allocated() / 2**20},
                    stages={"load_s": load_s, "inference_s": inference_s})
    label = f"quality-v5-12:{engine}:{manifest['model_id']}@{manifest['model_revision']}"
    document["metadata"]["recipe_label"] = label
    identity = artifacts.derived_identity(
        upstream={artifacts.AUDIO_16K: pcm, artifacts.VAD: artifacts.sha256_bytes(vad_bytes)},
        recipe_hash=artifacts.sha256_bytes(label.encode("utf-8")), models=manifest["files_sha256"])
    artifacts.write_artifact(out / artifacts.ASR, identity, document)
    return {"windows": len(chunks), "failed": len(failures), "characters": len(document["text"]),
            "load_s": round(load_s, 1), "inference_s": round(inference_s, 1),
            "max_allocated_mib": round(document["metadata"]["max_allocated_mib"])}


def write_align_jobs(out_root: Path, config_path: Path) -> Path:
    """`out_root/<id>/asr.json` 齐全后写产品对齐 worker 的 jobs 文件。"""
    from kototoki import artifacts, plan

    config = json.loads(config_path.read_text(encoding="utf-8"))["config"]
    files = [{"id": d.name, "work_dir": str(d), "inputs": {"wav": str(d / artifacts.AUDIO_16K), "asr": str(d / artifacts.ASR)}}
             for d in sorted(out_root.iterdir()) if (d / artifacts.ASR).is_file()]
    path = out_root / "jobs-align.json"
    path.write_text(json.dumps({"stage": "align", "recipe_hash": plan.recipe_hash("align"), "config": config,
                                "files": files}, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="ASR 候选第二轮（票据 12）")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("transcribe")
    p.add_argument("--engine", choices=("qwen", "hf-whisper"), required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--source-work", type=Path, required=True, help="含 vad.json 与 audio-16k.wav 的产品工作目录")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--limit", type=int, help="只转写前 N 个窗口（短窗资格确认）")
    p = sub.add_parser("jobs")
    p.add_argument("--out-root", type=Path, required=True)
    p.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "transcribe":
        os.environ.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
        print(json.dumps(transcribe(args.engine, args.manifest, args.source_work, args.out, args.limit)))
    else:
        print(write_align_jobs(args.out_root, args.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
