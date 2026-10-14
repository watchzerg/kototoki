"""双语合并：按 cue 编号与时间把中文与日文拼成两行，中文在上、日文在下（规格 §1.1、§5.2）。

纯函数，写出由编排器完成。中文译文内的换行替换为空格，保证 `ja-zh.srt` 每条恰好两行；
日文 cue 由 `cues.build_cues` 产出，本身是单行。回退为日文的条目两行相同，照常输出（报告见票据 09）。
"""

from __future__ import annotations

from collections.abc import Mapping

from kototoki.srt import IncompleteTranslationError, SourceDocument, render_srt, validate_translations


def merge(ja_document: SourceDocument, zh_translations: Mapping[str, str]) -> str:
    """沿用日文 cue 的编号与时间行；译文须精确覆盖全部 cue id，否则抛 `IncompleteTranslationError`。"""
    report = validate_translations(ja_document, zh_translations)
    if report["status"] != "complete":
        raise IncompleteTranslationError(report)
    lines = {cue.id: " ".join(zh_translations[cue.id].splitlines()) + "\n" + " ".join(cue.text.splitlines())
             for cue in ja_document.cues}
    return render_srt(ja_document, lines)
