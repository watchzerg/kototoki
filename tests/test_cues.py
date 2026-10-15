"""kototoki.cues 的离线测试：时间回填、断句三级切分、lead_out／min_duration、offset 与 SRT 一致性。"""

import unittest

from kototoki.cues import FALLBACK_MAX_CHAR_S, build_cues
from kototoki.srt import parse_srt

DEFAULT_RULES = {
    "max_chars": 24, "max_duration_s": 6.0, "min_duration_s": 0.8, "max_gap_s": 0.4,
    "sentence_endings": "。！？!?", "soft_breaks": "、，,", "lead_out_s": 0.3,
}


def rules(**overrides):
    merged = dict(DEFAULT_RULES)
    merged.update(overrides)
    return merged


# 关闭 lead_out 与 min_duration，使 cue 时间等于词汇字符的原始时间。
PLAIN = {"lead_out_s": 0.0, "min_duration_s": 0.0}


def timed(text, start, step=0.2):
    """每个字符都有时间、首尾相接的字符列表。"""
    return [(char, round(start + k * step, 6), round(start + (k + 1) * step, 6))
            for k, char in enumerate(text)]


def untimed(text):
    """每个字符都是 text_only 的字符列表。"""
    return [(char, None) for char in text]


def window(start, end, chars, segments=None):
    """窗口描述：WAV 本地边界、字符列表与 VAD 子段（缺省为整窗一段，传 [] 表示没有子段）。"""
    return {"start": start, "end": end, "chars": chars,
            "segments": [[start, end]] if segments is None else segments}


def make_align(windows, offset=0.0):
    """由紧凑描述构造 align 字典：只有 units 的时间加 offset，窗口与 VAD 子段保持本地秒。"""
    text, units, original_segments, chunks = "", [], [], []
    for win in windows:
        window_text = "".join(item[0] for item in win["chars"])
        for item in win["chars"]:
            i = len(units)
            ok = len(item) == 3 and item[1] is not None
            units.append({
                "char_start": i, "char_end": i + 1,
                "start": item[1] + offset if ok else None,
                "end": item[2] + offset if ok else None,
                "status": "ok" if ok else "text_only",
                "time_source": "api", "granularity": "character",
            })
        text += window_text
        original_segments.append({"text": window_text, "start": win["start"], "end": win["end"]})
        chunks.append({"start": win["start"], "end": win["end"], "segments": win["segments"]})
    return {"text": text, "offset_s": offset, "units": units,
            "original_segments": original_segments, "chunks": chunks}


def spans(payload):
    return [(cue["start_ms"], cue["end_ms"], cue["text"]) for cue in payload["cues"]]


def offset_scenario(offset):
    """窗 0 有首尾外推并触发钳制，窗 1 整窗 fallback。"""
    return make_align([
        window(0.9, 1.5, untimed("か") + timed("あい", 1.0) + untimed("き")),
        window(10.0, 12.0, untimed("うえ"), [[10.0, 11.0]]),
    ], offset)


class CueTestCase(unittest.TestCase):
    def assertWellFormed(self, payload, srt_text):
        """不变量：cue 无重叠、递增、不是纯符号，且 SRT 与 payload 一致。"""
        previous_end = 0
        for cue in payload["cues"]:
            self.assertTrue(any(char.isalnum() for char in cue["text"]), cue["text"])
            self.assertGreater(cue["end_ms"], cue["start_ms"])
            self.assertGreaterEqual(cue["start_ms"], previous_end)
            previous_end = cue["end_ms"]
        parsed = parse_srt(srt_text)
        self.assertEqual([(c.start_ms, c.end_ms, c.text) for c in parsed.cues], spans(payload))


