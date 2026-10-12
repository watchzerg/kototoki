"""Offline frozen bridge output identity boundary tests."""

import copy
import unittest

from experiments.components.evaluate_word_envelope import validate_output_identity


class EnvelopeScorerTests(unittest.TestCase):
    def test_repaired_bounds_are_allowed_while_text_is_exact(self):
        saved = {"text": "unchanged", "original_segments": [{"start": 1, "end": 1.02}]}
        bridge = {"text": saved["text"], "original_segments": [{"start": .3, "end": 1.02}]}
        result = {**bridge, "native": {"reused_asr_file": "frozen-bridge.json"}}
        before = copy.deepcopy((saved, bridge, result))
        validate_output_identity(result, saved, bridge, {"bridge": {"path": "frozen-bridge.json"}})
        self.assertEqual(before, (saved, bridge, result))
        for field, value in (("text", "changed"), ("original_segments", saved["original_segments"])):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "altered"):
                validate_output_identity({**result, field: value}, saved, bridge, {"bridge": {"path": "frozen-bridge.json"}})


if __name__ == "__main__":
    unittest.main()
