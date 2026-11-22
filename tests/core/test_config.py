from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from kototoki import config

MINIMAL = '[paths]\ninput_dir = "in"\n'


class LoadTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "配置 dir"
        self.root.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, text: str) -> Path:
        path = self.root / "kototoki.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_defaults_fill_missing_keys(self) -> None:
        cfg = config.load(self.write(MINIMAL), environ={})
        self.assertEqual(cfg.engine, "cross")  # ADR-0035「默认引擎」
        self.assertEqual(cfg.run.extract_workers, 4)
        self.assertIs(cfg.input.use_embedded_subtitles, True)  # ADR-0024：默认采用内嵌日文字幕
        self.assertEqual(cfg.cues, config.CueRules(24, 6.0, 0.8, 1.0, "。！？!?", "、，,", 0.3))
        self.assertEqual(cfg.source, self.root / "kototoki.toml")

    def test_user_relative_paths_resolve_against_config_dir(self) -> None:
        cfg = config.load(self.write(MINIMAL + 'work_dir = "w"\nmodels_root = "models"\nffmpeg = "bin/ffmpeg"\n'), environ={})
        self.assertEqual(cfg.paths.input_dir, self.root / "in")
        self.assertEqual(cfg.paths.work_dir, self.root / "w")
        self.assertEqual(cfg.paths.models_root, self.root / "models")
        self.assertEqual(cfg.paths.ffmpeg, self.root / "bin" / "ffmpeg")

    def test_unknown_keys_and_sections_are_errors(self) -> None:
        for text, needle in ((MINIMAL + "bogus = 1\n", "bogus"),
                             (MINIMAL + "[extra]\nx = 1\n", "[extra]")):
            with self.subTest(needle=needle), self.assertRaisesRegex(config.ConfigError, needle.replace("[", r"\[")):
                config.load(self.write(text), environ={})

    def test_required_paths_and_types_are_checked(self) -> None:
        bad = (('[paths]\n', "input_dir is required"),
               (MINIMAL + "[run]\nextract_workers = \"4\"\n", "must be an integer"),
               (MINIMAL + "[translate]\nseed = 0\n", r"\[translate\] seed"))  # Strata 不接受 0
        for text, message in bad:
            with self.subTest(message=message), self.assertRaisesRegex(config.ConfigError, message):
                config.load(self.write(text), environ={})


if __name__ == "__main__":
    unittest.main()
