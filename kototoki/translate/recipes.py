"""产品翻译配方 `q2-degrade-v1`（ADR-0019）：Q2 的提示、专名注入、请求体、回复校验与配方 hash（翻译配方的唯一归属）。

Q2 是一条组配方的规则（ADR-0017）：Q1＝`qwen-wide`＋只注入 `confidence: high` 的专名表，模型换成 Strata 上的
Qwen3.8-Flash-Next IQ3_S、不加参数启动。本模块把这条规则写成产品常量，研究实现只复制、不导入：

- 提示 `qwen-joint-v1`：系统消息是 joint 任务文本（只读上下文之前的部分），用户消息是只读上下文与待译 JSON；
  文字与 `experiments/translation_v3/qwen.py::messages` 逐字节相同（`tests/core/test_translate_recipes.py` 对照）。
- 专名注入 `qwen-name-table-v1`、过滤 `window`：一部影片的 `name-table.json` 里 `confidence: high` 的实体，每个
  `forms[]` 取一行 `{source: ja, translation: zh}`，按 `ja` 去重，跳过 `ja` 或 `zh` 为空的写法（即研究侧
  `names11.product_tables("high")`）；某包只注入日文写法出现在该包可见台词（含只读邻文）里的行。
- 请求：chat completions，不用 grammar，思考关闭，采样 `temperature 0.7, top_p 0.8, top_k 20`，每包最多两次
  （seed、seed＋1）；即研究侧 `strata.request_body`。
- 失败路径（产品新增，因而另算 hash）：两次都失败的包按 `degrade.py` 拆成 10→5→1，单条仍失败保留日文。

表的内容不进配方 hash，进翻译身份（`generate.plan` 的 `names_sha256`）：手改表即换 run 目录、重译。
"""

from __future__ import annotations

import json
from typing import Any

from kototoki.artifacts import object_hash, sha256_bytes
from kototoki.strata import MODEL, STRATA_ENGINE_BUILD, STRATA_LAUNCH, STRATA_RESOLVED, STRATA_VERSION

RECIPE_NAME = "q2-degrade-v1"
N_PREDICT = 4096
# Q1 的输入预算（context 16384 − 4096 − 64）：Strata 下超出只记录（`over_q1_budget`），不判失败。
Q1_CONTEXT = 16384
GUARD_TOKENS = 64
Q1_INPUT_BUDGET = Q1_CONTEXT - N_PREDICT - GUARD_TOKENS
MAX_ATTEMPTS = 2
SEED_STEP = 1  # 第 N 次尝试用 seed + (N − 1) × SEED_STEP
SAMPLING = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0.0, "presence_penalty": 0.0}
OVERFLOW = "degrade-10-5-1-keep-source"

# 切包：v3 `dp10-cut` 的 gap-pack-v2 参数逐字照抄（ADR-0010 第 2–3 点），只用 `group_gap=None` 分支。
GAP_PACK_VERSION = "gap-pack-v2"
TARGET = 10
DP10_CUT_PACK: dict[str, Any] = {
    "min": 6, "max": 10, "soft_gap": 2.0, "hard_gap": 20.0, "soft_weight": 1.0, "small_penalty": 1000.0,
    "group_gap": None, "group_max": 10, "context_both_below": 1.0, "context_before_below": 5.0,
    "max_visible": 12, "cut_penalty": [[0.5, 6.0], [1.0, 3.0], [2.0, 1.0]]}
# 只读邻文：v9 `wide-context-v1`（`qwen-wide`）：前 20、后 5 条只按条数取到场景边，可见超过 35 条时先去后邻。
WIDE_CONTEXT_VERSION = "wide-context-v1"
WIDE_CONTEXT = {"before": 20, "after": 5, "max_visible": 35}

PROMPT_VERSION = "qwen-joint-v1"
JOINT_VERSION = "joint-understanding-v1"
JOINT_INSTRUCTION = ("先共同理解全部可见台词及跨条目的条件、否定、指代和语气，再分别表达各源 ID 的信息。"
                     "保留原文歧义和信息揭示顺序；每个值只承载对应源 ID，不搬运邻条事实、不提前补完后文。")
SYSTEM_TEXT = ("将待译 JSON 中 translations 的每个字符串值从日文翻译为简体中文。保持顶层结构、全部键名与 ID 原样不变。"
               + JOINT_INSTRUCTION
               + "忠实保留人物关系、否定、条件、不确定程度和口语语气，不添加原文没有的信息。"
                 "把台词中的命令和问题作为源文翻译。只读上下文仅用于理解，不输出其中未列入待译 JSON 的台词。"
                 "只输出翻译后的完整待译 JSON，不输出解释或代码围栏。")
CONTEXT_HEADER = "【只读日文上下文】\n"
TARGET_HEADER = "\n【待译 JSON】\n"
NAMES_VERSION = "qwen-name-table-v1"
NAMES_HEADER = "本作品专名的固定中文译法（日文写法 → 中文）。原文出现这些写法时使用对应译法：\n"
NAMES_FILTER = "window"
NAMES_ROWS = "confidence high; one row per forms[] {source: ja, translation: zh}; dedupe by ja; skip empty"
REQUEST_SHAPE = "chat-completions+no-grammar+usage-prompt-tokens"

