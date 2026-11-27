---
covers:
  - kototoki/srt.py
---
# 产物契约子页：SRT 解析与渲染

`产物契约` 的子页：SRT 的严格解析、渲染、毫秒取整与字幕文字规则。改 `kototoki/srt.py` 或核对 SRT 读写口径时读本页。上级：[产物契约](../artifact-contract.md)。

## 行为规格


- 解析与渲染复制自 `archive/2026-11-18-pre-research-restructure:experiments/translation_flow/srt.py`，严格性不变（重复编号、坏时间行、非正时长、空文字行报错），但空白输入解析为零条目、零条目渲染为空串。读取容忍 UTF-8 BOM。
- `format_srt_ms([(start_ms, end_ms, text), ...])` 从 1 编号写出整数毫秒条目；时长非正即报错。日文 cue 与内嵌字幕清洗都用它。
- 秒到毫秒由调用方先用 `milliseconds` 取整：`floor(x*1000+0.5)`，不用 `round`。
- 字幕文字规则唯一出处 `subtitle_text_problem`，含翻译回复解析在内共用。
- 时间行四段到整数毫秒是 `time_parts_ms`，解析与内嵌字幕清洗共用；毫秒格式化只有 `srt` 一处实现。
- `write_srt(text, path)` 原子写出；是否允许覆盖现有文件由调用方按发布规则判定。

## 代码与验证入口

- 代码：`kototoki/srt.py`。
- `tests/core/test_srt.py`：毫秒取整为四舍五入而非银行家舍入、编号与时间行格式、畸形输入被严格解析拒绝、渲染保留编号与时间行与多行文字、译文不完整时抛出带报告的错误。
- 测试精简（2026-11-22）后不再有测试覆盖：
  - SRT：空 SRT、`srt_time` 拒绝负数、非正取整时长、空行文字、CRLF 归一、SHA 校验与 BOM 容忍。
