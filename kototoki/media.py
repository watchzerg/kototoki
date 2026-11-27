"""媒体：ffprobe 选音轨、从输入容器派生 16 kHz 单声道 PCM16 WAV（规格 §2）；不流复制原始音轨（ADR-0007「输入范围」）。

输入可以是视频或音频（ADR-0007「输入范围」）：除封面图外没有视频流即为音频，时长校验改对所选音轨的时长。

本模块是唯一定义时间轴零点的地方：派生 WAV 用 `aresample=async=1:first_pts=0` 补齐起始静音与
中途间隙，sample 0 即视频 0 秒，`offset_s` 恒为 0；音轨与容器的 `start_time` 只作诊断。

内嵌日文字幕（ADR-0024）：`select_subtitle` 按 `recipes.EMBEDDED` 选可用的文本字幕轨，`extract_subtitle` 让
ffmpeg 把它转成 SRT 文本返回；是否采用、清洗与落盘归编排。字幕时间与派生 WAV 一样以 ffmpeg 的输入零点为准。

只产生 ffmpeg 自身的输出文件（`audio-16k.wav`、`extract.log`），返回结果对象；
`probe.json` 等 JSON 产物的身份包装、写入与是否跳过由编排经产物契约完成。

模块页：docs/architecture/modules/config-and-media.md。
"""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from typing import IO, Any
import wave

from kototoki import recipes
from kototoki.artifacts import AUDIO_16K, EXTRACT_LOG
from kototoki.config import Config
from kototoki.procs import contained

# swr 在 -loglevel verbose 下报告的硬补偿（`async=1`）；样本数按输入采样率计。实测只报告一部分
# （合成 2 s 间隙只报出约 0.63 s），因此另用 ffmpeg 结束统计的输入样本数算净补偿。
_SWR_ADDED = re.compile(r"adding (\d+) audio samples of silence")
_SWR_DROPPED = re.compile(r"discarding (\d+) audio samples")
_INPUT_SAMPLES = re.compile(r"Input stream #0:(\d+) \(audio\):.*\((\d+) samples\)")
# ffmpeg `-loglevel level+verbose` 的一行：零到多个 `[上下文 @ 地址] ` 前缀，然后是 `[级别] `。
_LEVEL_LINE = re.compile(r"((?:\[[^\]]*\] )*?)\[(panic|fatal|error|warning|info|verbose|debug|trace)\] (.*)", re.S)
_ADDRESS = re.compile(r" @ [0-9A-Fa-fx]+")
_DIGITS = re.compile(r"\d+")
_DECODE_ERRORS = re.compile(r"Input stream #0:(\d+) \(audio\):.* (\d+) decode errors")
ERROR_LEVELS = ("panic", "fatal", "error")
LOG_HEAD_TAIL = 100                     # error／warning 行与 swr 补偿行在 extract.log 里各保留的前、后条数
DIAGNOSTIC_MESSAGES = 20                # `diagnostics.messages` 收录的 error／warning 类型数
MAX_OVERLONG_RATIO = 1.5                # 视频输入解码时长超过参照的这么多倍判失败（只判失败、不改 PCM，不进 `MEDIA`）
DECODE_LOG_CACHE = 50_000               # 只计数的 verbose 行按原文缓存的条目上限
_SEXAGESIMAL = re.compile(r"(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)")


