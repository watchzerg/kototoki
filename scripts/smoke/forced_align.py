"""smoke `forced_align`：验证 torchaudio 2.11.0+cu128 的 `forced_align` / `merge_tokens` 在 CUDA 上可用。

两段检查：
a. 合成数据：固定种子的随机 log-softmax emission，CUDA 与 CPU 各跑一次 forced_align，
   要求路径完全一致、分数接近、CUDA 路径的输出张量在 CUDA 上，且 merge_tokens 可用。
b. 冻结窗口：加载 MMS（CUDA FP32、jpn adapter），对冻结 W0 结果的第 0 个对齐窗口计算 emission，
   用同一份 emission 分别跑 CUDA 与 CPU 的 forced_align，路径必须一致；
   与冻结记录（torch 2.8.0 下产出）的对比只作参考，不构成门禁。

不使用 `MmsAligner`（其构造函数断言 torchaudio 2.8.0），只复用 `experiments.w0_demo.alignment`
中的纯函数。不添加任何私有 DLL 目录。结果里只有计数、哈希、布尔、耗时与版本，不含音频内容或转写文本。
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import wave
from pathlib import Path
from typing import Any

import smokelib

NAME = "forced_align"
FROZEN_RUN = smokelib.REPO / ".local/w0-demo/pyannote-gpu-v1-w0-pyannote-current-hf-ii-window-01/result.json"
AUDIO = smokelib.REPO / ".local/round2/corpus/audio/hf-ii-window-01.wav"
MMS_PATH = smokelib.REPO / ".local/models/mms-1b-all"
WINDOW_INDEX = 0
SCORE_ATOL = 1e-3  # CUDA 与 CPU 的累计分数允许的绝对误差


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_pcm(path: Path) -> tuple[Any, str]:
    """与 experiments/w0_demo/run.py 的 read_audio 一致：pcm_sha256 是原始 PCM16 字节的 sha256。"""
    import numpy as np

    with wave.open(str(path), "rb") as source:
        if (source.getnchannels(), source.getframerate(), source.getsampwidth(), source.getcomptype()) != (1, 16000, 2, "NONE"):
            raise ValueError("Input must be mono 16000 Hz PCM16 WAV")
        pcm = source.readframes(source.getnframes())
    audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    return audio, sha256_bytes(pcm)


def sync(torch: Any) -> None:
    torch.cuda.synchronize()


def run_aligner(torch: Any, emission_cpu: Any, ids: list[int], blank: int, device: str) -> dict[str, Any]:
    """在指定设备上跑一次 forced_align；返回路径、分数、输出设备与耗时。"""
    from torchaudio.functional import forced_align

    inputs = emission_cpu.unsqueeze(0).to(device)
    targets = torch.tensor([ids], device=device, dtype=torch.int64)
    if device.startswith("cuda"):
        sync(torch)
    started = time.perf_counter()
    labels, scores = forced_align(inputs, targets, blank=blank)
    if device.startswith("cuda"):
        sync(torch)
    return {"labels": labels, "scores": scores, "inputs": inputs,
            "seconds": round(time.perf_counter() - started, 4)}


def compare_runs(cuda: dict[str, Any], cpu: dict[str, Any], torch: Any) -> dict[str, Any]:
    """比较 CUDA 与 CPU 的对齐结果。"""
    labels_cuda, labels_cpu = cuda["labels"].cpu(), cpu["labels"].cpu()
    scores_cuda, scores_cpu = cuda["scores"].cpu(), cpu["scores"].cpu()
    paths_equal = bool(torch.equal(labels_cuda, labels_cpu))
    max_score_diff = float((scores_cuda - scores_cpu).abs().max()) if scores_cuda.shape == scores_cpu.shape else None
    return {
        "paths_identical": paths_equal,
        "path_length": int(labels_cuda.shape[-1]),
        "max_abs_score_diff": max_score_diff,
        "scores_close": max_score_diff is not None and max_score_diff <= SCORE_ATOL,
        "cuda_output_devices": [str(cuda["labels"].device), str(cuda["scores"].device)],
        "cuda_outputs_on_cuda": cuda["labels"].device.type == "cuda" and cuda["scores"].device.type == "cuda",
        "cuda_seconds": cuda["seconds"],
        "cpu_seconds": cpu["seconds"],
        "path_sha256": sha256_bytes(labels_cuda.numpy().tobytes()),
    }


def check_merge(torch: Any, run: dict[str, Any], ids: list[int], blank: int) -> dict[str, Any]:
    from torchaudio.functional import merge_tokens

    spans = merge_tokens(run["labels"][0], run["scores"][0].exp(), blank=blank)
    ok = len(spans) == len(ids) and all(span.token == expected for span, expected in zip(spans, ids))
    return {"span_count": len(spans), "target_count": len(ids), "tokens_match_targets": ok,
            "spans": [(int(span.start), int(span.end)) for span in spans]}


def synthetic_check(torch: Any, failures: list[str]) -> dict[str, Any]:
    """a. 合成 emission：随机但固定种子；目标不含空白且相邻不重复。"""
    frames, classes, length = 240, 40, 24
    generator = torch.Generator().manual_seed(20261014)
    emission = torch.randn(frames, classes, generator=generator).log_softmax(dim=-1)
    ids: list[int] = []
    while len(ids) < length:
        candidate = int(torch.randint(1, classes, (1,), generator=generator))
        if not ids or ids[-1] != candidate:
            ids.append(candidate)
    result: dict[str, Any] = {"frames": frames, "classes": classes, "target_length": length}
    try:
        cuda = run_aligner(torch, emission, ids, 0, "cuda:0")
        cpu = run_aligner(torch, emission, ids, 0, "cpu")
        result.update(compare_runs(cuda, cpu, torch))
        merged = check_merge(torch, cuda, ids, 0)
        result["merge_tokens"] = {key: merged[key] for key in ("span_count", "target_count", "tokens_match_targets")}
        for flag, message in ((result["paths_identical"], "synthetic: CUDA and CPU alignment paths differ"),
                              (result["scores_close"], "synthetic: CUDA and CPU scores differ beyond tolerance"),
                              (result["cuda_outputs_on_cuda"], "synthetic: CUDA forced_align outputs are not on CUDA"),
                              (merged["tokens_match_targets"], "synthetic: merge_tokens did not reproduce the targets")):
            if not flag:
                failures.append(message)
    except Exception as error:  # noqa: BLE001 - smoke 需要记录任何后端错误
        failures.append(f"synthetic: {type(error).__name__}: {error}")
        result["error"] = f"{type(error).__name__}: {error}"
    return result


def load_mms(torch: Any) -> tuple[Any, Any, dict[str, int], int, dict[str, Any]]:
    """按 alignment.py 的设置加载 MMS：jpn adapter、FP32、CUDA；词表与 adapter 头做一致性核对。"""
    from safetensors import safe_open
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

    adapter = MMS_PATH / "adapter.jpn.safetensors"
    if not adapter.is_file():
        raise FileNotFoundError(f"Japanese adapter missing: {adapter}")
    processor = Wav2Vec2Processor.from_pretrained(str(MMS_PATH), target_lang="jpn", local_files_only=True)
    processor.tokenizer.set_target_lang("jpn")
    model = Wav2Vec2ForCTC.from_pretrained(str(MMS_PATH), target_lang=None, local_files_only=True)
    model.load_adapter("jpn", local_files_only=True)
    model = model.float()
    with safe_open(str(adapter), framework="pt", device="cpu") as checkpoint:
        for name in ("weight", "bias"):
            actual = getattr(model.lm_head, name).detach().cpu()
            expected = checkpoint.get_tensor(f"lm_head.{name}").to(dtype=actual.dtype)
            if not torch.equal(actual, expected):
                raise ValueError(f"MMS jpn lm_head.{name} differs from local adapter")
    # transformers 5.x 的 Wav2Vec2CTCTokenizer 把词分隔符 `|` 作为额外 added token（id 2268）放进词表，
    # 超出模型 2268 个输出类；4.57 没有这一项。字典只取模型输出范围内的 id，越界项单独记录。
    vocabulary = processor.tokenizer.get_vocab()
    classes = model.config.vocab_size
    out_of_range = {char: code for char, code in vocabulary.items() if code >= classes}
    dictionary = {char.lower(): code for char, code in vocabulary.items() if code < classes}
    blank = model.config.pad_token_id
    if classes != 2268 or len(dictionary) != classes or blank != 0 or dictionary.get("<pad>") != blank:
        raise ValueError("MMS jpn vocabulary must have 2268 in-range entries with blank id 0")
    model = model.to("cuda:0").eval()
    if any(p.device.type != "cuda" or p.dtype != torch.float32 for p in model.parameters()):
        raise RuntimeError("MMS parameters must all be CUDA FP32")
    tokenizer_extra = {"tokenizer_vocab_size": len(vocabulary), "model_classes": classes,
                       "out_of_range_tokens": {char.encode("unicode_escape").decode(): code
                                               for char, code in out_of_range.items()}}
    return model, processor, dictionary, blank, tokenizer_extra


def frozen_window_check(torch: Any, failures: list[str]) -> dict[str, Any]:
    """b. 冻结窗口：真实 MMS emission 上的 CUDA / CPU forced_align，并与冻结记录对照（仅参考）。"""
    from experiments.w0_demo.alignment import character_targets, mms_numeric_policy, normalize_window

    result: dict[str, Any] = {"window_index": WINDOW_INDEX}
    frozen = json.loads(FROZEN_RUN.read_text(encoding="utf-8"))
    record = frozen["alignment_records"][WINDOW_INDEX]
    text = frozen["derived_segments"][WINDOW_INDEX]["text"]

    audio, pcm_sha = read_pcm(AUDIO)
    result["pcm_sha256_matches_frozen_input"] = pcm_sha == frozen["input"]["pcm_sha256"]
    result["audio_samples"] = int(len(audio))
    if not result["pcm_sha256_matches_frozen_input"]:
        failures.append("frozen: audio pcm_sha256 differs from the frozen run input")
        return result
    start, end = record["window_start_sample"], record["window_end_sample"]
    waveform = audio[start:end]
    result["window_samples"] = int(len(waveform))

    started = time.perf_counter()
    model, processor, dictionary, blank, result["tokenizer"] = load_mms(torch)
    sync(torch)
    result["model_load_seconds"] = round(time.perf_counter() - started, 3)

    targets = character_targets(text, dictionary, len(dictionary))
    ids = [target["token_id"] for target in targets]
    result["target_count"] = len(ids)
    result["wildcard_target_count"] = sum(1 for target in targets if not target["lexical_interval_accepted"])

    values, normalization = normalize_window(waveform, processor.feature_extractor)
    tensor = torch.from_numpy(values.copy()).unsqueeze(0).to("cuda:0")
    started = time.perf_counter()
    with torch.inference_mode():
        with mms_numeric_policy(torch) as numeric_policy:
            logits = model(tensor).logits
            if logits.device.type != "cuda" or logits.dtype != torch.float32:
                raise RuntimeError("MMS forward output must remain CUDA FP32")
            emission = logits.log_softmax(dim=-1)[0].cpu().detach()
        if emission.shape[1] != len(dictionary):
            raise ValueError("MMS emission vocabulary differs from loaded dictionary")
        if result["wildcard_target_count"]:
            mask = torch.ones(emission.shape[1], dtype=torch.bool)
            mask[blank] = False
            emission = torch.cat([emission, emission[:, mask].max(dim=1).values.unsqueeze(1)], dim=1)
        sync(torch)
        result["emission_seconds"] = round(time.perf_counter() - started, 3)
        cuda = run_aligner(torch, emission, ids, blank, "cuda:0")
        cpu = run_aligner(torch, emission, ids, blank, "cpu")
        merged = check_merge(torch, cuda, ids, blank)
    result["align_seconds"] = {"cuda": cuda["seconds"], "cpu": cpu["seconds"]}
    result["numeric_policy"] = numeric_policy
    result.update(compare_runs(cuda, cpu, torch))
    result["merge_tokens"] = {key: merged[key] for key in ("span_count", "target_count", "tokens_match_targets")}
    for flag, message in ((result["paths_identical"], "frozen: CUDA and CPU alignment paths differ"),
                          (result["cuda_outputs_on_cuda"], "frozen: CUDA forced_align outputs are not on CUDA"),
                          (merged["tokens_match_targets"], "frozen: merge_tokens did not reproduce the targets")):
        if not flag:
            failures.append(message)

    # 与冻结记录对照（参考信息，不是门禁）
    emission_np = emission.numpy()
    recorded = record["tokens"]
    spans = merged["spans"]
    pairs = list(zip(recorded, spans))
    diffs = [max(abs(item["start_frame"] - span[0]), abs(item["end_frame"] - span[1])) for item, span in pairs]
    result["vs_frozen_informational"] = {
        "frozen_torch": frozen["runtime_identity"]["packages"]["torch"],
        "frozen_torchaudio": frozen["runtime_identity"]["packages"]["torchaudio"],
        "emission_shape": list(emission_np.shape),
        "emission_shape_equal": list(emission_np.shape) == record["emission_shape"],
        "emission_sha256_equal": sha256_bytes(emission_np.tobytes()) == record["emission_sha256"],
        "path_sha256_equal": result["path_sha256"] == record["path_sha256"],
        "frame_count_equal": int(emission_np.shape[0]) == record["frame_count"],
        "token_count": len(spans),
        "frozen_token_count": len(recorded),
        "tokens_identical_frames": sum(1 for item, span in pairs if item["start_frame"] == span[0] and item["end_frame"] == span[1]),
        "max_abs_frame_diff": max(diffs) if diffs else None,
        "normalized_sha256_equal": normalization["normalized_float32_sha256"] == record["normalization"]["normalized_float32_sha256"],
        "raw_sha256_equal": normalization["raw_float32_sha256"] == record["normalization"]["raw_float32_sha256"],
    }
    del model, tensor, logits
    return result


def main() -> int:
    args = smokelib.parse_args("Smoke: torchaudio forced_align / merge_tokens on CUDA.")
    sys.path.insert(0, str(smokelib.REPO))  # 为了 import experiments.w0_demo
    timer = smokelib.Timer()
    failures: list[str] = []
    result: dict[str, Any] = {"passed": False, "versions": {}, "device": "unavailable", "failures": failures}
    try:
        import torch

        result["versions"] = {**smokelib.package_versions("torch", "torchaudio", "transformers", "numpy", "safetensors"),
                              "torch_runtime": torch.__version__, "cuda_runtime": torch.version.cuda,
                              "cudnn": torch.backends.cudnn.version()}
        if not torch.cuda.is_available():
            failures.append("CUDA is not available; CPU fallback is prohibited")
        else:
            result["device"] = torch.cuda.get_device_name(0)
            result["device_capability"] = list(torch.cuda.get_device_capability(0))
            torch.zeros(1, device="cuda:0").add_(1).item()  # 初始化 CUDA
            result["synthetic"] = synthetic_check(torch, failures)
            try:
                result["frozen_window"] = frozen_window_check(torch, failures)
            except Exception as error:  # noqa: BLE001
                failures.append(f"frozen: {type(error).__name__}: {error}")
                result["frozen_window"] = {"error": f"{type(error).__name__}: {error}"}
    except Exception as error:  # noqa: BLE001
        failures.append(f"{type(error).__name__}: {error}")
    result["elapsed_s"] = round(time.perf_counter() - timer.started, 3)
    result["passed"] = not failures
    return smokelib.finish(args.out, NAME, result)


if __name__ == "__main__":
    sys.exit(main())
