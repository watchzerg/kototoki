"""代码常量 == 资产清单 `assets.toml`：防止模型 SHA 表与默认模型路径漂移。
翻译与专名建表的模型由 Strata 管理（ADR-0029「Strata session」），不在清单里；清单只列产品用到的 STT 模型，ffmpeg 是系统包（ADR-0034）。

清单是身份的唯一权威（docs/development/dependencies.md）；代码常量保留用于运行时自校验，这里逐项钉住相等。
"""

from __future__ import annotations

import importlib.util
import tomllib
import unittest
from urllib.request import Request

from kototoki import config, plan

_ASSETS_SPEC = importlib.util.spec_from_file_location("assets_script", config.REPO_ROOT / "scripts" / "assets.py")
assets_script = importlib.util.module_from_spec(_ASSETS_SPEC)
_ASSETS_SPEC.loader.exec_module(assets_script)

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


class RedirectAuthTests(unittest.TestCase):
    def _redirect(self, old_url: str, new_url: str) -> Request:
        handler = assets_script._SafeRedirectHandler()
        req = Request(old_url, headers={"Authorization": "Bearer secret", "User-Agent": "test"})
        redirected = handler.redirect_request(req, None, 302, "Found", {}, new_url)
        self.assertIsNotNone(redirected)
        return redirected

    def test_cross_host_and_scheme_downgrade_strip_authorization(self) -> None:
        for new_url in ("https://cdn-lfs.example.com/file?sig=1", "http://huggingface.co/repo/file"):
            with self.subTest(new_url=new_url):
                redirected = self._redirect("https://huggingface.co/repo/resolve/rev/file", new_url)
                self.assertFalse(redirected.has_header("Authorization"))
                self.assertEqual(redirected.get_header("User-agent"), "test")

    def test_same_origin_preserves_authorization(self) -> None:
        for new_url in ("https://huggingface.co/other/path", "https://huggingface.co:443/other/path"):
            with self.subTest(new_url=new_url):
                redirected = self._redirect("https://huggingface.co/repo/resolve/rev/file", new_url)
                self.assertEqual(redirected.get_header("Authorization"), "Bearer secret")


if __name__ == "__main__":
    unittest.main()
