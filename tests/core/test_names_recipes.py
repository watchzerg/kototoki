"""专名建表配方 `q3-names-v3` 的身份钉子：系统提示的 sha256 与整份配方 hash 写死在这里，改动提示或任何请求参数须出新配方名并同时
更新钉子（ADR-0021、ADR-0028）。"""

from __future__ import annotations

import unittest

from kototoki.artifacts import sha256_bytes
from kototoki.names import recipes, table
from kototoki.recipes import recipe_hash

SYSTEM_PROMPT_SHA256 = "d8e16c0441b611129ba2bcab11a9a41ae7afe53bf1632d56ae9740b7f905dd78"
BUILD_HASH = "bcb9bebc5274d88a5f3737559b4ab77afa7278afc6d6196c77aad07b12acd072"


class RecipeIdentityTests(unittest.TestCase):
    def test_system_prompt_is_pinned(self):
        self.assertEqual(sha256_bytes(table.SYSTEM_PROMPT.encode("utf-8")), SYSTEM_PROMPT_SHA256)

    def test_hash_pinned(self):
        self.assertEqual(recipes.BUILD_RECIPE_HASH, BUILD_HASH)
        self.assertEqual(recipes.BUILD_RECIPE_HASH, recipe_hash(recipes.BUILD))
        self.assertEqual(recipes.BUILD["name"], "q3-names-v3")


if __name__ == "__main__":
    unittest.main()
