"""ASR 引擎 x0：Qwen3-ASR-1.7B-hf 逐窗独立转写（CUDA BF16、SDPA、greedy、原生 processor，配方 `recipes.X0`）。

复制自 `experiments/x0_demo/asr.py` 与 `experiments/qwen/run_qwen.py` 的 `check_gpu`，适配 transformers 5.19。
与研究期实现的差别：生成触顶（`max_new_tokens` 4096）不再抛错让整片失败，而是作为失败窗口返回，
由 worker 壳经 `protocol.fail_window` 置空并把截断文字记入 `failed_windows`（规格 §6）；
模型文件 SHA256 由 worker 壳经产物契约的缓存核对，本模块不再自行哈希（研究期的 `checkpoint_identity`）。
"""

from __future__ import annotations

import hashlib
import importlib.metadata
from pathlib import Path
import time
from typing import Any

import torch
from transformers import AutoModelForMultimodalLM, AutoProcessor

from kototoki.recipes import SAMPLE_RATE, X0
from kototoki.schema import validate_windows

DEVICE = X0["device"]
MAX_NEW_TOKENS = X0["generate"]["max_new_tokens"]
IMPLEMENTATION_FILES = ("processing_qwen3_asr.py", "feature_extraction_qwen3_asr.py", "modeling_qwen3_asr.py")


def check_gpu(model: Any, inputs: Any) -> dict[str, Any]:
    """模型参数与输入张量必须全在 CUDA 上（不回退 CPU）；返回设备、dtype 与形状证据。"""
    devices = sorted({str(param.device) for param in model.parameters()})
    tensors = {name: str(tensor.device) for name, tensor in inputs.items() if isinstance(tensor, torch.Tensor)}
    if not devices or any(not device.startswith("cuda") for device in devices):
        raise RuntimeError(f"Model is not entirely on CUDA: {devices}")
    if any(not device.startswith("cuda") for device in tensors.values()):
        raise RuntimeError(f"Input tensor is not on CUDA: {tensors}")
    return {"parameter_devices": devices, "input_devices": tensors, "dtype": str(model.dtype),
            "input_shapes": {name: list(tensor.shape) for name, tensor in inputs.items()
                             if isinstance(tensor, torch.Tensor)}}