class MediaError(RuntimeError):
    """该视频无法提取（无音轨、不支持的声道布局、ffmpeg 失败、解码截断）；编排记为该文件 extract 失败。"""

    def __init__(self, message: str, *, overwritten: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.overwritten = overwritten


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
    measured_sample_rate: float | None = None   # nb_frames × 1024 ÷ 流时长（只算 AAC-LC，诊断用）
    corrected_sample_rate: int | None = None    # 采样率标错时按此值解码；None 即按声明值


@dataclass(frozen=True)
class Probe:
    ffprobe: dict[str, Any]     # `-show_streams -show_format` 原始 JSON，供视频身份指纹
    audio: AudioTrack           # 选中的音轨
    audio_tracks: tuple[AudioTrack, ...]
    has_video: bool             # 除封面图外有视频流；False 即音频输入
    duration_s: float           # 时长校验的参照：视频输入取第一条视频流，音频输入取所选音轨
    duration_source: str        # stream.duration | stream.tags.DURATION | format.duration
    container_start_time: float | None
    subtitles: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]
    ffprobe_warnings: tuple[str, ...] = ()  # 仅来自 ffprobe 进程 stderr 的告警，采用内嵌字幕时也须呈现在运行日志

    def payload(self) -> dict[str, Any]:
        """`probe.json` 的内容（不含身份）。"""
        return {"selected_audio": _track_dict(self.audio),
                "audio_tracks": [_track_dict(track) for track in self.audio_tracks],
                "has_video": self.has_video, "duration_s": self.duration_s, "duration_source": self.duration_source,
                "container_start_time": self.container_start_time, "subtitles": list(self.subtitles),
                "warnings": list(self.warnings), "ffprobe": self.ffprobe}


@dataclass(frozen=True)
class Extract:
    wav: Path
    log: Path
    sample_rate: int
    samples: int
    pcm_sha256: str             # WAV 数据块（PCM 样本）的 SHA256
    decoded_duration_s: float
    duration_s: float
    offset_s: float
    pan: str
    compensation: dict[str, Any]
    warnings: tuple[str, ...]
    diagnostics: dict[str, Any] | None = None   # 解码日志的统计（`digest_decode_log`），只作诊断
    overwritten: tuple[str, ...] = ()           # 本次原子替换覆盖了哪些既有文件（由编排记 INFO 审计）

    def payload(self) -> dict[str, Any]:
        return {"wav": self.wav.name, "log": self.log.name,
                "sample_rate": self.sample_rate, "samples": self.samples, "pcm_sha256": self.pcm_sha256,
                "decoded_duration_s": self.decoded_duration_s, "duration_s": self.duration_s,
                "offset_s": self.offset_s, "pan": self.pan, "compensation": dict(self.compensation),
                "diagnostics": self.diagnostics, "warnings": list(self.warnings)}


def _track_dict(track: AudioTrack) -> dict[str, Any]:
    return {"index": track.index, "codec_name": track.codec_name, "channels": track.channels,
            "channel_layout": track.channel_layout, "sample_rate": track.sample_rate,
            "language": track.language, "default": track.default, "comment": track.comment,
            "start_time": track.start_time, "duration": track.duration,
            "measured_sample_rate": track.measured_sample_rate, "corrected_sample_rate": track.corrected_sample_rate}


# --- 纯函数：解析、选择、映射、命令行 ------------------------------------------------------------

def normalize_language(tag: str | None) -> str | None:
    """`jpn`／`ja`／`jp`（大小写不敏感）→ `jpn`（`recipes.LANGUAGE_ALIASES`，在 `MEDIA` 里）；其余标签只转小写。"""
    if tag is None:
        return None
    lowered = tag.strip().lower()
    return recipes.LANGUAGE_ALIASES.get(lowered, lowered) or None


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


def sample_rate_check(stream: Mapping[str, Any], declared: int | None) -> tuple[float | None, int | None]:
    """（实测采样率, 纠正后的采样率）。实测 = nb_frames × 1024 ÷ 流时长，只对 AAC-LC 且元数据齐全时算；
    实测落在 `recipes.MEDIA["sample_rate_correction"]` 某一对的真实值容差内时返回该真实值，否则为 None。"""
    rule = recipes.MEDIA["sample_rate_correction"]
    frames, duration = _float(stream.get("nb_frames")), _float(stream.get("duration"))
    if (stream.get("codec_name") != rule["codec"] or stream.get("profile") != rule["profile"]
            or not declared or not frames or not duration):
        return None, None
    measured = round(frames * rule["frame_samples"] / duration, 1)
    corrected = next((true for listed, true in rule["pairs"]
                      if listed == declared and abs(measured / true - 1) <= rule["relative_tolerance"]), None)
    return measured, corrected


