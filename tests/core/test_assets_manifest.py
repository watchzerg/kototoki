"""代码常量 == 资产清单 `assets.toml`：防止模型 SHA 表与默认模型路径漂移。
翻译与专名建表的模型由 Strata 管理（ADR-0029「Strata session」），不在清单里；清单只列产品用到的 STT 模型，ffmpeg 是系统包（ADR-0034）。

清单是身份的唯一权威（docs/development/dependencies.md）；代码常量保留用于运行时自校验，这里逐项钉住相等。
"""

from __future__ import annotations

import tomllib
import unittest

from kototoki import config, plan

with (config.REPO_ROOT / "assets.toml").open("rb") as _stream:
    MANIFEST = tomllib.load(_stream)
MODELS = MANIFEST["models"]


def shas(name: str) -> dict[str, str]:
    return {relative: entry["sha256"] for relative, entry in MODELS[name]["files"].items()}


class ModelConstantsTests(unittest.TestCase):
    def test_plan_tables_equal_manifest(self) -> None:
        self.assertEqual(shas("pyannote-segmentation-3.0"), {"pytorch_model.bin": plan.VAD_CHECKPOINT_SHA256})
        self.assertEqual(shas("faster-whisper-large-v3"), plan.W0_FILES)
        self.assertEqual(shas("qwen3-asr-1.7b-hf"), plan.X0_FILES)
        self.assertEqual(shas("mms-1b-all"), plan.MMS_FILES)


if __name__ == "__main__":
    unittest.main()
