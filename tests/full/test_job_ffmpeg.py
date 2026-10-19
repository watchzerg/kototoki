"""端到端 full 测试：项目内 ffmpeg 合成的数秒视频走完整批次编排，检查三份 SRT 发布。

沿用 `tests.core.test_job.JobCase` 的接缝：媒体阶段换成真实 `media.probe`／`extract`（ffmpeg／ffprobe 取
`config.load` 的默认路径，缺失时 setUp 失败而不是跳过），GPU 阶段仍由 `tests/fake_worker.py` 子进程顶替、
cue 构建、专名建表与替换、翻译仍是假实现；不经 `python -m kototoki` 子进程、不起 llama-server、不加载模型。
"""

from __future__ import annotations

import io
from pathlib import Path
import subprocess
import unittest
import wave

from kototoki import artifacts, recipes
from tests.core.test_job import LOG_LINE, SRT_JA, SRT_ZH, JobCase

SECONDS = 3


class EndToEndTests(JobCase):
    FAKE_MEDIA = False

    def setUp(self) -> None:
        super().setUp()
        for binary in (self.config.paths.ffmpeg, self.config.paths.ffprobe):
            if not binary.is_file():
                self.fail(f"{binary} not found: run `just install` (ffmpeg is listed in assets.toml) "
                          "or set [paths] ffmpeg/ffprobe")

    def make_video(self, rel: str, language: str = "jpn") -> None:
        """64x64 灰屏 + 48 kHz 立体声正弦、音轨标 `language` 的 mkv。"""
        path = self.input / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        command = [str(self.config.paths.ffmpeg), "-nostdin", "-loglevel", "error", "-y",
                   "-f", "lavfi", "-i", f"color=c=gray:s=64x64:r=25:d={SECONDS}",
                   "-f", "lavfi", "-i", f"aevalsrc='0.5*sin(2*PI*440*t)|0.5*sin(2*PI*660*t)':c=stereo:s=48000:d={SECONDS}",
                   "-map", "0:v", "-map", "1:a", "-c:v", "mpeg4", "-c:a", "flac",
                   "-metadata:s:a:0", f"language={language}", str(path)]
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8",
                                errors="replace", check=False)
        self.assertEqual(result.returncode, 0, result.stderr[-1500:])

    def test_synthesized_video_publishes_three_srts(self) -> None:
        rel = "S1/ep 01 テスト.mkv"
        self.make_video(rel)
        summary = self.run_job()
        self.assertEqual((summary.total, summary.published, summary.exit_code), (1, [rel], 0))

        work = self.work_dir(rel)
        with wave.open(str(work / artifacts.AUDIO_16K), "rb") as reader:
            self.assertEqual((reader.getframerate(), reader.getnchannels(), reader.getsampwidth()),
                             (recipes.SAMPLE_RATE, 1, 2))
            self.assertAlmostEqual(reader.getnframes() / recipes.SAMPLE_RATE, SECONDS, delta=0.1)
        self.assertEqual([launch["ids"] for launch in self.launches()], [self.ids(rel)] * 3)
        identifier = self.ids(rel)[0]
        self.assertEqual(self.calls, ["names_session_enter", f"names:{identifier}", "names_session_exit",
                                      "session_enter", f"translate:{identifier}", "session_exit", "merge"])
        for name in (artifacts.NAME_TABLE, artifacts.NAMES_APPLY):
            self.assertTrue((work / name).is_file(), name)

        self.assertEqual(self.final(rel, "ja").read_text(encoding="utf-8"), SRT_JA)
        self.assertEqual(self.final(rel, "zh").read_text(encoding="utf-8"), SRT_ZH)
        self.assertEqual(self.final(rel, "ja-zh").read_text(encoding="utf-8"),
                         "1\n00:00:01,000 --> 00:00:02,000\n你好\nこんにちは\n")
        self.assertEqual(sorted(Path(p).name for p in self.final(rel, "ja").parent.glob("*.srt")),
                         ["ep 01 テスト.ja-zh.srt", "ep 01 テスト.ja.srt", "ep 01 テスト.zh.srt"])
        published = artifacts.read_published(work)
        self.assertIsNotNone(published)
        self.assertEqual(set(published["sha256"]), {"ja", "zh", "ja-zh"})
        self.assertLessEqual({"names", "names_apply"}, set(published["sources"]))

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
