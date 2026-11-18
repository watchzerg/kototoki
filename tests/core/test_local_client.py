"""`kototoki.local_client` 的测试：OOM 识别、本机客户端的 trace 与回环限制。

2026-11-11 架构整理票据 05（ADR-0025）由 `test_llama_server.py` 拆出：llama-server 生命周期的测试随代码搬到
`archive/2026-11-18-pre-research-restructure:experiments/translation_v3/test_llama_server.py`，显存轮询的测试并入 `test_strata.py`。
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import tempfile
import unittest

from kototoki.artifacts import read_json
from kototoki.local_client import LlamaClient, explicit_oom


class ExplicitOomTests(unittest.TestCase):
    def test_oom_messages_detected(self):
        for message in ("CUDA error: out of memory", "cudaErrorMemoryAllocation"):
            with self.subTest(message=message):
                self.assertTrue(explicit_oom(message))

    def test_non_oom_message_not_detected(self):
        self.assertFalse(explicit_oom("context size exceeded"))


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

    def test_chat_completion_posts_to_the_openai_endpoint_and_traces_as_chat(self):
        reply = {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}
        self.client.opener = FakeOpener(json.dumps(reply).encode("utf-8"))
        body = {"messages": [{"role": "user", "content": "x"}], "seed": 1}
        self.assertEqual(self.client.chat_completion(body), reply)
        (request,) = self.client.opener.requests
        self.assertEqual(request.full_url, "http://127.0.0.1:8081/v1/chat/completions")
        self.assertEqual(json.loads(request.data), body)
        exchange = self.trace / "chat-01"
        self.assertEqual(self.client.last_exchange, str(exchange))
        self.assertEqual(json.loads((exchange / "request.json").read_bytes()),
                         {"endpoint": "/v1/chat/completions", "body": body})
        self.assertEqual(json.loads((exchange / "response.raw").read_bytes()), reply)
        self.assertEqual(read_json(exchange / "transport.json")["status"], 200)

    def test_unlabelled_request_keeps_the_numeric_name(self):
        self.client.opener = FakeOpener(b'{"content": "x"}')
        self.client.request("/v1/messages/count_tokens", {"messages": []})
        self.client.request("/v1/messages/count_tokens", {"messages": []}, trace_label="count")
        self.client.chat_completion({"messages": []})
        self.assertEqual(sorted(p.name for p in self.trace.iterdir()), ["00001", "chat-03", "count-02"])

    def test_research_only_methods_are_not_in_the_product_client(self):
        # ADR-0025：`/tokenize`、`/completion` 只有研究侧用，在 `archive/2026-11-18-pre-research-restructure:experiments/translation_v3/llama_server.py`
        self.assertFalse(hasattr(self.client, "tokenize"))
        self.assertFalse(hasattr(self.client, "complete"))

    def test_non_loopback_url_is_refused(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            LlamaClient("http://example.com:8081")


class ModuleTests(unittest.TestCase):
    def test_old_llama_server_module_is_gone(self):
        # ADR-0025：不留再导出模块
        with self.assertRaises(ImportError):
            importlib.import_module("kototoki.llama_server")


if __name__ == "__main__":
    unittest.main()
