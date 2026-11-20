"""`scripts/subtitles.py`（`just subtitles <目录>`）：写出的临时配置能被 `config.load` 读回、只设 input_dir，并原样转交产品入口。"""

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

    def test_config_sets_only_input_dir_and_keeps_defaults(self) -> None:
        path = subtitles.write_config(self.input_dir, self.config_dir)
        self.assertEqual(path.parent, self.config_dir)
        self.assertTrue(path.name.startswith("アニメ 第1期-"))
        cfg = config.load(path, environ={})
        self.assertEqual(cfg.paths.input_dir, self.input_dir.resolve())
        self.assertEqual(cfg.paths.work_dir, config.REPO_ROOT / ".local" / "work")
        self.assertEqual(cfg.engine, "cross")

    def test_same_directory_reuses_one_file(self) -> None:
        first = subtitles.write_config(self.input_dir, self.config_dir)
        second = subtitles.write_config(self.input_dir / ".." / self.input_dir.name, self.config_dir)
        self.assertEqual(first, second)
        self.assertEqual(len(list(self.config_dir.iterdir())), 1)

    def test_main_hands_the_config_to_the_product_entry(self) -> None:
        with mock.patch.object(subtitles, "CONFIG_DIR", self.config_dir), \
                mock.patch.object(subtitles.cli, "main", return_value=1) as entry:
            self.assertEqual(subtitles.main([str(self.input_dir)]), 1)
        (argv,), _ = entry.call_args
        self.assertEqual(config.load(Path(argv[0]), environ={}).paths.input_dir, self.input_dir.resolve())

    def test_rejects_wrong_argument_count(self) -> None:
        with mock.patch("sys.stderr"):
            self.assertEqual(subtitles.main([]), 2)


if __name__ == "__main__":
    unittest.main()
