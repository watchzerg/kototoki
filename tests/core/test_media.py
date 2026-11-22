"""media 的纯函数部分：语言归一化、音轨选择、时长来源、容器映射、下混选择、命令行构造、补偿解析。

用 ffmpeg 合成媒体的测试属于 full 层，在 `tests/full/test_media_ffmpeg.py`。
"""

from __future__ import annotations

import unittest

from kototoki import media, recipes


def stream(index: int, kind: str = "audio", **fields: object) -> dict[str, object]:
    return {"index": index, "codec_type": kind, **fields}


def audio(index: int, language: str | None = None, *, default: bool = False, comment: bool = False,
          **fields: object) -> dict[str, object]:
    tags = {"language": language} if language is not None else {}
    return stream(index, codec_name="aac", channels=2, channel_layout="stereo", sample_rate="48000", tags=tags,
                  disposition={"default": int(default), "comment": int(comment)}, **fields)


VIDEO = stream(0, "video", codec_name="h264", duration="100.0")


def track(**fields: object) -> media.AudioTrack:
    base = dict(index=1, codec_name="aac", channels=2, channel_layout="stereo", sample_rate=48000,
                language="jpn", default=True, comment=False, start_time=0.0, duration=100.0)
    return media.AudioTrack(**{**base, **fields})


class LanguageTests(unittest.TestCase):
    def test_japanese_aliases_normalize_to_jpn(self) -> None:
        for tag in ("jpn", "ja", "jp", "JPN", " Ja "):
            self.assertEqual(media.normalize_language(tag), "jpn")
        self.assertEqual(media.normalize_language("ENG"), "eng")
        self.assertIsNone(media.normalize_language(None))
        self.assertIsNone(media.normalize_language(""))


class SelectionTests(unittest.TestCase):
    def select(self, *streams: dict[str, object], language: str = "jpn") -> media.Probe:
        return media.parse_probe({"streams": [VIDEO, *streams], "format": {"duration": "100.5"}}, language)

    def test_language_match_beats_default_flag(self) -> None:
        probe = self.select(audio(1, "eng", default=True), audio(2, "ja"))
        self.assertEqual(probe.audio.index, 2)
        self.assertEqual(probe.warnings, ())

    def test_multiple_matches_prefer_default_and_warn(self) -> None:
        probe = self.select(audio(1, "jpn"), audio(2, "ja", default=True), audio(3, "jp"))
        self.assertEqual(probe.audio.index, 2)
        self.assertEqual(len(probe.warnings), 1)
        self.assertIn("3 audio streams", probe.warnings[0])
        first = self.select(audio(1, "jpn"), audio(2, "jpn"))
        self.assertEqual(first.audio.index, 1)

    def test_no_match_takes_first_audio_and_warns(self) -> None:
        probe = self.select(audio(1, "eng"), audio(2, None), audio(3, "jpn", comment=True))
        self.assertEqual(probe.audio.index, 1)
        self.assertIn("using the first audio stream", probe.warnings[0])


class SampleRateCheckTests(unittest.TestCase):
    """采样率标错（batch-run-fixes 02）：nb_frames × 1024 ÷ 流时长与声明值不符时按真实值解码。"""

    @staticmethod
    def aac(rate: str, frames: str | None, duration: str | None, **fields: object) -> dict[str, object]:
        extra = {key: value for key, value in (("nb_frames", frames), ("duration", duration)) if value is not None}
        return {**audio(1, "jpn"), "profile": "LC", "sample_rate": rate, **extra, **fields}

    def check(self, stream: dict[str, object]) -> tuple[float | None, int | None]:
        rate = stream.get("sample_rate")
        return media.sample_rate_check(stream, int(rate) if rate else None)

    def test_both_mislabeled_directions_are_corrected(self) -> None:
        # 封存样本的元数据：声明 48k、帧数对应 ≈44115；声明 44.1k、帧数对应 ≈47940
        self.assertEqual(self.check(self.aac("48000", "345119", "8010.916187")), (44115.0, 44100))
        self.assertEqual(self.check(self.aac("44100", "440106", "9400.760181")), (47939.6, 48000))


