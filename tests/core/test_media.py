"""media 的纯函数部分：语言归一化、音轨选择、时长来源、容器映射、下混选择、命令行构造、补偿解析。

用 ffmpeg 合成媒体的测试属于 full 层，在 `tests/full/test_media_ffmpeg.py`。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

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

    def test_commentary_is_excluded(self) -> None:
        probe = self.select(audio(1, "jpn", default=True, comment=True), audio(2, "jp"))
        self.assertEqual(probe.audio.index, 2)

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

    def test_configured_language_is_normalized_too(self) -> None:
        self.assertEqual(self.select(audio(1, "eng"), audio(2, "jpn"), language="ja").audio.index, 2)
        self.assertEqual(self.select(audio(1, "jpn"), audio(2, "eng"), language="ENG").audio.index, 2)

    def test_no_audio_fails(self) -> None:
        with self.assertRaisesRegex(media.MediaError, "No audio stream in the input"):
            self.select()
        with self.assertRaisesRegex(media.MediaError, "No audio stream in the input"):
            media.parse_probe({"streams": [], "format": {}}, "jpn")

    def test_records_absolute_index_codec_layout_start_time_and_subtitles(self) -> None:
        probe = media.parse_probe({"streams": [
            VIDEO, stream(1, "subtitle", codec_name="ass", tags={"language": "chi"}, disposition={"forced": 1}),
            audio(2, "jpn", start_time="0.021", duration="99.9")],
            "format": {"duration": "100.5", "start_time": "1.400000"}}, "jpn")
        self.assertEqual((probe.audio.index, probe.audio.codec_name, probe.audio.channel_layout), (2, "aac", "stereo"))
        self.assertEqual((probe.audio.start_time, probe.audio.duration, probe.audio.sample_rate), (0.021, 99.9, 48000))
        self.assertEqual(probe.container_start_time, 1.4)
        self.assertEqual(probe.subtitles, ({"index": 1, "codec_name": "ass", "language": "chi", "default": False,
                                            "forced": True},))
        payload = probe.payload()
        self.assertEqual(payload["selected_audio"]["index"], 2)
        self.assertIs(payload["ffprobe"], probe.ffprobe)


class VideoDurationTests(unittest.TestCase):
    def duration(self, video: dict[str, object], fmt: dict[str, object] | None = None) -> tuple[float, str]:
        probe = media.parse_probe({"streams": [video, audio(1, "jpn")], "format": fmt or {}}, "jpn")
        return probe.duration_s, probe.duration_source

    def test_stream_duration_first(self) -> None:
        self.assertEqual(self.duration(VIDEO, {"duration": "101"}), (100.0, "stream.duration"))

    def test_matroska_duration_tags(self) -> None:
        for key in ("DURATION", "DURATION-eng"):
            with self.subTest(key=key):
                video = stream(0, "video", tags={key: "01:57:08.021000000"})
                self.assertEqual(self.duration(video, {"duration": "7028.043"}), (7028.021, "stream.tags.DURATION"))

    def test_exact_duration_tag_beats_language_statistics_tag(self) -> None:
        # `-c copy` 剪片：原片全长的 DURATION-eng 排在前，真实片段时长在 DURATION
        video = stream(0, "video", tags={"DURATION-eng": "01:57:08.021000000", "DURATION": "00:00:23.000000000"})
        self.assertEqual(self.duration(video, {"duration": "23.5"}), (23.0, "stream.tags.DURATION"))

    def test_language_statistics_tag_is_used_alone(self) -> None:
        video = stream(0, "video", tags={"DURATION-jpn": "00:00:23.500000000"})
        self.assertEqual(self.duration(video, {"duration": "23.5"}), (23.5, "stream.tags.DURATION"))

    def test_tag_contradicting_container_takes_smaller_and_warns(self) -> None:
        video = stream(0, "video", tags={"DURATION": "02:02:05.000000000"})  # 7325 s
        probe = media.parse_probe({"streams": [video, audio(1, "jpn")], "format": {"duration": "303"}}, "jpn")
        self.assertEqual((probe.duration_s, probe.duration_source), (303.0, "format.duration"))
        self.assertEqual(len(probe.warnings), 1)
        self.assertIn("stream.tags.DURATION", probe.warnings[0])

    def test_falls_back_to_container_duration_with_warning(self) -> None:
        probe = media.parse_probe({"streams": [stream(0, "video"), audio(1, "jpn")], "format": {"duration": "12.5"}},
                                  "jpn")
        self.assertEqual((probe.duration_s, probe.duration_source), (12.5, "format.duration"))
        self.assertIn("container duration", probe.warnings[-1])
        with self.assertRaisesRegex(media.MediaError, "duration is unknown"):
            self.duration(stream(0, "video"))

    def test_cover_art_is_not_the_video_stream(self) -> None:
        cover = stream(0, "video", codec_name="mjpeg", duration="0.04", disposition={"attached_pic": 1})
        probe = media.parse_probe({"streams": [cover, audio(1, "jpn"), stream(2, "video", duration="50")],
                                   "format": {}}, "jpn")
        self.assertEqual(probe.duration_s, 50.0)
        self.assertTrue(probe.has_video)


class AudioOnlyInputTests(unittest.TestCase):
    """没有视频流（封面图不算）即音频输入：时长参照取所选音轨（ADR-0020）。"""

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

    def test_mp3_with_cover_art_counts_as_audio(self) -> None:
        cover = stream(1, "video", codec_name="mjpeg", duration="0.04", disposition={"attached_pic": 1})
        probe = media.parse_probe({"streams": [audio(0, "jpn", duration="30.0"), cover],
                                   "format": {"duration": "30.0"}}, "jpn")
        self.assertFalse(probe.has_video)
        self.assertEqual(probe.duration_s, 30.0)

    def test_falls_back_to_container_duration_with_audio_warning(self) -> None:
        probe = media.parse_probe({"streams": [audio(0, "jpn")], "format": {"duration": "12.5"}}, "jpn")
        self.assertEqual((probe.duration_s, probe.duration_source), (12.5, "format.duration"))
        self.assertIn("Audio stream has no duration", probe.warnings[-1])
        with self.assertRaisesRegex(media.MediaError, "Audio stream duration is unknown"):
            media.parse_probe({"streams": [audio(0, "jpn")], "format": {}}, "jpn")

    def test_stream_contradicting_container_takes_smaller_and_warns_audio(self) -> None:
        probe = media.parse_probe({"streams": [audio(0, "jpn", duration="500.0")], "format": {"duration": "60"}}, "jpn")
        self.assertEqual((probe.duration_s, probe.duration_source), (60.0, "format.duration"))
        self.assertIn("Audio duration from stream.duration", probe.warnings[0])


class ExtractTests(unittest.TestCase):
    """`extract()` 的流复制分支；ffmpeg 调用用桩替换。"""

    def run_extract(self, *, has_video: bool) -> tuple[mock.Mock, mock.Mock]:
        probe = SimpleNamespace(audio=track(), has_video=has_video)
        config = SimpleNamespace(paths=SimpleNamespace(ffmpeg=Path("ffmpeg.exe")))
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(media, "extract_original", return_value=(Path("audio.m4a"), "$ copy\n")) as copy, \
                mock.patch.object(media, "derive_pcm16k", return_value="extract") as derive:
            self.assertEqual(media.extract(Path("in.x"), Path(tmp) / "w", probe, config), "extract")
        return copy, derive

    def test_video_input_stream_copies_then_derives(self) -> None:
        copy, derive = self.run_extract(has_video=True)
        copy.assert_called_once()
        self.assertEqual(derive.call_args.kwargs["audio_copy"], Path("audio.m4a"))
        self.assertEqual(derive.call_args.kwargs["log_head"], "$ copy\n")

    def test_audio_input_skips_stream_copy(self) -> None:
        copy, derive = self.run_extract(has_video=False)
        copy.assert_not_called()
        self.assertIsNone(derive.call_args.kwargs["audio_copy"])

    def test_payload_of_audio_input_has_null_audio_copy(self) -> None:
        result = media.Extract(audio_copy=None, wav=Path("audio-16k.wav"), log=Path("extract.log"), sample_rate=16000,
                               samples=16000, pcm_sha256="0" * 64, decoded_duration_s=1.0, duration_s=1.0,
                               offset_s=0.0, pan="p", compensation={}, warnings=())
        payload = result.payload()
        self.assertIsNone(payload["audio_copy"])
        self.assertEqual(payload["duration_s"], 1.0)


class ContainerTests(unittest.TestCase):
    def test_mapping_follows_spec_table(self) -> None:
        expected = {"flac": ".flac", "aac": ".m4a", "alac": ".m4a", "ac3": ".ac3", "eac3": ".eac3", "dts": ".dts",
                    "opus": ".opus", "vorbis": ".ogg", "mp3": ".mp3", "pcm_s16le": ".wav", "pcm_s24le": ".wav",
                    "pcm_s32le": ".wav", "pcm_f32le": ".wav"}
        for codec, suffix in expected.items():
            self.assertEqual(media.container_suffix(codec), suffix)
        for codec in ("pcm_s16be", "pcm_s24be", "pcm_bluray", "pcm_dvd", "aac_latm", "truehd", "unknown"):
            self.assertEqual(media.container_suffix(codec), ".mka")


class PanSelectionTests(unittest.TestCase):
    def test_layout_and_channel_count_fallback(self) -> None:
        self.assertEqual(media.pan_filter(track(channels=1, channel_layout="mono")), recipes.PAN["mono"])
        self.assertEqual(media.pan_filter(track()), recipes.PAN["stereo"])
        self.assertEqual(media.pan_filter(track(channels=6, channel_layout="5.1(side)")), recipes.PAN["5.1(side)"])
        self.assertEqual(media.pan_filter(track(channels=6, channel_layout="")), recipes.PAN["5.1"])
        self.assertEqual(media.pan_filter(track(channels=8, channel_layout="8 channels")), recipes.PAN["7.1"])

    def test_unsupported_layouts_fail_before_ffmpeg(self) -> None:
        with self.assertRaisesRegex(media.MediaError, "Unsupported channel layout"):
            media.pan_filter(track(channels=5, channel_layout="5.0"))
        with self.assertRaisesRegex(media.MediaError, "Unsupported channel count"):
            media.pan_filter(track(channels=3, channel_layout=""))


def subtitle(index: int, codec: str = "subrip", language: str | None = "jpn", *, default: bool = False,
             forced: bool = False) -> dict[str, object]:
    return {"index": index, "codec_name": codec, "language": language, "default": default, "forced": forced}


class SubtitleSelectionTests(unittest.TestCase):
    """内嵌日文字幕的选轨（ADR-0024）：语言相符、文本编码、非 forced。"""

    def test_text_codecs_in_the_language_are_usable(self) -> None:
        for codec in ("subrip", "ass", "ssa", "mov_text", "webvtt"):
            chosen, warnings = media.select_subtitle([subtitle(3, codec, "ja")], "jpn")
            self.assertEqual((chosen, warnings), (subtitle(3, codec, "ja"), []))

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

    def test_configured_language_decides(self) -> None:
        streams = [subtitle(2, language="jpn"), subtitle(3, language="ENG")]
        self.assertEqual(media.select_subtitle(streams, "eng")[0]["index"], 3)

    def test_parse_probe_output_feeds_the_selection(self) -> None:
        probe = media.parse_probe({"streams": [
            VIDEO, audio(1, "jpn"),
            stream(2, "subtitle", codec_name="hdmv_pgs_subtitle", tags={"language": "jpn"}, disposition={"default": 1}),
            stream(3, "subtitle", codec_name="subrip", tags={"language": "jpn"}, disposition={})],
            "format": {"duration": "100.5"}}, "jpn")
        self.assertEqual(media.select_subtitle(probe.subtitles, "jpn")[0]["index"], 3)

    def test_forced_in_title_only_is_forced(self) -> None:
        # 真实片源（2026-11-12 验收）：两条 jpn 轨 disposition 都为 0，forced 只写在标题里
        probe = media.parse_probe({"streams": [
            VIDEO, audio(1, "jpn"),
            stream(31, "subtitle", codec_name="subrip", tags={"language": "jpn", "title": "ja--forced--"},
                   disposition={"default": 0, "forced": 0}),
            stream(32, "subtitle", codec_name="subrip", tags={"language": "jpn", "title": "Japanese"},
                   disposition={"default": 0, "forced": 0}),
            stream(33, "subtitle", codec_name="subrip", tags={"language": "jpn", "title": "Forced Narrative"})],
            "format": {"duration": "100.5"}}, "jpn")
        self.assertEqual([s["forced"] for s in probe.subtitles], [True, False, True])
        self.assertEqual(media.select_subtitle(probe.subtitles, "jpn"), (probe.subtitles[1] | {}, []))


class CommandTests(unittest.TestCase):
    ffmpeg = Path("D:/tools dir/ffmpeg.exe")
    video = Path("D:/影片 dir/第1話.mkv")

    def test_subtitle_command_converts_one_stream_to_srt_on_stdout(self) -> None:
        command = media.subtitle_command(self.ffmpeg, self.video, 4)
        self.assertEqual(command[0], str(self.ffmpeg))
        self.assertIn("-nostdin", command)
        self.assertEqual(command[command.index("-i") + 1], str(self.video))
        self.assertEqual(command[command.index("-map") + 1], "0:4")
        self.assertEqual(command[-5:], ["-c:s", "srt", "-f", "srt", "pipe:1"])

    def test_extract_subtitle_returns_stdout_and_raises_on_failure(self) -> None:
        with mock.patch("kototoki.media._run", return_value=SimpleNamespace(returncode=0, stdout="SRT", stderr="")):
            self.assertEqual(media.extract_subtitle(self.video, 4, self.ffmpeg), "SRT")
        with mock.patch("kototoki.media._run", return_value=SimpleNamespace(returncode=1, stdout="", stderr="boom")), \
                self.assertRaisesRegex(media.MediaError, "subtitle extraction failed"):
            media.extract_subtitle(self.video, 4, self.ffmpeg)

    def test_derive_command_decodes_from_container_by_absolute_index(self) -> None:
        command = media.derive_command(self.ffmpeg, self.video, track(index=3), Path("out/.a.partial.wav"))
        self.assertEqual(command[0], str(self.ffmpeg))
        self.assertIn("-nostdin", command)
        self.assertEqual(command[command.index("-loglevel") + 1], "verbose")
        self.assertEqual(command[command.index("-i") + 1], str(self.video))
        self.assertEqual(command[command.index("-map") + 1], "0:3")
        self.assertEqual(command[command.index("-af") + 1],
                         "aresample=async=1:first_pts=0,pan=mono|c0=0.5*c0+0.5*c1,"
                         "aresample=16000")
        self.assertEqual(command[command.index("-c:a") + 1], "pcm_s16le")
        self.assertNotIn("-ac", command)
        self.assertNotIn("-ar", command)
        self.assertEqual(command[-5:-1], ["-fflags", "+bitexact", "-flags:a", "+bitexact"])

    def test_copy_command_is_stream_copy_with_rf64_only_for_wav(self) -> None:
        command = media.copy_command(self.ffmpeg, self.video, track(index=2), Path("x/.audio.partial.m4a"))
        self.assertEqual(command[command.index("-c:a") + 1], "copy")
        self.assertEqual(command[command.index("-map") + 1], "0:2")
        self.assertIn("-nostdin", command)
        self.assertNotIn("-rf64", command)
        wav = media.copy_command(self.ffmpeg, self.video, track(codec_name="pcm_s24le"), Path("x/.audio.partial.wav"))
        self.assertEqual(wav[wav.index("-rf64") + 1], "auto")

    def test_probe_command_shows_all_streams_and_format(self) -> None:
        command = media.probe_command(Path("D:/tools dir/ffprobe.exe"), self.video)
        self.assertEqual(command[-1], str(self.video))
        self.assertIn("-show_streams", command)
        self.assertIn("-show_format", command)


class LogAndDurationTests(unittest.TestCase):
    def test_compensation_parses_swr_lines_and_input_samples(self) -> None:
        log = ("[SWR @ 0x1] adding 24000 audio samples of silence\n"
               "[SWR @ 0x1] adding 100 audio samples of silence\n"
               "[SWR @ 0x1] discarding 10 audio samples\n"
               "[in#0/matroska] Input stream #0:0 (video): 10 packets read\n"
               "[in#0/matroska]   Input stream #0:1 (audio): 188 packets read (67954 bytes); 188 frames decoded;"
               " 0 decode errors (144000 samples);\n")
        stats = media.parse_compensation(log, track(index=1), 3.5)
        self.assertEqual(stats, {"swr_reported_silence_samples": 24100, "swr_reported_discarded_samples": 10,
                                 "input_samples": 144000, "net_padding_s": 0.5})
        self.assertIsNone(media.parse_compensation("", track(), 1.0)["net_padding_s"])

    def test_duration_check_against_input_duration(self) -> None:
        for has_video in (True, False):
            self.assertEqual(media.check_duration(100.0, 100.9, has_video=has_video), [])
            self.assertEqual(media.check_duration(100.9, 100.0, has_video=has_video), [])
            self.assertIn("longer than the input duration",
                          media.check_duration(102.0, 100.0, has_video=has_video)[0])
        with self.assertRaisesRegex(media.MediaError, "shorter than the input duration.*truncated"):
            media.check_duration(98.9, 100.0, has_video=True)

    def test_audio_input_shorter_than_estimated_duration_only_warns(self) -> None:
        # VBR MP3 缺 Xing 头时 ffprobe 时长偏长：音频输入照常处理，只告警
        (warning,) = media.check_duration(95.0, 100.0, has_video=False)
        self.assertIn("5.000 s shorter than the input duration", warning)
        self.assertIn("audio input, continuing", warning)


if __name__ == "__main__":
    unittest.main()
