"""kototoki.translate.server 的翻译特有测试：冻结命令行、模型身份核对、stderr 送 DEVNULL。

与翻译无关的 llama-server 用例（驻留证据、显存轮询、OOM 识别、引擎核对、`server_stop`）在 `test_llama_server.py`。
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from kototoki.llama_server import InfraFailure, ManagedServer, check_model, loader_logs, server_command

from kototoki.translate.server import MODEL_ASSET, TRANSLATE_SPEC
from tests.core.test_llama_server import FakeProcess


class ServerCommandTests(unittest.TestCase):
    def test_frozen_flags_present(self):
        command = server_command(TRANSLATE_SPEC, Path("llama-server.exe"), Path("m.gguf"), 18080, Path("server.log"))
        for flag, value in [("-c", "8192"), ("-np", "1"), ("-ngl", "99"), ("--cache-ram", "8192"),
                            ("--fit", "off"), ("-fa", "on"), ("-ctk", "f16"), ("-lv", "4"),
                            ("--host", "127.0.0.1"), ("--port", "18080")]:
            with self.subTest(flag=flag):
                self.assertEqual(command[command.index(flag) + 1], value)

    def test_full_command_is_frozen(self):
        """票据 02 抽出共享模块前 `server_command` 的完整输出（逐元素、逐顺序）。"""
        command = server_command(TRANSLATE_SPEC, Path("llama-server.exe"), Path("m.gguf"), 18080, Path("server.log"))
        self.assertEqual(command, ["llama-server.exe", "-m", "m.gguf", "--host", "127.0.0.1", "--port", "18080",
                                   "-c", "8192", "-np", "1", "-ngl", "99", "-b", "256", "-ub", "128", "-t", "8",
                                   "-tb", "8", "-ctk", "f16", "-ctv", "f16", "--cache-ram", "8192", "-fa", "on",
                                   "--fit", "off", "--no-webui", "--log-file", "server.log", "-lv", "4"])


class CheckModelTests(unittest.TestCase):
    def test_wrong_file_name_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "other.gguf"
            model.write_bytes(b"x")
            with self.assertRaisesRegex(ValueError, "must be"):
                check_model(model, TRANSLATE_SPEC, Path(tmp) / "cache.json")

    def test_wrong_size_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / MODEL_ASSET["file"]
            model.write_bytes(b"tiny")
            with self.assertRaisesRegex(ValueError, "size"):
                check_model(model, TRANSLATE_SPEC, Path(tmp) / "cache.json")


class ServerLogFilesTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_loader_logs_ignore_a_leftover_stderr_log(self):
        (self.dir / "server.log").write_text("offloaded 49/49 layers to GPU\n", encoding="utf-8")
        (self.dir / "stdout.log").write_text("out\n", encoding="utf-8")
        (self.dir / "stderr.log").write_text("old duplicate\n", encoding="utf-8")
        text = loader_logs(self.dir)
        self.assertIn("offloaded 49/49", text)
        self.assertIn("out", text)
        self.assertNotIn("old duplicate", text)

    def test_server_stderr_is_discarded_instead_of_saved(self):
        """启动走到 Popen 为止（替身进程立刻退出 → `InfraFailure`）：stderr 送 DEVNULL，目录里没有 stderr.log。"""
        engine = self.dir / "llama-server.exe"
        engine.write_bytes(b"exe")
        (self.dir / "identity.json").write_text("{}", encoding="utf-8")
        runtime = self.dir / "session-01"
        popen = mock.Mock(return_value=FakeProcess(alive=False, code=2))
        with mock.patch("kototoki.llama_server.port_free", return_value=True), \
                mock.patch("kototoki.llama_server.check_engine", return_value={"llama-server.exe": "0" * 64}), \
                mock.patch("kototoki.llama_server.check_model", return_value={}), \
                mock.patch("kototoki.llama_server.wait_for_free_vram", return_value=16000), \
                mock.patch("kototoki.llama_server.subprocess.Popen", popen), \
                self.assertRaisesRegex(InfraFailure, "exited 2 during load"):
            ManagedServer(runtime, TRANSLATE_SPEC, engine=engine, model=self.dir / "m.gguf", port=18080,
                          model_cache=self.dir / "cache.json").__enter__()
        self.assertEqual(popen.call_args.kwargs["stderr"], subprocess.DEVNULL)
        self.assertEqual(sorted(p.name for p in runtime.iterdir()), ["engine-final.json", "stdout.log"])


if __name__ == "__main__":
    unittest.main()