class BackfillTests(CueTestCase):
    def test_interpolation_between_timed_chars(self):
        align = make_align([window(0, 10, [("あ", 1.0, 1.2)] + untimed("いうえ") + [("お", 1.8, 2.0)])])
        payload, srt_text = build_cues(align, rules(max_chars=1, **PLAIN))
        self.assertEqual(spans(payload), [
            (1000, 1200, "あ"), (1200, 1400, "い"), (1400, 1600, "う"),
            (1600, 1800, "え"), (1800, 2000, "お")])
        self.assertEqual(payload["backfilled_units"],
                         [{"unit_start": 1, "unit_end": 4, "time_source": "interpolated"}])
        self.assertEqual(payload["time_sources"], {"api": 2, "interpolated": 3})
        self.assertEqual(payload["fallback_windows"], [])
        self.assertEqual(payload["cues"][0]["time_sources"], {"api": 1})
        self.assertEqual(payload["cues"][0]["backfilled_units"], 0)
        self.assertEqual(payload["cues"][1]["time_sources"], {"interpolated": 1})
        self.assertEqual(payload["cues"][1]["backfilled_units"], 1)
        self.assertWellFormed(payload, srt_text)

    def test_edge_extrapolation_uses_average_char_duration(self):
        chars = untimed("かき") + timed("あい", 1.0) + untimed("くけ")
        payload, _ = build_cues(make_align([window(0, 10, chars)]), rules(max_chars=1, **PLAIN))
        self.assertEqual(spans(payload), [
            (600, 800, "か"), (800, 1000, "き"), (1000, 1200, "あ"),
            (1200, 1400, "い"), (1400, 1600, "く"), (1600, 1800, "け")])
        self.assertEqual(payload["backfilled_units"], [
            {"unit_start": 0, "unit_end": 2, "time_source": "interpolated"},
            {"unit_start": 4, "unit_end": 6, "time_source": "interpolated"}])

    def test_edge_extrapolation_is_clamped_to_window_bounds(self):
        chars = untimed("かき") + timed("あい", 1.0) + untimed("くけ")
        payload, _ = build_cues(make_align([window(0.7, 1.7, chars)]), rules(max_chars=1, **PLAIN))
        self.assertEqual(spans(payload), [
            (700, 800, "か"), (800, 1000, "き"), (1000, 1200, "あ"),
            (1200, 1400, "い"), (1400, 1600, "く"), (1600, 1700, "け")])

    def test_whole_window_fallback_distributes_over_vad_segments(self):
        win = window(10.0, 13.0, untimed("あいうえお"), [[10.0, 10.5], [12.0, 13.0]])
        payload, srt_text = build_cues(make_align([win]), rules(**PLAIN))
        # 5 字按 0.5:1.0 分配：份额 1.67／3.33，最大余数法得 2／3；每字 0.25 秒从子段起点排列。
        self.assertEqual(spans(payload), [(10000, 10500, "あい"), (12000, 12750, "うえお")])
        self.assertEqual(payload["fallback_windows"], [0])
        self.assertEqual(payload["time_sources"], {"fallback": 5})
        self.assertEqual(payload["backfilled_units"],
                         [{"unit_start": 0, "unit_end": 5, "time_source": "fallback"}])
        self.assertEqual(payload["cues"][0]["time_sources"], {"fallback": 2})
        self.assertEqual(payload["cues"][0]["backfilled_units"], 2)
        self.assertWellFormed(payload, srt_text)

    def test_fallback_char_duration_is_capped(self):
        win = window(0.0, 5.0, untimed("あい"), [[0.0, 5.0]])
        payload, _ = build_cues(make_align([win]), rules(**PLAIN))
        self.assertEqual(FALLBACK_MAX_CHAR_S, 0.25)
        self.assertEqual(spans(payload), [(0, 500, "あい")])

    def test_fallback_largest_remainder_tie_goes_to_earlier_segment(self):
        win = window(0.0, 3.0, untimed("あいうえお"), [[0.0, 1.0], [2.0, 3.0]])
        payload, _ = build_cues(make_align([win]), rules(max_chars=1, **PLAIN))
        # 份额 2.5／2.5，多出的 1 字给前一子段：3 字 + 2 字。
        self.assertEqual([(s, e) for s, e, _ in spans(payload)], [
            (0, 250), (250, 500), (500, 750), (2000, 2250), (2250, 2500)])

    def test_text_only_window_between_timed_windows(self):
        align = make_align([
            window(0.5, 2.0, timed("あい", 1.0)),
            window(3.0, 4.0, untimed("うえ"), []),
        ])
        payload, srt_text = build_cues(align, rules())
        # 无 VAD 子段时退回窗口边界；第二窗 3.0 起每字 0.25 秒。lead_out 0.3、min_duration 0.8 照常生效。
        self.assertEqual(spans(payload), [(1000, 1800, "あい"), (3000, 3800, "うえ")])
        self.assertEqual(payload["fallback_windows"], [1])
        self.assertEqual(payload["time_sources"], {"api": 2, "fallback": 2})
        self.assertWellFormed(payload, srt_text)


