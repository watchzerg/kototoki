"""专名建表配方的身份钉子：提示、schema 与整份配方的 sha256 写死在这里，不导入 experiments。

`SYSTEM_PROMPT_SHA256`、`RESPONSE_SCHEMA_SHA256` 取自 2026-10-19 的 `experiments/name_consistency/build_table.py`
（冻结的研究期实现，ADR-0013）：提示取 `SYSTEM_PROMPT` 的 UTF-8 字节，schema 取
`json.dumps(RESPONSE_SCHEMA, sort_keys=True, ensure_ascii=False)` 的 UTF-8 字节。改动提示或 schema 须出新版本，
并同时更新配方 hash 钉子。
"""

from __future__ import annotations

import json
import unittest

from kototoki.artifacts import sha256_bytes
from kototoki.names import recipes, table
from kototoki.recipes import recipe_hash

SYSTEM_PROMPT_SHA256 = "d8e16c0441b611129ba2bcab11a9a41ae7afe53bf1632d56ae9740b7f905dd78"
RESPONSE_SCHEMA_SHA256 = "3004d26cef032d99f1088fcae1fc0e093b689b373490e633f6c6dcfad23117ff"
BUILD_HASH = "5b8d1b76da757bb26aa3d3fb894c1963935a308b6ef4eb7c75edeaa2d44c9e50"
APPLY_HASH = "5c795c35ff811bd867b6f1bedb0fcc4551eb2eb638e0bdbcfc5623350c227442"


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

    def test_recipe_embeds_pinned_prompt_and_schema(self):
        self.assertEqual(recipes.BUILD["prompt_sha256"], SYSTEM_PROMPT_SHA256)
        self.assertEqual(recipes.BUILD["response_schema_sha256"], RESPONSE_SCHEMA_SHA256)
        self.assertEqual(recipes.BUILD["prompt_version"], "build-table-prompt-v5")

    def test_frozen_request_values(self):
        build = recipes.BUILD
        self.assertEqual((build["max_tokens"], build["reasoning"], build["context"]), (4096, "off", 20480))
        self.assertEqual(build["prompt_budget"], 20480 - 4096 - 512)
        self.assertEqual((build["attempts"], build["seed_step"]), (2, 1))
        self.assertEqual(build["model_asset"], {
            "file": "Qwen3.8-27B-UD-IQ3_S.gguf", "size": 12040883104,
            "sha256": "d847e2c1e4aa276e4b7b8e9ad7628050e61e165d49ab995407bc36677a6f3864"})

    def test_normalize_constants(self):
        normalize = recipes.BUILD["normalize"]
        self.assertEqual((normalize["max_forms"], normalize["max_items"], normalize["max_zh_len"],
                          normalize["max_ja_len"], normalize["min_high_person_cues"]), (12, 8, 12, 20, 3))

    def test_changing_a_value_changes_the_hash(self):
        changed = {**recipes.BUILD, "attempts": 3}
        self.assertNotEqual(recipe_hash(changed), recipes.BUILD_RECIPE_HASH)
        honorific = dict(recipes.BUILD["normalize"]["honorific"], sha256="0" * 64)
        changed = {**recipes.BUILD, "normalize": {**recipes.BUILD["normalize"], "honorific": honorific}}
        self.assertNotEqual(recipe_hash(changed), recipes.BUILD_RECIPE_HASH)


class ApplyRecipeTests(unittest.TestCase):
    def test_hash_pinned(self):
        self.assertEqual(recipes.APPLY_RECIPE_HASH, APPLY_HASH)
        self.assertEqual(recipes.APPLY_RECIPE_HASH, recipe_hash(recipes.APPLY))

    def test_frozen_default_path(self):
        apply = recipes.APPLY
        self.assertEqual(apply["rules"], {
            "extend_to_full_name": True, "isolated_singles": True, "name_check": False, "weak_name_check": False,
            "pool_by_target": False, "bigram_isolation": False, "iterate": 1, "min_confidence": "low"})
        self.assertEqual((apply["min_support"], apply["min_ratio"], apply["min_share"], apply["max_extend"],
                          apply["extend_share"], apply["ngram"]), (2, 0.8, 0.04, 6, 0.5, [2, 6]))
        self.assertTrue(apply["skip_fallback_cues"])

    def test_changing_a_constant_changes_the_hash(self):
        self.assertNotEqual(recipe_hash({**recipes.APPLY, "min_ratio": 0.7}), recipes.APPLY_RECIPE_HASH)
        boundary = recipes.APPLY["boundary_chars"] + "啦"
        self.assertNotEqual(recipe_hash({**recipes.APPLY, "boundary_chars": boundary}), recipes.APPLY_RECIPE_HASH)


class NamesServerTests(unittest.TestCase):
    def test_spec_joins_server_constants_and_model_asset(self):
        from kototoki.names import NAMES_SPEC
        server = recipes.NAMES_SERVER
        self.assertEqual(NAMES_SPEC.stage, "names")
        self.assertEqual(NAMES_SPEC.model_asset,
                         {"repo": server["repo"], "revision": server["revision"], **recipes.BUILD["model_asset"]})
        self.assertEqual((NAMES_SPEC.candidate, NAMES_SPEC.layers, NAMES_SPEC.context, NAMES_SPEC.extra_args,
                          NAMES_SPEC.min_free_mib, NAMES_SPEC.load_timeout_s),
                         (server["candidate"], server["layers"], server["context"], server["extra_args"],
                          server["min_free_mib"], server["load_timeout_s"]))

    def test_server_constants(self):
        server = recipes.NAMES_SERVER
        self.assertEqual((server["candidate"], server["repo"], server["revision"]), (
            "qwen3.8-27b-ud-iq3_s", "unsloth/Qwen3.8-27B-GGUF", "4ca720788d1e01f1bff70c033e0d0028fd02e502"))
        self.assertEqual((server["layers"], server["context"], server["min_free_mib"], server["load_timeout_s"]),
                         (99, recipes.BUILD["context"], 13000, 180))
        self.assertEqual(server["extra_args"],
                         ("-b", "512", "-ub", "512", "-fa", "on", "--jinja", "--reasoning", "off"))


if __name__ == "__main__":
    unittest.main()
