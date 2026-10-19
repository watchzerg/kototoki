"""`kototoki.names` 对编排器的接口：`Session` 的启动／重启／unavailable 与 `build_document` 的错误映射。

server 与客户端都是假实现（`server_factory`／`client_factory` 接缝），不起 llama-server、不加载模型。
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from typing import Any
import unittest
from urllib.error import HTTPError, URLError

from kototoki import names
from kototoki.llama_server import InfraFailure, ManagedServer
from kototoki.srt import parse_srt

SRT = "1\n00:00:01,000 --> 00:00:02,000\nシロウが来た\n\n2\n00:00:03,000 --> 00:00:04,000\nシロウだ\n"
REPLY = {"work_guess": None, "entries": [{
    "entity_ja": "シロウ", "kind": "person", "confidence": "medium", "zh": "士郎",
    "forms": [{"ja": "シロウ", "zh": "士郎"}], "zh_variants": [], "evidence": [1, 2]}]}


class FakeProcess:
    def __init__(self) -> None:
        self.code: int | None = None

    def poll(self) -> int | None:
        return self.code


class FakeServer:
    def __init__(self, harness: "Harness", runtime_dir: Path, on_pid) -> None:
        self.harness, self.runtime_dir, self.on_pid = harness, runtime_dir, on_pid
        self.number = len(harness.servers) + 1
        self.url = f"http://127.0.0.1:{9000 + self.number}"
        self.process = FakeProcess()

    def __enter__(self) -> "FakeServer":
        failure = self.harness.start_failures.pop(0) if self.harness.start_failures else None
        self.on_pid(1000 + self.number)
        if failure is not None:
            self.on_pid(None)
            raise failure
        self.harness.events.append(f"start:{self.number}")
        return self

    def __exit__(self, *exc: Any) -> None:
        self.harness.events.append(f"stop:{self.number}")
        self.on_pid(None)


class FakeClient:
    def __init__(self, harness: "Harness", url: str, timeout: float, trace_dir: Path) -> None:
        self.harness = harness
        harness.clients.append({"url": url, "timeout": timeout, "trace_dir": trace_dir})
        self.last_exchange: str | None = None

    def tokenize(self, text: str) -> list[int]:
        return [1] * 10

    def chat_completion(self, body: dict[str, Any]) -> dict[str, Any]:
        self.harness.bodies.append(body)
        if self.harness.chat_error is not None:
            error, raw = self.harness.chat_error
            if raw is not None:
                exchange = self.harness.root / "exchange"
                exchange.mkdir(exist_ok=True)
                (exchange / "response.raw").write_text(raw, encoding="utf-8")
                self.last_exchange = str(exchange)
            raise error
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(REPLY, ensure_ascii=False)}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 30}}


class Harness:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.servers: list[FakeServer] = []
        self.clients: list[dict[str, Any]] = []
        self.bodies: list[dict[str, Any]] = []
        self.events: list[str] = []
        self.pids: list[int | None] = []
        self.start_failures: list[Exception | None] = []
        self.chat_error: tuple[Exception, str | None] | None = None
        self.config = SimpleNamespace(paths=SimpleNamespace(output_dir=root / "out", llama_server=root / "x.exe"),
                                      models=SimpleNamespace(names=root / "Qwen3.8-27B-UD-IQ3_S.gguf"),
                                      names=SimpleNamespace(port=8081, seed=7, enabled=True))

    def session(self) -> names.Session:
        def server_factory(runtime_dir: Path, on_pid) -> FakeServer:
            server = FakeServer(self, runtime_dir, on_pid)
            self.servers.append(server)
            return server

        def client_factory(url: str, *, timeout: float, trace_dir: Path) -> FakeClient:
            return FakeClient(self, url, timeout, trace_dir)

        return names.Session(self.config, on_server_pid=self.pids.append, server_factory=server_factory,
                             client_factory=client_factory)


class Case(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.h = Harness(Path(tmp.name))
        self.work = self.h.root / "out" / ".work" / "abc"


class SessionTests(Case):

    def test_runtime_root_is_a_utc_stamp_with_pid(self) -> None:
        session = self.h.session()
        self.assertRegex(session.runtime_root.name, r"^\d{8}T\d{6}Z-\d+$")
        self.assertEqual(session.runtime_root.parent, self.h.root / "out" / ".work" / "names-sessions")

    def test_one_server_serves_the_batch_and_restarts_after_it_exits(self) -> None:
        with self.h.session() as session:
            first = session.ensure_started()
            self.assertIs(session.ensure_started(), first)
            first.process.code = 1  # server 自行退出：下一部影片再启动
            second = session.ensure_started()
            self.assertIsNot(second, first)
            self.assertEqual(second.runtime_dir, session.runtime_root / "session-02")
        self.assertEqual(self.h.events, ["start:1", "stop:1", "start:2", "stop:2"])
        self.assertEqual(self.h.pids, [1001, None, 1002, None])

    def test_at_most_three_starts_per_batch(self) -> None:
        session = self.h.session()
        for _ in range(names.MAX_STARTS):
            session.ensure_started().process.code = 1
        with self.assertRaisesRegex(names.NamesError, "already started 3 times"):
            session.ensure_started()
        self.assertIsNotNone(session.unavailable)
        self.assertEqual(len(self.h.servers), 3)

    def test_start_failure_makes_the_session_unavailable(self) -> None:
        self.h.start_failures = [InfraFailure("Free GPU memory 100 MiB stayed below 13000 MiB")]
        session = self.h.session()
        with self.assertRaisesRegex(names.NamesError, "failed to start: InfraFailure: Free GPU memory"):
            session.ensure_started()
        with self.assertRaisesRegex(names.NamesError, "could not start earlier in this batch"):
            session.ensure_started()
        self.assertEqual(len(self.h.servers), 1)  # 不再尝试启动
        self.assertIsNone(session.server)

    def test_managed_server_uses_names_spec_and_config(self) -> None:
        session = names.Session(self.h.config)
        server = session._managed_server(self.h.root / "rt", lambda pid: None)
        self.assertIsInstance(server, ManagedServer)
        self.assertIs(server.spec, names.NAMES_SPEC)
        self.assertEqual((server.engine, server.model, server.port),
                         (self.h.root / "x.exe", self.h.root / "Qwen3.8-27B-UD-IQ3_S.gguf", 8081))


class BuildDocumentTests(Case):
    def test_zero_cue_document_needs_no_server(self) -> None:
        result = names.build_document(self.work, parse_srt(""), None, 7)
        self.assertEqual((result.status, result.attempts, result.payload["entries"]), ("ok", 0, []))
        self.assertEqual(self.h.servers, [])

    def test_builds_through_the_session_server(self) -> None:
        with self.h.session() as session:
            result = names.build_document(self.work, parse_srt(SRT), session, 7)
        self.assertEqual((result.status, result.attempts), ("ok", 1))
        self.assertEqual([entry["entity_ja"] for entry in result.payload["entries"]], ["シロウ"])
        (client,) = self.h.clients
        self.assertEqual((client["url"], client["timeout"]), (self.h.servers[0].url, 1800.0))
        self.assertEqual(client["trace_dir"],
                         self.work / "names" / "transport" / session.runtime_root.name / "session-01")
        self.assertEqual(self.h.bodies[0]["seed"], 7)

    def test_http_error_with_oom_body_raises_and_stops_the_server(self) -> None:
        error = HTTPError("http://127.0.0.1:9001/v1/chat/completions", 500, "Internal Server Error", {},
                          io.BytesIO(b""))
        self.h.chat_error = (error, '{"error": "CUDA error: out of memory"}')
        with self.h.session() as session:
            with self.assertRaisesRegex(names.NamesError, r"^HTTP 500 \(oom\)") as caught:
                names.build_document(self.work, parse_srt(SRT), session, 7)
            self.assertIsNone(session.server)
            self.assertEqual(self.h.events, ["start:1", "stop:1"])
            self.assertNotIn("out of memory", str(caught.exception))  # 正文留在交换目录，不进消息

    def test_transport_failure_raises_and_next_document_restarts(self) -> None:
        self.h.chat_error = (URLError(ConnectionRefusedError("refused")), None)
        with self.h.session() as session:
            with self.assertRaisesRegex(names.NamesError, "transport failure: URLError"):
                names.build_document(self.work, parse_srt(SRT), session, 7)
            self.h.chat_error = None
            result = names.build_document(self.work, parse_srt(SRT), session, 7)
        self.assertEqual(result.status, "ok")
        self.assertEqual(self.h.events, ["start:1", "stop:1", "start:2", "stop:2"])
        self.assertEqual(self.h.clients[1]["trace_dir"].name, "session-02")


if __name__ == "__main__":
    unittest.main()
