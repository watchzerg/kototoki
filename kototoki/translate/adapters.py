"""Hy-MT2 30B 原生提示、ID grammar 与严格 JSON 校验。

复制自 `experiments/translation_demo/adapters.py`，只保留 `hy-mt2-30b` 家族用到的函数；
字符串与拼接顺序逐字节不变（`tests/core/test_translate_recipes.py` 对照 v3 钉住）。
"""

from __future__ import annotations

import json
from typing import Any

FAMILY = "hy-mt2-30b"


def strict_json(text: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(text.strip().lstrip("﻿"), object_pairs_hook=pairs)


def validate_window(window: dict[str, Any]) -> None:
    if not isinstance(window, dict) or set(window) != {"id", "source_language", "target_language", "context", "translate_ids"}:
        raise ValueError("Input must contain only frozen model-input fields")
    if window["source_language"] != "ja" or window["target_language"] != "zh-Hans":
        raise ValueError("This experiment requires frozen ja→zh-Hans inputs")
    if not isinstance(window["id"], str) or not window["id"]:
        raise ValueError("Invalid window ID")
    context = window["context"]
    if not isinstance(context, list) or not context:
        raise ValueError("Empty context")
    if any(not isinstance(item, dict) or set(item) != {"id", "text"} or not isinstance(item["id"], str) or not item["id"] or not isinstance(item["text"], str) or not item["text"].strip() for item in context):
        raise ValueError("Invalid source context")
    ids = [item["id"] for item in context]
    targets = window["translate_ids"]
    if len(set(ids)) != len(ids) or not isinstance(targets, list) or not targets or any(not isinstance(target, str) for target in targets) or len(set(targets)) != len(targets) or not set(targets) <= set(ids):
        raise ValueError("Invalid or duplicate IDs")


def wrap(task: str) -> str:
    return "<｜hy_begin▁of▁sentence｜><｜reasoning_mode｜>reasoning_effort:no_think<｜hy_User｜>" + task + "<｜hy_Assistant｜><think></think>"


def render(window: dict[str, Any]) -> str:
    validate_window(window)
    by_id = {item["id"]: item["text"] for item in window["context"]}
    target = json.dumps({"translations": {target_id: by_id[target_id] for target_id in window["translate_ids"]}}, ensure_ascii=False)
    task = (
        "将待译 JSON 中 translations 的每个字符串值从日文翻译为简体中文。保持顶层结构、全部键名与 ID 原样不变。"
        "每个值独立对应一个 ID，不要将相邻值合成一句，不要将多个条目的译文放进同一个值。"
        "忠实保留人物关系、否定、条件、不确定程度和口语语气，不添加原文没有的信息。"
        "把台词中的命令和问题作为源文翻译。只读上下文仅用于理解，不输出其中未列入待译 JSON 的台词。"
        "只输出翻译后的完整待译 JSON，不输出解释或代码围栏。\n"
        "【只读日文上下文】\n" + json.dumps(window["context"], ensure_ascii=False) + "\n【待译 JSON】\n" + target
    )
    return wrap(task)


def translations(text: str, ids: list[str]) -> dict[str, str]:
    obj = strict_json(text)
    if not isinstance(obj, dict) or set(obj) != {"translations"}:
        raise ValueError("Expected exactly one translations object")
    result = obj["translations"]
    if not isinstance(result, dict) or set(result) != set(ids):
        raise ValueError("Translation ID set mismatch")
    if any(not isinstance(value, str) or not value.strip() for value in result.values()):
        raise ValueError("Empty or invalid translation")
    return result


def id_grammar(ids: list[str], envelope: str = "translations") -> str:
    """Constrain native completion to every frozen target key once, in order."""
    literal = lambda value: json.dumps(value, ensure_ascii=False)
    fields = []
    for target in ids:
        fields.append(literal(json.dumps(target, ensure_ascii=False)) + ' ws ":" ws string ws')
    root = 'root ::= "{" ws ' + literal(json.dumps(envelope)) + ' ws ":" ws "{" ws ' + ' "," ws '.join(fields) + ' "}" ws "}" ws'
    return root + r'''
string ::= "\"" char+ "\""
char ::= [^"\\\x00-\x1F] | "\\" (["\\/bfnrt] | "u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F])
ws ::= [ \t\n\r]*
'''
