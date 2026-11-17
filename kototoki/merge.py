"""双语合并：按 cue 编号与时间把中文与日文拼成两行，中文在上、日文在下（规格 §1.1、§5.2）。

纯函数，写出由编排器完成。中文译文内的换行替换为空格，保证 `ja-zh.srt` 每条恰好两行；
日文 cue 由 `cues.build_cues` 产出，本身是单行。译文为 `None` 的 cue 不出中文，只输出日文一行（ADR-0029）。

模块页：docs/architecture/modules/translation-subsystem.md。
"""

from __future__ import annotations

from collections.abc import Mapping

from kototoki.srt import IncompleteTranslationError, SourceDocument, render_srt, validate_translations


def merge(ja_document: SourceDocument, zh_translations: Mapping[str, str | None]) -> str:
    """沿用日文 cue 的编号与时间行；译文须精确覆盖全部 cue id（`None` 算覆盖、表示不出中文），字符串须非空且
    不含空行，否则抛 `IncompleteTranslationError`（报告另带 `untranslated_ids`）。"""
    untranslated = {key for key, value in zh_translations.items() if value is None}
    report = validate_translations(ja_document, {k: v for k, v in zh_translations.items() if v is not None})
    expected = {cue.id for cue in ja_document.cues}
    report["missing_ids"] = [key for key in report["missing_ids"] if key not in untranslated]
    report["unexpected_ids"] = sorted(set(report["unexpected_ids"]) | (untranslated - expected), key=str)
    report["untranslated_ids"] = [cue.id for cue in ja_document.cues if cue.id in untranslated]
    if report["missing_ids"] or report["unexpected_ids"] or report["invalid"]:
        raise IncompleteTranslationError(report | {"status": "partial"})
    ja = {cue.id: " ".join(cue.text.splitlines()) for cue in ja_document.cues}
    lines = {}
    for key, text in ja.items():
        zh = zh_translations[key]
        lines[key] = text if zh is None else " ".join(zh.splitlines()) + "\n" + text
    return render_srt(ja_document, lines)