class QwenAsr:
    """加载一次本地 Qwen3-ASR checkpoint，之后按窗口转写。"""

    def __init__(self, model_path: Path) -> None:
        model_path = Path(model_path)
        if not model_path.is_dir():
            raise FileNotFoundError(f"Provision a local Qwen3-ASR checkpoint directory: {model_path}")
        if not torch.cuda.is_available():
            raise RuntimeError("Qwen ASR requires CUDA; CPU fallback is prohibited")
        self._processor = AutoProcessor.from_pretrained(model_path, local_files_only=True)
        self._model = AutoModelForMultimodalLM.from_pretrained(
            model_path, dtype=torch.bfloat16, attn_implementation=X0["attn_implementation"],
            device_map={"": DEVICE}, local_files_only=True).eval()
        torch.cuda.synchronize()
        distribution = importlib.metadata.distribution("transformers")
        implementation = {}
        for name in IMPLEMENTATION_FILES:
            with Path(distribution.locate_file(f"transformers/models/qwen3_asr/{name}")).open("rb") as stream:
                implementation[name] = hashlib.file_digest(stream, "sha256").hexdigest()
        self.metadata: dict[str, Any] = {
            "model": X0["model_id"], "revision": X0["model_revision"], "device": DEVICE, "dtype": X0["dtype"],
            "attention": X0["attn_implementation"], "language": X0["language"], **X0["generate"],
            "batch_size": X0["batch_size"], "previous_text_conditioning": X0["previous_text_conditioning"],
            "padding_to_30s": False, "mel_source": "native Qwen processor",
            "generation_config": self._model.generation_config.to_dict(),
            "installed_implementation_sha256": implementation,
            "package_versions": {name: importlib.metadata.version(name)
                                 for name in ("transformers", "torch", "numpy")},
        }

    def transcribe(self, audio: Any, chunks: list[dict[str, Any]]
                   ) -> tuple[list[dict[str, Any]], list[dict[str, Any] | None], list[tuple[int, str]]]:
        """逐窗独立解码 → (窗口段, 逐窗 trace, 失败窗口)，形状同 `asr_whisper.WhisperAsr.transcribe`。

        生成达到 `max_new_tokens` 的窗口：段内保留截断文字、trace 照常记录，并以 `(窗口序号, 原因)`
        列入失败窗口，由 worker 壳置空。单窗生成抛 `RuntimeError`（显存不足等）时该窗文字为空、
        trace 为 None，同样列入失败窗口，继续下一窗；是否已是 CUDA 粘性错误由 worker 壳判定。
        """
        validate_windows(chunks, len(audio))
        segments: list[dict[str, Any]] = []
        traces: list[dict[str, Any] | None] = []
        failures: list[tuple[int, str]] = []
        torch.cuda.reset_peak_memory_stats()
        for index, chunk in enumerate(chunks):
            start, end = chunk["start_sample"], chunk["end_sample"]
            segment = {"text": "", "start": chunk["start"], "end": chunk["end"],
                       "start_sample": start, "end_sample": end, "avg_logprob": None}
            data = audio[start:end]
            mark = time.perf_counter()
            inputs = self._processor.apply_transcription_request(
                audio=data, language=X0["language"],
                processor_kwargs={"audio_kwargs": {"sampling_rate": SAMPLE_RATE}}).to(DEVICE, torch.bfloat16)
            evidence = check_gpu(self._model, inputs)
            if inputs["input_ids"].ndim != 2 or inputs["input_ids"].shape[0] != 1:
                raise ValueError("Qwen processor must produce a single independent request")
            for name, tensor in inputs.items():
                if isinstance(tensor, torch.Tensor) and tensor.is_floating_point() and not torch.isfinite(tensor).all():
                    raise ValueError(f"Qwen processor produced non-finite input: {name}")
            torch.cuda.synchronize()
            preprocess_s = time.perf_counter() - mark
            mark = time.perf_counter()
            try:
                with torch.inference_mode():
                    output = self._model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS,
                                                  do_sample=X0["generate"]["do_sample"])
                torch.cuda.synchronize()
            except RuntimeError as error:
                segments.append(segment)
                traces.append(None)
                failures.append((index, f"{type(error).__name__}: {error}"))
                continue
            inference_s = time.perf_counter() - mark
            if output.device.type != "cuda":
                raise RuntimeError("Qwen output token IDs were not produced on CUDA")
            generated = output[:, inputs["input_ids"].shape[1]:]
            parsed = self._processor.decode(generated, return_format="parsed")[0]
            count = generated.shape[1]
            segments.append({**segment, "text": parsed["transcription"]})
            traces.append({"tokens": generated[0].detach().cpu().tolist(), "generated_tokens": count,
                           "token_limit_reached": count >= MAX_NEW_TOKENS,
                           "raw_asr": self._processor.decode(generated)[0],
                           "detected_language": parsed["language"],
                           "asr_input_evidence": {**evidence, "output_device": str(output.device)},
                           "pcm_float32_sha256": hashlib.sha256(data.tobytes()).hexdigest(),
                           "start_sample": start, "end_sample": end,
                           "preprocess_s": preprocess_s, "inference_s": inference_s})
            if count >= MAX_NEW_TOKENS:
                failures.append((index, f"token_limit_reached: generated {count} tokens"))
            del inputs, output, generated
        self.metadata.update(peak_allocated_bytes=torch.cuda.max_memory_allocated(),
                             peak_reserved_bytes=torch.cuda.max_memory_reserved())
        return segments, traces, failures
