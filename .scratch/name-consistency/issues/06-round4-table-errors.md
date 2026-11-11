# 06 第四轮：建表侧压错名、扩展不吞前置修饰、修表后再评合并统计

Status: resolved
Type: research
Blocked by: 05

## 范围

用户 2026-10-19 裁定（认可孤立单字为默认）。[第三轮](../../../docs/research/2026-10-19-name-consistency-round3.md)剩余有害行的来源是 no-think 表的错名（アンリマユ→安赫尔、マトウ増健→间桐慎二、造剣→言峰绮礼、シンジ→士郎 等），现有 no-think 表 confidence 全是 high，无法用门槛过滤。三件事：

1. **建表侧压错名**。提示 v5：confidence 只对"能从作品知识确定通行中文译名"的条目给 high；靠音译推断、说不出角色身份、ASR 碎片拼出来的条目给 medium／low；程序兜底：person 条目 evidence 少于 3 条 cue 时 high 降为 medium。重建四部 no-think 表（GPU，每部约 1 分钟）。两种用法对比：`--min-confidence high`（medium 默认跳过）与 `--weak-name-check`（非 high 条目要求其 zh 在译文里至少出现一次，否则跳过；区别于第二轮放弃的强校验）。
2. **扩展不吞前置修饰词**：查清 HF3-w0 [246][253] "笨蛋伊莉亚"→"伊莉雅"（`--pool-by-target` 下）与"如果白"→"士郎"为什么通过了 EXTEND_SHARE，最小修改。
3. **修表后再评 `--pool-by-target`**。

评估：四部 × {旧表默认（第三轮参照）, 新表 low, 新表 high, 新表 weak-check, 新表 high＋pool, 新表 weak＋pool}；覆盖率、Opus 逐行评审新增行、盲序成对判分新增 cue。

## 完成标准

- 剩余有害行中来自表错的清零或给出原因；`--pool-by-target` 在修表后的有害率 ≤4% 则采纳为默认。
- 第四轮报告入 `docs/research/`，登记索引；默认参数按结果定。

## 文件所有权

`build_table.py`、`test_build_table.py`（建表 agent）；`apply_table.py`、`test_apply_table.py`（替换 agent）；GPU 建表、评估驱动、报告与票据（主 agent）。

## Answer

报告：[第四轮](../../../docs/research/2026-10-19-name-consistency-round4.md)。65 项测试过；v5 表在 `.local/name-consistency/09-round4-tables/`（`-v5r` 为形状过滤后），矩阵在 `10-round4/`、`11-round4r/`。

- 建表侧：提示 v5 让次要角色得到 medium，但有害条目全是 high；`--min-confidence high` 与 `--weak-name-check` 输出相同，各拦 5 行无害、0 行有害。错名在 v4／v5 之间换了一批（安赫尔／间桐慎二 → 时臣／真嗣／安徒生·麦），是采样级不稳定。
- 扩展不吞前置修饰：已修（弱候选不得吞更强落点；弱落点当修饰词；第二遍起剥常用词），默认输出不变。
- `--pool-by-target` 在 v5 表上 8.2% 有害（多出的 6 行全是表错放出），不采纳。
- 完成标准：表错未清零（换了一批）；pool 未达 4%。默认不变。新增兜底：evidence<3 降级、zh 形状过滤、`--renormalize`。
