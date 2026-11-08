"""专名配方：建表 `BUILD`／`BUILD_RECIPE_HASH`，以及建表 server 的参数 `NAMES_SERVER`。

值全部来自 `names.table`（提示、采样、schema、归一常量）与 ADR-0014 冻结的最佳已知配置；改动 `BUILD` 任何一项即
得到新的 `BUILD_RECIPE_HASH`，已有 `name-table.json` 按产物契约失效重建。发布时替换已删除（ADR-0019）：表只经翻译
注入使用，注入规则归翻译子系统。`tests/core/test_names_recipes.py` 钉住提示、schema 与配方的 sha256。

`NAMES_SERVER` 只是普通字典常量，字段对应 llama-server 的 `ServerSpec`；`kototoki.names` 把它与
`BUILD["model_asset"]` 接成 `NAMES_SPEC`，本模块不导入 `kototoki.llama_server`。
"""

from __future__ import annotations

import json
from typing import Any

from kototoki.artifacts import object_hash, sha256_bytes
from kototoki.recipes import recipe_hash

from . import table

BUILD: dict[str, Any] = {
    "prompt_version": table.PROMPT_VERSION,
    "prompt_sha256": sha256_bytes(table.SYSTEM_PROMPT.encode("utf-8")),
    "sampling": dict(table.SAMPLING),
    "response_schema_sha256": sha256_bytes(
        json.dumps(table.RESPONSE_SCHEMA, sort_keys=True, ensure_ascii=False).encode("utf-8")),
    "max_tokens": table.MAX_TOKENS,
    "reasoning": "off",
    "context": table.CONTEXT_SIZE,
    # system+user 两段提示的 token 总上限（context − max_tokens − 512 余量，余量留给 chat 模板与控制 token）。
    "prompt_budget": table.PROMPT_BUDGET,
    "normalize": {
        "zh_shape": table.ZH_SHAPE.pattern,
        "max_zh_len": table.MAX_ZH_LEN,
        "max_forms": table.MAX_FORMS,
        "max_items": table.MAX_ITEMS,
        "min_high_person_cues": table.MIN_HIGH_PERSON_CUES,
        # 称呼词黑名单：版本标签加词表与前后缀的哈希，改词表即改配方。
        "honorific": {"version": table.HONORIFIC_VERSION,
                      "sha256": object_hash([table.HONORIFIC_JA, table._HONORIFIC_PREFIXES,
                                             table._HONORIFIC_SUFFIXES])},
        "ja_shape": table.JA_SHAPE.pattern,
        "max_ja_len": table.MAX_JA_LEN,
        "ja_hiragana_prefixes": table._JA_HIRAGANA_PREFIXES,
        "ja_hiragana_suffixes": table._JA_HIRAGANA_SUFFIXES,
        "de_next_to_katakana": table._DE_NEXT_TO_KATAKANA.pattern,
    },
    "attempts": table.ATTEMPTS,
    "seed_step": table.SEED_STEP,
    "model_asset": {
        "file": "Qwen3.8-27B-UD-IQ3_S.gguf",
        "size": 12040883104,
        "sha256": "d847e2c1e4aa276e4b7b8e9ad7628050e61e165d49ab995407bc36677a6f3864",
    },
}
BUILD_RECIPE_HASH = recipe_hash(BUILD)

NAMES_SERVER: dict[str, Any] = {
    "candidate": "qwen3.8-27b-ud-iq3_s",
    "repo": "unsloth/Qwen3.8-27B-GGUF",
    "revision": "4ca720788d1e01f1bff70c033e0d0028fd02e502",
    "layers": 99,
    "context": table.CONTEXT_SIZE,
    "extra_args": ("-b", "512", "-ub", "512", "-fa", "on", "--jinja", "--reasoning", "off"),
    "min_free_mib": 13000,
    "load_timeout_s": 180,
}
