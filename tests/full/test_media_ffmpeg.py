"""`kototoki.media` 的 full 层离线集成测试：用真实 ffmpeg 合成几秒的小片段，验证时间轴零点、下混与各编码的解码。

不需要模型、GPU 或网络；ffmpeg／ffprobe 取 `config.load` 的默认路径（缺失时 setUpClass 失败并给出处理办法）。
所有媒体都放在含空格和非 ASCII 字符的目录里，覆盖 Windows 路径传参。
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass
from pathlib import Path
import subprocess
import tempfile
import unittest
import wave

from kototoki import config, media, recipes

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


if __name__ == "__main__":
    unittest.main()