def _audio_track(stream: Mapping[str, Any]) -> AudioTrack:
    disposition = stream.get("disposition") or {}
    sample_rate = _float(stream.get("sample_rate"))
    measured, corrected = sample_rate_check(stream, int(sample_rate) if sample_rate else None)
    return AudioTrack(
        index=int(stream["index"]), codec_name=str(stream.get("codec_name", "")),
        channels=int(stream.get("channels") or 0), channel_layout=str(stream.get("channel_layout") or ""),
        sample_rate=int(sample_rate) if sample_rate else None,
        language=(stream.get("tags") or {}).get("language"),
        default=bool(disposition.get("default")), comment=bool(disposition.get("comment")),
        start_time=_float(stream.get("start_time")), duration=_stream_duration(stream)[0],
        measured_sample_rate=measured, corrected_sample_rate=corrected)


def select_audio(tracks: Sequence[AudioTrack], language: str) -> tuple[AudioTrack, list[str]]:
    """语言匹配且非 commentary 的音轨优先，其中 `default` 优先；无匹配取第一条（规则写在
    `recipes.MEDIA["audio_selection"]`，改规则须同时改它）。返回所选音轨与告警。

    无匹配时告警，唯一的音轨没有语言标签（或标为 `und`）时除外：没得选，这类源很常见（batch-run-fixes 06.4）。
    """
    if not tracks:
        raise MediaError("No audio stream in the input")
    wanted = normalize_language(language)
    matches = [track for track in tracks if normalize_language(track.language) == wanted and not track.comment]
    warnings = []
    if not matches:
        if len(tracks) == 1 and normalize_language(tracks[0].language) in (None, "und"):
            return tracks[0], warnings
        warnings.append(f"No non-commentary audio stream tagged {wanted!r}; using the first audio stream "
                        f"(index {tracks[0].index})")
        return tracks[0], warnings
    chosen = next((track for track in matches if track.default), matches[0])
    if len(matches) > 1:
        warnings.append(f"{len(matches)} audio streams tagged {wanted!r} "
                        f"(indices {', '.join(str(track.index) for track in matches)}); using index {chosen.index}")
    return chosen, warnings


def parse_probe(ffprobe: dict[str, Any], language: str) -> Probe:
    """ffprobe `-show_streams -show_format` JSON → `Probe`；时长参照取第一条视频流（非封面图），没有视频流
    （音频输入）时取所选音轨。"""
    streams = ffprobe.get("streams") or []
    tracks = tuple(_audio_track(stream) for stream in streams if stream.get("codec_type") == "audio")
    chosen, warnings = select_audio(tracks, language)
    if chosen.corrected_sample_rate:
        warnings.append(f"Audio stream {chosen.index} declares {chosen.sample_rate} Hz but its frames imply "
                        f"{chosen.measured_sample_rate} Hz; decoding it as {chosen.corrected_sample_rate} Hz")
    videos = [stream for stream in streams if stream.get("codec_type") == "video"
              and not (stream.get("disposition") or {}).get("attached_pic")]
    kind = "Video" if videos else "Audio"
    reference = videos[0] if videos else next(stream for stream in streams if stream.get("codec_type") == "audio"
                                              and int(stream["index"]) == chosen.index)
    duration, source = _stream_duration(reference)
    if duration is None:
        duration, source = _float((ffprobe.get("format") or {}).get("duration")), "format.duration"
        if duration is None:
            raise MediaError(f"{kind} stream duration is unknown (no stream, tag or container duration)")
        warnings.append(f"{kind} stream has no duration; using the container duration")
    # 流时长（尤其是标签）可能与容器时长矛盾（如 `-c copy` 残留的原片标签）：取较小者并告警，不失败
    container = _float((ffprobe.get("format") or {}).get("duration"))
    if (source != "format.duration" and container is not None
            and abs(duration - container) > recipes.MEDIA["duration_tolerance_s"]):
        warnings.append(f"{kind} duration from {source} ({duration:.3f} s) disagrees with the container duration "
                        f"({container:.3f} s); using the smaller one")
        if container < duration:
            duration, source = container, "format.duration"
    subtitles = tuple({"index": int(stream["index"]), "codec_name": stream.get("codec_name"),
                       "language": (stream.get("tags") or {}).get("language"),
                       "default": bool((stream.get("disposition") or {}).get("default")),
                       "forced": _subtitle_forced(stream)}
                      for stream in streams if stream.get("codec_type") == "subtitle")
    return Probe(ffprobe=ffprobe, audio=chosen, audio_tracks=tracks, has_video=bool(videos), duration_s=duration,
                 duration_source=source,
                 container_start_time=_float((ffprobe.get("format") or {}).get("start_time")),
                 subtitles=subtitles, warnings=tuple(warnings))


