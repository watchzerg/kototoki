from __future__ import annotations

import copy
from decimal import Decimal
import re
import unittest

from kototoki import cues, recipes
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
        for recipe in (recipes.MEDIA, recipes.VAD, recipes.W0, recipes.X0, recipes.MMS, recipes.CUES):
            digest = recipes.recipe_hash(recipe)
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
            self.assertEqual(digest, object_hash(recipe))
        hashes = {recipes.recipe_hash(r) for r in (recipes.MEDIA, recipes.VAD, recipes.W0, recipes.X0,
                                                   recipes.MMS, recipes.CUES)}
        self.assertEqual(len(hashes), 6)

    def test_pan_and_resample_constants_enter_the_media_hash(self) -> None:
        base = recipes.recipe_hash(recipes.MEDIA)
        changed_pan = copy.deepcopy(recipes.MEDIA)
        changed_pan["pan"]["stereo"] = "pan=mono|c0=c0"
        changed_rate = copy.deepcopy(recipes.MEDIA)
        changed_rate["resample_filter"] = "aresample=16000:resampler=soxr:precision=28"
        self.assertNotEqual(recipes.recipe_hash(changed_pan), base)
        self.assertNotEqual(recipes.recipe_hash(changed_rate), base)
        self.assertIs(recipes.MEDIA["pan"], recipes.PAN)

    def test_fixed_values_from_the_spec(self) -> None:
        self.assertEqual(recipes.VAD["device"], "cuda:0")
        self.assertEqual(recipes.VAD["model_revision"], "e66f3d3b9eb0873085418a7b813d3b369bf160bb")
        self.assertEqual(recipes.VAD["chunk_policy"]["max_chunk_samples"], 480000)
        self.assertEqual(recipes.W0["decode_options"]["beam_size"], 5)
        self.assertEqual(recipes.W0["compute_type"], "float16")
        self.assertEqual(recipes.X0["generate"], {"max_new_tokens": 4096, "do_sample": False})
        self.assertEqual(recipes.MMS["dtype"], "float32")
        self.assertEqual(recipes.MEDIA["offset_s"], 0)
        self.assertEqual(recipes.CUES["fallback_max_char_s"], cues.FALLBACK_MAX_CHAR_S)
        self.assertEqual(recipes.MEDIA["timeline_filter"], "aresample=async=1:first_pts=0")
        self.assertEqual(recipes.MEDIA["resample_filter"], "aresample=16000")

    def test_no_translation_recipe_here(self) -> None:
        names = {name.lower() for name in vars(recipes)}
        self.assertFalse({name for name in names if "translat" in name or "b10" in name})


if __name__ == "__main__":
    unittest.main()
