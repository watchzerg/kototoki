import json
from pathlib import Path
import tempfile
import unittest

from experiments.quality_v5.confirm_set import v4_sources


class ConfirmSetTest(unittest.TestCase):
    def test_v4_sources_cover_dev_and_confirm_case_insensitively(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, path in (("dev", r"D:\Lib\W01\E01\ja.srt"), ("confirm", r"D:\Lib\W02\E03\JA.srt")):
                (root / "sets" / name).mkdir(parents=True)
                (root / "sets" / name / "scenes.jsonl").write_text(
                    json.dumps({"source_ja_srt": path}) + "\n", encoding="utf-8")
            keys = v4_sources(root)
        self.assertEqual(keys, {str(Path(r"d:\lib\w01\e01\ja.srt")), str(Path(r"d:\lib\w02\e03\ja.srt"))})


if __name__ == "__main__":
    unittest.main()
