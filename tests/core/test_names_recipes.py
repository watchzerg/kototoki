"""专名建表配方 `q3-names-v3` 的身份钉子：提示、schema 与整份配方的 sha256 写死在这里，并与基线 Q3 的
`names-strata-v4` 对照（ADR-0021、ADR-0022、ADR-0026、ADR-0028）。

`SYSTEM_PROMPT_SHA256`、`RESPONSE_SCHEMA_SHA256` 取自 2026-10-19 的 `archive/2026-11-18-pre-research-restructure:experiments/name_consistency/build_table.py`
（冻结的研究期实现，ADR-0013）。`Q3_BUILD_HASH` 是 ADR-0021 记录的 `names-strata-v4` hash：用产品配方的四块
（`build`、`model`、`runtime`、`request`），把 ADR-0026 放宽的三项（`V4_LIMITS`）换回 v4 的值、去掉 ADR-0028 新增的
`retry_on`（`v4_build_block`），再加上研究侧的两个说明字段拼回 v13 `s1_recipe("v4")` 的形状，hash 必须相等，这证明
产品建表块与基线只差这四项。改动提示、schema 或任何请求参数须出新配方名，并同时更新 hash 钉子。
"""

from __future__ import annotations

import json
import unittest

from kototoki import strata
from kototoki.artifacts import sha256_bytes
from kototoki.names import recipes, table
from kototoki.recipes import recipe_hash
from kototoki.translate import recipes as translate_recipes

SYSTEM_PROMPT_SHA256 = "d8e16c0441b611129ba2bcab11a9a41ae7afe53bf1632d56ae9740b7f905dd78"
RESPONSE_SCHEMA_SHA256 = "3004d26cef032d99f1088fcae1fc0e093b689b373490e633f6c6dcfad23117ff"
BUILD_HASH = "d57ed0c6715f63fcb32bb034db03decf02650215af62c13ba95ae7bcdbcf33d7"  # q3-names-v2 为 2dbd324e…，v1 为 d3317926…
# `names-strata-v4` 的三项（ADR-0021）；产品自 ADR-0026 起为 16384、49152、32256。
V4_LIMITS = {"max_tokens": 8192, "context": 24576, "prompt_budget": 15872}
# ADR-0028 起产品建表块独有、`names-strata-v4` 没有的键（v4 把空表当不合格重试）。
PRODUCT_ONLY_KEYS = ("retry_on",)


def v4_build_block(build: dict) -> dict:
    """产品建表块换回 `names-strata-v4` 的建表块：三项限值换回 v4 的值，去掉产品独有的键。"""
    return {k: v for k, v in build.items() if k not in PRODUCT_ONLY_KEYS} | V4_LIMITS

Q3_BUILD_HASH = "38cb7bcda96534db70fb5823c05330cd212057058c381e88cadf756f26d308d0"
# v13 `s1_recipe("v4")` 里研究侧自己的说明字段（产品配方不含）；文字照抄，改动即与 ADR-0021 的 hash 不符。
# `endpoint` 与名字取自 2026-11-11 的 `archive/2026-11-18-pre-research-restructure:experiments/scene_batching_v6/v13.py`（`COUNT_TOKENS`、`VARIANTS["v4"]["name"]`）。
V13_PROMPT_BUDGET_CHECK = {"endpoint": "/v1/messages/count_tokens", "segments": ["system", "user"], "sum": True,
                           "fallback": "no precheck; usage.prompt_tokens recorded, over budget flagged"}
V13_RETRIES = "build_table again with seed + 2k while it fails; at most attempts requests; first ok kept"


class FrozenPromptTests(unittest.TestCase):
    def test_system_prompt_byte_identical_to_research(self):
        self.assertEqual(sha256_bytes(table.SYSTEM_PROMPT.encode("utf-8")), SYSTEM_PROMPT_SHA256)

    def test_response_schema_identical_to_research(self):
        text = json.dumps(table.RESPONSE_SCHEMA, sort_keys=True, ensure_ascii=False)
        self.assertEqual(sha256_bytes(text.encode("utf-8")), RESPONSE_SCHEMA_SHA256)

    def test_prompt_version_and_sampling(self):
        self.assertEqual(table.PROMPT_VERSION, "build-table-prompt-v5")
        self.assertEqual(table.SAMPLING,
                         {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0.0, "presence_penalty": 1.5})


