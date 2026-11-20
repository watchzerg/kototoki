"""`kototoki.media` 的 full 层离线集成测试：用真实 ffmpeg 合成几秒的小片段，验证时间轴零点、下混与各编码的解码。

不需要模型、GPU 或网络；ffmpeg／ffprobe 取 `config.load` 的默认路径（缺失时 setUpClass 失败并给出处理办法）。
所有媒体都放在含空格和非 ASCII 字符的目录里，覆盖 Windows 路径传参。
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass, field
from pathlib import Path
import subprocess
import tempfile
import unittest
import wave

from kototoki import config, job, media, recipes

RATE = recipes.SAMPLE_RATE
FRAME = RATE // 100  # 10 ms
FULL_SCALE = 32767


@dataclass
class Audio:
    """一条合成音轨：lavfi 源、可选的输入时间偏移、滤镜与元数据。"""
    src: str
    itsoffset: float = 0.0
    af: str | None = None
    language: str | None = None
    disposition: str | None = None
    codec: str | None = None  # 覆盖 make_clip 的默认音频编码


def tone_src(*, dur: float, freq: float = 440.0, amp: float = 0.5, bursts: list[tuple[float, float]] | None = None,
             channels: list[str] | None = None, layout: str = "mono", rate: int = 48000) -> str:
    """aevalsrc 源。`bursts` 给出有声区间（音轨本地时间）；`channels` 给出逐声道表达式（覆盖默认正弦）。"""
    if channels is None:
        expr = f"{amp}*sin(2*PI*{freq}*t)"
        if bursts is not None:
            expr += "*(" + "+".join(f"between(t,{a},{b})" for a, b in bursts) + ")"
        channels = [expr]
    return f"aevalsrc='{'|'.join(channels)}':c={layout}:s={rate}:d={dur}"


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8",
                            errors="replace", check=False)
    if result.returncode != 0:
        raise AssertionError(f"{Path(command[0]).name} failed ({result.returncode}): {result.stderr.strip()[-1500:]}")
    return result


def read_wav(path: Path) -> tuple[int, int, list[int]]:
    """(采样率, 声道数, 样本)；只读 16 bit PCM。"""
    with wave.open(str(path), "rb") as reader:
        assert reader.getsampwidth() == 2
        data = array("h")
        data.frombytes(reader.readframes(reader.getnframes()))
        return reader.getframerate(), reader.getnchannels(), list(data)


def first_onset(samples: list[int], start: int = 0, threshold: int = 2000) -> int:
    """从 `start` 起第一个幅度超过阈值的样本下标。"""
    for index in range(start, len(samples)):
        if abs(samples[index]) > threshold:
            return index
    raise AssertionError("no tone found in the WAV")


def peak(samples: list[int]) -> int:
    return max(abs(sample) for sample in samples)


@dataclass
class Clip:
    path: Path
    video_s: float
    audios: list[Audio] = field(default_factory=list)


class MediaFfmpegCase(unittest.TestCase):
    """基类：定位 ffmpeg、准备含空格与日文的目录、合成片段。"""

    cfg: config.Config

    @classmethod
    def setUpClass(cls) -> None:
        cls._cfg_tmp = tempfile.TemporaryDirectory()
        cfg_dir = Path(cls._cfg_tmp.name)
        (cfg_dir / "config.toml").write_text('[paths]\ninput_dir = "."\n', encoding="utf-8")
        cls.addClassCleanup(cls._cfg_tmp.cleanup)
        cls.cfg = config.load(cfg_dir / "config.toml")  # PATH 上没有 ffmpeg 时 ConfigError

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.media_dir = Path(self._tmp.name) / "媒体 テスト"
        self.media_dir.mkdir()
        self.work_dir = self.media_dir / "work dir 作業"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def make_clip(self, name: str, video_s: float, audios: list[Audio], *, codec: str = "flac") -> Path:
        path = self.media_dir / name
        command = [str(self.cfg.paths.ffmpeg), "-nostdin", "-loglevel", "error", "-y",
                   "-f", "lavfi", "-i", f"color=c=gray:s=64x64:r=25:d={video_s}"]
        for audio in audios:
            if audio.itsoffset:
                command += ["-itsoffset", str(audio.itsoffset)]
            command += ["-f", "lavfi", "-i", audio.src]
        command += ["-map", "0:v"]
        for number in range(len(audios)):
            command += ["-map", f"{number + 1}:a"]
        command += ["-c:v", "mpeg4", "-c:a", codec]
        for number, audio in enumerate(audios):
            if audio.codec:
                command += [f"-c:a:{number}", audio.codec]
            if audio.af:
                command += [f"-filter:a:{number}", audio.af]
            if audio.language:
                command += [f"-metadata:s:a:{number}", f"language={audio.language}"]
            if audio.disposition is not None:
                command += [f"-disposition:a:{number}", audio.disposition]
        command.append(str(path))
        run(command)
        return path

    def extract_clip(self, path: Path) -> tuple[media.Probe, media.Extract]:
        probe = media.probe(path, self.cfg)
        return probe, media.extract(path, self.work_dir, probe, self.cfg)


class TimelineTests(MediaFfmpegCase):
    def assertTime(self, actual_s: float, expected_s: float, tolerance_s: float = 0.010) -> None:
        self.assertAlmostEqual(actual_s, expected_s, delta=tolerance_s)

    def test_delayed_audio_is_padded_so_sample_zero_is_video_zero(self) -> None:
        # 音轨比视频晚 0.5 s 开始；本地 0–0.2 s 与 1.0–1.2 s 各有一段音
        src = tone_src(dur=2.5, bursts=[(0.0, 0.2), (1.0, 1.2)])
        path = self.make_clip("delayed.mkv", 3.0, [Audio(src, itsoffset=0.5)])
        probe, extract = self.extract_clip(path)
        self.assertAlmostEqual(probe.audio.start_time, 0.5, delta=0.05)  # 只作诊断
        _, _, samples = read_wav(extract.wav)
        self.assertLessEqual(peak(samples[:RATE // 2 - 80]), 1)  # 前 0.5 s 为数字静音（留 5 ms 滤波余量）
        onset = first_onset(samples)
        self.assertLess(abs(onset - RATE // 2), FRAME)
        second = first_onset(samples, start=onset + RATE // 2)
        self.assertEqual(extract.offset_s, 0)
        # cue／unit 时间 = sample / 16000 + offset_s，应等于视频时间
        self.assertTime(second / RATE + extract.offset_s, 1.5)
        self.assertTime(onset / RATE + extract.offset_s, 0.5)

    def test_mid_stream_gap_is_filled_with_silence(self) -> None:
        # 音频时间戳在 2.112 s 向后跳 2 s：本地 2.112 s 的音在视频 4.112 s 才出现。2.112 s = 101376 样本，
        # 既是 aevalsrc 1024 样本帧的边界，也是 FLAC 编码器 4608 样本包的边界；不在包边界时跳变会被
        # 推迟到下一个包（ffmpeg 8.0 实测）
        src = tone_src(dur=4.0, bursts=[(0.5, 0.7), (2.112, 2.312)])
        gap = Audio(src, af="asetpts='if(gte(T,2.112),PTS+2/TB,PTS)'")
        path = self.make_clip("gap.mkv", 6.0, [gap])
        probe, extract = self.extract_clip(path)
        _, _, samples = read_wav(extract.wav)
        first = first_onset(samples)
        self.assertLess(abs(first - RATE // 2), FRAME)
        self.assertLessEqual(peak(samples[int(1.0 * RATE):int(3.9 * RATE)]), 1)  # 间隙内无声
        resumed = first_onset(samples, start=int(1.0 * RATE))
        self.assertTime(resumed / RATE + extract.offset_s, 4.112)
        self.assertAlmostEqual(extract.decoded_duration_s, 6.0, delta=0.1)
        self.assertAlmostEqual(extract.compensation["net_padding_s"], 2.0, delta=0.05)
        # 编排据此在运行日志记 WARNING（审计 A-3）：2 s 净补入远超 0.1 s 阈值
        warnings = job.compensation_warnings(extract.compensation, probe.audio.sample_rate)
        self.assertEqual(len(warnings), 1, warnings)
        self.assertRegex(warnings[0], r"^Resampler padded 2\.0\d\d s net")


class DownmixTests(MediaFfmpegCase):
    def test_full_scale_5_1_does_not_clip(self) -> None:
        square = "if(lt(mod(t*100,1),0.5),0.999,-0.999)"
        src = tone_src(dur=2.0, channels=[square] * 6, layout="5.1", rate=RATE)  # 源即 16 kHz：隔离下混，不引入重采样过冲
        path = self.make_clip("surround.mkv", 2.0, [Audio(src)], codec="pcm_s16le")
        probe, extract = self.extract_clip(path)
        self.assertEqual(probe.audio.channels, 6)  # mkv 里的 PCM 不带布局，按声道数回落到 5.1
        self.assertEqual(extract.pan, recipes.PAN["5.1"])
        _, _, samples = read_wav(extract.wav)
        self.assertLess(peak(samples), FULL_SCALE)
        self.assertGreater(peak(samples), 0.8 * FULL_SCALE)
        self.assertNotIn(-32768, samples)

    def test_mono_passthrough(self) -> None:
        path = self.make_clip("mono.mkv", 2.0, [Audio(tone_src(dur=2.0))])
        probe, extract = self.extract_clip(path)
        self.assertEqual(extract.pan, recipes.PAN["mono"])
        rate, channels, samples = read_wav(extract.wav)
        self.assertEqual((rate, channels), (RATE, 1))
        self.assertAlmostEqual(len(samples) / rate, 2.0, delta=0.05)
        self.assertAlmostEqual(extract.decoded_duration_s, probe.duration_s, delta=0.1)

    def test_stereo_averages_channels(self) -> None:
        mono = self.make_clip("mono.mkv", 2.0, [Audio(tone_src(dur=2.0))])
        left_only = tone_src(dur=2.0, channels=["0.5*sin(2*PI*440*t)", "0"], layout="stereo")
        stereo = self.make_clip("stereo.mkv", 2.0, [Audio(left_only)])
        mono_peak = peak(read_wav(self.extract_clip(mono)[1].wav)[2])
        _, extract = self.extract_clip(stereo)
        self.assertEqual(extract.pan, recipes.PAN["stereo"])
        ratio = peak(read_wav(extract.wav)[2]) / mono_peak
        self.assertGreater(ratio, 0.4)
        self.assertLess(ratio, 0.6)


class DurationCheckTests(MediaFfmpegCase):
    # 规则：解码时长短于视频流超过 1 s 判失败（截断）；长于视频超过 1 s 告警，超过 1.5 倍判失败（时间戳断裂，
    # batch-run-fixes 04）。
    def test_audio_longer_than_video_only_warns(self) -> None:
        path = self.make_clip("long-audio.mkv", 4.0, [Audio(tone_src(dur=5.5))])
        _, extract = self.extract_clip(path)
        self.assertTrue(extract.warnings)
        self.assertTrue(extract.wav.is_file())

    def test_audio_far_longer_than_video_fails_without_wav(self) -> None:
        path = self.make_clip("overlong-audio.mkv", 3.0, [Audio(tone_src(dur=5.0))])
        probe = media.probe(path, self.cfg)
        with self.assertRaisesRegex(media.MediaError, "timestamps as broken"):
            media.extract(path, self.work_dir, probe, self.cfg)
        self.assertFalse((self.work_dir / "audio-16k.wav").exists())

    def test_audio_shorter_than_video_fails_without_wav(self) -> None:
        path = self.make_clip("short-audio.mkv", 4.0, [Audio(tone_src(dur=2.0))])
        probe = media.probe(path, self.cfg)
        with self.assertRaises(media.MediaError):
            media.extract(path, self.work_dir, probe, self.cfg)
        self.assertFalse((self.work_dir / "audio-16k.wav").exists())
        self.assertTrue((self.work_dir / "extract.log").is_file())

    def test_duration_source_is_documented_value(self) -> None:
        path = self.make_clip("src.mkv", 2.0, [Audio(tone_src(dur=2.0))])
        probe = media.probe(path, self.cfg)
        self.assertIn(probe.duration_source, {"stream.duration", "stream.tags.DURATION", "format.duration"})
        self.assertAlmostEqual(probe.duration_s, 2.0, delta=0.1)


class VideoCodecTests(MediaFfmpegCase):
    """视频输入的各种音频编码都只派生 WAV，不留原始音轨副本（ADR-0007「输入范围」）。"""

    def test_codecs_decode_without_audio_copy(self) -> None:
        cases = [("flac", "mkv"), ("pcm_s16le", "mkv"), ("pcm_s16be", "mov"), ("pcm_s24be", "mov")]
        for codec, container in cases:
            with self.subTest(codec=codec):
                path = self.make_clip(f"{codec}.{container}", 2.0, [Audio(tone_src(dur=2.0))], codec=codec)
                self.work_dir = self.media_dir / f"work {codec}"
                probe, extract = self.extract_clip(path)
                self.assertEqual(probe.audio.codec_name, codec)
                self.assertEqual(sorted(item.name for item in self.work_dir.iterdir()),
                                 ["audio-16k.wav", "extract.log"])
                rate, channels, samples = read_wav(extract.wav)
                self.assertEqual((rate, channels), (RATE, 1))
                self.assertAlmostEqual(len(samples) / rate, 2.0, delta=0.05)


class AudioOnlyInputTests(MediaFfmpegCase):
    """音频输入（ADR-0007「输入范围」）：WAV 照常派生，时长参照取所选音轨。"""

    def test_flac_input_derives_correct_wav(self) -> None:
        path = self.media_dir / "音声.flac"
        run([str(self.cfg.paths.ffmpeg), "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi",
             "-i", tone_src(dur=2.0), "-c:a", "flac", str(path)])
        probe, extract = self.extract_clip(path)
        self.assertFalse(probe.has_video)
        self.assertAlmostEqual(probe.duration_s, 2.0, delta=0.1)
        rate, channels, samples = read_wav(extract.wav)
        self.assertEqual((rate, channels), (RATE, 1))
        self.assertAlmostEqual(len(samples) / rate, 2.0, delta=0.05)
        self.assertAlmostEqual(extract.decoded_duration_s, probe.duration_s, delta=0.1)


class TrackSelectionTests(MediaFfmpegCase):
    def test_picks_normalized_language_non_commentary_track(self) -> None:
        def track(amp: float, **kwargs: str | None) -> Audio:
            return Audio(tone_src(dur=2.0, amp=amp), **kwargs)  # type: ignore[arg-type]

        path = self.make_clip("tracks.mkv", 2.0, [
            track(0.2, language="eng", disposition="default"),
            track(0.4, language="ja", disposition="comment"),  # 语言匹配但是 commentary
            track(0.6, language="jp", disposition="0"),        # 非默认，靠语言归一化匹配
        ])
        probe, extract = self.extract_clip(path)
        self.assertEqual(len(probe.audio_tracks), 3)
        self.assertEqual(probe.audio.index, probe.audio_tracks[2].index)
        self.assertEqual(probe.audio.index, 3)  # 视频为 0，音轨为 1、2、3
        self.assertAlmostEqual(peak(read_wav(extract.wav)[2]) / FULL_SCALE, 0.6, delta=0.05)


class DecodeLogTests(MediaFfmpegCase):
    """真实 ffmpeg 的 `level+verbose` 输出经 `digest_decode_log` 精简、计数（batch-run-fixes 03）。"""

    def test_clean_clip_has_no_errors_and_keeps_end_statistics(self) -> None:
        path = self.make_clip("clean.mkv", 2.0, [Audio(tone_src(dur=2.0))])
        probe, extract = self.extract_clip(path)
        self.assertEqual(extract.diagnostics["decode_errors"], 0)
        self.assertEqual(media.error_lines(extract.diagnostics), 0)
        self.assertGreater(extract.diagnostics["levels"]["verbose"], 0)
        self.assertFalse(any("error line(s)" in warning for warning in extract.warnings))
        self.assertIsNotNone(extract.compensation["input_samples"])  # 结束统计行保留下来供补偿解析
        body, table = extract.log.read_text(encoding="utf-8").split("[kototoki] message counts by level", 1)
        self.assertIn("Input stream #0:", body)
        self.assertIn("[kototoki] message types", table)
        self.assertNotIn("[dec:flac", body)  # 解码器等上下文的 verbose 行只计数，只在类型表里出现
        self.assertIn("[dec:flac", table)

    def test_corrupted_aac_reports_decode_errors(self) -> None:
        clean = self.media_dir / "clean.aac"
        run([str(self.cfg.paths.ffmpeg), "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi",
             "-i", "sine=d=4:sample_rate=48000", "-ac", "2", "-c:a", "aac", str(clean)])
        data = bytearray(clean.read_bytes())
        for offset in range(len(data) // 4, 3 * len(data) // 4, 997):  # 中段确定性地翻转若干字节
            data[offset] ^= 0x5A
        path = self.media_dir / "corrupted.aac"
        path.write_bytes(bytes(data))
        _, extract = self.extract_clip(path)
        diagnostics = extract.diagnostics
        self.assertGreater(diagnostics["decode_errors"], 0)
        self.assertGreater(media.error_lines(diagnostics), 0)
        self.assertTrue(diagnostics["messages"])
        self.assertTrue(all(m["level"] in ("error", "warning") for m in diagnostics["messages"]))
        self.assertIn(f"ffmpeg reported {media.error_lines(diagnostics)} error line(s) while decoding; "
                      "see extract.log", extract.warnings)


if __name__ == "__main__":
    unittest.main()
