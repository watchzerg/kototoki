"""GPU 公共部分：加载一次产品 w0（`kototoki.asr_whisper.WhisperAsr`），按给定样本区间与解码参数单次解码。

A2（问题窗口补解）与 B1（空子段补窗）都只解一次、无条件采用或按守卫置空，不在多个结果里挑选（§4.0）。
解码参数默认照抄产品 `WhisperAsr.options`，A2 只改 `no_repeat_ngram_size`。本模块导入时不加载 torch；
`load_w0` 才导入（先 torch 再 ctranslate2 的顺序由 `kototoki.asr_whisper` 保证）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from experiments.asr_robustness_v14 import common, signals
from kototoki import artifacts


class W0Decoder:
    """持有产品 `WhisperAsr`；`decode(audio, start_sample, end_sample, **overrides)` → 段字段＋trace＋守卫信号。"""

    def __init__(self, models: dict[str, str]):
        from kototoki.asr_whisper import WhisperAsr

        started = common.timed()
        self.asr = WhisperAsr(Path(models["w0"]), Path(models["w0_mel_assets"]))
        self.load_s = round(common.timed() - started, 1)
        self.metadata = dict(self.asr.metadata)

    def decode(self, audio: Any, start_sample: int, end_sample: int, **overrides: Any) -> dict[str, Any]:
        from kototoki.asr_whisper import features, generate

        options = {**self.asr.options, **overrides}
        started = common.timed()
        mel = features(audio[start_sample:end_sample], self.asr._filters)
        result = generate(self.asr._model, mel, options)
        seconds = common.timed() - started
        text = result["text"]
        return {"text": text, "avg_logprob": result["avg_logprob"], "tokens": result["tokens"],
                "prompt": result["prompt"], "kwargs": result["kwargs"],
                "feature_sha256": hashlib.sha256(mel.tobytes()).hexdigest(),
                "compression_ratio": round(signals.compression_ratio(text), 4),
                "cap_reached": signals.cap_reached({"tokens": result["tokens"], "prompt": result["prompt"]}),
                "seconds": round(seconds, 2)}


def read_audio(work: Path) -> tuple[Any, str]:
    from kototoki.workers import gpu

    return gpu.read_wav(work / artifacts.AUDIO_16K)


def signal_of(decoded: dict[str, Any]) -> dict[str, Any]:
    return {"compression_ratio": decoded["compression_ratio"], "cap_reached": decoded["cap_reached"],
            "avg_logprob": decoded["avg_logprob"]}


def models_sha256(asr: dict[str, Any]) -> dict[str, str]:
    """产品 `asr.json` 身份里的模型文件 SHA256（研究产物照抄）。"""
    return dict(asr["identity"]["models"])


def write_asr(work_out: Path, asr: dict[str, Any], segments: list[dict[str, Any]], traces: list[Any],
              failures: list[tuple[int, str]], experiment: dict[str, Any], label: str) -> Path:
    """写研究侧的产品形状 `asr.json`：段与 trace 替换，失败窗口按协议置空，身份用研究标签。"""
    from kototoki.workers.protocol import fail_window, retained_text, validate_failed_windows

    document: dict[str, Any] = {
        "schema_version": 1, "engine": asr["engine"], "offset_s": asr["offset_s"], "input": asr["input"],
        "chunks": asr["chunks"], "original_segments": [dict(s) for s in segments], "asr_traces": traces,
        "failed_windows": [],
    }
    for index, reason in failures:
        fail_window(document, index, reason)
    validate_failed_windows(document)
    document.update(text=retained_text(document), metadata={**asr["metadata"], "experiment": experiment},
                    stages=dict(asr.get("stages", {})))
    identity = common.research_identity(label, upstream=dict(asr["identity"]["upstream"]), models=models_sha256(asr))
    work_out.mkdir(parents=True, exist_ok=True)
    artifacts.write_artifact(work_out / artifacts.ASR, identity, document)
    return work_out / artifacts.ASR


def link_audio(work_out: Path, work_in: Path) -> None:
    import os

    target = work_out / artifacts.AUDIO_16K
    work_out.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        os.link(work_in / artifacts.AUDIO_16K, target)


__all__ = ["W0Decoder", "link_audio", "models_sha256", "read_audio", "signal_of", "write_asr"]
