from __future__ import annotations

import copy
from decimal import Decimal
import re
import unittest

from kototoki import recipes
from kototoki.artifacts import object_hash

# ffmpeg 标准下混权重：前左右 1、中置 0.707、环绕 0.707、LFE 丢弃；按声道序号。
LAYOUT_WEIGHTS = {
    "5.1": (1, 1, 0.707, 0, 0.707, 0.707),
    "5.1(side)": (1, 1, 0.707, 0, 0.707, 0.707),
    "6.1": (1, 1, 0.707, 0, 0.707, 0.707, 0.707),
    "7.1": (1, 1, 0.707, 0, 0.707, 0.707, 0.707, 0.707),
}
_TERM = re.compile(r"([0-9.]+)\*c(\d+)")


def coefficients(expression: str) -> dict[int, Decimal]:
    prefix = "pan=mono|c0="
    assert expression.startswith(prefix), expression
    terms = expression[len(prefix):].split("+")
    parsed = [_TERM.fullmatch(term) for term in terms]
    assert all(parsed), expression
    return {int(match.group(2)): Decimal(match.group(1)) for match in parsed}


class PanTests(unittest.TestCase):
    def test_mono_passthrough_and_stereo_baseline(self) -> None:
        self.assertEqual(recipes.PAN["mono"], "anull")
        self.assertEqual(recipes.PAN["stereo"], "pan=mono|c0=0.5*c0+0.5*c1")

    def test_surround_coefficients_are_normalized_standard_weights_without_clipping(self) -> None:
        for layout, weights in LAYOUT_WEIGHTS.items():
            with self.subTest(layout=layout):
                found = coefficients(recipes.PAN[layout])
                total = sum(weights)
                expected = {channel: Decimal(weight / total).quantize(Decimal("0.000001"), rounding="ROUND_FLOOR")
                            for channel, weight in enumerate(weights) if weight}
                self.assertEqual(found, expected)
                self.assertNotIn(3, found)  # LFE 丢弃
                self.assertLessEqual(sum(found.values()), 1)  # 满幅同相输入不削波

    def test_channel_count_fallback_points_at_known_layouts(self) -> None:
        for channels, layout in recipes.LAYOUT_BY_CHANNELS.items():
            self.assertIn(layout, recipes.PAN)
            if layout in LAYOUT_WEIGHTS:
                self.assertEqual(len(LAYOUT_WEIGHTS[layout]), channels)

    def test_no_implicit_ac_matrix(self) -> None:
        self.assertNotIn("-ac", recipes.MEDIA["output_flags"])


