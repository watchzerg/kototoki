---
covers:
  - kototoki/merge.py
---
# 翻译子系统子页：双语合并

`翻译子系统` 的子页：`ja.srt` 与译文合并为中日两行 `ja-zh.srt` 文本的纯函数 `kototoki.merge`。上级：[翻译子系统](../translation-subsystem.md)。

**合并**（`kototoki.merge.merge(ja_document, zh_translations) -> srt_text`）：纯函数；沿用日文 cue 的编号与时间行，每条两行，中文在上、日文在下；中文与日文内的换行都替换为空格；译文为 `None` 的条目只有日文一行。译文须精确覆盖全部 cue（`None` 算覆盖，只在本层处理；缺失、多余、空串、含空行抛 `IncompleteTranslationError`；文字合法性的判定唯一出处在 `srt.subtitle_text_problem`，回复解析同样调用它）；零条目文档得到空串。

## 代码与验证入口

- 代码：`kototoki/merge.py`。其余翻译模块见[枢纽页](../translation-subsystem.md#代码与验证入口)。
- 测试（core，`mise run test`）：`tests/core/test_merge.py`：中上日下且保留头部、多行译文以空格连接、`None` 只输出日文一行、零条目得空串、缺失译文抛错。
- 测试精简（2026-11-22）后不再有测试覆盖：`merge` 的译文与日文相同时两行照留、合并结果回解析条数、多出的译文与空串译文抛错、`None` 仍须其余 id 齐全且 id 已知。
