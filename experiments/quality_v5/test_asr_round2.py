import json
from pathlib import Path
import tempfile
import unittest

from experiments.quality_v5.asr_round2 import write_align_jobs
from kototoki import plan


class AsrRound2Test(unittest.TestCase):
    def test_align_jobs_cover_transcribed_dirs_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "candidate"
            for name, done in (("aaa", True), ("bbb", False)):
                (root / name).mkdir(parents=True)
                if done:
                    (root / name / "asr.json").write_text("{}", encoding="utf-8")
            config = Path(tmp) / "jobs-asr.json"
            config.write_text(json.dumps({"config": {"models": {}, "model_cache": "x"}}), encoding="utf-8")
            jobs = json.loads(write_align_jobs(root, config).read_text(encoding="utf-8"))
        self.assertEqual(jobs["stage"], "align")
        self.assertEqual(jobs["recipe_hash"], plan.recipe_hash("align"))
        self.assertEqual([entry["id"] for entry in jobs["files"]], ["aaa"])
        self.assertEqual(set(jobs["files"][0]["inputs"]), {"wav", "asr"})


if __name__ == "__main__":
    unittest.main()