class SplittingTests(CueTestCase):
    def test_gap_across_vad_segments_breaks_cue(self):
        chars = timed("あい", 0.0) + timed("うえ", 1.4)
        far = make_align([window(0, 10, chars, [[0.0, 0.5], [1.3, 10.0]])])
        payload, _ = build_cues(far, rules(**PLAIN))
        self.assertEqual(spans(payload), [(0, 400, "あい"), (1400, 1800, "うえ")])
        near = make_align([window(0, 10, timed("あい", 0.0) + timed("うえ", 0.7), [[0.0, 0.5], [0.6, 10.0]])])
        payload, _ = build_cues(near, rules(**PLAIN))
        self.assertEqual(spans(payload), [(0, 1100, "あいうえ")])

    def test_gap_inside_one_vad_segment_does_not_break(self):
        """票据 12：CTC 发射点之间的词内假间隙（拖长音）不切。"""
        chars = timed("あい", 0.0) + timed("うえ", 1.4)
        same_span = make_align([window(0, 10, chars)])
        payload, _ = build_cues(same_span, rules(**PLAIN))
        self.assertEqual(spans(payload), [(0, 1800, "あいうえ")])
        # 子段首尾相接（中间没有非语音区）同样不切。
        touching = make_align([window(0, 10, chars, [[0.0, 0.4], [0.4, 10.0]])])
        payload, _ = build_cues(touching, rules(**PLAIN))
        self.assertEqual(spans(payload), [(0, 1800, "あいうえ")])

    def test_gap_across_windows_breaks_cue(self):
        align = make_align([window(0, 0.5, timed("あい", 0.0)), window(1.3, 10, timed("うえ", 1.4))])
        payload, _ = build_cues(align, rules(**PLAIN))
        self.assertEqual(spans(payload), [(0, 400, "あい"), (1400, 1800, "うえ")])

    def test_sentence_ending_breaks_cue_and_stays_attached(self):
        for mark in "。！?":
            with self.subTest(mark=mark):
                chars = timed("あい", 0.0) + timed(mark, 0.4, 0.1) + timed("うえ", 0.5)
                payload, _ = build_cues(make_align([window(0, 10, chars)]), rules(**PLAIN))
                self.assertEqual(spans(payload), [(0, 400, "あい" + mark), (500, 900, "うえ")])

    def test_long_sentence_is_cut_after_last_fitting_soft_break(self):
        align = make_align([window(0, 10, timed("あい、うえ、おかきく", 0.0))])
        payload, _ = build_cues(align, rules(max_chars=6, **PLAIN))
        self.assertEqual(spans(payload), [(0, 1000, "あい、うえ、"), (1200, 2000, "おかきく")])
        # max_chars=5 时第二个软断点前缀超限，只能在第一个软断点后切。
        payload, _ = build_cues(align, rules(max_chars=5, **PLAIN))
        self.assertEqual(spans(payload), [
            (0, 400, "あい、"), (600, 1000, "うえ、"), (1200, 2000, "おかきく")])

    def test_hard_cut_without_soft_break_is_balanced(self):
        text = "あいうえおかきくけこ"
        payload, _ = build_cues(make_align([window(0, 10, timed(text, 0.0))]),
                                rules(max_chars=4, **PLAIN))
        pieces = [cue["text"] for cue in payload["cues"]]
        self.assertEqual(pieces, ["あいうえ", "おかき", "くけこ"])
        self.assertTrue(all(len(piece) <= 4 for piece in pieces))
        self.assertEqual("".join(pieces), text)

    def test_max_duration_splits_cue(self):
        align = make_align([window(0, 10, timed("あいうえおか", 2.0, 0.5))])
        payload, _ = build_cues(align, rules(max_duration_s=1.5, **PLAIN))
        self.assertEqual(spans(payload), [(2000, 3500, "あいう"), (3500, 5000, "えおか")])


class TimingAdjustmentTests(CueTestCase):
    def test_lead_out_extends_end_but_not_past_next_start(self):
        align = make_align([window(0, 10, timed("あい", 1.0) + timed("うえ", 1.9), [[1.0, 1.4], [1.9, 10.0]])])
        for lead_out, expected in ((0.3, [(1000, 1700), (1900, 2600)]),
                                   (1.0, [(1000, 1900), (1900, 3300)])):
            with self.subTest(lead_out_s=lead_out):
                payload, srt_text = build_cues(align, rules(lead_out_s=lead_out, min_duration_s=0.0))
                self.assertEqual([(s, e) for s, e, _ in spans(payload)], expected)
                self.assertWellFormed(payload, srt_text)

    def test_min_duration_extends_forward_without_overlap(self):
        chars = [("あ", 1.0, 1.1), ("い", 1.6, 1.7), ("う", 5.0, 5.1)]
        segments = [[1.0, 1.1], [1.6, 1.7], [5.0, 5.1]]
        payload, srt_text = build_cues(make_align([window(0, 10, chars, segments)]),
                                       rules(lead_out_s=0.0, min_duration_s=0.8))
        self.assertEqual(spans(payload), [(1000, 1600, "あ"), (1600, 2400, "い"), (5000, 5800, "う")])
        self.assertWellFormed(payload, srt_text)


