"""v14 研究包的离线单元测试：只用合成数据，不加载模型、不读 `.local/`、不碰 GPU。"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from experiments.asr_robustness_v14 import common, gaps, inputs, signals, workers
from kototoki import plan
from kototoki.workers import protocol


def sig(cr=1.0, alp=-0.2, cap=False):
    return {"compression_ratio": cr, "avg_logprob": alp, "cap_reached": cap}


class SignalPrimitives(unittest.TestCase):
    def test_compression_ratio(self):
        self.assertEqual(signals.compression_ratio(""), 0.0)
        varied = signals.compression_ratio("あいうえおかきくけこさしすせそ")
        repeated = signals.compression_ratio("あいうえお" * 20)
        self.assertGreater(repeated, varied)

    def test_cap_reached(self):
        self.assertFalse(signals.cap_reached(None))
        self.assertFalse(signals.cap_reached({"tokens": [1] * 10, "prompt": [1] * 4}))
        self.assertTrue(signals.cap_reached({"tokens": [1] * 443, "prompt": [1] * 4}))
        self.assertTrue(signals.cap_reached({"tokens": [1] * 447, "prompt": None}))
        self.assertFalse(signals.cap_reached({"tokens": [1] * 446}))

    def test_flagged_rules(self):
        doc = signals.RULES["doc-default"]  # cr>2.4 或触顶 或 (alp<-1 且 cr>2.4)
        self.assertTrue(signals.flagged(sig(cap=True), doc))
        self.assertTrue(signals.flagged(sig(cr=2.5), doc))
        self.assertFalse(signals.flagged(sig(cr=2.0, alp=-1.5), doc))  # alp 条件须同时压缩比高
        self.assertFalse(signals.flagged(sig(), doc))
        orr = signals.RULES["whisper-or"]
        self.assertTrue(signals.flagged(sig(cr=1.0, alp=-1.5), orr))
        self.assertFalse(signals.flagged(sig(cr=1.0, alp=-0.9), orr))
        self.assertTrue(signals.flagged(sig(cr=2.1), signals.RULES["cr2.0-alp1.0"]))
        self.assertTrue(signals.flagged(sig(alp=-0.85), signals.RULES["cr1.8-alp0.8"]))
        self.assertTrue(signals.flagged(sig(alp=-0.6), signals.RULES["alp0.5"]))
        self.assertFalse(signals.flagged(sig(alp=-0.6), signals.RULES["alp0.7"]))
        self.assertFalse(signals.flagged(sig(alp=None), signals.RULES["alp0.5"]))  # 无 alp 不标
        self.assertTrue(signals.flagged(sig(cap=True), signals.RULES["alp0.5"]))


class WindowSignals(unittest.TestCase):
    def setUp(self):
        texts = ["あいうえお", "かきくけこかきくけこ", "ほへとほへとほ", "あいうえか"]
        times = [(0.0, 2.0), (3.0, 5.0), (10.0, 12.0), (20.0, 22.0)]
        self.asr = {
            "original_segments": [{"text": t, "start": s, "end": e, "avg_logprob": -0.1 * (i + 1)}
                                  for i, (t, (s, e)) in enumerate(zip(texts, times))],
            "asr_traces": [{"tokens": [1] * 5, "prompt": [1] * 4}, None,
                           {"tokens": [1] * 447, "prompt": []}, {"tokens": [1] * 5, "prompt": []}],
        }
        self.reference = [
            {"index": 1, "start": 0.0, "end": 2.0, "text": "あいうえお"},   # 窗口 0：完全一致
            {"index": 2, "start": 3.0, "end": 5.0, "text": "さしすせそ"},   # 窗口 1：多出一倍
            {"index": 3, "start": 20.0, "end": 22.0, "text": "あいうえお"},  # 窗口 3：错 1 字
        ]
        self.rows = signals.window_signals(self.asr)
        signals.attach_reference(self.rows, self.asr, self.reference)

    def test_basic_fields(self):
        self.assertEqual(len(self.rows), 4)
        self.assertFalse(self.rows[0]["cap_reached"])
        self.assertTrue(self.rows[2]["cap_reached"])
        self.assertTrue(self.rows[1]["failed"])
        self.assertEqual(self.rows[0]["chars"], 5)
        self.assertEqual(self.rows[0]["duration_s"], 2.0)

    def test_buckets_and_cer(self):
        self.assertEqual(self.rows[0]["bucket"], "exact")
        self.assertEqual(self.rows[0]["unit_cer"], 0.0)
        self.assertEqual(self.rows[1]["bucket"], "heavy")
        self.assertEqual(self.rows[1]["unit_cer"], 2.0)
        self.assertEqual(self.rows[3]["bucket"], "light")
        self.assertEqual(self.rows[3]["unit_cer"], 0.2)

    def test_inserted_without_reference_overlap(self):
        row = self.rows[2]
        self.assertEqual(row["bucket"], "inserted")
        self.assertIsNone(row["unit_cer"])
        self.assertEqual(row["unit_ref_cues"], 0)
        self.assertEqual(row["blank_delta_edits"], -row["chars"])

    def test_blank_delta_sign(self):
        self.assertGreater(self.rows[0]["blank_delta_edits"], 0)   # 置空正确窗口更差
        self.assertLess(self.rows[1]["blank_delta_edits"], 0)      # 置空多出来的窗口更好
        self.assertEqual(self.rows[0]["blank_delta_edits"], 5)

    def test_rule_table_counts(self):
        table = signals.rule_table(self.rows)
        self.assertEqual(table["doc-default"]["flagged_windows"], 1)   # 只有触顶的窗口 2
        self.assertEqual(table["doc-default"]["flagged_indices"], [2])
        self.assertEqual(table["doc-default"]["blank_delta_edits_sum"], -self.rows[2]["chars"])


def make_align(text, status=None, mids=None):
    """每字符一个 unit；`mids[i]` 为该字符中点，None 或 status 非 ok 则无时间。"""
    units = []
    for i, _ in enumerate(text):
        mid = None if mids is None else mids[i]
        unit = {"char_start": i, "char_end": i + 1, "status": (status or {}).get(i, "ok")}
        if mid is not None and unit["status"] == "ok":
            unit.update(start=mid - 0.05, end=mid + 0.05)
        units.append(unit)
    return {"text": text, "units": units}


class Gaps(unittest.TestCase):
    def test_timed_chars(self):
        align = make_align("あいう", status={1: "text_only"}, mids=[0.5, 1.0, 1.5])
        times = gaps.timed_chars(align)
        self.assertAlmostEqual(times[0], 0.5)
        self.assertIsNone(times[1])
        self.assertAlmostEqual(times[2], 1.5)

    def test_segment_table(self):
        # 窗口 0：「あい、う」；子段 (0,1)、(2,3)；あ、い在第一段，标点不算，う中点 1.5 落在间隙
        # 窗口 1：「えお」全部 text_only，子段 (5,7)
        text0, text1 = "あい、う", "えお"
        mids = [0.3, 0.6, 0.6, 1.5, None, None]
        align = make_align(text0 + text1, status={4: "text_only", 5: "text_only"}, mids=mids)
        asr = {"original_segments": [{"text": text0}, {"text": text1}]}
        vad = {"chunks": [{"start": 0.0, "end": 3.0, "segments": [[0.0, 1.0], [2.0, 3.0]]},
                          {"start": 5.0, "end": 7.0, "segments": [[5.0, 7.0]]}]}
        rows = gaps.segment_table(vad, asr, align)
        self.assertEqual(len(rows), 3)
        first, second, third = rows
        self.assertEqual(first["chars"], 2)            # 标点不计
        self.assertFalse(first["empty"])
        self.assertEqual(second["chars"], 0)
        self.assertTrue(second["empty"])               # >=0.5 s 且无字
        self.assertEqual(first["window_gap_chars"], 1)
        self.assertEqual(first["window_lexical_chars"], 3)
        self.assertTrue(third["window_untimed"])
        self.assertFalse(third["empty"])               # 整窗无时间不判空
        self.assertEqual(third["window_untimed_chars"], 2)

    def test_short_segment_not_empty(self):
        align = make_align("あ", mids=[0.5])
        asr = {"original_segments": [{"text": "あ"}]}
        vad = {"chunks": [{"start": 0, "end": 2, "segments": [[0.0, 1.0], [1.2, 1.5]]}]}
        rows = gaps.segment_table(vad, asr, align)
        self.assertFalse(rows[1]["empty"])  # 0.3 s < 0.5 s

    def test_text_mismatch_raises(self):
        with self.assertRaises(ValueError):
            gaps.segment_table({"chunks": []}, {"original_segments": [{"text": "あ"}]}, make_align("い", mids=[0]))

    def test_reference_coverage(self):
        reference = [{"start": 0.0, "end": 2.0, "text": "あいうえおかきくけこ"}]
        empty = [{"start": 1.0, "end": 3.0}]
        cov = gaps.reference_coverage(empty, reference)
        self.assertEqual(cov["proportional"], 5.0)
        self.assertEqual(cov["whole_cue"], 10)
        self.assertEqual(cov["cues"], 1)
        self.assertEqual(cov["segments_with_reference"], 1)
        none = gaps.reference_coverage([{"start": 5.0, "end": 6.0}], reference)
        self.assertEqual((none["proportional"], none["whole_cue"]), (0.0, 0))

    def test_reference_char_times(self):
        doc = {"spans": [{"text": "あいうえ、お", "start": 10.0, "end": 20.0},
                         {"text": "かき", "start": 30.0, "end": 32.0}]}
        text, times = gaps.reference_char_times(doc)
        self.assertEqual(text, "あいうえおかき")
        self.assertEqual(len(times), 7)
        for got, want in zip(times[:5], [11.0, 13.0, 15.0, 17.0, 19.0]):
            self.assertAlmostEqual(got, want)
        self.assertAlmostEqual(times[5], 30.5)
        self.assertAlmostEqual(times[6], 31.5)

    def test_classify_deletions(self):
        spans = [("あいうえお", 0.0, 5.0), ("かきくけこ", 10.0, 15.0), ("さしすせそ", 20.0, 25.0),
                 ("たちつてと", 40.0, 45.0)]
        doc = {"spans": [{"text": t, "start": s, "end": e} for t, s, e in spans]}
        hyp = "".join(t for t, _, _ in spans)
        for char in "うおかしち":  # 时间点：2.5、4.5、10.5、21.5、41.5
            hyp = hyp.replace(char, "")
        vad = {"chunks": [{"start": 0.0, "end": 5.0}, {"start": 10.0, "end": 15.0}, {"start": 20.0, "end": 25.0}]}
        rows = [
            {"window": 0, "start": 0.0, "end": 2.0, "empty": False, "window_untimed": False},
            {"window": 0, "start": 3.0, "end": 5.0, "empty": True, "window_untimed": False},
            {"window": 1, "start": 10.0, "end": 15.0, "empty": False, "window_untimed": False},
            {"window": 2, "start": 20.0, "end": 25.0, "empty": False, "window_untimed": True},
        ]
        result = gaps.classify_deletions(doc, {"text": hyp}, vad, rows)
        self.assertEqual(result["deletions"], 5)
        self.assertEqual(result["official_D"], 5)
        self.assertTrue(result["matches_official"])
        self.assertEqual(result["classes"], {"outside_window": 1, "window_gap": 1, "empty_segment": 1,
                                             "nonempty_segment": 1, "untimed_window": 1})


class InputsAndWorkers(unittest.TestCase):
    def test_cue_rules_are_product_defaults(self):
        from kototoki.config import DEFAULTS
        rules = inputs.cue_rules()
        self.assertIn("max_chars", rules)
        self.assertEqual(rules, dict(DEFAULTS["cues"]))
        original = rules["max_chars"]
        rules["max_chars"] = -1  # 返回的是副本
        self.assertEqual(inputs.cue_rules()["max_chars"], original)

    def test_write_jobs_per_stage(self):
        config = {"models": {}, "model_cache": "cache.json"}
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            work = tmp / "abc123"
            for stage, names, engine in (("vad", {"wav"}, None), ("asr", {"wav", "vad"}, "w0"),
                                         ("align", {"wav", "asr"}, None)):
                path = tmp / f"jobs-{stage}.json"
                workers.write_jobs(stage, [work], path, config=config)
                value = json.loads(path.read_text(encoding="utf-8"))
                jobs = protocol.parse_jobs(value)
                self.assertEqual(jobs.stage, stage)
                self.assertEqual(jobs.recipe_hash, plan.recipe_hash(stage, engine=engine))
                self.assertEqual(set(jobs.files[0].inputs), names)
                self.assertEqual(jobs.files[0].id, "abc123")
                self.assertEqual(jobs.config["engine"], "w0")
            self.assertEqual(config, {"models": {}, "model_cache": "cache.json"})  # 传入的配置不被改动


class Identity(unittest.TestCase):
    def test_research_identity(self):
        upstream = {"audio-16k.wav": "a" * 64}
        models = {"whisper": "b" * 64}
        identity = common.research_identity("v14-test", upstream, models)
        self.assertEqual(identity["recipe_hash"], hashlib.sha256(b"v14-test").hexdigest())
        self.assertEqual(identity["upstream"], upstream)
        self.assertEqual(identity["models"], models)
        self.assertNotEqual(identity["recipe_hash"], plan.recipe_hash("asr", engine="w0"))


if __name__ == "__main__":
    unittest.main()
