"""媒体：ffprobe 选音轨、ffmpeg 流复制原始音轨、从视频容器派生 16 kHz 单声道 PCM16 WAV（规格 §2）。

本模块是唯一定义时间轴零点的地方：派生 WAV 用 `aresample=async=1:first_pts=0` 补齐起始静音与
中途间隙，sample 0 即视频 0 秒，`offset_s` 恒为 0；音轨与容器的 `start_time` 只作诊断。

只产生 ffmpeg 自身的输出文件（`audio.<ext>`、`audio-16k.wav`、`extract.log`），返回结果对象；
`probe.json` 等 JSON 产物的身份包装、写入与是否跳过由编排经产物契约完成。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any
import wave

from kototoki import recipes
from kototoki.artifacts import AUDIO_16K, AUDIO_COPY_STEM, EXTRACT_LOG, replace_with_retry
from kototoki.config import Config

# 流复制的容器映射（规格 §2.1）；未列出的编码一律 `.mka`。
CONTAINERS = {
    "flac": ".flac",
    "aac": ".m4a", "alac": ".m4a",
    "ac3": ".ac3",
    "eac3": ".eac3",
    "dts": ".dts",
    "opus": ".opus",
    "vorbis": ".ogg",
    "mp3": ".mp3",
    # 只有小端 PCM 放 WAV（超过 4 GB 时 RF64）；大端 PCM、pcm_bluray、pcm_dvd 等走 .mka
    "pcm_s16le": ".wav", "pcm_s24le": ".wav", "pcm_s32le": ".wav", "pcm_f32le": ".wav",
}
FALLBACK_CONTAINER = ".mka"

# 视为同一语言的标签（ffprobe `tags.language`，大小写不敏感）。
LANGUAGE_ALIASES = {"ja": "jpn", "jp": "jpn", "jpn": "jpn"}

# swr 在 -loglevel verbose 下报告的硬补偿（`async=1`）；样本数按输入采样率计。实测只报告一部分
# （合成 2 s 间隙只报出约 0.63 s），因此另用 ffmpeg 结束统计的输入样本数算净补偿。
_SWR_ADDED = re.compile(r"adding (\d+) audio samples of silence")
_SWR_DROPPED = re.compile(r"discarding (\d+) audio samples")
_INPUT_SAMPLES = re.compile(r"Input stream #0:(\d+) \(audio\):.*\((\d+) samples\)")
_SEXAGESIMAL = re.compile(r"(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)")


class MediaError(RuntimeError):
    """该视频无法提取（无音轨、不支持的声道布局、ffmpeg 失败、解码截断）；编排记为该文件 extract 失败。"""


@dataclass(frozen=True)
class AudioTrack:
    index: int                  # 绝对流索引（ffprobe `index`）
    codec_name: str
    channels: int
    channel_layout: str
    sample_rate: int | None
    language: str | None        # 原始标签
    default: bool
    comment: bool
    start_time: float | None    # 诊断用，不进时间轴
    duration: float | None


@dataclass(frozen=True)
class Probe:
    ffprobe: dict[str, Any]     # `-show_streams -show_format` 原始 JSON，供视频身份指纹
    audio: AudioTrack           # 选中的音轨
    audio_tracks: tuple[AudioTrack, ...]
    video_duration_s: float
    video_duration_source: str  # stream.duration | stream.tags.DURATION | format.duration
    container_start_time: float | None
    subtitles: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]

    def payload(self) -> dict[str, Any]:
        """`probe.json` 的内容（不含身份）。"""
        return {"selected_audio": _track_dict(self.audio),
                "audio_tracks": [_track_dict(track) for track in self.audio_tracks],
                "video_duration_s": self.video_duration_s, "video_duration_source": self.video_duration_source,
                "container_start_time": self.container_start_time, "subtitles": list(self.subtitles),
                "warnings": list(self.warnings), "ffprobe": self.ffprobe}


@dataclass(frozen=True)
class Extract:
    audio_copy: Path
    wav: Path
    log: Path
    sample_rate: int
    samples: int
    pcm_sha256: str             # WAV 数据块（PCM 样本）的 SHA256
    decoded_duration_s: float
    video_duration_s: float
    offset_s: float
    pan: str
    compensation: dict[str, Any]
    warnings: tuple[str, ...]

    def payload(self) -> dict[str, Any]:
        return {"audio_copy": self.audio_copy.name, "wav": self.wav.name, "log": self.log.name,
                "sample_rate": self.sample_rate, "samples": self.samples, "pcm_sha256": self.pcm_sha256,
                "decoded_duration_s": self.decoded_duration_s, "video_duration_s": self.video_duration_s,
                "offset_s": self.offset_s, "pan": self.pan, "compensation": dict(self.compensation),
                "warnings": list(self.warnings)}


def _track_dict(track: AudioTrack) -> dict[str, Any]:
    return {"index": track.index, "codec_name": track.codec_name, "channels": track.channels,
            "channel_layout": track.channel_layout, "sample_rate": track.sample_rate,
            "language": track.language, "default": track.default, "comment": track.comment,
            "start_time": track.start_time, "duration": track.duration}


# --- 纯函数：解析、选择、映射、命令行 ------------------------------------------------------------

def normalize_language(tag: str | None) -> str | None:
    """`jpn`／`ja`／`jp`（大小写不敏感）→ `jpn`；其余标签只转小写。"""
    if tag is None:
        return None
    lowered = tag.strip().lower()
    return LANGUAGE_ALIASES.get(lowered, lowered) or None


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # NaN → None


def _tag_duration(stream: Mapping[str, Any]) -> float | None:
    """Matroska 把流时长写在 `tags.DURATION`（`HH:MM:SS.fffffffff`）；mkvmerge 统计标签 `DURATION-<lang>` 只作后备：
    `-c copy` 剪出的片段会保留原片全长的 `DURATION-<lang>`，所以必须先取精确的 `DURATION`。"""
    exact = fallback = None
    for key, value in (stream.get("tags") or {}).items():
        upper = key.upper()
        if not isinstance(value, str) or not (upper == "DURATION" or upper.startswith("DURATION-")):
            continue
        match = _SEXAGESIMAL.fullmatch(value.strip())
        if not match:
            continue
        hours, minutes, seconds = match.groups()
        seconds_total = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        if upper == "DURATION":
            exact = seconds_total
        elif fallback is None:
            fallback = seconds_total
    return exact if exact is not None else fallback


def _stream_duration(stream: Mapping[str, Any]) -> tuple[float | None, str]:
    duration = _float(stream.get("duration"))
    if duration is not None:
        return duration, "stream.duration"
    return _tag_duration(stream), "stream.tags.DURATION"


def _audio_track(stream: Mapping[str, Any]) -> AudioTrack:
    disposition = stream.get("disposition") or {}
    sample_rate = _float(stream.get("sample_rate"))
    return AudioTrack(
        index=int(stream["index"]), codec_name=str(stream.get("codec_name", "")),
        channels=int(stream.get("channels") or 0), channel_layout=str(stream.get("channel_layout") or ""),
        sample_rate=int(sample_rate) if sample_rate else None,
        language=(stream.get("tags") or {}).get("language"),
        default=bool(disposition.get("default")), comment=bool(disposition.get("comment")),
        start_time=_float(stream.get("start_time")), duration=_stream_duration(stream)[0])


def select_audio(tracks: Sequence[AudioTrack], language: str) -> tuple[AudioTrack, list[str]]:
    """语言匹配且非 commentary 的音轨优先，其中 `default` 优先；无匹配取第一条。返回所选音轨与告警。"""
    if not tracks:
        raise MediaError("No audio stream in the video")
    wanted = normalize_language(language)
    matches = [track for track in tracks if normalize_language(track.language) == wanted and not track.comment]
    warnings = []
    if not matches:
        warnings.append(f"No non-commentary audio stream tagged {wanted!r}; using the first audio stream "
                        f"(index {tracks[0].index})")
        return tracks[0], warnings
    chosen = next((track for track in matches if track.default), matches[0])
    if len(matches) > 1:
        warnings.append(f"{len(matches)} audio streams tagged {wanted!r} "
                        f"(indices {', '.join(str(track.index) for track in matches)}); using index {chosen.index}")
    return chosen, warnings


def parse_probe(ffprobe: dict[str, Any], language: str) -> Probe:
    """ffprobe `-show_streams -show_format` JSON → `Probe`；视频时长取第一条视频流（非封面图）。"""
    streams = ffprobe.get("streams") or []
    tracks = tuple(_audio_track(stream) for stream in streams if stream.get("codec_type") == "audio")
    chosen, warnings = select_audio(tracks, language)
    videos = [stream for stream in streams if stream.get("codec_type") == "video"
              and not (stream.get("disposition") or {}).get("attached_pic")]
    if not videos:
        raise MediaError("No video stream in the input; duration cannot be checked against the video")
    duration, source = _stream_duration(videos[0])
    if duration is None:
        duration, source = _float((ffprobe.get("format") or {}).get("duration")), "format.duration"
        if duration is None:
            raise MediaError("Video stream duration is unknown (no stream, tag or container duration)")
        warnings.append("Video stream has no duration; using the container duration")
    # 流时长（尤其是标签）可能与容器时长矛盾（如 `-c copy` 残留的原片标签）：取较小者并告警，不失败
    container = _float((ffprobe.get("format") or {}).get("duration"))
    if (source != "format.duration" and container is not None
            and abs(duration - container) > recipes.MEDIA["duration_tolerance_s"]):
        warnings.append(f"Video duration from {source} ({duration:.3f} s) disagrees with the container duration "
                        f"({container:.3f} s); using the smaller one")
        if container < duration:
            duration, source = container, "format.duration"
    subtitles = tuple({"index": int(stream["index"]), "codec_name": stream.get("codec_name"),
                       "language": (stream.get("tags") or {}).get("language"),
                       "default": bool((stream.get("disposition") or {}).get("default")),
                       "forced": bool((stream.get("disposition") or {}).get("forced"))}
                      for stream in streams if stream.get("codec_type") == "subtitle")
    return Probe(ffprobe=ffprobe, audio=chosen, audio_tracks=tracks, video_duration_s=duration,
                 video_duration_source=source,
                 container_start_time=_float((ffprobe.get("format") or {}).get("start_time")),
                 subtitles=subtitles, warnings=tuple(warnings))


def container_suffix(codec_name: str) -> str:
    return CONTAINERS.get(codec_name, FALLBACK_CONTAINER)


def pan_filter(track: AudioTrack) -> str:
    """该音轨声道布局对应的下混表达式（`recipes.PAN`）；布局未标注时按声道数。"""
    layout = track.channel_layout
    if layout not in recipes.PAN:
        if layout and not layout.endswith("channels"):
            raise MediaError(f"Unsupported channel layout {layout!r} ({track.channels} channels)")
        layout = recipes.LAYOUT_BY_CHANNELS.get(track.channels, "")
        if not layout:
            raise MediaError(f"Unsupported channel count {track.channels} without a channel layout")
    return recipes.PAN[layout]


def probe_command(ffprobe: Path, video: Path) -> list[str]:
    return [str(ffprobe), "-hide_banner", "-v", "error", "-print_format", "json",
            "-show_streams", "-show_format", str(video)]


def copy_command(ffmpeg: Path, video: Path, track: AudioTrack, output: Path) -> list[str]:
    rf64 = ["-rf64", "auto"] if output.suffix == ".wav" else []
    return [str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-i", str(video),
            "-map", f"0:{track.index}", "-vn", "-sn", "-dn", "-c:a", "copy", *rf64, str(output)]


def derive_filter(track: AudioTrack) -> str:
    media = recipes.MEDIA
    return ",".join((media["timeline_filter"], pan_filter(track), media["resample_filter"]))


def derive_command(ffmpeg: Path, video: Path, track: AudioTrack, output: Path) -> list[str]:
    media = recipes.MEDIA
    return [str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "verbose", "-y", "-i", str(video),
            "-map", f"0:{track.index}", "-vn", "-sn", "-dn", "-af", derive_filter(track),
            "-c:a", media["codec"], *media["output_flags"], str(output)]


def parse_compensation(log: str, track: AudioTrack, decoded_s: float) -> dict[str, Any]:
    """补偿统计（只作诊断）：swr 报告的补入／丢弃样本数（输入采样率，含起始静音补齐，不完整），
    以及按 ffmpeg 结束统计算出的净补偿秒数（派生时长 − 解码出的输入时长，正为补入、负为丢弃）。"""
    input_samples = next((int(samples) for index, samples in _INPUT_SAMPLES.findall(log)
                          if int(index) == track.index), None)
    net = None
    if input_samples is not None and track.sample_rate:
        net = round(decoded_s - input_samples / track.sample_rate, 6)
    return {"swr_reported_silence_samples": sum(int(n) for n in _SWR_ADDED.findall(log)),
            "swr_reported_discarded_samples": sum(int(n) for n in _SWR_DROPPED.findall(log)),
            "input_samples": input_samples, "net_padding_s": net}


def check_duration(decoded_s: float, video_s: float) -> list[str]:
    """解码短于视频流超过容差判失败（`MediaError`）；长于视频超过容差只返回告警。"""
    tolerance = recipes.MEDIA["duration_tolerance_s"]
    if video_s - decoded_s > tolerance:
        raise MediaError(f"Decoded audio is {video_s - decoded_s:.3f} s shorter than the video stream "
                         f"({decoded_s:.3f} s vs {video_s:.3f} s); treating it as truncated")
    if decoded_s - video_s > tolerance:
        return [f"Decoded audio is {decoded_s - video_s:.3f} s longer than the video stream"]
    return []


# --- 子进程 ---------------------------------------------------------------------------------

def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8",
                          errors="replace", check=False)


def _partial(path: Path) -> Path:
    """同目录临时输出，保留扩展名供 ffmpeg 推断封装格式。"""
    return path.with_name(f".{path.stem}.{os.getpid()}.partial{path.suffix}")


def probe(path: Path, config: Config) -> Probe:
    """ffprobe 全部流并按 `config.input.audio_language` 选音轨。"""
    result = _run(probe_command(config.paths.ffprobe, Path(path)))
    if result.returncode != 0:
        raise MediaError(f"ffprobe failed ({result.returncode}): {result.stderr.strip()}")
    return parse_probe(json.loads(result.stdout), config.input.audio_language)


def _wav_pcm(path: Path) -> tuple[int, int, str]:
    """(采样率, 样本数, PCM 数据 SHA256)；要求单声道 16 bit。"""
    digest = hashlib.sha256()
    with wave.open(str(path), "rb") as reader:
        if reader.getnchannels() != 1 or reader.getsampwidth() != 2:
            raise MediaError(f"Derived WAV is not mono PCM16: {path.name}")
        rate, samples = reader.getframerate(), reader.getnframes()
        while chunk := reader.readframes(1 << 16):
            digest.update(chunk)
    return rate, samples, digest.hexdigest()


def extract_original(video: Path, work_dir: Path, track: AudioTrack, ffmpeg: Path) -> tuple[Path, str]:
    """`-c:a copy` 原样写出音轨为 `audio.<ext>`；返回路径与 ffmpeg stderr。"""
    target = Path(work_dir) / f"{AUDIO_COPY_STEM}{container_suffix(track.codec_name)}"
    partial = _partial(target)
    command = copy_command(ffmpeg, Path(video), track, partial)
    try:
        result = _run(command)
        if result.returncode != 0:
            raise MediaError(f"ffmpeg stream copy failed ({result.returncode}): {result.stderr.strip()[-2000:]}")
        replace_with_retry(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return target, f"$ {subprocess.list2cmdline(command)}\n{result.stderr}"


def derive_pcm16k(video: Path, work_dir: Path, probe_result: Probe, ffmpeg: Path, *, audio_copy: Path,
                  log_head: str = "") -> Extract:
    """从视频容器按绝对流索引解码，补齐时间轴、下混、重采样为 `audio-16k.wav`，verbose 日志写 `extract.log`。

    时长校验在替换目标之前完成：截断时不留下 `audio-16k.wav`，只留日志。
    """
    work_dir = Path(work_dir)
    target, log_path = work_dir / AUDIO_16K, work_dir / EXTRACT_LOG
    partial = _partial(target)
    track = probe_result.audio
    command = derive_command(ffmpeg, Path(video), track, partial)
    try:
        result = _run(command)
        log_path.write_text(f"{log_head}$ {subprocess.list2cmdline(command)}\n{result.stderr}",
                            encoding="utf-8", newline="\n")
        if result.returncode != 0:
            raise MediaError(f"ffmpeg decode failed ({result.returncode}); see {EXTRACT_LOG}")
        rate, samples, pcm_sha256 = _wav_pcm(partial)
        if rate != recipes.SAMPLE_RATE:
            raise MediaError(f"Derived WAV sample rate is {rate}, expected {recipes.SAMPLE_RATE}")
        decoded_s = samples / rate
        warnings = check_duration(decoded_s, probe_result.video_duration_s)
        replace_with_retry(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return Extract(audio_copy=audio_copy, wav=target, log=log_path, sample_rate=rate, samples=samples,
                   pcm_sha256=pcm_sha256, decoded_duration_s=decoded_s,
                   video_duration_s=probe_result.video_duration_s, offset_s=float(recipes.MEDIA["offset_s"]),
                   pan=pan_filter(track), compensation=parse_compensation(result.stderr, track, decoded_s),
                   warnings=tuple(warnings))


def extract(path: Path, work_dir: Path, probe_result: Probe, config: Config) -> Extract:
    """流复制原始音轨并派生 16 kHz WAV；两条 ffmpeg 命令与输出都记入 `extract.log`。"""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    pan_filter(probe_result.audio)  # 不支持的布局在任何 ffmpeg 运行前失败
    audio_copy, copy_log = extract_original(path, work_dir, probe_result.audio, config.paths.ffmpeg)
    return derive_pcm16k(path, work_dir, probe_result, config.paths.ffmpeg, audio_copy=audio_copy,
                         log_head=copy_log)