class EmptyAndSymbolTests(CueTestCase):
    def test_empty_input_yields_zero_cues(self):
        align = make_align([])
        payload, srt_text = build_cues(align, rules())
        self.assertEqual(payload["cues"], [])
        self.assertEqual(payload["time_sources"], {})
        self.assertEqual(payload["backfilled_units"], [])
        self.assertEqual(payload["fallback_windows"], [])
        self.assertEqual(payload["unrendered_chars"], 0)
        self.assertEqual(srt_text, "")

    def test_pure_punctuation_yields_zero_cues(self):
        cases = {
            "text_only": [window(0, 2, untimed("…。！"))],
            "timed": [window(0, 2, timed("…。！", 0.0, 0.1))],
            "with_space": [window(0, 2, untimed("… 。"))],
        }
        for name, windows in cases.items():
            with self.subTest(case=name):
                payload, srt_text = build_cues(make_align(windows), rules())
                text = make_align(windows)["text"]
                self.assertEqual(payload["cues"], [])
                self.assertEqual(srt_text, "")
                self.assertEqual(payload["unrendered_chars"], len(text))
        payload, _ = build_cues(make_align(cases["text_only"]), rules())
        self.assertEqual(payload["fallback_windows"], [0])

    def test_music_note_attaches_to_cue(self):
        chars = untimed("♪") + timed("ららら", 1.0) + untimed("♪")
        payload, srt_text = build_cues(make_align([window(0, 10, chars)]), rules(**PLAIN))
        self.assertEqual(spans(payload), [(1000, 1600, "♪ららら♪")])
        self.assertWellFormed(payload, srt_text)

    def test_punctuation_and_note_after_sentence_end(self):
        chars = [("ね", 1.0, 1.2), ("。", None), (" ", None), ("♪", None),
                 ("い", 1.4, 1.6), ("つ", 1.6, 1.8), ("も", 1.8, 2.0)]
        payload, srt_text = build_cues(make_align([window(0, 10, chars)]), rules(**PLAIN))
        # 空白处分开：「。」归前一条，「♪」归后一条。
        self.assertEqual(spans(payload), [(1000, 1200, "ね。"), (1400, 2000, "♪いつも")])
        self.assertEqual([(c["char_start"], c["char_end"]) for c in payload["cues"]], [(0, 2), (2, 7)])
        self.assertEqual(payload["cues"][1]["backfilled_units"], 2)
        self.assertWellFormed(payload, srt_text)

    def test_note_without_space_attaches_to_previous_cue_at_gap(self):
        chars = [("ね", 1.0, 1.2), ("♪", None), ("い", 2.0, 2.2), ("つ", 2.2, 2.4), ("も", 2.4, 2.6)]
        align = make_align([window(0, 10, chars, [[1.0, 1.3], [1.9, 10.0]])])
        payload, srt_text = build_cues(align, rules(**PLAIN))
        self.assertEqual(spans(payload), [(1000, 1200, "ね♪"), (2000, 2600, "いつも")])
        self.assertWellFormed(payload, srt_text)


class OffsetAndSrtTests(CueTestCase):
    def test_offset_is_applied_exactly_once(self):
        payload0, _ = build_cues(offset_scenario(0.0), rules())
        # 窗 0：か外推被窗口起点 0.9 钳制，き被窗口终点 1.5 钳制；窗 1 整窗 fallback 取子段起点。
        self.assertEqual(spans(payload0), [(900, 1800, "かあいき"), (10000, 10800, "うえ")])
        payload, _ = build_cues(offset_scenario(100.0), rules())
        self.assertEqual(spans(payload), [(100900, 101800, "かあいき"), (110000, 110800, "うえ")])
        self.assertEqual(payload["fallback_windows"], [1])
        self.assertEqual(payload["time_sources"], {"api": 2, "fallback": 2, "interpolated": 2})
        self.assertEqual(
            [(s - 100000, e - 100000) for s, e, _ in spans(payload)],
            [(s, e) for s, e, _ in spans(payload0)])

    def test_srt_matches_payload(self):
        for name, align in (("offset", offset_scenario(100.0)),
                            ("split", make_align([window(0, 10, timed("あい、うえ、おかきく。くけ", 0.0))]))):
            with self.subTest(case=name):
                payload, srt_text = build_cues(align, rules(max_chars=5))
                self.assertGreaterEqual(len(payload["cues"]), 2)
                self.assertEqual([cue["index"] for cue in payload["cues"]],
                                 list(range(1, len(payload["cues"]) + 1)))
                self.assertWellFormed(payload, srt_text)
                self.assertEqual(len(parse_srt(srt_text).cues), len(payload["cues"]))


class RuleValidationTests(unittest.TestCase):
    def test_missing_or_extra_rule_key_raises(self):
        align = make_align([window(0, 10, timed("あい", 1.0))])
        missing = dict(DEFAULT_RULES)
        del missing["lead_out_s"]
        extra = dict(DEFAULT_RULES, unknown=1)
        for name, bad in (("missing", missing), ("extra", extra)):
            with self.subTest(case=name):
                with self.assertRaises(ValueError):
                    build_cues(align, bad)


if __name__ == "__main__":
    unittest.main()
