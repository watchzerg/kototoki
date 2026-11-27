"""`kototoki.local_client` 的测试：OOM 识别、本机客户端的 trace 与回环限制。

2026-11-11 架构整理票据 05（ADR-0025）由 `test_llama_server.py` 拆出：llama-server 生命周期的测试随代码搬到
`archive/2026-11-18-pre-research-restructure:experiments/translation_v3/test_llama_server.py`，显存轮询的测试并入 `test_strata.py`。
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from kototoki.artifacts import read_json
from kototoki.local_client import LlamaClient, classify_failure, explicit_oom, response_body


class ExplicitOomTests(unittest.TestCase):
    def test_oom_messages_detected(self):
        for message in ("CUDA error: out of memory", "cudaErrorMemoryAllocation"):
            with self.subTest(message=message):
                self.assertTrue(explicit_oom(message))


class FailureClassificationTests(unittest.TestCase):
    def test_failure_text_is_oom_or_server_error(self):
        self.assertEqual(classify_failure("CUDA error: out of memory"), "oom")
        self.assertEqual(classify_failure("internal error"), "server_error")

    def test_response_body_reads_the_last_exchange_of_the_client(self):
        class Client:
            last_exchange = None

        client = Client()
        self.assertEqual(response_body(client), "")
        with tempfile.TemporaryDirectory() as tmp:
            client.last_exchange = tmp
            self.assertEqual(response_body(client), "")  # 交换目录里还没有 response.raw
            (Path(tmp) / "response.raw").write_bytes("本文".encode() + b"\xff")
            self.assertTrue(response_body(client).startswith("本文"))


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

    def test_non_loopback_url_is_refused(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            LlamaClient("http://example.com:8081")



if __name__ == "__main__":
    unittest.main()
