"""专名建表配方 `q3-names-v3`：`BUILD`／`BUILD_RECIPE_HASH`（ADR-0028）。

与基线 Q3 的 `names-strata-v4`（[ADR-0021「Q3 建表」]；`experiments/scene_batching_v6/v13.py` 的 `s1_recipe("v4")`，hash
`38cb7bcd…`）**相同**的是建表块 `build` 里的提示 v5、采样、schema、归一规则、`attempts` 5、`seed_step` 1，以及 `model`、
运行时身份 `runtime`（默认启动及其解析值、kv；v4 还记着 Strata 版本，产品自 ADR-0034 起不记）与请求形状 `request`（无 `response_format`、
`enable_thinking: false`、`model`），取值全部来自 `names.table` 与中间层 `kototoki.strata`；
**不同**的是 ADR-0028「输出上限与提示预算」放宽的三项（`max_tokens` 16384 对 8192、context 49152 对 24576、预算 32256 对 15872）、
ADR-0028「重试与空表」新增的 `retry_on`（只有格式不合格才重试，空表是合法结果；v4 把空表当不合格）、配方名，
以及不含研究侧的说明字段（`prompt_budget_check`、`retries` 文字）与 llama.cpp 的 `model_asset`，所以 hash 不同。
`tests/core/test_names_recipes.py` 钉住 hash，并把三项换回 v4 的值、去掉 `retry_on`、拼回 `names-strata-v4` 核对其 hash。

改动 `BUILD` 任何一项即得到新的 `BUILD_RECIPE_HASH`，已有 `name-table.json` 按产物契约失效重建。发布时替换已删除
（ADR-0029「专名注入」）：表只经翻译注入使用，注入规则归翻译子系统。
"""

from __future__ import annotations

import json
from typing import Any

from kototoki.artifacts import object_hash, sha256_bytes
from kototoki.recipes import recipe_hash
from kototoki.strata import MODEL, STRATA_LAUNCH, STRATA_RESOLVED

from . import table

RECIPE_NAME = "q3-names-v3"
KV = "int8"   # 默认启动的 KV 精度（v13 接入时观测；产品只记进配方，不单独核对）

BUILD: dict[str, Any] = {
    "name": RECIPE_NAME,
    "build": {
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
        # 只有格式不合格（截断、非 JSON、`entries` 不是列表）才换 seed 重试；空表接受（ADR-0028「重试与空表」）。
        "retry_on": table.RETRY_ON,
    },
    "model": MODEL,
    "runtime": {"launch": STRATA_LAUNCH, "resolved": dict(STRATA_RESOLVED), "kv": KV},
    "request": {"response_format": None, "chat_template_kwargs": {"enable_thinking": False}, "model": MODEL},
}
BUILD_RECIPE_HASH = recipe_hash(BUILD)
