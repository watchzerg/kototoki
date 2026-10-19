"""专名配方：建表 `BUILD`／`BUILD_RECIPE_HASH`、替换 `APPLY`／`APPLY_RECIPE_HASH`，以及建表 server 的参数 `NAMES_SERVER`。

值全部来自 `names.table`（提示、采样、schema、归一常量）、`names.apply`（替换规则与常量）与 ADR-0013 冻结的最佳
已知配置；改动 `BUILD` 任何一项即得到新的 `BUILD_RECIPE_HASH`，已有 `name-table.json` 按产物契约失效重建；
改动 `APPLY` 即得到新的 `names_apply` 身份，已发布影片下次运行重做替换与发布。`tests/core/test_names_recipes.py`
钉住提示、schema 与两份配方的 sha256。

`NAMES_SERVER` 只是普通字典常量，字段对应 llama-server 的 `ServerSpec`；`kototoki.names` 把它与
`BUILD["model_asset"]` 接成 `NAMES_SPEC`，本模块不导入 `kototoki.llama_server`。
"""

from __future__ import annotations

import json
from typing import Any

from kototoki.artifacts import object_hash, sha256_bytes
from kototoki.recipes import recipe_hash

from . import table
# 逐名导入：包属性 `kototoki.names.apply` 是替换函数（遮住同名子模块），`from . import apply` 取不到模块。
from .apply import (BOUNDARY_CHARS, EDGE_STOP, EXTEND_SHARE, MAX_EXTEND, MIN_RATIO, MIN_SHARE, MIN_SUPPORT, NGRAM_MAX,
                    NGRAM_MIN, SCHEMA as APPLY_SCHEMA, ZH_HONORIFICS)

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

# 替换的默认路径（ADR-0013 冻结）：规则一（统计层落点扩展到整个名字）与孤立单字开，研究期其余开关关、取默认值。
APPLY: dict[str, Any] = {
    "id": "names-apply-v1",
    "schema": APPLY_SCHEMA,
    "rules": {"extend_to_full_name": True, "isolated_singles": True, "name_check": False, "weak_name_check": False,
              "pool_by_target": False, "bigram_isolation": False, "iterate": 1, "min_confidence": "low"},
    # 译文等于日文原文的 cue（翻译回退）不参与锚定、统计与替换。
    "skip_fallback_cues": True,
    "min_support": MIN_SUPPORT,
    "min_ratio": MIN_RATIO,
    "min_share": MIN_SHARE,
    "max_extend": MAX_EXTEND,
    "extend_share": EXTEND_SHARE,
    "ngram": [NGRAM_MIN, NGRAM_MAX],
    "edge_stop": "".join(sorted(EDGE_STOP)),
    "zh_honorifics": list(ZH_HONORIFICS),
    "boundary_chars": "".join(sorted(BOUNDARY_CHARS)),
}
APPLY_RECIPE_HASH = recipe_hash(APPLY)

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
