"""`kototoki.names` 对编排器的接口：`build_document` 在共享 Strata session 上建表、错误映射，以及请求体与 seed 序列的
sha256 钉子（取自研究侧 v13 `NamesClient`＋`build_one`，基线 Q3 的 `names-strata-v4`；实时对照在
`tests/equivalence/test_names.py`）。

共享 session 用真实的 `kototoki.strata.Session`，Strata 服务与 HTTP 客户端是假实现（`server_factory`／`client_factory`
接缝），不起 Strata、不加载模型。
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from typing import Any
import unittest
from urllib.error import HTTPError, URLError

from kototoki import names
from kototoki.local_client import InfraFailure
from kototoki.names import table
from kototoki.srt import parse_srt
from kototoki.strata import MODEL, Session, StrataRefused

SRT = "1\n00:00:01,000 --> 00:00:02,000\nシロウが来た\n\n2\n00:00:03,000 --> 00:00:04,000\nシロウだ\n"
REPLY = {"work_guess": None, "entries": [{
    "entity_ja": "シロウ", "kind": "person", "confidence": "medium", "zh": "士郎",
    "forms": [{"ja": "シロウ", "zh": "士郎"}], "zh_variants": [], "evidence": [1, 2]}]}
GOOD = json.dumps(REPLY, ensure_ascii=False)


def reply(content: str = GOOD, finish: str = "stop", prompt_tokens: int = 20) -> dict[str, Any]:
    return {"choices": [{"finish_reason": finish, "message": {"content": content}}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": 30}}


def http_error(code: int = 500) -> HTTPError:
    return HTTPError("http://127.0.0.1:8080/x", code, "error", {}, io.BytesIO(b""))


class FakeServer:
    """伪 Strata 服务：`__enter__` 按 harness 的安排成功、拒绝或启动失败。"""

    url = "http://127.0.0.1:8080"
    identity = {"candidate": MODEL}

    def __init__(self, harness: "Harness", runtime_dir: Path, on_pid) -> None:
        self.harness, self.runtime_dir, self.on_pid = harness, runtime_dir, on_pid
        self.number = len(harness.servers) + 1

    def __enter__(self) -> "FakeServer":
        failure = self.harness.start_failures.pop(0) if self.harness.start_failures else None
        if failure is not None:
            self.on_pid(None)
            raise failure
        self.on_pid(1000 + self.number)
        self.harness.events.append(f"start:{self.number}")
        return self

    def __exit__(self, *exc: Any) -> None:
        self.harness.events.append(f"stop:{self.number}")
        self.on_pid(None)


class FakeClient:
    """伪 HTTP 客户端：`chat_completion` 按 `replies` 吐回复（或抛异常），`request` 只接受 count_tokens。"""

    def __init__(self, harness: "Harness", url: str, timeout: float, trace_dir: Path) -> None:
        self.harness = harness
        harness.clients.append({"url": url, "timeout": timeout, "trace_dir": trace_dir})
        self.last_exchange: str | None = None

    def request(self, endpoint: str, data: dict[str, Any], *, trace_label: str | None = None) -> dict[str, Any]:
        assert endpoint == names.COUNT_TOKENS and trace_label == "count", (endpoint, trace_label)
        self.harness.count_bodies.append(json.dumps(data, ensure_ascii=False))
        if isinstance(self.harness.count_result, Exception):
            raise self.harness.count_result
        if isinstance(self.harness.count_result, dict):
            return self.harness.count_result
        return {"input_tokens": 10}

    def chat_completion(self, body: dict[str, Any]) -> dict[str, Any]:
        self.harness.bodies.append(json.dumps(body, ensure_ascii=False))
        item = self.harness.replies.pop(0)
        if isinstance(item, Exception):
            if self.harness.error_raw is not None:
                exchange = self.harness.root / "exchange"
                exchange.mkdir(exist_ok=True)
                (exchange / "response.raw").write_text(self.harness.error_raw, encoding="utf-8")
                self.last_exchange = str(exchange)
            raise item
        return item


class Harness:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.servers: list[FakeServer] = []
        self.clients: list[dict[str, Any]] = []
        self.bodies: list[str] = []         # 发出的建表请求体（JSON 文本）
        self.count_bodies: list[str] = []   # 发出的 count_tokens 请求体（JSON 文本）
        self.events: list[str] = []
        self.pids: list[int | None] = []
        self.start_failures: list[Exception | None] = []
        self.replies: list[Any] = [reply()]
        self.error_raw: str | None = None
        self.count_result: Any = None       # None：正常计数；Exception：抛出；dict：原样返回
        self.config = SimpleNamespace(paths=SimpleNamespace(work_dir=root / "work", input_dir=root / "in"))

    def session(self) -> Session:
        def server_factory(runtime_dir: Path, on_pid) -> FakeServer:
            server = FakeServer(self, runtime_dir, on_pid)
            self.servers.append(server)
            return server

        def client_factory(url: str, *, timeout: float, trace_dir: Path) -> FakeClient:
            return FakeClient(self, url, timeout, trace_dir)

        return Session(self.config, on_server_pid=self.pids.append, server_factory=server_factory,
                       client_factory=client_factory)


class Case(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.h = Harness(Path(tmp.name))
        self.work = self.h.root / "work" / "abc"
        self.doc = parse_srt(SRT)

    def seeds(self) -> list[int]:
        return [json.loads(b)["seed"] for b in self.h.bodies]


class BuildDocumentTests(Case):
    def test_zero_cue_document_does_not_touch_the_session(self) -> None:
        result = names.build_document(self.work, parse_srt(""), None, 7)
        self.assertEqual((result.status, result.attempts, result.payload["entries"]), ("ok", 0, []))
        self.assertEqual(self.h.servers, [])

    def test_builds_through_the_shared_session(self) -> None:
        with self.h.session() as session:
            result = names.build_document(self.work, self.doc, session, 7)
            self.assertIsNotNone(session.server)  # 两阶段共用：建表后不停
        self.assertEqual((result.status, result.attempts), ("ok", 1))
        self.assertEqual([entry["entity_ja"] for entry in result.payload["entries"]], ["シロウ"])
        self.assertEqual(result.payload["build"],
                         {"status": "ok", "reason": None, "prompt_check": "count_tokens", "over_budget_by_usage": False})
        (client,) = self.h.clients
        self.assertEqual((client["url"], client["timeout"]), ("http://127.0.0.1:8080", 1800.0))
        # 交换目录布局不变：`<work_dir>/names/transport/<UTC戳>-<pid>/session-NN`（即 `session.label`）
        self.assertEqual(client["trace_dir"],
                         self.work / "names" / "transport" / session.runtime_root.name / "session-01")
        self.assertEqual(session.label, f"{session.runtime_root.name}/session-01")
        self.assertEqual(self.h.events, ["start:1", "stop:1"])
        self.assertEqual(self.h.pids, [1001, None])
        # 预算检查：system 与 user 两段各作一条 user 消息计数
        messages = table.build_messages(self.doc)
        self.assertEqual(self.h.count_bodies, [json.dumps({"model": MODEL, "messages": [{"role": "user", "content": m["content"]}]},
                                                          ensure_ascii=False) for m in messages])
        body = json.loads(self.h.bodies[0])
        self.assertEqual((body["seed"], body["max_tokens"], body["model"]), (7, 8192, MODEL))
        self.assertNotIn("response_format", body)

    def test_first_attempt_fails_then_the_next_seed_succeeds(self) -> None:
        self.h.replies = [reply(finish="length"), reply("不是 JSON"), reply()]
        with self.h.session() as session:
            result = names.build_document(self.work, self.doc, session, 7)
        self.assertEqual((result.status, result.attempts, self.seeds()), ("ok", 3, [7, 8, 9]))
        self.assertEqual(result.payload["meta"]["seed"], 9)

    def test_five_failures_write_an_empty_table_with_exactly_five_requests(self) -> None:
        self.h.replies = [reply(finish="length")] * 2 + [reply("不是 JSON")] * 3 + [reply()]
        with self.h.session() as session:
            with self.assertLogs("kototoki.names", level="WARNING") as logs:
                result = names.build_document(self.work, self.doc, session, 7)
            self.assertIsNotNone(session.server)  # 终态失败不停 Strata
        self.assertEqual((result.status, result.attempts, self.seeds()), ("failed", 5, [7, 8, 9, 10, 11]))
        self.assertEqual((result.payload["entries"], result.payload["meta"]["attempt"]), ([], 5))
        self.assertEqual(result.payload["build"]["status"], "failed")
        self.assertEqual(len(logs.records), 5)
        self.assertEqual(len(self.h.replies), 1)  # 第 6 个回复没被取走

    def test_count_tokens_unavailable_falls_back_to_no_precheck(self) -> None:
        for broken in (http_error(404), URLError("refused"), {"tokens": 3}, {"input_tokens": "10"}):
            with self.subTest(broken=broken):
                self.h = Harness(self.h.root)
                self.h.count_result = broken
                self.h.replies = [reply(prompt_tokens=table.PROMPT_BUDGET + 1)]
                with self.h.session() as session:
                    with self.assertLogs("kototoki.names", level="WARNING") as logs:
                        result = names.build_document(self.work, self.doc, session, 7)
                self.assertEqual(result.status, "ok")  # 预检跳过，提示照常发送
                self.assertEqual(len(self.h.count_bodies), 1)  # 第二段不再尝试
                self.assertEqual(len(self.h.bodies), 1)
                self.assertEqual(len(logs.records), 1)
                self.assertIn("count_tokens unavailable", logs.records[0].getMessage())
                self.assertTrue(result.payload["build"]["prompt_check"].startswith("skipped ("))
                self.assertTrue(result.payload["build"]["over_budget_by_usage"])  # 只记录，不失败

    def test_over_budget_prompt_is_not_sent(self) -> None:
        self.h.count_result = {"input_tokens": table.PROMPT_BUDGET}
        with self.h.session() as session:
            result = names.build_document(self.work, self.doc, session, 7)
        self.assertEqual((result.status, self.h.bodies, len(self.h.count_bodies)), ("too_long", [], 2))
        self.assertEqual(result.payload["build"]["prompt_check"], "count_tokens")

    def test_http_error_with_oom_body_raises_and_stops_strata(self) -> None:
        self.h.replies = [http_error(500)]
        self.h.error_raw = '{"error": "CUDA error: out of memory"}'
        with self.h.session() as session:
            with self.assertRaisesRegex(names.NamesError, r"^HTTP 500 \(oom\)") as caught, \
                    self.assertLogs("kototoki.names", level="WARNING") as logs:
                names.build_document(self.work, self.doc, session, 7)
            self.assertEqual(logs.records[-1].getMessage(), "[names] stopping Strata after HTTP 500 (oom)")
            self.assertIsNone(session.server)
            self.assertEqual(self.h.events, ["start:1", "stop:1"])
            self.assertNotIn("out of memory", str(caught.exception))  # 正文留在交换目录，不进消息
            self.assertIsNone(session.unavailable)  # 下一部需要模型的影片再启动

    def test_http_error_without_oom_is_a_server_error(self) -> None:
        self.h.replies = [http_error(503)]
        with self.h.session() as session:
            with self.assertRaisesRegex(names.NamesError, r"^HTTP 503 \(server_error\)"):
                names.build_document(self.work, self.doc, session, 7)

    def test_transport_failure_raises_and_the_next_document_restarts(self) -> None:
        self.h.replies = [URLError(ConnectionRefusedError("refused")), reply()]
        with self.h.session() as session:
            with self.assertRaisesRegex(names.NamesError, "transport failure: URLError"), \
                    self.assertLogs("kototoki.names", level="WARNING") as logs:
                names.build_document(self.work, self.doc, session, 7)
            self.assertEqual(logs.records[-1].getMessage(), "[names] stopping Strata after URLError")
            result = names.build_document(self.work, self.doc, session, 7)
        self.assertEqual(result.status, "ok")
        self.assertEqual(self.h.events, ["start:1", "stop:1", "start:2", "stop:2"])
        self.assertEqual(self.h.clients[1]["trace_dir"].name, "session-02")

    def test_refused_strata_fails_this_and_every_later_document(self) -> None:
        self.h.start_failures = [StrataRefused("another Strata launch is serving")]
        with self.h.session() as session:
            with self.assertRaisesRegex(names.NamesError, "Strata unavailable: another Strata launch"):
                names.build_document(self.work, self.doc, session, 7)
            with self.assertRaisesRegex(names.NamesError, "unavailable for the rest of this batch"):
                names.build_document(self.work, self.doc, session, 7)
        self.assertEqual(len(self.h.servers), 1)  # 第二部没有再碰工厂
        self.assertEqual(self.h.bodies, [])

    def test_start_failure_fails_this_document_and_the_next_one_tries_again(self) -> None:
        self.h.start_failures = [InfraFailure("Strata did not become ready within 300 s")]
        with self.h.session() as session:
            with self.assertRaisesRegex(names.NamesError, "Strata failed to start: Strata did not become ready"):
                names.build_document(self.work, self.doc, session, 7)
            self.assertIsNone(session.unavailable)
            result = names.build_document(self.work, self.doc, session, 7)
        self.assertEqual((result.status, self.h.events), ("ok", ["start:2", "stop:2"]))


class V13PinTests(Case):
    """同一份文档、同一串伪回复：产品 `build_document` 发出的建表请求体、count_tokens 请求体、状态、尝试数与表项
    的 sha256 钉死，seed 序列写死。钉值取自 2026-11-11 的研究侧 `experiments.scene_batching_v6.v13`
    `NamesClient`＋`build_one`（`names-strata-v4`）在同一输入上的输出，由 `tests/equivalence/test_names.py` 实时对照。"""

    def run_digest(self, replies: list[dict[str, Any]], seed: int, *, count_error: Exception | None = None) -> str:
        self.h = Harness(self.h.root)
        self.h.replies = list(replies)
        self.h.count_result = count_error
        with self.h.session() as session:
            result = names.build_document(self.work, self.doc, session, seed)
        observed = [self.h.bodies, self.h.count_bodies, result.status, result.attempts, result.payload["entries"]]
        return hashlib.sha256(json.dumps(observed, ensure_ascii=False).encode("utf-8")).hexdigest()

    def test_first_attempt_ok(self) -> None:
        self.assertEqual(self.run_digest([reply()], 20261019),
                         "95fef00e9dba875de4b6c77545023a7989977a434d6e2b3590b36c3257176b1a")
        self.assertEqual(self.seeds(), [20261019])

    def test_two_failures_then_ok(self) -> None:
        self.assertEqual(self.run_digest([reply(finish="length"), reply("不是 JSON"), reply()], 7),
                         "8b76546ce041db0567f157b813d54e88892d62a342bf8b5a434f10443237083d")
        self.assertEqual(self.seeds(), [7, 8, 9])

    def test_five_failures(self) -> None:
        digest = self.run_digest([reply(finish="length")] * 3 + [reply("不是 JSON")] * 2 + [reply()] * 2, 100)
        self.assertEqual(digest, "d07d7dfb21621fcce0c93ab1cd8e2a6053a01c789f01ef9310e6dd24904748bc")
        self.assertEqual(self.seeds(), [100, 101, 102, 103, 104])  # 第 6 次不发请求
        self.assertEqual(len(self.h.replies), 2)

    def test_count_tokens_fallback(self) -> None:
        self.assertEqual(self.run_digest([reply()], 7, count_error=http_error(404)),
                         "854ae7da20aad8b1835fa32d4d33485d3136d5ec883f894afdabad56e2afd24f")
        self.assertEqual(len(self.h.count_bodies), 1)

    def test_request_keys_and_values(self) -> None:
        body = table._request_body(table.build_messages(self.doc), 7)
        self.assertEqual(list(body), ["messages", "temperature", "top_p", "top_k", "min_p", "presence_penalty", "seed",
                                      "max_tokens", "chat_template_kwargs", "stream", "model"])
        self.assertEqual((body["max_tokens"], body["model"], body["chat_template_kwargs"], body["stream"]),
                         (8192, MODEL, {"enable_thinking": False}, False))
        self.assertEqual(MODEL, "qwen3.8-flash-next-iq3_s")
        self.assertEqual((table.MAX_TOKENS, table.CONTEXT_SIZE, table.ATTEMPTS), (8192, 24576, 5))


if __name__ == "__main__":
    unittest.main()