class RecipeHashTests(unittest.TestCase):
    def test_hash_is_canonical_sha256_of_recipe(self) -> None:
        every = (recipes.MEDIA, recipes.VAD, recipes.W0, recipes.X0, recipes.CROSS, recipes.MMS, recipes.CUES)
        for recipe in every:
            digest = recipes.recipe_hash(recipe)
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
            self.assertEqual(digest, object_hash(recipe))
        self.assertEqual(len({recipes.recipe_hash(r) for r in every}), 7)

    def test_pinned_asr_recipe_hashes(self) -> None:
        # 钉住 hash：改动任一值即得到新 hash 并使已有产物失效。W0 自 ADR-0030 起带 guard 块（复读、语速与
        # 幻听句规则，换 id）；CROSS 嵌套 W0 而随之改变；X0 不变。
        self.assertEqual(recipes.W0["id"], "w0-faster-whisper-large-v3-guard-v3")
        self.assertEqual(recipes.W0["baseline"], "w0-pyannote-current-mms-v1")  # 解码与特征仍是 W0 基线
        self.assertEqual(recipes.recipe_hash(recipes.W0),
                         "6a47318c7732534270f64d14bb5da9830a79fdcae9f6d84e01a309532d62403b")
        self.assertEqual(recipes.recipe_hash(recipes.X0),
                         "5d1bec25fbb4acae6d82a866620faf75e2c55498aa304c1dadd7dc401bfd057b")
        self.assertEqual(recipes.recipe_hash(recipes.CROSS),
                         "bd5bc55527a539beab598e98f687f1bcbbcc6c23b3ba3a823fd3e9dfb46338e3")

    def test_pinned_media_vad_mms_cues_embedded_recipe_hashes(self) -> None:
        # 2026-11-11 架构整理（docs/plans/architecture-cleanup.md 票据 03）钉住：值取自 c639b22 的配方。
        # 除 MEDIA 外，这次整理不得改变任何一个；翻译 RECIPE_HASH 与建表 BUILD_RECIPE_HASH 各在
        # test_translate_recipes.py、test_names_recipes.py 钉住。
        # MEDIA 在票据 03 有意变一次：LAYOUT_BY_CHANNELS 与音轨选择规则（含 LANGUAGE_ALIASES）进 MEDIA，id 不变。
        # 改之前：58892e0a96afe3a876ba90959ce19ef649d5cd1052910c132bcd92055f971e1e
        # 2026-11-16 batch-run-fixes 02 出 v2（采样率标错纠正）；v1 为 0d19d8d8…
        self.assertEqual(recipes.MEDIA["id"], "media-pcm16k-v2")
        self.assertEqual(recipes.recipe_hash(recipes.MEDIA),
                         "e6a9fa76fc3e07b4b81b8353eea5fe6b9a209c9a39bbcfbca957381b21208a84")
        self.assertEqual(recipes.recipe_hash(recipes.VAD),
                         "d940145d29b8bc4ba834d53fa2ac818fbf28aab8b2b9ce18af555c350733a60c")
        self.assertEqual(recipes.recipe_hash(recipes.MMS),
                         "ebafa3aa8f83555e87f3d7506aef20a5135f3cae5c4664ba00d0da2c07975475")
        self.assertEqual(recipes.recipe_hash(recipes.CUES),
                         "cad2355caf19cf25d43065c800042f0f03ef42f7062f8bdbcb2f9bd06cf18243")
        self.assertEqual(recipes.recipe_hash(recipes.EMBEDDED),
                         "351da4b1adb3adf65641c17c2a7aac998fb6c49ee2e6aa9e307145d731e7e276")  # v2；v1 为 7c82c08b…

    def test_cross_nests_both_sub_recipes_and_judge_parameters(self) -> None:
        self.assertIs(recipes.CROSS["w0"], recipes.W0)
        self.assertIs(recipes.CROSS["x0"], recipes.X0)
        self.assertEqual(recipes.CROSS["judge"]["margin"], -1.0)
        self.assertEqual(recipes.CROSS["judge"]["length_weight"], 0.0)
        self.assertEqual(recipes.CROSS["judge"]["max_batch"], 16)
        base = recipes.recipe_hash(recipes.CROSS)
        for path in (("w0", "decode_options", "beam_size"), ("w0", "guard", "repeat", "min_copies"),
                     ("w0", "guard", "speech_rate", "max_chars_per_s"),
                     ("x0", "generate", "max_new_tokens"), ("judge", "margin")):
            changed = copy.deepcopy(recipes.CROSS)
            node = changed
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = 99
            with self.subTest(path=path):
                self.assertNotEqual(recipes.recipe_hash(changed), base)

    def test_pan_and_resample_constants_enter_the_media_hash(self) -> None:
        base = recipes.recipe_hash(recipes.MEDIA)
        changed_pan = copy.deepcopy(recipes.MEDIA)
        changed_pan["pan"]["stereo"] = "pan=mono|c0=c0"
        changed_rate = copy.deepcopy(recipes.MEDIA)
        changed_rate["resample_filter"] = "aresample=16000:resampler=soxr:precision=28"
        self.assertNotEqual(recipes.recipe_hash(changed_pan), base)
        self.assertNotEqual(recipes.recipe_hash(changed_rate), base)
        self.assertIs(recipes.MEDIA["pan"], recipes.PAN)

    def test_sample_rate_correction_rule_enters_the_media_hash(self) -> None:
        rule = recipes.MEDIA["sample_rate_correction"]
        self.assertEqual(rule["pairs"], [[48000, 44100], [44100, 48000]])
        self.assertEqual(rule["relative_tolerance"], 0.01)
        base = recipes.recipe_hash(recipes.MEDIA)
        changed = copy.deepcopy(recipes.MEDIA)
        changed["sample_rate_correction"]["relative_tolerance"] = 0.02
        self.assertNotEqual(recipes.recipe_hash(changed), base)

    def test_layout_fallback_and_audio_selection_enter_the_media_hash(self) -> None:
        self.assertIs(recipes.MEDIA["layout_by_channels"], recipes.LAYOUT_BY_CHANNELS)
        self.assertIs(recipes.MEDIA["audio_selection"]["language_aliases"], recipes.LANGUAGE_ALIASES)
        base = recipes.recipe_hash(recipes.MEDIA)
        for path, value in ((("layout_by_channels", 6), "5.1(side)"),
                            (("audio_selection", "language_aliases", "jp"), "x"),
                            (("audio_selection", "rule"), "first stream")):
            changed = copy.deepcopy(recipes.MEDIA)
            node = changed
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = value
            with self.subTest(path=path):
                self.assertNotEqual(recipes.recipe_hash(changed), base)

    def test_fixed_values_from_the_spec(self) -> None:
        self.assertEqual(recipes.VAD["device"], "cuda:0")
        self.assertEqual(recipes.VAD["model_revision"], "e66f3d3b9eb0873085418a7b813d3b369bf160bb")
        self.assertEqual(recipes.VAD["chunk_policy"]["max_chunk_samples"], 480000)
        self.assertEqual(recipes.W0["decode_options"]["beam_size"], 5)
        self.assertEqual(recipes.W0["compute_type"], "float16")
        self.assertEqual(recipes.X0["generate"], {"max_new_tokens": 4096, "do_sample": False})
        self.assertEqual(recipes.MMS["dtype"], "float32")
        self.assertEqual(recipes.MEDIA["offset_s"], 0)
        self.assertEqual(recipes.CUES["fallback_max_char_s"], 0.25)
        self.assertEqual(recipes.MEDIA["timeline_filter"], "aresample=async=1:first_pts=0")
        self.assertEqual(recipes.MEDIA["resample_filter"], "aresample=16000")

    def test_no_translation_recipe_here(self) -> None:
        names = {name.lower() for name in vars(recipes)}
        self.assertFalse({name for name in names if "translat" in name or "b10" in name})


if __name__ == "__main__":
    unittest.main()
