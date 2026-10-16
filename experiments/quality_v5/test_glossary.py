import unittest

from experiments.quality_v5.glossary import build_glossary
from experiments.translation_v3 import recipes as R


class GlossaryTest(unittest.TestCase):
    def test_majority_rendering_becomes_the_entry(self):
        cues = [("アリシアが来た", "艾莉西亚来了"), ("アリシアは強い", "艾莉西亚很强"),
                ("アリシア、待って", "艾莉西亚，等等"), ("今日は晴れ", "今天晴天")]
        self.assertEqual(build_glossary({"W01": cues}), {"W01": [{"source": "アリシア", "translation": "艾莉西亚"}]})

    def test_recipe_injects_only_entries_visible_in_the_window(self):
        recipe = R.compose("gl", R.BUILTIN["b10-joint"],
                           glossary={"W01": [{"source": "アリシア", "translation": "艾莉西亚"},
                                             {"source": "ドワーフ", "translation": "矮人"}]})
        window = {"id": "b0", "source_language": "ja", "target_language": "zh-Hans",
                  "context": [{"id": "c1", "text": "アリシアが来た"}], "translate_ids": ["c1"]}
        self.assertEqual(R.glossary_for_window(recipe, "W01", window), [{"source": "アリシア", "translation": "艾莉西亚"}])
        self.assertIn("艾莉西亚", R.render_translation(recipe, window, work_id="W01"))
        self.assertNotIn("矮人", R.render_translation(recipe, window, work_id="W01"))
        self.assertNotIn(R.GLOSSARY_INJECTION, R.render_translation(recipe, window, work_id="W02"))
        self.assertNotEqual(recipe.recipe_hash, R.BUILTIN["b10-joint"].recipe_hash)


if __name__ == "__main__":
    unittest.main()
