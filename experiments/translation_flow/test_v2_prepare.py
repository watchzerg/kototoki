"""Behavioral tests for score-independent source packing."""

import unittest

from .v2_prepare import pack_scene


def scene(count=23):
    return {"id": "scene-a", "context": [{"id": str(i), "text": f"台詞{i}"} for i in range(count)],
            "translate_ids": [str(i) for i in range(count)]}


class PackingTests(unittest.TestCase):
    def test_full_batches_and_tail_cover_once(self):
        rows, mapping = pack_scene(scene(), target_size=10)
        self.assertEqual([len(r["translate_ids"]) for r in rows], [10, 10, 3])
        self.assertEqual([i for r in rows for i in r["translate_ids"]], scene()["translate_ids"])
        self.assertEqual([m["full_batch"] for m in mapping], [True, True, False])

    def test_asymmetric_context_is_readonly(self):
        rows, _ = pack_scene(scene(), target_size=5, context_before=3, context_after=0)
        self.assertEqual([c["id"] for c in rows[1]["context"]], [str(i) for i in range(2, 10)])
        self.assertEqual(rows[1]["translate_ids"], [str(i) for i in range(5, 10)])

    def test_offset_preserves_warmup_and_full_scope(self):
        rows, mapping = pack_scene(scene(), target_size=5, offset=2)
        self.assertTrue(mapping[0]["warmup"])
        self.assertEqual(rows[1]["translate_ids"], [str(i) for i in range(2, 7)])
        self.assertEqual([i for r in rows for i in r["translate_ids"]], scene()["translate_ids"])

    def test_measured_tokens_keep_long_single_cue(self):
        counts = {str(i): 3 for i in range(23)}
        counts["2"] = 15
        rows, mapping = pack_scene(scene(), token_target=10, token_counts=counts)
        self.assertEqual(rows[0]["translate_ids"], ["0", "1"])
        self.assertEqual(rows[1]["translate_ids"], ["2"])
        self.assertTrue(mapping[1]["single_cue_over_token_target"])

    def test_reject_unmeasured_tokens_and_scoring_only_scene(self):
        with self.assertRaises(ValueError):
            pack_scene(scene(), token_target=10)
        source = scene()
        source["translate_ids"] = ["4", "5"]
        with self.assertRaises(ValueError):
            pack_scene(source)

    def test_common_context_diagnostic_keeps_same_information(self):
        a, _ = pack_scene(scene(), target_size=3, common_context=True)
        b, _ = pack_scene(scene(), target_size=10, common_context=True)
        self.assertTrue(all(r["context"] == a[0]["context"] for r in a + b))


if __name__ == "__main__":
    unittest.main()