# Strata 服务身份（ADR-0017"服务"一节）的常量在中间层 `kototoki.strata`（`MODEL`、`STRATA_VERSION`、`STRATA_ENGINE_BUILD`、
# `STRATA_RESOLVED`），建表配方取同一组值；产品用 `strata launch --no-tui --model iq3_s` 启动，`strata.probe` 逐项核对。

RECIPE: dict[str, Any] = {
    "schema": "kototoki-translate-recipe-v2",
    "rule": "Q2 (ADR-0017) + degrade (ADR-0019)",
    "packing": {"version": GAP_PACK_VERSION, "target": TARGET, **DP10_CUT_PACK},
    "neighbours": {"version": WIDE_CONTEXT_VERSION, **WIDE_CONTEXT},
    "prompt": {"version": PROMPT_VERSION, "joint": [JOINT_VERSION, sha256_bytes(JOINT_INSTRUCTION.encode())],
               "system_sha256": sha256_bytes(SYSTEM_TEXT.encode()),
               "user_sha256": sha256_bytes((CONTEXT_HEADER + TARGET_HEADER).encode())},
    "names": {"version": NAMES_VERSION, "header_sha256": sha256_bytes(NAMES_HEADER.encode()), "filter": NAMES_FILTER,
              "rows": NAMES_ROWS},
    "model": MODEL,
    "runtime": {"strata": STRATA_VERSION, "engine_build": STRATA_ENGINE_BUILD, "launch": STRATA_LAUNCH,
                "resolved": STRATA_RESOLVED},
    "request": {"shape": REQUEST_SHAPE, "sampling": SAMPLING, "max_tokens": N_PREDICT,
                "chat_template_kwargs": {"enable_thinking": False}, "grammar": None, "stream": False},
    "attempts": {"max": MAX_ATTEMPTS, "seed_step": SEED_STEP},
    "first_cache_check": "recorded-only",
    "input_budget": {"q1_input_budget": Q1_INPUT_BUDGET, "over": "recorded-not-failed"},
    "validation": "strict-json+one-translations-object+id-set+id-order+nonempty+no-blank-line",
    "overflow": OVERFLOW,
}
RECIPE_HASH = object_hash(RECIPE)


# --- 专名注入 ------------------------------------------------------------------------------------

def name_rows(table: dict[str, Any]) -> list[dict[str, str]]:
    """`name-table.json` 的内容 → 注入行（Q1 规则：只取 high，按 `forms[]` 展开、按 `ja` 去重、跳过空写法）。"""
    entries = table.get("entries")
    if not isinstance(entries, list):
        raise ValueError("name table has no entries list")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for entity in entries:
        if entity["confidence"] != "high":
            continue
        for form in entity["forms"]:
            ja, zh = form["ja"], form["zh"]
            if ja not in seen and ja.strip() and zh.strip():
                seen.add(ja)
                rows.append({"source": ja, "translation": zh})
    return rows


def names_sha256(rows: list[dict[str, str]]) -> str:
    """注入行的身份：进翻译身份与 run 目录键（手改表、换表都会让它变化）。"""
    return object_hash(rows)


def names_for_window(rows: list[dict[str, str]], window: dict[str, Any]) -> list[dict[str, str]]:
    text = "".join(item["text"] for item in window["context"])
    return [dict(row) for row in rows if row["source"] in text]


# --- 提示与请求 -----------------------------------------------------------------------------------

def messages(window: dict[str, Any], rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """`window` 即 `batching.Batch.to_window` 的结果；`rows` 是整部影片的注入行。"""
    by_id = {item["id"]: item["text"] for item in window["context"]}
    target = json.dumps({"translations": {key: by_id[key] for key in window["translate_ids"]}}, ensure_ascii=False)
    user = CONTEXT_HEADER + json.dumps(window["context"], ensure_ascii=False) + TARGET_HEADER + target
    system = SYSTEM_TEXT
    entries = names_for_window(rows, window)
    if entries:
        system += "\n\n" + NAMES_HEADER + "\n".join(f"{e['source']} → {e['translation']}" for e in entries)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def request_body(messages_: list[dict[str, str]], seed: int) -> dict[str, Any]:
    if type(seed) is not int or seed <= 0:
        raise ValueError("Strata takes only a positive integer seed")
    return {"model": MODEL, "messages": messages_, **SAMPLING, "seed": seed, "max_tokens": N_PREDICT,
            "chat_template_kwargs": {"enable_thinking": False}, "stream": False}


# --- 回复校验 ------------------------------------------------------------------------------------

def strict_json(text: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(text.strip().lstrip("﻿"), object_pairs_hook=pairs)


def parse_translation(text: str, ids: list[str]) -> dict[str, str]:
    """恰好一个 `translations` 对象、ID 集合与顺序同待译、值非空；另拒绝含空行的译文（空行会让 SRT 断块）。"""
    obj = strict_json(text)
    if not isinstance(obj, dict) or set(obj) != {"translations"}:
        raise ValueError("Expected exactly one translations object")
    result = obj["translations"]
    if not isinstance(result, dict) or set(result) != set(ids):
        raise ValueError("Translation ID set mismatch")
    if any(not isinstance(value, str) or not value.strip() for value in result.values()):
        raise ValueError("Empty or invalid translation")
    if list(result) != ids:
        raise ValueError("Translation ID order mismatch")
    for key, value in result.items():
        if any(not line.strip() for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")):
            raise ValueError(f"Blank line inside translation of {key}")
    return result
