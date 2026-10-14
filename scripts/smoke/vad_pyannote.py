"""smoke #2：pyannote.audio 4.0.7＋torchcodec 0.17 在产品环境导入，对 10 s 内存波形做 VAD 推理。

记录导入后与推理后进程实际加载的 FFmpeg DLL（avcodec／avformat／avutil／swresample／swscale）。
一个都没有时，VAD worker 不需要把 FFmpeg 目录加入 PATH（规格 §7.1）。
波形取自冻结窗口 hf-ii-window-01 第一个 ASR 窗口起点后的 10 s，只记录区间数与时长，不记录内容。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import warnings
import wave

import smokelib

AUDIO = smokelib.REPO / ".local/round2/corpus/audio/hf-ii-window-01.wav"
RESULT = smokelib.REPO / ".local/w0-demo/pyannote-gpu-v1-w0-pyannote-current-hf-ii-window-01/result.json"
CHECKPOINT = smokelib.REPO / ".local/models/vad-comparison/pyannote-segmentation-3.0/pytorch_model.bin"
SAMPLE_RATE = 16000
SECONDS = 10
FFMPEG_PREFIXES = ("avcodec", "avformat", "avutil", "avdevice", "avfilter", "swresample", "swscale", "postproc")


def path_ffmpeg_dirs() -> list[str]:
    """PATH 中含 FFmpeg 共享 DLL 的目录；只用于解释观察结果。"""
    hits = []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        folder = Path(entry)
        if entry and folder.is_dir() and any(folder.glob("avcodec*.dll")):
            hits.append(entry)
    return hits


def load_waveform():
    import numpy as np
    start = json.loads(RESULT.read_text(encoding="utf-8"))["chunks"][0]["start_sample"]
    with wave.open(str(AUDIO), "rb") as stream:
        if (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) != (SAMPLE_RATE, 1, 2):
            raise ValueError("expected 16 kHz mono PCM16")
        stream.setpos(start)
        frames = stream.readframes(SECONDS * SAMPLE_RATE)
    return np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0


def main() -> int:
    args = smokelib.parse_args(__doc__)
    timer = smokelib.Timer()
    failures: list[str] = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        import torch
        import torchcodec  # noqa: F401  显式导入，确认产品环境中可用
        from pyannote.audio import Model
        from pyannote.audio.pipelines import VoiceActivityDetection
    import_warnings = [f"{w.category.__name__}: {str(w.message)[:300]}" for w in caught]
    timer.mark("import")
    after_import = smokelib.modules_matching(FFMPEG_PREFIXES)
    if not torch.cuda.is_available():
        failures.append("CUDA unavailable")
        return smokelib.finish(args.out, "vad_pyannote", {"passed": False, "failures": failures})
    model = Model.from_pretrained(str(CHECKPOINT), token=None)
    if model is None or not model.specifications.powerset:
        failures.append("segmentation-3.0 powerset checkpoint did not load")
        return smokelib.finish(args.out, "vad_pyannote", {"passed": False, "failures": failures})
    engine = VoiceActivityDetection(segmentation=model, device=torch.device("cuda:0"))
    engine.instantiate({"min_duration_on": 0.0, "min_duration_off": 0.0})
    timer.mark("load")
    audio = load_waveform()
    annotation = engine({"waveform": torch.from_numpy(audio).unsqueeze(0), "sample_rate": SAMPLE_RATE,
                         "uri": "smoke-vad"})
    torch.cuda.synchronize()
    timer.mark("infer")
    intervals = [[round(s.start, 3), round(s.end, 3)] for s in annotation.get_timeline().support()]
    device = str(next(model.parameters()).device)
    after_infer = smokelib.modules_matching(FFMPEG_PREFIXES)
    if not device.startswith("cuda"):
        failures.append(f"model on {device}, expected cuda")
    if not intervals:
        failures.append("no speech interval detected in a known speech window")
    return smokelib.finish(args.out, "vad_pyannote", {
        "passed": not failures, "failures": failures,
        "versions": smokelib.package_versions("torch", "torchaudio", "torchcodec", "pyannote.audio", "numpy"),
        "device": f"{device} ({torch.cuda.get_device_name(0)})",
        "elapsed_s": timer.mark("total"), "timings_s": timer.marks,
        "audio_seconds": len(audio) / SAMPLE_RATE, "speech_intervals": len(intervals),
        "speech_seconds": round(sum(end - start for start, end in intervals), 3),
        "import_warnings": import_warnings,
        "ffmpeg_dlls_after_import": after_import, "ffmpeg_dlls_after_inference": after_infer,
        "path_dirs_with_ffmpeg_dlls": path_ffmpeg_dirs(),
        "conclusion": ("no FFmpeg DLL loaded: VAD worker does not need FFmpeg on PATH" if not after_infer
                       else "FFmpeg DLLs loaded: VAD worker needs dirname(paths.ffmpeg) on PATH"),
    })


if __name__ == "__main__":
    sys.exit(main())
