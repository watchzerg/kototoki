"""`experiments.translation_v3.llama_server` 的离线测试：驻留证据、命令行拼装、引擎核对、`server_stop` 标注、
`/tokenize`／`/completion` 客户端的交换目录命名。

2026-11-11 架构整理票据 05（ADR-0025）随代码从产品 `tests/core/test_llama_server.py` 搬来，断言不变；
产品客户端、OOM 识别的测试在 `tests/core/test_local_client.py`，显存轮询的测试在 `tests/core/test_strata.py`。
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from experiments.translation_v3.llama_server import (
    LlamaClient, ManagedServer, ServerSpec, check_engine, residency_evidence, server_command, validate_residency,
)
from kototoki.artifacts import read_json, sha256_bytes

# 环境 smoke 中 stock llama.cpp b11583 的真实加载日志节选
LOADER_LOG = """\
0.01.277.190 I load_tensors: offloaded 49/49 layers to GPU
0.01.277.194 I load_tensors:   CPU_Mapped model buffer size =   132.75 MiB
0.01.277.195 I load_tensors:        CUDA0 model buffer size = 14201.67 MiB
"""

SPEC = ServerSpec(stage="names", candidate="toy", model_asset={"file": "toy.gguf", "size": 1, "sha256": "0" * 64},
                  layers=64, context=20480, extra_args=("--jinja", "--reasoning", "off"), min_free_mib=12000,
                  load_timeout_s=300)


SPEC = ServerSpec(stage="names", candidate="toy", model_asset={"file": "toy.gguf", "size": 1, "sha256": "0" * 64},
                  layers=64, context=20480, extra_args=("--jinja", "--reasoning", "off"), min_free_mib=12000,
                  load_timeout_s=300)


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


class ServerCommandTests(unittest.TestCase):
    def test_extra_args_sit_between_fixed_head_and_logging_tail(self):
        command = server_command(SPEC, Path("llama-server.exe"), Path("toy.gguf"), 8081, Path("server.log"))
        self.assertEqual(command, ["llama-server.exe", "-m", "toy.gguf", "--host", "127.0.0.1", "--port", "8081",
                                   "-c", "20480", "-np", "1", "-ngl", "64", "--jinja", "--reasoning", "off",
                                   "--no-webui", "--log-file", "server.log", "-lv", "4"])


class CheckEngineTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.engine = self.dir / "llama-server.exe"
        self.engine.write_bytes(b"exe")
        (self.dir / "ggml-cuda.dll").write_bytes(b"dll")
        self.identity = {"runtime_file_sha256": {"llama-server.exe": sha256_bytes(b"exe"),
                                                 "ggml-cuda.dll": sha256_bytes(b"dll"),
                                                 "llama-bench.exe": "0" * 64}}
        self.cache = self.dir / "cache.json"

    def test_matching_files_pass_and_are_cached(self):
        self.assertEqual(set(check_engine(self.engine, self.identity, self.cache)), {"llama-server.exe", "ggml-cuda.dll"})
        self.assertTrue(self.cache.is_file())

    def test_modified_dll_raises(self):
        (self.dir / "ggml-cuda.dll").write_bytes(b"patched")
        with self.assertRaisesRegex(ValueError, "mismatch"):
            check_engine(self.engine, self.identity, self.cache)

    def test_unlisted_dll_raises(self):
        (self.dir / "extra.dll").write_bytes(b"x")
        with self.assertRaisesRegex(ValueError, "not in identity"):
            check_engine(self.engine, self.identity, self.cache)


class FakeProcess:
    """替身 llama-server 进程：`alive` 为 True 时只有 kill 能结束它（terminate 超时），`hangs` 为 True 时 terminate 不生效。"""

    def __init__(self, *, alive: bool, hangs: bool = False, code: int = 0):
        self.alive, self.hangs, self.code = alive, hangs, code
        self.pid = 4242
        self.calls: list[str] = []

    @property
    def returncode(self):
        return self.poll()

    def poll(self):
        return None if self.alive else self.code

    def terminate(self):
        self.calls.append("terminate")
        if not self.hangs:
            self.alive, self.code = False, 1  # Windows 上 TerminateProcess 的固定退出码

    def kill(self):
        self.calls.append("kill")
        self.alive, self.code = False, -9

    def wait(self, timeout=None):
        if self.alive:
            raise subprocess.TimeoutExpired("llama-server", timeout or 0)
        return self.code


class ManagedServerStopTests(unittest.TestCase):
    """`__exit__` 只靠进程对象，不需要真实 server：核对 `engine-final.json` 的 `server_stop` 标注。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.runtime = Path(tmp.name) / "session-01"
        self.runtime.mkdir()
        self.pids: list[int | None] = []

    def server(self, process) -> ManagedServer:
        server = ManagedServer(self.runtime, SPEC, engine=Path("llama-server.exe"), model=Path("m.gguf"), port=18080,
                               model_cache=Path("cache.json"), on_pid=self.pids.append)
        server.process = process
        return server

    def final(self) -> dict:
        return read_json(self.runtime / "engine-final.json")

    def test_terminate_is_labelled_so_exit_code_1_is_not_a_fault(self):
        process = FakeProcess(alive=True)
        self.server(process).__exit__(None, None, None)
        self.assertEqual(process.calls, ["terminate"])
        final = self.final()
        self.assertEqual((final["server_exit_code"], final["server_stop"]), (1, "terminated"))
        self.assertEqual(self.pids, [None])

    def test_kill_after_terminate_timeout_is_labelled(self):
        process = FakeProcess(alive=True, hangs=True)
        self.server(process).__exit__(None, None, None)
        self.assertEqual(process.calls, ["terminate", "kill"])
        self.assertEqual(self.final()["server_stop"], "killed")

    def test_process_that_already_exited_keeps_its_own_exit_code(self):
        self.server(FakeProcess(alive=False, code=3)).__exit__(None, None, None)
        final = self.final()
        self.assertEqual((final["server_exit_code"], final["server_stop"]), (3, "exited"))

    def test_never_started_records_none(self):
        self.server(None).__exit__(None, None, None)
        final = self.final()
        self.assertEqual((final["server_exit_code"], final["server_stop"]), (None, None))
        self.assertEqual(self.pids, [])


