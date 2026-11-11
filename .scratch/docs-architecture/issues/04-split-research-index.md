# 04 拆调研索引

Status: resolved
Type: task
Blocked by: 03

范围见 [spec §4 票据 04](../spec.md#04-拆调研索引)。

## 执行记录

- `docs/research/INDEX.md` 47,341 → 4,979 字符（318 → 74 行，最长行 736 → 231）。只留规则（8 条）、
  "按主题的现状"表（12 行）、"轮次登记"表（17 行）、子索引链接。
- 时间线原文（120 行）用脚本原样搬到 `docs/research/timeline.md`，只加标题、状态行与一段"何时读本页"。
- 主题目录用脚本按小节搬到 `docs/research/topics/` 的 6 篇子索引，验收记录搬到 `topics/acceptance-records.md`。
  条目文字未改，只把相对链接统一加一层 `../`。
- 四量化报告附录目录的 14 篇 Markdown（13 篇原先未登记，另 1 篇 `reproduction.md` 原先只在时间线里出现）
  登记在 `topics/translation-models.md` 的"Hy30 四量化报告的附录"一节。
- 原索引顶部那段英文（迁入调研的说明）改写成中文规则，含义未变。
- 旧锚点：`#决定与探索时间线` 与 `#翻译后审校与人名专名一致性2026-10-19已结题adr-0013` 被冻结文件引用
  （ADR-0014、ADR-0018、`2026-10-19-asr-pair-oracle.md`、`docs/testing/translation-model-evaluation.md`、
  `experiments/name_consistency/README.md`、一张旧票据），在 INDEX 末尾保留同名小节各一句话。
- 活链接改到新位置：`README.md`、`docs/INDEX.md`、`docs/adr/INDEX.md`（两处）。`AGENTS.md` 的那个链接已在票据 03 去掉。
- 没有代码引用或校验 `docs/research/INDEX.md`。

## Answer

门通过：顶层索引 74 行（≤ 150）、最长行 231 字符（≤ 400）；`just docs-check` 通过。
脚本核对：`docs/research/` 下除索引页与时间线外的 117 篇 Markdown，每篇在 `topics/*.md` 里恰好登记一次（未登记 0、重复 0）。
轮次登记表另外链接各轮报告，属路由，不算第二次登记。子索引的条目是原样搬来的长条目，最长行 742 字符，不受 L1 行长预算约束。