def _subtitle_forced(stream: Mapping[str, Any]) -> bool:
    """forced = disposition 标了 forced，或标题里含 "forced"（不分大小写）。不少片源只在标题里写
    （如 `ja--forced--`），disposition 为 0；漏判会选中只有外语对白的部分字幕轨。"""
    title = (stream.get("tags") or {}).get("title")
    return bool((stream.get("disposition") or {}).get("forced")) or (
        isinstance(title, str) and "forced" in title.casefold())


def select_subtitle(subtitles: Sequence[Mapping[str, Any]], language: str) -> tuple[dict[str, Any] | None, list[str]]:
    """可用的内嵌字幕轨（`Probe.subtitles` 的一项）与告警；没有时为 None（规则见 `recipes.EMBEDDED`，ADR-0024）。

    可用 = 语言标签与 `language` 归一后相同、编码是文本字幕、不是 forced（只有屏幕字与外语对白的部分字幕）。
    多条可用时取 default 的，再取流索引最小的，并告警。只看流的元数据，不看内容。
    """
    wanted = normalize_language(language)
    matches = sorted((stream for stream in subtitles
                      if normalize_language(stream.get("language")) == wanted and not stream.get("forced")
                      and stream.get("codec_name") in recipes.EMBEDDED["codecs"]),
                     key=lambda stream: (not stream.get("default"), stream["index"]))
    if not matches:
        return None, []
    chosen = dict(matches[0])
    warnings = []
    if len(matches) > 1:
        warnings.append(f"{len(matches)} text subtitle streams tagged {wanted!r} "
                        f"(indices {', '.join(str(s['index']) for s in sorted(matches, key=lambda s: s['index']))}); "
                        f"using index {chosen['index']}")
    return chosen, warnings


def subtitle_command(ffmpeg: Path, video: Path, index: int) -> list[str]:
    """把绝对流索引 `index` 的文本字幕轨转成 SRT 写到 stdout。"""
    return [str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(video),
            "-map", f"0:{index}", "-c:s", "srt", "-f", "srt", "pipe:1"]


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


def derive_filter(track: AudioTrack) -> str:
    media = recipes.MEDIA
    correction = ([media["sample_rate_correction"]["filter"].format(true=track.corrected_sample_rate,
                                                                    declared=track.sample_rate)]
                  if track.corrected_sample_rate else [])
    return ",".join((*correction, media["timeline_filter"], pan_filter(track), media["resample_filter"]))


def derive_command(ffmpeg: Path, video: Path, track: AudioTrack, output: Path) -> list[str]:
    media = recipes.MEDIA
    return [str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "level+verbose", "-y", "-i", str(video),
            "-map", f"0:{track.index}", "-vn", "-sn", "-dn", "-af", derive_filter(track),
            "-c:a", media["codec"], *media["output_flags"], str(output)]


