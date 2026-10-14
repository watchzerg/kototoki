"""STT／cue／媒体的配方常量与 `recipe_hash`（规格 §1.1、§10.2）；翻译配方只在 `kototoki/translate/recipes.py`。

这里的值改变模型输入或输出，因此不进配置文件：改动任何一项即得到新的 `recipe_hash`，
已有产物按产物契约失效重算。各值取自已验证的 demo 实现（来源写在每节注释里）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from kototoki.artifacts import object_hash

SAMPLE_RATE = 16000
MAX_WINDOW_SAMPLES = 30 * SAMPLE_RATE

# --- 媒体：派生 16 kHz 单声道 PCM16 WAV（下混取自 experiments/corpus/prepare_round2.py，规格 §2.2） --------

# 按声道布局写死的下混表达式。系数为 ffmpeg 标准下混权重（前左右 1、中置 0.707、环绕 0.707、丢 LFE）
# 除以权重和后向下截到 6 位小数，系数和 ≤ 1，满幅输入不削波。按声道序号引用，
# 布局未标注（ffprobe 无 channel_layout）时按声道数取对应布局。不用 `-ac 1` 的隐式矩阵。
PAN: dict[str, str] = {
    "mono": "anull",  # 单声道直通
    "stereo": "pan=mono|c0=0.5*c0+0.5*c1",  # 与基线证据 hf-ii-full.wav 相同
    # FL FR FC LFE BL BR；5.1(side) 为 FL FR FC LFE SL SR，序号相同
    "5.1": "pan=mono|c0=0.242659*c0+0.242659*c1+0.171560*c2+0.171560*c4+0.171560*c5",
    "5.1(side)": "pan=mono|c0=0.242659*c0+0.242659*c1+0.171560*c2+0.171560*c4+0.171560*c5",
    # FL FR FC LFE BC SL SR
    "6.1": "pan=mono|c0=0.207125*c0+0.207125*c1+0.146437*c2+0.146437*c4+0.146437*c5+0.146437*c6",
    # FL FR FC LFE BL BR SL SR
    "7.1": "pan=mono|c0=0.180668*c0+0.180668*c1+0.127732*c2+0.127732*c4+0.127732*c5+0.127732*c6+0.127732*c7",
}
# ffprobe 没给 channel_layout 时按声道数选布局。
LAYOUT_BY_CHANNELS = {1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}

MEDIA: dict[str, Any] = {
    "id": "media-pcm16k-v1",
    "decode": "from the video container by absolute stream index",
    # 起始静音补齐、间隙补零，sample 0 即视频 0 秒；offset_s 恒为 0
    "timeline_filter": "aresample=async=1:first_pts=0",
    "pan": PAN,
    # 降采样用 soxr 28 bit（2026-10-14 用户裁定，替代默认 swr；8 kHz 边缘无折叠残留）。
    # 时间轴补偿（timeline_filter，同采样率只插静音／丢样）仍由 swr 完成。
    "resample_filter": f"aresample={SAMPLE_RATE}:resampler=soxr:precision=28",
    "codec": "pcm_s16le",
    "output_flags": ["-fflags", "+bitexact", "-flags:a", "+bitexact"],
    "sample_rate": SAMPLE_RATE,
    "channels": 1,
    "offset_s": 0,
    # 解码时长短于视频流超过此值判截断失败；长于视频超过此值只告警
    "duration_tolerance_s": 1.0,
}

# --- VAD（来源 experiments/w0_demo/vad_candidates.py `CurrentPyannoteVad`、`chunk_intervals`；ADR-0003） ----

VAD: dict[str, Any] = {
    "id": "pyannote-current-source-span-merge-v1",
    "package": ["pyannote.audio", "4.0.7"],
    "model_id": "pyannote/segmentation-3.0",
    "model_revision": "e66f3d3b9eb0873085418a7b813d3b369bf160bb",
    "requires_powerset": True,
    "pipeline": "pyannote.audio.pipelines.VoiceActivityDetection",
    "instantiate": {"min_duration_on": 0.0, "min_duration_off": 0.0},
    "native_options": {"onset": 0.5, "offset": 0.5, "powerset_conversion": True,
                       "speaker_reduction": "max before overlap-add"},
    "precision": "float32",
    "device": "cuda:0",  # 第一版固定，不设配置键
    "sample_rate": SAMPLE_RATE,
    "chunk_policy": {
        "id": "source-span-merge-v1",
        "max_chunk_samples": MAX_WINDOW_SAMPLES,
        "interval_conversion": "floor start, ceil end, clip to source, sorted union",
        "merge": "greedy whole intervals while source span fits",
        "long_interval_split": f"hard split every {MAX_WINDOW_SAMPLES} source samples",
        "additional_padding_samples": 0,
        "internal_silence": "retained",
        "concatenation": False,
        "seconds": "sample / 16000, nextafter toward +inf when truncation would undershoot",
    },
}

# --- ASR w0（来源 experiments/w0_demo/asr.py；W0 契约 w0-pyannote-current-mms-v1） -------------------------

W0: dict[str, Any] = {
    "id": "w0-faster-whisper-large-v3-v1",
    "baseline": "w0-pyannote-current-mms-v1",
    "model": "faster-whisper large-v3 (CTranslate2)",
    "device": "cuda:0",
    "compute_type": "float16",
    "language": "ja",
    "task": "transcribe",
    "batch_size": 1,
    "condition_on_previous_text": False,
    "features": {
        "n_mels": 128, "mel_npz_key": "mel_128",
        "mel_sha256": "7450ae70723a5ef9d341e3cee628c7cb0177f36ce42c44b7ed2bf3325f0f6d4c",
        "crop_samples": MAX_WINDOW_SAMPLES, "pad": "right zero-pad waveform to crop_samples",
        "stft": {"n_fft": 400, "hop": 160, "window": "hann(400)", "center": True},
        "log_mel": "log10(clamp(filters @ |stft[..., :-1]|^2, 1e-10)); max(x, x.max() - 8); (x + 4) / 4",
    },
    "decode_options": {
        "beam_size": 5, "patience": 1, "length_penalty": 1, "suppress_blank": True,
        "suppress_tokens": [-1], "no_repeat_ngram_size": 0, "repetition_penalty": 1,
        "initial_prompt": None, "without_timestamps": True, "prefix": None, "hotwords": None,
        "max_length": "model.max_length",
    },
}

# --- ASR x0（来源 experiments/x0_demo/asr.py、experiments/qwen/run_qwen.py；X0 契约） ------------------------

X0: dict[str, Any] = {
    "id": "x0-qwen3-asr-1.7b-v1",
    "model_id": "Qwen/Qwen3-ASR-1.7B-hf",
    "model_revision": "bcd2b5b7f32b480ab5790554cfa8347f246a14f3",
    "device": "cuda:0",
    "dtype": "bfloat16",
    "attn_implementation": "sdpa",
    "language": "ja",
    "processor": "native AutoProcessor.apply_transcription_request, sampling_rate 16000, no padding to 30 s",
    "generate": {"max_new_tokens": 4096, "do_sample": False},
    "batch_size": 1,
    "previous_text_conditioning": False,
    "token_limit": "window reaching max_new_tokens is emptied and recorded in failed_windows",
}

# --- 强制对齐（来源 experiments/w0_demo/alignment.py；MMS 对齐模块页） --------------------------------------

MMS: dict[str, Any] = {
    "id": "mms-1b-all-jpn-ctc-v1",
    "model_id": "facebook/mms-1b-all",
    "adapter": "jpn",
    "device": "cuda:0",
    "dtype": "float32",
    "sample_rate": SAMPLE_RATE,
    "normalization": {"do_normalize": True, "padding": "max_length", "max_length": "max(400, n_samples)",
                      "attention_mask_in_forward": False},
    "numeric_policy": {"matmul_allow_tf32": False, "cudnn_allow_tf32": True, "cudnn_benchmark": False},
    "dictionary": "char.lower() -> id for vocab ids < model.config.vocab_size",
    "char_targets": "per original char, lowercased; skip edge whitespace and '|'; OOV -> wildcard column",
    "wildcard": "appended column = max over non-blank log-probs per frame",
    "time_semantics": "ctc_nonblank_token_span",
    "seconds_decimals": 3,
}

# --- 日文 cue（规格 §5.2；显示规则数值在配置文件 [cues]，作为身份的配置键另行记录） --------------------------

CUES: dict[str, Any] = {
    "id": "ja-cues-v1",
    "split_order": "sentence endings and gaps, then soft breaks, then hard character split",
    "untimed_fill": {"inner": "linear interpolation between timed neighbours (time_source=interpolated)",
                     "edge": "extrapolate at the neighbour per-character duration, clipped to the window",
                     "failed_window": "distribute over the window's VAD segments (time_source=fallback)"},
    "lead_out": "extend end by lead_out_s without crossing the next cue start",
    "millisecond_rounding": "floor(x * 1000 + 0.5)",
}


def recipe_hash(recipe: Mapping[str, Any]) -> str:
    """配方常量的规范 JSON 的 SHA256；产物身份的 `recipe_hash` 字段。"""
    return object_hash(recipe)
