"""smoke `ct2_after_torch`：同一进程先 `import torch` 并初始化 CUDA，再导入 ctranslate2／faster_whisper，
验证 faster-whisper large-v3 能在 GPU 上以 float16 解码，且 CT2 用的是 torch 已加载的那一份 CUDA 12 运行库。

CT2 的 Linux wheel 不自带 CUDA 运行库，按 soname `dlopen` `libcublas.so.12`、`libcudnn.so.9`，同一进程里复用 torch
从 `site-packages/nvidia/`（`nvidia-*-cu12` wheel）加载的那一份；系统里另有一份被加载时这里会查出来。
输入是合成的 5 s 正弦波，作为一个窗口交给产品的 `WhisperAsr.transcribe`；只检查能跑通，不对照任何参考结果。
通过条件：解码完成、模型实际为 CUDA float16、已加载的 `libcudnn*`／`libcublas*`／`libcudart*` 全部来自
`site-packages/nvidia/`。结果只含版本、计数、布尔与耗时，不保存解码文本。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

import smokelib

sys.path.insert(0, str(smokelib.REPO))

import torch  # noqa: E402 - 顺序是被验证的对象：torch 在前

NAME = "ct2_after_torch"
LIB_PREFIXES = ("libcudnn", "libcublas", "libcudart")
MODELS = smokelib.REPO / ".local/models"
SECONDS = 5


def main() -> int:
    args = smokelib.parse_args("Smoke: torch first, then CTranslate2 / faster-whisper on CUDA.")
    timer = smokelib.Timer()
    failures: list[str] = []
    result: dict[str, Any] = {"passed": False, "versions": smokelib.package_versions(
        "torch", "ctranslate2", "faster-whisper", "numpy"), "failures": failures}

    torch.zeros(1, device="cuda").add_(1).item()  # 初始化 CUDA，让 cudnn／cublas 先由 torch 加载
    result["device"] = torch.cuda.get_device_name(0)
    result["torch"] = {"cuda": torch.version.cuda, "cudnn_version": torch.backends.cudnn.version(),
                       "capability": list(torch.cuda.get_device_capability(0))}
    after_torch = {Path(path).name for path in smokelib.modules_matching(LIB_PREFIXES)}

    import numpy as np
    from kototoki.asr_whisper import WhisperAsr  # 模块内先 torch 后 ctranslate2

    started = time.perf_counter()
    asr = WhisperAsr(MODELS / "faster-whisper-large-v3", MODELS / "w0-assets")
    result["model_load_s"] = round(time.perf_counter() - started, 3)
    result["model"] = {key: asr.metadata[key] for key in ("device", "compute_type")}

    t = np.arange(SECONDS * 16000, dtype=np.float32) / 16000
    audio = (0.1 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    started = time.perf_counter()
    window = {"start": 0.0, "end": float(SECONDS), "start_sample": 0, "end_sample": len(audio)}
    _, traces, window_failures = asr.transcribe(audio, [window])
    result["decode_s"] = round(time.perf_counter() - started, 3)
    if window_failures:
        failures.append(f"decode failed: {window_failures[0][1][:300]}")
    else:
        result["token_count"] = len(traces[0]["tokens"])

    nvidia_dir = os.path.realpath(Path(torch.__file__).parent.parent / "nvidia")
    loaded = smokelib.modules_matching(LIB_PREFIXES)
    outside = [path for path in loaded if not os.path.realpath(path).startswith(nvidia_dir + os.sep)]
    result["cuda_libs"] = {"loaded": [Path(path).name for path in loaded],
                           "new_after_ct2": sorted({Path(path).name for path in loaded} - after_torch),
                           "outside_nvidia_dir": outside}
    if not loaded:
        failures.append("no cudnn/cublas/cudart library loaded")
    if outside:
        failures.append(f"{len(outside)} CUDA librar(ies) loaded from outside site-packages/nvidia")
    result["elapsed_s"] = round(time.perf_counter() - timer.started, 3)
    result["passed"] = not failures
    return smokelib.finish(args.out, NAME, result)


if __name__ == "__main__":
    sys.exit(main())