class VideoDurationTests(unittest.TestCase):
    def duration(self, video: dict[str, object], fmt: dict[str, object] | None = None) -> tuple[float, str]:
        probe = media.parse_probe({"streams": [video, audio(1, "jpn")], "format": fmt or {}}, "jpn")
        return probe.duration_s, probe.duration_source

    def test_stream_duration_first(self) -> None:
        self.assertEqual(self.duration(VIDEO, {"duration": "101"}), (100.0, "stream.duration"))

    def test_tag_contradicting_container_takes_smaller_and_warns(self) -> None:
        video = stream(0, "video", tags={"DURATION": "02:02:05.000000000"})  # 7325 s
        probe = media.parse_probe({"streams": [video, audio(1, "jpn")], "format": {"duration": "303"}}, "jpn")
        self.assertEqual((probe.duration_s, probe.duration_source), (303.0, "format.duration"))
        self.assertEqual(len(probe.warnings), 1)
        self.assertIn("stream.tags.DURATION", probe.warnings[0])


class AudioOnlyInputTests(unittest.TestCase):
    """没有视频流（封面图不算）即音频输入：时长参照取所选音轨（ADR-0007「输入范围」）。"""

    def test_audio_only_uses_chosen_audio_stream_duration(self) -> None:
        probe = media.parse_probe({"streams": [audio(0, "eng", duration="10.0"), audio(1, "jpn", duration="61.5")],
                                   "format": {"duration": "61.6"}}, "jpn")
        self.assertFalse(probe.has_video)
        self.assertEqual((probe.audio.index, probe.duration_s, probe.duration_source), (1, 61.5, "stream.duration"))
        self.assertEqual(probe.warnings, ())
        payload = probe.payload()
        self.assertIs(payload["has_video"], False)
        self.assertEqual((payload["duration_s"], payload["duration_source"]), (61.5, "stream.duration"))
        self.assertNotIn("video_duration_s", payload)


class PanSelectionTests(unittest.TestCase):
    def test_layout_and_channel_count_fallback(self) -> None:
        self.assertEqual(media.pan_filter(track(channels=1, channel_layout="mono")), recipes.PAN["mono"])
        self.assertEqual(media.pan_filter(track()), recipes.PAN["stereo"])
        self.assertEqual(media.pan_filter(track(channels=6, channel_layout="5.1(side)")), recipes.PAN["5.1(side)"])
        self.assertEqual(media.pan_filter(track(channels=6, channel_layout="")), recipes.PAN["5.1"])
        self.assertEqual(media.pan_filter(track(channels=8, channel_layout="8 channels")), recipes.PAN["7.1"])


def subtitle(index: int, codec: str = "subrip", language: str | None = "jpn", *, default: bool = False,
             forced: bool = False) -> dict[str, object]:
    return {"index": index, "codec_name": codec, "language": language, "default": default, "forced": forced}


class SubtitleSelectionTests(unittest.TestCase):
    """内嵌日文字幕的选轨（ADR-0024）：语言相符、文本编码、非 forced。"""

    def test_bitmap_forced_and_other_languages_are_not_usable(self) -> None:
        streams = [subtitle(2, "hdmv_pgs_subtitle"), subtitle(3, "dvd_subtitle"), subtitle(4, "dvb_subtitle"),
                   subtitle(5, "ass", forced=True), subtitle(6, "subrip", "chi"), subtitle(7, "subrip", None)]
        self.assertEqual(media.select_subtitle(streams, "jpn"), (None, []))
        self.assertEqual(media.select_subtitle([], "jpn"), (None, []))

    def test_multiple_matches_prefer_default_then_lowest_index_and_warn(self) -> None:
        chosen, warnings = media.select_subtitle([subtitle(5), subtitle(3, "ass"), subtitle(4, default=True)], "jpn")
        self.assertEqual(chosen["index"], 4)
        self.assertEqual(warnings, ["3 text subtitle streams tagged 'jpn' (indices 3, 4, 5); using index 4"])
        chosen, _ = media.select_subtitle([subtitle(5), subtitle(3, "ass")], "jpn")
        self.assertEqual(chosen["index"], 3)


class DurationCheckTests(unittest.TestCase):
    def test_video_input_far_longer_than_reference_fails(self) -> None:
        # 时间戳断裂被 aresample=async 补出数小时静音（batch-run-fixes 04）：视频输入超过 1.5 倍判失败
        (warning,) = media.check_duration(150.0, 100.0, has_video=True)
        self.assertIn("50.000 s longer than the input duration", warning)
        with self.assertRaisesRegex(media.MediaError, "longer than the input duration.*timestamps as broken"):
            media.check_duration(150.1, 100.0, has_video=True)
        (warning,) = media.check_duration(400.0, 100.0, has_video=False)  # 音频输入只告警
        self.assertIn("300.000 s longer than the input duration", warning)


if __name__ == "__main__":
    unittest.main()