def parse_compensation(log: str, swr_samples: tuple[int, int], track: AudioTrack,
                       decoded_s: float) -> dict[str, Any]:
    """补偿统计（只作诊断）：swr 报告的（补入, 丢弃）样本数（`digest_decode_log` 边读边累加；输入采样率，
    含起始静音补齐，不完整），以及按 `log` 里 ffmpeg 结束统计算出的净补偿秒数（派生时长 − 解码出的输入时长，
    正为补入、负为丢弃）。采样率标错已纠正时，输入时长按纠正后的采样率算。"""
    input_samples = next((int(samples) for index, samples in _INPUT_SAMPLES.findall(log)
                          if int(index) == track.index), None)
    rate = track.corrected_sample_rate or track.sample_rate
    net = None
    if input_samples is not None and rate:
        net = round(decoded_s - input_samples / rate, 6)
    return {"swr_reported_silence_samples": swr_samples[0], "swr_reported_discarded_samples": swr_samples[1],
            "input_samples": input_samples, "net_padding_s": net}


class _HeadTail:
    """按到达顺序写前 `LOG_HEAD_TAIL` 条，之后只留最后 `LOG_HEAD_TAIL` 条，结束时写出省略条数与这些行。"""

    def __init__(self, label: str, out: IO[str]) -> None:
        self.label, self.out, self.seen = label, out, 0
        self.tail: deque[str] = deque(maxlen=LOG_HEAD_TAIL)

    def add(self, line: str) -> None:
        self.seen += 1
        if self.seen <= LOG_HEAD_TAIL:
            self.out.write(line + "\n")
        else:
            self.tail.append(line)

    def finish(self) -> None:
        if not self.tail:
            return
        omitted = self.seen - LOG_HEAD_TAIL - len(self.tail)
        self.out.write(f"[kototoki] {omitted} {self.label} line(s) omitted; the last {len(self.tail)} follow\n"
                       if omitted else f"[kototoki] {self.label} lines after the first {LOG_HEAD_TAIL} follow\n")
        self.out.writelines(line + "\n" for line in self.tail)


