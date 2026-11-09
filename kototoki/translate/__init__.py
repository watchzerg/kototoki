"""翻译子系统：对编排器只暴露 `plan`／`TranslatePlan`（run 目录、期望身份、是否需要模型）、`translate_document`
与产品配方 hash `RECIPE_HASH`。Strata 的生命周期与共享 session 在中间层 `kototoki.strata`（ADR-0022），由编排器持有、
传给 `translate_document`；`Session` 在此只是过渡期的再导出，编排改用 `kototoki.strata.Session` 后删除。

`recipes`（Q2 规则的产品配方 `q2-degrade-v1`）、`batching`、`degrade`、`generate` 是内部实现；编排器不导入它们。
`strata` 子模块只再导出 `kototoki.strata` 给研究侧既有导入路径。子系统不取 GPU 锁、不做时间换算。
见 docs/architecture/modules/translation-subsystem.md 与 ADR-0019、ADR-0022。
"""

from kototoki.strata import Session

from .generate import TranslateError, TranslatePlan, TranslateResult, plan, translate_document
from .recipes import RECIPE_HASH

__all__ = ["RECIPE_HASH", "Session", "TranslateError", "TranslatePlan", "TranslateResult", "plan", "translate_document"]
