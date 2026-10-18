"""代码常量 == 资产清单 `assets.toml`：防止模型 SHA 表、翻译模型身份与默认路径里的版本号三处漂移。

清单是身份的唯一权威（docs/development/dependencies.md）；代码常量保留用于运行时自校验，这里逐项钉住相等。
"""

from __future__ import annotations

import tomllib
import unittest

from kototoki import config, plan, recipes
from kototoki.translate.server import MODEL_ASSET

with (config.REPO_ROOT / "assets.toml").open("rb") as _stream:
    MANIFEST = tomllib.load(_stream)
MODELS = MANIFEST["models"]
TOOLS = MANIFEST["tools"]


def shas(name: str) -> dict[str, str]:
    return {relative: entry["sha256"] for relative, entry in MODELS[name]["files"].items()}


class ModelConstantsTests(unittest.TestCase):
    def test_plan_tables_equal_manifest(self) -> None:
        self.assertEqual(shas("pyannote-segmentation-3.0"), {"pytorch_model.bin": plan.VAD_CHECKPOINT_SHA256})
        self.assertEqual(shas("faster-whisper-large-v3"), plan.W0_FILES)
        self.assertEqual(shas("w0-assets"), {"mel_filters.npz": recipes.W0["features"]["mel_sha256"]})
        self.assertEqual(shas("qwen3-asr-1.7b-hf"), plan.X0_FILES)
        self.assertEqual(shas("mms-1b-all"), plan.MMS_FILES)

    def test_translation_model_asset_equals_manifest(self) -> None:
        model = MODELS["hy-mt2-30b-a3b-apex-i-compact"]
        self.assertEqual((model["repo"], model["revision"]), (MODEL_ASSET["repo"], MODEL_ASSET["revision"]))
        self.assertEqual(model["files"], {MODEL_ASSET["file"]: {"sha256": MODEL_ASSET["sha256"],
                                                                "size": MODEL_ASSET["size"]}})

    def test_default_model_paths_point_into_manifest_dirs(self) -> None:
        defaults = config.DEFAULTS
        self.assertEqual(defaults["vad"]["model"], f"{MODELS['pyannote-segmentation-3.0']['dir']}/pytorch_model.bin")
        self.assertEqual(defaults["asr.w0"]["model"], MODELS["faster-whisper-large-v3"]["dir"])
        self.assertEqual(defaults["asr.w0"]["mel_assets"], MODELS["w0-assets"]["dir"])
        self.assertEqual(defaults["asr.x0"]["model"], MODELS["qwen3-asr-1.7b-hf"]["dir"])
        self.assertEqual(defaults["align"]["model"], MODELS["mms-1b-all"]["dir"])
        self.assertEqual(defaults["translate"]["model"],
                         f"{MODELS['hy-mt2-30b-a3b-apex-i-compact']['dir']}/{MODEL_ASSET['file']}")
        self.assertEqual(defaults["paths"]["models_root"], ".local/models")


class ToolPathTests(unittest.TestCase):
    def test_default_binary_paths_carry_manifest_versions(self) -> None:
        paths = config.DEFAULTS["paths"]
        ffmpeg, llama = TOOLS["ffmpeg"]["version"], TOOLS["llama.cpp"]["version"]
        self.assertEqual(paths["ffmpeg"], f".local/tools/ffmpeg/{ffmpeg}/bin/ffmpeg.exe")
        self.assertEqual(paths["ffprobe"], f".local/tools/ffmpeg/{ffmpeg}/bin/ffprobe.exe")
        self.assertEqual(paths["llama_server"], f".local/tools/llama.cpp/{llama}/llama-server.exe")

    def test_manifest_locks_the_files_the_product_runs(self) -> None:
        self.assertLessEqual({"bin/ffmpeg.exe", "bin/ffprobe.exe"}, set(TOOLS["ffmpeg"]["files"]))
        self.assertIn("llama-server.exe", TOOLS["llama.cpp"]["files"])


if __name__ == "__main__":
    unittest.main()
