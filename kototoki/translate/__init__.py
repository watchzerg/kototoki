"""翻译子系统：对编排器只暴露 `plan`／`TranslatePlan`（run 目录、期望身份、是否需要模型）、`translate_document`、
`Session` 与产品配方 hash `RECIPE_HASH`。

`server`、`client`、`batching`、`generate`、`procs` 是内部实现；编排器不导入它们，也看不到 llama-server。
子系统不取 GPU 锁、不做时间换算。见 docs/architecture/modules/translation-subsystem.md。
"""

from .generate import Session, TranslateError, TranslatePlan, TranslateResult, plan, translate_document
from .recipes import RECIPE_HASH

__all__ = ["RECIPE_HASH", "Session", "TranslateError", "TranslatePlan", "TranslateResult", "plan", "translate_document"]
