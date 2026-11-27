"""`kototoki.names` 对编排器的接口：`build_document` 在共享 Strata session 上建表、错误映射，以及请求体与 seed 序列的
sha256 钉子（取自研究侧 v13 `NamesClient`＋`build_one`，基线 Q3 的 `names-strata-v4`）。

共享 session 用真实的 `kototoki.strata.Session`，Strata 服务（共享的 `tests/core/strata_fakes.py`）与 HTTP 客户端（`client_factory`）是假实现
（`server_factory`／`client_factory` 接缝），不起 Strata、不加载模型。
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from typing import Any
import unittest
from urllib.error import HTTPError

from kototoki import names
from kototoki.names import table
from kototoki.srt import parse_srt
from kototoki.strata import MODEL, Session, StrataRefused
from tests.core.strata_fakes import StrataHarness

SRT = "1\n00:00:01,000 --> 00:00:02,000\nシロウが来た\n\n2\n00:00:03,000 --> 00:00:04,000\nシロウだ\n"
REPLY = {"work_guess": None, "entries": [{
    "entity_ja": "シロウ", "kind": "person", "confidence": "medium", "zh": "士郎",
    "forms": [{"ja": "シロウ", "zh": "士郎"}], "zh_variants": [], "evidence": [1, 2]}]}
GOOD = json.dumps(REPLY, ensure_ascii=False)


def reply(content: str = GOOD, finish: str = "stop", prompt_tokens: int = 20) -> dict[str, Any]:
    return {"choices": [{"finish_reason": finish, "message": {"content": content}}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": 30}}


def http_error(code: int = 500) -> HTTPError:
    error = HTTPError("http://127.0.0.1:8080/x", code, "error", {}, io.BytesIO(b""))
    error.close()  # 产品的 LocalClient 读完正文即关；伪造的错误同样先关，code 与 str 不受影响
    return error


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


class Harness(StrataHarness):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.clients: list[dict[str, Any]] = []
        self.bodies: list[str] = []         # 发出的建表请求体（JSON 文本）
        self.count_bodies: list[str] = []   # 发出的 count_tokens 请求体（JSON 文本）
        self.replies: list[Any] = [reply()]
        self.error_raw: str | None = None
        self.count_result: Any = None       # None：正常计数；Exception：抛出；dict：原样返回

    def session(self) -> Session:
        def client_factory(url: str, *, timeout: float, trace_dir: Path) -> FakeClient:
            return FakeClient(self, url, timeout, trace_dir)

        return super().session(client_factory)


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
        self.assertEqual((client["url"], client["timeout"]), ("http://127.0.0.1:8080/#1", 1800.0))
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
        self.assertEqual((body["seed"], body["max_tokens"], body["model"]), (7, 16384, MODEL))
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

    def test_http_error_without_oom_text_is_server_error(self) -> None:
        self.h.replies = [http_error(500)]
        self.h.error_raw = '{"error": "internal failure"}'
        with self.h.session() as session:
            with self.assertRaisesRegex(names.NamesError, r"^HTTP 500 \(server_error\)"):
                names.build_document(self.work, self.doc, session, 7)
            self.assertEqual(self.h.events, ["start:1", "stop:1"])

    def test_refused_strata_fails_this_and_every_later_document(self) -> None:
        self.h.start_failures = [StrataRefused("another Strata launch is serving")]
        with self.h.session() as session:
            with self.assertRaisesRegex(names.NamesError, "Strata unavailable: another Strata launch"):
                names.build_document(self.work, self.doc, session, 7)
            with self.assertRaisesRegex(names.NamesError, "unavailable for the rest of this batch"):
                names.build_document(self.work, self.doc, session, 7)
        self.assertEqual(len(self.h.servers), 1)  # 第二部没有再碰工厂
        self.assertEqual(self.h.bodies, [])



if __name__ == "__main__":
    unittest.main()
