"""代码常量 == 资产清单 `assets.toml`：防止模型 SHA 表与默认模型路径漂移。
翻译与专名建表的模型由 Strata 管理（ADR-0029「Strata session」），不在清单里；清单只列产品用到的 STT 模型，ffmpeg 是系统包（ADR-0034）。

清单是身份的唯一权威（docs/development/dependencies.md）；代码常量保留用于运行时自校验，这里逐项钉住相等。
"""

from __future__ import annotations

import tomllib
import unittest

from kototoki import config, plan, recipes

with (config.REPO_ROOT / "assets.toml").open("rb") as _stream:
    MANIFEST = tomllib.load(_stream)
MODELS = MANIFEST["models"]


def shas(name: str) -> dict[str, str]:
    return {relative: entry["sha256"] for relative, entry in MODELS[name]["files"].items()}


class ModelConstantsTests(unittest.TestCase):
    def test_plan_tables_equal_manifest(self) -> None:
        self.assertEqual(shas("pyannote-segmentation-3.0"), {"pytorch_model.bin": plan.VAD_CHECKPOINT_SHA256})
        self.assertEqual(shas("faster-whisper-large-v3"), plan.W0_FILES)
        self.assertEqual(shas("w0-assets"), {"mel_filters.npz": recipes.W0["features"]["mel_sha256"]})
        self.assertEqual(shas("qwen3-asr-1.7b-hf"), plan.X0_FILES)
        self.assertEqual(shas("mms-1b-all"), plan.MMS_FILES)

    def test_no_hy_mt2_translation_model_is_listed(self) -> None:
        self.assertFalse([name for name in MODELS if "hy-mt" in name.lower() or "apex" in name.lower()])
        self.assertNotIn("model", config.DEFAULTS["translate"])

    def test_default_model_paths_point_into_manifest_dirs(self) -> None:
        defaults = config.DEFAULTS
        self.assertEqual(defaults["vad"]["model"], f"{MODELS['pyannote-segmentation-3.0']['dir']}/pytorch_model.bin")
        self.assertEqual(defaults["asr.w0"]["model"], MODELS["faster-whisper-large-v3"]["dir"])
        self.assertEqual(defaults["asr.w0"]["mel_assets"], MODELS["w0-assets"]["dir"])
        self.assertEqual(defaults["asr.x0"]["model"], MODELS["qwen3-asr-1.7b-hf"]["dir"])
        self.assertEqual(defaults["align"]["model"], MODELS["mms-1b-all"]["dir"])
        self.assertNotIn("model", defaults["names"])  # 建表模型由 Strata 管理（ADR-0029「Strata session」）
        self.assertEqual(defaults["paths"]["models_root"], ".local/models")


class ManifestScopeTests(unittest.TestCase):
    def test_manifest_lists_only_models(self) -> None:
        self.assertEqual(set(MANIFEST), {"models"})  # ffmpeg 是系统包（ADR-0034「ffmpeg」）


if __name__ == "__main__":
    unittest.main()
