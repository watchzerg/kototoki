"""端到端 full 测试：项目内 ffmpeg 合成的数秒视频与音频走完整批次编排，检查源文件旁的双语字幕发布。

沿用 `tests.core.test_job.JobCase` 的接缝：媒体阶段换成真实 `media.probe`／`extract`（ffmpeg／ffprobe 取
`config.load` 的默认路径，缺失时 setUp 失败而不是跳过），GPU 阶段仍由 `tests/fake_worker.py` 子进程顶替、
cue 构建、专名建表、翻译仍是假实现；不经 `python -m kototoki` 子进程、不起 llama-server／Strata、不加载模型。
"""

from __future__ import annotations

import io
import subprocess
import unittest
import wave

from kototoki import artifacts, recipes
from tests.core.test_job import LOG_LINE, MERGED, SRT_JA, JobCase

SECONDS = 3
SINE = f"aevalsrc='0.5*sin(2*PI*440*t)|0.5*sin(2*PI*660*t)':c=stereo:s=48000:d={SECONDS}"


class EndToEndTests(JobCase):
    FAKE_MEDIA = False

    def setUp(self) -> None:
        super().setUp()
        for binary in (self.config.paths.ffmpeg, self.config.paths.ffprobe):
            if not binary.is_file():
                self.fail(f"{binary} not found: run `just install` (ffmpeg is listed in assets.toml) "
                          "or set [paths] ffmpeg/ffprobe")

    def ffmpeg(self, rel: str, *args: str) -> None:
        path = self.input / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        command = [str(self.config.paths.ffmpeg), "-nostdin", "-loglevel", "error", "-y", *args, str(path)]
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8",
                                errors="replace", check=False)
        self.assertEqual(result.returncode, 0, result.stderr[-1500:])

    def make_video(self, rel: str, language: str = "jpn") -> None:
        """64x64 灰屏 + 48 kHz 立体声正弦、音轨标 `language` 的 mkv。"""
        self.ffmpeg(rel, "-f", "lavfi", "-i", f"color=c=gray:s=64x64:r=25:d={SECONDS}", "-f", "lavfi", "-i", SINE,
                    "-map", "0:v", "-map", "1:a", "-c:v", "mpeg4", "-c:a", "flac",
                    "-metadata:s:a:0", f"language={language}")

    def make_audio(self, rel: str) -> None:
        """只有 48 kHz 立体声正弦的音频文件（编码器由扩展名决定）。"""
        self.ffmpeg(rel, "-f", "lavfi", "-i", SINE)

    def test_synthesized_video_publishes_bilingual_subtitle_next_to_it(self) -> None:
        rel = "S1/ep 01 テスト.mkv"
        self.make_video(rel)
        summary = self.run_job()
        self.assertEqual((summary.total, summary.published, summary.exit_code), (1, [rel], 0))

        work = self.work_dir(rel)
        with wave.open(str(work / artifacts.AUDIO_16K), "rb") as reader:
            self.assertEqual((reader.getframerate(), reader.getnchannels(), reader.getsampwidth()),
                             (recipes.SAMPLE_RATE, 1, 2))
            self.assertAlmostEqual(reader.getnframes() / recipes.SAMPLE_RATE, SECONDS, delta=0.1)
        self.assertEqual(len(list(work.glob(f"{artifacts.AUDIO_COPY_STEM}.*"))), 1)  # 视频输入做原音轨流复制
        self.assertEqual([launch["ids"] for launch in self.launches()], [self.ids(rel)] * 3)
        identifier = self.ids(rel)[0]
        self.assertEqual(self.calls, ["names_session_enter", f"names:{identifier}", "names_session_exit",
                                      "session_enter", f"translate:{identifier}", "session_exit", "merge"])
        self.assertTrue((work / artifacts.NAME_TABLE).is_file())
        self.assertFalse((work / "names-apply.json").exists())  # ADR-0019：没有发布时替换
        self.assertEqual((work / "ja.srt").read_text(encoding="utf-8"), SRT_JA)  # 日文字幕留在工作目录

        self.assertEqual(self.final(rel).read_text(encoding="utf-8"), MERGED)
        self.assertEqual(sorted(p.name for p in (self.input / "S1").iterdir()),
                         ["ep 01 テスト.ja-zh.srt", "ep 01 テスト.mkv"])
        published = self.published(rel)
        self.assertEqual(published["sha256"], artifacts.sha256_file(self.final(rel)))
        self.assertIn("names", published["sources"])
        self.assertNotIn("names_apply", published["sources"])

    def test_synthesized_audio_skips_stream_copy(self) -> None:
        rel = "ep02.flac"
        self.make_audio(rel)
        summary = self.run_job()
        self.assertEqual((summary.published, summary.exit_code), ([rel], 0))
        work = self.work_dir(rel)
        probe = artifacts.read_json(work / artifacts.PROBE)
        self.assertFalse(probe["has_video"])
        self.assertIsNone(probe["extract"]["audio_copy"])
        self.assertEqual(list(work.glob(f"{artifacts.AUDIO_COPY_STEM}.*")), [])
        with wave.open(str(work / artifacts.AUDIO_16K), "rb") as reader:
            self.assertAlmostEqual(reader.getnframes() / recipes.SAMPLE_RATE, SECONDS, delta=0.1)
        self.assertEqual(self.final(rel).read_text(encoding="utf-8"), MERGED)

    def test_missing_jpn_track_is_logged_as_warning(self) -> None:
        rel = "no-jpn.mkv"
        self.make_video(rel, language="eng")
        console = io.StringIO()
        summary = self.run_job(console=console)
        self.assertEqual((summary.published, summary.exit_code), ([rel], 0))
        warnings = [m[2] for m in map(LOG_LINE.match, console.getvalue().splitlines()) if m and m[1] == "WARNING"]
        self.assertEqual(warnings, [f"[extract] {rel}: No non-commentary audio stream tagged 'jpn'; "
                                    "using the first audio stream (index 1)"])


if __name__ == "__main__":
    unittest.main()
