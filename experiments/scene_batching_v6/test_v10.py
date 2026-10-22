"""v10 offline checks: Qwen options keep old hashes, render as specified, and the A2 helpers."""

from __future__ import annotations

import unittest

from experiments.translation_v3 import qwen
from experiments.translation_v3 import recipes as R

from . import a2, asr10

WINDOW = {"id": "w", "source_language": "ja", "target_language": "zh-Hans",
          "context": [{"id": "a", "text": "ハルカが来た"}, {"id": "b", "text": "行こう"}], "translate_ids": ["b"]}
TABLE = {"W1": [{"source": "ハルカ", "translation": "遥"}, {"source": "ミナト", "translation": "凑"}]}


def arm(**options):
    return R.compose("arm", "qwen-wide", qwen_options=options)


class OptionsTest(unittest.TestCase):
    def test_old_hashes_unchanged(self):
        self.assertEqual(R.BUILTIN["qwen-wide"].recipe_hash,
                         "719237b92c45c4d0f19971ece6b0944157c23ad2e33bbfe0644db60aabfcaef7")
        self.assertTrue(R.BUILTIN["dp10-cut"].recipe_hash.startswith("ee72ce66"))
        self.assertNotIn("qwen_options", R.BUILTIN["qwen-wide"].spec()["recipe"])

    def test_options_change_hash_and_validate(self):
        v2 = arm(system="qwen-joint-v2")
        self.assertNotEqual(v2.recipe_hash, R.BUILTIN["qwen-wide"].recipe_hash)
        self.assertIn("options", v2.spec()["versions"]["model"])
        for bad in ({}, {"system": "nope"}, {"asr": "x"}, {"names": {"filter": "window"}}, {"brief": {"W1": " "}},
                    {"context": 8192}, {"other": 1}):
            with self.assertRaises(ValueError):
                arm(**bad)
        with self.assertRaises(ValueError):
            R.compose("hy", "dp10-cut", qwen_options={"system": "qwen-joint-v2"})

    def test_v2_keeps_v1_rules_and_user_message(self):
        v1 = qwen.messages(WINDOW)
        v2 = qwen.messages(WINDOW, arm(system="qwen-joint-v2"), "W1")
        self.assertIn(v1[0]["content"], v2[0]["content"])
        self.assertTrue(v2[0]["content"].startswith(qwen.QWEN_JOINT_V2_ROLE))
        self.assertEqual(v1[1], v2[1])
        self.assertEqual(qwen.messages(WINDOW, R.BUILTIN["qwen-wide"], "W1"), v1)

    def test_asr_names_brief(self):
        asr = qwen.messages(WINDOW, arm(asr="qwen-asr-aware-v1"), "W1")[0]["content"]
        self.assertTrue(asr.endswith(qwen.ASR_TEXTS["qwen-asr-aware-v1"]))
        window = arm(names={"filter": "window", "tables": TABLE})
        self.assertEqual(qwen.names_for_window(window, "W1", WINDOW), [TABLE["W1"][0]])
        self.assertIn("ハルカ → 遥", qwen.messages(WINDOW, window, "W1")[0]["content"])
        self.assertNotIn("ミナト", qwen.messages(WINDOW, window, "W1")[0]["content"])
        self.assertEqual(len(qwen.names_for_window(arm(names={"filter": "all", "tables": TABLE}), "W1", WINDOW)), 2)
        self.assertEqual(qwen.names_for_window(window, "W2", WINDOW), [])
        brief = arm(brief={"W1": "校园喜剧"})
        self.assertTrue(qwen.messages(WINDOW, brief, "W1")[0]["content"].endswith(qwen.BRIEF_HEADER + "校园喜剧"))
        with self.assertRaises(ValueError):
            qwen.messages(WINDOW, brief, "W2")

    def test_context_override(self):
        self.assertEqual(qwen.context_size(arm(context=24576)), 24576)
        self.assertEqual(qwen.context_size(R.BUILTIN["qwen-wide"]), qwen.WIDE_CONTEXT)


class A2Test(unittest.TestCase):
    def test_agreement_signs(self):
        sim = {"a": 0.1, "b": -0.2, "c": 0.0, "d": 0.3}
        judge = {"a": -1.0, "b": -1.0, "c": 5.0, "d": 0.0}
        self.assertEqual(a2.agreement(sim, judge), {"judge_nonzero": 3, "sim_nonzero": 2, "agree": 1, "rate": 0.5})

    def test_verdict(self):
        boot = lambda lo, hi: {"bootstrap": {"anime_series": {"ci90": [lo, hi]}, "animation_movie": {"ci90": [lo, hi]}}}
        self.assertEqual(a2.verdict({"pooled": {"chrf": boot(0.01, 0.02), "bge_m3": boot(-0.01, 0.01)}})["gate"], "pass")
        self.assertEqual(a2.verdict({"pooled": {"chrf": boot(-0.03, -0.01), "bge_m3": boot(-0.01, 0.01)}})["gate"],
                         "flag-judge-preference")


class AsrStageTest(unittest.TestCase):
    units = {"f": [{"bucket": b} for b in ["exact"] * 5 + ["light"] * 4 + ["heavy"] * 3 + ["missed"] * 2]}

    def test_sample_is_fixed_per_bucket(self):
        a = asr10.sample_units(self.units, {"exact": 2, "light": "all", "heavy": 1, "missed": 2})
        self.assertEqual(a, asr10.sample_units(self.units, {"exact": 2, "light": "all", "heavy": 1}))
        self.assertEqual([b for _, _, b in a], ["exact"] * 2 + ["light"] * 4 + ["heavy"])
        self.assertEqual(a[:2], asr10.sample_units(self.units, {"exact": 2})[:2])

    def test_bootstrap_and_names(self):
        rows = [{"px": 1, "py": 0}] * 10
        self.assertEqual(asr10._boot(rows), [-1.0, -1.0])
        self.assertIsNone(asr10._boot([]))
        errors = [{"category": "terminology", "note": ""}, {"category": "mistranslation", "note": "人名译错"},
                  {"category": "grammar", "note": "语序"}]
        self.assertEqual(asr10._names(errors), 2)


if __name__ == "__main__":
    unittest.main()
