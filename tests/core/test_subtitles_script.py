"""`scripts/subtitles.py`（`mise run subtitles <目录>`）：写出的临时配置能被 `config.load` 读回、只设 input_dir，并原样转交产品入口。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from kototoki import config

_SPEC = importlib.util.spec_from_file_location("subtitles_script", config.REPO_ROOT / "scripts" / "subtitles.py")
subtitles = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(subtitles)


class SubtitlesScriptCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.input_dir = self.root / "アニメ 第1期"   # 非 ASCII 与空格
        self.input_dir.mkdir()
        self.config_dir = self.root / "run-configs"

    def test_main_hands_the_config_to_the_product_entry(self) -> None:
        with mock.patch.object(subtitles, "CONFIG_DIR", self.config_dir), \
                mock.patch.object(subtitles.cli, "main", return_value=1) as entry:
            self.assertEqual(subtitles.main([str(self.input_dir)]), 1)
        (argv,), _ = entry.call_args
        self.assertEqual(config.load(Path(argv[0]), environ={}).paths.input_dir, self.input_dir.resolve())

    def test_write_config_escapes_quotes_and_backslashes(self) -> None:
        tricky = self.root / 'アニメ "第1期"\\特番'
        tricky.mkdir()
        path = subtitles.write_config(tricky, config_dir=self.config_dir)
        self.assertEqual(config.load(path, environ={}).paths.input_dir, tricky.resolve())


if __name__ == "__main__":
    unittest.main()
