"""ASR 引擎 w0：faster-whisper large-v3（CT2 FP16）逐窗独立转写，torch 特征链（配方 `recipes.W0`）。

复制自 `experiments/w0_demo/asr.py`（log-Mel 与生成流程源自 WhisperX 3.8.6（BSD-2）与 OpenAI
Whisper（MIT），见 `experiments/w0_demo/THIRD_PARTY_NOTICES.txt`）。去掉了私有 DLL 目录与 PATH 逻辑。

导入顺序是接口的一部分：本模块**先 `import torch` 再导入 `ctranslate2`／`faster_whisper`**，
cublas／cudart 与 cuDNN 子库因此来自 torch；CT2 随后按全路径加载自带的 `cudnn64_9.dll`
（9.10 调度器），与 torch 的 9.19 并存（票据 01 smoke #3，用户已接受）。有测试钉住这一顺序。
CT2 在 sm_120 上依赖 PTX JIT：冷启动首窗解码约 27 s，之后约 5 s。
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import math
from pathlib import Path
from typing import Any

import numpy as np
import torch
import ctranslate2  # 必须在 torch 之后、faster_whisper 之前导入；`score` 用其 StorageView
from faster_whisper import WhisperModel
from faster_whisper.tokenizer import Tokenizer

from kototoki.recipes import W0
from kototoki.schema import validate_windows

CROP_SAMPLES = W0["features"]["crop_samples"]
MEL_SHA256 = W0["features"]["mel_sha256"]
MEL_FILE = "mel_filters.npz"


def features(audio: Any, filters: Any) -> Any:
    """Right-pad waveform before centered float32 Torch STFT; never pad Mel."""
    if not 0 < len(audio) <= CROP_SAMPLES:
        raise ValueError("Expected nonempty mono PCM at 16 kHz, no longer than 30s")
    waveform = torch.from_numpy(audio)
    if len(audio) < CROP_SAMPLES:
        waveform = torch.nn.functional.pad(waveform, (0, CROP_SAMPLES - len(audio)))
    window = torch.hann_window(400).to(waveform.device)
    spectrum = torch.stft(waveform, 400, 160, window=window, return_complex=True)
    magnitudes = spectrum[..., :-1].abs() ** 2
    log_spec = torch.clamp(filters @ magnitudes, min=1e-10).log10()
    log_spec = torch.maximum(log_spec, log_spec.max() - 8.0)
    return ((log_spec + 4.0) / 4.0).numpy()


def generate(model: Any, mel: Any, options: dict[str, Any]) -> dict[str, Any]:
    """Use the base faster-whisper prompt/encoder and the exact CT2 whitelist."""
    tokenizer = Tokenizer(model.hf_tokenizer, model.model.is_multilingual,
                          task=W0["task"], language=W0["language"])
    previous = []
    if options["initial_prompt"] is not None:
        previous = tokenizer.encode(" " + options["initial_prompt"].strip())
    prompt = model.get_prompt(tokenizer, previous, without_timestamps=options["without_timestamps"],
                              prefix=options["prefix"], hotwords=options["hotwords"])
    encoder = model.encode(mel[np.newaxis])
    kwargs = {name: options[name] for name in (
        "beam_size", "patience", "length_penalty", "suppress_blank", "suppress_tokens",
        "no_repeat_ngram_size", "repetition_penalty")}
    kwargs.update(max_length=model.max_length, return_scores=True)
    result = model.model.generate(encoder, [prompt], **kwargs)[0]
    tokens = result.sequences_ids[0]
    length = len(tokens)
    return {"tokens": list(tokens), "text": tokenizer.tokenizer.decode_batch(
        [[token for token in tokens if token < tokenizer.eot]])[0],
        "avg_logprob": result.scores[0] * length ** options["length_penalty"] / (length + 1),
        "prompt": list(prompt), "kwargs": kwargs}


class WhisperAsr:
    """加载一次本地 faster-whisper 模型与 mel 滤波器，之后按窗口转写。"""

    def __init__(self, model_path: Path, mel_assets: Path) -> None:
        model_path, mel_path = Path(model_path), Path(mel_assets) / MEL_FILE
        if not model_path.is_dir():
            raise FileNotFoundError(f"Provision a local faster-whisper model directory: {model_path}")
        with mel_path.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        if checksum != MEL_SHA256:
            raise ValueError("Mel asset differs from the measured W0 filterbank; provision the pinned mel_filters.npz")
        with np.load(mel_path, allow_pickle=False) as archive:
            bank = archive[W0["features"]["mel_npz_key"]].copy()
        if bank.shape != (128, 201) or bank.dtype != np.float32 or not np.isfinite(bank).all():
            raise ValueError("mel_128 must be a finite float32 matrix with shape (128, 201)")
        model = WhisperModel(str(model_path), device="cuda", device_index=0,
                             compute_type=W0["compute_type"], local_files_only=True, cpu_threads=4)
        if model.model.device != "cuda" or model.model.compute_type != W0["compute_type"]:
            raise RuntimeError("ASR requires actual CUDA float16 execution; CPU fallback is disabled")
        if model.feature_extractor.mel_filters.shape[0] != W0["features"]["n_mels"]:
            raise ValueError("The measured W0 ASR requires a 128-Mel model")
        self._model, self._filters = model, torch.from_numpy(bank)
        self.options: dict[str, Any] = {name: value for name, value in W0["decode_options"].items()
                                        if name != "max_length"}
        self.metadata: dict[str, Any] = {
            "device": model.model.device, "compute_type": model.model.compute_type,
            "package_versions": {name: importlib.metadata.version(name)
                                 for name in ("faster-whisper", "ctranslate2", "torch", "numpy")},
        }

    def transcribe(self, audio: Any, chunks: list[dict[str, Any]]
                   ) -> tuple[list[dict[str, Any]], list[dict[str, Any] | None], list[tuple[int, str]]]:
        """逐窗独立解码 → (窗口段, 逐窗 trace, 失败窗口)。

        段与窗口一一对应，坐标照抄窗口（WAV 本地）。单窗解码抛 `RuntimeError`（CT2 的 CUDA 错误、
        显存不足等）时该窗 `text` 为空、trace 为 None，并以 `(窗口序号, 原因)` 列入失败窗口，
        继续下一窗；是否已是 CUDA 粘性错误由 worker 壳在写产物前判定。
        """
        validate_windows(chunks, len(audio))
        segments: list[dict[str, Any]] = []
        traces: list[dict[str, Any] | None] = []
        failures: list[tuple[int, str]] = []
        for index, chunk in enumerate(chunks):
            start, end = chunk["start_sample"], chunk["end_sample"]
            segment = {"text": "", "start": chunk["start"], "end": chunk["end"],
                       "start_sample": start, "end_sample": end, "avg_logprob": None}
            try:
                mel = features(audio[start:end], self._filters)
                result = generate(self._model, mel, self.options)
            except RuntimeError as error:
                segments.append(segment)
                traces.append(None)
                failures.append((index, f"{type(error).__name__}: {error}"))
                continue
            segments.append({**segment, "text": result["text"], "avg_logprob": result["avg_logprob"]})
            traces.append({"tokens": result["tokens"], "prompt": result["prompt"], "kwargs": result["kwargs"],
                           "feature_sha256": hashlib.sha256(mel.tobytes()).hexdigest(),
                           "start_sample": start, "end_sample": end})
        return segments, traces, failures

    def score(self, audio: Any, chunk: dict[str, Any], texts: list[str], max_batch: int = 16) -> list[float]:
        """教师强制打分：同一窗口音频下每段文本的 Σ log P(token)，不含 EOT；空文本得 0.0。

        窗口音频与特征同 `transcribe`（`audio[start_sample:end_sample]`，`features()` 右补零到 30 s）；
        编码器每次调用只跑一次，输出展开成批后经 `Whisper.align` 分批（每批至多 `max_batch` 条）打分，
        结果与 `texts` 一一对应。`start_sequence` 为 `sot_sequence`（<|sot|><|ja|><|transcribe|>），CT2 在其后
        自动接 `<|notimestamps|>`，等价于产品无时间戳、无 initial prompt 的提示（调研已对照产品 avg_logprob
        核实；若直接传含 `<|notimestamps|>` 的产品提示，会被重复接一次，分数更远）。文本 token 为
        `tokenizer.encode(text)`，不含 EOT；分数只在文本词表上归一化。

        空文本（或编码后无 token）得 0.0 且不送入 `align`；全部为空时连编码器也不运行（裁判依赖这一点）。
        `align` 返回的概率数与 token 数不符时抛 `RuntimeError`。不保留跨调用状态，批内显存临时量即用即释放。
        """
        scores = [0.0] * len(texts)
        if not any(texts):
            return scores
        window = audio[chunk["start_sample"]:chunk["end_sample"]]
        mel = features(window, self._filters)
        tokenizer = Tokenizer(self._model.hf_tokenizer, self._model.model.is_multilingual,
                              task=W0["task"], language=W0["language"])
        start_sequence = list(tokenizer.sot_sequence)
        tokens = {index: tokenizer.encode(text) for index, text in enumerate(texts) if text}
        todo = [index for index, ids in tokens.items() if ids]
        if not todo:
            return scores
        num_frames = min(mel.shape[-1], -(-len(window) // 160))
        base = torch.as_tensor(self._model.encode(mel), device="cuda")
        for begin in range(0, len(todo), max_batch):
            group = todo[begin:begin + max_batch]
            batch = base.expand(len(group), *base.shape[1:]).contiguous()
            view = ctranslate2.StorageView.from_array(batch)
            results = self._model.model.align(view, start_sequence, [tokens[index] for index in group],
                                              [num_frames] * len(group))
            del view, batch
            if len(results) != len(group):
                raise RuntimeError("align returned a different number of results than texts")
            for index, result in zip(group, results):
                probs = list(result.text_token_probs)
                if len(probs) != len(tokens[index]):
                    raise RuntimeError("text_token_probs length differs from text tokens")
                scores[index] = float(sum(math.log(max(prob, 1e-45)) for prob in probs))
        del base
        return scores