class FakeResponse:
    def __init__(self, body: bytes):
        self.status, self.body = 200, body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body


class FakeOpener:
    """记录请求、返回固定正文；不碰 socket。"""

    def __init__(self, body: bytes):
        self.body = body
        self.requests: list = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        return FakeResponse(self.body)


class LlamaClientTraceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.trace = Path(tmp.name) / "transport"
        self.client = LlamaClient("http://127.0.0.1:8081", trace_dir=self.trace)

    def test_completion_trace_keeps_the_numeric_name(self):
        self.client.opener = FakeOpener(b'{"content": "x"}')
        self.client.complete({"prompt": [1]})
        self.client.chat_completion({"messages": []})
        self.assertEqual(sorted(p.name for p in self.trace.iterdir()), ["00001", "chat-02"])

    def test_tokenize_posts_the_native_prompt_and_checks_the_ids(self):
        self.client.opener = FakeOpener(b'{"tokens": [1, 2, 3]}')
        self.assertEqual(self.client.tokenize("<s>x"), [1, 2, 3])
        (request,) = self.client.opener.requests
        self.assertEqual(request.full_url, "http://127.0.0.1:8081/tokenize")
        self.assertEqual(json.loads(request.data), {"content": "<s>x", "add_special": False, "parse_special": True})
        self.client.opener = FakeOpener(b'{"tokens": []}')
        with self.assertRaisesRegex(ValueError, "nonempty integer"):
            self.client.tokenize("x")


if __name__ == "__main__":
    unittest.main()