def digest_decode_log(lines: Iterable[str], out: IO[str],
                      track: AudioTrack) -> tuple[str, tuple[int, int], dict[str, Any]]:
    """边读 `-loglevel level+verbose` 的 stderr 边写精简日志到 `out`；返回原样保留的行（含结束统计，供
    `parse_compensation`）、swr 报告的（补入, 丢弃）样本数之和与诊断统计。规则见模块页"解码日志"：info 行、
    无上下文行、`in#`／`out#` 行原样保留；error／warning 行与 swr 补偿行各留前后 100 条；其余 verbose 行只计数；
    末尾附消息类型计数表。"""
    kept: list[str] = []
    types: Counter[tuple[str, str]] = Counter()
    examples: dict[tuple[str, str], str] = {}
    flagged, swr = _HeadTail("error/warning", out), _HeadTail("resampler compensation", out)
    swr_added = swr_dropped = 0
    # 刷屏的 verbose 行几乎都是逐字重复的少数几种（每秒可达数十万行）：按原文缓存其类型、只计原文条数，
    # 结束时再并入类型计数，免得逐行跑正则拖慢 ffmpeg。缓存与原文计数都设上限。
    counted: dict[str, tuple[str, str]] = {}
    pending: Counter[str] = Counter()

    def classify(line: str) -> tuple[str, str, str] | None:
        """(级别, 类型模式, 去向)；去向为 flag（error／warning）、swr、keep（原样写）或 count（只计数）。"""
        match = _LEVEL_LINE.fullmatch(line)
        if match is None:
            return None
        context, level, message = match.groups()
        pattern = _DIGITS.sub("N", _ADDRESS.sub("", context) + message)
        if level in ERROR_LEVELS or level == "warning":
            return level, pattern, "flag"
        if _SWR_ADDED.search(message) or _SWR_DROPPED.search(message):
            return level, pattern, "swr"
        if level == "info" or not context or context.startswith(("[in#", "[out#")):
            return level, pattern, "keep"
        return level, pattern, "count"

    def flush() -> None:
        for text, count in pending.items():
            types[counted[text]] += count
        pending.clear()

    for raw in lines:
        line = raw.rstrip("\r\n")
        if line in counted:
            pending[line] += 1
            continue
        if not line.strip():
            continue
        result = classify(line)
        if result is None:  # 没有级别标签（level+ 下不应出现）：原样保留
            out.write(line + "\n")
            kept.append(line)
            continue
        level, pattern, route = result
        key = (level, pattern)
        examples.setdefault(key, line)
        if route == "count":
            if len(counted) >= DECODE_LOG_CACHE:
                flush()
                counted.clear()
            counted[line] = key
            pending[line] += 1
            continue
        types[key] += 1
        if route == "flag":
            flagged.add(line)
        elif route == "swr":
            swr.add(line)
            swr_added += sum(int(n) for n in _SWR_ADDED.findall(line))
            swr_dropped += sum(int(n) for n in _SWR_DROPPED.findall(line))
        else:
            out.write(line + "\n")
            kept.append(line)
    flush()
    levels: Counter[str] = Counter()
    for (level, _), count in types.items():
        levels[level] += count
    flagged.finish()
    swr.finish()
    ranked = sorted(types.items(), key=lambda item: (-item[1], item[0]))
    out.write(f"[kototoki] message counts by level: {dict(sorted(levels.items()))}\n")
    out.write("[kototoki] message types (count, [level] pattern, first example):\n")
    for (level, pattern), count in ranked:
        out.write(f"{count:>10}  [{level}] {pattern}\n            e.g. {examples[level, pattern]}\n")
    text = "\n".join(kept)
    decode_errors = next((int(errors) for index, errors in _DECODE_ERRORS.findall(text)
                          if int(index) == track.index), None)
    messages = [{"level": level, "count": count, "pattern": pattern, "example": examples[level, pattern]}
                for (level, pattern), count in ranked if level in ERROR_LEVELS or level == "warning"]
    return text, (swr_added, swr_dropped), {"levels": dict(sorted(levels.items())), "decode_errors": decode_errors,
                  "messages": messages[:DIAGNOSTIC_MESSAGES]}


def error_lines(diagnostics: Mapping[str, Any]) -> int:
    """诊断统计里 error 级（含 fatal、panic）的行数。"""
    return sum(diagnostics["levels"].get(level, 0) for level in ERROR_LEVELS)


def check_duration(decoded_s: float, reference_s: float, *, has_video: bool) -> list[str]:
    """解码与参照时长（视频流或音频输入的所选音轨）偏差超过容差时：视频输入短于参照判失败（`MediaError`，
    字幕会对不上画面）；音频输入短于参照只返回告警——没有画面要对齐，且 VBR MP3 缺 Xing 头时 ffprobe 的
    时长是按码率估的、不可信（ADR-0007「输入范围」）。长于参照返回告警；视频输入超过参照 `MAX_OVERLONG_RATIO` 倍判失败
    （时间戳严重断裂，`aresample=async` 补出数小时静音）。"""
    tolerance = recipes.MEDIA["duration_tolerance_s"]
    if reference_s - decoded_s > tolerance:
        message = (f"Decoded audio is {reference_s - decoded_s:.3f} s shorter than the input duration "
                   f"({decoded_s:.3f} s vs {reference_s:.3f} s)")
        if not has_video:
            return [f"{message}; audio input, continuing (the duration may be an estimate)"]
        raise MediaError(f"{message}; treating it as truncated")
    if decoded_s - reference_s > tolerance:
        message = (f"Decoded audio is {decoded_s - reference_s:.3f} s longer than the input duration "
                   f"({decoded_s:.3f} s vs {reference_s:.3f} s)")
        if has_video and decoded_s > reference_s * MAX_OVERLONG_RATIO:
            raise MediaError(f"{message}; more than {MAX_OVERLONG_RATIO}x, treating the timestamps as broken")
        return [message]
    return []


