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


class RecipeHashTests(unittest.TestCase):
    def test_hash_is_canonical_sha256_of_recipe(self) -> None:
        every = (recipes.MEDIA, recipes.VAD, recipes.W0, recipes.X0, recipes.CROSS, recipes.MMS, recipes.CUES)
        for recipe in every:
            digest = recipes.recipe_hash(recipe)
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
            self.assertEqual(digest, object_hash(recipe))
        self.assertEqual(len({recipes.recipe_hash(r) for r in every}), 7)

    def test_pan_and_resample_constants_enter_the_media_hash(self) -> None:
        base = recipes.recipe_hash(recipes.MEDIA)
        changed_pan = copy.deepcopy(recipes.MEDIA)
        changed_pan["pan"]["stereo"] = "pan=mono|c0=c0"
        changed_rate = copy.deepcopy(recipes.MEDIA)
        changed_rate["resample_filter"] = "aresample=16000:resampler=soxr:precision=28"
        self.assertNotEqual(recipes.recipe_hash(changed_pan), base)
        self.assertNotEqual(recipes.recipe_hash(changed_rate), base)
        self.assertIs(recipes.MEDIA["pan"], recipes.PAN)


if __name__ == "__main__":
    unittest.main()
