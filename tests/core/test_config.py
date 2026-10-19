from __future__ import annotations

from pathlib import Path
import tempfile
import tomllib
import unittest

from dataclasses import asdict

from kototoki import config, cues

MINIMAL = '[paths]\ninput_dir = "in"\noutput_dir = "out"\n'


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
        self.assertEqual(cfg.engine, "w0")
        self.assertEqual(cfg.run.extract_workers, 4)
        self.assertIs(cfg.run.force, False)
        self.assertEqual(cfg.run.stable_check_s, 10.0)
        self.assertEqual(cfg.input.audio_language, "jpn")
        self.assertEqual(cfg.input.video_extensions, (".mkv", ".mp4", ".m2ts", ".ts", ".mov", ".avi"))
        self.assertEqual(cfg.cues, config.CueRules(24, 6.0, 0.8, 1.0, "。！？!?", "、，,", 0.3))
        self.assertEqual(cfg.translate, config.TranslateConfig(port=8080, seed=20261008))
        self.assertEqual(cfg.names, config.NamesConfig(port=8081, seed=20261019, enabled=True))
        self.assertEqual(cfg.source, self.root / "kototoki.toml")

    def test_cue_rules_have_the_shape_build_cues_expects(self) -> None:
        rules = asdict(config.load(self.write(MINIMAL), environ={}).cues)
        self.assertEqual(set(rules), cues.RULE_KEYS)

    def test_user_relative_paths_resolve_against_config_dir(self) -> None:
        cfg = config.load(self.write(MINIMAL + 'models_root = "models"\nffmpeg = "bin/ffmpeg.exe"\n'), environ={})
        self.assertEqual(cfg.paths.input_dir, self.root / "in")
        self.assertEqual(cfg.paths.output_dir, self.root / "out")
        self.assertEqual(cfg.paths.models_root, self.root / "models")
        self.assertEqual(cfg.paths.ffmpeg, self.root / "bin" / "ffmpeg.exe")

    def test_default_relative_paths_resolve_against_repo_root(self) -> None:
        cfg = config.load(self.write(MINIMAL), environ={})
        self.assertEqual(cfg.paths.models_root, config.REPO_ROOT / ".local" / "models")
        # 默认路径里的版本号由 test_assets_manifest 钉住与 assets.toml 一致；这里只核对相对仓库根解析。
        for key in ("ffmpeg", "ffprobe", "llama_server"):
            self.assertEqual(getattr(cfg.paths, key), config.REPO_ROOT / config.DEFAULTS["paths"][key])

    def test_model_paths_are_relative_to_models_root(self) -> None:
        cfg = config.load(self.write(MINIMAL + 'models_root = "m"\n[asr.w0]\nmodel = "w"\n[align]\nmodel = "D:/abs/mms"\n'),
                          environ={})
        self.assertEqual(cfg.models.w0, self.root / "m" / "w")
        self.assertEqual(cfg.models.w0_mel_assets, self.root / "m" / "w0-assets")
        self.assertEqual(cfg.models.align, Path("D:/abs/mms").resolve())
        default = config.load(self.write(MINIMAL), environ={})
        self.assertEqual(default.models.vad, config.REPO_ROOT / ".local/models/vad-comparison/"
                         "pyannote-segmentation-3.0/pytorch_model.bin")

    def test_cross_engine_is_accepted_and_carries_both_asr_models(self) -> None:
        cfg = config.load(self.write(MINIMAL + '[stt]\nengine = "cross"\n'), environ={})
        self.assertEqual(cfg.engine, "cross")
        self.assertEqual(config.ENGINES, ("w0", "x0", "cross"))
        self.assertEqual(cfg.models.w0, config.REPO_ROOT / ".local/models/faster-whisper-large-v3")
        self.assertEqual(cfg.models.w0_mel_assets, config.REPO_ROOT / ".local/models/w0-assets")
        self.assertEqual(cfg.models.x0, config.REPO_ROOT / ".local/models/qwen3-asr-1.7b-hf")

    def test_unknown_engine_message_lists_all_engines(self) -> None:
        with self.assertRaisesRegex(config.ConfigError, r"one of w0, x0, cross, got 'w1'"):
            config.load(self.write(MINIMAL + '[stt]\nengine = "w1"\n'), environ={})

    def test_names_model_is_relative_to_models_root(self) -> None:
        default = config.load(self.write(MINIMAL), environ={})
        self.assertEqual(default.models.names,
                         config.REPO_ROOT / ".local/models/glossary-v1/Qwen3.8-27B-UD-IQ3_S.gguf")
        cfg = config.load(self.write(MINIMAL + 'models_root = "m"\n[names]\nmodel = "g/x.gguf"\nport = 9\nseed = 1\n'
                                              'enabled = false\n'), environ={})
        self.assertEqual(cfg.models.names, self.root / "m" / "g" / "x.gguf")
        self.assertEqual(cfg.names, config.NamesConfig(port=9, seed=1, enabled=False))

    def test_unknown_keys_and_sections_are_errors(self) -> None:
        for text, needle in ((MINIMAL + "bogus = 1\n", "bogus"),
                             (MINIMAL + "[names]\nthink = true\n", "think"),
                             (MINIMAL + "[vad]\ndevice = \"cpu\"\n", "device"),
                             (MINIMAL + "[run]\nbreak_stale_lock = true\n", "break_stale_lock"),
                             (MINIMAL + "[extra]\nx = 1\n", "[extra]"),
                             (MINIMAL + "[asr.whisper]\nmodel = \"x\"\n", "[asr.whisper]")):
            with self.subTest(needle=needle), self.assertRaisesRegex(config.ConfigError, needle.replace("[", r"\[")):
                config.load(self.write(text), environ={})

    def test_required_paths_and_types_are_checked(self) -> None:
        bad = (('[paths]\ninput_dir = "in"\n', "output_dir is required"),
               (MINIMAL + "[run]\nextract_workers = \"4\"\n", "must be an integer"),
               (MINIMAL + "[run]\nforce = 1\n", "true or false"),
               (MINIMAL + "[names]\nenabled = 1\n", r"\[names\] enabled must be true or false"),
               (MINIMAL + "[names]\nenabled = \"true\"\n", "true or false"),
               (MINIMAL + "[stt]\nengine = \"w1\"\n", "engine must be one of"),
               (MINIMAL + "[input]\nvideo_extensions = \".mkv\"\n", "list of nonempty strings"),
               (MINIMAL + "[run]\nextract_workers = 0\n", "at least 1"))
        for text, message in bad:
            with self.subTest(message=message), self.assertRaisesRegex(config.ConfigError, message):
                config.load(self.write(text), environ={})

    def test_integer_accepted_for_float_keys(self) -> None:
        cfg = config.load(self.write(MINIMAL + "[cues]\nmax_duration_s = 7\n"), environ={})
        self.assertEqual(cfg.cues.max_duration_s, 7.0)
        self.assertIsInstance(cfg.cues.max_duration_s, float)

    def test_invalid_toml_and_missing_file_raise_config_error(self) -> None:
        with self.assertRaisesRegex(config.ConfigError, "Invalid TOML"):
            config.load(self.write("[paths\n"), environ={})
        with self.assertRaisesRegex(config.ConfigError, "Cannot read"):
            config.load(self.root / "missing.toml", environ={})

    def test_gpu_lock_is_fixed_and_break_stale_lock_comes_from_environment(self) -> None:
        path = self.write(MINIMAL)
        self.assertEqual(config.load(path, environ={}).gpu_lock, config.REPO_ROOT / ".local" / "gpu.lock")
        self.assertIs(config.load(path, environ={}).break_stale_lock, False)
        self.assertIs(config.load(path, environ={"KOTOTOKI_BREAK_STALE_LOCK": "1"}).break_stale_lock, True)
        self.assertIs(config.load(path, environ={"KOTOTOKI_BREAK_STALE_LOCK": "0"}).break_stale_lock, False)


class ExampleFileTests(unittest.TestCase):
    def test_example_config_loads_and_lists_every_key(self) -> None:
        example = config.REPO_ROOT / "kototoki.toml.example"
        cfg = config.load(example, environ={})
        self.assertEqual(cfg.engine, "w0")
        with example.open("rb") as stream:
            document = tomllib.load(stream)
        written = {(section, key) for section, table in config._flatten(document).items() for key in table}
        expected = {(section, key) for section, table in config.DEFAULTS.items() for key in table}
        self.assertEqual(written, expected)


if __name__ == "__main__":
    unittest.main()
