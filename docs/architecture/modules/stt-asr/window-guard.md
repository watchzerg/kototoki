---
covers:
  - kototoki/guard.py
---
# STT ASR 子页：整窗守卫

`STT ASR` 的子页：w0 整窗守卫（ADR-0030）的规则、处理结果与 `kototoki.guard` 接口。

## w0 整窗守卫

[ADR-0030](../../../adr/0030-asr-window-plausibility-guard.md)；纯逻辑 `kototoki/guard.py`，壳内 `workers.asr.apply_guard`。w0 转写返回之后、组装文档之前，壳对每个**未失败**的窗口调用 `guard.apply(text, end − start)`。三条规则都在规范化文本（`judge.normalize`：NFKC、去标点与空白）上判定，参数在 `recipes.W0["guard"]`，不是配置项；无法规范化的文字（跨簇 NFKC 组合）三条都不命中，`guard.apply` 返回非破坏性的跳过记录。顺序：

1. **复读 `repeat-strict`**：周期 ≥2 字的单元相邻重复 ≥10 份（同一字符连写按周期 2 计），或 ≥3 字的子串不重叠出现 ≥10 次；且重复部分覆盖该窗规范化文字 ≥50%（覆盖率四舍五入到 4 位小数）。
   - 折叠（`action: collapse`）：在原文上保留覆盖最多的那段相邻重复的第一个单元，删掉其后各次重复所占的原文区间（含夹在其中的标点），其余照抄。
   - 置空（`action: blank`）：折叠后仍命中，或只有非相邻复现命中（没有可折叠的区段）。
2. **语速 `speech-rate`**：对复读处理后（可能已折叠）的文字，规范化字数 ÷ 窗口时长 > 20 字/秒即置空。拦住 Whisper 在极短窗口（几十到几百毫秒）上编出的整句；也保证 MMS（每帧 20 ms）放得下全部字符。
3. **已知幻听句 `hallucination-phrase`**：复读处理后的整窗规范化文字等于名单中的一句（`ご視聴ありがとうございました`、`チャンネル登録よろしくお願いします`、`byH`）即置空。只比整窗，这几句作为长句的一部分不拦。名单是 Whisper large-v3 的固定幻听，随模型而不是随内容；换模型时要重新整理。

第一个置空的规则生效。处理结果：

- 被折叠的段 `text` 换成折叠后的文字，`avg_logprob` 与 trace 里的 tokens 仍是解码原值（因此 tokens 与 `text` 不再对应）。
- 被置空的窗口作为失败窗口追加，原因 `guard:<规则名>`，经 `protocol.fail_window` 把原文（未折叠）移入 `failed_windows`、段文字置空，不进对齐、cue 与翻译。
- 无法规范化跳过（`action: skip`）：保留原文不改写、不记失败、不计入 `guarded_windows`，只写 `guard` trace 并由壳记一行 `WARNING`（不含文字）。
- 三种情况都在该窗 trace 写 `guard`，内容是生效规则或跳过记录，不含文字：复读 `{rule, action, period, copies, removed_raw_chars}`（置空时后三项描述被放弃的折叠，没有可折叠区段时为 `null`／`null`／0）；语速 `{rule, action, chars, duration_s}`；幻听句 `{rule, action, phrase_index}`；跳过 `{rule: "normalize", action: "skip", reason: "normalize_failed"}`。复读折叠后又被语速或幻听句置空时，只记置空的那条。
- 只做后处理：不重解码、不温度回退，不看压缩比、`avg_logprob` 与 `no_speech_prob`。解码抛错的失败窗口不过守卫。x0 引擎不过守卫。
- 进度行与每文件 INFO 行带守卫改动的窗口数（`guarded_windows`／`N guarded`，只计折叠与置空，不计跳过；进度行的计数由编排抄进运行日志的 `[asr] done` 行）；每个被折叠或跳过的窗口各一行 WARNING（只记序号与规则/计数，不含文字），被置空的窗口走失败窗口的 WARNING 行。
- 范围有限：语速正常的长窗口里，名单外的套话与"整窗只转出一句"的漏转不在守卫范围（ADR-0030）。

## 守卫接口

- `kototoki.guard` 属基础层，只导入 `recipes` 与 `judge.normalize`。`guard.REPEAT`、`guard.SPEECH_RATE`、`guard.PHRASES` 是三条规则的规则名与参数（取自 `recipes.W0["guard"]` 的三个子块）。
- `guard.apply(text, duration_s) -> (new_text, record | None)`：按顺序过三条规则；未命中返回原文与 `None`；否则返回生效规则或跳过记录，`action` 为 `collapse` 时 `new_text` 是折叠后的文字，为 `blank` 时调用方应把该窗置空（`new_text` 仍是原文），为 `skip` 时保留原文不置空。`duration_s` 不为正抛 `ValueError`。
- `guard.check_repeat(text) -> bool`、`guard.apply_repeat(text)`：只跑复读规则（`apply` 的第一步，也是与研究实现实时对照的入口）。
- 守卫只处理字符串；改写段文字、写 trace 与失败窗口记账在壳 `workers/asr.py`。

## 代码与验证入口

- 代码：`kototoki/guard.py`；壳内 `workers.asr.apply_guard` 在 `kototoki/workers/asr.py`（[枢纽页](../stt-asr.md#代码与验证入口)）。
- `tests/core/test_guard.py`：复读——10 份命中 9 份不命中、周期 2 的 22 份折叠为 1 份并记 `removed_raw_chars`、只有非相邻复现即置空；整窗——恰好 20 字/秒不置空、超过即置空并记 `speech-rate`、整窗幻听句置空并记 `hallucination-phrase`、复读先于后两条且后两条看折叠后的文字、跨簇 NFKC 返回非破坏性跳过记录。
- `tests/core/test_stt_workers.py` 的 ASR 部分：复读窗口折叠、跨簇 NFKC 跳过各自写 trace 与 WARNING，日志不含文字。
- 测试精简（2026-11-22）后不再有测试覆盖：
  - 复读边界：覆盖率不足一半不命中、单字连写按周期 2、普通与空文本放行、标点夹在重复之间时的原文区间与更长单位前后文保留、折叠后仍命中即置空。
  - 整窗边界：标点不计字数、长句内与名单外的感谢不拦、复读置空优先、时长不为正抛错。
  - 常量与壳：三个规则常量等于配方块、名单已是规范化形式、守卫在基础层不导入 torch、研究样例结果的 sha256 钉子。
  - 壳内：折叠不掉时置空、语速与幻听句置空的 trace、已失败窗口不过守卫、x0 引擎不受守卫、cross 的裁判拿到守卫后的 w0 文字。