# --- 子进程 ---------------------------------------------------------------------------------

FFMPEG_VERSION = re.compile(r"^ffmpeg version (\S+)", re.MULTILINE)


def parse_ffmpeg_version(text: str) -> str | None:
    match = FFMPEG_VERSION.search(text)
    return match.group(1) if match else None


def _format_error(exc: BaseException) -> str:
    """将异常压成单行 `<类型>: <首行消息>`（截断到 200 字符）。"""
    message = str(exc).strip()
    if not message:
        return type(exc).__name__
    return f"{type(exc).__name__}: {message.splitlines()[0][:200]}"


def _stderr_summary(text: str, *, limit: int = 200) -> str:
    """将进程 stderr/stdout 压成单行摘要（首条非空行截断到 `limit` 字符，附其余行数）。"""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    first = lines[0][:limit]
    return f"{first} (+{len(lines) - 1} more line(s))" if len(lines) > 1 else first


def probe_ffmpeg_version(ffmpeg: Path) -> tuple[str, str | None]:
    """探测 `ffmpeg -version`：返回 `(版本号, None)`，或 `("unavailable", 含可执行路径与具体原因的诊断说明)`。"""
    executable = Path(ffmpeg)
    try:
        result = _run([str(executable), "-version"])
    except OSError as error:
        return "unavailable", f"failed to execute {executable} ({_format_error(error)})"
    if result.returncode != 0:
        detail = _stderr_summary(result.stderr) or _stderr_summary(result.stdout) or "no output"
        return "unavailable", f"{executable} exited with code {result.returncode}: {detail}"
    version = parse_ffmpeg_version(result.stdout)
    if not version:
        detail = _stderr_summary(result.stdout) or _stderr_summary(result.stderr) or "empty output"
        return "unavailable", f"unexpected `ffmpeg -version` output from {executable}: {detail}"
    return version, None


def ffmpeg_version(ffmpeg: Path) -> str:
    """`ffmpeg -version` 报的构建版本（如 `n9.0.2-31-g…`），写进运行日志首行；取不到时为 `unavailable`。"""
    return probe_ffmpeg_version(ffmpeg)[0]


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(contained(command), stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8",
                          errors="replace", check=False)


def _run_decode(command: list[str], log_path: Path,
                track: AudioTrack) -> tuple[int, str, tuple[int, int], dict[str, Any], bool]:
    """运行解码命令，stderr 流式经 `digest_decode_log` 写进同目录临时文件再原子替换 `log_path`；
    返回 `(退出码, kept, swr_samples, diagnostics, log_overwritten)`。替换前异常退出时清理临时文件，不破坏旧日志。
    """
    partial_log = _partial(log_path)
    try:
        with open(partial_log, "w", encoding="utf-8", newline="\n") as log, \
                subprocess.Popen(contained(command), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.PIPE, encoding="utf-8", errors="replace") as process:
            log.write(f"$ {shlex.join(command)}\n")
            assert process.stderr is not None
            try:
                kept, swr_samples, diagnostics = digest_decode_log(process.stderr, log, track)
            except BaseException:
                process.kill()
                raise
            returncode = process.wait()
            log.flush()
            os.fsync(log.fileno())
        existed = log_path.exists()
        os.replace(partial_log, log_path)
        return returncode, kept, swr_samples, diagnostics, existed
    finally:
        partial_log.unlink(missing_ok=True)


def _partial(path: Path) -> Path:
    """同目录临时输出，保留扩展名供 ffmpeg 推断封装格式。"""
    return path.with_name(f".{path.stem}.{os.getpid()}.partial{path.suffix}")


