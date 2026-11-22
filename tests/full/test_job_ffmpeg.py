"""端到端 full 测试：项目内 ffmpeg 合成的数秒视频与音频走完整批次编排，检查源文件旁的双语字幕发布。

沿用 `tests.core.test_job.JobCase` 的接缝：媒体阶段换成真实 `media.probe`／`extract`（ffmpeg／ffprobe 取
`config.load` 的默认路径，缺失时 setUp 失败而不是跳过），GPU 阶段仍由 `tests/fake_worker.py` 子进程顶替、
cue 构建、专名建表、翻译仍是假实现；不经 `python -m kototoki` 子进程、不起 llama-server／Strata、不加载模型。
"""

from __future__ import annotations

import subprocess
import unittest
import wave

from kototoki import artifacts, recipes
from tests.core.test_job import MERGED, SRT_JA, JobCase

SECONDS = 3
SINE = f"aevalsrc='0.5*sin(2*PI*440*t)|0.5*sin(2*PI*660*t)':c=stereo:s=48000:d={SECONDS}"


class EndToEndTests(JobCase):
    FAKE_MEDIA = False

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
        self.assertEqual(list(work.glob("audio.*")), [])  # ADR-0007「输入范围」：不流复制原始音轨
        self.assertEqual([launch["ids"] for launch in self.launches()], [self.ids(rel)] * 3)
        identifier = self.ids(rel)[0]
        # 共享 Strata session：names 启动、翻译后退出（ADR-0029「Strata session」）
        self.assertEqual(self.calls, ["session_enter", f"names:{identifier}", f"translate:{identifier}",
                                      "session_exit", "merge"])
        self.assertTrue((work / artifacts.NAME_TABLE).is_file())
        self.assertFalse((work / "names-apply.json").exists())  # 已废止的发布时替换（现见 ADR-0028「表的使用与校对」）：没有发布时替换
        self.assertEqual((work / "ja.srt").read_text(encoding="utf-8"), SRT_JA)  # 日文字幕留在工作目录

        self.assertEqual(self.final(rel).read_text(encoding="utf-8"), MERGED)
        self.assertEqual(sorted(p.name for p in (self.input / "S1").iterdir()),
                         ["ep 01 テスト.ja-zh.srt", "ep 01 テスト.mkv"])
        published = self.published(rel)
        self.assertEqual(published["sha256"], artifacts.sha256_file(self.final(rel)))
        self.assertIn("names", published["sources"])
        self.assertNotIn("names_apply", published["sources"])

    def make_subtitled_video(self, rel: str, subtitle: str, text: str, *extra: str) -> None:
        """`make_video` 的片段再加一条标 `jpn` 的文本字幕轨（`subtitle` 为字幕文件名，决定格式；`extra` 追加输出参数）。"""
        source = self.root / subtitle
        source.write_text(text, encoding="utf-8", newline="\n")
        self.ffmpeg(rel, "-f", "lavfi", "-i", f"color=c=gray:s=64x64:r=25:d={SECONDS}", "-f", "lavfi", "-i", SINE,
                    "-i", str(source), "-map", "0:v", "-map", "1:a", "-map", "2:s", "-c:v", "mpeg4", "-c:a", "flac",
                    "-metadata:s:a:0", "language=jpn", "-metadata:s:s:0", "language=jpn", *extra)

    def assert_embedded(self, rel: str, ja_srt: str, codec: str) -> None:
        summary = self.run_job()
        self.assertEqual((summary.published, summary.embedded, summary.exit_code), ([rel], [rel], 0))
        work = self.work_dir(rel)
        self.assertEqual((work / "ja.srt").read_text(encoding="utf-8"), ja_srt)
        self.assertEqual(artifacts.read_json(work / artifacts.JA_EMBEDDED)["stream"]["codec_name"], codec)
        self.assertFalse((work / artifacts.AUDIO_16K).exists())  # 不提取音频
        self.assertEqual(self.launches(), [])                    # 不起任何 GPU worker
        self.assertIn("ja_embedded", self.published(rel)["sources"])
        self.assertTrue(self.final(rel).is_file())

    def test_embedded_subrip_track_replaces_speech_recognition(self) -> None:
        # 容器起点不为 0（+2 s）：字幕时间与派生 WAV 一样以 ffmpeg 的输入零点为准，仍是 0.5 s
        self.make_subtitled_video("srt 字幕.mkv", "ja.srt",
                                  "1\n00:00:00,500 --> 00:00:01,500\n<i>こんにちは</i>\n二行目\n\n"
                                  "2\n00:00:01,600 --> 00:00:02,400\n（ドアの音）\n", "-c:s", "srt", "-output_ts_offset", "2")
        self.assert_embedded("srt 字幕.mkv", "1\n00:00:00,500 --> 00:00:01,500\nこんにちは 二行目\n\n"
                                             "2\n00:00:01,600 --> 00:00:02,400\n（ドアの音）\n", "subrip")


if __name__ == "__main__":
    unittest.main()
