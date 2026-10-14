"""kototoki.translate.server 的纯函数测试：驻留证据、显存轮询、OOM 识别、冻结命令行、模型身份核对。"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from kototoki.translate.server import (
    InfraFailure, MODEL_ASSET, check_model, explicit_oom, residency_evidence, server_command,
    validate_residency, wait_for_free_vram,
)

# 环境 smoke 中 stock llama.cpp b11583 的真实加载日志节选
LOADER_LOG = """\
0.01.277.190 I load_tensors: offloaded 49/49 layers to GPU
0.01.277.194 I load_tensors:   CPU_Mapped model buffer size =   132.75 MiB
0.01.277.195 I load_tensors:        CUDA0 model buffer size = 14201.67 MiB
"""


class ResidencyTests(unittest.TestCase):
    def test_evidence_parsed_from_stock_log(self):
        evidence = residency_evidence(LOADER_LOG)
        self.assertEqual(evidence["gpu_layers_offloaded"], 49)
        self.assertEqual(evidence["model_layers_total"], 49)
        self.assertEqual(evidence["layers_not_offloaded"], 0)
        self.assertEqual(evidence["gpu_model_buffers_mib"], {"CUDA0": 14201.67})
        self.assertEqual(evidence["cpu_model_buffers_mib"], {"CPU_Mapped": 132.75})

    def test_full_offload_passes_with_larger_requested_layers(self):
        validate_residency(residency_evidence(LOADER_LOG), 99)

    def test_partial_offload_raises(self):
        log = LOADER_LOG.replace("49/49", "40/49")
        with self.assertRaisesRegex(RuntimeError, "Partial"):
            validate_residency(residency_evidence(log), 99)

    def test_missing_offload_line_raises(self):
        log = "\n".join(line for line in LOADER_LOG.splitlines() if "offloaded" not in line)
        with self.assertRaises(RuntimeError):
            validate_residency(residency_evidence(log), 99)

    def test_missing_cuda_buffer_raises(self):
        log = "\n".join(line for line in LOADER_LOG.splitlines() if "CUDA0" not in line)
        with self.assertRaisesRegex(RuntimeError, "GPU model buffer"):
            validate_residency(residency_evidence(log), 99)


class WaitForFreeVramTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def _sleep(self, seconds: float) -> None:
        # 假睡眠只推进假时钟，不真正等待
        self.sleeps.append(seconds)
        self.now += seconds

    def _wait(self, readings, timeout=10.0):
        iterator = iter(readings)
        last = [None]

        def query():
            last[0] = next(iterator, last[0])
            return last[0]

        return wait_for_free_vram(14300, timeout, query=query, sleep=self._sleep, clock=lambda: self.now)

    def test_returns_reading_once_threshold_reached(self):
        self.assertEqual(self._wait([1000, 5000, 14500, 16000]), 14500)
        self.assertEqual(len(self.sleeps), 2)

    def test_timeout_raises_with_last_reading(self):
        with self.assertRaises(InfraFailure) as caught:
            self._wait([1000, 2000, 3456])
        self.assertIn("3456", str(caught.exception))

    def test_unknown_reading_message(self):
        with self.assertRaises(InfraFailure) as caught:
            self._wait([None])
        message = str(caught.exception).lower()
        self.assertIn("unknown", message)
        self.assertIn("nvidia-smi failed", message)


class ExplicitOomTests(unittest.TestCase):
    def test_oom_messages_detected(self):
        for message in ("CUDA error: out of memory", "cudaErrorMemoryAllocation"):
            with self.subTest(message=message):
                self.assertTrue(explicit_oom(message))

    def test_non_oom_message_not_detected(self):
        self.assertFalse(explicit_oom("context size exceeded"))


class ServerCommandTests(unittest.TestCase):
    def test_frozen_flags_present(self):
        command = server_command(Path("llama-server.exe"), Path("m.gguf"), 18080, Path("server.log"))
        for flag, value in [("-c", "8192"), ("-np", "1"), ("-ngl", "99"), ("--cache-ram", "8192"),
                            ("--fit", "off"), ("-fa", "on"), ("-ctk", "f16"), ("-lv", "4"),
                            ("--host", "127.0.0.1"), ("--port", "18080")]:
            with self.subTest(flag=flag):
                self.assertEqual(command[command.index(flag) + 1], value)


class CheckModelTests(unittest.TestCase):
    def test_wrong_file_name_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "other.gguf"
            model.write_bytes(b"x")
            with self.assertRaisesRegex(ValueError, "must be"):
                check_model(model, Path(tmp) / "cache.json")

    def test_wrong_size_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / MODEL_ASSET["file"]
            model.write_bytes(b"tiny")
            with self.assertRaisesRegex(ValueError, "size"):
                check_model(model, Path(tmp) / "cache.json")


if __name__ == "__main__":
    unittest.main()
