"""专名建表（`kototoki.names`）与研究侧 `experiments.scene_batching_v6.v13`（基线 Q3 的 `names-strata-v4`）的实时对照：
配方块与 hash、请求体、count_tokens 请求与 seed 序列。产品自 ADR-0026 起只在 `max_tokens`／context／提示预算三项上
与 v4 不同：对照时把产品请求体的 `max_tokens` 换成 v13 的值，其余仍须逐字节相同。core 侧只钉字面量与摘要
（`tests/core/test_names_recipes.py`、`tests/core/test_names_session.py`）。"""

from __future__ import annotations

import json
import unittest
from typing import Any

from experiments.scene_batching_v6 import v13
from kototoki import names
from kototoki.names import recipes, table
from kototoki.recipes import recipe_hash
from tests.core.test_names_recipes import Q3_BUILD_HASH, V13_PROMPT_BUDGET_CHECK, V13_RETRIES, V4_LIMITS, v4_build_block
from tests.core.test_names_session import Case, Harness, http_error, reply


def as_v13(body_json: str) -> str:
    """产品建表请求体换回 v13 的 `max_tokens`（ADR-0026 的唯一请求差异），键序不变。"""
    body = json.loads(body_json)
    assert body["max_tokens"] == table.MAX_TOKENS
    body["max_tokens"] = v13.S1_MAX_TOKENS
    return json.dumps(body, ensure_ascii=False)


class BuildRecipeEquivalenceTests(unittest.TestCase):
    def test_build_block_model_runtime_and_request_equal_names_strata_v4_except_limits(self):
        build = recipes.BUILD
        self.assertEqual(V4_LIMITS, {"max_tokens": v13.S1_MAX_TOKENS, "context": v13.S1_CONTEXT,
                                     "prompt_budget": v13.S1_PROMPT_BUDGET})
        v4 = {"name": v13.VARIANTS["v4"]["name"], "build": v4_build_block(build["build"]), "model": build["model"],
              "runtime": build["runtime"], "request": build["request"],
              "prompt_budget_check": {"endpoint": v13.COUNT_TOKENS, "segments": ["system", "user"], "sum": True,
                                      "fallback": "no precheck; usage.prompt_tokens recorded, over budget flagged"},
              "retries": V13_RETRIES}
        self.assertEqual(v13.VARIANTS["v4"]["name"], "names-strata-v4")
        self.assertEqual(recipe_hash(v4), Q3_BUILD_HASH)
        self.assertEqual(v4["prompt_budget_check"], V13_PROMPT_BUDGET_CHECK)  # core 里写死的字面量与 v13 一致


class V13ByteExactTests(Case):
    """同一份文档、同一串伪回复：产品 `build_document` 发出的建表请求与 count_tokens 请求，和研究侧 v13
    `NamesClient`＋`build_one`（`names-strata-v4`）逐字节相同，seed 序列相同。"""

    def v13_run(self, replies: list[dict[str, Any]], seed: int, *, count_error: Exception | None = None
                ) -> tuple[list[str], list[str], Any]:
        chats: list[str] = []
        counts: list[str] = []

        def post(url: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
            if url.endswith(v13.COUNT_TOKENS):
                counts.append(json.dumps(body, ensure_ascii=False))
                if count_error is not None:
                    raise count_error
                return {"input_tokens": 10}
            self.assertTrue(url.endswith("/v1/chat/completions"), url)
            chats.append(json.dumps(body, ensure_ascii=False))
            return replies.pop(0)

        client = v13.NamesClient(post=post, variant="v4")
        result, _record = v13.build_one(self.doc, client, seed)
        return chats, counts, result

    def product_run(self, replies: list[dict[str, Any]], seed: int, *, count_error: Exception | None = None
                    ) -> tuple[list[str], list[str], Any]:
        self.h = Harness(self.h.root)
        self.h.replies = list(replies)
        self.h.count_result = count_error
        with self.h.session() as session:
            result = names.build_document(self.work, self.doc, session, seed)
        return self.h.bodies, self.h.count_bodies, result

    def compare(self, replies: list[dict[str, Any]], seed: int, *, count_error: Exception | None = None) -> None:
        theirs = self.v13_run(list(replies), seed, count_error=count_error)
        ours = self.product_run(list(replies), seed, count_error=count_error)
        self.assertEqual([as_v13(b) for b in ours[0]], theirs[0])  # 建表请求体（JSON 文本，max_tokens 换回 v13）
        self.assertEqual(ours[1], theirs[1])  # count_tokens 请求体
        self.assertEqual((ours[2].status, ours[2].attempts), (theirs[2].status, theirs[2].attempts))
        self.assertEqual(ours[2].payload["entries"], theirs[2].payload["entries"])

    def test_first_attempt_ok(self) -> None:
        self.compare([reply()], 20261019)
        self.assertEqual(self.seeds(), [20261019])
        self.assertEqual(json.loads(as_v13(self.h.bodies[0])),
                         v13.strata_body(table._request_body(table.build_messages(self.doc), 20261019)))

    def test_two_failures_then_ok(self) -> None:
        self.compare([reply(finish="length"), reply("不是 JSON"), reply()], 7)
        self.assertEqual(self.seeds(), [7, 8, 9])

    def test_five_failures(self) -> None:
        self.compare([reply(finish="length")] * 3 + [reply("不是 JSON")] * 2 + [reply()] * 2, 100)
        self.assertEqual(self.seeds(), [100, 101, 102, 103, 104])  # 第 6 次不发请求
        self.assertEqual(len(self.h.replies), 2)

    def test_count_tokens_fallback(self) -> None:
        self.compare([reply()], 7, count_error=http_error(404))
        self.assertEqual(len(self.h.count_bodies), 1)

    def test_request_keys_and_values(self) -> None:
        body = v13.strata_body(table._request_body(table.build_messages(self.doc), 7))
        self.assertEqual(list(body), ["messages", "temperature", "top_p", "top_k", "min_p", "presence_penalty", "seed",
                                      "max_tokens", "chat_template_kwargs", "stream", "model"])
        self.assertEqual((body["max_tokens"], body["model"], body["chat_template_kwargs"], body["stream"]),
                         (v13.S1_MAX_TOKENS, v13.strata.MODEL, {"enable_thinking": False}, False))
        self.assertEqual((table.MAX_TOKENS, table.CONTEXT_SIZE, table.PROMPT_BUDGET), (16384, 49152, 32256))
        self.assertEqual((v13.S1_MAX_TOKENS, v13.S1_CONTEXT, v13.S1_PROMPT_BUDGET), (8192, 24576, 15872))
        self.assertEqual(table.ATTEMPTS, v13.VARIANTS["v4"]["attempts"])


if __name__ == "__main__":
    unittest.main()