def probe(path: Path, config: Config) -> Probe:
    """ffprobe 全部流并按 `config.input.audio_language` 选音轨；退出码为 0 但 stderr 非空时追加告警。"""
    result = _run(probe_command(config.paths.ffprobe, Path(path)))
    if result.returncode != 0:
        raise MediaError(f"ffprobe failed ({result.returncode}): {result.stderr.strip()}")
    parsed = parse_probe(json.loads(result.stdout), config.input.audio_language)
    if stderr := _stderr_summary(result.stderr):
        warning = f"ffprobe reported stderr despite exit 0: {stderr}"
        return replace(parsed, warnings=(*parsed.warnings, warning), ffprobe_warnings=(warning,))
    return parsed


def extract_subtitle(video: Path, index: int, ffmpeg: Path, *, warnings: list[str] | None = None) -> str:
    """内嵌文本字幕轨经 ffmpeg 转出的 SRT 文本（UTF-8，未清洗；清洗在 `kototoki.embedded.clean`）。不写任何文件。

    退出码为 0 但 stderr 非空时，若调用方传入 `warnings` 列表则追加摘要告警。
    """
    result = _run(subtitle_command(ffmpeg, Path(video), index))
    if result.returncode != 0:
        raise MediaError(f"ffmpeg subtitle extraction failed ({result.returncode}): {result.stderr.strip()[-2000:]}")
    if warnings is not None and (stderr := _stderr_summary(result.stderr)):
        warnings.append(f"ffmpeg subtitle extraction reported stderr despite exit 0: {stderr}")
    return result.stdout


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


def extract(path: Path, work_dir: Path, probe_result: Probe, config: Config) -> Extract:
    """从输入容器按绝对流索引解码，补齐时间轴、下混、重采样为 `audio-16k.wav`，精简后的解码日志原子写 `extract.log`。

    时长校验在替换目标之前完成：截断时不留下 `audio-16k.wav`，只留日志。
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    target, log_path = work_dir / AUDIO_16K, work_dir / EXTRACT_LOG
    partial = _partial(target)
    track = probe_result.audio
    command = derive_command(config.paths.ffmpeg, Path(path), track, partial)  # 不支持的下混布局在此失败，不运行 ffmpeg
    overwritten: list[str] = []
    try:
        returncode, kept, swr_samples, diagnostics, log_overwritten = _run_decode(command, log_path, track)
        if log_overwritten:
            overwritten.append(EXTRACT_LOG)
        if returncode != 0:
            raise MediaError(f"ffmpeg decode failed ({returncode}); see {EXTRACT_LOG}")
        rate, samples, pcm_sha256 = _wav_pcm(partial)
        if rate != recipes.SAMPLE_RATE:
            raise MediaError(f"Derived WAV sample rate is {rate}, expected {recipes.SAMPLE_RATE}")
        decoded_s = samples / rate
        warnings = check_duration(decoded_s, probe_result.duration_s, has_video=probe_result.has_video)
        if errors := error_lines(diagnostics):
            warnings.append(f"ffmpeg reported {errors} error line(s) while decoding; see {EXTRACT_LOG}")
        wav_existed = target.exists()
        os.replace(partial, target)
        if wav_existed:
            overwritten.append(AUDIO_16K)
    except MediaError as error:
        if overwritten and not error.overwritten:
            error.overwritten = tuple(overwritten)
        raise
    finally:
        partial.unlink(missing_ok=True)
    return Extract(wav=target, log=log_path, sample_rate=rate, samples=samples,
                   pcm_sha256=pcm_sha256, decoded_duration_s=decoded_s,
                   duration_s=probe_result.duration_s, offset_s=float(recipes.MEDIA["offset_s"]),
                   pan=pan_filter(track), compensation=parse_compensation(kept, swr_samples, track, decoded_s),
                   warnings=tuple(warnings), diagnostics=diagnostics, overwritten=tuple(overwritten))