class BuildRecipeTests(unittest.TestCase):
    def test_hash_pinned(self):
        self.assertEqual(recipes.BUILD_RECIPE_HASH, BUILD_HASH)
        self.assertEqual(recipes.BUILD_RECIPE_HASH, recipe_hash(recipes.BUILD))
        self.assertEqual(recipes.BUILD["name"], "q3-names-v3")

    def test_build_block_model_runtime_and_request_equal_names_strata_v4_except_limits(self):
        build = recipes.BUILD
        v4 = {"name": "names-strata-v4", "build": v4_build_block(build["build"]), "model": build["model"],
              "runtime": build["runtime"], "request": build["request"],
              "prompt_budget_check": V13_PROMPT_BUDGET_CHECK, "retries": V13_RETRIES}
        self.assertEqual(recipe_hash(v4), Q3_BUILD_HASH)

    def test_recipe_embeds_pinned_prompt_and_schema(self):
        build = recipes.BUILD["build"]
        self.assertEqual(build["prompt_sha256"], SYSTEM_PROMPT_SHA256)
        self.assertEqual(build["response_schema_sha256"], RESPONSE_SCHEMA_SHA256)
        self.assertEqual(build["prompt_version"], "build-table-prompt-v5")

    def test_frozen_request_values(self):
        build = recipes.BUILD["build"]
        self.assertEqual((build["max_tokens"], build["reasoning"], build["context"]), (16384, "off", 49152))
        self.assertEqual(build["prompt_budget"], 49152 - 16384 - 512)  # 32256（ADR-0026）
        self.assertEqual((build["attempts"], build["seed_step"], build["retry_on"]), (5, 1, "malformed"))
        self.assertNotIn("model_asset", build)
        self.assertEqual(recipes.BUILD["request"],
                         {"response_format": None, "chat_template_kwargs": {"enable_thinking": False},
                          "model": "qwen3.8-flash-next-iq3_s"})

    def test_runtime_identity_equals_the_translation_recipe(self):
        runtime = recipes.BUILD["runtime"]
        self.assertEqual({k: v for k, v in runtime.items() if k != "kv"}, translate_recipes.RECIPE["runtime"])
        self.assertEqual(runtime["kv"], "int8")
        self.assertEqual((recipes.BUILD["model"], runtime["strata"], runtime["engine_build"], runtime["launch"]),
                         (strata.MODEL, strata.STRATA_VERSION, strata.STRATA_ENGINE_BUILD, strata.STRATA_LAUNCH))
        self.assertEqual(runtime["resolved"], strata.STRATA_RESOLVED)
        self.assertIsNot(runtime["resolved"], strata.STRATA_RESOLVED)

    def test_normalize_constants(self):
        normalize = recipes.BUILD["build"]["normalize"]
        self.assertEqual((normalize["max_forms"], normalize["max_items"], normalize["max_zh_len"],
                          normalize["max_ja_len"], normalize["min_high_person_cues"]), (12, 8, 12, 20, 3))

    def test_changing_a_value_changes_the_hash(self):
        changed = {**recipes.BUILD, "build": {**recipes.BUILD["build"], "attempts": 3}}
        self.assertNotEqual(recipe_hash(changed), recipes.BUILD_RECIPE_HASH)
        honorific = dict(recipes.BUILD["build"]["normalize"]["honorific"], sha256="0" * 64)
        normalize = {**recipes.BUILD["build"]["normalize"], "honorific": honorific}
        changed = {**recipes.BUILD, "build": {**recipes.BUILD["build"], "normalize": normalize}}
        self.assertNotEqual(recipe_hash(changed), recipes.BUILD_RECIPE_HASH)
        changed = {**recipes.BUILD, "runtime": {**recipes.BUILD["runtime"], "kv": "f16"}}
        self.assertNotEqual(recipe_hash(changed), recipes.BUILD_RECIPE_HASH)


if __name__ == "__main__":
    unittest.main()
